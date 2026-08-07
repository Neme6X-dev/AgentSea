/**
 * Tous les sites de la plateforme.
 *
 * L'écran sert d'abord au support : quand un client écrit « mon site ne marche pas »,
 * il faut retrouver son site en trois secondes et voir son état, son score de revue et
 * son URL. Les filtres sont donc ceux d'une recherche, pas ceux d'un rapport.
 *
 * Le score de revue est affiché avec son verdict, et non seul : « 62 » ne veut rien
 * dire, « 62 — à corriger » se comprend sans documentation.
 */
import { sites } from '../lib/admin-api.js';
import {
  card, dataTable, errorBanner, mountAdminShell, pager, setRefreshing, skeleton, tileGrid,
} from '../lib/admin-shell.js';
import { badge, groupThousands, statTile } from '../lib/charts.js';
import { instantRelatif } from './admin.js';

const ETATS = [
  ['', 'Tous'],
  ['deployed', 'En ligne'],
  ['ready', 'Prêt à publier'],
  ['running', 'En cours'],
  ['pending', 'En attente'],
  ['error', 'En erreur'],
];

let zoneTable = null;
let zoneResume = null;
let premierRendu = true;
const filtres = { page: 1, size: 25, q: '', status: '', country: '' };

async function charger() {
  if (premierRendu) skeleton(zoneTable, 8);
  else setRefreshing(zoneTable, true);

  try {
    const page = await sites.list(filtres);
    rendreResume(page);
    rendreTable(page);
    premierRendu = false;
  } catch (error) {
    errorBanner(zoneTable, error, charger);
  } finally {
    setRefreshing(zoneTable, false);
  }
}

function rendreResume(page) {
  zoneResume.innerHTML = '';
  const enLigne = page.items.filter((s) => s.status === 'deployed').length;
  const enErreur = page.items.filter((s) => s.status === 'error').length;
  const vues = page.items.reduce((sum, s) => sum + (s.views || 0), 0);
  const scores = page.items.map((s) => s.score).filter((s) => typeof s === 'number');

  const grille = tileGrid();
  grille.append(
    statTile({ label: 'Sites (total)', value: groupThousands(page.total), icon: 'language' }),
    statTile({ label: 'En ligne sur cette page', value: groupThousands(enLigne), icon: 'public' }),
    statTile({
      label: 'Score de revue moyen',
      value: scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : '—',
      icon: 'verified',
      hint: scores.length ? `sur ${scores.length} site(s) relus` : 'aucun rapport',
    }),
    statTile({
      label: 'Pages vues', value: groupThousands(vues), icon: 'visibility',
      hint: enErreur ? `${enErreur} site(s) en erreur` : 'aucun site en erreur',
    }),
  );
  zoneResume.appendChild(grille);
}

function rendreTable(page) {
  zoneTable.innerHTML = '';
  zoneTable.appendChild(
    dataTable(
      ['Site', 'Propriétaire', 'Pays', 'État', 'Revue', 'Versions', 'Vues', 'Créé'],
      page.items.map((s) => [
        celluleSite(s),
        s.user_email || '—',
        `${s.flag} ${s.country}`,
        badge(libelleEtat(s.status), tonalite(s.status)),
        celluleScore(s),
        groupThousands(s.versions),
        groupThousands(s.views),
        instantRelatif(s.created_at),
      ]),
      { empty: 'Aucun site ne correspond à ces filtres.' },
    ),
  );
  zoneTable.appendChild(pager(page, (p) => { filtres.page = p; charger(); }));
}

function celluleSite(s) {
  const box = document.createElement('div');
  box.className = 'flex flex-col leading-tight min-w-[180px]';
  if (s.site_url) {
    const lien = document.createElement('a');
    lien.href = s.site_url;
    lien.target = '_blank';
    // `noopener` systématique sur un lien externe : sans lui, la page ouverte garde
    // une référence vers celle du back-office et peut la rediriger.
    lien.rel = 'noopener noreferrer';
    lien.className = 'text-on-surface hover:text-primary transition-colors inline-flex items-center gap-1';
    lien.innerHTML = `${s.slug}<span class="material-symbols-outlined text-xs">open_in_new</span>`;
    box.appendChild(lien);
  } else {
    const nom = document.createElement('span');
    nom.className = 'text-on-surface';
    nom.textContent = s.slug;
    box.appendChild(nom);
  }
  if (s.business_type) {
    const secteur = document.createElement('span');
    secteur.className = 'font-body-sm text-body-sm text-on-surface-variant/70';
    secteur.textContent = s.business_type;
    box.appendChild(secteur);
  }
  return box;
}

