// Scène 3D des agents Jarvis — Three.js WebGL classique (pas WebGPU).
//
// Personnages et mobilier : kit KayKit par Kay Lousberg (kaylousberg.com), sous
// CC0 1.0 — domaine public, usage commercial autorisé, aucune attribution exigée.
// Le bureau lui-même est assemblé par code (voir `office-kit.js`).
//
// Ce jeu d'assets remplace « The Delegation » d'Arturo Paracuellos, qui était sous
// CC BY-NC 4.0 : la clause NC interdit l'usage commercial, donc le produit ne pouvait
// pas être vendu tant que ces modèles y figuraient.
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
import { buildNavMesh, projectToNav, findPath, moveOnNav } from './navmesh.js';
import { buildOffice, ROAM_IDS } from './office-kit.js';

// Chemin absolu : les modèles vivent dans public/ et sont copiés tels quels à la
// racine du build. En relatif ils dépendraient de l'URL de la page qui monte la scène.
//
// Le décodeur Draco est copié depuis `three/examples/jsm/libs/draco/gltf/` vers
// `public/assets/draco/`. DRACOLoader ne le résout pas tout seul : sans chemin explicite
// il le cherche à la racine du site et échoue en silence sur un 404, laissant la scène
// noire. Ces fichiers sont chargés à l'exécution par un worker, pas importés par le
// bundler — d'où la copie plutôt qu'un `import`.
const DRACO_BASE = '/assets/draco/';

/**
 * Personnages « Mini Characters » de Kenney (CC0).
 *
 * Un modèle **distinct par agent** : la couleur seule ne suffit pas à reconnaître
 * quelqu'un dans une vue d'ensemble, où les personnages font quelques dizaines de
 * pixels. Une silhouette propre à chacun, elle, se lit immédiatement.
 *
 * Ils remplacent le personnage médiéval du kit KayKit, unique et cloné six fois : tous
 * les agents s'y ressemblaient, et il fallait masquer armes et cape pour le rendre
 * présentable dans un bureau. Ceux-ci sont contemporains, cinq fois plus légers, et
 * apportent `sit`, `walk`, `interact-*` — exactement le vocabulaire d'un poste de travail.
 */
const CHARACTER_BASE = '/assets/kenney/characters/';
/** Hauteur du modèle au repos : sert à le ramener à une taille humaine (~1,7 m). */
const CHARACTER_SCALE = 2.45;

// Chaque agent a un poste de travail (`desk`) où il se rend pour travailler, et
// déambule dans le bureau le reste du temps. `anims` donne le clip joué **à l'arrêt** :
// pendant un déplacement, c'est toujours la marche.
//
// Les noms de clips sont ceux du kit KayKit. Le jeu est plus fourni que celui du
// modèle précédent : on dispose des transitions assis/debout (`Sit_Chair_Down`,
// `Sit_Chair_StandUp`), qui évitent qu'un agent apparaisse assis d'une frame à l'autre.
const AGENTS = [
  { name: 'Orchestration',       role: 'Chef d\'orchestre', color: 0xb3aeff,
    desk: 'desk-1', model: 'character-male-a.glb' },
  { name: 'Conception & Design', role: 'Directeur artistique', color: 0xff8fc7,
    desk: 'desk-2', model: 'character-female-b.glb' },
  { name: 'Contenu',             role: 'Rédacteur', color: 0x7fd1ff,
    desk: 'desk-3', model: 'character-male-c.glb' },
  { name: 'Gestion & Build',     role: 'Développeur', color: 0x8fffb0,
    desk: 'desk-4', model: 'character-female-d.glb' },
  { name: 'Qualité & Sécurité',  role: 'Auditeur', color: 0xffd27f,
    desk: 'desk-5', model: 'character-male-e.glb' },
  { name: 'Déploiement',         role: 'Ops', color: 0x7fffe0,
    desk: 'desk-6', model: 'character-female-f.glb' },
];

/** Clips du pack Kenney, communs à tous les personnages. */
const CLIPS = {
  walk: 'walk',
  stand: 'idle',
  sit: 'sit',
  work: 'interact-right',
  done: 'emote-yes',
};

/** Texte affiché sous le nom quand aucune source réelle ne le fournit. */
const DEFAULT_DETAIL = {
  idle: 'En attente',
  working: 'Au travail…',
  done: 'Terminé',
};

const WALK_SPEED = 1.35;   // m/s — allure de bureau, ni course ni traîne
const ACCEL = 5.5;         // m/s² — démarrages et arrêts progressifs plutôt que par à-coups
const TURN_SPEED = 7;      // rad/s — pivot vers la direction de marche
const ARRIVAL = 0.16;      // distance à laquelle une étape intermédiaire est franchie
const GOAL_ARRIVAL = 0.08; // idem pour le dernier point du chemin, où l'on veut être précis
const SLOW_RADIUS = 0.7;   // distance à laquelle on commence à décélérer vers le but
const AGENT_RADIUS = 0.28; // demi-largeur d'un personnage, retranchée des portails

const PERSONAL_SPACE = 0.9;    // rayon en dessous duquel deux agents s'interpénètrent
const SEPARATION_PASSES = 3;   // relaxations par frame : une seule passe ne résout pas un paquet de 3+
const WALKING_PUSH = 0.55;     // atténuation de la poussée subie par un agent en marche

const AVOID_RADIUS = 1.3;      // rayon de perception d'un collègue à éviter en marchant
const AVOID_STRENGTH = 1.1;    // poids de l'évitement face au cap direct vers l'étape
const AVOID_SIDE_BIAS = 0.6;   // biais latéral qui tranche les tête-à-tête symétriques

