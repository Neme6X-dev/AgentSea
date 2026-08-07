/**
 * Analytics approfondi.
 *
 * La vue d'ensemble répond à « comment ça va » ; cet écran répond à « pourquoi ».
 * Il porte les analyses qui demandent qu'on s'y arrête : rétention par cohorte,
 * fréquentation réelle des sites publiés, secteurs d'activité des clients.
 *
 * Le trafic des sites mérite une explication. Pour un commerçant, la métrique qui
 * compte n'est pas la page vue mais le **contact** : un clic sur WhatsApp ou sur
 * « appeler ». C'est la seule qui prouve que son site lui rapporte quelque chose, et
 * c'est donc elle qu'on met en avant — la page vue n'est que le dénominateur.
 */
import { analytics } from '../lib/admin-api.js';
import {
  card, dataTable, errorBanner, mountAdminShell, setRefreshing, skeleton, splitGrid, tileGrid,
} from '../lib/admin-shell.js';
import {
  barChart, compact, donutChart, emptyState, groupThousands, lineChart, statTile,
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
  if (premierRendu) skeleton(cible, 8);
  else setRefreshing(cible, true);

  try {
    // Chargement en parallèle : ces six requêtes sont indépendantes, les enchaîner
    // multiplierait par six la latence perçue sur une connexion à forte latence.
    const [trafic, cohortes, secteurs, revenus, couts, topComptes] = await Promise.all([
      analytics.traffic(days),
      analytics.cohorts(Math.max(3, Math.min(24, Math.ceil(days / 30) + 3))),
      analytics.businessTypes(days),
      analytics.series('revenue', days, granularite(days)),
      analytics.multiSeries(['llm_cost', 'llm_calls'], days, granularite(days)),
      analytics.topUsers(days),
    ]);
    rendre(cible, { trafic, cohortes, secteurs, revenus, couts, topComptes }, days);
    premierRendu = false;
  } catch (error) {
    errorBanner(cible, error, () => charger(days));
  } finally {
    setRefreshing(cible, false);
  }
}

