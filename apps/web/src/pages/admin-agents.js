/**
 * Agents IA : coût, performance, qualité produite.
 *
 * C'est l'écran qui répond à la question dont dépend toute la tarification :
 * **combien coûte un site généré, et est-il bon ?** Sans lui, le poste de dépense le
 * plus volatil de la plateforme reste invisible jusqu'à la facture du fournisseur, et
 * la qualité livrée ne se mesure que par les réclamations.
 *
 * Le score de revue et le coût sont volontairement présentés côte à côte : un modèle
 * moins cher qui produit des sites au verdict « à corriger » coûte en réalité plus,
 * parce qu'il faut regénérer.
 */
import { analytics } from '../lib/admin-api.js';
import {
  card, dataTable, errorBanner, mountAdminShell, setRefreshing, skeleton, splitGrid, tileGrid,
} from '../lib/admin-shell.js';
import {
  badge, barChart, compact, donutChart, emptyState, groupThousands, lineChart, statTile, ORDINAL,
} from '../lib/charts.js';

let content = null;
let premierRendu = true;

function granularite(days) {
  if (days > 180) return 'month';
  if (days > 60) return 'week';
  return 'day';
}

async function charger(days) {
  const cible = content;
  if (premierRendu) skeleton(cible, 7);
  else setRefreshing(cible, true);

  try {
    const [agents, qualite, series] = await Promise.all([
      analytics.agents(days),
      analytics.quality(days),
      analytics.multiSeries(['llm_calls', 'llm_cost'], days, granularite(days)),
    ]);
    rendre(cible, { agents, qualite, series }, days);
    premierRendu = false;
  } catch (error) {
    errorBanner(cible, error, () => charger(days));
  } finally {
    setRefreshing(cible, false);
  }
}

