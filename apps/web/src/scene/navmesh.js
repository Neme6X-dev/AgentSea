/**
 * Navigation sur le maillage `navMesh` du bureau.
 *
 * Le modèle fournit une surface de sol praticable (plane) que la scène se contentait de
 * rendre invisible. Elle sert ici à ce pour quoi elle existe : faire cheminer les agents
 * **autour** des murs et du mobilier plutôt qu'au travers.
 *
 * Quatre étapes :
 *   1. extraction des triangles en coordonnées monde, fusion des sommets dupliqués et
 *      calcul du voisinage ;
 *   2. indexation spatiale (grille uniforme) pour localiser un point sans parcourir tout
 *      le maillage — cette recherche a lieu plusieurs fois par frame et par agent ;
 *   3. A* sur le graphe des triangles → un couloir de triangles ;
 *   4. « funnel » (tirage de corde) → une suite de points en ligne droite dans ce
 *      couloir, sans le zigzag qu'on obtiendrait en reliant les milieux d'arêtes.
 *
 * Tout se calcule en 2D (X/Z) : la surface est plane, une troisième dimension
 * n'apporterait que du bruit numérique.
 *
 * Convention d'orientation : `cross(a, b, c) > 0` signifie « c est à gauche de a→b ».
 * Les triangles sont réorientés à la construction pour que `cross(v0, v1, v2) >= 0`, et
 * les portails en découlent : en franchissant l'arête `v[e] → v[e+1]`, on sort du
 * triangle avec `v[e+1]` sur sa gauche. Le funnel ne fonctionne que si cette convention
 * est tenue de bout en bout.
 */
import * as THREE from 'three';

/** Précision de fusion des sommets dupliqués dans le tampon de géométrie. */
const WELD = 1e-3;

/** Tolérance des tests d'appartenance : un point pile sur une arête est « dedans ». */
const EPS = 1e-6;

const cellKey = (x, z) => `${Math.round(x / WELD)}:${Math.round(z / WELD)}`;

/** Double de l'aire signée — positif si `c` est à gauche de `a→b`. */
function cross(a, b, c) {
  return (b.x - a.x) * (c.z - a.z) - (c.x - a.x) * (b.z - a.z);
}

function dist(a, b) {
  return Math.hypot(a.x - b.x, a.z - b.z);
}

/** Égalité de position (et non d'identité) : le funnel compare des points recalculés. */
function same(a, b) {
  return Math.abs(a.x - b.x) < WELD && Math.abs(a.z - b.z) < WELD;
}

function clampInt(v, lo, hi) {
  return v < lo ? lo : v > hi ? hi : v;
}

/* --- Construction ----------------------------------------------------------- */

/**
 * Grille uniforme des triangles, pour localiser un point en temps constant.
 *
 * `locate` était un balayage linéaire du maillage entier, appelé pour chaque agent à
 * chaque frame (et deux fois quand le point tombait hors surface). La grille ramène ça
 * au contenu d'une case.
 */
function buildGrid(tris) {
  let minX = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxZ = -Infinity;
  for (const t of tris) {
    for (const v of t.v) {
      if (v.x < minX) minX = v.x;
      if (v.x > maxX) maxX = v.x;
      if (v.z < minZ) minZ = v.z;
      if (v.z > maxZ) maxZ = v.z;
    }
  }

  const largeur = Math.max(maxX - minX, 1e-3);
  const profondeur = Math.max(maxZ - minZ, 1e-3);
  // Environ une case par triangle : assez fin pour trier, assez grossier pour ne pas
  // remplir la mémoire de cases vides.
  const cote = Math.max(Math.sqrt((largeur * profondeur) / tris.length), 1e-3);
  const nx = clampInt(Math.ceil(largeur / cote), 1, 128);
  const nz = clampInt(Math.ceil(profondeur / cote), 1, 128);
  const cellX = largeur / nx;
  const cellZ = profondeur / nz;
  const cells = new Array(nx * nz);

  tris.forEach((t, ti) => {
    const x0 = Math.min(t.v[0].x, t.v[1].x, t.v[2].x);
    const x1 = Math.max(t.v[0].x, t.v[1].x, t.v[2].x);
    const z0 = Math.min(t.v[0].z, t.v[1].z, t.v[2].z);
    const z1 = Math.max(t.v[0].z, t.v[1].z, t.v[2].z);
    const ix0 = clampInt(Math.floor((x0 - minX) / cellX), 0, nx - 1);
    const ix1 = clampInt(Math.floor((x1 - minX) / cellX), 0, nx - 1);
    const iz0 = clampInt(Math.floor((z0 - minZ) / cellZ), 0, nz - 1);
    const iz1 = clampInt(Math.floor((z1 - minZ) / cellZ), 0, nz - 1);
    for (let iz = iz0; iz <= iz1; iz++) {
      for (let ix = ix0; ix <= ix1; ix++) {
        (cells[iz * nx + ix] ??= []).push(ti);
      }
    }
  });

  return { minX, minZ, nx, nz, cellX, cellZ, cells, pas: Math.min(cellX, cellZ) };
}

