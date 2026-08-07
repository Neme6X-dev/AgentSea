/**
 * Bureau des agents — construit par code à partir du kit KayKit (CC0).
 *
 * Remplace `office.glb`, qui était sous CC BY-NC 4.0 : usage commercial interdit,
 * donc inutilisable pour un produit vendu. Le mobilier vient de « KayKit Furniture
 * Bits » (Kay Lousberg, CC0 1.0 — usage commercial autorisé, attribution non
 * obligatoire), et tout ce qui n'est pas du mobilier (sol, cloisons) est de la
 * géométrie primitive générée ici, donc libre de droits par construction.
 *
 * ## Pourquoi construire la scène par code plutôt que d'importer un GLB
 *
 * Le plan (`LAYOUT`) est la **source unique de vérité** : les cloisons visibles, la
 * surface praticable et les points d'intérêt en découlent tous. Avec un GLB, la
 * surface de navigation est un maillage authoré à part, qui peut discrètement cesser
 * de correspondre aux murs qu'on voit — c'est précisément ce qui laissait des agents
 * passer au travers. Ici, une cloison ajoutée au plan bloque la navigation dans le
 * même mouvement : la désynchronisation n'est pas corrigée, elle est rendue
 * impossible.
 *
 * ## Échelle
 *
 * Le kit est modelé en unités où une table fait 2 × 1 × 2 et un personnage 2,25 de
 * haut. `KIT_SCALE` ramène le tout au mètre (table 1,5 m de large et 0,75 m de haut,
 * personnage 1,69 m), ce qui permet de garder telles quelles les constantes métriques
 * du déplacement (vitesse de marche, espace personnel, rayon d'agent).
 */
import * as THREE from 'three';

/** Facteur ramenant les unités du kit au mètre. */
export const KIT_SCALE = 0.75;

const FURNITURE_BASE = '/assets/kaykit/furniture/';

/** Côté d'une cellule de navigation, en mètres. */
const CELL = 1;

/**
 * Palette du plateau.
 *
 * Les teintes sont **désaturées et sombres** à dessein. Les six agents portent des
 * pastels vifs (violet, rose, cyan, vert, ambre) et ce sont eux que l'œil doit suivre :
 * un décor aussi saturé qu'eux les ferait disparaître dans le fond. La couleur ici
 * sert à distinguer les zones — on doit lire « salle de réunion », « coin détente »,
 * « plateau de travail » sans étiquette — pas à attirer le regard.
 *
 * L'ocre et la terre cuite ne sont pas décoratifs non plus : ce sont les teintes des
 * marchés auxquels le produit s'adresse.
 */
const PALETTE = {
  solBase: '#22242e',
  solPlateau: '#262b3a',
  solBaie: '#333b52',
  solCommun: '#332b33',
  solAllee: '#3d4463',
  zoneReunion: '#2d4a49',
  zoneDetente: '#4a3421',
  zoneCafe: '#3d3140',
  ocre: '#c0883c',
  terre: '#a2543a',
  grille: 'rgba(255, 255, 255, 0.035)',
  grilleForte: 'rgba(255, 255, 255, 0.07)',

  mur: 0x424556,
  // Corniche de cloison : petite surface, elle peut se permettre d'être franche.
  murCorniche: 0xb07f3a,
  plinthe: 0x2b2620,
  // Couvre-mur périphérique : **volontairement terne**. Vu de la caméra isométrique,
  // c'est sa face supérieure qu'on voit, sur 36 cm de large et sur tout le tour de la
  // pièce — de loin la plus grande surface continue de la scène. En ocre franc elle
  // encadrait le plateau d'un bandeau doré qui captait le regard avant les agents.
  plintheCap: 0x5c4a33,
};

/**
 * Plan du plateau, en mètres.
 *
 * `wall` : cloison pleine, infranchissable et visible.
 * `block` : encombrement au sol (mobilier) — on le contourne, mais rien n'est dressé.
 */
