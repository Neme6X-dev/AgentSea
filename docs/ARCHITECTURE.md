# Architecture

Ce document explique les décisions structurantes — celles qui coûteraient cher à
revenir dessus — et surtout **pourquoi** elles ont été prises. Le détail de chaque
module vit dans son propre en-tête ; on ne le recopie pas ici, il divergerait.

---

## Vue d'ensemble

```
Navigateur (produit)          Navigateur (back-office)        Sites publiés
      │                                │                            │
      │ /api/auth /api/sessions        │ /api/admin/*               │ /api/public/beacon
      │ /api/dev  /api/account         │                            │
      ▼                                ▼                            ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                          API FastAPI (apps/api)                          │
│                                                                          │
│  middlewares  →  corrélation · en-têtes de sécurité · débit public       │
│  routers      →  auth, account, sessions, dev, agents, admin, public     │
│  services     →  pipeline code → revue → publication                     │
│  billing      →  offres, tarification régionale, quotas                  │
│  africa       →  pays, devises, téléphonie, paiement, conventions        │
│  analytics    →  collecte (events) · agrégations (queries)               │
└───────────┬──────────────────────────────────────────┬───────────────────┘
            │ dépose                                   │ lit / écrit
            ▼                                          ▼
   ┌──────────────────┐                        ┌──────────────────┐
   │  Table `jobs`    │◀── réserve ───────────│    PostgreSQL     │
   │  (file durable)  │                        └──────────────────┘
   └────────┬─────────┘                                 ▲
            │ SKIP LOCKED                               │
            ▼                                           │
   ┌──────────────────┐    ┌──────────┐                 │
   │ worker(s)        │───▶│  Gemini  │                 │
   │ app.jobs.worker  │    └──────────┘                 │
   └────────┬─────────┘                                 │
            │ écrit les fichiers du site ───────────────┘
            ▼
   sites/<slug>/v{n}/ ── publication ──▶ sites/<slug>/live/ ──▶ (SFTP VPS)
```

---

## Décisions

### 1. Une file de travaux en base, pas des tâches asyncio

**Constat.** Le prototype lançait la génération dans `asyncio.create_task` depuis le
routeur. Une génération dure 60 à 180 secondes.

**Ce qui cassait.** Trois choses, toutes visibles dès le deuxième utilisateur :

- La tâche occupait la boucle d'événements du serveur web. Quelques générations
  simultanées ralentissaient toutes les autres requêtes — y compris le *polling* qui
  affiche l'avancement, donc l'utilisateur voyait sa barre se figer.
- Un redémarrage perdait la tâche en vol. La session restait « en cours » pour
  toujours, le front interrogeait dans le vide, et rien n'apparaissait dans les
  journaux : il n'y avait pas d'erreur, juste une tâche qui n'existait plus.
- Impossible d'ajouter un second serveur : les tâches ne sont pas partagées.

**Décision.** Une table `jobs` et un worker séparé, avec réservation par
`SELECT … FOR UPDATE SKIP LOCKED`.

**Pourquoi pas Redis ou Celery.** Une dépendance d'infrastructure de plus à héberger,
superviser et sauvegarder, sur des VPS où chaque service compte. PostgreSQL est déjà
là et `SKIP LOCKED` fournit exactement la primitive : plusieurs workers piochent dans
la même table sans verrou global, et aucun travail n'est pris deux fois.

**Conséquences.**
- Monter en charge = lancer des workers. Aucune reconfiguration.
- Un worker tué laisse une ligne `running` ; `reclaim_stale()` la reprend au-delà de
  `JOB_LOCK_TIMEOUT_S`. Ce seuil doit rester **largement supérieur** à la plus longue
  génération, sinon on reprendrait un travail toujours en cours et le client recevrait
  deux sites.
- Les handlers laissent remonter leurs exceptions : c'est la file qui décide de
  réessayer. Les absorber, comme le faisait la version asyncio, rendait tout échec
  définitif.

Le jour où le volume justifie une vraie file, seul `app/jobs/queue.py` change.

---

### 2. Un registre régional unique

**Constat.** Les règles qui varient d'un pays à l'autre sont nombreuses : indicatif,
devise et ses décimales, opérateurs mobile money, jours ouvrés, TVA, conventions
d'adresse.