/**
 * Construit le graphe de navigation à partir du maillage `navMesh`.
 *
 * Retourne `null` si le maillage est absent ou inexploitable : la scène doit pouvoir
 * fonctionner sans, quitte à revenir au déplacement en ligne droite.
 */
export function buildNavMesh(mesh) {
  if (!mesh || !mesh.geometry) return null;

  const geom = mesh.geometry;
  const pos = geom.getAttribute('position');
  if (!pos) return null;

  mesh.updateWorldMatrix(true, false);
  const matrix = mesh.matrixWorld;

  // Sommets en coordonnées monde, fusionnés par position. Le tampon de géométrie
  // duplique les sommets partagés ; sans fusion, deux triangles voisins ne se
  // reconnaissent pas et le maillage se retrouve troué de frontières fictives.
  const tmp = new THREE.Vector3();
  const canon = new Map();
  const sommet = (i) => {
    tmp.fromBufferAttribute(pos, i).applyMatrix4(matrix);
    const k = cellKey(tmp.x, tmp.z);
    let p = canon.get(k);
    if (!p) {
      p = { id: canon.size, x: tmp.x, y: tmp.y, z: tmp.z };
      canon.set(k, p);
    }
    return p;
  };

  const index = geom.getIndex();
  const count = index ? index.count : pos.count;
  const tris = [];
  for (let i = 0; i + 2 < count; i += 3) {
    const a = sommet(index ? index.getX(i) : i);
    const b = sommet(index ? index.getX(i + 1) : i + 1);
    const c = sommet(index ? index.getX(i + 2) : i + 2);

    // Triangle dégénéré (aire nulle, ou deux sommets fusionnés) : il n'apporte aucune
    // surface praticable et fausserait le voisinage comme le funnel.
    const aire = cross(a, b, c);
    if (Math.abs(aire) < 1e-9) continue;

    // Winding uniformisé : le funnel s'appuie sur une orientation cohérente pour
    // distinguer sa gauche de sa droite.
    const v = aire > 0 ? [a, b, c] : [a, c, b];

    tris.push({
      v,
      centroid: {
        x: (v[0].x + v[1].x + v[2].x) / 3,
        z: (v[0].z + v[1].z + v[2].z) / 3,
      },
      neighbours: [], // { tri, left, right } — arête partagée, orientée
    });
  }
  if (!tris.length) return null;

  // Voisinage : deux triangles se touchent s'ils partagent une arête (deux sommets).
  const edges = new Map();
  tris.forEach((tri, ti) => {
    for (let e = 0; e < 3; e++) {
      const a = tri.v[e];
      const b = tri.v[(e + 1) % 3];
      const k = a.id < b.id ? `${a.id}|${b.id}` : `${b.id}|${a.id}`;
      let bucket = edges.get(k);
      if (!bucket) edges.set(k, (bucket = []));
      bucket.push({ ti, e });
    }
  });

  let bordures = 0;
  for (const partages of edges.values()) {
    if (partages.length < 2) {
      bordures++;
      continue; // arête de bord : rien au-delà
    }
    // Maillage non manifold (plus de deux faces sur une arête) : on relie tout de même
    // les faces deux à deux, un couloir imparfait valant mieux qu'une zone injoignable.
    for (let i = 0; i < partages.length; i++) {
      for (let j = i + 1; j < partages.length; j++) {
        link(tris, partages[i], partages[j]);
        link(tris, partages[j], partages[i]);
      }
    }
  }

  return {
    tris,
    grid: buildGrid(tris),
    y: tris[0].v[0].y,
    stats: { triangles: tris.length, bordures },
  };
}