const LAYOUT = {
  floor: { x0: -11, x1: 11, z0: -7, z1: 7 },

  // Cloison séparant les espaces communs (à gauche) du plateau de travail (à droite),
  // percée d'une porte. C'est elle qui donne un sens au cheminement : pour passer
  // d'un côté à l'autre, il faut trouver l'ouverture.
  // Bornes calées sur les frontières de cellules : un rectangle qui s'arrête au milieu
  // d'une case la condamne entière, et la cloison bloquerait alors plus large qu'elle
  // n'est dessinée. La porte fait ici deux cellules (cellules centrées en z = ±0,5).
  walls: [
    { x0: -5, x1: -4, z0: -7, z1: -1 },
    { x0: -5, x1: -4, z0: 1, z1: 7 },
  ],

  // Postes de travail : la table, et la chaise d'où l'agent travaille. Tous les points
  // sont des **centres de cellule** — c'est ce qui garantit qu'un agent naît et
  // s'assoit sur une case praticable.
  desks: [
    { id: 'desk-1', x: -1.5, z: -4.5 },
    { id: 'desk-2', x: 2.5, z: -4.5 },
    { id: 'desk-3', x: 6.5, z: -4.5 },
    { id: 'desk-4', x: -1.5, z: 4.5 },
    { id: 'desk-5', x: 2.5, z: 4.5 },
    { id: 'desk-6', x: 6.5, z: 4.5 },
  ],

  // Zones de flânerie : c'est là que circulent les agents sans tâche en cours.
  // `roam-reunion` se tient **à côté** de la table de réunion et non dessus : la table
  // occupe désormais une empreinte réelle, et un point de flânerie posé sur du
  // mobilier bloquant est un agent qui naît hors surface praticable.
  roam: [
    { id: 'roam-reunion', x: -6.5, z: -4.5 },
    { id: 'roam-detente', x: -8.5, z: 4.5 },
    { id: 'roam-porte', x: -6.5, z: 0.5 },
    { id: 'roam-allee-nord', x: 1.5, z: -1.5 },
    { id: 'roam-allee-sud', x: 5.5, z: 1.5 },
    { id: 'roam-hub', x: -1.5, z: 0.5 },
    { id: 'roam-est', x: 9.5, z: -0.5 },
    { id: 'roam-cafe', x: -9.5, z: 0.5 },
    { id: 'roam-nord', x: -2.5, z: -6.5 },
    { id: 'roam-sud', x: 7.5, z: 6.5 },
  ],

  /**
   * Décor.
   *
   * `blocks` : empreinte au sol à retirer de la surface praticable. Sans elle, un
   * agent traverse le meuble — ce que le plateau tolérait jusqu'ici parce que le décor
   * se limitait à des bords. Une table de réunion au milieu d'une salle, elle, se
   * contourne. L'empreinte est volontairement **plus petite que le meuble** : elle est
   * discrétisée en cellules, et déborder de quelques centimètres condamne la cellule
   * voisine entière.
   *
   * `y` : hauteur de pose, pour ce qui se range sur un meuble plutôt qu'au sol.
   */
  props: [
    /* --- Salle de réunion (nord-ouest) ------------------------------------- */
    { model: 'rug_rectangle_stripes_A', x: -8.5, z: -4.9, rot: 0, y: 0.012 },
    { model: 'table_medium_long', x: -8.5, z: -4.9, rot: 0, blocks: { w: 2, d: 1.1 } },
    { model: 'chair_B', x: -9.6, z: -5.95, rot: 0.16 },
    { model: 'chair_B', x: -7.4, z: -5.95, rot: -0.16 },
    { model: 'chair_B', x: -9.6, z: -3.85, rot: Math.PI - 0.16 },
    { model: 'chair_B', x: -7.4, z: -3.85, rot: Math.PI + 0.16 },
    { model: 'shelf_A_big', x: -10.3, z: -5, rot: Math.PI / 2 },
    { model: 'book_set', x: -10.25, z: -5.4, y: 0.3, rot: Math.PI / 2 },
    { model: 'cactus_medium_B', x: -10.3, z: -2.4, rot: 0 },
    { model: 'cabinet_medium', x: -7.5, z: -6.3, rot: 0 },
    { model: 'pictureframe_standing_A', x: -7.5, z: -6.3, y: 0.75, rot: 0 },

    /* --- Coin détente (sud-ouest) ------------------------------------------ */
    { model: 'rug_rectangle_A', x: -8.5, z: 4.6, rot: 0, y: 0.012 },
    { model: 'couch_pillows', x: -8.5, z: 5.6, rot: Math.PI, blocks: { w: 2, d: 0.7 } },
    { model: 'table_low', x: -8.5, z: 3.6, rot: 0, blocks: { w: 1.5, d: 0.6 } },
    { model: 'lamp_table', x: -8.5, z: 3.6, y: 0.38, rot: 0 },
    { model: 'armchair_pillows', x: -10.2, z: 4.6, rot: Math.PI / 2 },
    { model: 'armchair', x: -6.8, z: 4.6, rot: -Math.PI / 2 },
    { model: 'lamp_standing', x: -10.3, z: 6.2, rot: 0 },
    { model: 'cactus_medium_A', x: -5.8, z: 6.4, rot: 0 },

    /* --- Point café (ouest) ------------------------------------------------- */
    { model: 'rug_oval_A', x: -9.1, z: 0.5, rot: Math.PI / 2, y: 0.012 },
    // Plaqué contre le mur (x = -10,45) et non à -10,25 : 20 cm plus au centre, son
    // empreinte mordait la cellule de `roam-cafe`, qui devenait inatteignable.
    { model: 'cabinet_medium_decorated', x: -10.45, z: 0.6, rot: Math.PI / 2, blocks: { w: 0.7, d: 1.3 } },
    { model: 'cabinet_small', x: -10.4, z: -0.9, rot: Math.PI / 2 },
    { model: 'book_set', x: -10.35, z: -0.9, y: 0.75, rot: Math.PI / 2 },
    { model: 'chair_stool_wood', x: -8.8, z: 1.4, rot: -Math.PI / 2 },

    /* --- Rangements le long de la cloison (face plateau) -------------------- */
    { model: 'cabinet_small_decorated', x: -3.6, z: -3.5, rot: Math.PI / 2 },
    { model: 'cabinet_small_decorated', x: -3.6, z: 2.5, rot: Math.PI / 2 },
    { model: 'cactus_medium_A', x: -3.6, z: -6.4, rot: 0 },
    { model: 'cactus_small_B', x: -3.6, z: 6.4, rot: 0 },

    /* --- Coin détente est --------------------------------------------------- */
    { model: 'rug_oval_B', x: 8.9, z: 2.5, rot: 0, y: 0.012 },
    { model: 'table_small', x: 8.9, z: 2.5, rot: 0, blocks: { w: 0.7, d: 0.7 } },
    { model: 'chair_stool', x: 8.9, z: 1.55, rot: 0 },
    { model: 'chair_stool_wood', x: 8.9, z: 3.45, rot: Math.PI },
    { model: 'armchair', x: 10.2, z: 2.5, rot: -Math.PI / 2 },

    /* --- Bibliothèque est ---------------------------------------------------- */
    { model: 'shelf_B_large', x: 10.2, z: -3.5, rot: -Math.PI / 2 },
    { model: 'shelf_B_large_decorated', x: 10.2, z: 5.2, rot: -Math.PI / 2 },
    { model: 'shelf_A_small', x: 10.3, z: -0.6, rot: -Math.PI / 2 },
    { model: 'book_set', x: 10.25, z: -3.1, y: 0.3, rot: -Math.PI / 2 },

    /* --- Bordures du plateau : plantes, meubles bas, lampes ------------------ */
    { model: 'cabinet_medium', x: 4.5, z: -6.4, rot: 0 },
    { model: 'pictureframe_standing_B', x: 4.5, z: -6.4, y: 0.75, rot: 0 },
    { model: 'lamp_standing', x: 0.4, z: -6.4, rot: 0 },
    { model: 'lamp_standing', x: 8.6, z: -6.4, rot: 0 },
    { model: 'cactus_medium_A', x: 10.4, z: -6.4, rot: 0 },
    { model: 'cactus_small_A', x: 10.4, z: 6.4, rot: 0 },
    { model: 'cactus_medium_B', x: 4.4, z: 6.4, rot: 0 },
    { model: 'cactus_small_B', x: 0.5, z: 6.4, rot: 0 },
  ],

  /**
   * Cadres accrochés aux deux faces de la cloison.
   *
   * Les modèles de cadre sont plats **en z** : sans rotation ils regardent `+z`. Pour
   * habiller une cloison dont la normale est `±x`, il faut donc un quart de tour.
   * `y` est une hauteur de pose volontairement basse (1,2 m) : selon les modèles le
   * pivot est au centre ou au pied, et cette valeur reste dans le mur dans les deux cas.
   */
  frames: [
    { model: 'pictureframe_large_B', x: -5.07, z: -4, y: 1.2, rot: -Math.PI / 2 },
    { model: 'pictureframe_medium', x: -5.07, z: 3.5, y: 1.2, rot: -Math.PI / 2 },
    { model: 'pictureframe_large_A', x: -3.93, z: -2.5, y: 1.2, rot: Math.PI / 2 },
    { model: 'pictureframe_medium', x: -3.93, z: 4.5, y: 1.2, rot: Math.PI / 2 },
  ],
};

