/**
 * Ossature commune des écrans d'administration.
 *
 * La navigation est **construite en JavaScript** et non recopiée dans chaque fichier
 * HTML. Les pages clientes portent chacune leur copie du markup de nav — huit copies
 * qui divergent dès qu'on touche à une entrée. Le back-office en compte sept : les
 * dupliquer aurait garanti la même dérive, en pire.
 *
 * Le shell fournit aussi les deux éléments que tous les écrans partagent :
 *
 * - **Le garde d'accès.** Un compte sans rôle d'équipe est renvoyé vers l'accueil
 *   avec un message clair, plutôt que de rester devant sept panneaux vides. Ce n'est
 *   qu'un confort d'affichage : chaque endpoint revérifie le rôle côté serveur.
 * - **Le filtre de période, unique et au-dessus de tout.** Un sélecteur par carte
 *   produirait des graphiques qui ne parlent pas de la même chose côte à côte — le
 *   défaut le plus courant des dashboards maison.
 */
import { getUser, clearSession } from './auth.js';
import { auth } from './api.js';
import {
  buildCollapseToggle,
  buildScrim,
  buildTopbar,
  restoreNavState,
  wireDrawer,
} from './nav-drawer.js';

/** Entrées du back-office, dans l'ordre de consultation naturel. */
const NAV = [
  { href: 'admin.html', icon: 'dashboard', label: "Vue d'ensemble" },
  { href: 'admin-analytics.html', icon: 'insights', label: 'Analytics' },
  { href: 'admin-utilisateurs.html', icon: 'group', label: 'Utilisateurs' },
  { href: 'admin-sites.html', icon: 'language', label: 'Sites' },
  { href: 'admin-agents.html', icon: 'smart_toy', label: 'Agents IA' },
  { href: 'admin-systeme.html', icon: 'monitor_heart', label: 'Système' },
  { href: 'admin-journal.html', icon: 'history', label: 'Journal' },
];

/** Périodes proposées. Bornées : au-delà d'un an, aucune décision ne se prend sur une courbe. */
export const PERIODS = [
  { days: 7, label: '7 jours' },
  { days: 30, label: '30 jours' },
  { days: 90, label: '90 jours' },
  { days: 365, label: '12 mois' },
];

const PERIOD_KEY = 'jarvisAdminPeriod';

/** Période courante, mémorisée entre les écrans pour ne pas la resaisir à chaque page. */
export function currentPeriod() {
  const stored = Number(localStorage.getItem(PERIOD_KEY));
  return PERIODS.some((p) => p.days === stored) ? stored : 30;
}

/**
 * Monte l'ossature et rend la main quand l'accès est confirmé.
 *
 * @param {object} options
 * @param {string} options.active fichier de la page courante, pour marquer l'onglet.
 * @param {string} options.title titre de l'écran.
 * @param {string} [options.subtitle] contexte affiché sous le titre.
 * @param {boolean} [options.period] afficher le sélecteur de période.
 * @param {(days: number) => void} [options.onPeriodChange] rappel au changement.
 * @returns {Promise<{content: HTMLElement, user: object} | null>} `null` si l'accès est refusé.
 */
export async function mountAdminShell({ active, title, subtitle, period = false, onPeriodChange }) {
  // `flex` a disparu : la barre est en position fixe et le contenu porte sa marge.
  // Le conserver empêchait le contenu de prendre toute la largeur sur téléphone,
  // où la barre n'occupe plus de place dans le flux.
  document.body.className =
    'bg-background text-on-background font-body-md min-h-screen overflow-x-hidden ' +
    'selection:bg-surface-container-highest selection:text-white';

  restoreNavState();

  const user = await resolveUser();
  const layout = buildLayout({ active, title, subtitle, period, onPeriodChange, user });

  if (!isStaff(user)) {
    // On n'affiche pas un dashboard vide : c'est le message le plus déroutant qui
    // soit, parce qu'il ressemble à une panne alors que c'est un refus.
    renderAccessDenied(layout.content, user);
    return null;
  }

  return { content: layout.content, user };
}

