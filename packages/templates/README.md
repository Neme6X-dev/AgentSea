# Guide de Construction et Spécification des Templates Web (`templates/`)

Ce document définit les normes, la structure et les règles à respecter pour la création et le maintien du répertoire de templates de sites web dans le projet (`./templates/`).

---

## 1. Arborescence du Dossier `templates/`

Le dossier `templates/` contient à la fois les définitions des métadonnées sous forme de fichiers JSON à la racine de `templates/` et les fichiers sources HTML/CSS/JS correspondants dans le sous-dossier `templates/html/`.

### Exemple de Structure

```text
templates/
├── restaurant-moderne-01.json
├── restaurant-chaleureux-02.json
├── boutique-minimaliste-01.json
├── boutique-colore-02.json
├── portfolio-creatif-01.json
├── portfolio-epure-02.json
├── cabinet-corporate-01.json
├── cabinet-professionnel-02.json
├── evenementiel-dynamique-01.json
├── evenementiel-elegant-02.json
└── html/
    ├── restaurant-moderne-01/
    │   ├── index.html
    │   ├── about.html
    │   ├── menu.html
    │   ├── contact.html
    │   ├── css/
    │   │   └── style.css
    │   ├── js/
    │   │   └── main.js
    │   └── assets/
    │       ├── images/
    │       └── fonts/
    ├── restaurant-chaleureux-02/
    │   └── ... (même structure)
    ├── boutique-minimaliste-01/
    │   └── ... (même structure)
    └── ... (un dossier par id, même structure interne)
```

---

## 2. Règles Fondamentales

1. **Correspondance stricte de l'Identifiant (`id`)** :
   - Le nom du dossier situé dans `templates/html/<id>/` doit être **exactement identique** au champ `"id"` défini dans le fichier JSON correspondant (`templates/<id>.json`).
2. **Autonomie et Isolation de chaque Template** :
   - Chaque template conserve son propre sous-dossier `css/`, `js/` et `assets/`.
   - **Aucune mutualisation** ni partage de fichiers statiques n'est autorisé entre templates.
3. **Emplacement des Fichiers JSON** :
   - Les fichiers JSON doivent être placés à plat directement sous `templates/` (aucun sous-dossier pour les fichiers JSON).
4. **Noms Fixes pour les Pages HTML** :
   - Les fichiers HTML réels conservent des noms standardisés (ex: `index.html`, `about.html`, `menu.html`, `contact.html`, etc.), même si leur contenu spécifique diffère selon le template.

---

## 3. Spécification des Fichiers JSON de Métadonnées

Chaque fichier JSON doit strictement respecter la structure et la typologie des champs décrites ci-dessous.

### Exemple de Fichier JSON (`templates/restaurant-moderne-01.json`)

```json
{
  "id": "restaurant-moderne-01",
  "secteur": "restauration",
  "style": "moderne",
  "nb_pages": 4,
  "pages": ["accueil", "a-propos", "menu", "contact"],
  "description": "Mise en page une page (single-page), grandes photos plein écran, menu interactif avec filtres, bouton de réservation flottant, ambiance chaleureuse et conviviale.",
  "composants": ["hero-fullscreen", "galerie-photos", "menu-filtrable", "formulaire-reservation", "footer-contact"],
  "animations": ["fade-in au scroll", "parallax hero"],
  "responsive": true,
  "dependances": [],
  "licence": "MIT",
  "source": "startbootstrap.com",
  "html_path": "/templates/html/restaurant-moderne-01/"
}
```

### Rôle et Définition de chaque Champ

| Champ | Type | Description / Rôle Système |
| :--- | :--- | :--- |
| `id` | `string` | **Identifiant unique**. Doit obligatoirement concorder avec le nom du dossier dans `html/`. |
| `secteur` | `string` | Utilisé pour le filtrage par domaine d'activité (Étape 1 de la sélection/filtrage). |
| `style` | `string` | Filtre secondaire de design (ex: `moderne`, `minimaliste`, `chaleureux`, `épuré`, `dynamique`...). |
| `nb_pages` | `number` | Nombre total de pages fournies dans le template. Permet à l'agent de vérifier la compatibilité. |
| `pages` | `array[string]` | Liste des pages/vues incluses (ex: `["accueil", "a-propos", "menu", "contact"]`). |
| `description` | `string` | **Champ critique**. Indexé pour la recherche vectorielle (RAG). Doit décrire précisément les visuels, l'ambiance et la mise en page. |
| `composants` | `array[string]` | Liste des éléments d'interface (UI) réutilisables ou assemblables par l'agent de structure. |
| `animations` | `array[string]` | Indique les effets visuels et animations intégrés (ex: `fade-in au scroll`, `parallax hero`). |
| `responsive` | `boolean` | Booléen indiquant l'adaptation mobile / tablette. |
| `dependances` | `array[string]` | Bibliothèques et scripts JS/CSS externes nécessaires (ex: `["bootstrap@5.3", "aos@2.3"]`). |
| `licence` | `string` | Licence du template (ex: `MIT`, `CC-BY-4.0`). Traçabilité légale. |
| `source` | `string` | Provenance ou créateur d'origine du template (ex: `startbootstrap.com`). |
| `html_path` | `string` | Pointeur absolu ou relatif vers le dossier des sources réelles (`/templates/html/<id>/`). |

---

## 4. Procédure de Création d'un Nouveau Template

Lors de l'ajout d'un template au répertoire :
1. Définir un identifiant unique sous la forme `<secteur>-<style>-<numéro>` (ex: `portfolio-creatif-01`).
2. Créer le fichier de métadonnées `templates/<id>.json`.
3. Créer le dossier source `templates/html/<id>/`.
4. Placer dans ce dossier les pages HTML réelles ainsi que les dossiers isolés `css/`, `js/` et `assets/`.
5. Valider que `html_path` pointe bien vers `/templates/html/<id>/`.
