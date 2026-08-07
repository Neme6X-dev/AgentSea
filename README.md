# Jarvis — Plateforme de création de sites web pour l'Afrique

Un commerçant décrit son activité en une phrase ; des agents IA produisent, relisent et
publient un site vitrine complet, avec bouton WhatsApp, prix en devise locale et moyens
de paiement mobile money du pays.

Ce dépôt contient toute la plateforme : l'API, l'interface, le back-office, le
catalogue de gabarits et l'infrastructure de déploiement.

---

## Ce qui rend cette plateforme différente

Elle n'est pas « traduite en français » : elle est **conçue pour ses marchés**.

| Choix | Pourquoi |
|---|---|
| Le franc CFA s'écrit sans décimales | « 15 000,00 FCFA » n'existe pas. Un formatage générique ajoute deux zéros qui font amateur. |
| WhatsApp avant l'e-mail | C'est le premier canal de contact. Un site vitrine sans bouton WhatsApp perd la majorité de ses prises de contact. |
| Mobile money avant la carte bancaire | La pénétration du mobile money dépasse largement celle de la carte. Un parcours de paiement qui ouvre sur « Payer par carte » perd la plupart des acheteurs au premier écran. |
| Budget de poids de page < 150 Ko | Une part importante du trafic arrive en 3G, sur des forfaits facturés au mégaoctet. Chaque kilo-octet est payé par le visiteur. |
| Adresse au point de repère | L'adressage formel est minoritaire en Afrique de l'Ouest. « En face de la pharmacie Sainte-Rita » localise mieux qu'un numéro de rue. |
| Tarifs indexés sur le pouvoir d'achat local | Le même plan ne coûte pas la même chose à Niamey et à Johannesburg. Facturer partout le prix sud-africain fermerait le marché principal. |
| Repos hebdomadaire par pays | Le Maghreb travaille le dimanche. « Fermé le week-end » sur un site marocain est faux. |

Trente pays sont décrits dans un registre unique (`apps/api/app/africa/countries.py`) :
indicatif, devise, fuseau, langues, opérateurs mobile money, TVA, jours ouvrés.
**Ouvrir un pays = ajouter une entrée à ce fichier**, et nulle part ailleurs.

---

## Structure

```
apps/
  api/                 API FastAPI — agents, file de travaux, facturation, back-office
    app/
      africa/          Registre des pays, devises, téléphonie, paiement, conventions
      agents/          Designer, codeur, revue sécurité, validation déterministe
      analytics/       Collecte d'événements (events) et agrégations (queries)
      billing/         Catalogue d'offres, tarification régionale, quotas
      core/            Journalisation corrélée, middlewares HTTP, pagination
      jobs/            File durable PostgreSQL, handlers, worker
      routers/         auth, account, sessions, dev, agents, admin, public
      devsecops/       Analyse statique des sites générés
  web/                 Interface Vite multipage (produit + back-office)
    src/lib/           api, admin-api, charts, admin-shell, auth
    src/pages/         Un module par écran
packages/
  templates/           Catalogue de gabarits, partagé entre l'API et le front
  brand/               Palettes, règles SEO, logo source
infra/
  kvm1/                Docker Compose, Caddy, script de déploiement
  ci/                  Intégration DefectDojo
docs/                  Architecture, catalogue de conception, règles internes
```

Le catalogue de gabarits vit dans `packages/` et non dans l'un des deux applicatifs :
il sert de repère de structure au codeur **et** alimente la galerie de démarrage côté
interface. Le dupliquer l'aurait fait diverger dès la première retouche.

---

## Démarrage

### Prérequis

- Python 3.12+, Node 20+, PostgreSQL 14+

### API

```bash
cd apps/api
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # renseigner JWT_SECRET, DATABASE_URL, ADMIN_EMAILS
.venv/bin/alembic upgrade head
.venv/bin/python -m uvicorn app.main:app --reload
```

Documentation interactive : <http://localhost:8000/docs>

### Worker

En production, les générations passent par la file (`JOB_MODE=queue`) et un worker les
exécute :

```bash
cd apps/api && .venv/bin/python -m app.jobs.worker
```

Plusieurs workers peuvent tourner sur des machines différentes : la réservation par
`SELECT … FOR UPDATE SKIP LOCKED` garantit qu'un travail n'est jamais pris deux fois.
**Monter en charge se fait en lançant des workers**, sans rien reconfigurer.

En développement, `JOB_MODE=inline` exécute le travail dans le processus web et évite
d'avoir à lancer un second terminal.

### Interface

```bash
cd apps/web
npm install
cp .env.example .env
npm run dev                   # http://localhost:5173
```

Le proxy de Vite transmet `/api` et `/sites` vers l'API : aucun préflight CORS en
développement, et les aperçus de sites restent sur la même origine que l'éditeur.

### Back-office

Accessible à `/admin.html` pour les comptes de rôle `support`, `admin` ou `owner`.
Sur une base neuve, personne n'a ces rôles : renseignez `ADMIN_EMAILS` dans `.env`
**avant** de créer votre compte.

