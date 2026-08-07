/**
 * Graphiques SVG du back-office — sans aucune dépendance.
 *
 * ## Pourquoi pas Chart.js ou D3
 *
 * Ce n'est pas une préférence d'ingénierie, c'est une contrainte de marché. La
 * plateforme s'adresse à l'Afrique et son back-office sera consulté depuis Cotonou,
 * Lomé ou Douala, souvent en 4G partagée. Chart.js pèse ~200 Ko minifié, D3 davantage.
 * Ce module en fait moins de 20 et couvre exactement les formes dont le dashboard a
 * besoin. Sur une connexion à 500 ko/s, c'est la différence entre un tableau de bord
 * qui s'affiche et un tableau de bord qu'on attend.
 *
 * ## Règles suivies (et pourquoi elles ne se négocient pas)
 *
 * - **Un seul axe des ordonnées.** Jamais deux échelles sur un même graphique : leur
 *   alignement est arbitraire et invente une corrélation qui n'existe pas dans les
 *   données. Deux mesures d'ordres différents → deux graphiques.
 * - **La couleur suit l'entité, jamais son rang.** Filtrer une série ne repeint pas
 *   les survivantes : un lecteur qui a appris « les publications sont en vert » ne
 *   doit pas voir le vert changer de sens en changeant de filtre.
 * - **Palette figée et validée.** Les huit teintes ont passé les contrôles de
 *   séparation sous protanopie et deutéranopie sur la surface sombre du dashboard.
 *   Elles se lisent depuis les variables CSS `--chart-N` et ne se choisissent pas ici.
 * - **Marques fines, grille discrète.** Le trait fait 2 px, les barres sont plafonnées
 *   à 24 px, la grille est une hairline pleine — jamais pointillée, ce qui se lirait
 *   comme un seuil.
 * - **Aucune valeur n'est accessible par la seule infobulle.** Chaque graphique
 *   produit une table équivalente, masquée visuellement mais lue par les lecteurs
 *   d'écran et dépliable. Une infobulle enrichit, elle ne conditionne jamais l'accès.
 */

/** Palette catégorielle, dans l'ordre figé. Lue depuis le thème, pas redéfinie ici. */
export const SERIES = [
  'var(--chart-1, #3987e5)',
  'var(--chart-2, #d95926)',
  'var(--chart-3, #199e70)',
  'var(--chart-4, #c98500)',
  'var(--chart-5, #d55181)',
  'var(--chart-6, #008300)',
  'var(--chart-7, #9085e9)',
  'var(--chart-8, #e66767)',
];

/** Échelle de statut — réservée, jamais utilisée pour une identité de série. */
export const STATUS = {
  good: 'var(--status-good, #0ca30c)',
  warning: 'var(--status-warning, #fab219)',
  serious: 'var(--status-serious, #ec835a)',
  critical: 'var(--status-critical, #d03b3b)',
};

/**
 * Rampe ordinale — une seule teinte, du clair au foncé.
 * Réservée aux séquences ordonnées (étapes d'entonnoir, tranches de score) où l'ordre
 * fait partie du sens et doit se voir dans la couleur.
 */
export const ORDINAL = ['#cde2fb', '#86b6ef', '#3987e5', '#1c5cab', '#0d366b'];

const SURFACE = 'var(--surface-chart, #1e1f26)';
const GRID = 'rgba(255,255,255,0.07)';
const INK = 'var(--text-primary, #e2e2eb)';
const INK_MUTED = 'var(--text-muted, #918f9e)';

const NS = 'http://www.w3.org/2000/svg';

/* --------------------------------------------------------------------------- */
/* Utilitaires                                                                 */
/* --------------------------------------------------------------------------- */

function el(tag, attrs = {}, children = []) {
  const node = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== null && v !== undefined) node.setAttribute(k, String(v));
  }
  for (const child of [].concat(children)) {
    if (child) node.appendChild(child);
  }
  return node;
}

/**
 * Abrège un nombre pour un axe ou une tuile.
 *
 * Les seuils sont `k` et `M` et non `K`/`Mio` : c'est la notation qu'attend un
 * lecteur francophone, et un axe n'est pas l'endroit où introduire du vocabulaire.
 */
