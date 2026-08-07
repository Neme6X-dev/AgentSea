# Intégration des modifications — mock-verif

**2/5 scénarios réussis.**

| Scénario | État | Détail |
| --- | --- | --- |
| `retouche/ajout-section` | ❌ | instruction appliquée — aucune mention d'horaires |
| `cycle/preview` | ✅ | tous les contrôles passent |
| `refonte` | ⛔ | HTTP 500: Internal Server Error (la refonte avec design_spec n'est pas supportée) |
| `cycle/rollback` | ⛔ | HTTP 500: Internal Server Error (pas d'endpoint de publication par version) |
| `cycle/garde-fou` | ✅ | tous les contrôles passent |

## Détail des contrôles

### `retouche/ajout-section`

_Ajoute une section Horaires qui reprend les horaires d'ouverture du spec._

- ✅ **nouvelle version créée** — v1 → v2
- ❌ **instruction appliquée** — aucune mention d'horaires
- ✅ **sections conservées** — toutes présentes
- ✅ **structure conservée** — header/main/footer présents
- ✅ **fichiers liés conservés** — style.css et script.js référencés
- ✅ **pas de régression sécurité** — aucun nouveau finding critical/high

### `cycle/preview`

_Après une édition, le site en ligne reste inchangé jusqu'à publication explicite._

- ✅ **site publié au départ** — live servi
- ✅ **live inchangé après édition** — live préservé
- ✅ **preview de la nouvelle version servie** — HTTP 200

### `refonte`

_Refonte complète vers un style éditorial sombre (nouveau DesignSpec)._

- ⛔ HTTP 500: Internal Server Error (la refonte avec design_spec n'est pas supportée)

### `cycle/rollback`

_Republier la v1 après des versions plus récentes._

- ⛔ HTTP 500: Internal Server Error (pas d'endpoint de publication par version)

### `cycle/garde-fou`

_Une version au verdict `fail` n'est pas publiable sans force._

- ✅ **cas applicable** — verdict courant « pass » : garde-fou non sollicité sur ce run