/**
 * Enregistre `depuis → vers` avec le portail orienté du point de vue de `depuis`.
 *
 * En franchissant l'arête `v[e] → v[e+1]` d'un triangle orienté positivement, on sort
 * avec `v[e+1]` à sa gauche et `v[e]` à sa droite. C'est cette orientation que le funnel
 * consomme ; l'inverser fait passer les agents du mauvais côté des angles.
 */
function link(tris, depuis, vers) {
  const tri = tris[depuis.ti];
  tri.neighbours.push({
    tri: vers.ti,
    left: tri.v[(depuis.e + 1) % 3],
    right: tri.v[depuis.e],
  });
}

/* --- Localisation ----------------------------------------------------------- */

/** Vrai si le point (X/Z) est dans le triangle. */
function inside(tri, p) {
  const [a, b, c] = tri.v;
  return cross(a, b, p) >= -EPS && cross(b, c, p) >= -EPS && cross(c, a, p) >= -EPS;
}

function closestOnSegment(a, b, p) {
  const dx = b.x - a.x;
  const dz = b.z - a.z;
  const l2 = dx * dx + dz * dz;
  if (l2 < 1e-12) return { x: a.x, z: a.z };
  let t = ((p.x - a.x) * dx + (p.z - a.z) * dz) / l2;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  return { x: a.x + dx * t, z: a.z + dz * t };
}

/** Point du triangle le plus proche de `p` (le point lui-même s'il est dedans). */
function closestOnTriangle(tri, p) {
  if (inside(tri, p)) return { x: p.x, z: p.z };
  let meilleur = null;
  let meilleureD = Infinity;
  for (let e = 0; e < 3; e++) {
    const q = closestOnSegment(tri.v[e], tri.v[(e + 1) % 3], p);
    const d = (q.x - p.x) ** 2 + (q.z - p.z) ** 2;
    if (d < meilleureD) {
      meilleureD = d;
      meilleur = q;
    }
  }
  return meilleur;
}

/** Triangles de la case contenant `p`, ou `null`. */
function bucketAt(nav, p) {
  const g = nav.grid;
  const ix = clampInt(Math.floor((p.x - g.minX) / g.cellX), 0, g.nx - 1);
  const iz = clampInt(Math.floor((p.z - g.minZ) / g.cellZ), 0, g.nz - 1);
  return g.cells[iz * g.nx + ix] || null;
}

/**
 * Triangle le plus proche de `p` et point correspondant sur sa surface.
 *
 * Recherche en couronnes autour de la case du point : on s'arrête dès qu'aucune couronne
 * plus lointaine ne peut faire mieux que le meilleur candidat déjà trouvé.
 */
function nearestTriangle(nav, p) {
  const g = nav.grid;
  const cx = clampInt(Math.floor((p.x - g.minX) / g.cellX), 0, g.nx - 1);
  const cz = clampInt(Math.floor((p.z - g.minZ) / g.cellZ), 0, g.nz - 1);
  const rayonMax = Math.max(g.nx, g.nz);

  let tri = -1;
  let meilleureD = Infinity;
  let point = null;

  for (let r = 0; r <= rayonMax; r++) {
    // Toute case de la couronne `r` est à au moins `(r-1) * pas` du point : inutile de
    // l'explorer si le candidat courant est déjà plus près.
    if (tri >= 0 && (r - 1) * g.pas > Math.sqrt(meilleureD)) break;

    for (let iz = cz - r; iz <= cz + r; iz++) {
      if (iz < 0 || iz >= g.nz) continue;
      const bordZ = iz === cz - r || iz === cz + r;
      for (let ix = cx - r; ix <= cx + r; ix++) {
        if (ix < 0 || ix >= g.nx) continue;
        if (r > 0 && !bordZ && ix !== cx - r && ix !== cx + r) continue;
        const bucket = g.cells[iz * g.nx + ix];
        if (!bucket) continue;
        for (const ti of bucket) {
          const q = closestOnTriangle(nav.tris[ti], p);
          const d = (q.x - p.x) ** 2 + (q.z - p.z) ** 2;
          if (d < meilleureD) {
            meilleureD = d;
            tri = ti;
            point = q;
          }
        }
      }
    }
  }

  return tri < 0 ? null : { tri, x: point.x, z: point.z };
}