**Ce qui cassait.** Le garde-fou anti-invention de coordonnées ne reconnaissait que le
format français (`+33` ou `0` + neuf chiffres). Deux conséquences symétriques : un
numéro béninois inventé par le modèle passait sans être vu, et un numéro légitimement
fourni par le client était signalé comme inventé.

**Décision.** `app/africa/` porte tout : `countries`, `currencies`, `phone`,
`payments`, `locales`. Ouvrir un pays = ajouter une entrée à `COUNTRIES`.

**Pourquoi pas `phonenumbers` (libphonenumber).** Plusieurs mégaoctets pour une
couverture mondiale dont trente pays nous concernent, et des métadonnées qui suivent
mal les migrations de plan de numérotation ouest-africaines — le Bénin est passé à dix
chiffres en 2024 et les deux formats circulent encore. Notre registre se corrige en
une ligne.

**Conséquence pour les agents.** Le contexte régional est **calculé** et transmis au
codeur comme faisant autorité, plutôt que laissé à sa connaissance : un modèle à qui
l'on demande les opérateurs mobile money du Togo répond régulièrement « Orange Money »,
qui n'y opère pas.

---

### 3. Horodatages typés en base, chaînes ISO à l'API

Le premier schéma stockait les dates en `VARCHAR(32)`. Les agrégations du back-office
(« sites publiés par semaine », rétention par cohorte) auraient exigé de découper des
chaînes de caractères en SQL.

Le stockage utilise donc de vrais `timestamptz`, et la conversion en chaîne ISO se
fait à la frontière, dans `db._dict()`. Les modèles Pydantic et le front continuent de
voir `created_at: str` — le contrat public n'a pas bougé.

**La migration correspondante** ajoute `USING …::timestamptz` sur chaque conversion et
un `server_default` sur chaque colonne `NOT NULL` ajoutée. Sans ces deux précautions,
elle échoue sur une base contenant déjà des comptes — ce qui est le cas de toute base
de production. L'aller-retour `upgrade` / `downgrade` a été vérifié sur une base
peuplée.

---

### 4. Rôles séparés, écriture réservée

| Rôle | Portée |
|---|---|
| `user` | Le produit |
| `support` | Lecture du back-office |
| `admin` | Écriture : offre, suspension, relance, interrupteurs |
| `owner` | Idem, non rétrogradable par un `admin` |

La séparation lecture/écriture est le cœur du modèle. Sans elle, « accès au
back-office » finit toujours par signifier « peut tout faire », y compris pour
quelqu'un embauché pour répondre aux messages WhatsApp.

Le contrôle se fait par **comparaison de rang** (`ROLE_RANK`), jamais par égalité :
ajouter un rôle intermédiaire n'oblige pas à relire chaque condition.

Un compte sans rôle reçoit **404** sur `/api/admin/*`, pas 403 : un 403 confirmerait
l'existence de ces routes et inviterait à chercher une élévation de privilège.

Un administrateur ne peut ni se retirer ses droits ni se suspendre : ce sont les deux
gestes qui ferment la porte de l'intérieur.

---

### 5. L'audit précède l'action

`events.audit()` est appelé **avant** que la modification soit appliquée, et
contrairement à `events.track()` il **ne masque pas ses erreurs**. Une trace impossible
à écrire empêche l'action.

On ne suspend pas le compte d'un client sans laisser de trace de qui l'a fait — ni
pour le client, ni pour un régulateur, ni pour l'équipe six mois plus tard.

L'e-mail de l'acteur est conservé en plus de son identifiant : supprimer un compte
n'efface pas ce qu'il a fait.

---

### 6. Collecte tolérante, audit strict

Deux régimes d'erreur opposés, et c'est délibéré :

- **`events.track()`, `record_llm_call()`, `record_visit()` absorbent leurs
  exceptions.** Un graphique manquant est un désagrément ; une génération de site qui
  échoue parce que l'écriture d'un événement a échoué est une faute.
- **`events.audit()` les laisse remonter**, pour la raison ci-dessus.

Sur la vie privée : aucune IP n'est stockée en clair, seulement un condensat salé et
tronqué. Il distingue deux visiteurs sur une journée ; il ne permet pas de remonter à
une personne, et la rotation du sel le rend inexploitable au-delà.

---

### 7. La mesure est injectée, pas demandée au modèle

`jarvis-metrics.js` est écrit par `app/deploy.py` à chaque écriture de version. On ne
le demande pas à l'agent codeur : un modèle omet ou déforme régulièrement un bloc
technique de ce genre, et une mesure absente sur un site sur cinq rend toutes les
statistiques inexploitables.