/** Modèles dont l'ombre portée se lit ; le reste alourdit la passe sans rien apporter. */
const PROJETTENT = new Set([
  'couch', 'couch_pillows', 'armchair', 'armchair_pillows', 'cabinet_medium',
  'cabinet_medium_decorated', 'cabinet_small', 'cabinet_small_decorated',
  'lamp_standing', 'shelf_A_big', 'shelf_B_large', 'shelf_B_large_decorated',
  'table_medium_long', 'table_low', 'table_small', 'chair_B',
]);

/**
 * Empreinte au sol d'une table, volontairement inférieure à la cellule.
 *
 * L'encombrement est discrétisé : un rectangle qui déborde, ne serait-ce que de
 * quelques centimètres, condamne la cellule voisine **entière**. Avec 1,6 m, la table
 * mangeait la cellule de sa propre chaise : l'agent y naissait hors surface praticable,
 * plus aucun chemin ne partait de lui, et il restait planté là sans que rien ne le
 * signale. En restant sous la taille d'une cellule et centré sur elle, le bureau
 * n'occupe que la sienne.
 */
const DESK_FOOTPRINT = { w: 0.9, d: 0.9 };
/** Recul de la chaise : exactement une cellule, donc toujours sur la case voisine libre. */
const CHAIR_OFFSET = CELL;

