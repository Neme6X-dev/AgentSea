# Génération de code — baseline

6/10 runs aboutis · **6/6 conformes** à toutes les règles déterministes.

| Indicateur | Valeur |
| --- | --- |
| Taux de conformité | **100%** |
| Score reviewer moyen | 51/100 |
| Latence génération moyenne | 41.2 s |
| Latence review moyenne | 62.5 s |
| Taille HTML moyenne | 2.9 Ko |
| Sections du spec manquantes | 0 |
| Couleurs du spec absentes du CSS | 0 |
| **Contacts inventés** | **0** |
| Findings critical | 1 |
| Findings high | 2 |
| **Revues en échec** | **1/6** |

## Détail par run

| Spec | Run | Conforme | Manquements | Score | Verdict | HTML | Code (s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| restaurant | 1 | ✅ | — | 65 | warn | 3.0 Ko | 55.0 |
| avocat | 1 | ⛔ | `HTTPStatusError: Server error '500 Internal Server Error' for url 'http://127.0.0.1:8010/api/agents/code'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500` | — | — | — | — |
| freelance | 1 | ✅ | — | 0 | erreur | 2.6 Ko | 31.6 |
| association | 1 | ✅ | — | 94 | pass | 2.9 Ko | 43.0 |
| boutique | 1 | ✅ | — | 50 | fail | 2.9 Ko | 52.0 |
| restaurant | 2 | ✅ | — | 97 | pass | 2.7 Ko | 39.6 |
| avocat | 2 | ✅ | — | 0 | fail | 3.5 Ko | 25.9 |
| freelance | 2 | ⛔ | `HTTPStatusError: Server error '500 Internal Server Error' for url 'http://127.0.0.1:8010/api/agents/code'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500` | — | — | — | — |
| association | 2 | ⛔ | `HTTPStatusError: Server error '500 Internal Server Error' for url 'http://127.0.0.1:8010/api/agents/code'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500` | — | — | — | — |
| boutique | 2 | ⛔ | `HTTPStatusError: Server error '500 Internal Server Error' for url 'http://127.0.0.1:8010/api/agents/code'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/500` | — | — | — | — |