function rendre(host, d, days) {
  host.innerHTML = '';

  /* --- Ce que rapportent les sites publiés --------------------------------- */
  const tuiles = tileGrid();
  tuiles.append(
    statTile({
      label: 'Pages vues', value: groupThousands(d.trafic.total_views), icon: 'visibility',
      trend: d.trafic.points.map((p) => p.views),
    }),
    statTile({
      label: 'Prises de contact', value: groupThousands(d.trafic.total_contacts), icon: 'forum',
      hint: `${d.trafic.contact_rate} % des visites aboutissent à un contact`,
      trend: d.trafic.points.map((p) => p.whatsapp + p.calls),
    }),
    statTile({
      label: 'Revenu encaissé', value: `${compact(d.revenus.total)} FCFA`, icon: 'savings',
      hint: `sur ${days} jours`,
    }),
    statTile({
      label: 'Appels aux modèles', value: groupThousands(d.couts.totals?.llm_calls || 0), icon: 'bolt',
      hint: `${compact(d.couts.totals?.llm_cost || 0)} FCFA de coût`,
    }),
  );
  host.appendChild(tuiles);

  /* --- Fréquentation des sites --------------------------------------------- */
  const traficCard = card();
  if (d.trafic.points?.length) {
    lineChart(traficCard, {
      title: 'Fréquentation des sites publiés',
      subtitle: 'Pages vues et prises de contact (WhatsApp + appels)',
      labels: d.trafic.points.map((p) => p.date),
      series: [
        { label: 'Pages vues', values: d.trafic.points.map((p) => p.views) },
        { label: 'Contacts', values: d.trafic.points.map((p) => p.whatsapp + p.calls) },
      ],
      format: groupThousands,
    });
  } else {
    emptyState(traficCard, "Aucune visite mesurée. La balise de mesure s'active à la publication d'un site.");
  }
  host.appendChild(traficCard);

  /* --- Coût des modèles ----------------------------------------------------- */
  const coutCard = card();
  if (d.couts.dates?.length) {
    // Deux mesures d'ordres très différents (des francs et un nombre d'appels) ne
    // partagent pas un axe : on ne trace ici que le coût, et le volume d'appels est
    // rappelé dans le sous-titre.
    lineChart(coutCard, {
      title: 'Coût des modèles',
      subtitle: `En FCFA · ${groupThousands(d.couts.totals?.llm_calls || 0)} appels sur la période`,
      labels: d.couts.dates,
      series: [{ label: 'Coût', values: d.couts.series.llm_cost || [] }],
      area: true,
      format: (v) => `${compact(v)} FCFA`,
    });
  } else {
    emptyState(coutCard);
  }
  host.appendChild(coutCard);

  /* --- Cohortes et secteurs ------------------------------------------------- */
  const duo = splitGrid();

  const cohortes = card();
  const titreCoh = document.createElement('h3');
  titreCoh.className = 'font-headline-md text-headline-md text-on-surface';
  titreCoh.textContent = 'Rétention par cohorte';
  const sousTitreCoh = document.createElement('p');
  sousTitreCoh.className = 'font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5 mb-sm';
  sousTitreCoh.textContent =
    "Mesurée sur l'activité réelle, pas sur l'abonnement : un compte qui paie sans revenir est un départ à venir.";
  cohortes.append(titreCoh, sousTitreCoh);
  cohortes.appendChild(
    dataTable(
      ["Mois d'inscription", 'Comptes', 'Actifs 30 j', 'Actifs 90 j'],
      (d.cohortes.cohorts || []).map((c) => [
        moisLisible(c.month),
        groupThousands(c.size),
        `${c.retention_30d} %`,
        `${c.retention_90d} %`,
      ]),
      { empty: 'Pas encore assez de recul pour une analyse de cohortes.' },
    ),
  );

  const secteurs = card();
  if (d.secteurs?.length) {
    donutChart(secteurs, {
      title: "Secteurs d'activité",
      subtitle: 'Ce que les clients construisent réellement',
      items: d.secteurs.map((s) => ({ label: libelleSecteur(s.type), value: s.count })),
      format: groupThousands,
    });
  } else {
    emptyState(secteurs, 'Aucun secteur renseigné sur cette période.');
  }

  duo.append(cohortes, secteurs);
  host.appendChild(duo);

  /* --- Sites les plus consultés et comptes les plus actifs ------------------ */
  const duo2 = splitGrid();

  const topSites = card();
  if (d.trafic.top_sites?.length) {
    barChart(topSites, {
      title: 'Sites les plus consultés',
      subtitle: 'Pages vues sur la période',
      items: d.trafic.top_sites.map((s) => ({
        label: s.slug,
        value: s.views,
        hint: s.whatsapp ? `${groupThousands(s.whatsapp)} contacts WhatsApp` : undefined,
      })),
      format: groupThousands,
    });
  } else {
    emptyState(topSites, 'Aucun site publié n\'a encore reçu de visite.');
  }

  const topComptes = card();
  const titreTop = document.createElement('h3');
  titreTop.className = 'font-headline-md text-headline-md text-on-surface';
  titreTop.textContent = 'Comptes les plus actifs';
  const sousTitreTop = document.createElement('p');
  sousTitreTop.className = 'font-body-sm text-body-sm text-on-surface-variant/70 mt-0.5 mb-sm';
  sousTitreTop.textContent = 'Les premiers à interroger avant toute décision produit';
  topComptes.append(titreTop, sousTitreTop);
  topComptes.appendChild(
    dataTable(
      ['Compte', 'Pays', 'Offre', 'Sites'],
      (d.topComptes || []).map((u) => [
        u.name || u.email,
        `${u.flag} ${u.country}`,
        u.plan,
        groupThousands(u.sites),
      ]),
      { empty: 'Aucune activité sur cette période.' },
    ),
  );

  duo2.append(topSites, topComptes);
  host.appendChild(duo2);
}

function moisLisible(iso) {
  const [annee, mois] = String(iso).split('-');
  const noms = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre'];
  const nom = noms[Number(mois) - 1];
  return nom ? `${nom} ${annee}` : iso;
}

function libelleSecteur(type) {
  const libelles = {
    restaurant: 'Restauration', boutique: 'Commerce', cabinet: 'Cabinet / conseil',
    artisan: 'Artisanat', sante: 'Santé', education: 'Éducation', immobilier: 'Immobilier',
    hotel: 'Hôtellerie', association: 'Association', autre: 'Autre',
  };
  return libelles[type] || type;
}

async function init() {
  const shell = await mountAdminShell({
    active: 'admin-analytics.html',
    title: 'Analytics',
    subtitle: 'Comprendre ce qui se passe, et pourquoi',
    period: true,
    onPeriodChange: charger,
  });
  if (!shell) return;
  content = shell.content;
  await charger(Number(localStorage.getItem('jarvisAdminPeriod')) || 30);
}

init();
