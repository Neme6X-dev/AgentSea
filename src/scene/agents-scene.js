// Scène 3D des agents Jarvis — Three.js WebGL classique (pas WebGPU).
// Modèles 3D (personnages + bureau) de « The Delegation » par Arturo
// Paracuellos (unboring.net), CC BY-NC 4.0, usage non commercial.
//
// Choix volontaire : WebGL plutôt que WebGPU. Le rendu WebGPU nécessite un vrai
// GPU matériel et est bloqué par les navigateurs sur les adaptateurs logiciels
// (voir chrome://gpu). WebGL classique tourne partout, y compris en rendu
// logiciel, donc c'est le choix le plus robuste pour ce widget.
//
// ORGANISATION (inspirée de « the delegation ») :
//   - agents-pipeline.js : logique d'état (quel agent est idle/working/done).
//   - AgentController     : un agent = une machine à états (crossfade des clips,
//                           highlight, indicateur de complétion). Ne calcule
//                           aucune position/rotation aléatoire.
//   - initAgentsScene     : montage de la scène + boucle de rendu qui LIT le
//                           pipeline et applique l'état à chaque agent.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { createPipeline } from './agents-pipeline.js';

// Chemin absolu : les modèles vivent dans public/ et sont copiés tels quels à la
// racine du build. En relatif ils dépendraient de l'URL de la page qui monte la scène.
//
// Le décodeur Draco, lui, n'est plus vendored : DRACOLoader pointe par défaut sur
// celui livré avec three, que le bundler résout et émet. Une copie manuelle dans
// public/ n'aurait fait que dupliquer ces fichiers et se désynchroniser de three.
const MODELS_BASE = '/assets/models/';

// Chaque agent a une position de base fixe (POI cohérent avec son rôle) et un
// clip d'animation par état. Aucune position n'est recalculée au fil du temps.
const AGENTS = [
  { name: 'Orchestration',       color: 0xb3aeff, poi: 'poi-idle-area-boardroom', seated: false,
    anims: { idle: 'Idle',     working: 'Talk',     done: 'LookAround' } },
  { name: 'Conception & Design', color: 0xff8fc7, poi: 'poi-sit_work-1', seated: true,
    anims: { idle: 'Sit_Idle', working: 'Sit_Work', done: 'Sit_Idle' } },
  { name: 'Contenu',             color: 0x7fd1ff, poi: 'poi-sit_work-2', seated: true,
    anims: { idle: 'Sit_Idle', working: 'Sit_Work', done: 'Sit_Idle' } },
  { name: 'Gestion & Build',     color: 0x8fffb0, poi: 'poi-sit_work-3', seated: true,
    anims: { idle: 'Sit_Idle', working: 'Sit_Work', done: 'Sit_Idle' } },
  { name: 'Qualité & Sécurité',  color: 0xffd27f, poi: 'poi-sit_work-4', seated: true,
    anims: { idle: 'Sit_Idle', working: 'Sit_Work', done: 'Sit_Idle' } },
  { name: 'Déploiement',         color: 0x7fffe0, poi: 'poi-sit_work-5', seated: true,
    anims: { idle: 'Sit_Idle', working: 'Sit_Work', done: 'Sit_Idle' } },
];

const DONE_COLOR = new THREE.Color(0x37d67a);
const IDLE_DOT = new THREE.Color(0x6b7280);
const CENTER = new THREE.Vector3(-0.5, 0, 0.5); // les agents regardent le centre

let activeScene = null;