/**
 * Profil courant : cache local d'abord, serveur ensuite.
 *
 * Le cache évite un écran blanc au chargement ; l'appel serveur qui suit corrige un
 * rôle périmé — typiquement un compte promu depuis un autre poste.
 */
async function resolveUser() {
  const cached = getUser();
  try {
    return await auth.me();
  } catch {
    return cached;
  }
}

function isStaff(user) {
  return ['support', 'admin', 'owner'].includes(user?.role);
}

function buildLayout({ active, title, subtitle, period, onPeriodChange, user }) {
  document.body.innerHTML = '';

  /* --- Barre latérale ------------------------------------------------------
     `.app-nav` porte le même comportement que côté produit : tiroir sous 768 px,
     barre repliable au-delà. C'est le point : un membre de l'équipe qui passe du
     produit à l'administration retrouve la navigation au même endroit, ouverte
     par le même geste. */
  const nav = document.createElement('nav');
  nav.id = 'app-nav';
  nav.className = 'app-nav py-md border-r border-white/5';
  nav.setAttribute('aria-label', 'Navigation du back-office');
  nav.appendChild(buildCollapseToggle());

  // Voir `.app-nav-scroll` dans tailwind.css : le défilement vit ici, pas sur `.app-nav`,
  // pour ne pas rogner le bouton de repli qui déborde du bord droit de la barre.
  const scroll = document.createElement('div');
  scroll.className = 'app-nav-scroll';
  nav.appendChild(scroll);

  const top = document.createElement('div');
  top.className = 'flex flex-col gap-md px-3';

  const brand = document.createElement('a');
  brand.href = 'index.html';
  brand.className = 'flex items-center gap-2 px-1.5 min-w-0 h-10 shrink-0';
  brand.innerHTML =
    '<img alt="Jarvis" class="logo-mark w-5 h-5 object-contain shrink-0" src="/assets/jarvis-mark.png">' +
    '<span class="nav-label font-headline-md text-headline-md tracking-tight text-on-surface truncate">Jarvis</span>' +
    '<span class="nav-label inline-flex items-center px-2 py-0.5 rounded-full bg-primary-container/60 text-on-primary-container font-label-md text-label-md shrink-0">Admin</span>';
  top.appendChild(brand);

  const list = document.createElement('ul');
  list.className = 'flex flex-col gap-1 w-full';
  for (const entry of NAV) {
    const li = document.createElement('li');
    const a = document.createElement('a');
    a.href = entry.href;
    const courant = entry.href === active;
    a.className =
      'nav-item flex items-center gap-sm px-sm rounded-lg transition-colors duration-150 ' +
      (courant
        ? 'bg-surface-container text-on-surface font-semibold'
        : 'text-on-surface-variant/80 hover:text-on-surface hover:bg-surface-container');
    if (courant) a.setAttribute('aria-current', 'page');
    a.innerHTML =
      `<span class="material-symbols-outlined text-lg shrink-0"${courant ? " style=\"font-variation-settings:'FILL' 1;\"" : ''}>${entry.icon}</span>` +
      `<span class="nav-label font-label-md text-label-md">${entry.label}</span>`;
    li.appendChild(a);
    list.appendChild(li);
  }
  top.appendChild(list);
  scroll.appendChild(top);

  /* --- Pied : retour au produit et déconnexion ----------------------------- */
  const bottom = document.createElement('div');
  bottom.className = 'px-3 w-full flex flex-col gap-1';
  bottom.innerHTML =
    '<a href="index.html" class="nav-item flex items-center gap-sm px-sm rounded-lg text-on-surface-variant/80 hover:text-on-surface hover:bg-surface-container transition-colors">' +
    '<span class="material-symbols-outlined text-lg shrink-0">arrow_back</span>' +
    '<span class="nav-label font-label-md text-label-md">Retour au produit</span></a>';
  const logout = document.createElement('button');
  logout.type = 'button';
  logout.className =
    'nav-item flex items-center gap-sm px-sm rounded-lg text-on-surface-variant/80 hover:text-on-surface hover:bg-surface-container transition-colors w-full text-left';
  logout.innerHTML =
    '<span class="material-symbols-outlined text-lg shrink-0">logout</span>' +
    '<span class="nav-label font-label-md text-label-md">Déconnexion</span>';
  logout.addEventListener('click', () => {
    clearSession();
    window.location.href = 'connexion.html';
  });
  bottom.appendChild(logout);
  scroll.appendChild(bottom);
  document.body.appendChild(nav);

  /* --- Zone principale ----------------------------------------------------- */
  const main = document.createElement('main');
  main.className = 'app-main min-w-0 flex flex-col min-h-screen';

  // L'en-tête colle sous la barre supérieure mobile, et en haut de la fenêtre au
  // format bureau où cette barre n'existe pas.
  const header = document.createElement('header');
  header.className =
    'sticky top-14 md:top-0 z-40 flex flex-wrap items-center gap-sm md:gap-md ' +
    'px-md md:px-lg py-sm md:py-md border-b border-outline-variant/20 ' +
    'bg-background/85 backdrop-blur-xl';

  const heading = document.createElement('div');
  // `basis-full` sur petit écran : le titre garde sa ligne, le filtre de période
  // passe dessous. Sur la même ligne, un titre comme « Utilisateurs » et quatre
  // boutons de période se disputaient 360 px et se tronquaient tous les deux.
  const h1 = document.createElement('h1');
  heading.className = 'min-w-0 flex-1 basis-full sm:basis-auto';
  h1.className = 'font-headline-lg text-headline-lg text-on-surface truncate';
  h1.textContent = title;
  heading.appendChild(h1);
  if (subtitle) {
    const p = document.createElement('p');
    p.className = 'font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5';
    p.textContent = subtitle;
    heading.appendChild(p);
  }
  header.appendChild(heading);

  // Filtre de période : une seule rangée, au-dessus de tout ce qu'elle cadre.
  // Sous 360 px, les quatre libellés dépassent : la rangée défile plutôt que de
  // se replier, pour que « 12 mois » ne se retrouve pas seul sur une ligne.
  if (period) {
    const group = document.createElement('div');
    group.className =
      'flex items-center gap-1 p-1 rounded-full bg-surface-container/70 border ' +
      'border-outline-variant/25 overflow-x-auto max-w-full ' +
      '[scrollbar-width:none] [&::-webkit-scrollbar]:hidden';
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', "Période d'analyse");
    const actif = currentPeriod();
    for (const p of PERIODS) {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.dataset.days = String(p.days);
      btn.className =
        'px-3 py-1.5 rounded-full font-label-md text-label-md transition-colors shrink-0 ' +
        (p.days === actif
          ? 'bg-surface-container-highest text-on-surface'
          : 'text-on-surface-variant hover:text-on-surface');
      btn.textContent = p.label;
      if (p.days === actif) btn.setAttribute('aria-pressed', 'true');
      btn.addEventListener('click', () => {
        localStorage.setItem(PERIOD_KEY, String(p.days));
        for (const other of group.children) {
          const isActive = other === btn;
          other.className =
            'px-3 py-1.5 rounded-full font-label-md text-label-md transition-colors shrink-0 ' +
            (isActive ? 'bg-surface-container-highest text-on-surface' : 'text-on-surface-variant hover:text-on-surface');
          other.setAttribute('aria-pressed', String(isActive));
        }
        onPeriodChange?.(p.days);
      });
      group.appendChild(btn);
    }
    header.appendChild(group);
  }

  if (user) {
    const badge = document.createElement('div');
    badge.className = 'flex items-center gap-2 pl-md border-l border-outline-variant/20';
    badge.innerHTML =
      `<div class="hidden sm:flex flex-col items-end leading-tight">
         <span class="font-label-md text-label-md text-on-surface truncate max-w-[180px]">${user.name || user.email}</span>
         <span class="font-body-sm text-body-sm text-on-surface-variant/60">${roleLabel(user.role)}</span>
       </div>
       <span class="w-9 h-9 rounded-full bg-primary-container/60 text-on-primary-container grid place-items-center font-label-md text-label-md shrink-0">
         ${(user.name || user.email || '?').trim().charAt(0).toUpperCase()}
       </span>`;
    header.appendChild(badge);
  }

  main.appendChild(header);

  const content = document.createElement('div');
  content.className = 'flex-1 px-md md:px-lg py-md md:py-lg flex flex-col gap-md md:gap-lg max-w-[1280px] w-full';
  main.appendChild(content);

  document.body.append(buildTopbar({ title: 'Administration', href: 'admin.html' }), buildScrim(), main);
  wireDrawer();

  return { content };
}

