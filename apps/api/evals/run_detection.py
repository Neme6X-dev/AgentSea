"""Éval 6B — « Est-ce qu'on identifie bien les vulnérabilités ? »

Passe le SAST déterministe (`app/devsecops/sast.py`) sur un corpus annoté à la main
et calcule précision / rappel / F1. **Aucun appel réseau**, donc exécutable en CI comme
garde anti-régression.

Chaque cas de `evals/corpus/<nom>/` porte un `expected.json` :

    must_detect      règles qui DOIVENT être remontées  → manquantes = faux négatifs
    must_not_detect  pièges qui ne doivent PAS tirer     → remontées = faux positifs

Les règles remontées hors de ces deux listes sont comptées comme « extras » et
rapportées à part : elles ne pénalisent pas le score, ce qui permet d'ajouter des
règles au SAST sans réannoter tout le corpus.

Usage :
    .venv/bin/python -m evals.run_detection
    .venv/bin/python -m evals.run_detection --min-recall 0.9 --max-fp 0
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.devsecops.sast import sast_scan  # noqa: E402
from evals.rules import rule_of  # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parent / "corpus"
OUT_DIR = Path(__file__).resolve().parent / "out"


@dataclass
class CaseResult:
    name: str
    description: str
    vulnerable: bool
    detected: set[str] = field(default_factory=set)
    true_positives: set[str] = field(default_factory=set)
    false_negatives: set[str] = field(default_factory=set)
    false_positives: set[str] = field(default_factory=set)
    extras: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.false_negatives and not self.false_positives


def load_cases(corpus_dir: Path) -> list[Path]:
    if not corpus_dir.is_dir():
        raise SystemExit(f"Corpus introuvable : {corpus_dir}")
    cases = sorted(d for d in corpus_dir.iterdir() if d.is_dir() and (d / "expected.json").is_file())
    if not cases:
        raise SystemExit(f"Aucun cas annoté dans {corpus_dir}")
    return cases


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def run_case(case_dir: Path) -> CaseResult:
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    findings = sast_scan(
        html=_read(case_dir / "index.html"),
        css=_read(case_dir / "style.css"),
        js=_read(case_dir / "script.js"),
    )
    detected = {rule_of(f) for f in findings}
    must_detect = set(expected.get("must_detect", []))
    must_not_detect = set(expected.get("must_not_detect", []))

    return CaseResult(
        name=case_dir.name,
        description=expected.get("description", ""),
        vulnerable=bool(expected.get("vulnerable", False)),
        detected=detected,
        true_positives=must_detect & detected,
        false_negatives=must_detect - detected,
        false_positives=must_not_detect & detected,
        extras=detected - must_detect - must_not_detect,
    )


def aggregate(results: list[CaseResult]) -> dict[str, float | int]:
    tp = sum(len(r.true_positives) for r in results)
    fn = sum(len(r.false_negatives) for r in results)
    fp = sum(len(r.false_positives) for r in results)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "true_positives": tp,
        "false_negatives": fn,
        "false_positives": fp,
        "extras": sum(len(r.extras) for r in results),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "cases": len(results),
        "cases_ok": sum(1 for r in results if r.ok),
    }


def render_markdown(results: list[CaseResult], stats: dict[str, float | int], label: str) -> str:
    lines = [
        f"# Détection des vulnérabilités — {label}",
        "",
        f"Corpus : **{stats['cases']} cas**, dont {stats['cases_ok']} sans erreur.",
        "",
        "| Métrique | Valeur |",
        "| --- | --- |",
        f"| Rappel | **{stats['recall']:.2f}** |",
        f"| Précision | **{stats['precision']:.2f}** |",
        f"| F1 | **{stats['f1']:.2f}** |",
        f"| Vrais positifs | {stats['true_positives']} |",
        f"| Faux négatifs (vulnérabilités ratées) | {stats['false_negatives']} |",
        f"| Faux positifs (pièges déclenchés) | {stats['false_positives']} |",
        f"| Règles hors annotation (extras) | {stats['extras']} |",
        "",
        "## Détail par cas",
        "",
        "| Cas | État | Ratés | Faux positifs | Extras |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in results:
        lines.append(
            f"| `{r.name}` | {'✅' if r.ok else '❌'} "
            f"| {', '.join(sorted(r.false_negatives)) or '—'} "
            f"| {', '.join(sorted(r.false_positives)) or '—'} "
            f"| {', '.join(sorted(r.extras)) or '—'} |"
        )

    problems = [r for r in results if not r.ok]
    if problems:
        lines += ["", "## Cas en échec", ""]
        for r in problems:
            lines.append(f"### `{r.name}`")
            lines.append("")
            lines.append(r.description)
            lines.append("")
            if r.false_negatives:
                lines.append(f"- **Non détecté** : {', '.join(sorted(r.false_negatives))}")
            if r.false_positives:
                lines.append(f"- **Faux positif** : {', '.join(sorted(r.false_positives))}")
            lines.append("")
    return "\n".join(lines) + "\n"


def print_console(results: list[CaseResult], stats: dict[str, float | int]) -> None:
    width = max(len(r.name) for r in results)
    print()
    for r in results:
        mark = "✅" if r.ok else "❌"
        detail = ""
        if r.false_negatives:
            detail += f"  raté: {', '.join(sorted(r.false_negatives))}"
        if r.false_positives:
            detail += f"  faux positif: {', '.join(sorted(r.false_positives))}"
        print(f"  {mark} {r.name.ljust(width)}{detail}")
    print()
    print(f"  Rappel     {stats['recall']:.2f}   ({stats['true_positives']} détectées, "
          f"{stats['false_negatives']} ratées)")
    print(f"  Précision  {stats['precision']:.2f}   ({stats['false_positives']} faux positifs)")
    print(f"  F1         {stats['f1']:.2f}")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=CORPUS_DIR)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--label", default="", help="Étiquette du run (ex: baseline, apres-lot4)")
    parser.add_argument("--min-recall", type=float, default=0.0, help="Seuil d'échec (CI)")
    parser.add_argument("--max-fp", type=int, default=-1, help="Faux positifs tolérés (CI, -1 = illimité)")
    args = parser.parse_args(argv)

    results = [run_case(d) for d in load_cases(args.corpus)]
    stats = aggregate(results)
    print_console(results, stats)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    label = args.label or stamp
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / f"detection-{label}.md"
    report.write_text(render_markdown(results, stats, label), encoding="utf-8")
    print(f"  Rapport : {report}")
    print()

    failed = False
    if args.min_recall > 0 and stats["recall"] < args.min_recall:
        print(f"  ÉCHEC : rappel {stats['recall']:.2f} < seuil {args.min_recall:.2f}")
        failed = True
    if args.max_fp >= 0 and stats["false_positives"] > args.max_fp:
        print(f"  ÉCHEC : {stats['false_positives']} faux positifs > seuil {args.max_fp}")
        failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
