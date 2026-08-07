/**
 * Ossature commune des écrans produit.
 *
 * Pendant du back-office (`admin-shell.js`), pour la même raison : la barre de
 * navigation était recopiée telle quelle dans six fichiers HTML — soit six copies
 * d'une cinquantaine de lignes, déjà divergentes entre elles (l'entrée « Nouvelle
 * application » n'avait pas le même markup sur `projets.html` que sur `index.html`,
 * et `editeur.html` n'avait tout simplement pas de navigation sous 768 px). Ajouter
 * une entrée demandait six modifications, et en oublier une passait inaperçu.
 *
 * ## Comportement selon la largeur
 *
 * Sous 768 px, la barre latérale devient un **tiroir** ouvert depuis une barre
 * supérieure. Le rail d'icônes de 64 px qui tenait lieu de version mobile coûtait
 * 18 % de la largeur d'un téléphone de 360 px pour n'afficher aucun libellé : on
 * payait la place d'une navigation sans en avoir l'usage. Dans le tiroir, les
 * libellés sont visibles — c'est tout l'intérêt de le déployer.
 *
 * Au-delà, rien ne change par rapport à l'existant : barre à 256 px, repliable à
 * 64 px, choix mémorisé d'une page à l'autre.
 */
import { getUser, clearSession } from './auth.js';
import { auth } from './api.js';
import {
  buildCollapseToggle,
  buildScrim,
  buildTopbar,
  closeDrawer,
  wireDrawer,
} from './nav-drawer.js';

/** Entrées principales, dans l'ordre du parcours naturel. */
const NAV = [
  { href: 'index.html', icon: 'auto_awesome', label: 'Accueil' },
  { href: 'projets.html', icon: 'folder_open', label: 'Projets' },
  { href: 'agents.html', icon: 'smart_toy', label: 'Agents' },
  { href: 'ressources.html', icon: 'inventory_2', label: 'Ressources' },
  { href: 'parametres.html', icon: 'settings', label: 'Paramètres' },
  { href: 'aide.html', icon: 'help', label: 'Aide' },
];

/**
 * Monte la navigation, la barre supérieure mobile et le voile du tiroir.
 *
 * @param {object} options
 * @param {string} options.active fichier de la page courante, pour marquer l'onglet.
 * @param {string} [options.title] titre affiché dans la barre supérieure mobile.
 * @param {() => void} [options.onNewApp] action du bouton « Nouvelle application ».
 *   Par défaut, navigation vers l'accueil ; `index.html` s'en sert pour donner le
 *   focus au champ de saisie plutôt que de recharger la page qu'on regarde déjà.
 * @param {'full'|'rail'} [options.variant] `rail` garde la barre étroite au format
 *   bureau — c'est le choix de l'éditeur, qui partage sa largeur entre la
 *   conversation et l'aperçu. Sans effet sous 768 px : le tiroir est le même
 *   partout, libellés compris.
 */
export function mountAppShell({ active, title, onNewApp, variant = 'full' } = {}) {
  // Une seconde exécution remplacerait la nav par une copie : on s'arrête net
  // plutôt que d'empiler deux barres identiques.
  if (document.querySelector('.app-nav')) return;

  const nav = buildNav({ active, onNewApp, variant });
  const scrim = buildScrim();
  const topbar = buildTopbar({ title: title || document.title.replace(/\s*[—-]\s*Jarvis.*/i, '') });

  document.body.prepend(scrim);
  document.body.prepend(nav);
  document.body.prepend(topbar);

  wireDrawer();
  refreshAccountLabel();
}

/* --------------------------------------------------------------------------- */
/* Construction                                                                 */
/* --------------------------------------------------------------------------- */

