/**
 * Vue d'ensemble du back-office.
 *
 * L'écran répond à quatre questions, dans cet ordre — c'est celui dans lequel un
 * dirigeant les pose :
 *
 * 1. **Est-ce que ça marche ?** Indicateurs de tête avec leur variation. Un nombre
 *    seul ne dit rien ; c'est l'écart avec la période précédente qui déclenche une
 *    décision.
 * 2. **Est-ce que ça croît ?** Inscriptions, sites créés et sites publiés sur une même
 *    échelle. Trois séries comparables, un seul axe — jamais deux échelles superposées.
 * 3. **Où ça coince ?** L'entonnoir d'activation. Une chute entre « créé » et
 *    « généré » est un problème technique ; entre « généré » et « publié », un
 *    problème de qualité perçue. Deux causes, deux corrections différentes.
 * 4. **Où sont les clients ?** Ventilation par pays et par offre.
 */
import { analytics } from '../lib/admin-api.js';
import {
  card, dataTable, errorBanner, mountAdminShell, setRefreshing, skeleton, splitGrid, tileGrid,
} from '../lib/admin-shell.js';
import {
  badge, compact, donutChart, emptyState, funnelChart, groupThousands, lineChart, statTile,
} from '../lib/charts.js';

let content = null;
let premierRendu = true;

async function charger(days) {
  const cible = content;
  if (premierRendu) skeleton(cible, 6);
  else setRefreshing(cible, true);

  try {
    const data = await analytics.overview(days);
    // Les trois courbes de croissance sont demandées à part : elles partagent les
    // mêmes dates et se superposent donc légitimement sur un axe unique.
    const croissance = await analytics.multiSeries(['signups', 'sites', 'publishes'], days, granularite(days));
    rendre(cible, data, croissance, days);
    premierRendu = false;
  } catch (error) {
    errorBanner(cible, error, () => charger(days));
  } finally {
    setRefreshing(cible, false);
  }
}

/** Au-delà de 90 jours, le point journalier devient illisible : on agrège. */
function granularite(days) {
  if (days > 180) return 'month';
  if (days > 60) return 'week';
  return 'day';
}

