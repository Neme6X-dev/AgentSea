// Scène 3D des agents Jarvis — Three.js WebGL classique (pas WebGPU).
// Réutilise les modèles 3D (personnages + bureau) de "The Delegation"
// par Arturo Paracuellos (unboring.net), CC BY-NC 4.0, usage non commercial.
//
// Choix volontaire : WebGL plutôt que WebGPU. Le rendu WebGPU nécessite un
// vrai GPU matériel et est bloqué par les navigateurs sur les adaptateurs
// logiciels (voir chrome://gpu). WebGL classique tourne partout, y compris
// en rendu logiciel, donc c'est le choix le plus robuste pour ce widget.

import * as THREE from 'three';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
import { DRACOLoader } from 'three/addons/loaders/DRACOLoader.js';
import * as SkeletonUtils from 'three/addons/utils/SkeletonUtils.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

const MODELS_BASE = 'assets/models/';
const DRACO_BASE = 'assets/draco/';

const AGENTS = [
  { name: 'Orchestration', color: 0xb3aeff, poi: 'poi-idle-area-boardroom', anim: 'Wave' },
  { name: 'Conception & Design', color: 0xff8fc7, poi: 'poi-sit_work-1', anim: 'Sit_Work' },
  { name: 'Contenu', color: 0x7fd1ff, poi: 'poi-sit_work-2', anim: 'Sit_Work' },
  { name: 'Gestion & Build', color: 0x8fffb0, poi: 'poi-sit_work-3', anim: 'Sit_Work' },
  { name: 'Qualité & Sécurité', color: 0xffd27f, poi: 'poi-sit_work-4', anim: 'Sit_Work' },
  { name: 'Déploiement', color: 0x7fffe0, poi: 'poi-sit_work-5', anim: 'Sit_Work' },
];

let activeScene = null;

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
  const hemi = new THREE.HemisphereLight(0xdfe6ff, 0x1a1a22, 0.5);
  scene.add(hemi);
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
  const draco = new DRACOLoader();
  draco.setDecoderPath(DRACO_BASE);
  loader.setDRACOLoader(draco);

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

  const mixers = [];
  const clips = characterGltf.animations || [];

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
      if (lname.includes('body')) mat.color = new THREE.Color(agent.color);
      child.material = mat;
    });

    const pos = poiPositions[agent.poi] || new THREE.Vector3((i - 2.5) * 1.3, 0, 2);
    clone.position.copy(pos);
    clone.lookAt(-0.5, pos.y, 0.5);
    scene.add(clone);

    const mixer = new THREE.AnimationMixer(clone);
    const clip = clips.find((c) => c.name === agent.anim) || clips.find((c) => c.name === 'Idle') || clips[0];
    if (clip) mixer.clipAction(clip).play();
    mixers.push(mixer);
  });

  const clock = new THREE.Clock();
  let rafId = null;
  function animate() {
    rafId = requestAnimationFrame(animate);
    const delta = Math.min(clock.getDelta(), 0.1);
    for (const mixer of mixers) mixer.update(delta);
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
    dispose() {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
      controls.dispose();
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
