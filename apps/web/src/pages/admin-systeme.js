/**
 * Exploitation : santé, file de travaux, interrupteurs, configuration.
 *
 * C'est l'écran qu'on ouvre quand quelque chose ne va pas. Il est donc conçu pour
 * répondre vite à « d'où vient le problème », dans cet ordre : état global, puis file
 * de travaux (le point de blocage le plus fréquent), puis anomalies de configuration.
 *
 * Les avertissements de configuration viennent des mêmes contrôles qu'au démarrage du
 * serveur. Les afficher ici permet de constater qu'un réglage a dérivé — un CORS
 * rouvert à tous, un mode simulation resté actif — sans avoir à ouvrir les journaux
 * d'un VPS auquel on n'a pas forcément accès depuis un téléphone.
 */
import { flags as flagsApi, jobs as jobsApi, system as systemApi, config as configApi } from '../lib/admin-api.js';
import {
  card, dataTable, errorBanner, mountAdminShell, pager, setRefreshing, skeleton, tileGrid,
} from '../lib/admin-shell.js';
import { badge, groupThousands, statTile } from '../lib/charts.js';
import { instantRelatif } from './admin.js';

let content = null;
let moiMeme = null;
let zoneSante = null;
let zoneFile = null;
let zoneFlags = null;
let zoneConfig = null;
let premierRendu = true;
const filtresJobs = { page: 1, size: 25, status: '' };

function peutEcrire() {
  return ['admin', 'owner'].includes(moiMeme?.role);
}

async function charger() {
  if (premierRendu) skeleton(zoneSante, 4);
  else setRefreshing(zoneSante, true);

  try {
    const [sante, travaux] = await Promise.all([systemApi(), jobsApi.list(filtresJobs)]);
    rendreSante(sante);
    rendreFile(travaux);
    premierRendu = false;
  } catch (error) {
    errorBanner(zoneSante, error, charger);
  } finally {
    setRefreshing(zoneSante, false);
  }
}

function rendreSante(s) {
  zoneSante.innerHTML = '';

  const etats = {
    ok: ['Tout va bien', 'good', 'check_circle'],
    degraded: ['Fonctionnement dégradé', 'warning', 'warning'],
    down: ['Service indisponible', 'critical', 'error'],
  };
  const [libelle, tone, icone] = etats[s.status] || etats.degraded;

  const bandeau = card({ className: 'flex flex-wrap items-center gap-md' });
  const gauche = document.createElement('div');
  gauche.className = 'flex items-center gap-sm flex-1 min-w-[240px]';
  gauche.innerHTML = `<span class="material-symbols-outlined text-2xl text-status-${tone === 'good' ? 'good' : tone === 'warning' ? 'warning' : 'critical'}">${icone}</span>`;
  const texte = document.createElement('div');
  texte.innerHTML = `
    <p class="font-headline-md text-headline-md text-on-surface">${libelle}</p>
    <p class="font-body-sm text-body-sm text-on-surface-variant/70">
      Environnement ${s.environment} · mode travaux « ${s.job_mode} »
    </p>`;
  gauche.appendChild(texte);
  bandeau.appendChild(gauche);

  const integrations = document.createElement('div');
  integrations.className = 'flex flex-wrap items-center gap-2';
  for (const [label, actif] of [
    ['Base de données', s.database],
    ['Modèles IA', s.llm_configured],
    ['Paiements', s.payments_configured],
    ['Publication VPS', s.vps_configured],
  ]) {
    integrations.appendChild(badge(`${label} · ${actif ? 'configuré' : 'absent'}`, actif ? 'good' : 'neutral'));
  }
  bandeau.appendChild(integrations);
  zoneSante.appendChild(bandeau);

  /* --- File de travaux : les chiffres qui expliquent une attente ------------ */
  const q = s.queue || {};
  const tuiles = tileGrid();
  tuiles.append(
    statTile({ label: "En file d'attente", value: groupThousands(q.queued || 0), icon: 'pending' }),
    statTile({
      label: 'En cours', value: groupThousands(q.running || 0), icon: 'sync',
      hint: `${q.active_workers || 0} worker(s) actif(s)`,
    }),
    statTile({
      label: 'Attente la plus ancienne', value: dureeLisible(q.oldest_wait_s || 0), icon: 'hourglass_top',
      goodDown: true,
    }),
    statTile({
      label: 'Travaux en échec', value: groupThousands(q.failed || 0), icon: 'error', goodDown: true,
      hint: `durée moyenne ${dureeLisible(Math.round((q.avg_duration_ms || 0) / 1000))}`,
    }),
  );
  zoneSante.appendChild(tuiles);

  /* --- Anomalies de configuration ------------------------------------------ */
  if (s.warnings?.length) {
    const alertes = card();
    const titre = document.createElement('h3');
    titre.className = 'font-headline-md text-headline-md text-on-surface mb-sm';
    titre.textContent = `Configuration — ${s.warnings.length} point(s) d'attention`;
    alertes.appendChild(titre);

    const liste = document.createElement('ul');
    liste.className = 'flex flex-col gap-2';
    for (const avertissement of s.warnings) {
      const critique = avertissement.startsWith('CRITIQUE');
      const li = document.createElement('li');
      li.className = `flex items-start gap-2 p-2.5 rounded-lg ${critique ? 'bg-status-critical/10' : 'bg-surface-container-high/40'}`;
      li.innerHTML =
        `<span class="material-symbols-outlined text-base shrink-0 ${critique ? 'text-status-critical' : 'text-status-warning'}">${critique ? 'error' : 'warning'}</span>` +
        `<span class="font-body-md text-body-md text-on-surface">${avertissement.replace(/^CRITIQUE\s*:\s*/, '')}</span>`;
      liste.appendChild(li);
    }
    alertes.appendChild(liste);
    zoneSante.appendChild(alertes);
  }
}