/**
 * Index du triangle contenant le point, ou `-1`.
 *
 * `hint` est le dernier triangle connu de l'appelant : un agent qui avance d'un pas reste
 * presque toujours dans le même triangle ou chez un voisin immédiat, ce qui évite même
 * de consulter la grille.
 */
export function locate(nav, p, hint = -1) {
  if (!nav) return -1;

  if (hint >= 0 && hint < nav.tris.length) {
    if (inside(nav.tris[hint], p)) return hint;
    for (const voisin of nav.tris[hint].neighbours) {
      if (inside(nav.tris[voisin.tri], p)) return voisin.tri;
    }
  }

  const bucket = bucketAt(nav, p);
  if (bucket) {
    for (const ti of bucket) {
      if (inside(nav.tris[ti], p)) return ti;
    }
  }
  return -1;
}

/**
 * Ramène un point sur la surface praticable, **au plus près**.
 *
 * Le repli historique renvoyait le centre du triangle le plus proche : un agent poussé
 * de quelques centimètres hors du maillage se retrouvait téléporté au milieu d'une dalle,
 * parfois à plus d'un mètre. Comme la scène rappelle cette fonction à chaque frame, le
 * symptôme était un personnage qui saute sur place. Projeter sur le point le plus proche
 * corrige le débordement sans jamais déplacer visiblement l'agent.
 *
 * Retourne aussi le triangle atteint, à repasser en `hint` au tour suivant.
 */
export function projectToNav(nav, p, hint = -1) {
  if (!nav) return { x: p.x, z: p.z, tri: -1 };

  const ti = locate(nav, p, hint);
  if (ti >= 0) return { x: p.x, z: p.z, tri: ti };

  const proche = nearestTriangle(nav, p);
  if (!proche) return { x: p.x, z: p.z, tri: -1 };

  // Léger retrait vers l'intérieur : posé pile sur l'arête, le point ressort « dehors »
  // à la frame suivante au moindre arrondi, et l'agent vibre contre le mur.
  const c = nav.tris[proche.tri].centroid;
  const dx = c.x - proche.x;
  const dz = c.z - proche.z;
  const d = Math.hypot(dx, dz);
  const marge = Math.min(1e-3, d);
  return {
    x: d > 1e-9 ? proche.x + (dx / d) * marge : proche.x,
    z: d > 1e-9 ? proche.z + (dz / d) * marge : proche.z,
    tri: proche.tri,
  };
}

/** Variante sans triangle, conservée pour les appelants qui n'en ont pas l'usage. */
export function clampToNav(nav, p) {
  const q = projectToNav(nav, p);
  return { x: q.x, z: q.z };
}

/**
 * Déplace un point **le long de la surface**, sans jamais franchir de mur.
 *
 * `clampToNav` ne pouvait pas rendre ce service : c'est une projection de *point*, qui
 * répond « ce point est-il praticable ? » et non « le trajet l'est-il ? ». Or deux dalles
 * peuvent être voisines dans l'espace tout en étant séparées par une cloison — sans arête
 * commune, donc sans lien dans le graphe. Un pas (ou une poussée de `separate()`) qui
 * enjambe la cloison atterrit dans un triangle parfaitement valide de l'autre côté :
 * `projectToNav` n'y voit rien à redire et laisse passer. Le maillage du bureau compte
 * 148 arêtes de bord et deux endroits où 0,4 à 0,65 m à vol d'oiseau demandent 1,2 à
 * 2,2 m à pied — ce sont exactement les points de passage à travers les murs.
 *
 * Ici, le segment est suivi de triangle en triangle par le voisinage déjà construit. Sur
 * une arête de bord, le déplacement est arrêté net puis **glissé** le long du mur, ce qui
 * évite de rester collé à ramper contre l'obstacle.
 *
 * @returns {{x: number, z: number, tri: number}} position atteinte et triangle courant.
 */
