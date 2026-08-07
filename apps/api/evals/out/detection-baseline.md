# Détection des vulnérabilités — baseline

Corpus : **16 cas**, dont 8 sans erreur.

| Métrique | Valeur |
| --- | --- |
| Rappel | **0.45** |
| Précision | **0.71** |
| F1 | **0.56** |
| Vrais positifs | 5 |
| Faux négatifs (vulnérabilités ratées) | 6 |
| Faux positifs (pièges déclenchés) | 2 |
| Règles hors annotation (extras) | 0 |

## Détail par cas

| Cas | État | Ratés | Faux positifs | Extras |
| --- | --- | --- | --- | --- |
| `clean-baseline` | ✅ | — | — | — |
| `trap-eval-word-in-text` | ✅ | — | — | — |
| `trap-inline-svg-data-uri` | ✅ | — | — | — |
| `trap-javascript-word-in-text` | ❌ | — | html.javascript_url | — |
| `trap-onclick-property-assignment` | ❌ | — | html.inline_event_handler | — |
| `vuln-html-cdn-script` | ✅ | — | — | — |
| `vuln-html-data-html-uri` | ❌ | html.data_html_uri | — | — |
| `vuln-html-form-external-action` | ❌ | html.form_external_action | — | — |
| `vuln-html-iframe-external` | ❌ | html.iframe_external | — | — |
| `vuln-html-inline-onclick` | ❌ | html.inline_event_handler | — | — |
| `vuln-html-javascript-url` | ✅ | — | — | — |
| `vuln-html-target-blank` | ❌ | html.target_blank_no_noopener | — | — |
| `vuln-js-eval-external` | ✅ | — | — | — |
| `vuln-js-eval-inline` | ❌ | js.eval | — | — |
| `vuln-js-innerhtml` | ✅ | — | — | — |
| `vuln-secret-google-key` | ✅ | — | — | — |

## Cas en échec

### `trap-javascript-word-in-text`

La chaîne « javascript: » apparaît dans un paragraphe affiché.

- **Faux positif** : html.javascript_url

### `trap-onclick-property-assignment`

Affectation légitime d'une fonction à .onclick en JS (pas un handler inline).

- **Faux positif** : html.inline_event_handler

### `vuln-html-data-html-uri`

Lien vers une URI data:text/html (contourne l'origine).

- **Non détecté** : html.data_html_uri

### `vuln-html-form-external-action`

Formulaire postant vers un domaine tiers en http://.

- **Non détecté** : html.form_external_action

### `vuln-html-iframe-external`

iframe pointant vers un domaine externe non maîtrisé.

- **Non détecté** : html.iframe_external

### `vuln-html-inline-onclick`

Handler onclick inline dans le HTML (surface XSS).

- **Non détecté** : html.inline_event_handler

### `vuln-html-target-blank`

Lien target="_blank" sans rel="noopener" (tabnabbing).

- **Non détecté** : html.target_blank_no_noopener

### `vuln-js-eval-inline`

eval() dans un <script> inline du HTML (pas de script.js).

- **Non détecté** : js.eval