/**
 * Ce qui traîne sur chaque bureau, par poste.
 *
 * Un plateau où les six postes portent exactement les mêmes objets se lit comme un
 * décor dupliqué. Varier trois babioles suffit à donner l'impression que quelqu'un
 * travaille là — pour un coût nul, ces modèles étant déjà chargés ailleurs.
 */
const DESK_CLUTTER = [
  [{ model: 'book_set', dx: 0.55, dz: -0.2, rot: 0.6 }],
  [{ model: 'lamp_table', dx: -0.55, dz: -0.15, rot: 0 }],
  [{ model: 'pictureframe_standing_A', dx: 0.5, dz: -0.25, rot: -0.5 },
    { model: 'book_set', dx: -0.55, dz: -0.1, rot: 0.2 }],
  [{ model: 'pictureframe_standing_B', dx: -0.5, dz: -0.25, rot: 0.4 }],
  [{ model: 'book_set', dx: 0.55, dz: -0.2, rot: -0.4 },
    { model: 'lamp_table', dx: -0.55, dz: -0.15, rot: 0 }],
  [{ model: 'book_single', dx: 0.5, dz: -0.25, rot: 0.9 }],
];

/* --------------------------------------------------------------------------- */
/* Chargement                                                                   */
/* --------------------------------------------------------------------------- */

async function loadPiece(loader, nom, cache) {
  if (!cache.has(nom)) {
    cache.set(nom, loader.loadAsync(`${FURNITURE_BASE}${nom}.gltf`).then((g) => g.scene));
  }
  const modele = await cache.get(nom);
  return modele.clone(true);
}

/* --------------------------------------------------------------------------- */
/* Sol                                                                          */
/* --------------------------------------------------------------------------- */

/**
 * Texture du sol, peinte au canevas.
 *
 * Un sol d'une seule couleur ne dit rien du lieu : les six bureaux, le coin détente et
 * la salle de réunion s'y ressemblent, et le plateau ressemble à une grille abstraite.
 * Les zones colorées donnent à chaque partie une identité lisible d'un coup d'œil,
 * depuis une caméra qui ne descend jamais au niveau du sol.
 *
 * Peinte plutôt que composée de plans superposés : des plans coplanaires à `y = 0`
 * produiraient du z-fighting, et les décaler en hauteur créerait des marches visibles
 * en vue rasante. Une seule texture, un seul plan, aucun des deux problèmes.
 */
