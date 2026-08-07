/**
 * Mécanique de navigation partagée entre le produit et le back-office.
 *
 * Les deux ossatures (`app-shell.js`, `admin-shell.js`) n'ont pas les mêmes entrées
 * ni le même en-tête, mais elles ont exactement le même comportement de barre :
 * tiroir sous 768 px, barre latérale repliable au-delà. Ce comportement est ici, une
 * fois. Deux implémentations auraient divergé — et un utilisateur qui passe du
 * produit à l'administration aurait dû réapprendre où se trouve la navigation.
 *
 * Le style associé vit dans `src/styles/tailwind.css` (`.app-nav`, `.app-scrim`,
 * `.app-topbar`, `.app-main`).
 */

const COLLAPSE_KEY = 'jarvisNavCollapsed';
const DESKTOP = '(min-width: 768px)';

/* --------------------------------------------------------------------------- */
/* Tiroir mobile                                                                */
/* --------------------------------------------------------------------------- */

export function isDrawerOpen() {
  return document.documentElement.classList.contains('nav-open');
}

export function openDrawer() {
  document.documentElement.classList.add('nav-open');
  // Le corps de page ne défile plus derrière le tiroir : sans cela, un glissement
  // du doigt sur le voile fait défiler la page en dessous, et on retrouve le
  // contenu déplacé en refermant.
  document.body.style.overflow = 'hidden';
  document.getElementById('nav-drawer-toggle')?.setAttribute('aria-expanded', 'true');
  document.querySelector('.app-nav a, .app-nav button')?.focus({ preventScroll: true });
}

export function closeDrawer() {
  if (!isDrawerOpen()) return;
  document.documentElement.classList.remove('nav-open');
  document.body.style.overflow = '';
  const toggle = document.getElementById('nav-drawer-toggle');
  toggle?.setAttribute('aria-expanded', 'false');
  toggle?.focus({ preventScroll: true });
}

/**
 * Barre supérieure mobile : ouverture du tiroir, marque, et un emplacement libre
 * à droite pour ce que l'écran veut y mettre.
 *
 * @param {object} options
 * @param {string} options.title texte affiché à côté de la marque.
 * @param {string} [options.href] destination de la marque.
 */
export function buildTopbar({ title, href = 'index.html' }) {
  const bar = document.createElement('header');
  bar.className = 'app-topbar md:hidden';

  const burger = document.createElement('button');
  burger.type = 'button';
  burger.id = 'nav-drawer-toggle';
  burger.className =
    'w-11 h-11 -ml-1 shrink-0 grid place-items-center rounded-lg text-on-surface-variant ' +
    'hover:text-on-surface hover:bg-surface-container transition-colors';
  burger.setAttribute('aria-label', 'Ouvrir la navigation');
  burger.setAttribute('aria-expanded', 'false');
  burger.setAttribute('aria-controls', 'app-nav');
  burger.innerHTML = '<span class="material-symbols-outlined text-2xl">menu</span>';
  burger.addEventListener('click', () => (isDrawerOpen() ? closeDrawer() : openDrawer()));
  bar.appendChild(burger);

  const brand = document.createElement('a');
  brand.href = href;
  brand.className = 'flex items-center gap-2 min-w-0 flex-1';
  const mark = document.createElement('img');
  mark.alt = '';
  mark.className = 'logo-mark w-5 h-5 object-contain shrink-0';
  mark.src = '/assets/jarvis-mark.png';
  const label = document.createElement('span');
  label.className = 'font-headline-md text-headline-md text-on-surface truncate';
  // `textContent` et non `innerHTML` : le titre vient parfois du <title> de la page.
  label.textContent = title || 'Jarvis';
  brand.append(mark, label);
  bar.appendChild(brand);

  return bar;
}

/** Voile du tiroir. Cliquable pour refermer — le geste attendu de tout tiroir. */
export function buildScrim() {
  const scrim = document.createElement('div');
  scrim.className = 'app-scrim md:hidden';
  scrim.setAttribute('aria-hidden', 'true');
  scrim.addEventListener('click', closeDrawer);
  return scrim;
}

/** Bouton de repli de la barre latérale, ancré à son bord droit (bureau seulement). */
export function buildCollapseToggle() {
  const button = document.createElement('button');
  button.type = 'button';
  button.id = 'nav-collapse-toggle';
  button.className =
    'hidden md:flex absolute top-4 -right-3 w-6 h-6 items-center justify-center rounded-full ' +
    'bg-surface-container-high border border-outline-variant/30 text-on-surface-variant ' +
    'hover:text-on-surface hover:bg-surface-container-highest shadow-md transition-colors z-10';
  button.title = 'Réduire / élargir la navigation';
  button.setAttribute('aria-label', 'Réduire ou élargir la navigation');
  button.innerHTML =
    '<span class="material-symbols-outlined nav-toggle-icon text-[15px]">chevron_left</span>';
  button.addEventListener('click', () => {
    const collapsed = document.documentElement.classList.toggle('nav-collapsed');
    localStorage.setItem(COLLAPSE_KEY, collapsed ? '1' : '0');
  });
  return button;
}

/** Fermetures du tiroir : Échap, clic sur une entrée, passage en largeur bureau. */
export function wireDrawer() {
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') closeDrawer();
  });

  // Un lien qui mène ailleurs ferme le tiroir. Utile pour les ancres internes, qui
  // ne rechargent pas la page et laisseraient sinon le tiroir ouvert par-dessus la
  // section qu'on vient de demander.
  document.querySelector('.app-nav')?.addEventListener('click', (event) => {
    if (event.target.closest('a')) closeDrawer();
  });

  // Passer en largeur bureau avec le tiroir ouvert laisserait le corps de page
  // bloqué en `overflow: hidden` alors que le tiroir n'existe plus.
  window.matchMedia(DESKTOP).addEventListener('change', (event) => {
    if (event.matches) closeDrawer();
  });
}

/**
 * Restaure l'état replié.
 *
 * Les pages produit le font depuis un script inline en tête de document : un module
 * ES est toujours différé, la barre s'afficherait dépliée puis sauterait. Le
 * back-office, dont l'ossature est construite entièrement en JavaScript, n'a pas ce
 * problème et appelle simplement cette fonction.
 */
export function restoreNavState() {
  if (localStorage.getItem(COLLAPSE_KEY) === '1') {
    document.documentElement.classList.add('nav-collapsed');
  }
}