function rendre(host, d, days) {
  host.innerHTML = '';

  const totalAppels = d.agents.reduce((s, a) => s + a.calls, 0);
  const totalCout = d.agents.reduce((s, a) => s + a.cost_xof, 0);
  const totalErreurs = d.agents.reduce((s, a) => s + a.errors, 0);
  const latenceMoyenne = totalAppels
    ? Math.round(d.agents.reduce((s, a) => s + a.avg_latency_ms * a.calls, 0) / totalAppels)
    : 0;

  /* --- Indicateurs --------------------------------------------------------- */
  const tuiles = tileGrid();
  tuiles.append(
    statTile({
      label: 'Appels aux modèles', value: groupThousands(totalAppels), icon: 'bolt',
      trend: d.series.series?.llm_calls,
    }),
    statTile({
      label: 'Coût total', value: `${compact(totalCout)} FCFA`, icon: 'payments', goodDown: true,
      hint: totalAppels ? `≈ ${(totalCout / totalAppels).toFixed(1).replace('.', ',')} FCFA par appel` : '',
    }),
    statTile({
      label: 'Latence moyenne', value: `${groupThousands(latenceMoyenne)} ms`, icon: 'timer', goodDown: true,
    }),
    statTile({
      label: "Taux d'erreur", value: `${totalAppels ? ((totalErreurs / totalAppels) * 100).toFixed(1).replace('.', ',') : 0} %`,
      icon: 'error', goodDown: true,
      hint: `${groupThousands(totalErreurs)} appel(s) en échec`,
    }),
  );
  host.appendChild(tuiles);

  /* --- Volume et coût dans le temps ---------------------------------------- */
  const evolution = card();
  if (d.series.dates?.length) {
    // Une seule série par graphique : appels et francs n'ont pas le même ordre de
    // grandeur, les superposer inventerait une corrélation qui n'existe pas.
    lineChart(evolution, {
      title: 'Volume d\'appels',
      subtitle: `Sur ${days} jours · coût cumulé ${compact(d.series.totals?.llm_cost || 0)} FCFA`,
      labels: d.series.dates,
      series: [{ label: 'Appels', values: d.series.series.llm_calls || [] }],
      area: true,
      format: groupThousands,
    });
  } else {
    emptyState(evolution, 'Aucun appel aux modèles sur cette période.');
  }
  host.appendChild(evolution);

  /* --- Détail par agent ----------------------------------------------------- */
  const detail = card();
  const titre = document.createElement('h3');
  titre.className = 'font-headline-md text-headline-md text-on-surface';
  titre.textContent = 'Performance par agent';
  const sousTitre = document.createElement('p');
  sousTitre.className = 'font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5 mb-sm';
  sousTitre.textContent = 'Chaque couple agent / modèle, avec son coût réel et sa fiabilité';
  detail.append(titre, sousTitre);
  detail.appendChild(
    dataTable(
      ['Agent', 'Modèle', 'Appels', 'Latence moy.', 'Latence max.', 'Erreurs', 'Coût', 'Coût / appel'],
      d.agents.map((a) => [
        libelleAgent(a.agent),
        a.model,
        groupThousands(a.calls),
        `${groupThousands(a.avg_latency_ms)} ms`,
        `${groupThousands(a.max_latency_ms)} ms`,
        badge(`${a.error_rate} %`, a.error_rate > 5 ? 'critical' : a.error_rate > 1 ? 'warning' : 'good'),
        a.cost_formatted,
        `${a.cost_per_call_xof.toFixed(1).replace('.', ',')} FCFA`,
      ]),
      { empty: 'Aucun appel enregistré. La mesure démarre à la première génération.' },
    ),
  );
  host.appendChild(detail);

  /* --- Qualité produite ----------------------------------------------------- */
  const duo = splitGrid();

  const scores = card();
  if (d.qualite.reports) {
    // Les tranches de score sont **ordonnées** : elles prennent la rampe à une seule
    // teinte, pas des couleurs catégorielles. L'ordre doit se voir dans la couleur.
    barChart(scores, {
      title: 'Distribution des scores de revue',
      subtitle: `${groupThousands(d.qualite.reports)} rapports · moyenne ${String(d.qualite.average_score).replace('.', ',')}/100`,
      items: d.qualite.distribution.map((b, i) => ({
        label: b.range,
        value: b.count,
        color: ORDINAL[Math.min(d.qualite.distribution.length - 1 - i, ORDINAL.length - 1)],
      })),
      format: groupThousands,
    });
  } else {
    emptyState(scores, 'Aucun rapport de revue sur cette période.');
  }

  const findings = card();
  const parGravite = (d.qualite.findings_by_severity || []).filter((f) => f.count > 0);
  if (parGravite.length) {
    donutChart(findings, {
      title: 'Problèmes détectés par gravité',
      subtitle: 'Cumul des findings de sécurité, qualité et accessibilité',
      items: parGravite.map((f) => ({
        label: libelleGravite(f.severity),
        value: f.count,
        color: couleurGravite(f.severity),
      })),
      format: groupThousands,
    });
  } else {
    emptyState(findings, 'Aucun problème relevé sur cette période.');
  }

  duo.append(scores, findings);
  host.appendChild(duo);

  /* --- Verdicts ------------------------------------------------------------- */
  const verdicts = (d.qualite.verdicts || []).filter((v) => v.count > 0);
  if (verdicts.length) {
    const bande = card({ className: 'flex flex-wrap items-center gap-md' });
    const t = document.createElement('h3');
    t.className = 'font-headline-md text-headline-md text-on-surface w-full';
    t.textContent = 'Verdicts de publication';
    bande.appendChild(t);
    for (const v of verdicts) {
      bande.appendChild(badge(`${libelleVerdict(v.verdict)} · ${groupThousands(v.count)}`, toneVerdict(v.verdict)));
    }
    host.appendChild(bande);
  }
}

function libelleAgent(agent) {
  return { coder: 'Codeur', reviewer: 'Revue sécurité', designer: 'Designer', inconnu: 'Non attribué' }[agent] || agent;
}

function libelleGravite(s) {
  return { critical: 'Critique', high: 'Élevée', medium: 'Moyenne', low: 'Faible', info: 'Information' }[s] || s;
}

function couleurGravite(s) {
  return {
    critical: 'var(--status-critical, #d03b3b)',
    high: 'var(--status-serious, #ec835a)',
    medium: 'var(--status-warning, #fab219)',
    low: 'var(--chart-1, #3987e5)',
    info: 'var(--chart-3, #199e70)',
  }[s];
}

function libelleVerdict(v) {
  return { pass: 'Conforme', warn: 'À surveiller', fail: 'À corriger' }[v] || v;
}

function toneVerdict(v) {
  return { pass: 'good', warn: 'warning', fail: 'critical' }[v] || 'neutral';
}

async function init() {
  const shell = await mountAdminShell({
    active: 'admin-agents.html',
    title: 'Agents IA',
    subtitle: 'Ce que coûtent les modèles, et ce qu\'ils produisent',
    period: true,
    onPeriodChange: charger,
  });
  if (!shell) return;
  content = shell.content;
  await charger(Number(localStorage.getItem('jarvisAdminPeriod')) || 30);
}

init();