export function moveOnNav(nav, from, to, hint = -1) {
  if (!nav) return { x: to.x, z: to.z, tri: -1 };

  let tri = locate(nav, from, hint);
  // Départ hors maillage (repositionnement, arrondi) : on raccroche au plus près plutôt
  // que de refuser le mouvement, sinon l'agent reste bloqué dehors indéfiniment.
  if (tri < 0) {
    const base = projectToNav(nav, from, hint);
    tri = base.tri;
    if (tri < 0) return { x: from.x, z: from.z, tri: -1 };
    from = { x: base.x, z: base.z };
  }

  let px = from.x;
  let pz = from.z;
  let qx = to.x;
  let qz = to.z;
  let glissements = 0;

  // Borne de sécurité : un pas ne traverse qu'une poignée de triangles. La boucle ne
  // doit jamais pouvoir tourner indéfiniment sur un maillage non manifold.
  for (let iter = 0; iter < 24; iter++) {
    const t = nav.tris[tri];
    if (inside(t, { x: qx, z: qz })) return { x: qx, z: qz, tri };

    // Arête franchie en premier par le segment p → q.
    let meilleureT = Infinity;
    let sortie = -1;
    for (let e = 0; e < 3; e++) {
      const a = t.v[e];
      const b = t.v[(e + 1) % 3];
      // Winding positif : un point intérieur est à gauche de chaque arête. Sortir par
      // celle-ci, c'est passer à droite.
      const cq = (b.x - a.x) * (qz - a.z) - (b.z - a.z) * (qx - a.x);
      if (cq >= 0) continue;
      const cp = (b.x - a.x) * (pz - a.z) - (b.z - a.z) * (px - a.x);
      const denom = cp - cq;
      if (Math.abs(denom) < EPS) continue;
      const s = cp / denom; // paramètre le long de p → q
      if (s < -EPS || s > meilleureT) continue;
      meilleureT = Math.max(0, s);
      sortie = e;
    }

    // Aucune sortie identifiable (arrondi sur un sommet) : on s'en tient au point de
    // départ, que l'on sait praticable, plutôt que de valider un saut non vérifié.
    if (sortie < 0) return { x: px, z: pz, tri };

    const a = t.v[sortie];
    const b = t.v[(sortie + 1) % 3];
    const voisin = t.neighbours.find((n) => n.right === a && n.left === b)
      || t.neighbours.find((n) => (n.right === b && n.left === a));

    // Point de contact sur l'arête, très légèrement en retrait pour ne pas se poser
    // pile dessus (au prochain tour, l'arrondi le ferait basculer dehors).
    const hx = px + (qx - px) * meilleureT;
    const hz = pz + (qz - pz) * meilleureT;

    if (voisin) {
      px = hx;
      pz = hz;
      tri = voisin.tri;
      continue;
    }

    /* --- Mur : on s'arrête et on glisse ---------------------------------------- */
    if (glissements >= 2) return { x: px, z: pz, tri };
    glissements++;

    const ex = b.x - a.x;
    const ez = b.z - a.z;
    const elen = Math.hypot(ex, ez);
    if (elen < EPS) return { x: px, z: pz, tri };
    const ux = ex / elen;
    const uz = ez / elen;

    // Reste du déplacement projeté sur le mur : l'agent longe l'obstacle au lieu de
    // s'y écraser. On repart du point de contact, légèrement rentré vers l'intérieur.
    const restX = qx - hx;
    const restZ = qz - hz;
    const along = restX * ux + restZ * uz;

    const nx = t.centroid.x - hx;
    const nz = t.centroid.z - hz;
    const nlen = Math.hypot(nx, nz);
    const marge = 1e-3;
    px = hx + (nlen > EPS ? (nx / nlen) * marge : 0);
    pz = hz + (nlen > EPS ? (nz / nlen) * marge : 0);
    qx = px + ux * along;
    qz = pz + uz * along;
  }

  return { x: px, z: pz, tri };
}

/* --- Chemin ----------------------------------------------------------------- */

/** Tas binaire minimal — A* sortait son minimum par balayage linéaire de la file. */
class MinHeap {
  constructor() {
    this.items = [];
    this.keys = [];
  }

  get size() {
    return this.items.length;
  }

