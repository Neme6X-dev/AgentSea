/**
 * Gestion des comptes.
 *
 * Deux principes de conception, tous deux dictés par le fait que ces actions touchent
 * des clients réels :
 *
 * - **Aucune action destructrice sans confirmation nommée.** Suspendre un compte
 *   demande d'écrire un motif : c'est ce motif que le client verra, et c'est lui qui
 *   restera dans le journal d'audit. Un bouton qui suspend en un clic finit toujours
 *   par être cliqué par erreur.
 * - **Seul le rôle administrateur peut écrire.** Le support consulte les comptes
 *   pour aider un client ; il ne change pas leur offre. L'interface masque les
 *   commandes qu'il n'a pas — mais c'est le serveur qui tranche à chaque appel.
 */
import { users } from '../lib/admin-api.js';
import {
  card, dataTable, errorBanner, mountAdminShell, pager, setRefreshing, skeleton,
} from '../lib/admin-shell.js';
import { badge, groupThousands, meter } from '../lib/charts.js';
import { instantRelatif } from './admin.js';

const OFFRES = ['decouverte', 'essentiel', 'pro', 'business', 'agence'];
const ROLES = [
  ['user', 'Utilisateur'], ['support', 'Support'], ['admin', 'Administrateur'], ['owner', 'Propriétaire'],
];

let content = null;
let moiMeme = null;
let premierRendu = true;
const filtres = { page: 1, size: 25, q: '', role: '', plan: '', status: '', sort: 'created_at' };

/** Vrai si le compte connecté peut modifier. Confort d'affichage : le serveur revérifie. */
function peutEcrire() {
  return ['admin', 'owner'].includes(moiMeme?.role);
}

async function charger() {
  const cible = zoneTable;
  if (premierRendu) skeleton(cible, 8);
  else setRefreshing(cible, true);

  try {
    const page = await users.list(filtres);
    rendreTable(cible, page);
    premierRendu = false;
  } catch (error) {
    errorBanner(cible, error, charger);
  } finally {
    setRefreshing(cible, false);
  }
}

let zoneTable = null;

function rendreFiltres(host) {
  const barre = card({ className: 'flex flex-wrap items-end gap-md' });

  const recherche = champ('Rechercher', 'search');
  recherche.input.placeholder = 'E-mail, nom ou société';
  recherche.input.value = filtres.q;
  // On attend la fin de la saisie plutôt que d'interroger à chaque touche : sur une
  // connexion lente, taper « cotonou » lancerait sept requêtes dont six inutiles,
  // et la dernière arrivée n'est pas forcément la dernière tapée.
  let minuteur;
  recherche.input.addEventListener('input', () => {
    clearTimeout(minuteur);
    minuteur = setTimeout(() => {
      filtres.q = recherche.input.value.trim();
      filtres.page = 1;
      charger();
    }, 350);
  });
  barre.appendChild(recherche.wrap);

  barre.appendChild(
    selecteur('Offre', [['', 'Toutes'], ...OFFRES.map((p) => [p, p])], filtres.plan, (v) => {
      filtres.plan = v; filtres.page = 1; charger();
    }),
  );
  barre.appendChild(
    selecteur('Rôle', [['', 'Tous'], ...ROLES], filtres.role, (v) => {
      filtres.role = v; filtres.page = 1; charger();
    }),
  );
  barre.appendChild(
    selecteur('État', [['', 'Tous'], ['active', 'Actif'], ['suspended', 'Suspendu']], filtres.status, (v) => {
      filtres.status = v; filtres.page = 1; charger();
    }),
  );
  barre.appendChild(
    selecteur('Tri', [
      ['created_at', 'Inscription récente'],
      ['last_seen_at', 'Vu récemment'],
      ['sites', 'Nombre de sites'],
      ['email', 'E-mail (A→Z)'],
    ], filtres.sort, (v) => { filtres.sort = v; filtres.page = 1; charger(); }),
  );

  host.appendChild(barre);
}

