"""Tests de devsecops.sast : analyse statique déterministe.

Ce module est le contrôle qui garde la publication d'un site client : son verdict décide
si `/api/sessions/{id}/publish` accepte la mise en ligne. Deux propriétés comptent donc
autant l'une que l'autre :

- **détecter** les vulnérabilités réelles, sans quoi le garde-fou est décoratif ;
- **ne pas crier à tort**, sans quoi l'utilisateur prend l'habitude de forcer la publication.

Les assertions portent sur `rule`, identifiant stable, et non sur `title` qui est un libellé
d'affichage amené à être reformulé.

Le corpus annoté de `evals/corpus/` complète ces tests en mesurant précision et rappel.
"""
from __future__ import annotations

from app.devsecops.sast import sast_scan

CLEAN_HTML = (
    '<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>Site</title></head><body><h1>Titre</h1></body></html>"
)


def rules(findings) -> set[str]:
    return {f["rule"] for f in findings}


def severity_of(findings, rule: str) -> str | None:
    for f in findings:
        if f["rule"] == rule:
            return f["severity"]
    return None


def scan(html=CLEAN_HTML, css="", js="", **kw):
    return sast_scan(html=html, css=css, js=js, **kw)


class TestJavaScript:
    def test_eval_is_critical(self):
        assert severity_of(scan(js="eval('alert(1)')"), "js.eval") == "critical"

    def test_new_function_and_document_write(self):
        out = scan(js="var f = new Function('a', 'return a'); document.write('<b>x</b>');")
        assert {"js.new_function", "js.document_write"} <= rules(out)

    def test_inner_html_is_high(self):
        assert severity_of(scan(js="el.innerHTML = data;"), "js.inner_html") == "high"

    def test_clean_js_is_silent(self):
        out = scan(js="document.addEventListener('click', function () {});")
        assert not any(f["category"] == "security" for f in out)

    def test_line_number_is_reported(self):
        """Un finding sans localisation n'est pas corrigeable automatiquement."""
        out = scan(js="var a = 1;\nvar b = 2;\neval(b);")
        finding = next(f for f in out if f["rule"] == "js.eval")
        assert finding["line"] == 3
        assert finding["file"] == "script.js"

    def test_source_is_marked_sast(self):
        """Le reviewer ne dégrade le score que sur des findings déterministes."""
        assert all(f["source"] == "sast" for f in scan(js="eval(1)"))


class TestInlineScript:
    """Le code d'un <script> inline échappait entièrement à l'analyse."""

    def test_eval_inside_inline_script_is_detected(self):
        html = CLEAN_HTML.replace("</body>", "<script>var x = eval(conf);</script></body>")
        assert "js.eval" in rules(scan(html=html))

    def test_inline_script_line_is_absolute_in_the_document(self):
        html = (
            '<!DOCTYPE html>\n<html lang="fr">\n<head><meta charset="utf-8">\n'
            '<meta name="viewport" content="w"></head>\n<body>\n<script>\neval(1);\n'
            "</script>\n</body></html>"
        )
        finding = next(f for f in scan(html=html) if f["rule"] == "js.eval")
        assert finding["file"] == "index.html"
        assert finding["line"] == 7

    def test_external_script_reference_is_not_scanned_as_code(self):
        html = CLEAN_HTML.replace("</body>", '<script src="script.js"></script></body>')
        assert "js.eval" not in rules(scan(html=html))