  push(item, key) {
    this.items.push(item);
    this.keys.push(key);
    let i = this.items.length - 1;
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (this.keys[p] <= this.keys[i]) break;
      this._swap(i, p);
      i = p;
    }
  }

  pop() {
    const sommet = this.items[0];
    const item = this.items.pop();
    const key = this.keys.pop();
    if (this.items.length) {
      this.items[0] = item;
      this.keys[0] = key;
      let i = 0;
      for (;;) {
        const g = 2 * i + 1;
        const d = g + 1;
        let m = i;
        if (g < this.keys.length && this.keys[g] < this.keys[m]) m = g;
        if (d < this.keys.length && this.keys[d] < this.keys[m]) m = d;
        if (m === i) break;
        this._swap(i, m);
        i = m;
      }
    }
    return sommet;
  }

  _swap(i, j) {
    const it = this.items[i];
    this.items[i] = this.items[j];
    this.items[j] = it;
    const k = this.keys[i];
    this.keys[i] = this.keys[j];
    this.keys[j] = k;
  }
}

/**
 * A* sur le graphe des triangles.
 *
 * Retourne `{ chemin, atteint }`. Quand la cible est injoignable (zone séparée du reste
 * du maillage), on rend le meilleur couloir exploré plutôt que `null` : l'agent s'approche
 * autant que possible au lieu de traverser les murs en ligne droite, ce que faisait le
 * repli précédent.
 */
function corridor(nav, startTri, goalTri, goal) {
  if (startTri === goalTri) return { chemin: [startTri], atteint: true };

  const open = new MinHeap();
  const g = new Map([[startTri, 0]]);
  const from = new Map();
  const closed = new Set();

  const h0 = dist(nav.tris[startTri].centroid, goal);
  open.push(startTri, h0);

  let plusProche = startTri;
  let plusProcheH = h0;

  const remonter = (fin) => {
    const chemin = [fin];
    let n = fin;
    while (from.has(n)) {
      n = from.get(n);
      chemin.unshift(n);
    }
    return chemin;
  };

  while (open.size) {
    const cur = open.pop();
    if (closed.has(cur)) continue;
    if (cur === goalTri) return { chemin: remonter(cur), atteint: true };
    closed.add(cur);

    const h = dist(nav.tris[cur].centroid, goal);
    if (h < plusProcheH) {
      plusProcheH = h;
      plusProche = cur;
    }

    for (const voisin of nav.tris[cur].neighbours) {
      if (closed.has(voisin.tri)) continue;
      const cout =
        (g.get(cur) ?? Infinity) + dist(nav.tris[cur].centroid, nav.tris[voisin.tri].centroid);
      if (cout < (g.get(voisin.tri) ?? Infinity)) {
        from.set(voisin.tri, cur);
        g.set(voisin.tri, cout);
        open.push(voisin.tri, cout + dist(nav.tris[voisin.tri].centroid, goal));
      }
    }
  }

  return { chemin: remonter(plusProche), atteint: false };
}

/**
 * Rétrécit un portail de `radius` à chaque extrémité.
 *
 * Le tirage de corde passe exactement par les sommets du couloir, donc au ras des angles
 * de murs : un personnage large d'une trentaine de centimètres y rentre visiblement
 * dedans. Reculer les extrémités du portail écarte le chemin de la même distance. Le
 * facteur est borné à un peu moins de la moitié pour qu'un portail étroit se réduise à son
 * milieu sans jamais s'inverser.
 */
function shrinkPortal(left, right, radius) {
  const dx = right.x - left.x;
  const dz = right.z - left.z;
  const len = Math.hypot(dx, dz);
  if (len < 1e-6 || radius <= 0) return { left, right };
  const t = Math.min(radius / len, 0.49);
  return {
    left: { x: left.x + dx * t, z: left.z + dz * t },
    right: { x: right.x - dx * t, z: right.z - dz * t },
  };
}

/** Portails (arêtes partagées) le long d'un couloir de triangles. */
function portalsFor(nav, chemin, start, goal, radius) {
  const list = [{ left: start, right: start }];
  for (let i = 0; i < chemin.length - 1; i++) {
    const lien = nav.tris[chemin[i]].neighbours.find((n) => n.tri === chemin[i + 1]);
    if (!lien) continue;
    list.push(shrinkPortal(lien.left, lien.right, radius));
  }
  list.push({ left: goal, right: goal });
  return list;
}