function buildNav({ active, onNewApp, variant }) {
  const nav = document.createElement('nav');
  nav.className =
    'app-nav border-r border-white/5 py-md' + (variant === 'rail' ? ' app-nav--rail' : '');
  nav.id = 'app-nav';
  nav.setAttribute('aria-label', 'Navigation principale');

  // Le rail n'a pas de largeur à replier : il est déjà au minimum.
  if (variant !== 'rail') nav.appendChild(buildCollapseToggle());

  // Le défilement vertical est confiné à ce conteneur, pas porté par `.app-nav` lui-même
  // (voir le commentaire sur `.app-nav-scroll` dans tailwind.css) : sans ça, le bouton de
  // repli qui déborde du bord droit de la barre se retrouve rogné.
  const scroll = document.createElement('div');
  scroll.className = 'app-nav-scroll';
  nav.appendChild(scroll);

  const top = document.createElement('div');
  top.className = 'flex flex-col gap-md px-3';

  /* --- Marque -------------------------------------------------------------- */
  const brand = document.createElement('a');
  brand.href = 'index.html';
  brand.className = 'flex items-center gap-1.5 px-1.5 min-w-0 h-10 shrink-0';
  brand.innerHTML =
    '<img alt="Jarvis" class="logo-mark w-5 h-5 object-contain shrink-0" src="/assets/jarvis-mark.png">' +
    '<span class="nav-label font-headline-md text-headline-md tracking-tight text-on-surface truncate">Jarvis</span>';
  top.appendChild(brand);

  /* --- Appel à l'action ---------------------------------------------------- */
  const create = document.createElement('button');
  create.type = 'button';
  create.id = 'new-app-btn';
  create.className =
    'nav-item flex items-center justify-center gap-sm px-sm bg-surface-container-highest text-on-surface ' +
    'rounded-lg font-label-md text-label-md transition-transform duration-150 ease-out ' +
    'hover:scale-[0.97] hover:bg-surface-bright w-full group border border-outline-variant/30';
  create.innerHTML =
    '<span class="material-symbols-outlined text-base group-hover:rotate-90 transition-transform duration-300">add</span>' +
    '<span class="nav-label">Nouvelle application</span>';
  create.addEventListener('click', () => {
    closeDrawer();
    if (onNewApp) onNewApp();
    else window.location.href = 'index.html';
  });
  top.appendChild(create);

  /* --- Entrées ------------------------------------------------------------- */
  const list = document.createElement('ul');
  list.className = 'flex flex-col gap-1 w-full';
  for (const entry of NAV) {
    list.appendChild(navItem(entry, entry.href === active));
  }
  top.appendChild(list);
  scroll.appendChild(top);

  /* --- Pied : compte et déconnexion ---------------------------------------- */
  const bottom = document.createElement('div');
  bottom.className = 'px-3 w-full flex flex-col gap-1 pb-2';

  const account = document.createElement('a');
  account.href = 'parametres.html#profile';
  account.id = 'nav-account';
  account.className =
    'nav-item flex items-center gap-sm px-sm text-on-surface-variant/80 hover:text-on-surface ' +
    'transition-colors hover:bg-surface-container rounded-lg duration-150 w-full';
  account.innerHTML =
    '<span class="material-symbols-outlined text-lg shrink-0">account_circle</span>' +
    '<span class="nav-label font-label-md text-label-md truncate">Compte</span>';
  bottom.appendChild(account);

  const logout = document.createElement('button');
  logout.type = 'button';
  logout.className =
    'nav-item flex items-center gap-sm px-sm text-on-surface-variant/80 hover:text-on-surface ' +
    'transition-colors hover:bg-surface-container rounded-lg duration-150 w-full text-left';
  logout.innerHTML =
    '<span class="material-symbols-outlined text-lg shrink-0">logout</span>' +
    '<span class="nav-label font-label-md text-label-md">Déconnexion</span>';
  logout.addEventListener('click', () => {
    // La session est effacée ici et non par le lien : un `<a href>` laissait le
    // jeton en place, et la page de connexion renvoyait aussitôt l'utilisateur
    // « déconnecté » dans l'application.
    clearSession();
    window.location.href = 'connexion.html';
  });
  bottom.appendChild(logout);

  scroll.appendChild(bottom);
  return nav;
}

function navItem({ href, icon, label }, current) {
  const li = document.createElement('li');
  const a = document.createElement('a');
  a.href = href;
  a.className =
    'nav-item flex items-center gap-sm px-sm rounded-lg transition-colors duration-150 ease-out ' +
    (current
      ? 'bg-surface-container text-on-surface font-semibold'
      : 'text-on-surface-variant/80 hover:text-on-surface hover:bg-surface-container');
  if (current) a.setAttribute('aria-current', 'page');
  a.innerHTML =
    `<span class="material-symbols-outlined text-lg shrink-0"${current ? " style=\"font-variation-settings:'FILL' 1;\"" : ''}>${icon}</span>` +
    `<span class="nav-label font-label-md text-label-md">${label}</span>`;
  li.appendChild(a);
  return li;
}

/* --------------------------------------------------------------------------- */
/* Compte                                                                       */
/* --------------------------------------------------------------------------- */

/** Remplace « Compte » par le nom réel, du cache d'abord puis du serveur. */
function refreshAccountLabel() {
  const label = document.querySelector('#nav-account .nav-label');
  if (!label) return;

  const apply = (user) => {
    if (user?.name || user?.email) label.textContent = user.name || user.email;
  };

  apply(getUser());
  auth.me().then(apply).catch(() => {
    // Hors ligne ou session expirée : « Compte » reste un libellé valable, et
    // `api.js` s'occupe déjà de rediriger sur un 401.
  });
}

