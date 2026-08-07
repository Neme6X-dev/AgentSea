"""Éval 6A — « Est-ce qu'on génère bien du code ? »

Envoie des DesignSpec figés à `POST /api/agents/code`, puis mesure le résultat avec des
règles déterministes (`app.agents.validation`) et avec le rapport de l'agent review.

Passer par `/api/agents/code` plutôt que `/api/dev/generate` **isole l'agent codeur** :
le spec est constant, donc deux runs sont comparables et l'écart mesuré vient bien du
codeur, pas du designer.

Usage :
    .venv/bin/python -m evals.run_generation --label baseline
    .venv/bin/python -m evals.run_generation --runs 1 --specs restaurant,avocat
"""
from __future__ import annotations

import argparse
import csv
import statistics
import sys
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agents.validation import validate_site  # noqa: E402
from evals.client import EvalClient, check_server  # noqa: E402
from evals.specs import SPECS  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "out"


@dataclass
class RunResult:
    spec: str
    run: int
    ok: bool = False
    error: str = ""
    slug: str = ""
    version: int = 0
    latency_code_s: float = 0.0
    latency_review_s: float = 0.0
    html_bytes: int = 0
    css_bytes: int = 0
    js_bytes: int = 0
    issues: list[str] = field(default_factory=list)
    sections_expected: int = 0
    sections_missing: int = 0
    palette_misses: int = 0
    invented_contact: bool = False
    sast_critical: int = 0
    sast_high: int = 0
    score: int = 0
    verdict: str = ""
    review_error: str = ""

    @property
    def conforme(self) -> bool:
        return self.ok and not self.issues