function dureeLisible(secondes) {
  if (!secondes) return '—';
  if (secondes < 60) return `${secondes} s`;
  if (secondes < 3600) return `${Math.round(secondes / 60)} min`;
  return `${(secondes / 3600).toFixed(1).replace('.', ',')} h`;
}

function rendreFile(page) {
  zoneFile.innerHTML = '';

  const entete = document.createElement('div');
  entete.className = 'flex flex-wrap items-center justify-between gap-md mb-sm';
  const titre = document.createElement('div');
  titre.innerHTML = `
    <h3 class="font-headline-md text-headline-md text-on-surface">File de travaux</h3>
    <p class="font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5">
      Générations, éditions et publications confiées aux workers
    </p>`;
  entete.appendChild(titre);

  const commandes = document.createElement('div');
  commandes.className = 'flex items-center gap-sm';

  const filtre = document.createElement('select');
  filtre.className =
    'h-9 px-3 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 font-body-md text-body-md text-on-surface focus:ring-0';
  for (const [v, l] of [['', 'Tous les états'], ['queued', 'En attente'], ['running', 'En cours'], ['failed', 'En échec'], ['done', 'Terminés']]) {
    const opt = document.createElement('option');
    opt.value = v; opt.textContent = l;
    if (v === filtresJobs.status) opt.selected = true;
    filtre.appendChild(opt);
  }
  filtre.addEventListener('change', () => { filtresJobs.status = filtre.value; filtresJobs.page = 1; charger(); });
  commandes.appendChild(filtre);

  if (peutEcrire()) {
    const reprendre = document.createElement('button');
    reprendre.type = 'button';
    reprendre.className =
      'h-9 px-4 rounded-full border border-outline-variant/40 font-label-md text-label-md text-on-surface hover:bg-surface-container-highest transition-colors';
    reprendre.textContent = 'Reprendre les orphelins';
    reprendre.title = "Remet en file les travaux dont le worker a disparu";
    reprendre.addEventListener('click', async () => {
      reprendre.disabled = true;
      try {
        const r = await jobsApi.reclaim();
        reprendre.textContent = `${r.reclaimed} repris`;
        setTimeout(() => { reprendre.textContent = 'Reprendre les orphelins'; reprendre.disabled = false; }, 2000);
        charger();
      } catch {
        reprendre.disabled = false;
      }
    });
    commandes.appendChild(reprendre);
  }

  entete.appendChild(commandes);
  zoneFile.appendChild(entete);

  zoneFile.appendChild(
    dataTable(
      ['Travail', 'État', 'Tentatives', 'Durée', 'Erreur', 'Créé', ''],
      page.items.map((j) => [
        celluleTravail(j),
        badge(libelleEtatJob(j.status), toneJob(j.status)),
        `${j.attempts}/${j.max_attempts}`,
        j.duration_ms ? dureeLisible(Math.round(j.duration_ms / 1000)) : '—',
        celluleErreur(j.error),
        instantRelatif(j.created_at),
        actionsJob(j),
      ]),
      { empty: 'Aucun travail dans la file.' },
    ),
  );
  zoneFile.appendChild(pager(page, (p) => { filtresJobs.page = p; charger(); }));
}