---

## Architecture

### La file de travaux

Une génération dure 60 à 180 secondes. Le prototype la lançait dans une tâche asyncio
du processus web, ce qui posait trois problèmes dès le deuxième utilisateur :

1. La tâche occupait la boucle d'événements ; quelques générations simultanées
   ralentissaient toutes les autres requêtes, y compris le suivi d'avancement.
2. Un redémarrage — déploiement, `OOMKilled`, coupure — perdait la tâche en vol. La
   session restait « en cours » indéfiniment, sans erreur nulle part.
3. Impossible d'ajouter un second serveur.

La file vit dans PostgreSQL plutôt que dans Redis : une dépendance d'infrastructure de
moins à héberger et sauvegarder, sur des VPS où chaque service compte. Un travail
survit au processus, et un worker qui redémarre reprend ce que le précédent a laissé
en plan.

### Les rôles

| Rôle | Peut |
|---|---|
| `user` | Utiliser la plateforme |
| `support` | **Lire** tout le back-office |
| `admin` | Écrire : changer une offre, suspendre un compte, relancer un travail |
| `owner` | Idem, non rétrogradable par un `admin` |

Le support consulte le compte d'un client pour l'aider ; il ne le modifie pas. Sans
cette séparation, « accès au back-office » finit par signifier « peut tout faire ».

Les routes d'administration répondent **404** à un compte sans rôle, jamais 403 : un
403 confirmerait leur existence et inviterait à chercher une élévation de privilège.

### L'audit

Toute écriture depuis le back-office est consignée **avant** d'être appliquée. Une
trace impossible à écrire empêche l'action — on ne suspend pas le compte d'un client
sans laisser de trace de qui l'a fait. Le journal conserve l'e-mail de l'acteur en
plus de son identifiant : supprimer un compte n'efface pas ce qu'il a fait.

### La mesure

Chaque site publié embarque `jarvis-metrics.js`, injecté par la plateforme et non
demandé au modèle — un modèle omet ou déforme régulièrement ce genre de bloc, et une
mesure absente sur un site sur cinq rend toutes les statistiques inexploitables.

Le fichier envoie trois champs : le site, le type d'événement, un drapeau « première
visite du jour ». **Aucune IP n'est stockée en clair**, seulement un condensat salé et
tronqué qui distingue deux visiteurs sans permettre d'en identifier un.

L'indicateur qui compte n'est pas la page vue mais le **contact** : un clic sur
WhatsApp ou sur « appeler ». C'est la seule métrique qui prouve à un commerçant que
son site lui rapporte quelque chose.

### Les graphiques

`apps/web/src/lib/charts.js` est écrit sans dépendance : ~9 Ko compressés contre
~200 Ko pour Chart.js. Sur une connexion à 500 ko/s, c'est la différence entre un
tableau de bord qui s'affiche et un tableau de bord qu'on attend.

La palette a été validée sur la surface sombre du dashboard : bande de clarté, plancher
de chroma, séparation sous protanopie et deutéranopie, contraste. **Elle ne se retouche
pas à l'œil** — deux teintes qui « se distinguent bien » à l'écran peuvent être
identiques pour 8 % des hommes. Chaque graphique produit aussi une table équivalente :
aucune valeur n'est accessible par la seule infobulle.

---

## Tarification

⚠️ **La grille est un point de départ, pas une décision arrêtée.** Elle existe pour que
la plateforme sache compter, facturer et appliquer des quotas dès aujourd'hui. Les
montants se changent dans `apps/api/app/billing/plans.py`, en un seul endroit.

| Offre | Prix (Bénin) | Pour qui |
|---|---|---|
| Découverte | Gratuit | Particuliers, essai |
| Essentiel | 3 500 FCFA/mois | Artisans, commerçants |
| Pro | 9 500 FCFA/mois | PME, professions libérales |
| Business | 25 000 FCFA/mois | Groupes, franchises, ONG |
| Agence | 75 000 FCFA/mois | Revendeurs (marque blanche) |

Les prix sont **libellés en FCFA, pas convertis depuis l'euro** : afficher « 5,99 € (≈
3 930 FCFA) » signale à un client de Cotonou qu'il paie le tarif d'un autre marché. Un
coefficient par pays (`PRICE_TIERS`) ajuste ensuite sur le pouvoir d'achat local.

Le palier gratuit publie de vrais sites : un essai qui ne met rien en ligne ne démontre
rien. La limite porte sur le volume et la marque, pas sur la mise en ligne.

---

## Tests

```bash
make db-dev     # PostgreSQL local sur 55432, avec la base de test
make test       # suite de l'API (225 tests) puis construction du front
```

`make db-dev` écoute sur **55432** et non 5432 : une machine de développement fait
presque toujours tourner un autre PostgreSQL sur le port standard, et une suite de
tests qui se connecte silencieusement à la base d'un autre projet est pire qu'une
suite qui refuse de démarrer.