function champ(label, icon) {
  const wrap = document.createElement('label');
  wrap.className = 'flex flex-col gap-1 flex-1 min-w-[200px]';
  const span = document.createElement('span');
  span.className = 'font-label-md text-label-md text-on-surface-variant';
  span.textContent = label;
  const box = document.createElement('div');
  box.className =
    'flex items-center gap-2 px-3 h-10 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 focus-within:border-outline';
  if (icon) {
    const ico = document.createElement('span');
    ico.className = 'material-symbols-outlined text-base text-on-surface-variant/60';
    ico.textContent = icon;
    box.appendChild(ico);
  }
  const input = document.createElement('input');
  input.type = 'search';
  input.className =
    'flex-1 bg-transparent border-0 p-0 font-body-md text-body-md text-on-surface focus:ring-0 placeholder:text-on-surface-variant/40';
  box.appendChild(input);
  wrap.append(span, box);
  return { wrap, input };
}

function selecteur(label, options, valeur, onChange) {
  const wrap = document.createElement('label');
  wrap.className = 'flex flex-col gap-1 min-w-[150px]';
  const span = document.createElement('span');
  span.className = 'font-label-md text-label-md text-on-surface-variant';
  span.textContent = label;
  const select = document.createElement('select');
  select.className =
    'h-10 px-3 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 ' +
    'font-body-md text-body-md text-on-surface focus:ring-0 focus:border-outline';
  for (const [v, l] of options) {
    const opt = document.createElement('option');
    opt.value = v;
    opt.textContent = l;
    if (v === valeur) opt.selected = true;
    select.appendChild(opt);
  }
  select.addEventListener('change', () => onChange(select.value));
  wrap.append(span, select);
  return wrap;
}

function rendreTable(host, page) {
  host.innerHTML = '';

  const lignes = page.items.map((u) => [
    celluleCompte(u),
    `${u.flag} ${u.country_name}`,
    u.plan,
    badge(u.status === 'suspended' ? 'Suspendu' : 'Actif', u.status === 'suspended' ? 'critical' : 'good'),
    badge(libelleRole(u.role), u.role === 'user' ? 'neutral' : 'good'),
    `${groupThousands(u.sites)} (${groupThousands(u.published)} publiés)`,
    instantRelatif(u.last_seen_at) || 'jamais',
    actions(u),
  ]);

  host.appendChild(
    dataTable(
      ['Compte', 'Pays', 'Offre', 'État', 'Rôle', 'Sites', 'Dernière visite', ''],
      lignes,
      { empty: 'Aucun compte ne correspond à ces filtres.' },
    ),
  );
  host.appendChild(pager(page, (p) => { filtres.page = p; charger(); }));
}

function celluleCompte(u) {
  const box = document.createElement('div');
  box.className = 'flex flex-col leading-tight min-w-[200px]';
  const nom = document.createElement('span');
  nom.className = 'text-on-surface';
  nom.textContent = u.name || u.email;
  const detail = document.createElement('span');
  detail.className = 'font-body-sm text-body-sm text-on-surface-variant/70';
  detail.textContent = u.name ? u.email : u.company || u.provider;
  box.append(nom, detail);
  return box;
}

function libelleRole(role) {
  return Object.fromEntries(ROLES)[role] || role;
}

function actions(u) {
  const box = document.createElement('div');
  box.className = 'flex items-center gap-1 justify-end';

  const detail = boutonIcone('info', 'Voir la fiche', () => ouvrirFiche(u.id));
  box.appendChild(detail);

  if (!peutEcrire() || u.id === moiMeme?.id) return box;

  if (u.status === 'suspended') {
    box.appendChild(boutonIcone('lock_open', 'Réactiver', async () => {
      await users.reactivate(u.id);
      charger();
    }));
  } else {
    box.appendChild(boutonIcone('block', 'Suspendre', () => ouvrirSuspension(u)));
  }
  return box;
}

function boutonIcone(icon, titre, onClick) {
  const b = document.createElement('button');
  b.type = 'button';
  b.title = titre;
  b.setAttribute('aria-label', titre);
  b.className =
    'w-9 h-9 grid place-items-center rounded-full text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest transition-colors';
  b.innerHTML = `<span class="material-symbols-outlined text-base">${icon}</span>`;
  b.addEventListener('click', onClick);
  return b;
}

/* --------------------------------------------------------------------------- */
/* Panneaux                                                                    */
/* --------------------------------------------------------------------------- */