function celluleScore(s) {
  if (typeof s.score !== 'number') {
    const rien = document.createElement('span');
    rien.className = 'text-on-surface-variant/50';
    rien.textContent = '—';
    return rien;
  }
  const verdicts = { pass: ['Conforme', 'good'], warn: ['À surveiller', 'warning'], fail: ['À corriger', 'critical'] };
  const [libelle, tone] = verdicts[s.verdict] || ['Relu', 'neutral'];
  return badge(`${s.score} — ${libelle}`, tone);
}

function libelleEtat(status) {
  return Object.fromEntries(ETATS)[status] || status;
}

function tonalite(status) {
  return { deployed: 'good', ready: 'neutral', running: 'neutral', pending: 'neutral', error: 'critical', failed: 'critical' }[status] || 'neutral';
}

function rendreFiltres(host) {
  const barre = card({ className: 'flex flex-wrap items-end gap-md' });

  const wrap = document.createElement('label');
  wrap.className = 'flex flex-col gap-1 flex-1 min-w-[220px]';
  wrap.innerHTML = '<span class="font-label-md text-label-md text-on-surface-variant">Rechercher</span>';
  const box = document.createElement('div');
  box.className =
    'flex items-center gap-2 px-3 h-10 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 focus-within:border-outline';
  box.innerHTML = '<span class="material-symbols-outlined text-base text-on-surface-variant/60">search</span>';
  const input = document.createElement('input');
  input.type = 'search';
  input.placeholder = 'Nom du site ou demande initiale';
  input.className =
    'flex-1 bg-transparent border-0 p-0 font-body-md text-body-md text-on-surface focus:ring-0 placeholder:text-on-surface-variant/40';
  let minuteur;
  input.addEventListener('input', () => {
    clearTimeout(minuteur);
    minuteur = setTimeout(() => { filtres.q = input.value.trim(); filtres.page = 1; charger(); }, 350);
  });
  box.appendChild(input);
  wrap.appendChild(box);
  barre.appendChild(wrap);

  const etat = document.createElement('label');
  etat.className = 'flex flex-col gap-1 min-w-[160px]';
  etat.innerHTML = '<span class="font-label-md text-label-md text-on-surface-variant">État</span>';
  const select = document.createElement('select');
  select.className =
    'h-10 px-3 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 font-body-md text-body-md text-on-surface focus:ring-0 focus:border-outline';
  for (const [v, l] of ETATS) {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = l;
    select.appendChild(opt);
  }
  select.addEventListener('change', () => { filtres.status = select.value; filtres.page = 1; charger(); });
  etat.appendChild(select);
  barre.appendChild(etat);

  const pays = document.createElement('label');
  pays.className = 'flex flex-col gap-1 min-w-[140px]';
  pays.innerHTML = '<span class="font-label-md text-label-md text-on-surface-variant">Pays (code ISO)</span>';
  const paysInput = document.createElement('input');
  paysInput.maxLength = 2;
  paysInput.placeholder = 'BJ';
  paysInput.className =
    'h-10 px-3 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 font-body-md text-body-md text-on-surface uppercase focus:ring-0 focus:border-outline';
  let minuteurPays;
  paysInput.addEventListener('input', () => {
    clearTimeout(minuteurPays);
    minuteurPays = setTimeout(() => {
      filtres.country = paysInput.value.trim().toUpperCase();
      filtres.page = 1;
      charger();
    }, 350);
  });
  pays.appendChild(paysInput);
  barre.appendChild(pays);

  host.appendChild(barre);
}

async function init() {
  const shell = await mountAdminShell({
    active: 'admin-sites.html',
    title: 'Sites',
    subtitle: 'Tous les sites générés sur la plateforme',
  });
  if (!shell) return;

  zoneResume = document.createElement('div');
  shell.content.appendChild(zoneResume);
  rendreFiltres(shell.content);
  zoneTable = card();
  shell.content.appendChild(zoneTable);
  await charger();
}

init();
