# Intégration des modifications — baseline

**1/6 scénarios réussis.**

| Scénario | État | Détail |
| --- | --- | --- |
| `retouche/ajout-section` | ⛔ | HTTP 500: Internal Server Error |
| `retouche/changement-cta` | ✅ | tous les contrôles passent |
| `cycle/preview` | ❌ | live inchangé après édition — le live a été écrasé sans publication explicite |
| `refonte` | ⛔ | HTTP 500: Internal Server Error (la refonte avec design_spec n'est pas supportée) |
| `cycle/rollback` | ⛔ | HTTP 404: {"detail":"Not Found"} (pas d'endpoint de publication par version) |
| `cycle/garde-fou` | ❌ | publication refusée sans force — HTTP 404; publication forcée acceptée — HTTP 404 |

## Détail des contrôles

### `retouche/ajout-section`

_Ajoute une section Horaires qui reprend les horaires d'ouverture du spec._

- ⛔ HTTP 500: Internal Server Error

### `retouche/changement-cta`

_Change le libellé du bouton principal en « Réserver maintenant »._

- ✅ **nouvelle version créée** — v2 → v3
- ✅ **instruction appliquée** — nouveau libellé présent
- ✅ **sections conservées** — toutes présentes
- ✅ **structure conservée** — header/main/footer présents
- ✅ **fichiers liés conservés** — style.css et script.js référencés
- ✅ **pas de régression sécurité** — aucun nouveau finding critical/high

### `cycle/preview`

_Après une édition, le site en ligne reste inchangé jusqu'à publication explicite._

- ✅ **site publié au départ** — live servi
- ❌ **live inchangé après édition** — le live a été écrasé sans publication explicite
- ✅ **preview de la nouvelle version servie** — HTTP 200

### `refonte`

_Refonte complète vers un style éditorial sombre (nouveau DesignSpec)._

- ⛔ HTTP 500: Internal Server Error (la refonte avec design_spec n'est pas supportée)

### `cycle/rollback`

_Republier la v1 après des versions plus récentes._

- ⛔ HTTP 404: {"detail":"Not Found"} (pas d'endpoint de publication par version)

### `cycle/garde-fou`

_Une version au verdict `fail` n'est pas publiable sans force._

- ❌ **publication refusée sans force** — HTTP 404
- ❌ **publication forcée acceptée** — HTTP 404