function celluleTravail(j) {
  const box = document.createElement('div');
  box.className = 'flex flex-col leading-tight min-w-[180px]';
  const kind = document.createElement('span');
  kind.className = 'text-on-surface';
  kind.textContent = libelleKind(j.kind);
  const ref = document.createElement('span');
  ref.className = 'font-body-sm text-body-sm text-on-surface-variant/60 font-code text-code';
  ref.textContent = j.session_id || j.id;
  box.append(kind, ref);
  return box;
}

function celluleErreur(erreur) {
  if (!erreur) {
    const rien = document.createElement('span');
    rien.className = 'text-on-surface-variant/40';
    rien.textContent = '—';
    return rien;
  }
  const span = document.createElement('span');
  span.className = 'font-body-sm text-body-sm text-on-surface-variant block max-w-[280px] truncate';
  span.textContent = erreur;
  // Le message complet reste accessible au survol et au clavier : tronquer sans
  // recours cacherait justement l'information qu'on est venu chercher.
  span.title = erreur;
  return span;
}

function actionsJob(j) {
  const box = document.createElement('div');
  box.className = 'flex justify-end';
  if (!peutEcrire() || j.status === 'queued' || j.status === 'running') return box;

  const relancer = document.createElement('button');
  relancer.type = 'button';
  relancer.title = 'Relancer ce travail';
  relancer.setAttribute('aria-label', 'Relancer ce travail');
  relancer.className =
    'w-9 h-9 grid place-items-center rounded-full text-on-surface-variant hover:text-on-surface hover:bg-surface-container-highest transition-colors';
  relancer.innerHTML = '<span class="material-symbols-outlined text-base">restart_alt</span>';
  relancer.addEventListener('click', async () => {
    relancer.disabled = true;
    try { await jobsApi.retry(j.id); charger(); } catch { relancer.disabled = false; }
  });
  box.appendChild(relancer);
  return box;
}

function libelleKind(kind) {
  return {
    'site.generate': 'Génération', 'site.edit': 'Modification',
    'site.publish': 'Publication', 'site.review': 'Revue',
  }[kind] || kind;
}

function libelleEtatJob(status) {
  return { queued: 'En attente', running: 'En cours', done: 'Terminé', failed: 'En échec' }[status] || status;
}

function toneJob(status) {
  return { done: 'good', running: 'neutral', queued: 'neutral', failed: 'critical' }[status] || 'neutral';
}

/* --------------------------------------------------------------------------- */
/* Interrupteurs de fonctionnalité                                             */
/* --------------------------------------------------------------------------- */

async function chargerFlags() {
  try {
    const liste = await flagsApi.list();
    zoneFlags.innerHTML = '';

    const titre = document.createElement('div');
    titre.innerHTML = `
      <h3 class="font-headline-md text-headline-md text-on-surface">Interrupteurs</h3>
      <p class="font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5 mb-sm">
        Ouvrir un pays, activer un modèle ou couper une intégration défaillante — sans redéployer
      </p>`;
    zoneFlags.appendChild(titre);

    if (!liste.length) {
      const vide = document.createElement('p');
      vide.className = 'font-body-md text-body-md text-on-surface-variant/60 py-md';
      vide.textContent = 'Aucun interrupteur défini.';
      zoneFlags.appendChild(vide);
    } else {
      const grille = document.createElement('div');
      grille.className = 'flex flex-col gap-2';
      for (const f of liste) grille.appendChild(ligneFlag(f));
      zoneFlags.appendChild(grille);
    }

    if (peutEcrire()) zoneFlags.appendChild(formulaireFlag());
  } catch (error) {
    errorBanner(zoneFlags, error, chargerFlags);
  }
}

function ligneFlag(f) {
  const ligne = document.createElement('div');
  ligne.className = 'flex flex-wrap items-center gap-sm p-3 rounded-lg bg-surface-container-high/40';

  const infos = document.createElement('div');
  infos.className = 'flex-1 min-w-[200px]';
  infos.innerHTML = `
    <p class="font-body-md text-body-md text-on-surface font-code text-code">${f.key}</p>
    ${f.description ? `<p class="font-body-sm text-body-sm text-on-surface-variant/70">${f.description}</p>` : ''}`;
  ligne.appendChild(infos);

  ligne.appendChild(badge(
    f.enabled ? (f.rollout_percent < 100 ? `Actif · ${f.rollout_percent} %` : 'Actif') : 'Inactif',
    f.enabled ? 'good' : 'neutral',
  ));

  if (peutEcrire()) {
    const bascule = document.createElement('button');
    bascule.type = 'button';
    bascule.className =
      'h-9 px-4 rounded-full border border-outline-variant/40 font-label-md text-label-md text-on-surface hover:bg-surface-container-highest transition-colors';
    bascule.textContent = f.enabled ? 'Désactiver' : 'Activer';
    bascule.addEventListener('click', async () => {
      bascule.disabled = true;
      try {
        await flagsApi.set(f.key, { enabled: !f.enabled, rollout_percent: f.rollout_percent, description: f.description });
        chargerFlags();
      } catch { bascule.disabled = false; }
    });
    ligne.appendChild(bascule);
  }
  return ligne;
}