/**
 * Tirage de corde (*simple stupid funnel*) : réduit le couloir à une ligne brisée
 * tendue. Sans lui, relier les milieux d'arêtes donnerait une marche en zigzag.
 *
 * Les comparaisons d'apex se font par position et non par identité : le rétrécissement
 * des portails fabrique de nouveaux points, et une comparaison d'objets ne reconnaîtrait
 * plus un apex pourtant confondu avec le bord de la corde — l'algorithme repartait alors
 * en boucle sur le même segment. Le compteur `garde` reste un filet : une géométrie
 * pathologique ne doit jamais figer la boucle de rendu.
 */
function funnel(portails) {
  const points = [];
  let apex = portails[0].left;
  let left = portails[0].left;
  let right = portails[0].right;
  let iApex = 0;
  let iLeft = 0;
  let iRight = 0;

  let garde = 0;
  const maxIter = portails.length * 4 + 32;

  for (let i = 1; i < portails.length; i++) {
    if (++garde > maxIter) break;
    const nl = portails[i].left;
    const nr = portails[i].right;

    // Côté droit : `nr` resserre la corde s'il passe à gauche de apex→right.
    if (cross(apex, right, nr) >= 0) {
      if (same(apex, right) || cross(apex, left, nr) < 0) {
        right = nr;
        iRight = i;
      } else {
        // La droite a dépassé la gauche : l'apex saute sur le point gauche, qui devient
        // un sommet du chemin, et le balayage reprend de là.
        points.push(left);
        apex = left;
        iApex = iLeft;
        right = apex;
        iRight = iApex;
        i = iApex;
        continue;
      }
    }

    // Côté gauche : symétrique.
    if (cross(apex, left, nl) <= 0) {
      if (same(apex, left) || cross(apex, right, nl) > 0) {
        left = nl;
        iLeft = i;
      } else {
        points.push(right);
        apex = right;
        iApex = iRight;
        left = apex;
        iLeft = iApex;
        i = iApex;
        continue;
      }
    }
  }

  const fin = portails[portails.length - 1].left;
  if (!points.length || !same(points[points.length - 1], fin)) points.push(fin);
  return points;
}

/**
 * Itinéraire praticable entre deux points.
 *
 * Retourne une suite de points à suivre. Le dernier n'est la destination demandée que si
 * elle est réellement joignable : sinon, c'est le point praticable le plus proche — mieux
 * vaut un agent qui s'arrête à la bonne porte qu'un agent qui traverse le mur.
 *
 * @param {object} nav        graphe rendu par `buildNavMesh`, ou `null`
 * @param {{x,z}} start       position de départ
 * @param {{x,z}} goal        destination visée
 * @param {number} radius     demi-largeur de l'agent, pour ne pas raser les angles
 * @param {number} startTri   triangle connu du départ (accélère la localisation)
 */
export function findPath(nav, start, goal, { radius = 0, startTri = -1 } = {}) {
  const direct = [{ x: goal.x, z: goal.z }];
  if (!nav) return direct;

  const a = projectToNav(nav, start, startTri);
  const b = projectToNav(nav, goal);
  if (a.tri < 0 || b.tri < 0) return direct;
  if (a.tri === b.tri) return [{ x: b.x, z: b.z }];

  const { chemin, atteint } = corridor(nav, a.tri, b.tri, b);
  if (!chemin.length) return direct;
  if (chemin.length === 1) return [{ x: b.x, z: b.z }];

  // Cible injoignable : on s'arrête au centre du dernier triangle atteignable.
  const fin = atteint ? b : nav.tris[chemin[chemin.length - 1]].centroid;

  const portails = portalsFor(nav, chemin, a, fin, radius);
  let points;
  try {
    points = funnel(portails);
  } catch {
    points = null;
  }

  // Repli sur les milieux d'arêtes : moins direct, mais toujours dans le couloir.
  if (!points || !points.length) {
    points = portails.slice(1, -1).map((p) => ({
      x: (p.left.x + p.right.x) / 2,
      z: (p.left.z + p.right.z) / 2,
    }));
    points.push({ x: fin.x, z: fin.z });
  }

  // Le funnel émet un point à chaque changement d'apex, ce qui produit des doublons quand
  // deux portails partagent un sommet. Un agent s'y arrêterait deux fois.
  const sortie = [];
  for (const p of points) {
    const dernier = sortie[sortie.length - 1];
    if (!dernier || Math.hypot(p.x - dernier.x, p.z - dernier.z) > 1e-3) {
      sortie.push({ x: p.x, z: p.z });
    }
  }
  return sortie.length ? sortie : direct;
}
