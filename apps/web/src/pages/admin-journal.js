/**
 * Journal d'audit : qui a fait quoi, sur quel compte, et quand.
 *
 * L'écran existe pour une raison précise : ce qu'un administrateur fait sur le compte
 * d'un client — le suspendre, changer son offre, relancer un travail — doit rester
 * explicable des mois plus tard, y compris à un client mécontent ou à un régulateur.
 *
 * Le détail de chaque modification est affiché sous forme **avant → après** plutôt que
 * comme un objet brut : « offre : decouverte → pro » se lit, un JSON ne se lit pas.
 * L'e-mail de l'acteur est conservé en plus de son identifiant, de sorte que la
 * suppression d'un compte n'efface pas la trace de ce qu'il a fait.
 */
import { audit } from '../lib/admin-api.js';
import {
  card, dataTable, errorBanner, mountAdminShell, pager, setRefreshing, skeleton,
} from '../lib/admin-shell.js';
import { badge } from '../lib/charts.js';

const ACTIONS = [
  ['', 'Toutes les actions'],
  ['user.update', 'Modification de compte'],
  ['job.retry', 'Relance de travail'],
  ['job.reclaim', 'Reprise de la file'],
  ['flag.set', 'Interrupteur modifié'],
];

const LIBELLES_CHAMPS = {
  plan: 'Offre', role: 'Rôle', status: 'État', country: 'Pays',
  name: 'Nom', company: 'Société', plan_period: 'Périodicité',
  suspended_at: 'Date de suspension', suspension_reason: 'Motif de suspension',
  enabled: 'Activé', rollout_percent: 'Déploiement', description: 'Description',
};

let zoneTable = null;
let premierRendu = true;
const filtres = { page: 1, size: 25, action: '' };

async function charger() {
  if (premierRendu) skeleton(zoneTable, 8);
  else setRefreshing(zoneTable, true);

  try {
    rendre(await audit(filtres));
    premierRendu = false;
  } catch (error) {
    errorBanner(zoneTable, error, charger);
  } finally {
    setRefreshing(zoneTable, false);
  }
}

function rendre(page) {
  zoneTable.innerHTML = '';
  zoneTable.appendChild(
    dataTable(
      ['Quand', 'Auteur', 'Action', 'Cible', 'Détail'],
      page.items.map((e) => [
        horodatage(e.ts),
        e.actor_email || 'système',
        badge(libelleAction(e.action), tonalite(e.action)),
        e.target_type ? `${e.target_type} #${e.target_id}` : '—',
        celluleChangements(e),
      ]),
      { empty: 'Aucune action enregistrée.' },
    ),
  );
  zoneTable.appendChild(pager(page, (p) => { filtres.page = p; charger(); }));
}

/**
 * Date et heure complètes, sans forme relative.
 *
 * Contrairement au fil d'activité, un journal d'audit doit porter l'instant exact :
 * « il y a 3 jours » ne permet pas de recouper une trace avec un incident daté.
 */
function horodatage(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso || '—';
  return d.toLocaleString('fr-FR', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function libelleAction(action) {
  return Object.fromEntries(ACTIONS)[action] || action;
}

function tonalite(action) {
  if (action === 'user.update') return 'warning';
  if (action.startsWith('flag')) return 'neutral';
  return 'neutral';
}

function celluleChangements(entree) {
  const box = document.createElement('div');
  box.className = 'flex flex-col gap-0.5 min-w-[220px]';

  const changements = entree.changes || {};
  const cles = Object.keys(changements);

  if (!cles.length && !entree.note) {
    const rien = document.createElement('span');
    rien.className = 'text-on-surface-variant/40';
    rien.textContent = '—';
    return rien;
  }

  for (const cle of cles) {
    const valeur = changements[cle];
    const ligne = document.createElement('span');
    ligne.className = 'font-body-sm text-body-sm text-on-surface-variant';
    const libelle = LIBELLES_CHAMPS[cle] || cle;

    // Le back-office envoie `{avant, après}` pour une modification de compte, et une
    // valeur simple pour les autres actions. On gère les deux plutôt que d'imposer un
    // format unique à des actions qui n'ont pas la même nature.
    if (valeur && typeof valeur === 'object' && 'avant' in valeur) {
      ligne.innerHTML =
        `<b class="text-on-surface font-medium">${libelle}</b> : ` +
        `<span class="line-through opacity-60">${afficher(valeur.avant)}</span> → ` +
        `<span class="text-on-surface">${afficher(valeur['après'])}</span>`;
    } else {
      ligne.innerHTML = `<b class="text-on-surface font-medium">${libelle}</b> : ${afficher(valeur)}`;
    }
    box.appendChild(ligne);
  }

  if (entree.note) {
    const note = document.createElement('span');
    note.className = 'font-body-sm text-body-sm text-on-surface-variant/70 italic';
    note.textContent = `« ${entree.note} »`;
    box.appendChild(note);
  }

  return box;
}

function afficher(valeur) {
  if (valeur === null || valeur === undefined || valeur === '') return '∅';
  if (typeof valeur === 'boolean') return valeur ? 'oui' : 'non';
  return String(valeur);
}

function rendreFiltres(host) {
  const barre = card({ className: 'flex flex-wrap items-end gap-md' });

  const wrap = document.createElement('label');
  wrap.className = 'flex flex-col gap-1 min-w-[220px]';
  wrap.innerHTML = '<span class="font-label-md text-label-md text-on-surface-variant">Action</span>';
  const select = document.createElement('select');
  select.className =
    'h-10 px-3 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 font-body-md text-body-md text-on-surface focus:ring-0 focus:border-outline';
  for (const [v, l] of ACTIONS) {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = l;
    select.appendChild(opt);
  }
  select.addEventListener('change', () => { filtres.action = select.value; filtres.page = 1; charger(); });
  wrap.appendChild(select);
  barre.appendChild(wrap);

  const rappel = document.createElement('p');
  rappel.className = 'font-body-sm text-body-sm text-on-surface-variant/60 flex-1 min-w-[260px]';
  rappel.textContent =
    "Le journal est en écriture seule : une action qui n'a pas pu y être consignée n'est pas appliquée.";
  barre.appendChild(rappel);

  host.appendChild(barre);
}

async function init() {
  const shell = await mountAdminShell({
    active: 'admin-journal.html',
    title: "Journal d'audit",
    subtitle: 'Toutes les actions administratives, dans leur ordre chronologique',
  });
  if (!shell) return;

  rendreFiltres(shell.content);
  zoneTable = card();
  shell.content.appendChild(zoneTable);
  await charger();
}

init();