function panneau(titre) {
  const overlay = document.createElement('div');
  overlay.className = 'fixed inset-0 z-[90] bg-black/60 backdrop-blur-sm flex items-center justify-center p-md';
  overlay.setAttribute('role', 'dialog');
  overlay.setAttribute('aria-modal', 'true');

  const boite = document.createElement('div');
  boite.className =
    'bg-surface-container border border-outline-variant/30 rounded-2xl w-full max-w-2xl max-h-[85vh] overflow-y-auto p-lg flex flex-col gap-md';

  const entete = document.createElement('div');
  entete.className = 'flex items-start justify-between gap-md';
  const h = document.createElement('h2');
  h.className = 'font-headline-lg text-headline-lg text-on-surface';
  h.textContent = titre;
  const fermer = boutonIcone('close', 'Fermer', () => overlay.remove());
  entete.append(h, fermer);
  boite.appendChild(entete);

  overlay.appendChild(boite);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) overlay.remove(); });
  // Échap ferme : un panneau modal qu'on ne peut fermer qu'à la souris bloque
  // l'utilisateur au clavier.
  const esc = (e) => { if (e.key === 'Escape') { overlay.remove(); document.removeEventListener('keydown', esc); } };
  document.addEventListener('keydown', esc);

  document.body.appendChild(overlay);
  return { overlay, boite };
}

async function ouvrirFiche(id) {
  const { boite } = panneau('Fiche du compte');
  const corps = document.createElement('div');
  skeleton(corps, 5);
  boite.appendChild(corps);

  try {
    const d = await users.get(id);
    corps.innerHTML = '';

    const infos = document.createElement('dl');
    infos.className = 'grid grid-cols-2 gap-x-lg gap-y-2';
    for (const [cle, valeur] of [
      ['E-mail', d.user.email],
      ['Nom', d.user.name || '—'],
      ['Société', d.user.company || '—'],
      ['Pays', `${d.country.flag} ${d.country.name}`],
      ['Téléphone', d.user.phone || '—'],
      ['Offre', `${d.plan.name} — ${d.plan.price.formatted}/${d.plan.price.period}`],
      ['Inscription', new Date(d.user.created_at).toLocaleDateString('fr-FR')],
      ['Coût IA cumulé', `${groupThousands(d.lifetime_llm_cost_xof)} FCFA`],
    ]) {
      const dt = document.createElement('dt');
      dt.className = 'font-label-md text-label-md text-on-surface-variant';
      dt.textContent = cle;
      const dd = document.createElement('dd');
      dd.className = 'font-body-md text-body-md text-on-surface';
      dd.textContent = valeur;
      infos.append(dt, dd);
    }
    corps.appendChild(infos);

    const conso = document.createElement('div');
    conso.className = 'flex flex-col gap-sm pt-md border-t border-outline-variant/20';
    const titreConso = document.createElement('h3');
    titreConso.className = 'font-headline-md text-headline-md text-on-surface';
    titreConso.textContent = `Consommation (${d.period})`;
    conso.appendChild(titreConso);
    conso.appendChild(meter({
      label: 'Générations ce mois-ci',
      used: d.usage.generations || 0,
      limit: d.plan.quotas.generations_per_month,
    }));
    conso.appendChild(meter({
      label: 'Sites',
      used: d.sites.length,
      limit: d.plan.quotas.sites,
    }));
    corps.appendChild(conso);

    if (peutEcrire()) corps.appendChild(formulaireModification(d));

    const titreSites = document.createElement('h3');
    titreSites.className = 'font-headline-md text-headline-md text-on-surface pt-md border-t border-outline-variant/20';
    titreSites.textContent = `Sites (${d.sites.length})`;
    corps.appendChild(titreSites);
    corps.appendChild(
      dataTable(
        ['Site', 'État', 'Créé le'],
        d.sites.slice(0, 15).map((s) => [
          s.slug,
          badge(s.status, s.status === 'deployed' ? 'good' : s.status === 'error' ? 'critical' : 'neutral'),
          new Date(s.created_at).toLocaleDateString('fr-FR'),
        ]),
        { empty: 'Aucun site.' },
      ),
    );
  } catch (error) {
    errorBanner(corps, error);
  }
}