function formulaireFlag() {
  const form = document.createElement('form');
  form.className = 'flex flex-wrap items-end gap-sm pt-md mt-sm border-t border-outline-variant/20';

  const cle = document.createElement('input');
  cle.required = true;
  cle.placeholder = 'nom_de_l_interrupteur';
  cle.className =
    'h-10 px-3 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 font-body-md text-body-md text-on-surface focus:ring-0 flex-1 min-w-[200px]';

  const desc = document.createElement('input');
  desc.placeholder = 'À quoi il sert';
  desc.className =
    'h-10 px-3 rounded-lg bg-surface-container-high/60 border border-outline-variant/30 font-body-md text-body-md text-on-surface focus:ring-0 flex-1 min-w-[200px]';

  const creer = document.createElement('button');
  creer.type = 'submit';
  creer.className =
    'h-10 px-5 rounded-full bg-on-surface text-background font-label-md text-label-md font-semibold hover:bg-surface-variant hover:text-on-surface transition-colors';
  creer.textContent = 'Créer';

  form.append(cle, desc, creer);
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    creer.disabled = true;
    try {
      await flagsApi.set(cle.value.trim(), { enabled: false, rollout_percent: 100, description: desc.value.trim() || null });
      cle.value = ''; desc.value = '';
      chargerFlags();
    } finally {
      creer.disabled = false;
    }
  });
  return form;
}

/* --------------------------------------------------------------------------- */
/* Configuration effective                                                     */
/* --------------------------------------------------------------------------- */

async function chargerConfig() {
  if (!peutEcrire()) return;
  try {
    const c = await configApi();
    zoneConfig.innerHTML = '';

    const titre = document.createElement('div');
    titre.innerHTML = `
      <h3 class="font-headline-md text-headline-md text-on-surface">Configuration effective</h3>
      <p class="font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5 mb-sm">
        Aucun secret n'est exposé : seule la présence d'une clé est indiquée, jamais sa valeur
      </p>`;
    zoneConfig.appendChild(titre);

    zoneConfig.appendChild(
      dataTable(
        ['Réglage', 'Valeur'],
        [
          ['Environnement', c.environment],
          ['Mode des travaux', `${c.job_mode} (concurrence ${c.job_concurrency})`],
          ['Pays par défaut', c.default_country],
          ['Devise par défaut', c.default_currency],
          ['Pays ouverts', `${c.enabled_countries.length} pays`],
          ['URL publique', c.public_base_url],
          ['Origines CORS', c.cors_origins.join(', ')],
          ['Modèle codeur', c.models.coder],
          ['Modèle revue', c.models.reviewer],
          ['Clés IA configurées', String(c.models.keys_configured)],
          ['Mode simulation IA', c.models.mock ? 'ACTIF — les sites générés sont factices' : 'inactif'],
          ['Coût jeton entrée', `${c.llm_pricing_xof_per_mtok.input} FCFA / M jetons`],
          ['Coût jeton sortie', `${c.llm_pricing_xof_per_mtok.output} FCFA / M jetons`],
          ['Agrégateur de paiement', c.integrations.payment_provider || 'aucun'],
        ],
      ),
    );
  } catch (error) {
    errorBanner(zoneConfig, error, chargerConfig);
  }
}

async function init() {
  const shell = await mountAdminShell({
    active: 'admin-systeme.html',
    title: 'Système',
    subtitle: "L'état d'exploitation de la plateforme",
  });
  if (!shell) return;
  moiMeme = shell.user;
  content = shell.content;

  zoneSante = document.createElement('div');
  zoneSante.className = 'flex flex-col gap-lg';
  zoneFile = card();
  zoneFlags = card();
  zoneConfig = card();
  content.append(zoneSante, zoneFile, zoneFlags, zoneConfig);

  await Promise.all([charger(), chargerFlags(), chargerConfig()]);
}

init();