function buildFloorTexture() {
  const { x0, x1, z0, z1 } = LAYOUT.floor;
  const PPM = 48; // pixels par mètre — assez pour des bords nets sans texture géante
  const canvas = document.createElement('canvas');
  canvas.width = Math.round((x1 - x0) * PPM);
  canvas.height = Math.round((z1 - z0) * PPM);
  const g = canvas.getContext('2d');

  const px = (x) => (x - x0) * PPM;
  const pz = (z) => (z - z0) * PPM;
  const zone = (xa, za, xb, zb, fill) => {
    g.fillStyle = fill;
    g.fillRect(px(xa), pz(za), (xb - xa) * PPM, (zb - za) * PPM);
  };

  zone(x0, z0, x1, z1, PALETTE.solBase);

  // Les deux grands ensembles, de part et d'autre de la cloison.
  zone(x0, z0, -4, z1, PALETTE.solCommun);
  zone(-4, z0, x1, z1, PALETTE.solPlateau);

  // Baies de travail : une bande sous chaque rangée de bureaux. Sans elles le plateau
  // est une grande surface uniforme où les six postes flottent sans rien qui les relie.
  zone(-4, -6.2, x1, -2.8, PALETTE.solBaie);
  zone(-4, 2.8, x1, 6.2, PALETTE.solBaie);

  // Zones d'usage.
  zone(-11, -7, -5.6, -2.6, PALETTE.zoneReunion);
  zone(-11, 2.6, -5.6, 7, PALETTE.zoneDetente);
  zone(-11, -1.6, -8.4, 2.6, PALETTE.zoneCafe);
  zone(7.4, 0.6, 11, 4.4, PALETTE.zoneDetente);

  // Allée de circulation : elle prolonge la porte vers l'est et explique d'un regard
  // pourquoi les agents passent tous par là.
  zone(-4, -1, x1, 1, PALETTE.solAllee);

  // Liserés ocre le long de l'allée — la seule touche franchement colorée du sol,
  // réservée à l'axe de circulation principal.
  g.fillStyle = PALETTE.ocre;
  g.globalAlpha = 0.5;
  g.fillRect(px(-4), pz(-1) - 2, (x1 + 4) * PPM, 4);
  g.fillRect(px(-4), pz(1) - 2, (x1 + 4) * PPM, 4);
  // Seuil de porte, en terre cuite : marque l'ouverture dans la cloison.
  g.fillStyle = PALETTE.terre;
  g.globalAlpha = 0.65;
  g.fillRect(px(-5.2), pz(-1), 1.4 * PPM, 2 * PPM);
  g.globalAlpha = 1;

  // Trame : une ligne par mètre, appuyée tous les quatre. Elle donne l'échelle et
  // rappelle un plancher technique — sans elle les grandes zones paraissent plates.
  for (let x = x0; x <= x1; x += 1) {
    g.fillStyle = (x % 4 === 0) ? PALETTE.grilleForte : PALETTE.grille;
    g.fillRect(px(x) - 0.5, 0, 1, canvas.height);
  }
  for (let z = z0; z <= z1; z += 1) {
    g.fillStyle = (z % 4 === 0) ? PALETTE.grilleForte : PALETTE.grille;
    g.fillRect(0, pz(z) - 0.5, canvas.width, 1);
  }

  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return tex;
}

/* --------------------------------------------------------------------------- */
/* Poste informatique                                                           */
/* --------------------------------------------------------------------------- */

/**
 * Écran + pied + clavier, en géométrie primitive.
 *
 * Le kit de mobilier ne contient aucun ordinateur, et c'est justement l'objet dont on
 * a le plus besoin : sans lui, un agent assis « au travail » est indiscernable d'un
 * agent assis qui attend. Le construire ici plutôt que d'aller chercher un modèle a un
 * avantage décisif — la dalle est un matériau à nous, dont on pilote l'émission image
 * par image. C'est ce qui permet d'allumer l'écran quand l'agent produit.
 *
 * L'écran fait face à `+z`, c'est-à-dire à la chaise, elle-même toujours placée à
 * `+CHAIR_OFFSET` du centre de la table.
 */
function buildComputer() {
  const group = new THREE.Group();

  const sombre = new THREE.MeshStandardMaterial({ color: 0x1e2028, roughness: 0.6, metalness: 0.2 });

  const pied = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.14, 0.04, 12), sombre);
  pied.position.y = 0.02;
  group.add(pied);

  const mat = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.18, 0.05), sombre);
  mat.position.y = 0.13;
  group.add(mat);

  const chassis = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.44, 0.04), sombre);
  chassis.position.set(0, 0.44, 0);
  chassis.castShadow = true;
  group.add(chassis);

  // La dalle : émissive, à intensité pilotée. `toneMapped: false` la garde franche
  // même sous l'exposition ACES du rendu, sans quoi l'allumage se verrait à peine.
  const screen = new THREE.MeshStandardMaterial({
    color: 0x0d1016,
    emissive: new THREE.Color(0x8fb7ff),
    emissiveIntensity: 0,
    roughness: 0.35,
    toneMapped: false,
  });
  const dalle = new THREE.Mesh(new THREE.PlaneGeometry(0.64, 0.36), screen);
  dalle.position.set(0, 0.44, 0.021);
  group.add(dalle);

  const clavier = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.02, 0.18), sombre);
  clavier.position.set(0, 0.01, 0.34);
  group.add(clavier);

  // Tapis de souris + souris : deux volumes minuscules, mais ce sont eux qui font
  // lire le plan de travail comme un poste occupé plutôt que comme une table nue.
  const tapis = new THREE.Mesh(
    new THREE.BoxGeometry(0.2, 0.006, 0.16),
    new THREE.MeshStandardMaterial({ color: 0x2b2f3d, roughness: 0.95 }),
  );
  tapis.position.set(0.36, 0.003, 0.32);
  group.add(tapis);

  const souris = new THREE.Mesh(new THREE.SphereGeometry(0.045, 10, 8), sombre);
  souris.scale.set(1, 0.55, 1.35);
  souris.position.set(0.36, 0.026, 0.32);
  group.add(souris);

  return { group, screen };
}