function formulaireModification(d) {
  const form = document.createElement('form');
  form.className = 'flex flex-wrap items-end gap-md pt-md border-t border-outline-variant/20';

  const titre = document.createElement('h3');
  titre.className = 'font-headline-md text-headline-md text-on-surface w-full';
  titre.textContent = 'Modifier';
  form.appendChild(titre);

  let offre = d.user.plan;
  let role = d.user.role;
  form.appendChild(selecteur('Offre', OFFRES.map((p) => [p, p]), offre, (v) => { offre = v; }));
  form.appendChild(selecteur('Rôle', ROLES, role, (v) => { role = v; }));

  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.className =
    'h-10 px-5 rounded-full bg-on-surface text-background font-label-md text-label-md font-semibold hover:bg-surface-variant hover:text-on-surface transition-colors';
  submit.textContent = 'Enregistrer';
  form.appendChild(submit);

  const retour = document.createElement('p');
  retour.className = 'w-full font-body-sm text-body-sm';
  form.appendChild(retour);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const changements = {};
    if (offre !== d.user.plan) changements.plan = offre;
    if (role !== d.user.role) changements.role = role;
    if (!Object.keys(changements).length) {
      retour.textContent = 'Rien à enregistrer.';
      retour.className = 'w-full font-body-sm text-body-sm text-on-surface-variant';
      return;
    }
    submit.disabled = true;
    try {
      await users.update(d.user.id, changements);
      retour.textContent = 'Modifications enregistrées.';
      retour.className = 'w-full font-body-sm text-body-sm text-status-good';
      charger();
    } catch (error) {
      retour.textContent = error.message;
      retour.className = 'w-full font-body-sm text-body-sm text-status-critical';
    } finally {
      submit.disabled = false;
    }
  });

  return form;
}

function ouvrirSuspension(u) {
  const { overlay, boite } = panneau('Suspendre ce compte');

  const explication = document.createElement('p');
  explication.className = 'font-body-md text-body-md text-on-surface-variant';
  explication.textContent =
    `${u.email} ne pourra plus se connecter. Ses sites déjà publiés restent en ligne. ` +
    'Le motif saisi ici lui sera affiché et restera dans le journal d\'audit.';
  boite.appendChild(explication);

  const form = document.createElement('form');
  form.className = 'flex flex-col gap-md';

  const label = document.createElement('label');
  label.className = 'flex flex-col gap-1';
  label.innerHTML = '<span class="font-label-md text-label-md text-on-surface-variant">Motif (obligatoire)</span>';
  const motif = document.createElement('textarea');
  motif.required = true;
  motif.rows = 3;
  motif.className =
    'rounded-lg bg-surface-container-high/60 border border-outline-variant/30 p-3 ' +
    'font-body-md text-body-md text-on-surface focus:ring-0 focus:border-outline resize-none';
  motif.placeholder = 'Ex. : impayés depuis deux mois, contenu contraire aux conditions…';
  label.appendChild(motif);
  form.appendChild(label);

  const actions = document.createElement('div');
  actions.className = 'flex items-center justify-end gap-sm';
  const annuler = document.createElement('button');
  annuler.type = 'button';
  annuler.className = 'h-10 px-4 rounded-full border border-outline-variant/40 font-label-md text-label-md text-on-surface hover:bg-surface-container-highest transition-colors';
  annuler.textContent = 'Annuler';
  annuler.addEventListener('click', () => overlay.remove());
  const confirmer = document.createElement('button');
  confirmer.type = 'submit';
  confirmer.className = 'h-10 px-5 rounded-full bg-status-critical text-white font-label-md text-label-md font-semibold hover:opacity-90 transition-opacity';
  confirmer.textContent = 'Suspendre';
  actions.append(annuler, confirmer);
  form.appendChild(actions);

  const erreur = document.createElement('p');
  erreur.className = 'font-body-sm text-body-sm text-status-critical';
  form.appendChild(erreur);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    confirmer.disabled = true;
    try {
      await users.suspend(u.id, motif.value.trim());
      overlay.remove();
      charger();
    } catch (error) {
      erreur.textContent = error.message;
      confirmer.disabled = false;
    }
  });

  boite.appendChild(form);
}

async function init() {
  const shell = await mountAdminShell({
    active: 'admin-utilisateurs.html',
    title: 'Utilisateurs',
    subtitle: 'Consulter, filtrer et administrer les comptes',
  });
  if (!shell) return;
  content = shell.content;
  moiMeme = shell.user;

  rendreFiltres(content);
  zoneTable = card();
  content.appendChild(zoneTable);
  await charger();
}

init();
