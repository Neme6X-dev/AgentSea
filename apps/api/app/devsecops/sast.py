"""SAST déterministe sur le site généré (complète la revue LLM).

C'est le contrôle de sécurité qui garde la **publication** d'un site client : son verdict
alimente `ReviewReport`, et `/api/sessions/{id}/publish` refuse une mise en ligne dont le
verdict est `fail`. Un site client ne part donc en production qu'après être passé ici.

Contrairement au reviewer LLM, cette analyse est reproductible : même entrée, même verdict.
C'est ce qui la rend mesurable (`evals/run_detection.py`, corpus annoté) et utilisable comme
garde anti-régression en intégration continue.

Chaque check produit un finding conforme à `ReviewFinding` (`app/contracts.py`) :

- `rule`  : identifiant stable, indépendant du libellé affiché (les titres évoluent) ;
- `line`  : ligne concernée, pour qu'un correctif puisse viser l'endroit exact ;
- `source`: toujours `sast`, ce qui permet au reviewer de ne dégrader le score que sur des
  faits déterministes.

Deux principes gouvernent les motifs ci-dessous :

1. **Analyser du code, jamais du texte affiché.** Un site vitrine parle souvent de sécurité
   (« les URL javascript: sont interdites ») : chercher un motif dangereux dans tout le
   document produit des faux positifs qui décrédibilisent le rapport, et poussent
   l'utilisateur à forcer la publication par réflexe. On ne scanne donc que le JS (fichier
   ou `<script>` inline) et les attributs de balises.
2. **Distinguer l'usage dangereux de l'usage légitime.** `el.onclick = maFonction` est
   correct ; `el.onclick = "alert(1)"` ne l'est pas. Les motifs visent le second.
"""
from __future__ import annotations

import re
from typing import Any

_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Au-delà, un même défaut répété noie le rapport (un site avec 40 <img> sans alt).
_MAX_PER_RULE = 3