La suite exige un PostgreSQL réel — le schéma utilise des types et des verrous
(`SKIP LOCKED`) que SQLite ne reproduit pas, et une base de test qui ment sur le
comportement de la production ne teste rien.

```bash
cd apps/web && npm run build      # vérifie que les 15 pages se construisent
```

---

## Points d'attention en production

`settings.validate()` contrôle la configuration au démarrage et **refuse de démarrer**
si une anomalie critique est détectée en production. Ces défauts ne cassent rien
immédiatement : ils produisent une plateforme qui semble fonctionner tout en étant
vulnérable, ou qui livre des sites factices.

- `JWT_SECRET` d'au moins 32 caractères (`openssl rand -hex 32`)
- `CORS_ORIGINS` listant les origines réelles, jamais `*`
- `PUBLIC_BASE_URL` en HTTPS
- `GEMINI_MOCK=false`
- `JOB_MODE=queue` et au moins un worker en service
- `ADMIN_EMAILS` renseigné avant la première inscription

L'écran **Système** du back-office rejoue ces mêmes contrôles : une configuration qui
dérive se constate sans ouvrir les journaux du serveur.

---

## Déploiement

La cible est un VPS 4 Go (Wayhost KVM1). Tout est décrit dans `infra/kvm1/`.

### La pile

| Service | Rôle | Enveloppe |
|---|---|---|
| `edge` | Caddy : TLS, en-têtes de sécurité, sert `/sites/*` en statique | 64 Mo |
| `web` | Front Vite construit, servi par nginx | 64 Mo |
| `app` | API FastAPI | 1 Go |
| `worker` | Dépile la table `jobs` et exécute les générations | 1 Go |
| `db` | PostgreSQL 16 | 512 Mo |

`app` et `worker` partagent **la même image** et les **mêmes volumes** (`data/`,
`sites/`) : le worker écrit les fichiers des sites, l'edge et l'API les servent. Des
montages divergents publieraient des sites que personne ne sert.

### Mettre en ligne

```bash
# Sur le VPS, depuis /opt/app (compose + .env + Caddyfile)
cp infra/kvm1/.env.example .env      # puis renseigner les valeurs CRITIQUE
APP_TAG=$(git rev-parse --short HEAD) ./deploy.sh
```

`deploy.sh` construit l'image depuis la **racine du monorepo** (`SRC_DIR`) et non depuis
`apps/api/` : l'image embarque `packages/templates/catalog`, qui vit en dehors du
dossier de l'API. Le script refuse de construire si ce catalogue manque — sans lui la
plateforme démarre, passe son healthcheck et génère des sites, mais le codeur travaille
sans repère de structure et rien ne le signale.

Le script vérifie ensuite deux choses : que `app` répond à `/healthz`, et que `worker`
tourne. Le second contrôle compte autant que le premier : en `JOB_MODE=queue` sans
worker, l'API accepte les demandes, les empile et reste verte pendant que les sessions
des clients restent « en cours » indéfiniment.

### Ce qui n'est pas encore en place

| Sujet | État |
|---|---|
| **Intégration continue** | `apps/api/.gitlab-ci.yml` décrit une chaîne DevSecOps complète (secrets, SAST, SCA, conteneur, DAST, DefectDojo), mais elle a été écrite quand l'API était un dépôt autonome : elle référence `Dockerfile` et `deploy/kvm1/` à la racine, qui sont aujourd'hui `apps/api/Dockerfile` et `infra/kvm1/`. Le dépôt est par ailleurs hébergé sur GitHub, où ce fichier n'est pas lu. **Le déploiement est donc manuel** (`deploy.sh`) tant que la chaîne n'est pas reportée. |
| **TLS** | `Caddyfile` (ACME) est prêt ; tant qu'il n'y a pas de domaine, utiliser `Caddyfile.http-dev` et `DOMAIN=:80`. `PUBLIC_BASE_URL` doit passer en HTTPS avant la mise en production, sinon `settings.validate()` refuse le démarrage. |
| **Image du front** | `FRONTEND_IMAGE` pointe encore vers un registre ITNET. En mode `local`, `deploy.sh` ne construit que l'API : l'image du front doit être poussée, ou construite à la main (`docker build apps/web`). |
| **Sauvegardes** | Aucun `pg_dump` planifié, et `sites/` n'est pas sauvegardé. Ce sont les fichiers des clients. |
| **Supervision** | Journaux en JSON et bornés (10 Mo × 3), mais aucun agrégateur ni alerte : une file qui s'allonge ne se voit qu'en regardant. |

---

## Documentation

| Fichier | Contenu |
|---|---|
| `docs/ARCHITECTURE.md` | Décisions structurantes et leurs raisons — **à lire en premier** |
| `docs/architecture-legacy.md` | Architecture d'origine du backend |
| `docs/design-catalog/` | Catalogue de conception, ADR, diagrammes |
| `docs/coding-rules.md` | Règles de code |
| `docs/security-policy.md` | Politique de sécurité applicative |
| `apps/api/docs/API.md` | Contrat détaillé de l'API |
| `packages/templates/README.md` | Comment ajouter un gabarit |