class TestHtmlSecurity:
    def test_inline_event_handler_in_markup(self):
        html = CLEAN_HTML.replace("</body>", '<button onclick="alert(1)">x</button></body>')
        assert severity_of(scan(html=html), "html.inline_event_handler") == "high"

    def test_onclick_property_assignment_is_not_flagged(self):
        """`el.onclick = maFonction` est parfaitement légitime."""
        out = scan(js="var b = document.querySelector('a');\nb.onclick = ouvrirMenu;")
        assert not (rules(out) & {"html.inline_event_handler", "js.string_event_handler"})

    def test_string_assigned_to_handler_is_flagged(self):
        assert "js.string_event_handler" in rules(scan(js='el.onclick = "alert(1)";'))

    def test_javascript_url_in_href(self):
        html = CLEAN_HTML.replace("</body>", '<a href="javascript:void(0)">x</a></body>')
        assert severity_of(scan(html=html), "html.javascript_url") == "critical"

    def test_javascript_word_in_visible_text_is_not_flagged(self):
        """Un site qui *parle* de sécurité ne doit pas déclencher d'alerte."""
        html = CLEAN_HTML.replace("</body>", "<p>Les URL javascript: sont interdites.</p></body>")
        assert "html.javascript_url" not in rules(scan(html=html))

    def test_external_script_and_stylesheet(self):
        html = CLEAN_HTML.replace(
            "</body>",
            '<script src="https://cdn.example/x.js"></script>'
            '<link rel="stylesheet" href="https://fonts.example/f.css"></body>',
        )
        assert {"html.external_script", "html.external_resource"} <= rules(scan(html=html))

    def test_external_iframe_and_srcdoc(self):
        html = CLEAN_HTML.replace(
            "</body>", '<iframe src="https://tiers.example/x" srcdoc="contenu"></iframe></body>'
        )
        assert {"html.iframe_external", "html.srcdoc"} <= rules(scan(html=html))

    def test_data_text_html_uri(self):
        html = CLEAN_HTML.replace("</body>", '<a href="data:text/html;base64,PHA+">x</a></body>')
        assert severity_of(scan(html=html), "html.data_html_uri") == "high"

    def test_data_image_uri_is_allowed(self):
        """Un SVG inline en data: est l'alternative recommandée à une image distante."""
        html = CLEAN_HTML.replace(
            "</body>", '<img src="data:image/svg+xml,%3Csvg%3E" alt="Logo"></body>'
        )
        assert not (rules(scan(html=html)) & {"html.data_html_uri", "html.img_no_alt"})

    def test_base_tag(self):
        html = CLEAN_HTML.replace("<title>", '<base href="/autre/"><title>')
        assert "html.base_tag" in rules(scan(html=html))

    def test_form_posting_to_another_domain(self):
        html = CLEAN_HTML.replace(
            "</body>",
            '<form action="https://collecte.example/leads"><input id="a" aria-label="a"></form></body>',
        )
        assert severity_of(scan(html=html), "html.form_external_action") == "high"

    def test_target_blank_without_noopener(self):
        html = CLEAN_HTML.replace("</body>", '<a href="https://x.example" target="_blank">x</a></body>')
        assert "html.target_blank_no_noopener" in rules(scan(html=html))

    def test_target_blank_with_noopener_is_fine(self):
        html = CLEAN_HTML.replace(
            "</body>", '<a href="https://x.example" target="_blank" rel="noopener">x</a></body>'
        )
        assert "html.target_blank_no_noopener" not in rules(scan(html=html))

    def test_http_link_is_flagged(self):
        html = CLEAN_HTML.replace("</body>", '<a href="http://ancien.example">x</a></body>')
        assert "html.insecure_http_link" in rules(scan(html=html))


class TestHtmlStructure:
    def test_missing_doctype(self):
        assert "html.missing_doctype" in rules(scan(html="<p>juste du texte</p>"))

    def test_missing_viewport_charset_lang(self):
        out = scan(html="<!DOCTYPE html><html><body>x</body></html>")
        assert {"html.missing_viewport", "html.missing_charset", "html.missing_lang"} <= rules(out)

    def test_empty_html(self):
        assert "html.empty" in rules(scan(html="   "))

    def test_clean_document_has_no_critical_or_high(self):
        assert not any(f["severity"] in ("critical", "high") for f in scan(html=CLEAN_HTML))


class TestCss:
    def test_external_font_and_import(self):
        css = (
            '@import url("https://fonts.example/f.css");\n'
            ".a { background: url(https://cdn.example/i.png); }"
        )
        assert {"css.import_external", "css.external_resource"} <= rules(scan(css=css))

    def test_data_uri_in_css_is_allowed(self):
        assert "css.external_resource" not in rules(
            scan(css='.a { background: url("data:image/svg+xml,%3Csvg%3E"); }')
        )

    def test_expression_is_flagged(self):
        assert "css.expression" in rules(scan(css=".a { width: expression(alert(1)); }"))


