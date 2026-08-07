"""Rapport de sécurité lisible (markdown) à partir d'un ReviewReport."""
from __future__ import annotations

from app.contracts import ReviewReport

_LABELS = {
    "security": "Sécurité",
    "design_fidelity": "Fidélité design",
    "accessibility": "Accessibilité",
    "responsiveness": "Responsive",
    "content": "Contenu",
}

_VERDICT_LABELS = {"pass": "✅ Validé", "warn": "⚠️ Avec réserves", "fail": "❌ À corriger"}


def render_markdown(report: ReviewReport) -> str:
    """Produit un rapport markdown affichable (utilisé par le front / la démo)."""
    lines: list[str] = [
        f"# Rapport de revue — Score {report.score}/100",
        "",
        f"**Verdict** : {_VERDICT_LABELS.get(report.verdict, report.verdict)}",
        "",
    ]
    if report.summary:
        lines += [report.summary, ""]

    lines.append("## Dimensions")
    for key, label in _LABELS.items():
        value = getattr(report.dimensions, key)
        bar = "█" * (value // 10) + "░" * (10 - value // 10)
        lines.append(f"- {label}: {value}/100 `{bar}`")
    lines.append("")

    if report.findings:
        lines.append("## Findings")
        for f in report.findings:
            sev = f.severity.upper().ljust(8)
            lines.append(f"- **[{sev}]** ({f.category}) {f.title}")
            if f.file:
                lines.append(f"  - Fichier: `{f.file}`")
            if f.detail:
                lines.append(f"  - {f.detail}")
            if f.fix:
                lines.append(f"  - Fix: {f.fix}")
        lines.append("")

    return "\n".join(lines)