const STUCK_WINDOW = 1.6;      // s d'observation avant de conclure au blocage
const STUCK_DISTANCE = 0.18;   // m parcourus en deçà desquels on considère l'agent coincé
const REPLAN_INTERVAL = 4;     // s entre deux recalculs d'un trajet qui progresse

/**
 * Écarte les agents qui s'interpénètrent.
 *
 * Chacun choisit sa destination sans connaître celle des autres : deux d'entre eux visant
 * la même zone finissaient superposés, donnant un personnage à deux têtes. Plusieurs
 * passes sont nécessaires : écarter la paire (i, j) peut en rapprocher une troisième,
 * qu'une seule itération laisserait donc encore collée.
 *
 * Contrairement à la version précédente, les agents en marche ne sont plus exclus — ils
 * se traversaient alors mutuellement. C'est `push` qui rend la poussée compatible avec la
 * marche, en ne les faisant jamais reculer.
 */
function separate(controllers, nav) {
  for (let pass = 0; pass < SEPARATION_PASSES; pass++) {
    let touches = null;
    for (let i = 0; i < controllers.length; i++) {
      for (let j = i + 1; j < controllers.length; j++) {
        const a = controllers[i];
        const b = controllers[j];
        // Deux agents assis à leur poste ne peuvent pas se gêner : leurs bureaux sont
        // distincts. Les pousser ne ferait que les décaler de leur chaise.
        if (a.atDesk && b.atDesk) continue;

        const dx = b.root.position.x - a.root.position.x;
        const dz = b.root.position.z - a.root.position.z;
        const d2 = dx * dx + dz * dz;
        if (d2 >= PERSONAL_SPACE * PERSONAL_SPACE) continue;

        let nx;
        let nz;
        let d;
        if (d2 < 1e-8) {
          // Exactement superposés : aucune direction naturelle ne se dégage des
          // positions. Sans repli, la garde contre la division par zéro les laissait
          // confondus pour toujours — on choisit donc une direction arbitraire mais
          // stable pour cette paire, plutôt que de renoncer à les séparer.
          const angle = (i * 2.399963 + j * 1.618034) % (Math.PI * 2);
          nx = Math.cos(angle);
          nz = Math.sin(angle);
          d = 0;
        } else {
          d = Math.sqrt(d2);
          nx = dx / d;
          nz = dz / d;
        }

        // Un agent installé à son poste ne se déplace pas : c'est l'autre qui contourne,
        // et il encaisse donc tout l'écart au lieu de la moitié.
        const partA = b.atDesk ? 1 : a.atDesk ? 0 : 0.5;
        const ecart = PERSONAL_SPACE - d;
        push(a, -nx * ecart * partA, -nz * ecart * partA, nav);
        push(b, nx * ecart * (1 - partA), nz * ecart * (1 - partA), nav);
        (touches ??= new Set()).add(i).add(j);
      }
    }
    if (!touches) break;
  }
}

/**
 * Applique une poussée de séparation à un agent.
 *
 * Un agent en marche n'est jamais repoussé vers l'arrière : la composante opposée à sa
 * direction est retirée, il glisse donc sur le côté au lieu d'annuler son pas. Sans ce
 * filtrage, deux agents qui se croisent se repoussent à contresens et chacun défait le
 * pas de l'autre à la frame suivante — deux personnages figés à se cogner.
 *
 * La poussée passe par le maillage au même titre qu'un pas : c'était l'autre porte
 * d'entrée dans les murs. Elle pouvait déplacer un agent de près d'un demi-mètre d'un
 * coup — bien plus qu'une foulée (2 cm à 60 img/s) — et la reprojection qui suivait ne
 * distinguait pas un point de l'autre côté d'une cloison d'un point resté du bon côté.
 */
function push(ctrl, px, pz, nav = null) {
  if (ctrl.atDesk) return;

  if (ctrl.walking) {
    const fx = ctrl.moveX;
    const fz = ctrl.moveZ;
    const longitudinal = px * fx + pz * fz;
    if (longitudinal < 0) {
      px -= longitudinal * fx;
      pz -= longitudinal * fz;
    }
    px *= WALKING_PUSH;
    pz *= WALKING_PUSH;
    // Face-à-face parfaitement symétrique : la poussée était entièrement longitudinale et
    // il n'en reste rien. Chacun se décale alors sur sa propre gauche, donc de côtés
    // opposés, plutôt que de rester collés jusqu'à ce que l'un cède.
    if (Math.hypot(px, pz) < 1e-4) {
      const amplitude = Math.abs(longitudinal) * WALKING_PUSH;
      px = -fz * amplitude;
      pz = fx * amplitude;
    }
  }

  const pos = ctrl.root.position;
  if (nav) {
    const arrivee = moveOnNav(nav, { x: pos.x, z: pos.z }, { x: pos.x + px, z: pos.z + pz }, ctrl.navTri);
    pos.x = arrivee.x;
    pos.z = arrivee.z;
    if (arrivee.tri >= 0) ctrl.navTri = arrivee.tri;
  } else {
    pos.x += px;
    pos.z += pz;
  }
}

/**
 * Générateur pseudo-aléatoire déterministe (mulberry32).
 *
 * La déambulation doit paraître libre sans être imprévisible : à graine égale, deux
 * exécutions produisent le même parcours, ce qui garde la scène reproductible et
 * débogable — c'est le parti pris du module depuis l'origine.
 */