/* --------------------------------------------------------------------------- */
/* Surface praticable                                                           */
/* --------------------------------------------------------------------------- */

/** Vrai si le rectangle couvre, même partiellement, la cellule de centre (cx, cz). */
function rectCoversCell(r, cx, cz) {
  const demi = CELL / 2;
  return r.x0 < cx + demi && r.x1 > cx - demi && r.z0 < cz + demi && r.z1 > cz - demi;
}

/** Rectangle d'encombrement centré sur un point, à partir d'une largeur et d'une profondeur. */
function footprint(x, z, { w, d }) {
  return { x0: x - w / 2, x1: x + w / 2, z0: z - d / 2, z1: z + d / 2 };
}

/**
 * Construit le maillage de navigation à partir du plan.
 *
 * Une cellule libre donne deux triangles ; deux cellules voisines partagent leurs
 * sommets, donc `buildNavMesh` les relie. Deux cellules séparées par une cloison ne
 * sont pas voisines : aucun lien n'existe, et `moveOnNav` n'a alors aucun chemin à
 * proposer au travers — le mur tient sans avoir à être testé séparément.
 */
function buildWalkableMesh(bloques) {
  const { x0, x1, z0, z1 } = LAYOUT.floor;
  const sommets = [];

  for (let cx = x0 + CELL / 2; cx < x1; cx += CELL) {
    for (let cz = z0 + CELL / 2; cz < z1; cz += CELL) {
      if (bloques.some((r) => rectCoversCell(r, cx, cz))) continue;
      const a = cx - CELL / 2;
      const b = cx + CELL / 2;
      const c = cz - CELL / 2;
      const d = cz + CELL / 2;
      // Deux triangles, sommets en coordonnées exactes : la fusion par position du
      // constructeur de maillage recolle alors parfaitement les cellules voisines.
      sommets.push(a, 0, c, b, 0, c, b, 0, d);
      sommets.push(a, 0, c, b, 0, d, a, 0, d);
    }
  }

  const geom = new THREE.BufferGeometry();
  geom.setAttribute('position', new THREE.Float32BufferAttribute(sommets, 3));
  const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ visible: false }));
  mesh.name = 'navMesh';
  mesh.visible = false;
  return mesh;
}

/**
 * Vérifie que tous les points d'intérêt communiquent entre eux.
 *
 * Le contrôle « le point est sur une case libre » ne suffit pas : du mobilier ajouté
 * au milieu d'une salle peut isoler une poche de cellules parfaitement praticables
 * mais inatteignables. L'agent qui y flâne s'y retrouve enfermé, ou n'arrive jamais à
 * son bureau — sans erreur, sans message, avec pour seul symptôme un agent qui « ne
 * fait rien ». Un parcours en largeur depuis le premier point le dit tout de suite.
 */
function unreachablePois(pois, bloques) {
  const { x0, x1, z0, z1 } = LAYOUT.floor;
  const key = (cx, cz) => `${cx},${cz}`;
  const libre = new Set();

  for (let cx = x0 + CELL / 2; cx < x1; cx += CELL) {
    for (let cz = z0 + CELL / 2; cz < z1; cz += CELL) {
      if (!bloques.some((r) => rectCoversCell(r, cx, cz))) libre.add(key(cx, cz));
    }
  }

  const cellOf = (p) => key(Math.floor(p.x) + 0.5, Math.floor(p.z) + 0.5);
  const entries = Object.entries(pois);
  if (!entries.length) return [];

  const depart = cellOf(entries[0][1]);
  if (!libre.has(depart)) return entries.map(([id]) => id);

  const vus = new Set([depart]);
  const file = [depart];
  while (file.length) {
    const [cx, cz] = file.pop().split(',').map(Number);
    for (const [dx, dz] of [[1, 0], [-1, 0], [0, 1], [0, -1]]) {
      const k = key(cx + dx, cz + dz);
      if (libre.has(k) && !vus.has(k)) { vus.add(k); file.push(k); }
    }
  }

  return entries.filter(([, p]) => !vus.has(cellOf(p))).map(([id]) => id);
}

/* --------------------------------------------------------------------------- */
/* Construction                                                                 */
/* --------------------------------------------------------------------------- */