export function compact(value, { decimals = 1 } = {}) {
  const n = Number(value) || 0;
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${trim(n / 1e9, decimals)} Md`;
  if (abs >= 1e6) return `${trim(n / 1e6, decimals)} M`;
  if (abs >= 1e4) return `${trim(n / 1e3, 0)} k`;
  if (abs >= 1e3) return groupThousands(Math.round(n));
  return trim(n, Number.isInteger(n) ? 0 : decimals);
}

function trim(n, decimals) {
  return Number(n.toFixed(decimals)).toString().replace('.', ',');
}

/** Séparateur de milliers : espace fine insécable, règle typographique française. */
export function groupThousands(n) {
  return String(Math.round(Number(n) || 0)).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

/** Date ISO → libellé court d'axe (« 6 août »). */
export function shortDate(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short' });
}

/**
 * Graduations « rondes » couvrant [0, max].
 *
 * Un axe gradué à 0 / 3 741 / 7 482 est illisible : on cherche un pas en 1, 2, 5 ou
 * 10 × puissance de dix, celui qui donne quatre à cinq repères.
 */
function niceTicks(max, count = 4) {
  if (max <= 0) return [0, 1];
  const raw = max / count;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * magnitude).find((s) => s >= raw) ?? magnitude * 10;
  const ticks = [];
  for (let v = 0; v <= max + step * 0.001; v += step) ticks.push(v);
  return ticks;
}

/**
 * Table équivalente d'un graphique, pour les lecteurs d'écran et le dépliage manuel.
 *
 * C'est la contrepartie obligatoire de toute infobulle : aucune valeur ne doit être
 * accessible uniquement en survolant. Un utilisateur au clavier, un lecteur d'écran
 * ou quelqu'un qui veut recopier un chiffre doit pouvoir l'atteindre.
 */
function tableView(caption, columns, rows) {
  const wrap = document.createElement('details');
  wrap.className = 'mt-sm group';
  const summary = document.createElement('summary');
  summary.className =
    'cursor-pointer font-label-md text-label-md text-on-surface-variant/70 hover:text-on-surface transition-colors select-none';
  summary.textContent = 'Voir les données';
  wrap.appendChild(summary);

  const scroller = document.createElement('div');
  scroller.className = 'overflow-x-auto mt-xs';
  const table = document.createElement('table');
  table.className = 'w-full font-body-sm text-body-sm border-collapse';
  if (caption) {
    const cap = document.createElement('caption');
    cap.className = 'sr-only';
    cap.textContent = caption;
    table.appendChild(cap);
  }

  const thead = document.createElement('thead');
  const htr = document.createElement('tr');
  for (const col of columns) {
    const th = document.createElement('th');
    th.scope = 'col';
    th.className =
      'text-left py-1 pr-3 border-b border-outline-variant/30 text-on-surface-variant font-medium';
    th.textContent = col;
    htr.appendChild(th);
  }
  thead.appendChild(htr);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr');
    row.forEach((cell, index) => {
      const td = document.createElement('td');
      // `tabular-nums` uniquement sur les colonnes de chiffres, qui doivent
      // s'aligner verticalement — jamais sur du texte, où l'espacement égal des
      // caractères se voit et dérange.
      td.className = `py-1 pr-3 border-b border-outline-variant/15 ${
        index === 0 ? 'text-on-surface-variant' : 'text-on-surface tabular-nums'
      }`;
      td.textContent = cell;
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  scroller.appendChild(table);
  wrap.appendChild(scroller);
  return wrap;
}

/** Légende : la voie d'identification fiable dès deux séries. */
function legend(series) {
  const box = document.createElement('div');
  box.className = 'flex flex-wrap items-center gap-x-md gap-y-1 mt-sm';
  for (const s of series) {
    const item = document.createElement('span');
    item.className = 'inline-flex items-center gap-2 font-label-md text-label-md text-on-surface-variant';
    const dot = document.createElement('span');
    dot.className = 'inline-block w-2.5 h-2.5 rounded-full shrink-0';
    dot.style.background = s.color;
    item.appendChild(dot);
    // Le libellé reste en encre de texte : une teinte catégorielle claire est
    // illisible en petit corps. L'identité vient de la pastille à côté.
    item.appendChild(document.createTextNode(s.label));
    box.appendChild(item);
  }
  return box;
}

/** Conteneur commun : surface, titre, zone de tracé, légende, table. */
function frame(host, { title, subtitle } = {}) {
  host.innerHTML = '';
  const root = document.createElement('div');
  root.className = 'viz-root';
  if (title) {
    const h = document.createElement('h3');
    h.className = 'font-headline-md text-headline-md text-on-surface';
    h.textContent = title;
    root.appendChild(h);
  }
  if (subtitle) {
    const p = document.createElement('p');
    p.className = 'font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5';
    p.textContent = subtitle;
    root.appendChild(p);
  }
  host.appendChild(root);
  return root;
}

/* --------------------------------------------------------------------------- */
/* Infobulle partagée                                                          */
/* --------------------------------------------------------------------------- */

let tipNode = null;

function tooltip() {
  if (tipNode) return tipNode;
  tipNode = document.createElement('div');
  tipNode.className =
    'fixed z-[100] pointer-events-none opacity-0 transition-opacity duration-100 ' +
    'bg-surface-container-highest/95 backdrop-blur-sm border border-outline-variant/40 ' +
    'rounded-lg px-3 py-2 shadow-xl font-body-sm text-body-sm text-on-surface';
  document.body.appendChild(tipNode);
  return tipNode;
}

function showTip(html, x, y) {
  const tip = tooltip();
  tip.innerHTML = html;
  tip.style.opacity = '1';
  const rect = tip.getBoundingClientRect();
  // On bascule l'infobulle du côté opposé quand elle sortirait de la fenêtre :
  // sur un écran étroit, la version « toujours à droite » se retrouve tronquée
  // exactement sur les points les plus intéressants, ceux du bord droit.
  const left = x + 14 + rect.width > window.innerWidth ? x - rect.width - 14 : x + 14;
  const top = Math.max(8, Math.min(y - rect.height / 2, window.innerHeight - rect.height - 8));
  tip.style.left = `${Math.max(8, left)}px`;
  tip.style.top = `${top}px`;
}

function hideTip() {
  if (tipNode) tipNode.style.opacity = '0';
}

/* --------------------------------------------------------------------------- */
/* Courbe / aire                                                               */
/* --------------------------------------------------------------------------- */

/**
 * Graphique en courbes, avec aire optionnelle, réticule et infobulle.
 *
 * @param {HTMLElement} host conteneur.
 * @param {object} config
 * @param {string[]} config.labels dates ou catégories de l'axe des abscisses.
 * @param {{label: string, values: number[], color?: string}[]} config.series séries.
 * @param {boolean} [config.area] remplir sous la courbe (une seule série).
 * @param {(v: number) => string} [config.format] mise en forme des valeurs.
 */
export function lineChart(host, { labels, series, title, subtitle, area = false, format = compact, height = 220 }) {
  const root = frame(host, { title, subtitle });
  const W = 720;
  const H = height;
  const pad = { top: 16, right: 16, bottom: 30, left: 46 };
  const plotW = W - pad.left - pad.right;
  const plotH = H - pad.top - pad.bottom;

  const coloured = series.map((s, i) => ({ ...s, color: s.color || SERIES[i % SERIES.length] }));
  const max = Math.max(1, ...coloured.flatMap((s) => s.values));
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1];

  const x = (i) => pad.left + (labels.length <= 1 ? plotW / 2 : (i / (labels.length - 1)) * plotW);
  const y = (v) => pad.top + plotH - (v / top) * plotH;

  const svg = el('svg', {
    viewBox: `0 0 ${W} ${H}`,
    class: 'w-full',
    style: `height:${H}px`,
    role: 'img',
    'aria-label': title || 'Graphique',
  });

  // Grille : hairline pleine, un pas au-dessus de la surface. Jamais pointillée —
  // le pointillé se lit comme un seuil ou une projection.
  for (const t of ticks) {
    svg.appendChild(el('line', { x1: pad.left, x2: W - pad.right, y1: y(t), y2: y(t), stroke: GRID, 'stroke-width': 1 }));
    svg.appendChild(
      el('text', { x: pad.left - 8, y: y(t) + 4, 'text-anchor': 'end', fill: INK_MUTED, 'font-size': 11, style: 'font-variant-numeric:tabular-nums' },
        document.createTextNode(compact(t))),
    );
  }

  // Abscisses : on n'affiche qu'un repère sur N pour éviter le chevauchement, plutôt
  // que d'incliner les libellés — un texte tourné à 45° se lit mal et mange la hauteur.
  const every = Math.max(1, Math.ceil(labels.length / 7));
  labels.forEach((label, i) => {
    if (i % every !== 0 && i !== labels.length - 1) return;
    svg.appendChild(
      el('text', { x: x(i), y: H - 10, 'text-anchor': 'middle', fill: INK_MUTED, 'font-size': 11 },
        document.createTextNode(shortDate(label))),
    );
  });

  for (const s of coloured) {
    const path = s.values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
    if (area && coloured.length === 1) {
      // Aire à ~10 % d'opacité : un lavis, jamais un aplat saturé.
      svg.appendChild(
        el('path', {
          d: `${path} L${x(s.values.length - 1)} ${y(0)} L${x(0)} ${y(0)} Z`,
          fill: s.color,
          'fill-opacity': 0.1,
        }),
      );
    }
    svg.appendChild(
      el('path', { d: path, fill: 'none', stroke: s.color, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }),
    );
    // Point terminal : anneau à la couleur de la surface pour rester lisible quand
    // plusieurs séries se croisent au bord droit.
    const last = s.values.length - 1;
    if (last >= 0) {
      svg.appendChild(el('circle', { cx: x(last), cy: y(s.values[last]), r: 4, fill: s.color, stroke: SURFACE, 'stroke-width': 2 }));
    }
  }

  // Réticule et zones de survol. Une bande par point, large : viser un trait de 2 px
  // à la souris est impossible, et au doigt encore moins.
  const crosshair = el('line', { y1: pad.top, y2: pad.top + plotH, stroke: 'rgba(255,255,255,0.18)', 'stroke-width': 1, opacity: 0 });
  svg.appendChild(crosshair);

  labels.forEach((label, i) => {
    const bandW = plotW / Math.max(1, labels.length - 1 || 1);
    const band = el('rect', {
      x: x(i) - bandW / 2,
      y: pad.top,
      width: bandW,
      height: plotH,
      fill: 'transparent',
      style: 'cursor:crosshair',
      tabindex: 0,
      role: 'button',
      'aria-label': `${shortDate(label)} : ${coloured.map((s) => `${s.label} ${format(s.values[i])}`).join(', ')}`,
    });
    const reveal = (event) => {
      crosshair.setAttribute('x1', x(i));
      crosshair.setAttribute('x2', x(i));
      crosshair.setAttribute('opacity', 1);
      const rect = band.getBoundingClientRect();
      const lignes = coloured
        .map(
          (s) =>
            `<span class="flex items-center gap-2 whitespace-nowrap"><span style="background:${s.color}" class="inline-block w-2 h-2 rounded-full"></span>${s.label}<b class="ml-auto pl-3 tabular-nums">${format(s.values[i])}</b></span>`,
        )
        .join('');
      showTip(`<div class="font-medium mb-1">${shortDate(label)}</div><div class="flex flex-col gap-0.5">${lignes}</div>`,
        event ? event.clientX : rect.left + rect.width / 2, event ? event.clientY : rect.top + rect.height / 2);
    };
    band.addEventListener('mousemove', reveal);
    band.addEventListener('focus', () => reveal(null));
    band.addEventListener('mouseleave', () => { crosshair.setAttribute('opacity', 0); hideTip(); });
    band.addEventListener('blur', () => { crosshair.setAttribute('opacity', 0); hideTip(); });
    svg.appendChild(band);
  });

  root.appendChild(svg);
  // Une seule série n'a pas besoin de légende : le titre nomme déjà ce qui est tracé.
  if (coloured.length > 1) root.appendChild(legend(coloured));
  root.appendChild(
    tableView(title || 'Données', ['Date', ...coloured.map((s) => s.label)],
      labels.map((l, i) => [shortDate(l), ...coloured.map((s) => format(s.values[i]))])),
  );
  return root;
}

/* --------------------------------------------------------------------------- */
/* Barres                                                                      */
/* --------------------------------------------------------------------------- */

/**
 * Barres horizontales — la forme juste pour comparer des catégories nommées.
 *
 * L'horizontale plutôt que la verticale dès que les libellés sont des mots : un nom
 * de pays ou d'offre tient sur une ligne à gauche, alors qu'en colonnes il faudrait
 * l'incliner ou le tronquer.
 *
 * Une catégorie nominale = **une seule couleur** pour toutes les barres. Colorer
 * chaque barre différemment dépenserait le canal d'identité à réencoder ce que la
 * longueur montre déjà.
 */
export function barChart(host, { items, title, subtitle, format = compact, color = SERIES[0], max: forcedMax }) {
  const root = frame(host, { title, subtitle });
  const rows = items.slice(0, 12);
  const max = Math.max(1, forcedMax || 0, ...rows.map((r) => r.value));

  const list = document.createElement('div');
  list.className = 'flex flex-col gap-sm mt-sm';

  for (const row of rows) {
    const line = document.createElement('div');
    line.className = 'group';

    const head = document.createElement('div');
    head.className = 'flex items-baseline justify-between gap-md mb-1';
    const label = document.createElement('span');
    label.className = 'font-body-sm text-body-sm text-on-surface-variant truncate';
    label.textContent = row.label;
    const value = document.createElement('span');
    value.className = 'font-label-md text-label-md text-on-surface tabular-nums shrink-0';
    value.textContent = format(row.value);
    head.append(label, value);

    // Piste et remplissage. La barre est plafonnée à 10 px de haut : une barre fine
    // se lit aussi bien qu'une épaisse et laisse respirer la liste.
    const track = document.createElement('div');
    track.className = 'h-2.5 rounded-full bg-surface-container-highest/60 overflow-hidden';
    const fill = document.createElement('div');
    fill.className = 'h-full rounded-full transition-[width] duration-500 ease-out';
    fill.style.width = `${Math.max(2, (row.value / max) * 100)}%`;
    fill.style.background = row.color || color;
    track.appendChild(fill);

    line.append(head, track);
    if (row.hint) {
      const hint = document.createElement('p');
      hint.className = 'font-body-sm text-body-sm text-on-surface-variant/50 mt-0.5';
      hint.textContent = row.hint;
      line.appendChild(hint);
    }
    list.appendChild(line);
  }

  root.appendChild(list);
  root.appendChild(
    tableView(title || 'Données', ['Catégorie', 'Valeur'], rows.map((r) => [r.label, format(r.value)])),
  );
  return root;
}

/* --------------------------------------------------------------------------- */
/* Anneau (part-à-tout)                                                        */
/* --------------------------------------------------------------------------- */

/**
 * Anneau — uniquement pour une part-à-tout lue d'un coup d'œil, six segments maximum.
 *
 * Au-delà, ou pour comparer des valeurs proches, ce sont des barres qu'il faut :
 * l'œil compare mal des angles. La queue est repliée sur « Autres » plutôt que de
 * puiser dans une neuvième couleur, qui serait indistinguable des précédentes.
 */
export function donutChart(host, { items, title, subtitle, format = compact, centerLabel }) {
  const root = frame(host, { title, subtitle });

  const sorted = [...items].sort((a, b) => b.value - a.value);
  const head = sorted.slice(0, 5);
  const tail = sorted.slice(5);
  const segments = tail.length
    ? [...head, { label: 'Autres', value: tail.reduce((sum, r) => sum + r.value, 0) }]
    : head;

  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
  const coloured = segments.map((s, i) => ({ ...s, color: s.color || SERIES[i % SERIES.length] }));

  const size = 180;
  const r = 70;
  const stroke = 22;
  const c = 2 * Math.PI * r;
  const svg = el('svg', { viewBox: `0 0 ${size} ${size}`, class: 'shrink-0', style: `width:${size}px;height:${size}px`, role: 'img', 'aria-label': title || 'Répartition' });

  let offset = 0;
  for (const s of coloured) {
    const part = s.value / total;
    // Écart de 2 px à la couleur de la surface entre segments : c'est le blanc qui
    // sépare, jamais un contour dessiné autour des marques.
    const arc = Math.max(0, part * c - 2);
    const circle = el('circle', {
      cx: size / 2, cy: size / 2, r,
      fill: 'none',
      stroke: s.color,
      'stroke-width': stroke,
      'stroke-dasharray': `${arc} ${c - arc}`,
      'stroke-dashoffset': -offset,
      transform: `rotate(-90 ${size / 2} ${size / 2})`,
      style: 'cursor:pointer',
    });
    circle.addEventListener('mousemove', (e) =>
      showTip(`<b>${s.label}</b><br>${format(s.value)} — ${(part * 100).toFixed(1).replace('.', ',')} %`, e.clientX, e.clientY));
    circle.addEventListener('mouseleave', hideTip);
    svg.appendChild(circle);
    offset += part * c;
  }

  if (centerLabel) {
    svg.appendChild(el('text', { x: size / 2, y: size / 2 - 2, 'text-anchor': 'middle', fill: INK, 'font-size': 24, 'font-weight': 600 },
      document.createTextNode(centerLabel.value)));
    svg.appendChild(el('text', { x: size / 2, y: size / 2 + 18, 'text-anchor': 'middle', fill: INK_MUTED, 'font-size': 11 },
      document.createTextNode(centerLabel.label)));
  }

  const layout = document.createElement('div');
  layout.className = 'flex flex-wrap items-center gap-lg mt-sm';
  layout.appendChild(svg);

  const list = document.createElement('div');
  list.className = 'flex flex-col gap-2 min-w-[180px] flex-1';
  for (const s of coloured) {
    const item = document.createElement('div');
    item.className = 'flex items-center gap-2 font-body-sm text-body-sm';
    const dot = document.createElement('span');
    dot.className = 'w-2.5 h-2.5 rounded-full shrink-0';
    dot.style.background = s.color;
    const name = document.createElement('span');
    name.className = 'text-on-surface-variant truncate';
    name.textContent = s.label;
    const val = document.createElement('span');
    val.className = 'ml-auto text-on-surface tabular-nums shrink-0';
    val.textContent = `${format(s.value)} · ${((s.value / total) * 100).toFixed(0)} %`;
    item.append(dot, name, val);
    list.appendChild(item);
  }
  layout.appendChild(list);
  root.appendChild(layout);
  root.appendChild(
    tableView(title || 'Répartition', ['Catégorie', 'Valeur', 'Part'],
      coloured.map((s) => [s.label, format(s.value), `${((s.value / total) * 100).toFixed(1).replace('.', ',')} %`])),
  );
  return root;
}

/* --------------------------------------------------------------------------- */
/* Entonnoir                                                                   */
/* --------------------------------------------------------------------------- */

/**
 * Entonnoir d'activation. Les étapes sont **ordonnées** : elles prennent donc la
 * rampe ordinale à une seule teinte, et non des couleurs catégorielles — c'est ce
 * qui fait voir la progression dans la couleur elle-même.
 *
 * La déperdition entre deux étapes est affichée en clair : c'est l'information qui
 * déclenche une décision, pas le nombre absolu.
 */
export function funnelChart(host, { steps, title, subtitle }) {
  const root = frame(host, { title, subtitle });
  const start = Math.max(1, steps[0]?.count || 1);

  const list = document.createElement('div');
  list.className = 'flex flex-col gap-2 mt-sm';

  steps.forEach((step, i) => {
    const row = document.createElement('div');

    const head = document.createElement('div');
    head.className = 'flex items-baseline justify-between gap-md mb-1';
    const label = document.createElement('span');
    label.className = 'font-body-md text-body-md text-on-surface';
    label.textContent = step.step;
    const value = document.createElement('span');
    value.className = 'font-label-md text-label-md text-on-surface-variant tabular-nums shrink-0';
    value.textContent = `${groupThousands(step.count)} · ${step.share_of_start ?? 0} %`;
    head.append(label, value);

    const track = document.createElement('div');
    track.className = 'h-7 rounded-lg bg-surface-container-highest/40 overflow-hidden';
    const fill = document.createElement('div');
    fill.className = 'h-full rounded-lg transition-[width] duration-500 ease-out';
    fill.style.width = `${Math.max(1.5, (step.count / start) * 100)}%`;
    fill.style.background = ORDINAL[Math.min(i, ORDINAL.length - 1)];
    track.appendChild(fill);

    row.append(head, track);

    if (i > 0 && step.dropped > 0) {
      const loss = document.createElement('p');
      loss.className = 'font-body-sm text-body-sm text-on-surface-variant/60 mt-1';
      loss.textContent = `− ${groupThousands(step.dropped)} perdus à cette étape (${step.step_conversion} % de conversion)`;
      row.appendChild(loss);
    }
    list.appendChild(row);
  });

  root.appendChild(list);
  root.appendChild(
    tableView(title || 'Entonnoir', ['Étape', 'Comptes', 'Depuis le départ', 'Conversion'],
      steps.map((s) => [s.step, groupThousands(s.count), `${s.share_of_start} %`, `${s.step_conversion} %`])),
  );
  return root;
}

/* --------------------------------------------------------------------------- */
/* Sparkline et tuiles                                                         */
/* --------------------------------------------------------------------------- */

/** Courbe miniature d'une tuile. Sans axe ni infobulle : c'est une tendance, pas une lecture. */
export function sparkline(values, { width = 96, height = 28, color = SERIES[0] } = {}) {
  const svg = el('svg', { viewBox: `0 0 ${width} ${height}`, style: `width:${width}px;height:${height}px`, 'aria-hidden': 'true' });
  if (!values.length) return svg;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = max - min || 1;
  const x = (i) => (values.length === 1 ? width / 2 : (i / (values.length - 1)) * width);
  const y = (v) => height - 2 - ((v - min) / span) * (height - 4);
  const d = values.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ');
  svg.appendChild(el('path', { d: `${d} L${x(values.length - 1)} ${height} L0 ${height} Z`, fill: color, 'fill-opacity': 0.12 }));
  svg.appendChild(el('path', { d, fill: 'none', stroke: color, 'stroke-width': 1.75, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }));
  return svg;
}

/**
 * Tuile d'indicateur : libellé, valeur, variation, tendance.
 *
 * La variation est toujours rapportée à une période nommée. Un nombre seul
 * (« 143 sites ») ne dit pas si la situation s'améliore ; c'est la variation qui
 * déclenche une décision.
 *
 * `goodDown` inverse la lecture de la couleur pour les métriques où la baisse est une
 * bonne nouvelle — coût des modèles, taux d'échec, latence.
 */
export function statTile({ label, value, delta, deltaLabel = 'vs période précédente', trend, goodDown = false, icon, hint }) {
  const card = document.createElement('div');
  card.className =
    'bg-surface-container/70 border border-outline-variant/25 rounded-xl p-md flex flex-col gap-1 ' +
    'hover:border-outline-variant/50 transition-colors';

  const top = document.createElement('div');
  top.className = 'flex items-center gap-2';
  if (icon) {
    const ico = document.createElement('span');
    ico.className = 'material-symbols-outlined text-base text-on-surface-variant/60';
    ico.textContent = icon;
    top.appendChild(ico);
  }
  const lab = document.createElement('span');
  lab.className = 'font-label-md text-label-md text-on-surface-variant';
  lab.textContent = label;
  top.appendChild(lab);
  card.appendChild(top);

  const row = document.createElement('div');
  row.className = 'flex items-end justify-between gap-md mt-0.5';
  const val = document.createElement('span');
  // Chiffres proportionnels sur une grande valeur : `tabular-nums` donne à chaque
  // chiffre la largeur d'un zéro, ce qui fait paraître « 121 » distendu en gros corps.
  val.className = 'font-headline-lg text-headline-lg text-on-surface';
  val.textContent = value;
  row.appendChild(val);
  if (trend?.length) row.appendChild(sparkline(trend));
  card.appendChild(row);

  if (delta !== undefined && delta !== null) {
    const positif = Number(delta) >= 0;
    const bon = goodDown ? !positif : positif;
    const d = document.createElement('div');
    d.className = 'flex items-center gap-1 font-body-sm text-body-sm mt-0.5';
    const arrow = document.createElement('span');
    arrow.className = 'material-symbols-outlined text-sm';
    arrow.textContent = positif ? 'trending_up' : 'trending_down';
    // Icône + signe + libellé : la couleur ne porte jamais le sens seule.
    arrow.style.color = bon ? STATUS.good : STATUS.critical;
    const txt = document.createElement('span');
    txt.className = 'text-on-surface-variant';
    txt.textContent = `${positif ? '+' : ''}${String(delta).replace('.', ',')} % ${deltaLabel}`;
    d.append(arrow, txt);
    card.appendChild(d);
  }

  if (hint) {
    const h = document.createElement('p');
    h.className = 'font-body-sm text-body-sm text-on-surface-variant/50';
    h.textContent = hint;
    card.appendChild(h);
  }
  return card;
}

/**
 * Jauge d'usage face à un quota.
 *
 * La sévérité monte avec le remplissage : au-delà de 90 %, l'utilisateur doit
 * comprendre qu'il va être bloqué avant de l'être. Une limite `-1` vaut « illimité »
 * et n'affiche aucune jauge — dessiner une barre sans plafond n'a pas de sens.
 */
export function meter({ label, used, limit, format = groupThousands }) {
  const wrap = document.createElement('div');
  wrap.className = 'flex flex-col gap-1.5';

  const head = document.createElement('div');
  head.className = 'flex items-baseline justify-between gap-md';
  const lab = document.createElement('span');
  lab.className = 'font-body-sm text-body-sm text-on-surface-variant';
  lab.textContent = label;
  const val = document.createElement('span');
  val.className = 'font-label-md text-label-md text-on-surface tabular-nums';
  val.textContent = limit < 0 ? `${format(used)} · illimité` : `${format(used)} / ${format(limit)}`;
  head.append(lab, val);
  wrap.appendChild(head);

  if (limit >= 0) {
    const pct = Math.min(100, limit ? (used / limit) * 100 : 0);
    const track = document.createElement('div');
    track.className = 'h-2 rounded-full bg-surface-container-highest/60 overflow-hidden';
    const fill = document.createElement('div');
    fill.className = 'h-full rounded-full transition-[width] duration-500';
    fill.style.width = `${Math.max(2, pct)}%`;
    fill.style.background = pct >= 90 ? STATUS.critical : pct >= 70 ? STATUS.warning : SERIES[0];
    track.appendChild(fill);
    wrap.appendChild(track);
  }
  return wrap;
}

/** Pastille d'état : couleur **et** libellé, jamais la couleur seule. */
export function badge(text, tone = 'neutral') {
  const tones = {
    good: 'bg-status-good/15 text-status-good border-status-good/30',
    warning: 'bg-status-warning/15 text-status-warning border-status-warning/30',
    serious: 'bg-status-serious/15 text-status-serious border-status-serious/30',
    critical: 'bg-status-critical/15 text-status-critical border-status-critical/30',
    neutral: 'bg-surface-container-highest text-on-surface-variant border-outline-variant/40',
  };
  const span = document.createElement('span');
  span.className = `inline-flex items-center px-2 py-0.5 rounded-full border font-label-md text-label-md whitespace-nowrap ${tones[tone] || tones.neutral}`;
  span.textContent = text;
  return span;
}

/** Message affiché à la place d'un graphique quand il n'y a rien à tracer. */
export function emptyState(host, message = 'Aucune donnée sur cette période.') {
  host.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'flex flex-col items-center justify-center py-xl text-center gap-2';
  const icon = document.createElement('span');
  icon.className = 'material-symbols-outlined text-3xl text-on-surface-variant/30';
  icon.textContent = 'monitoring';
  const text = document.createElement('p');
  text.className = 'font-body-sm text-body-sm text-on-surface-variant/60 max-w-xs';
  text.textContent = message;
  box.append(icon, text);
  host.appendChild(box);
  return box;
}