def sast_scan(
    *,
    html: str,
    css: str,
    js: str,
    palette: tuple[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Analyse statique du HTML/CSS/JS généré. Retourne des findings triés par gravité.

    Args:
        html, css, js: contenus des trois fichiers du site.
        palette: couple (couleur de texte, couleur de fond) du DesignSpec, pour le contrôle
            de contraste. Omis, ce seul check est ignoré.
    """
    findings: list[dict[str, Any]] = []

    _scan_js(js, findings, file="script.js")
    _scan_inline_scripts(html, findings)
    _scan_html(html, findings)
    _scan_css(css, findings)
    _scan_secrets(html, findings, file="index.html")
    _scan_secrets(css, findings, file="style.css")
    _scan_secrets(js, findings, file="script.js")
    _scan_accessibility(html, findings)
    _check_contrast(palette, findings)

    return _finalize(findings)


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
def _line_at(text: str, pos: int, offset: int = 0) -> int:
    return text.count("\n", 0, pos) + 1 + offset


def _add(
    findings: list[dict[str, Any]],
    rule: str,
    severity: str,
    category: str,
    title: str,
    file: str,
    detail: str = "",
    fix: str = "",
    line: int | None = None,
) -> None:
    findings.append(
        {
            "rule": rule,
            "severity": severity,
            "category": category,
            "title": title,
            "detail": detail,
            "fix": fix,
            "file": file,
            "line": line,
            "source": "sast",
        }
    )


def _finalize(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dédoublonne sur (règle, fichier, ligne), plafonne par règle, trie par gravité."""
    seen: set[tuple[str, str, int | None]] = set()
    per_rule: dict[str, int] = {}
    kept: list[dict[str, Any]] = []

    for finding in findings:
        key = (finding["rule"], finding["file"], finding["line"])
        if key in seen:
            continue
        seen.add(key)
        count = per_rule.get(finding["rule"], 0)
        if count >= _MAX_PER_RULE:
            continue
        per_rule[finding["rule"]] = count + 1
        kept.append(finding)

    kept.sort(key=lambda f: (_SEVERITY_ORDER.get(f["severity"], 5), f["rule"], f["line"] or 0))
    return kept


# --------------------------------------------------------------------------- #
# JavaScript — fichier script.js et blocs <script> inline
# --------------------------------------------------------------------------- #
_DANGEROUS_JS: list[tuple[str, str, str, str, str]] = [
    (
        "js.eval",
        r"\beval\s*\(",
        "critical",
        "Utilisation de eval()",
        "eval() exécute du code arbitraire : toute donnée qui y parvient devient du code.",
    ),
    (
        "js.new_function",
        r"\bnew\s+Function\s*\(",
        "critical",
        "Utilisation de new Function()",
        "Équivalent à eval() : construit du code exécutable à partir d'une chaîne.",
    ),
    (
        "js.document_write",
        r"\bdocument\.write(?:ln)?\s*\(",
        "critical",
        "document.write()",
        "Injecte du HTML arbitraire dans le document pendant son analyse.",
    ),
    (
        "js.inner_html",
        r"\.(?:innerHTML|outerHTML)\s*=|\.insertAdjacentHTML\s*\(",
        "high",
        "innerHTML non contrôlé",
        "Affecter du HTML construit dynamiquement expose à une injection de balises.",
    ),
    (
        # el.onclick = "alert(1)" : une CHAÎNE affectée à un handler.
        # el.onclick = maFonction est légitime et ne doit pas remonter.
        "js.string_event_handler",
        r"\.\s*on[a-z]+\s*=\s*[\"'`]",
        "high",
        "Handler d'événement défini par une chaîne",
        "Une chaîne affectée à un handler est évaluée comme du code.",
    ),
    (
        # Seule l'affectation d'une URL javascript: est dangereuse ; la même chaîne
        # stockée dans une variable de contenu ne l'est pas.
        "js.javascript_url",
        r"(?:\.href|\.src|location(?:\.href)?)\s*=\s*[\"'`]\s*javascript:",
        "critical",
        "Navigation vers une URL javascript:",
        "Affecter une URL javascript: exécute du code arbitraire.",
    ),
]

_FIXES = {
    "js.eval": "Utiliser JSON.parse() pour des données, jamais eval().",
    "js.new_function": "Remplacer par une fonction déclarée normalement.",
    "js.document_write": "Construire les nœuds avec createElement/textContent.",
    "js.inner_html": "Utiliser textContent, ou construire les nœuds un par un.",
    "js.string_event_handler": "Passer une référence de fonction, ou utiliser addEventListener.",
    "js.javascript_url": "Utiliser un gestionnaire d'événement plutôt qu'une URL javascript:.",
}


def _scan_js(js: str, findings: list[dict[str, Any]], *, file: str, line_offset: int = 0) -> None:
    if not js.strip():
        return
    for rule, pattern, severity, title, detail in _DANGEROUS_JS:
        for match in re.finditer(pattern, js):
            _add(
                findings,
                rule,
                severity,
                "security",
                title,
                file,
                detail,
                _FIXES.get(rule, "Supprimer le code dangereux."),
                _line_at(js, match.start(), line_offset),
            )


_INLINE_SCRIPT_RE = re.compile(
    r"<script\b(?P<attrs>[^>]*)>(?P<body>.*?)</script\s*>", re.IGNORECASE | re.DOTALL
)


def _scan_inline_scripts(html: str, findings: list[dict[str, Any]]) -> None:
    """Analyse le code des `<script>` inline du HTML.

    Sans ça, un `eval()` écrit directement dans index.html n'était jamais vu : le scanner
    ne regardait que script.js. C'était son principal angle mort.
    """
    if not html:
        return
    for match in _INLINE_SCRIPT_RE.finditer(html):
        if re.search(r"\bsrc\s*=", match.group("attrs"), re.IGNORECASE):
            continue  # script externe : traité par _scan_html
        body = match.group("body")
        if not body.strip():
            continue
        offset = _line_at(html, match.start("body")) - 1
        _scan_js(body, findings, file="index.html", line_offset=offset)


# --------------------------------------------------------------------------- #
# HTML
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"<(?P<name>[a-zA-Z][a-zA-Z0-9-]*)\b(?P<attrs>[^>]*)>")
_INLINE_HANDLER_RE = re.compile(r"\bon[a-z]+\s*=\s*[\"'][^\"']*[\"']", re.IGNORECASE)
_EXTERNAL_URL = r"(?:https?:)?//"


def _attr(attrs: str, name: str) -> str | None:
    match = re.search(rf"\b{name}\s*=\s*[\"']([^\"']*)[\"']", attrs, re.IGNORECASE)
    return match.group(1) if match else None


def _scan_html(html: str, findings: list[dict[str, Any]]) -> None:
    if not html.strip():
        _add(findings, "html.empty", "high", "quality", "HTML vide", "index.html",
             "Le site n'a aucun contenu HTML.", "Générer un document complet.", 1)
        return

    _scan_document_head(html, findings)

    for match in _TAG_RE.finditer(html):
        name = match.group("name").lower()
        attrs = match.group("attrs")
        line = _line_at(html, match.start())

        handler = _INLINE_HANDLER_RE.search(attrs)
        if handler:
            _add(findings, "html.inline_event_handler", "high", "security",
                 "Handler d'événement inline", "index.html",
                 f"<{name}> porte {handler.group(0)[:60]}.",
                 "Déplacer le code dans script.js avec addEventListener.", line)

        for attr_name in ("href", "src", "action", "formaction"):
            value = _attr(attrs, attr_name)
            if value is None:
                continue
            stripped = value.strip()
            lowered = stripped.lower()

            if lowered.startswith("javascript:"):
                _add(findings, "html.javascript_url", "critical", "security",
                     "URL javascript:", "index.html",
                     f"<{name} {attr_name}=\"{stripped[:50]}\">.",
                     "Remplacer par un gestionnaire d'événement dans script.js.", line)
            elif lowered.startswith("data:text/html"):
                _add(findings, "html.data_html_uri", "high", "security",
                     "URI data:text/html", "index.html",
                     f"<{name}> pointe vers un document data: qui hérite de l'origine du site.",
                     "Servir le document depuis un fichier du site.", line)
            elif lowered.startswith("http://"):
                _add(findings, "html.insecure_http_link", "medium", "security",
                     "Lien http:// non sécurisé", "index.html",
                     f"<{name} {attr_name}=\"{stripped[:50]}\">.",
                     "Passer en https:// ou en lien relatif.", line)

        src = _attr(attrs, "src")
        href = _attr(attrs, "href")

        if name == "script" and src and re.match(_EXTERNAL_URL, src):
            _add(findings, "html.external_script", "high", "security",
                 "Script externe détecté", "index.html", f"src: {src[:70]}",
                 "Intégrer le script localement : le site doit être autonome.", line)

        if name == "link" and href and re.match(_EXTERNAL_URL, href):
            _add(findings, "html.external_resource", "medium", "security",
                 "Ressource externe (CDN ou police)", "index.html", f"href: {href[:70]}",
                 "Supprimer la dépendance externe.", line)

        if name == "iframe":
            if src and re.match(_EXTERNAL_URL, src):
                _add(findings, "html.iframe_external", "high", "security",
                     "iframe externe", "index.html",
                     f"Le site embarque un document tiers ({src[:60]}).",
                     "Retirer l'iframe ou la remplacer par un lien explicite.", line)
            if _attr(attrs, "srcdoc") is not None:
                _add(findings, "html.srcdoc", "medium", "security",
                     "iframe srcdoc", "index.html",
                     "Le contenu de srcdoc est interprété comme un document HTML.",
                     "Construire la section directement dans la page.", line)

        if name == "base":
            _add(findings, "html.base_tag", "medium", "security",
                 "Balise <base> détectée", "index.html",
                 "Une balise <base> réécrit la cible de tous les liens relatifs de la page.",
                 "Supprimer <base> et utiliser des chemins relatifs explicites.", line)

        if name == "form":
            action = _attr(attrs, "action")
            if action is None:
                _add(findings, "html.form_no_action", "info", "security",
                     "Formulaire sans action", "index.html",
                     "Le formulaire ne définit pas d'action : la soumission rechargera la page.",
                     "Définir une action, ou gérer l'envoi en JavaScript.", line)
            elif re.match(_EXTERNAL_URL, action.strip()):
                _add(findings, "html.form_external_action", "high", "security",
                     "Formulaire vers un domaine externe", "index.html",
                     f"Les données saisies par les visiteurs partent vers {action[:60]}.",
                     "Poster vers le domaine du site, ou retirer le formulaire.", line)

        if name == "a" and (_attr(attrs, "target") or "").lower() == "_blank":
            rel = (_attr(attrs, "rel") or "").lower()
            if "noopener" not in rel and "noreferrer" not in rel:
                _add(findings, "html.target_blank_no_noopener", "medium", "security",
                     "target=\"_blank\" sans rel=\"noopener\"", "index.html",
                     "La page ouverte peut manipuler la page d'origine (tabnabbing).",
                     'Ajouter rel="noopener noreferrer".', line)

        if name == "img" and _attr(attrs, "alt") is None:
            _add(findings, "html.img_no_alt", "medium", "accessibility",
                 "Image sans alt", "index.html",
                 "Une image sans attribut alt est ignorée par les lecteurs d'écran.",
                 'Ajouter un alt descriptif (ou alt="" si l\'image est décorative).', line)


def _scan_document_head(html: str, findings: list[dict[str, Any]]) -> None:
    if "<!doctype" not in html.lower() and "<html" not in html.lower():
        _add(findings, "html.missing_doctype", "high", "quality", "Document HTML incomplet",
             "index.html", "Doctype ou balise <html> manquant.", "Ajouter <!DOCTYPE html>.", 1)
    if not re.search(r"<meta[^>]+charset", html, re.IGNORECASE):
        _add(findings, "html.missing_charset", "medium", "quality", "Charset manquant",
             "index.html", "Sans charset déclaré, les accents peuvent s'afficher incorrectement.",
             'Ajouter <meta charset="utf-8">.', 1)
    if not re.search(r"<meta[^>]+viewport", html, re.IGNORECASE):
        _add(findings, "html.missing_viewport", "high", "responsive", "Viewport manquant",
             "index.html", "Sans meta viewport, le site s'affiche dézoomé sur mobile.",
             'Ajouter <meta name="viewport" content="width=device-width, initial-scale=1">.', 1)
    if not re.search(r"<html[^>]+lang\s*=", html, re.IGNORECASE):
        _add(findings, "html.missing_lang", "medium", "accessibility", "Attribut lang manquant",
             "index.html", "La langue du document n'est pas déclarée.",
             'Ajouter lang="fr" sur <html>.', 1)


# --------------------------------------------------------------------------- #
# CSS
# --------------------------------------------------------------------------- #
def _scan_css(css: str, findings: list[dict[str, Any]]) -> None:
    if not css:
        return
    for match in re.finditer(r"@import\s+(?:url\(\s*)?[\"']?(?:https?:)?//", css, re.IGNORECASE):
        _add(findings, "css.import_external", "medium", "security", "@import externe dans le CSS",
             "style.css", "Le CSS importe une feuille de style distante.",
             "Intégrer les règles localement.", _line_at(css, match.start()))

    for match in re.finditer(r"url\(\s*[\"']?(?:https?:)?//", css, re.IGNORECASE):
        _add(findings, "css.external_resource", "medium", "security",
             "Ressource externe dans le CSS", "style.css",
             "Le CSS charge une ressource distante (police ou image).",
             "Remplacer par une ressource locale ou un data: URI SVG.", _line_at(css, match.start()))

    for match in re.finditer(r"\bexpression\s*\(", css, re.IGNORECASE):
        _add(findings, "css.expression", "high", "security", "expression() dans le CSS",
             "style.css", "expression() exécute du JavaScript depuis une feuille de style.",
             "Supprimer l'appel à expression().", _line_at(css, match.start()))


# --------------------------------------------------------------------------- #
# Secrets
# --------------------------------------------------------------------------- #
_SECRET_PATTERNS: list[tuple[str, str, str]] = [
    ("secret.openrouter", r"\bsk-or-v1-[A-Za-z0-9_-]{16,}", "Clé API type OpenRouter"),
    ("secret.openai", r"\bsk-[A-Za-z0-9]{20,}\b", "Clé API OpenAI"),
    ("secret.google_api_key", r"\bAIza[0-9A-Za-z_-]{20,}\b", "Clé API Google"),
    ("secret.aws_key", r"\bAKIA[0-9A-Z]{16}\b", "Clé AWS Access Key"),
    ("secret.github_token", r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b", "Token GitHub"),
    ("secret.slack", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b", "Token Slack"),
    ("secret.private_key", r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----", "Clé privée"),
    ("secret.jwt", r"\beyJhbGciOi[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.", "JWT / Bearer token"),
    (
        "secret.generic_api_key",
        r"\b(?:api[_-]?key|apikey|secret|token|password)\s*[:=]\s*[\"'][A-Za-z0-9_\-]{16,}[\"']",
        "Clé API générique",
    ),
]

_SECRET_FLAGS = {"secret.generic_api_key": re.IGNORECASE}


def _scan_secrets(text: str, findings: list[dict[str, Any]], *, file: str) -> None:
    if not text:
        return
    for rule, pattern, kind in _SECRET_PATTERNS:
        for match in re.finditer(pattern, text, _SECRET_FLAGS.get(rule, 0)):
            _add(findings, rule, "critical", "security", f"Secret détecté ({kind})", file,
                 "Un secret livré au navigateur est lisible par n'importe quel visiteur.",
                 "Retirer le secret du code et le servir depuis le backend.",
                 _line_at(text, match.start()))


# --------------------------------------------------------------------------- #
# Accessibilité déterministe
# --------------------------------------------------------------------------- #
def _scan_accessibility(html: str, findings: list[dict[str, Any]]) -> None:
    if not html:
        return

    h1s = list(re.finditer(r"<h1\b", html, re.IGNORECASE))
    if len(h1s) > 1:
        _add(findings, "a11y.multiple_h1", "low", "accessibility", "Plusieurs <h1>", "index.html",
             f"{len(h1s)} balises <h1> : la hiérarchie du document devient ambiguë.",
             "Ne garder qu'un <h1> et passer les autres en <h2>.", _line_at(html, h1s[1].start()))

    labelled = {
        m.group(1)
        for m in re.finditer(r"<label[^>]+for\s*=\s*[\"']([^\"']+)[\"']", html, re.IGNORECASE)
    }
    for match in re.finditer(r"<(?:input|select|textarea)\b[^>]*>", html, re.IGNORECASE):
        tag = match.group(0)
        if re.search(r"\btype\s*=\s*[\"'](?:hidden|submit|button|reset)[\"']", tag, re.IGNORECASE):
            continue
        if _attr(tag, "id") in labelled or _attr(tag, "aria-label") or _attr(tag, "aria-labelledby"):
            continue
        _add(findings, "a11y.input_no_label", "medium", "accessibility",
             "Champ de formulaire sans label", "index.html",
             "Le champ n'est associé à aucun label : il est inutilisable au lecteur d'écran.",
             'Ajouter un <label for="…"> ou un aria-label.', _line_at(html, match.start()))


def _relative_luminance(hex_color: str) -> float | None:
    value = hex_color.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(c * 2 for c in value)
    if len(value) != 6:
        return None
    try:
        channels = [int(value[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    except ValueError:
        return None
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _check_contrast(palette: tuple[str, str] | None, findings: list[dict[str, Any]]) -> None:
    """Contraste texte/fond du DesignSpec, seuil WCAG AA (4,5:1) pour le texte courant."""
    if not palette:
        return
    text_lum, bg_lum = _relative_luminance(palette[0]), _relative_luminance(palette[1])
    if text_lum is None or bg_lum is None:
        return
    lighter, darker = max(text_lum, bg_lum), min(text_lum, bg_lum)
    ratio = (lighter + 0.05) / (darker + 0.05)
    if ratio < 4.5:
        _add(findings, "a11y.contrast", "medium", "accessibility", "Contraste insuffisant",
             "style.css",
             f"Rapport texte/fond de {ratio:.1f}:1 ({palette[0]} sur {palette[1]}), "
             "sous le seuil WCAG AA de 4,5:1.",
             "Assombrir la couleur de texte ou éclaircir le fond.", 1)