/**
 * Monte le bureau.
 *
 * @returns {Promise<{group: THREE.Group, navMesh: THREE.Mesh, pois: Record<string, THREE.Vector3>, deskAngles: Record<string, number>, screens: Record<string, THREE.Material>}>}
 */
export async function buildOffice(loader) {
  const group = new THREE.Group();
  group.name = 'office';
  const cache = new Map();
  const pois = {};
  const deskAngles = {};
  /** Matériau de dalle par poste : la scène y pilote l'allumage selon l'état de l'agent. */
  const screens = {};

  /* --- Sol ----------------------------------------------------------------- */
  const { x0, x1, z0, z1 } = LAYOUT.floor;
  const sol = new THREE.Mesh(
    new THREE.PlaneGeometry(x1 - x0, z1 - z0),
    new THREE.MeshStandardMaterial({ map: buildFloorTexture(), roughness: 0.94, metalness: 0 }),
  );
  sol.rotation.x = -Math.PI / 2;
  sol.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2);
  sol.receiveShadow = true;
  group.add(sol);

  // Muret périphérique : borne le plateau, qui flotterait sinon dans le vide. Assez bas
  // (0,5 m) pour ne jamais masquer un agent depuis la caméra isométrique, assez haut
  // pour que le plateau se lise comme une pièce et non comme une dalle posée sur rien.
  // Purement décoratif — la limite réelle est celle du maillage de navigation.
  const cx = (x0 + x1) / 2;
  const cz = (z0 + z1) / 2;
  const matPlinthe = new THREE.MeshStandardMaterial({ color: PALETTE.plinthe, roughness: 1 });
  const matCap = new THREE.MeshStandardMaterial({ color: PALETTE.plintheCap, roughness: 0.8 });
  const murets = [
    { w: x1 - x0 + 0.6, d: 0.3, x: cx, z: z0 - 0.15 },
    { w: x1 - x0 + 0.6, d: 0.3, x: cx, z: z1 + 0.15 },
    { w: 0.3, d: z1 - z0, x: x0 - 0.15, z: cz },
    { w: 0.3, d: z1 - z0, x: x1 + 0.15, z: cz },
  ];
  for (const m of murets) {
    const bloc = new THREE.Mesh(new THREE.BoxGeometry(m.w, 0.5, m.d), matPlinthe);
    bloc.position.set(m.x, 0.25, m.z);
    bloc.receiveShadow = true;
    group.add(bloc);
    // Couvre-mur ocre : un liseré chaud qui dessine le contour de la pièce.
    const cap = new THREE.Mesh(new THREE.BoxGeometry(m.w + 0.06, 0.06, m.d + 0.06), matCap);
    cap.position.set(m.x, 0.53, m.z);
    group.add(cap);
  }

  /* --- Cloisons ------------------------------------------------------------- */
  const matMur = new THREE.MeshStandardMaterial({ color: PALETTE.mur, roughness: 0.9 });
  const matCorniche = new THREE.MeshStandardMaterial({ color: PALETTE.murCorniche, roughness: 0.75 });
  for (const m of LAYOUT.walls) {
    const w = m.x1 - m.x0;
    const d = m.z1 - m.z0;
    const mur = new THREE.Mesh(new THREE.BoxGeometry(w, 2.4, d), matMur);
    mur.position.set((m.x0 + m.x1) / 2, 1.2, (m.z0 + m.z1) / 2);
    mur.castShadow = true;
    mur.receiveShadow = true;
    group.add(mur);

    // Corniche ocre en tête de cloison : elle souligne la seule ligne verticale de la
    // scène et donne au plateau son accent chaud à hauteur d'œil.
    //
    // Débordante en x, **fine en épaisseur** : la cloison fait 1 m d'épaisseur, et une
    // corniche qui la couvrait entièrement offrait à la caméra isométrique un bandeau
    // ocre de 1 m sur 6 — la plus grande surface colorée de la scène, pour un élément
    // censé n'être qu'un liseré. On ne coiffe donc que les deux arêtes.
    for (const cote of [-1, 1]) {
      const liseré = new THREE.Mesh(new THREE.BoxGeometry(0.18, 0.14, d + 0.06), matCorniche);
      liseré.position.set((m.x0 + m.x1) / 2 + cote * (w / 2 + 0.02), 2.43, (m.z0 + m.z1) / 2);
      group.add(liseré);
    }
  }

  /* --- Postes de travail ---------------------------------------------------- */
  const bloques = LAYOUT.walls.map((m) => ({ ...m }));

  for (const [i, poste] of LAYOUT.desks.entries()) {
    const table = await loadPiece(loader, 'table_medium', cache);
    table.scale.setScalar(KIT_SCALE);
    table.position.set(poste.x, 0, poste.z);
    // Seul le plan de travail projette : sa silhouette compte, celle d'un livre non.
    table.traverse((c) => { if (c.isMesh) c.castShadow = true; });
    group.add(table);

    // La chaise regarde la table ; l'agent qui s'y assoit prend le même cap.
    const chaise = await loadPiece(loader, i % 2 ? 'chair_A' : 'chair_A_wood', cache);
    chaise.scale.setScalar(KIT_SCALE);
    chaise.position.set(poste.x, 0, poste.z + CHAIR_OFFSET);
    chaise.rotation.y = Math.PI;
    group.add(chaise);

    // Un peu de vie sur les bureaux, sans encombrer davantage le sol.
    for (const objet of DESK_CLUTTER[i % DESK_CLUTTER.length]) {
      const piece = await loadPiece(loader, objet.model, cache);
      piece.scale.setScalar(KIT_SCALE);
      piece.position.set(poste.x + objet.dx, 0.75, poste.z + objet.dz);
      piece.rotation.y = objet.rot;
      group.add(piece);
    }

    // Poste informatique : c'est lui qui rend le travail lisible. L'écran est le seul
    // objet de la scène dont l'intensité varie — allumé, on voit d'un coup d'œil quel
    // bureau produit quelque chose, sans avoir à lire la moindre étiquette.
    const { group: ordi, screen } = buildComputer();
    ordi.position.set(poste.x, 0.75, poste.z);
    group.add(ordi);
    screens[poste.id] = screen;

    pois[poste.id] = new THREE.Vector3(poste.x, 0, poste.z + CHAIR_OFFSET);
    // Cap vers la table : `Math.atan2(dx, dz)` est la convention de lacet de la scène.
    deskAngles[poste.id] = Math.atan2(0, -CHAIR_OFFSET);

    bloques.push(footprint(poste.x, poste.z, DESK_FOOTPRINT));
  }

  /* --- Décor ---------------------------------------------------------------- */
  for (const p of LAYOUT.props) {
    const obj = await loadPiece(loader, p.model, cache);
    obj.scale.setScalar(KIT_SCALE);
    obj.position.set(p.x, p.y || 0, p.z);
    obj.rotation.y = p.rot || 0;
    const projette = PROJETTENT.has(p.model);
    obj.traverse((c) => { if (c.isMesh) { c.castShadow = projette; c.receiveShadow = true; } });
    group.add(obj);

    if (p.blocks) bloques.push(footprint(p.x, p.z, p.blocks));
  }

  /* --- Cadres au mur --------------------------------------------------------- */
  for (const f of LAYOUT.frames) {
    const cadre = await loadPiece(loader, f.model, cache);
    cadre.scale.setScalar(KIT_SCALE);
    cadre.position.set(f.x, f.y, f.z);
    cadre.rotation.y = f.rot;
    group.add(cadre);
  }

  /* --- Zones de flânerie ---------------------------------------------------- */
  for (const r of LAYOUT.roam) {
    pois[r.id] = new THREE.Vector3(r.x, 0, r.z);
  }

  const navMesh = buildWalkableMesh(bloques);
  group.add(navMesh);

  // Garde-fou : un point d'intérêt tombé sur une case encombrée est un agent qui naît
  // hors de la surface praticable. Plus aucun chemin ne part de lui et il reste planté
  // là, sans erreur ni message — la panne est parfaitement silencieuse, et c'est ce qui
  // la rend coûteuse. On la rend bruyante.
  const horsSurface = Object.entries(pois).filter(
    ([, p]) => bloques.some((r) => rectCoversCell(r, p.x, p.z))
      || p.x <= LAYOUT.floor.x0 || p.x >= LAYOUT.floor.x1
      || p.z <= LAYOUT.floor.z0 || p.z >= LAYOUT.floor.z1,
  );
  if (horsSurface.length) {
    console.error(
      'office-kit : points d\'intérêt hors surface praticable —',
      horsSurface.map(([id]) => id).join(', '),
    );
  }

  const isoles = unreachablePois(pois, bloques);
  if (isoles.length) {
    console.error('office-kit : points d\'intérêt inatteignables —', isoles.join(', '));
  }

  return { group, navMesh, pois, deskAngles, screens };
}

/** Identifiants des postes, dans l'ordre du pipeline. */
export const DESK_IDS = LAYOUT.desks.map((d) => d.id);
/** Identifiants des zones de flânerie. */
export const ROAM_IDS = LAYOUT.roam.map((r) => r.id);