**Fichier externe et non script inline.** La politique de sécurité appliquée aux sites
publiés interdit le script inline (`script-src 'self'`). L'assouplir pour cette balise
rouvrirait la voie à toute injection dans du HTML produit par un modèle — exactement ce
que cette politique protège.

`connect-src` inclut l'origine publique de l'API, sans quoi la mesure échouerait
silencieusement sur les sites servis depuis un domaine personnalisé : précisément ceux
qui comptent le plus.

---

### 8. Quotas au point d'entrée, décompte à l'engagement

La génération est joignable depuis `/api/dev/generate`, `/api/sessions/{id}/edit` et
les endpoints `/api/agents/*`. Un contrôle recopié trois fois diverge à la première
évolution : `app/billing/quotas.py` porte la règle, les routeurs l'appellent.

Les contrôles renvoient une `QuotaCheck` plutôt que de lever : l'appelant décide s'il
refuse ou avertit. Le refus est un **402 Payment Required**, pas un 403 — le compte a
le droit d'agir, c'est son forfait qui ne le couvre pas, et la nuance permet au front
d'ouvrir la page d'abonnement au lieu d'afficher « accès refusé ».

La vérification a lieu **avant** de créer la session : dépasser son forfait ne doit pas
laisser une session orpheline dans la liste des projets.

---

### 9. Graphiques sans dépendance

`apps/web/src/lib/charts.js` : ~9 Ko compressés contre ~200 Ko pour Chart.js. Le
back-office sera consulté depuis Cotonou ou Douala, souvent en 4G partagée.

La palette catégorielle a été **validée**, pas choisie : bande de clarté, plancher de
chroma, séparation sous protanopie et deutéranopie, lisibilité en vision normale,
contraste sur la surface sombre. Elle ne se retouche pas à l'œil — deux teintes qui
« se distinguent bien » à l'écran peuvent être identiques pour 8 % des hommes.

Règles appliquées partout : un seul axe des ordonnées (jamais deux échelles, qui
inventent une corrélation absente des données), la couleur suit l'entité et non son
rang, et chaque graphique produit une table équivalente — aucune valeur n'est
accessible par la seule infobulle.

---

### 10. Le catalogue de gabarits est partagé

`packages/templates/catalog/` sert de repère de structure à l'agent codeur **et**
alimente la galerie côté interface. Les deux copies d'origine (une par applicatif)
étaient identiques au démarrage ; elles auraient divergé à la première retouche.

`settings.templates_dir` conserve un repli sur un emplacement interne
(`apps/api/app/templates`). Ce repli n'est pas décoratif : c'est **là que l'image
Docker range le catalogue**, copié depuis `packages/` à la construction. L'image reste
ainsi autonome à l'exécution — elle n'exige pas que le monorepo soit présent sur le
serveur — au prix d'une contrainte : le contexte de construction est la racine du
monorepo, pas `apps/api/` (`docker build -f apps/api/Dockerfile .`).

Cette contrainte mérite d'être signalée parce que l'oublier ne casse rien de visible.
L'image se construit, démarre, passe son healthcheck et génère des sites ; simplement
`catalog()` renvoie un tuple vide et le codeur travaille sans repère de structure. Il
faut comparer la qualité des sites produits pour s'en apercevoir. `deploy.sh` vérifie
donc la présence du catalogue avant de construire, plutôt que de faire confiance à la
synchronisation des sources.

---

## Ce qui reste ouvert

| Sujet | État |
|---|---|
| Encaissement réel | Le registre des agrégateurs et le calcul de frais existent (`app/africa/payments.py`), l'intégration d'un PSP reste à faire. `PAYMENT_PROVIDER` est le point d'entrée. |
| Grille tarifaire | Fonctionnelle mais non arrêtée commercialement. Un seul fichier à modifier : `app/billing/plans.py`. |
| Multi-langue de l'interface | Le socle existe (`app/africa/locales.py`), les traductions ne sont pas faites. Les sites générés, eux, sont déjà multilingues. |
| Comptes d'équipe | `team_seats` est décompté dans les quotas ; le partage effectif d'un site entre plusieurs comptes reste à implémenter. |
| Domaines personnalisés | La colonne `custom_domain` existe sur les sessions ; la vérification DNS et l'émission de certificat restent à faire. |