def run_one(client: EvalClient, spec_name: str, run_index: int) -> RunResult:
    result = RunResult(spec=spec_name, run=run_index)
    spec_dict = SPECS[spec_name]
    spec = client.spec_model(spec_dict)
    result.sections_expected = len(spec.sections)

    try:
        session = client.create_session(f"[eval {spec_name}] {spec.name} — {spec.tagline}")
        result.slug = session["slug"]
        code, result.latency_code_s = client.agent_code(session["id"], spec_dict)
        result.version = code["version"]

        site = client.load_version(result.slug, result.version)
        result.html_bytes = len(site.html.encode("utf-8"))
        result.css_bytes = len(site.css.encode("utf-8"))
        result.js_bytes = len(site.js.encode("utf-8"))

        issues = validate_site(site, spec)
        result.issues = [i.code for i in issues]
        result.sections_missing = sum(1 for i in issues if i.code.startswith("sections.missing"))
        result.palette_misses = sum(1 for i in issues if i.code.startswith("palette."))
        result.invented_contact = any(i.code.startswith("contact.invented") for i in issues)

        # La revue est mesurée à part : un review qui plante ne doit pas effacer les
        # métriques de génération, déjà collectées. C'est aussi un résultat en soi.
        try:
            review, result.latency_review_s = client.agent_review(session["id"], result.slug)
            report = review["report"]
            result.score = report["score"]
            result.verdict = report["verdict"]
            result.sast_critical = sum(1 for f in report["findings"] if f["severity"] == "critical")
            result.sast_high = sum(1 for f in report["findings"] if f["severity"] == "high")
        except Exception as exc:  # noqa: BLE001
            result.verdict = "erreur"
            result.review_error = f"{type(exc).__name__}: {exc}"[:200]
            print(f"    !! review {spec_name} run {run_index} : {result.review_error}", file=sys.stderr)

        result.ok = True
    except Exception as exc:  # noqa: BLE001 - un run raté ne doit pas tuer la campagne
        result.error = f"{type(exc).__name__}: {exc}"
        print(f"    !! {spec_name} run {run_index} : {result.error}", file=sys.stderr)
        if "--debug" in sys.argv:
            traceback.print_exc()
    return result


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def render_markdown(results: list[RunResult], label: str) -> str:
    done = [r for r in results if r.ok]
    conformes = [r for r in done if r.conforme]

    lines = [
        f"# Génération de code — {label}",
        "",
        f"{len(done)}/{len(results)} runs aboutis · "
        f"**{len(conformes)}/{len(done)} conformes** à toutes les règles déterministes.",
        "",
        "| Indicateur | Valeur |",
        "| --- | --- |",
        f"| Taux de conformité | **{len(conformes) / len(done) * 100:.0f}%** |" if done else "| Taux de conformité | — |",
        f"| Score reviewer moyen | {_mean([r.score for r in done]):.0f}/100 |",
        f"| Latence génération moyenne | {_mean([r.latency_code_s for r in done]):.1f} s |",
        f"| Latence review moyenne | {_mean([r.latency_review_s for r in done]):.1f} s |",
        f"| Taille HTML moyenne | {_mean([float(r.html_bytes) for r in done]) / 1024:.1f} Ko |",
        f"| Sections du spec manquantes | {sum(r.sections_missing for r in done)} |",
        f"| Couleurs du spec absentes du CSS | {sum(r.palette_misses for r in done)} |",
        f"| **Contacts inventés** | **{sum(1 for r in done if r.invented_contact)}** |",
        f"| Findings critical | {sum(r.sast_critical for r in done)} |",
        f"| Findings high | {sum(r.sast_high for r in done)} |",
        f"| **Revues en échec** | **{sum(1 for r in done if r.review_error)}/{len(done)}** |",
        "",
        "## Détail par run",
        "",
        "| Spec | Run | Conforme | Manquements | Score | Verdict | HTML | Code (s) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in results:
        if not r.ok:
            lines.append(f"| {r.spec} | {r.run} | ⛔ | `{r.error}` | — | — | — | — |")
            continue
        lines.append(
            f"| {r.spec} | {r.run} | {'✅' if r.conforme else '❌'} "
            f"| {', '.join(r.issues) or '—'} | {r.score} | {r.verdict} "
            f"| {r.html_bytes / 1024:.1f} Ko | {r.latency_code_s:.1f} |"
        )

    failures: dict[str, int] = {}
    for r in done:
        for code in r.issues:
            failures[code.split(":")[0]] = failures.get(code.split(":")[0], 0) + 1
    if failures:
        lines += ["", "## Règles les plus violées", "", "| Règle | Occurrences |", "| --- | --- |"]
        for code, count in sorted(failures.items(), key=lambda kv: -kv[1]):
            lines.append(f"| `{code}` | {count} |")

    return "\n".join(lines) + "\n"


def write_csv(results: list[RunResult], path: Path) -> None:
    rows = [asdict(r) for r in results]
    for row in rows:
        row["issues"] = ";".join(row["issues"])
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=2, help="Runs par spec (défaut 2)")
    parser.add_argument("--specs", default="", help="Sous-ensemble, séparé par des virgules")
    parser.add_argument("--label", default="", help="Étiquette du run (ex: baseline)")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    names = [s.strip() for s in args.specs.split(",") if s.strip()] or list(SPECS)
    unknown = [n for n in names if n not in SPECS]
    if unknown:
        raise SystemExit(f"Spec(s) inconnue(s) : {', '.join(unknown)}. Disponibles : {', '.join(SPECS)}")

    check_server()
    total = len(names) * args.runs
    print(f"\n  Campagne génération : {len(names)} specs × {args.runs} runs = {total} générations "
          f"({total * 2} appels Gemini)\n")

    results: list[RunResult] = []
    with EvalClient() as client:
        client.login()
        for run_index in range(1, args.runs + 1):
            for name in names:
                print(f"  [{len(results) + 1}/{total}] {name} run {run_index}…", flush=True)
                result = run_one(client, name, run_index)
                results.append(result)
                if result.ok:
                    state = "conforme" if result.conforme else f"{len(result.issues)} manquement(s)"
                    print(f"       {state} · score {result.score} ({result.verdict}) "
                          f"· {result.latency_code_s:.1f}s")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    label = args.label or stamp
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / f"generation-{label}.md"
    report.write_text(render_markdown(results, label), encoding="utf-8")
    write_csv(results, args.out / f"generation-{label}.csv")

    done = [r for r in results if r.ok]
    conformes = sum(1 for r in done if r.conforme)
    print(f"\n  Conformes : {conformes}/{len(done)}")
    print(f"  Contacts inventés : {sum(1 for r in done if r.invented_contact)}")
    print(f"  Rapport : {report}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
