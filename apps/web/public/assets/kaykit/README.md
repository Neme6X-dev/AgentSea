# Assets 3D — KayKit (CC0)

Personnages et mobilier de la scène 3D des agents.

| Dossier | Pack | Auteur | Licence |
|---|---|---|---|
| `characters/` | KayKit — Character Pack : Adventurers 1.0 | Kay Lousberg ([kaylousberg.com](https://kaylousberg.com)) | CC0 1.0 |
| `furniture/` | KayKit — Furniture Bits 1.0 | Kay Lousberg | CC0 1.0 |

**CC0 1.0 Universal** : domaine public. Usage **commercial autorisé**, modification
autorisée, **aucune attribution obligatoire**. Les textes de licence d'origine sont
conservés dans `LICENSE-characters.txt` et `LICENSE-furniture.txt`.

## Pourquoi ces assets

Ils remplacent « The Delegation » d'Arturo Paracuellos (unboring.net), qui était sous
**CC BY-NC 4.0**. La clause **NC** interdit tout usage commercial : ces modèles ne
pouvaient pas rester dans un produit destiné à être vendu. Ils ont été supprimés du
dépôt, ils ne sont pas simplement remplacés dans le code.

## Contenu réellement utilisé

- `characters/Rogue.glb` — seul personnage embarqué, cloné six fois et teinté par agent.
  Les quatre autres personnages du pack (Knight, Mage, Barbarian, Rogue_Hooded) ont été
  retirés : ils pèsent ~15 Mo pour rien, et leur silhouette (armure, chapeau de sorcier,
  tête d'ours) jure dans un bureau. Les armes et la cape du Rogue sont masquées à
  l'exécution (`HIDDEN_PARTS` dans `agents-scene.js`) : il ne reste qu'une silhouette
  neutre.
- `furniture/` — le pack complet est conservé : il ne pèse qu'1 Mo, et seules les pièces
  citées dans `office-kit.js` sont réellement chargées par le navigateur.

Le bureau lui-même (sol, cloisons) n'est pas un modèle importé : il est assemblé par
code dans `src/scene/office-kit.js`, à partir de géométrie primitive et de ces pièces.