function roleLabel(role) {
  return { owner: 'Propriétaire', admin: 'Administrateur', support: 'Support' }[role] || 'Utilisateur';
}

function renderAccessDenied(host, user) {
  host.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'flex flex-col items-center justify-center text-center gap-md py-2xl';
  box.innerHTML = `
    <span class="material-symbols-outlined text-5xl text-on-surface-variant/30">lock</span>
    <h2 class="font-headline-lg text-headline-lg text-on-surface">Accès réservé à l'équipe</h2>
    <p class="font-body-md text-body-md text-on-surface-variant max-w-md">
      ${user ? `Votre compte (${user.email}) n'a pas le rôle nécessaire pour ouvrir l'administration.` : 'Connectez-vous avec un compte de l\'équipe.'}
      Si vous pensez que c'est une erreur, demandez à un administrateur de vous attribuer un rôle.
    </p>
    <a href="index.html" class="mt-sm inline-flex items-center gap-2 px-5 py-2.5 rounded-full bg-on-surface text-background font-label-md text-label-md font-semibold hover:bg-surface-variant hover:text-on-surface transition-colors">
      <span class="material-symbols-outlined text-sm">arrow_back</span> Retour à l'accueil
    </a>`;
  host.appendChild(box);
}

/* --------------------------------------------------------------------------- */
/* Blocs de mise en page réutilisés par tous les écrans                         */
/* --------------------------------------------------------------------------- */

