"""Identifiants de règles canoniques pour l'évaluation de la détection.

Le SAST (`app/devsecops/sast.py`) identifie aujourd'hui ses findings par leur `title`,
une chaîne en français destinée à l'utilisateur. Ces titres bougeront (reformulation,
traduction) alors que le corpus annoté, lui, doit rester stable.

Ce module fait le pont : un identifiant canonique par règle, et une table d'alias
`title → rule`. Quand `sast_scan` exposera un champ `rule`, le harnais le préférera et
cette table ne servira plus qu'aux rapports archivés.
"""
from __future__ import annotations

from typing import Any

# --------------------------------------------------------------------------- #
# Règles canoniques
# --------------------------------------------------------------------------- #
JS_EVAL = "js.eval"
JS_NEW_FUNCTION = "js.new_function"
JS_DOCUMENT_WRITE = "js.document_write"
JS_INNER_HTML = "js.inner_html"

HTML_EMPTY = "html.empty"
HTML_MISSING_DOCTYPE = "html.missing_doctype"
HTML_MISSING_CHARSET = "html.missing_charset"
HTML_MISSING_VIEWPORT = "html.missing_viewport"
HTML_MISSING_LANG = "html.missing_lang"
HTML_IMG_NO_ALT = "html.img_no_alt"
HTML_INLINE_EVENT_HANDLER = "html.inline_event_handler"
HTML_JAVASCRIPT_URL = "html.javascript_url"
HTML_EXTERNAL_SCRIPT = "html.external_script"
HTML_EXTERNAL_RESOURCE = "html.external_resource"
HTML_INSECURE_HTTP_LINK = "html.insecure_http_link"
HTML_IFRAME_EXTERNAL = "html.iframe_external"
HTML_SRCDOC = "html.srcdoc"
HTML_DATA_HTML_URI = "html.data_html_uri"
HTML_BASE_TAG = "html.base_tag"
HTML_FORM_EXTERNAL_ACTION = "html.form_external_action"
HTML_FORM_NO_ACTION = "html.form_no_action"
HTML_TARGET_BLANK_NO_NOOPENER = "html.target_blank_no_noopener"

CSS_EXTERNAL_RESOURCE = "css.external_resource"
CSS_IMPORT_EXTERNAL = "css.import_external"
CSS_EXPRESSION = "css.expression"

SECRET_GOOGLE_API_KEY = "secret.google_api_key"
SECRET_AWS_KEY = "secret.aws_key"
SECRET_PRIVATE_KEY = "secret.private_key"
SECRET_JWT = "secret.jwt"
SECRET_OPENROUTER = "secret.openrouter"
SECRET_GITHUB_TOKEN = "secret.github_token"
SECRET_OPENAI = "secret.openai"
SECRET_SLACK = "secret.slack"
SECRET_GENERIC_API_KEY = "secret.generic_api_key"

A11Y_MULTIPLE_H1 = "a11y.multiple_h1"
A11Y_INPUT_NO_LABEL = "a11y.input_no_label"
A11Y_CONTRAST = "a11y.contrast"

UNKNOWN = "unknown"

# --------------------------------------------------------------------------- #
# Alias : titre produit par le SAST → règle canonique
# --------------------------------------------------------------------------- #
_TITLE_ALIASES: dict[str, str] = {
    "utilisation de eval()": JS_EVAL,
    "utilisation de new function()": JS_NEW_FUNCTION,
    "document.write()": JS_DOCUMENT_WRITE,
    "innerhtml non contrôlé": JS_INNER_HTML,
    "event handler inline": HTML_INLINE_EVENT_HANDLER,
    "url javascript:": HTML_JAVASCRIPT_URL,
    "url javascript: dans un lien": HTML_JAVASCRIPT_URL,
    "html vide": HTML_EMPTY,
    "document html incomplet": HTML_MISSING_DOCTYPE,
    "charset manquant": HTML_MISSING_CHARSET,
    "viewport manquant": HTML_MISSING_VIEWPORT,
    "attribut lang manquant": HTML_MISSING_LANG,
    "image sans alt": HTML_IMG_NO_ALT,
    "script externe détecté": HTML_EXTERNAL_SCRIPT,
    "ressource externe (cdn/font) détectée": HTML_EXTERNAL_RESOURCE,
    "lien http:// non sécurisé": HTML_INSECURE_HTTP_LINK,
    "formulaire sans action": HTML_FORM_NO_ACTION,
    "iframe externe": HTML_IFRAME_EXTERNAL,
    "iframe srcdoc": HTML_SRCDOC,
    "uri data:text/html": HTML_DATA_HTML_URI,
    "balise <base> détectée": HTML_BASE_TAG,
    "formulaire vers un domaine externe": HTML_FORM_EXTERNAL_ACTION,
    "target=\"_blank\" sans rel=\"noopener\"": HTML_TARGET_BLANK_NO_NOOPENER,
    "ressource externe dans le css": CSS_EXTERNAL_RESOURCE,
    "@import externe dans le css": CSS_IMPORT_EXTERNAL,
    "expression() dans le css": CSS_EXPRESSION,
    "plusieurs <h1>": A11Y_MULTIPLE_H1,
    "champ de formulaire sans label": A11Y_INPUT_NO_LABEL,
    "contraste insuffisant": A11Y_CONTRAST,
}

# Les findings « secret » portent le type entre parenthèses : Secret détecté (Clé privée).
_SECRET_ALIASES: dict[str, str] = {
    "clé api google": SECRET_GOOGLE_API_KEY,
    "clé aws access key": SECRET_AWS_KEY,
    "clé privée": SECRET_PRIVATE_KEY,
    "jwt / bearer token": SECRET_JWT,
    "clé api type openrouter": SECRET_OPENROUTER,
    "token github": SECRET_GITHUB_TOKEN,
    "clé api openai": SECRET_OPENAI,
    "token slack": SECRET_SLACK,
    "clé api générique": SECRET_GENERIC_API_KEY,
}


def rule_of(finding: dict[str, Any]) -> str:
    """Identifiant canonique d'un finding, via son champ `rule` sinon son titre."""
    explicit = finding.get("rule")
    if explicit:
        return str(explicit)

    title = str(finding.get("title", "")).strip().lower()
    if title.startswith("secret détecté"):
        kind = title.partition("(")[2].rpartition(")")[0].strip()
        return _SECRET_ALIASES.get(kind, SECRET_GENERIC_API_KEY)
    return _TITLE_ALIASES.get(title, UNKNOWN)