// Texture partagée pour l'indicateur d'état (pastille douce, générée à la volée,
// aucun asset externe).
function makeDotTexture() {
  const size = 64;
  const canvas = document.createElement('canvas');
  canvas.width = canvas.height = size;
  const ctx = canvas.getContext('2d');
  const g = ctx.createRadialGradient(size / 2, size / 2, 0, size / 2, size / 2, size / 2);
  g.addColorStop(0, 'rgba(255,255,255,1)');
  g.addColorStop(0.55, 'rgba(255,255,255,0.9)');
  g.addColorStop(1, 'rgba(255,255,255,0)');
  ctx.fillStyle = g;
  ctx.beginPath();
  ctx.arc(size / 2, size / 2, size / 2, 0, Math.PI * 2);
  ctx.fill();
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

// Un agent = une machine à états. Transitions animées par crossfade (pas de
// coupure brute), highlight et indicateur pilotés par interpolation (lerp).
class AgentController {
  constructor(root, clips, cfg, dotTexture) {
    this.root = root;
    this.cfg = cfg;
    this.baseColor = new THREE.Color(cfg.color);
    this.state = null;

    // Machine d'animation : une action par état, prêtes à être fondues.
    this.mixer = new THREE.AnimationMixer(root);
    this.actions = {};
    for (const key of ['idle', 'working', 'done']) {
      const clip =
        clips.find((c) => c.name === cfg.anims[key]) ||
        clips.find((c) => c.name === 'Idle') ||
        clips[0];
      if (!clip) continue;
      const action = this.mixer.clipAction(clip);
      action.enabled = true;
      action.setEffectiveWeight(0);
      action.play();
      this.actions[key] = action;
    }
    this.current = null;

    // Matériaux « body » ciblés pour le highlight d'état (emissive).
    this.bodyMats = [];
    root.traverse((child) => {
      if (child.isMesh && child.name.toLowerCase().includes('body')) {
        this.bodyMats.push(child.material);
      }
    });

    // Indicateur d'état flottant (billboard) au-dessus de l'agent.
    this.dot = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: dotTexture, transparent: true, depthWrite: false })
    );
    this.dot.scale.setScalar(0.34);
    this.dot.position.set(0, cfg.seated ? 1.35 : 2.05, 0);
    this.dot.material.opacity = 0;
    root.add(this.dot);

    this.dotColor = IDLE_DOT.clone();
    this.emissiveInt = 0;

    this.setState('idle', true);
  }

  setState(state, immediate = false) {
    if (state === this.state) return;
    this.state = state;
    const next = this.actions[state] || this.actions.idle;
    if (next && next !== this.current) {
      const dur = immediate ? 0 : 0.45;
      next.reset();
      next.setEffectiveWeight(1);
      next.fadeIn(dur);
      next.play();
      if (this.current) this.current.fadeOut(dur);
      this.current = next;
    }
  }

  update(delta, status, time) {
    this.mixer.update(delta);

    // Cibles de highlight/indicateur selon l'état.
    let targetColor;
    let targetOpacity;
    let targetEmissive;
    if (status.state === 'working') {
      const pulse = 0.5 + 0.5 * Math.sin(time * 4.5); // pulsation douce, déterministe
      targetColor = this.baseColor;
      targetOpacity = 0.85;
      targetEmissive = 0.18 + 0.22 * pulse;
    } else if (status.state === 'done') {
      targetColor = DONE_COLOR;
      targetOpacity = 0.95;
      targetEmissive = 0.12;
    } else {
      targetColor = IDLE_DOT;
      targetOpacity = 0.28;
      targetEmissive = 0;
    }

    const k = 1 - Math.pow(0.001, delta); // lerp indépendant du framerate
    this.dotColor.lerp(targetColor, k);
    this.dot.material.color.copy(this.dotColor);
    this.dot.material.opacity += (targetOpacity - this.dot.material.opacity) * k;

    this.emissiveInt += (targetEmissive - this.emissiveInt) * k;
    const emissiveColor = status.state === 'done' ? DONE_COLOR : this.baseColor;
    for (const mat of this.bodyMats) {
      if (!mat.emissive) continue;
      mat.emissive.copy(emissiveColor);
      mat.emissiveIntensity = this.emissiveInt;
    }
  }

  dispose() {
    this.mixer.stopAllAction();
    if (this.dot) {
      this.dot.material.dispose();
      if (this.dot.parent) this.dot.parent.remove(this.dot);
    }
  }
}