/** Carte : le conteneur standard d'un graphique ou d'un tableau. */
export function card({ className = '' } = {}) {
  const box = document.createElement('section');
  box.className = `bg-surface-container/50 border border-outline-variant/25 rounded-2xl p-md ${className}`;
  return box;
}

/** Grille responsive de tuiles d'indicateurs. */
export function tileGrid() {
  const grid = document.createElement('div');
  grid.className = 'grid gap-md grid-cols-2 lg:grid-cols-4';
  return grid;
}

/** Grille à deux colonnes pour les graphiques, empilée sur mobile. */
export function splitGrid() {
  const grid = document.createElement('div');
  grid.className = 'grid gap-lg grid-cols-1 xl:grid-cols-2';
  return grid;
}

/**
 * Squelette de chargement.
 *
 * Affiché uniquement au **premier** rendu. Sur un rafraîchissement, la vue
 * précédente est conservée à opacité réduite : un squelette qui réapparaît à chaque
 * changement de filtre fait sauter la mise en page et donne une impression de lenteur
 * que la latence réelle ne justifie pas.
 */
export function skeleton(host, lines = 3) {
  host.innerHTML = '';
  const box = document.createElement('div');
  box.className = 'animate-pulse flex flex-col gap-sm py-md';
  for (let i = 0; i < lines; i += 1) {
    const bar = document.createElement('div');
    bar.className = 'h-3 rounded bg-surface-container-highest/50';
    bar.style.width = `${100 - i * 12}%`;
    box.appendChild(bar);
  }
  host.appendChild(box);
  return box;
}

/** Marque une zone comme en cours de rafraîchissement, sans la vider. */
export function setRefreshing(host, refreshing) {
  host.style.opacity = refreshing ? '0.55' : '1';
  host.style.transition = 'opacity 150ms ease';
}