function rendre(host, data, croissance, days) {
  host.innerHTML = '';
  const k = data.kpis;

  /* --- Indicateurs de tête ------------------------------------------------- */
  const tuiles = tileGrid();
  tuiles.append(
    statTile({
      label: 'Comptes', value: groupThousands(k.users_total), icon: 'group',
      delta: k.users_new_change, deltaLabel: `· ${groupThousands(k.users_new)} nouveaux`,
      hint: `${groupThousands(k.users_active_7d)} actifs cette semaine`,
    }),
    statTile({
      label: 'Sites créés', value: groupThousands(k.sites_total), icon: 'language',
      delta: k.sites_new_change, deltaLabel: `· ${groupThousands(k.sites_new)} sur la période`,
      hint: `${groupThousands(k.sites_published)} publiés (${k.publish_rate} %)`,
    }),
    statTile({
      label: 'Revenu mensuel récurrent', value: k.mrr_formatted, icon: 'payments',
      hint: `${groupThousands(k.paying_customers)} clients payants · ${k.conversion_rate} % de conversion`,
    }),
    statTile({
      label: 'Coût des modèles', value: k.llm_cost_formatted, icon: 'smart_toy',
      // La baisse est ici une bonne nouvelle : la lecture de la couleur s'inverse.
      goodDown: true,
      hint: k.cost_per_site_xof ? `≈ ${compact(k.cost_per_site_xof)} FCFA par site généré` : 'Aucun site sur la période',
    }),
  );
  host.appendChild(tuiles);

  /* --- Santé d'exploitation ------------------------------------------------ */
  const sante = card({ className: 'flex flex-wrap items-center gap-lg' });
  sante.append(
    metrique('Taux de réussite des travaux', `${k.job_success_rate} %`, k.jobs_failed ? `${k.jobs_failed} en échec` : 'aucun échec'),
    metrique("File d'attente", groupThousands(data.queue?.queued ?? 0), `${data.queue?.running ?? 0} en cours · ${data.queue?.active_workers ?? 0} worker(s)`),
    metrique('Latence moyenne des modèles', `${groupThousands(k.llm_avg_latency_ms)} ms`, `${k.llm_error_rate} % d'erreurs`),
    metrique('Contacts depuis les sites', groupThousands(k.whatsapp_clicks + k.call_clicks), `${groupThousands(k.site_views)} pages vues`),
  );
  host.appendChild(sante);

  /* --- Croissance ---------------------------------------------------------- */
  const croissanceCard = card();
  if (croissance.dates?.length) {
    lineChart(croissanceCard, {
      title: 'Croissance',
      subtitle: `Inscriptions, sites créés et sites publiés — ${days} derniers jours`,
      labels: croissance.dates,
      series: [
        { label: 'Inscriptions', values: croissance.series.signups || [] },
        { label: 'Sites créés', values: croissance.series.sites || [] },
        { label: 'Sites publiés', values: croissance.series.publishes || [] },
      ],
      format: groupThousands,
    });
  } else {
    emptyState(croissanceCard);
  }
  host.appendChild(croissanceCard);

  /* --- Entonnoir et offres ------------------------------------------------- */
  const duo = splitGrid();

  const entonnoir = card();
  if (data.funnel?.length) {
    funnelChart(entonnoir, {
      title: "Parcours d'activation",
      subtitle: `Comptes inscrits sur les ${days} derniers jours et leur progression`,
      steps: data.funnel,
    });
  } else {
    emptyState(entonnoir, 'Aucune inscription sur cette période.');
  }

  const offres = card();
  const plansAvecComptes = (data.plans || []).filter((p) => p.users > 0);
  if (plansAvecComptes.length) {
    donutChart(offres, {
      title: 'Répartition des offres',
      subtitle: 'Comptes par formule souscrite',
      items: plansAvecComptes.map((p) => ({ label: p.name, value: p.users })),
      format: groupThousands,
      centerLabel: { value: groupThousands(k.users_total), label: 'comptes' },
    });
  } else {
    emptyState(offres, 'Aucun compte enregistré.');
  }

  duo.append(entonnoir, offres);
  host.appendChild(duo);

  /* --- Géographie et activité ---------------------------------------------- */
  const duo2 = splitGrid();

  const geo = card();
  const titreGeo = document.createElement('h3');
  titreGeo.className = 'font-headline-md text-headline-md text-on-surface';
  titreGeo.textContent = 'Marchés';
  const sousTitreGeo = document.createElement('p');
  sousTitreGeo.className = 'font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5 mb-sm';
  sousTitreGeo.textContent = 'Comptes, sites et revenu par pays';
  geo.append(titreGeo, sousTitreGeo);
  geo.appendChild(
    dataTable(
      ['Pays', 'Comptes', 'Sites', 'MRR'],
      (data.geography || []).map((g) => [
        `${g.flag} ${g.name}`,
        groupThousands(g.users),
        groupThousands(g.sites),
        g.mrr_formatted,
      ]),
      { empty: 'Aucune activité géolocalisée.' },
    ),
  );

  const activite = card();
  const titreAct = document.createElement('h3');
  titreAct.className = 'font-headline-md text-headline-md text-on-surface mb-sm';
  titreAct.textContent = 'Activité récente';
  activite.appendChild(titreAct);
  activite.appendChild(
    dataTable(
      ['Événement', 'Compte', 'Quand'],
      (data.recent || []).map((e) => [
        e.label,
        e.user_email || '—',
        instantRelatif(e.ts),
      ]),
      { empty: 'Rien à signaler pour le moment.' },
    ),
  );

  duo2.append(geo, activite);
  host.appendChild(duo2);

  /* --- État du pipeline ---------------------------------------------------- */
  if (data.statuses?.length) {
    const pipeline = card({ className: 'flex flex-wrap items-center gap-md' });
    const titre = document.createElement('h3');
    titre.className = 'font-headline-md text-headline-md text-on-surface w-full';
    titre.textContent = 'État des sites';
    pipeline.appendChild(titre);
    for (const s of data.statuses) {
      const bloc = document.createElement('div');
      bloc.className = 'flex items-center gap-2';
      bloc.appendChild(badge(`${s.label} · ${groupThousands(s.count)}`, tonalite(s.status)));
      pipeline.appendChild(bloc);
    }
    host.appendChild(pipeline);
  }
}

function metrique(label, valeur, detail) {
  const bloc = document.createElement('div');
  bloc.className = 'flex flex-col gap-0.5 min-w-[160px]';
  bloc.innerHTML = `
    <span class="font-label-md text-label-md text-on-surface-variant">${label}</span>
    <span class="font-headline-md text-headline-md text-on-surface tabular-nums">${valeur}</span>
    <span class="font-body-sm text-body-sm text-on-surface-variant/60">${detail}</span>`;
  return bloc;
}

function tonalite(status) {
  return { deployed: 'good', ready: 'neutral', running: 'neutral', pending: 'neutral', error: 'critical', failed: 'critical' }[status] || 'neutral';
}

/** Horodatage relatif : « il y a 3 h » se lit plus vite qu'une date complète. */
export function instantRelatif(iso) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso || '—';
  const secondes = Math.round((Date.now() - d.getTime()) / 1000);
  if (secondes < 60) return "à l'instant";
  if (secondes < 3600) return `il y a ${Math.round(secondes / 60)} min`;
  if (secondes < 86400) return `il y a ${Math.round(secondes / 3600)} h`;
  if (secondes < 604800) return `il y a ${Math.round(secondes / 86400)} j`;
  return d.toLocaleDateString('fr-FR', { day: 'numeric', month: 'short', year: 'numeric' });
}

async function init() {
  const shell = await mountAdminShell({
    active: 'admin.html',
    title: "Vue d'ensemble",
    subtitle: "L'état de la plateforme en un écran",
    period: true,
    onPeriodChange: charger,
  });
  if (!shell) return;
  content = shell.content;
  await charger(Number(localStorage.getItem('jarvisAdminPeriod')) || 30);
}

init();