function makeRandom(seed) {
  let a = seed >>> 0;
  return function random() {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

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

/**
 * Étiquette flottante : petite case dessinée sur un canvas, portée par un sprite.
 *
 * Un sprite plutôt qu'un élément HTML positionné : l'étiquette suit l'agent dans la
 * profondeur de la scène et se fait masquer par le décor comme n'importe quel objet,
 * là où une surcouche HTML flotterait toujours au-dessus.
 */
function makeLabelTexture(title, role, detail, accent) {
  const W = 620;
  const H = 210;
  const canvas = document.createElement('canvas');
  canvas.width = W;
  canvas.height = H;
  const ctx = canvas.getContext('2d');

  // Carte arrondie, volontairement discrète : six de ces cartes cohabitent à l'écran,
  // et une seule un peu trop contrastée suffit à faire oublier la scène qu'elle annote.
  const pad = 8;
  const w = W - pad * 2;
  const h = H - pad * 2;
  const r = 30;
  ctx.beginPath();
  ctx.moveTo(pad + r, pad);
  ctx.arcTo(pad + w, pad, pad + w, pad + h, r);
  ctx.arcTo(pad + w, pad + h, pad, pad + h, r);
  ctx.arcTo(pad, pad + h, pad, pad, r);
  ctx.arcTo(pad, pad, pad + w, pad, r);
  ctx.closePath();
  ctx.fillStyle = 'rgba(16, 17, 24, 0.82)';
  ctx.fill();
  ctx.lineWidth = 2;
  ctx.strokeStyle = 'rgba(255,255,255,0.10)';
  ctx.stroke();

  // Liseré de couleur à gauche : il identifie l'agent d'un coup d'œil, sans ajouter
  // la moindre ligne de texte.
  ctx.beginPath();
  ctx.roundRect(pad + 14, pad + 22, 7, h - 44, 4);
  ctx.fillStyle = accent;
  ctx.fill();

  const x = pad + 38;
  ctx.textBaseline = 'alphabetic';

  ctx.fillStyle = 'rgba(255,255,255,0.97)';
  ctx.font = '700 40px Manrope, system-ui, sans-serif';
  ctx.fillText(ellipsize(ctx, title, w - 70), x, pad + 62);

  ctx.fillStyle = accent;
  ctx.font = '600 28px Manrope, system-ui, sans-serif';
  ctx.fillText(ellipsize(ctx, role, w - 70), x, pad + 104);

  ctx.fillStyle = 'rgba(255,255,255,0.72)';
  ctx.font = '400 30px Manrope, system-ui, sans-serif';
  ctx.fillText(ellipsize(ctx, detail || '', w - 70), x, pad + 152);

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

/** Tronque au besoin : une carte qui s'élargit selon son texte danse à l'écran. */
function ellipsize(ctx, text, maxWidth) {
  let out = String(text);
  if (ctx.measureText(out).width <= maxWidth) return out;
  while (out.length > 1 && ctx.measureText(out + '…').width > maxWidth) out = out.slice(0, -1);
  return out + '…';
}

// Un agent = une machine à états. Transitions animées par crossfade (pas de
// coupure brute), highlight et indicateur pilotés par interpolation (lerp).
//
// Il se déplace dans le bureau : il rejoint son poste pour travailler, et déambule
// entre les espaces communs le reste du temps.
class AgentController {
  constructor(root, clips, cfg, dotTexture, { seed = 1, rank = 0, deskPos, deskAngle = null, model = null, roamPositions = [], nav = null, siblings = [] } = {}) {
    this.root = root;
    // `root` porte la position à l'échelle du mètre, `model` le squelette à l'échelle
    // du kit. Le mixeur doit s'appliquer au second : c'est lui qui porte les nœuds
    // nommés que les pistes d'animation ciblent.
    this.model = model || root;
    this.cfg = cfg;
    this.rank = rank;
    this.baseColor = new THREE.Color(cfg.color);
    this.state = null;
    // Référence partagée vers tous les contrôleurs (y compris celui-ci) : sert à éviter
    // de choisir une flânerie qui atterrirait sur un collègue déjà en place.
    this.siblings = siblings;

    // Machine d'animation : une action par état, prêtes à être fondues.
    this.mixer = new THREE.AnimationMixer(this.model);
    this.actions = {};
    const clipFor = (nom) =>
      clips.find((c) => c.name === nom) || clips.find((c) => c.name === CLIPS.stand) || clips[0];
    for (const [key, nom] of [
      ['idle', CLIPS.sit],      // assis à son poste, sans tâche
      ['working', CLIPS.sit],   // assis et à l'ouvrage — c'est l'écran qui le signale
      ['done', CLIPS.done],
      ['walk', CLIPS.walk],
      // Debout, hors de son poste : la pose assise n'aurait aucun sens en pleine pièce.
      ['stand', CLIPS.stand],
    ]) {
      const clip = clipFor(nom);
      if (!clip) continue;
      const action = this.mixer.clipAction(clip);
      action.enabled = true;
      action.setEffectiveWeight(0);
      action.play();
      this.actions[key] = action;
    }
    this.current = null;

    // --- Déplacement ---------------------------------------------------------
    this.random = makeRandom(seed);
    this.nav = nav;
    this.deskPos = deskPos ? deskPos.clone() : root.position.clone();
    // Cap du poste, donné par le plan. Sans lui, un agent revenant travailler garde le
    // cap de son dernier pas de marche — souvent de travers par rapport au poste,
    // jamais franchement assis face à lui.
    this.deskAngle = deskAngle ?? Math.atan2(CENTER.x - this.deskPos.x, CENTER.z - this.deskPos.z);
    this.roamPositions = roamPositions;
    // Itinéraire en cours : suite de points issus du maillage de navigation. Un seul
    // point suffirait en terrain libre, mais contourner un mur en demande plusieurs.
    this.path = [];
    this.destination = null; // but du trajet, publié pour que les collègues ne le visent pas
    this.nextRoamAt = 0;     // instant du prochain départ en déambulation
    this.walking = false;
    this.atDesk = false;     // installé à son poste : immobile, et non poussable
    this.stateWanted = 'idle';

    // Triangle de navigation courant : sert d'indice de départ à la localisation, qui
    // devient alors un test local au lieu d'une recherche dans tout le maillage.
    this.navTri = -1;
    // Vitesse et direction réellement suivies. Les faire évoluer progressivement, plutôt
    // que de les recalculer d'une frame à l'autre, est ce qui distingue une démarche d'un
    // glissement saccadé.
    this.speed = 0;
    this.moveX = Math.sin(root.rotation.y);
    this.moveZ = Math.cos(root.rotation.y);
    // Détection de blocage : position de référence et instant du dernier contrôle.
    this.replanAt = 0;
    this.stuckSince = 0;
    this.stuckFrom = { x: root.position.x, z: root.position.z };
    // Nombre de blocages consécutifs sur le trajet courant : au-delà d'un recalcul
    // resté sans effet, on change carrément de destination plutôt que de s'obstiner.
    this.stuckStrikes = 0;
    // Instant jusqu'auquel cet agent cède le passage : il s'arrête pour laisser
    // l'autre franchir le goulet, au lieu de se disputer le même mètre carré.
    this.yieldUntil = 0;

    // Matériaux porteurs du halo d'état. Le personnage du kit est texturé par un atlas
    // partagé, sans maillage « corps » distinct : on prend donc tous les matériaux
    // visibles, dont l'émissif a déjà été réglé à la couleur de l'agent au montage.
    this.bodyMats = [];
    this.model.traverse((child) => {
      if (child.isMesh && child.visible && child.material) this.bodyMats.push(child.material);
    });

    // Indicateur d'état flottant (billboard) au-dessus de l'agent.
    this.dot = new THREE.Sprite(
      new THREE.SpriteMaterial({ map: dotTexture, transparent: true, depthWrite: false })
    );
    this.dot.scale.setScalar(0.34);
    // Au-dessus de la tête : le personnage fait ~1,7 m une fois le kit ramené au mètre.
    this.dot.position.set(0, 2.02, 0);
    this.dot.material.opacity = 0;
    root.add(this.dot);

    // Étiquette de tâche, au-dessus de la pastille. Redessinée seulement quand le
    // texte change : reconstruire une texture à chaque frame coûterait cher pour rien.
    this.labelText = '';
    this.labelSprite = new THREE.Sprite(
      new THREE.SpriteMaterial({ transparent: true, depthWrite: false, opacity: 0 })
    );
    this.labelSprite.scale.set(1.72, 0.58, 1);
    this.labelSprite.position.set(0, 2.55, 0);
    root.add(this.labelSprite);
    this.setLabel('En attente');

    this.dotColor = IDLE_DOT.clone();
    this.emissiveInt = 0;

    this.setState('idle', true);
  }

  /** Change le texte de l'étiquette (no-op si identique). */
  setLabel(detail) {
    if (detail === this.labelText) return;
    this.labelText = detail;
    const accent = `#${this.baseColor.getHexString()}`;
    this.labelSprite.material.map?.dispose();
    this.labelSprite.material.map = makeLabelTexture(this.cfg.name, this.cfg.role, detail, accent);
    this.labelSprite.material.needsUpdate = true;
  }

  /**
   * Enregistre l'état voulu par le pipeline.
   *
   * Le clip effectivement joué est décidé dans `update` : tant que l'agent marche,
   * c'est `Walk`, quel que soit l'état demandé. Un agent qui rejoint son bureau doit
   * traverser la pièce debout avant de s'asseoir.
   */
  requestState(state, time = 0) {
    if (state === this.stateWanted) return;
    this.stateWanted = state;

    if (state === 'working') {
      // Au travail : on rejoint son poste, en contournant ce qu'il faut.
      this.goTo(this.deskPos, time);
    } else {
      // Libéré : on quitte le poste pour un espace commun, après un court délai.
      this.path = [];
      this.destination = null;
      this.nextRoamAt = 0;
    }
  }

  /** Trace un itinéraire praticable jusqu'à `dest` et l'adopte. */
  goTo(dest, time = 0) {
    if (!dest) return;
    const p = this.root.position;
    const cible = projectToNav(this.nav, dest);
    this.destination = { x: cible.x, z: cible.z };
    this.path = findPath(this.nav, { x: p.x, z: p.z }, this.destination, {
      radius: AGENT_RADIUS,
      startTri: this.navTri,
    });
    this.replanAt = time + REPLAN_INTERVAL;
    this.stuckSince = time;
    this.stuckFrom = { x: p.x, z: p.z };
  }

  /** Retrace le chemin vers la destination courante depuis la position actuelle. */
  _replan(time) {
    this.replanAt = time + REPLAN_INTERVAL;
    if (!this.destination) return;
    const p = this.root.position;
    this.path = findPath(this.nav, { x: p.x, z: p.z }, this.destination, {
      radius: AGENT_RADIUS,
      startTri: this.navTri,
    });
  }

  setState(state, immediate = false) {
    if (state === this.state) return;
    const precedent = this.state;
    this.state = state;
    const next = this.actions[state] || this.actions.idle;
    if (next && next !== this.current) {
      // Fondu court sur les transitions impliquant la marche : mélanger longuement une
      // pose assise et une foulée donne un personnage penché, ni assis ni debout.
      const marche = state === 'walk' || precedent === 'walk';
      const dur = immediate ? 0 : marche ? 0.18 : 0.45;
      next.reset();
      next.setEffectiveWeight(1);
      next.fadeIn(dur);
      next.play();
      if (this.current) this.current.fadeOut(dur);
      this.current = next;
    }
  }

  /**
   * Choisit un point de flânerie, en évitant si possible les abords immédiats des
   * collègues déjà en place.
   *
   * Sans cet évitement, chaque agent choisit sa cible dans l'ignorance des autres : sur
   * neuf zones communes partagées par six agents, plusieurs convergent régulièrement
   * vers le même point et s'y retrouvent agglutinés — `separate()` les repousse ensuite,
   * mais seulement une fois qu'ils s'y sont déjà cognés. Mieux vaut ne pas viser là où
   * quelqu'un se trouve déjà.
   */
  _pickRoamTarget() {
    const CLEARANCE = PERSONAL_SPACE * 2.2;
    let meilleur = null;
    let meilleureMarge = -Infinity;

    for (let essai = 0; essai < 6; essai++) {
      const choix = this.roamPositions[Math.floor(this.random() * this.roamPositions.length)];
      // Décalage autour du point : sans lui, deux agents visant le même espace se
      // superposeraient exactement. Large, car les zones communes sont vastes.
      const candidat = {
        x: choix.x + (this.random() - 0.5) * 2.4,
        z: choix.z + (this.random() - 0.5) * 2.4,
      };

      let marge = Infinity;
      for (const autre of this.siblings) {
        if (autre === this) continue;
        // Position actuelle **et** destination annoncée : viser l'endroit où un collègue
        // se rend revient à s'y agglutiner deux secondes plus tard, ce que la seule
        // position ne permettait pas d'anticiper.
        for (const ref of [autre.root.position, autre.destination]) {
          if (!ref) continue;
          const d = Math.hypot(candidat.x - ref.x, candidat.z - ref.z);
          if (d < marge) marge = d;
        }
      }
      if (marge >= CLEARANCE) return candidat;
      if (marge > meilleureMarge) { meilleureMarge = marge; meilleur = candidat; }
    }
    // Aucun essai n'était assez dégagé (zones bondées) : on prend le moins pire plutôt
    // que de renoncer à flâner.
    return meilleur;
  }

  /**
   * Fait avancer l'agent vers sa destination, et choisit une nouvelle flânerie.
   *
   * Retourne `true` s'il est en train de marcher — c'est ce qui décide du clip joué.
   */
  _move(delta, time) {
    // Pas d'itinéraire et libre de ses mouvements : on choisit une destination, après
    // une pause, sinon les six agents repartiraient tous en même temps.
    if (!this.path.length && this.stateWanted !== 'working' && this.roamPositions.length) {
      if (this.nextRoamAt === 0) {
        // Délai court : chaque changement d'état remet ce compteur à zéro, et un tirage
        // large (jusqu'à 7,5 s) s'additionnait d'un état à l'autre — le plateau restait
        // figé une vingtaine de secondes avant que quiconque ne se lève. L'échelonnement
        // entre agents reste assuré par leur graine propre.
        this.nextRoamAt = time + 0.6 + this.random() * 2.5;
      } else if (time >= this.nextRoamAt) {
        this.goTo(this._pickRoamTarget());
        this.nextRoamAt = 0;
      }
    }

    if (!this.path.length) {
      // Arrivé et au travail : on cale le cap sur le bureau plutôt que de rester sur
      // le dernier cap de marche, qui n'a aucune raison de faire face au poste.
      if (this.stateWanted === 'working') this._turnTowards(this.deskAngle, delta);
      return false;
    }

    const pos = this.root.position;

    // Cession de passage en cours : on marque l'arrêt le temps que l'autre dégage.
    // Rester planté quelques dixièmes de seconde est ce qui résout le face-à-face —
    // continuer à pousser ne fait que prolonger le blocage.
    if (time < this.yieldUntil) return false;

    /* --- Surveillance du blocage ---------------------------------------------- */
    // Ces garde-fous étaient déclarés mais n'ont jamais été branchés : rien ne
    // surveillait la progression, donc deux agents en opposition n'avaient aucun
    // moyen d'en sortir — ils se cognaient tant que la scène tournait.
    if (time - this.stuckSince >= STUCK_WINDOW) {
      const parcouru = Math.hypot(pos.x - this.stuckFrom.x, pos.z - this.stuckFrom.z);
      if (parcouru < STUCK_DISTANCE) {
        this.stuckStrikes++;
        if (this.stuckStrikes === 1) {
          // Premier échec : l'itinéraire est peut-être simplement périmé.
          this._replan(time);
        } else if (this.stateWanted === 'working') {
          // En route vers son poste : la destination n'est pas négociable, on
          // s'écarte brièvement pour casser la symétrie puis on repart.
          this.yieldUntil = time + 0.35 + this.random() * 0.4;
          this._replan(time);
          this.stuckStrikes = 0;
        } else {
          // En flânerie : la destination n'a aucune importance, on en change.
          this.goTo(this._pickRoamTarget(), time);
          this.stuckStrikes = 0;
        }
      } else {
        this.stuckStrikes = 0;
      }
      this.stuckSince = time;
      this.stuckFrom = { x: pos.x, z: pos.z };
    }

    // Recalcul périodique : le chemin a été tracé sur une situation qui a bougé
    // (collègues déplacés, agent dévié de son couloir par les évitements).
    if (time >= this.replanAt) this._replan(time);

    const etape = this.path[0];
    if (!etape) return false;
    const dx = etape.x - pos.x;
    const dz = etape.z - pos.z;
    const dist = Math.hypot(dx, dz);

    if (dist <= ARRIVAL) {
      // Étape franchie : on enchaîne sur la suivante sans marquer l'arrêt.
      this.path.shift();
      return this.path.length > 0;
    }

    // Cap direct vers l'étape, dévié par la proximité des collègues qui se trouvent
    // globalement devant soi (ceux déjà dépassés ne doivent pas faire zigzaguer la
    // marche). Sans cette déviation, deux agents dont les chemins se croisent
    // avancent l'un vers l'autre jusqu'à se toucher, où `separate()` les repousse en
    // sens inverse — chacun annulant le pas de l'autre à la frame suivante, ce qui se
    // voit comme deux personnages figés en train de se cogner.
    let dirX = dx / dist;
    let dirZ = dz / dist;

    let avoidX = 0;
    let avoidZ = 0;
    for (const autre of this.siblings) {
      if (autre === this) continue;
      const ox = pos.x - autre.root.position.x;
      const oz = pos.z - autre.root.position.z;
      const od = Math.hypot(ox, oz);
      if (od >= AVOID_RADIUS || od < 1e-4) continue;
      // (ox, oz) pointe de l'autre vers moi ; devant soi, il pointe donc plutôt à
      // l'opposé du cap (dot proche de -1). Ignorer ce qui est nettement dans le sens
      // du cap (dot > 0.2), c'est-à-dire déjà dépassé.
      if ((ox / od) * dirX + (oz / od) * dirZ > 0.2) continue;

      // Face-à-face serré : les deux avancent l'un vers l'autre. L'évitement latéral
      // seul ne suffit pas dans un passage étroit — les deux se décalent, se
      // retrouvent encore nez à nez, et recommencent. Le rang tranche : le plus
      // grand s'efface, l'autre passe. Le critère est stable dans le temps, donc la
      // décision ne s'inverse pas d'une frame à l'autre.
      if (autre.walking && od < PERSONAL_SPACE * 1.25) {
        const versMoi = (-ox / od) * autre.moveX + (-oz / od) * autre.moveZ;
        if (versMoi > 0.5 && this.rank > autre.rank) {
          this.yieldUntil = time + 0.5;
          return false;
        }
      }

      const poids = (AVOID_RADIUS - od) / AVOID_RADIUS;
      avoidX += (ox / od) * poids;
      avoidZ += (oz / od) * poids;
      // Biais latéral, vers sa propre gauche : un obstacle pile dans l'axe (ou deux
      // agents en tête-à-tête parfaitement symétrique) ne dégage sinon aucune
      // direction naturelle — la répulsion pure les laisse alors immobiles à distance
      // de sécurité au lieu de contourner. Chacun se décale de son côté, donc les deux
      // s'écartent sur des côtés opposés plutôt que de se disputer le même.
      avoidX += -dirZ * poids * AVOID_SIDE_BIAS;
      avoidZ += dirX * poids * AVOID_SIDE_BIAS;
    }

    let dirFinalX = dirX + avoidX * AVOID_STRENGTH;
    let dirFinalZ = dirZ + avoidZ * AVOID_STRENGTH;
    const norme = Math.hypot(dirFinalX, dirFinalZ);
    if (norme > 1e-4) {
      dirFinalX /= norme;
      dirFinalZ /= norme;
    } else {
      dirFinalX = dirX;
      dirFinalZ = dirZ;
    }

    // Direction réellement suivie, publiée pour les collègues. Elle n'était fixée qu'au
    // spawn : `push()` s'en sert pour ne jamais repousser un marcheur vers l'arrière, et
    // travaillait donc sur le cap initial du personnage, sans rapport avec sa marche du
    // moment — la poussée pouvait annuler le pas au lieu de le décaler.
    this.moveX = dirFinalX;
    this.moveZ = dirFinalZ;

    const pas = Math.min(WALK_SPEED * delta, dist);

    // Déplacement contraint à la surface : le trajet est suivi d'un triangle à l'autre
    // et s'arrête (puis glisse) sur un mur. La version précédente déplaçait librement
    // puis reprojetait le point d'arrivée — or un point de l'autre côté d'une cloison
    // est parfaitement valide, donc rien ne s'opposait à la traversée.
    if (this.nav) {
      const arrivee = moveOnNav(
        this.nav,
        { x: pos.x, z: pos.z },
        { x: pos.x + dirFinalX * pas, z: pos.z + dirFinalZ * pas },
        this.navTri,
      );
      pos.x = arrivee.x;
      pos.z = arrivee.z;
      if (arrivee.tri >= 0) this.navTri = arrivee.tri;
    } else {
      pos.x += dirFinalX * pas;
      pos.z += dirFinalZ * pas;
    }

    // Pivot progressif vers la direction réellement suivie (pas le cap direct) : sans
    // quoi le personnage semblerait glisser de travers pendant qu'il contourne un
    // collègue, au lieu de se tourner vers là où il marche vraiment.
    this._turnTowards(Math.atan2(dirFinalX, dirFinalZ), delta);

    return true;
  }

  /** Pivote progressivement vers un cap (radians), sans jamais tourner d'un coup. */
  _turnTowards(angle, delta) {
    let ecart = angle - this.root.rotation.y;
    while (ecart > Math.PI) ecart -= Math.PI * 2;
    while (ecart < -Math.PI) ecart += Math.PI * 2;
    this.root.rotation.y += Math.max(-TURN_SPEED * delta, Math.min(TURN_SPEED * delta, ecart));
  }

  update(delta, status, time) {
    this.mixer.update(delta);

    // Le déplacement prime sur l'état : on ne s'assoit qu'une fois arrivé.
    this.requestState(status.state);
    this.walking = this._move(delta, time);

    // « Installé à son poste » : veut travailler, ne marche plus, et se trouve
    // effectivement sur sa chaise. Ce drapeau était déclaré mais jamais positionné, si
    // bien que la règle « un agent assis ne se fait pas bousculer » ne s'appliquait
    // jamais — c'est aussi ce qui laissait les collègues déloger un agent de sa chaise.
    this.atDesk =
      this.stateWanted === 'working'
      && !this.walking
      && Math.hypot(this.root.position.x - this.deskPos.x, this.root.position.z - this.deskPos.z) < 0.35;

    // Clip effectif. Les poses assises du kit n'ont de sens qu'à un bureau : hors de
    // son poste, un agent à l'arrêt doit rester debout, sinon il s'assoit dans le vide.
    let clip;
    if (this.walking) clip = 'walk';
    else if (this.atDesk) clip = status.state === 'idle' ? 'idle' : status.state;
    else clip = status.state === 'done' ? 'done' : 'stand';
    this.setState(clip);

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

    // L'étiquette n'est pleinement lisible que sur l'agent au travail : les six
    // affichées à la même intensité rendraient la scène illisible.
    const labelTarget = status.state === 'working' ? 1 : status.state === 'done' ? 0.45 : 0.2;
    this.labelSprite.material.opacity += (labelTarget - this.labelSprite.material.opacity) * k;

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
    if (this.labelSprite) {
      this.labelSprite.material.map?.dispose();
      this.labelSprite.material.dispose();
      if (this.labelSprite.parent) this.labelSprite.parent.remove(this.labelSprite);
    }
  }
}

export async function initAgentsScene(container) {
  disposeAgentsScene();

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x1a1b22);
  // Brouillard reculé : le plateau fait 18 x 12 m, la portée précédente (14-26)
  // avait été calée sur un bureau bien plus petit et noyait le fond de la pièce.
  scene.fog = new THREE.Fog(0x1a1b22, 30, 54);

  const camera = new THREE.PerspectiveCamera(42, container.clientWidth / container.clientHeight, 0.1, 100);
  camera.position.set(8, 9.5, 13);

  const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setSize(container.clientWidth, container.clientHeight);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.05;
  // Le canvas est glissé DERRIÈRE l'indicateur de chargement plutôt que de vider le
  // conteneur : effacer ici détachait l'indicateur alors que les modèles n'étaient pas
  // encore chargés, si bien qu'un échec ultérieur n'avait plus où s'afficher — la scène
  // restait noire et muette. L'appelant retire l'indicateur quand la scène est prête.
  renderer.domElement.classList.add('absolute', 'inset-0');
  container.insertBefore(renderer.domElement, container.firstChild);

  const controls = new OrbitControls(camera, renderer.domElement);
  controls.target.set(1.5, 0.7, 0);
  controls.enableDamping = true;
  controls.dampingFactor = 0.08;
  controls.minDistance = 6;
  controls.maxDistance = 48;
  controls.maxPolarAngle = Math.PI / 2.05;
  controls.update();

  scene.add(new THREE.AmbientLight(0xffffff, 0.95));
  scene.add(new THREE.HemisphereLight(0xdfe6ff, 0x1a1a22, 0.5));
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.9);
  dirLight.position.set(8, 14, 7);
  dirLight.castShadow = true;
  dirLight.shadow.mapSize.set(1024, 1024);
  dirLight.shadow.camera.left = -20;
  dirLight.shadow.camera.right = 20;
  dirLight.shadow.camera.top = 20;
  dirLight.shadow.camera.bottom = -20;
  scene.add(dirLight);

  // Les deux modèles sont compressés en Draco. Sans `setDecoderPath`, three cherche le
  // décodeur à la racine du site, reçoit un 404, et le chargement échoue — la scène
  // restait alors noire, sans le moindre message.
  const dracoLoader = new DRACOLoader();
  dracoLoader.setDecoderPath(DRACO_BASE);

  const loader = new GLTFLoader();
  loader.setDRACOLoader(dracoLoader);

  // Le bureau est assemblé par code depuis le kit CC0 (voir `office-kit.js`), et le
  // personnage vient du même kit. L'ancien couple office.glb / character.glb était sous
  // CC BY-NC 4.0 : interdit en usage commercial, donc inutilisable pour le produit.
  const [officeBuilt, ...characterGltfs] = await Promise.all([
    buildOffice(loader),
    ...AGENTS.map((a) => loader.loadAsync(CHARACTER_BASE + a.model)),
  ]);

  const { group: office, navMesh: navMeshNode, pois: poiPositions, deskAngles, screens } = officeBuilt;
  // Le décor **reçoit** les ombres partout, mais n'en **projette** que là où
  // `office-kit.js` l'a jugé utile (murs, tables). Le bureau assemblé compte plusieurs
  // centaines de maillages — livres, cactus, cadres — et les faire tous participer à la
  // passe d'ombre revenait à dessiner la scène deux fois pour des ombres de la taille
  // d'un livre. Le premier rendu s'en trouvait considérablement rallongé.
  office.traverse((child) => {
    if (child.isMesh && child.name !== 'navMesh') child.receiveShadow = true;
  });
  scene.add(office);

  // Le graphe est construit une fois, à partir de la surface praticable engendrée par
  // le plan. `null` si le maillage manque — les agents retombent sur la ligne droite.
  const nav = buildNavMesh(navMeshNode);

  const dotTexture = makeDotTexture();
  const controllers = [];

  AGENTS.forEach((agent, i) => {
    const gltf = characterGltfs[i];
    const clips = gltf.animations || [];

    // Un porteur intermédiaire reçoit l'échelle du modèle, ce qui laisse au contrôleur
    // un repère à l'échelle du mètre : il pilote position et lacet sans jamais avoir à
    // tenir compte du facteur de conversion.
    const clone = new THREE.Group();
    const modele = SkeletonUtils.clone(gltf.scene);
    modele.scale.setScalar(CHARACTER_SCALE);
    clone.add(modele);

    modele.traverse((child) => {
      if (!child.isMesh) return;
      child.castShadow = true;
      child.receiveShadow = true;
      const mat = child.material.clone();
      // Teinte franche : c'est elle qui rattache le personnage à sa carte et à sa ligne
      // dans le pipeline. À 55 %, tous les agents viraient au vert du modèle d'origine
      // et devenaient indiscernables les uns des autres — l'inverse du but recherché.
      if (mat.color) mat.color.lerp(new THREE.Color(agent.color), 0.82);
      mat.emissive = new THREE.Color(agent.color);
      mat.emissiveIntensity = 0;
      child.material = mat;
    });

    // Position de départ : le poste de l'agent. Elle évolue ensuite au fil de ses
    // déplacements — c'est le contrôleur qui en a la charge.
    const desk = poiPositions[agent.desk] || new THREE.Vector3((i - 2.5) * 1.3, 0, 2);
    clone.position.copy(desk);
    clone.rotation.y = deskAngles[agent.desk] ?? 0;
    scene.add(clone);

    const roamPositions = ROAM_IDS.map((nom) => poiPositions[nom]).filter(Boolean);

    controllers.push(
      new AgentController(clone, clips, agent, dotTexture, {
        // Une graine par agent : chacun flâne différemment, mais de façon reproductible.
        seed: i * 7919 + 13,
        // Rang de priorité, fixe et distinct : c'est lui qui tranche un face-à-face.
        // Sans arbitre, deux agents symétriques se cèdent le passage en même temps,
        // indéfiniment.
        rank: i,
        deskPos: desk,
        deskAngle: deskAngles[agent.desk],
        model: modele,
        roamPositions,
        nav,
        // Même tableau que celui rempli par cette boucle : par référence, chaque
        // contrôleur y verra tous ses collègues une fois la scène montée.
        siblings: controllers,
      }),
    );
  });

  // Le pipeline (série) pilote l'état de chaque agent. Poids : Build un peu plus
  // long, Déploiement un peu plus court, pour un rythme crédible.
  const pipeline = createPipeline(
    AGENTS.map((a) => a.name),
    { weights: [1.0, 1.05, 1.05, 1.35, 1.0, 0.9] }
  );

  const clock = new THREE.Clock();
  pipeline.start(clock.getElapsedTime());

  // Vrai dès qu'une source réelle (le backend, via `applyStatuses`) pilote la scène.
  let piloteExterne = false;

  let rafId = null;
  function animate() {
    rafId = requestAnimationFrame(animate);
    const delta = Math.min(clock.getDelta(), 0.1);
    const t = clock.elapsedTime;

    // Rebouclage propre de la séquence tant que la génération n'est pas figée.
    if (pipeline.loop && pipeline.isFinished(t)) pipeline.start(t);

    for (let i = 0; i < controllers.length; i++) {
      const status = pipeline.statusAt(i, t);
      // Sans source réelle branchée, la carte suivrait éternellement son texte de
      // départ (« En attente »), y compris sur un agent en plein travail. On la fait
      // donc suivre l'état simulé — dès qu'`applyStatuses` prend la main, c'est son
      // libellé, plus précis, qui l'emporte.
      if (!piloteExterne) controllers[i].setLabel(DEFAULT_DETAIL[status.state] || '');
      // `update` décide seul du clip : forcer l'état ici court-circuiterait la marche.
      controllers[i].update(delta, status, t);

      // L'écran du poste s'allume quand l'agent y travaille, et s'éteint dès qu'il le
      // quitte. C'est le repère le plus direct de la scène : une dalle allumée signale
      // un bureau qui produit, sans qu'il faille lire quoi que ce soit.
      const dalle = screens[AGENTS[i].desk];
      if (dalle) {
        const actif = status.state === 'working' && controllers[i].atDesk;
        const veille = status.state === 'done' && controllers[i].atDesk ? 0.35 : 0;
        // Léger scintillement : un écran parfaitement stable se lit comme une lampe.
        const cible = actif ? 1.5 + 0.35 * Math.sin(t * 7 + i) : veille;
        dalle.emissiveIntensity += (cible - dalle.emissiveIntensity) * Math.min(1, delta * 6);
      }
    }

    separate(controllers, nav);

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

    /** Noms des agents, dans l'ordre où la scène les affiche. */
    agentNames: AGENTS.map((a) => a.name),

    /**
     * Applique l'état réel du backend à la scène.
     *
     * `entries` : un objet `{state, detail}` par agent, dans l'ordre de `agentNames`.
     * Passer par `setStatus` fige la timeline simulée pour cet agent — c'est le point
     * d'entrée prévu par `agents-pipeline.js` pour une source réelle.
     */
    applyStatuses(entries) {
      piloteExterne = true;
      entries.forEach((entry, i) => {
        if (!entry || i >= controllers.length) return;
        pipeline.setStatus(i, entry.state);
        controllers[i].setLabel(entry.detail);
      });
      // Une source réelle pilote désormais la scène : le rebouclage décoratif n'a
      // plus lieu d'être, il repasserait les agents en « idle » derrière le backend.
      pipeline.loop = false;
    },
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
