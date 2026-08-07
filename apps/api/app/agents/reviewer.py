"""Agent review/sécurité (Flo) : audit qualité + sécurité d'un site généré.

Combine une analyse LLM (Gemini) et des checks statiques déterministes (SAST).
"""
from __future__ import annotations

import json
import re

from app.contracts import (
    DesignSpec,
    GeneratedSite,
    ReviewDimensions,
    ReviewFinding,
    ReviewReport,
)
from app.devsecops.sast import sast_scan
from app.gemini import LLMError, gemini

SYSTEM_PROMPT = """# AGENT REVUE — Qualité & Sécurité

## Rôle
Tu audites un site généré (html/css/js) et produis un rapport structuré, affiché à l'utilisateur ET utilisé comme feuille de route de correction.

## Entrée
Le site généré + le DesignSpec (pour vérifier la fidélité).

## Ce que tu évalues
1. Sécurité (priorité) : XSS (innerHTML/outerHTML non échappé, injection de <script>, onclick/href javascript:, eval, new Function, document.write), scripts/styles distants (CDN), liens http:// non sécurisés, secrets/tokens en dur, formulaires sans action valide.
2. Qualité : fidélité au spec (palette exacte, typo, sections présentes, tone respecté), contenus cohérents, AUCUNE information inventée (téléphone/email fantômes).
3. Accessibilité : lang, alt, contrastes, navigation clavier, aria manquants critiques.
4. Responsive : viewport, rupture de layout mobile, overflow horizontal.

## Sortie — STRICT
Un objet JSON valide uniquement, sans markdown ni texte hors JSON :
{
  "score": 0-100,
  "verdict": "pass|warn|fail",
  "dimensions": {
    "security": 0-100, "design_fidelity": 0-100,
    "accessibility": 0-100, "responsiveness": 0-100, "content": 0-100
  },
  "findings": [
    { "severity": "critical|high|medium|low|info",
      "category": "security|quality|accessibility|responsive",
      "title": "court et explicite", "detail": "où et pourquoi",
      "fix": "correction concrète", "file": "index.html|style.css|script.js" }
  ],
  "summary": "2-3 phrases, compréhensibles par un non-technique"
}

## Règles
- Impitoyable sur la sécurité : le moindre eval ou innerHTML non échappé → critical.
- Findings triés critical → info. Score cohérent avec les findings (pas de 95 si un critical existe).
- Jamais de fix qui introduit une dépendance externe. Langue du résumé = langue du site."""


async def review_site(
    site: GeneratedSite,
    spec: DesignSpec,
    model: str | None = None,
) -> ReviewReport:
    """Audite un site : checks SAST (déterministes) + revue LLM, puis fusionne.

    La revue LLM est *facultative* : si Gemini est indisponible ou répond hors schéma,
    le rapport se replie sur les seuls checks déterministes et le signale via
    `llm_available`. Ce repli ne doit jamais dégrader le verdict d'un site sain — c'est
    pourquoi les dimensions non vérifiables partent d'une base neutre et non de zéro.
    """
    sast_findings = _run_sast(site, spec)
    user = _build_user_message(site, spec)

    llm_findings: list[ReviewFinding] = []
    llm_dimensions: ReviewDimensions | None = None
    summary = ""

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            data = await gemini.complete_json(SYSTEM_PROMPT, user, model=model or None)
            report = _parse_llm_report(data)
            llm_findings = report.findings
            llm_dimensions = report.dimensions
            summary = report.summary
            break
        except (LLMError, ValueError) as exc:
            # ValueError = réponse hors schéma. Sans ce rattrapage, elle remontait en
            # HTTP 500 et cassait le workflow n8n au lieu de dégrader proprement.
            last_error = exc
            if attempt == 0:
                user = (
                    f"{user}\n\nATTENTION : ta réponse précédente était invalide ({exc}). "
                    "Réponds uniquement avec le JSON conforme au schéma."
                )

    llm_available = llm_dimensions is not None
    if not llm_available:
        summary = (
            "Revue automatique partielle : l'analyse par le modèle est indisponible "
            f"({last_error}). Le rapport ne repose que sur les contrôles déterministes."
        )

    merged = _merge_findings(sast_findings, llm_findings)
    dimensions = _merge_dimensions(llm_dimensions, merged)
    score, verdict = _score(merged, dimensions)
    return ReviewReport(
        score=score,
        verdict=verdict,
        dimensions=dimensions,
        findings=merged,
        summary=summary,
        sast_findings_count=len(sast_findings),
        llm_findings_count=len(llm_findings),
        llm_available=llm_available,
    )


def _run_sast(site: GeneratedSite, spec: DesignSpec) -> list[ReviewFinding]:
    findings = sast_scan(
        html=site.html,
        css=site.css,
        js=site.js,
        # La palette vient du spec : elle permet de vérifier le contraste texte/fond
        # (WCAG AA) sans avoir à deviner quelles variables CSS portent ces couleurs.
        palette=(spec.palette.text, spec.palette.bg),
    )
    # `source` distingue le déterministe du LLM : seul le premier pénalise les dimensions.
    return [ReviewFinding(**{**f, "source": "sast"}) for f in findings]