class TestSecrets:
    def test_google_api_key(self):
        out = scan(js='var k = "AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";')
        assert severity_of(out, "secret.google_api_key") == "critical"

    def test_private_key(self):
        # Marqueur scindé pour que les scanners de secrets ne prennent pas ce
        # fichier de test pour une vraie fuite de clé privée.
        pem = "-----BEGIN " + "PRIVATE KEY-----\nabc"
        assert "secret.private_key" in rules(scan(html=pem))

    def test_github_and_slack_tokens(self):
        js = 'var a = "ghp_' + "a" * 36 + '"; var b = "xoxb-1234567890-abcdef";'
        assert {"secret.github_token", "secret.slack"} <= rules(scan(js=js))

    def test_generic_api_key_assignment(self):
        assert "secret.generic_api_key" in rules(scan(js='const api_key = "abcdef1234567890XY";'))

    def test_file_of_the_secret_is_reported(self):
        """Sans le fichier, l'utilisateur ne sait pas où retirer le secret."""
        out = scan(css="/* AIzaSyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA */")
        finding = next(f for f in out if f["rule"] == "secret.google_api_key")
        assert finding["file"] == "style.css"

    def test_no_secret_in_ordinary_content(self):
        html = CLEAN_HTML.replace("</body>", "<p>Notre mot de passe est secret.</p></body>")
        assert not any(f["rule"].startswith("secret.") for f in scan(html=html))


class TestAccessibility:
    def test_image_without_alt(self):
        html = CLEAN_HTML.replace("</body>", '<img src="a.svg"></body>')
        assert "html.img_no_alt" in rules(scan(html=html))

    def test_multiple_h1(self):
        html = CLEAN_HTML.replace("</body>", "<h1>Deuxième</h1></body>")
        assert "a11y.multiple_h1" in rules(scan(html=html))

    def test_input_without_label(self):
        html = CLEAN_HTML.replace("</body>", '<form action="/x"><input id="mail"></form></body>')
        assert "a11y.input_no_label" in rules(scan(html=html))

    def test_labelled_input_is_fine(self):
        html = CLEAN_HTML.replace(
            "</body>",
            '<form action="/x"><label for="mail">Mail</label><input id="mail"></form></body>',
        )
        assert "a11y.input_no_label" not in rules(scan(html=html))

    def test_submit_button_needs_no_label(self):
        html = CLEAN_HTML.replace("</body>", '<form action="/x"><input type="submit"></form></body>')
        assert "a11y.input_no_label" not in rules(scan(html=html))

    def test_contrast_below_aa_is_flagged(self):
        assert "a11y.contrast" in rules(scan(palette=("#bbbbbb", "#ffffff")))

    def test_sufficient_contrast_is_silent(self):
        assert "a11y.contrast" not in rules(scan(palette=("#111111", "#ffffff")))

    def test_contrast_skipped_without_palette(self):
        assert "a11y.contrast" not in rules(scan())


class TestReportHygiene:
    def test_repeated_defect_is_capped(self):
        """Un défaut répété ne doit pas noyer les findings graves dans le rapport."""
        html = CLEAN_HTML.replace("</body>", '<img src="a.svg">' * 40 + "</body>")
        assert sum(1 for f in scan(html=html) if f["rule"] == "html.img_no_alt") <= 3

    def test_findings_are_sorted_by_severity(self):
        html = CLEAN_HTML.replace("</body>", '<img src="a.svg"><a href="javascript:x">y</a></body>')
        out = scan(html=html, js="eval(1)")
        order = ["critical", "high", "medium", "low", "info"]
        positions = [order.index(f["severity"]) for f in out]
        assert positions == sorted(positions)

    def test_identical_finding_on_same_line_is_deduplicated(self):
        """Deux occurrences sur une même ligne : une seule entrée, une seule correction."""
        assert sum(1 for f in scan(js="eval(1); eval(1);") if f["rule"] == "js.eval") == 1