export async function initAgentsScene(container) {
  disposeAgentsScene();

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1b22);
  scene.fog = new THREE.Fog(0x1a1b22, 14, 26);

  const camera = new THREE.PerspectiveCamera(42, container.clientWidth / container.clientHeight, 0.1, 100);
  camera.position.set(6.5, 5.5, 8);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  container.innerHTML = '';
  container.appendChild(renderer.domElement);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(-0.5, 1, 0.5);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 4;
  controls.maxDistance = 16;
  controls.maxPolarAngle = Math.PI / 2.05;
  controls.update();

  scene.add(new THREE.AmbientLight(0xffffff, 0.7));
  scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x1a1a22, 0.5));
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.6);
  dirLight.position.set(5, 9, 4);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.set(1024, 1024);
  dirLight.shadow.camera.left = -8;
  dirLight.shadow.camera.right = 8;
  dirLight.shadow.camera.top = 8;
  dirLight.shadow.camera.bottom = -8;
  scene.add(dirLight);

  const loader = new GLTFLoader();
  loader.setDRACOLoader(new DRACOLoader());

  const [officeGltf, characterGltf] = await Promise.all([
    loader.loadAsync(MODELS_BASE + 'office.glb'),
    loader.loadAsync(MODELS_BASE + 'character.glb'),
  ]);

  const office = officeGltf.scene;
  const poiPositions = {};
  office.traverse((child) => {
    if (child.name && child.name.startsWith('poi-')) {
      poiPositions[child.name] = child.position.clone();
    }
    if (child.name === 'navMesh') child.visible = false;
    if (child.isMesh) {
      child.receiveShadow = true;
      child.castShadow = true;
    }
  });
  scene.add(office);

  const clips = characterGltf.animations || [];
  const dotTexture = makeDotTexture();
  const controllers = [];

  AGENTS.forEach((agent, i) => {
    const clone = SkeletonUtils.clone(characterGltf.scene);
    clone.traverse((child) => {
      if (!child.isMesh) return;
      const lname = child.name.toLowerCase();
      if (lname.includes('cap') || lname.includes('headphones')) {
        child.visible = false;
        return;
      }
      child.castShadow = true;
      child.receiveShadow = true;
      const mat = child.material.clone();
      if (lname.includes('body')) {
        mat.color = new THREE.Color(agent.color);
        mat.emissive = new THREE.Color(agent.color);
        mat.emissiveIntensity = 0;
      }
      child.material = mat;
    });

    // Position de base fixe + orientation vers le centre (jamais recalculées).
    const pos = poiPositions[agent.poi] || new THREE.Vector3((i - 2.5) * 1.3, 0, 2);
    clone.position.copy(pos);
    clone.lookAt(CENTER.x, pos.y, CENTER.z);
    scene.add(clone);

    controllers.push(new AgentController(clone, clips, agent, dotTexture));
  });

  // Le pipeline (série) pilote l'état de chaque agent. Poids : Build un peu plus
  // long, Déploiement un peu plus court, pour un rythme crédible.
  const pipeline = createPipeline(
    AGENTS.map((a) => a.name),
    { weights: [1.0, 1.05, 1.05, 1.35, 1.0, 0.9] }
  );

  const clock = new THREE.Clock();
  pipeline.start(clock.getElapsedTime());

  let rafId = null;
  function animate() {
    rafId = requestAnimationFrame(animate);
    const delta = Math.min(clock.getDelta(), 0.1);
    const t = clock.elapsedTime;

    // Rebouclage propre de la séquence tant que la génération n'est pas figée.
    if (pipeline.loop && pipeline.isFinished(t)) pipeline.start(t);

    for (let i = 0; i < controllers.length; i++) {
      const status = pipeline.statusAt(i, t);
      controllers[i].setState(status.state);
      controllers[i].update(delta, status, t);
    }

    controls.update();
    renderer.render(scene, camera);
  }
  animate();

  function onResize() {
    const w = container.clientWidth;
    const h = container.clientHeight;
    if (!w || !h) return;
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    renderer.setSize(w, h);
  }
  const resizeObserver = new ResizeObserver(onResize);
  resizeObserver.observe(container);

  activeScene = {
    pipeline, // exposé pour synchroniser avec le cycle de génération réel
    dispose() {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
      controls.dispose();
      for (const c of controllers) c.dispose();
      dotTexture.dispose();
      renderer.dispose();
    },
  };

  return activeScene;
}

export function disposeAgentsScene() {
  if (activeScene) {
    activeScene.dispose();
    activeScene = null;
  }
}