/** Bandeau d'erreur, avec la possibilité de réessayer. */
export function errorBanner(host, error, onRetry) {
  host.innerHTML = '';
  const box = document.createElement('div');
  box.className =
    'flex flex-wrap items-center gap-sm p-md rounded-xl border border-status-critical/30 bg-status-critical/10';
  const icon = document.createElement('span');
  icon.className = 'material-symbols-outlined text-status-critical';
  icon.textContent = 'error';
  const text = document.createElement('p');
  text.className = 'font-body-md text-body-md text-on-surface flex-1 min-w-[200px]';
  text.textContent = error?.message || 'Chargement impossible.';
  box.append(icon, text);
  if (onRetry) {
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className =
      'px-3 py-1.5 rounded-full border border-outline-variant/40 font-label-md text-label-md text-on-surface hover:bg-surface-container-highest transition-colors';
    retry.textContent = 'Réessayer';
    retry.addEventListener('click', onRetry);
    box.appendChild(retry);
  }
  host.appendChild(box);
}

/** Tableau simple, en-têtes figées, défilement horizontal contenu dans la carte. */
export function dataTable(columns, rows, { empty = 'Aucun résultat.' } = {}) {
  const scroller = document.createElement('div');
  scroller.className = 'overflow-x-auto -mx-md px-md';

  if (!rows.length) {
    const none = document.createElement('p');
    none.className = 'font-body-md text-body-md text-on-surface-variant/60 py-lg text-center';
    none.textContent = empty;
    scroller.appendChild(none);
    return scroller;
  }

  const table = document.createElement('table');
  table.className = 'w-full border-collapse';

  const thead = document.createElement('thead');
  const htr = document.createElement('tr');
  for (const col of columns) {
    const th = document.createElement('th');
    th.scope = 'col';
    th.className =
      'text-left whitespace-nowrap py-2 px-3 border-b border-outline-variant/30 ' +
      'font-label-md text-label-md text-on-surface-variant font-medium';
    th.textContent = typeof col === 'string' ? col : col.label;
    htr.appendChild(th);
  }
  thead.appendChild(htr);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (const row of rows) {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-surface-container/60 transition-colors';
    for (const cell of row) {
      const td = document.createElement('td');
      td.className = 'py-2.5 px-3 border-b border-outline-variant/15 font-body-md text-body-md text-on-surface align-middle';
      if (cell instanceof Node) td.appendChild(cell);
      else td.textContent = cell ?? '—';
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  scroller.appendChild(table);
  return scroller;
}

/** Pagination : numéro de page, total, et navigation. */
export function pager(page, onChange) {
  const bar = document.createElement('div');
  bar.className = 'flex items-center justify-between gap-md pt-md mt-sm border-t border-outline-variant/20';

  const info = document.createElement('span');
  info.className = 'font-body-sm text-body-sm text-on-surface-variant';
  const from = page.total ? (page.page - 1) * page.size + 1 : 0;
  const to = Math.min(page.page * page.size, page.total);
  info.textContent = page.total
    ? `${from}–${to} sur ${page.total}`
    : 'Aucun résultat';
  bar.appendChild(info);

  const nav = document.createElement('div');
  nav.className = 'flex items-center gap-2';
  for (const [label, target, disabled] of [
    ['Précédent', page.page - 1, page.page <= 1],
    ['Suivant', page.page + 1, page.page >= page.pages],
  ]) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.disabled = disabled;
    btn.className =
      'px-3 py-1.5 rounded-full border border-outline-variant/40 font-label-md text-label-md transition-colors ' +
      (disabled ? 'text-on-surface-variant/30 cursor-not-allowed' : 'text-on-surface hover:bg-surface-container-highest');
    btn.textContent = label;
    if (!disabled) btn.addEventListener('click', () => onChange(target));
    nav.appendChild(btn);
  }
  bar.appendChild(nav);
  return bar;
}