def _build_user_message(site: GeneratedSite, spec: DesignSpec) -> str:
    return (
        f"## DesignSpec (référence)\n{json.dumps(spec.model_dump(), ensure_ascii=False, indent=2)}\n\n"
        f"## Site généré\nHTML:\n{site.html[:8000]}\n\nCSS:\n{site.css[:4000]}\n\nJS:\n{site.js[:2000]}\n\n"
        "Produis le rapport JSON de revue."
    )


_CATEGORIES = {"security", "quality", "accessibility", "responsive"}
_SEVERITIES = {"critical", "high", "medium", "low", "info"}


def _coerce_enum(value: object, allowed: set[str], default: str) -> str:
    """Ramène une valeur de LLM dans l'énumération attendue.

    Gemini recopie parfois la syntaxe du schéma (`"responsive|accessibility"`) au lieu
    de choisir. Plutôt que de jeter tout le rapport pour un champ, on retient la
    première valeur reconnue.
    """
    text = str(value or "").strip().lower()
    if text in allowed:
        return text
    for token in re.split(r"[|,/\s]+", text):
        if token in allowed:
            return token
    return default


def _parse_llm_report(data: dict) -> ReviewReport:
    findings = data.get("findings")
    if isinstance(findings, list):
        for finding in findings:
            if isinstance(finding, dict):
                finding["category"] = _coerce_enum(finding.get("category"), _CATEGORIES, "quality")
                finding["severity"] = _coerce_enum(finding.get("severity"), _SEVERITIES, "info")
                finding["source"] = "llm"
    if isinstance(data.get("verdict"), str):
        data["verdict"] = _coerce_enum(data["verdict"], {"pass", "warn", "fail"}, "warn")

    try:
        return ReviewReport.model_validate(data)
    except Exception as exc:
        raise ValueError(f"Rapport LLM invalide: {exc}") from exc


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_SAST_PENALTIES = {"critical": 30, "high": 18, "medium": 8, "low": 3, "info": 0}


def _merge_findings(
    sast: list[ReviewFinding],
    llm: list[ReviewFinding],
) -> list[ReviewFinding]:
    """Fusionne les deux sources en conservant la version déterministe des doublons.

    La clé inclut le fichier et la ligne : deux failles distinctes qui portent le même
    titre ne sont plus écrasées l'une par l'autre.
    """
    seen: set[tuple[str, str, str, str, int | None]] = set()
    merged: list[ReviewFinding] = []
    for finding in [*sast, *llm]:
        key = (
            finding.category,
            finding.severity,
            finding.file,
            finding.title.strip().lower(),
            finding.line,
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(finding)
    merged.sort(key=lambda f: _SEVERITY_ORDER.get(f.severity, 5))
    return merged


# Sans revue LLM, la fidélité au design ou la cohérence du contenu ne sont pas
# vérifiables. On part d'une base neutre plutôt que de zéro : un site sain doit rester
# publiable même si Gemini est en panne.
_NEUTRAL_WITHOUT_LLM = 80


def _merge_dimensions(
    base: ReviewDimensions | None,
    findings: list[ReviewFinding],
) -> ReviewDimensions:
    """Dégrade les dimensions selon les findings **déterministes** uniquement.

    Les findings du LLM sont exclus : le modèle a déjà tenu compte de ses propres
    constats en notant les dimensions. Les repénaliser ici revenait à sanctionner deux
    fois un reviewer précis, et donc à mieux noter un reviewer laconique.
    """
    dim = base.model_copy() if base is not None else ReviewDimensions(
        security=_NEUTRAL_WITHOUT_LLM,
        design_fidelity=_NEUTRAL_WITHOUT_LLM,
        accessibility=_NEUTRAL_WITHOUT_LLM,
        responsiveness=_NEUTRAL_WITHOUT_LLM,
        content=_NEUTRAL_WITHOUT_LLM,
    )
    for f in findings:
        if f.source != "sast":
            continue
        penalty = _SAST_PENALTIES.get(f.severity, 0)
        if penalty == 0:
            continue
        if f.category == "security":
            dim.security = max(0, dim.security - penalty)
        elif f.category == "accessibility":
            dim.accessibility = max(0, dim.accessibility - penalty)
        elif f.category == "responsive":
            dim.responsiveness = max(0, dim.responsiveness - penalty)
        else:
            dim.design_fidelity = max(0, dim.design_fidelity - penalty)
            dim.content = max(0, dim.content - penalty)
    return dim


def _score(findings: list[ReviewFinding], dims: ReviewDimensions) -> tuple[int, str]:
    avg = (dims.security + dims.design_fidelity + dims.accessibility + dims.responsiveness + dims.content) / 5
    for f in findings:
        if f.severity == "critical":
            avg = min(avg, 50)
        elif f.severity == "high":
            avg = min(avg, 65)
    score = max(0, min(100, int(round(avg))))
    if score >= 85 and not any(f.severity in ("critical", "high") for f in findings):
        verdict = "pass"
    elif score >= 55:
        verdict = "warn"
    else:
        verdict = "fail"
    return score, verdict
