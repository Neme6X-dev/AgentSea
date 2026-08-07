"""Éval 6C — « Est-ce qu'on intègre bien du code ? »

Le scénario le plus fragile du système : reprendre un site existant, y appliquer une
demande de l'utilisateur, et ne rien casser au passage. Chaque édition est jugée sur
**deux critères opposés** — l'instruction doit être appliquée, *et* tout le reste doit
être conservé. Un agent qui régénère un site tout neuf « réussit » l'application et
échoue la conservation ; c'est précisément ce qu'on veut voir.

Couvre aussi le cycle de vie que l'utilisateur attend quand son site est déjà en ligne :
prévisualiser sans publier, revenir en arrière, et être protégé d'une publication qui
casse le site.

Usage :
    .venv/bin/python -m evals.run_edit --label baseline
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.contracts import DesignSpec, GeneratedSite  # noqa: E402
from app.devsecops.sast import sast_scan  # noqa: E402
from evals.client import EvalClient, check_server  # noqa: E402
from evals.specs import SPECS  # noqa: E402

OUT_DIR = Path(__file__).resolve().parent / "out"

# Refonte : un spec volontairement à l'opposé du spec de départ (clair → sombre).
REDESIGN_SPEC: dict[str, Any] = {
    **SPECS["restaurant"],
    "tone": "premium",
    "style": "editorial",
    "palette": {
        "primary": "#c9a227",
        "secondary": "#1a1a1a",
        "accent": "#e0623d",
        "bg": "#121212",
        "text": "#f2efe9",
    },
    "typography": {"heading_font": "Georgia, serif", "body_font": "Georgia, serif", "base_size": "18px"},
}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Scenario:
    name: str
    description: str
    checks: list[Check] = field(default_factory=list)
    error: str = ""

    @property
    def passed(self) -> bool:
        return not self.error and all(c.passed for c in self.checks)

    def add(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append(Check(name, passed, detail))


# --------------------------------------------------------------------------- #
# Briques de vérification
# --------------------------------------------------------------------------- #
def section_ids(html: str) -> set[str]:
    return {m.group(1) for m in re.finditer(r'<section[^>]*\bid\s*=\s*["\']([^"\']+)["\']', html, re.IGNORECASE)}


def severity_counts(site: GeneratedSite) -> dict[str, int]:
    counts: dict[str, int] = {}
    for f in sast_scan(html=site.html, css=site.css, js=site.js):
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return counts


def check_conservation(scenario: Scenario, before: GeneratedSite, after: GeneratedSite) -> None:
    """Ce qui existait avant doit exister après : c'est ça, « intégrer » plutôt que « refaire »."""
    lost = section_ids(before.html) - section_ids(after.html)
    scenario.add(
        "sections conservées",
        not lost,
        f"perdues : {', '.join(sorted(lost))}" if lost else "toutes présentes",
    )

    missing_structure = [tag for tag in ("<header", "<main", "<footer") if tag not in after.html.lower()]
    scenario.add(
        "structure conservée",
        not missing_structure,
        f"absent : {', '.join(missing_structure)}" if missing_structure else "header/main/footer présents",
    )

    broken_refs = [ref for ref in ("style.css", "script.js") if ref not in after.html]
    scenario.add(
        "fichiers liés conservés",
        not broken_refs,
        f"non référencé : {', '.join(broken_refs)}" if broken_refs else "style.css et script.js référencés",
    )

    before_counts, after_counts = severity_counts(before), severity_counts(after)
    regressions = [
        sev for sev in ("critical", "high")
        if after_counts.get(sev, 0) > before_counts.get(sev, 0)
    ]
    scenario.add(
        "pas de régression sécurité",
        not regressions,
        f"nouveaux findings {', '.join(regressions)}" if regressions else "aucun nouveau finding critical/high",
    )


# --------------------------------------------------------------------------- #
# Scénarios
# --------------------------------------------------------------------------- #
def _applied_section_added(after: GeneratedSite) -> tuple[bool, str]:
    found = bool(re.search(r"horaire", after.html, re.IGNORECASE))
    return found, "section horaires présente" if found else "aucune mention d'horaires"


def _applied_cta_changed(after: GeneratedSite) -> tuple[bool, str]:
    found = "Réserver maintenant" in after.html
    return found, "nouveau libellé présent" if found else "libellé inchangé"


def _applied_text_rewritten(after: GeneratedSite) -> tuple[bool, str]:
    found = bool(re.search(r"famille", after.html, re.IGNORECASE))
    return found, "texte réécrit" if found else "aucune mention des familles"


TWEAKS: list[tuple[str, str, Callable[[GeneratedSite], tuple[bool, str]]]] = [
    ("ajout-section", "Ajoute une section Horaires qui reprend les horaires d'ouverture du spec.", _applied_section_added),
    ("changement-cta", "Change le libellé du bouton principal en « Réserver maintenant ».", _applied_cta_changed),
    ("reecriture-texte", "Réécris le texte de la section À propos pour insister sur l'accueil des familles.", _applied_text_rewritten),
]


def scenario_tweak(client: EvalClient, session_id: str, slug: str, name: str,
                   instruction: str, applied: Callable[[GeneratedSite], tuple[bool, str]]) -> Scenario:
    scenario = Scenario(f"retouche/{name}", instruction)
    try:
        before_version = client.get_session(session_id)["versions"][-1]
        before = client.load_version(slug, int(before_version.lstrip("v")))

        response, _ = client.edit(session_id, instruction)
        if response.status_code >= 400:
            scenario.error = f"HTTP {response.status_code}: {response.text[:200]}"
            return scenario

        after_version = client.get_session(session_id)["versions"][-1]
        scenario.add("nouvelle version créée", after_version != before_version, f"{before_version} → {after_version}")
        after = client.load_version(slug, int(after_version.lstrip("v")))

        ok, detail = applied(after)
        scenario.add("instruction appliquée", ok, detail)
        check_conservation(scenario, before, after)
    except Exception as exc:  # noqa: BLE001
        scenario.error = f"{type(exc).__name__}: {exc}"
    return scenario


def scenario_redesign(client: EvalClient, session_id: str, slug: str) -> Scenario:
    """Refonte complète : le nouveau spec doit gagner, et l'ancien ne doit rien laisser."""
    scenario = Scenario("refonte", "Refonte complète vers un style éditorial sombre (nouveau DesignSpec).")
    try:
        old_spec = DesignSpec.model_validate(SPECS["restaurant"])
        new_spec = DesignSpec.model_validate(REDESIGN_SPEC)

        before_version = client.get_session(session_id)["versions"][-1]
        response, _ = client.edit(
            session_id,
            "Je veux changer complètement le design : ambiance sombre, éditoriale, typographie serif.",
            mode="redesign",
            design_spec=REDESIGN_SPEC,
        )
        if response.status_code >= 400:
            scenario.error = (
                f"HTTP {response.status_code}: {response.text[:200]} "
                "(la refonte avec design_spec n'est pas supportée)"
            )
            return scenario

        after_version = client.get_session(session_id)["versions"][-1]
        scenario.add("nouvelle version créée", after_version != before_version, f"{before_version} → {after_version}")
        after = client.load_version(slug, int(after_version.lstrip("v")))
        css = after.css.lower()

        applied = [c for c in (new_spec.palette.primary, new_spec.palette.bg, new_spec.palette.text) if c.lower() in css]
        scenario.add(
            "nouvelle palette appliquée",
            len(applied) == 3,
            f"{len(applied)}/3 couleurs du nouveau spec présentes",
        )

        residual = [c for c in (old_spec.palette.primary, old_spec.palette.bg) if c.lower() in css]
        scenario.add(
            "ancienne palette évacuée",
            not residual,
            f"résidus : {', '.join(residual)}" if residual else "aucun résidu de l'ancienne palette",
        )

        missing = {s.id for s in new_spec.sections} - section_ids(after.html)
        scenario.add(
            "sections du nouveau spec présentes",
            not missing,
            f"manquantes : {', '.join(sorted(missing))}" if missing else "toutes présentes",
        )
    except Exception as exc:  # noqa: BLE001
        scenario.error = f"{type(exc).__name__}: {exc}"
    return scenario


def scenario_preview_isolation(client: EvalClient, session_id: str, slug: str) -> Scenario:
    """Un site déjà en ligne ne doit pas bouger tant que l'utilisateur n'a pas publié."""
    scenario = Scenario(
        "cycle/preview",
        "Après une édition, le site en ligne reste inchangé jusqu'à publication explicite.",
    )
    try:
        live_before = client.fetch_live(slug)
        scenario.add("site publié au départ", live_before is not None, "live servi" if live_before else "rien en live")

        response, _ = client.edit(session_id, "Ajoute une phrase de bienvenue dans le hero.")
        if response.status_code >= 400:
            scenario.error = f"HTTP {response.status_code}: {response.text[:200]}"
            return scenario

        live_after = client.fetch_live(slug)
        unchanged = live_before == live_after
        scenario.add(
            "live inchangé après édition",
            unchanged,
            "le live a été écrasé sans publication explicite" if not unchanged else "live préservé",
        )

        version = client.get_session(session_id)["versions"][-1]
        preview = client._client.get(f"/sites/{slug}/{version}/index.html")  # noqa: SLF001 - lecture statique
        scenario.add("preview de la nouvelle version servie", preview.status_code == 200, f"HTTP {preview.status_code}")
    except Exception as exc:  # noqa: BLE001
        scenario.error = f"{type(exc).__name__}: {exc}"
    return scenario


def scenario_rollback(client: EvalClient, session_id: str, slug: str) -> Scenario:
    """Revenir à une version antérieure, alors que toutes sont sur disque."""
    scenario = Scenario("cycle/rollback", "Republier la v1 après des versions plus récentes.")
    try:
        v1 = client.load_version(slug, 1)
        response = client.publish(session_id, version=1)
        if response.status_code >= 400:
            scenario.error = (
                f"HTTP {response.status_code}: {response.text[:160]} "
                "(pas d'endpoint de publication par version)"
            )
            return scenario
        live = client.fetch_live(slug)
        scenario.add("live revenu sur la v1", live == v1.html, "contenu identique à v1" if live == v1.html else "contenu différent de v1")
    except Exception as exc:  # noqa: BLE001
        scenario.error = f"{type(exc).__name__}: {exc}"
    return scenario


def scenario_publish_gate(client: EvalClient, session_id: str, slug: str) -> Scenario:
    """Publier une version au verdict `fail` doit demander une confirmation explicite."""
    scenario = Scenario("cycle/garde-fou", "Une version au verdict `fail` n'est pas publiable sans force.")
    try:
        session = client.get_session(session_id)
        report = session.get("report") or {}
        verdict = report.get("verdict")
        if verdict != "fail":
            scenario.add(
                "cas applicable",
                True,
                f"verdict courant « {verdict} » : garde-fou non sollicité sur ce run",
            )
            return scenario
        response = client.publish(session_id)
        scenario.add("publication refusée sans force", response.status_code == 409, f"HTTP {response.status_code}")
        forced = client.publish(session_id, force=True)
        scenario.add("publication forcée acceptée", forced.status_code < 400, f"HTTP {forced.status_code}")
    except Exception as exc:  # noqa: BLE001
        scenario.error = f"{type(exc).__name__}: {exc}"
    return scenario


# --------------------------------------------------------------------------- #
# Campagne
# --------------------------------------------------------------------------- #
def render_markdown(scenarios: list[Scenario], label: str) -> str:
    passed = sum(1 for s in scenarios if s.passed)
    lines = [
        f"# Intégration des modifications — {label}",
        "",
        f"**{passed}/{len(scenarios)} scénarios réussis.**",
        "",
        "| Scénario | État | Détail |",
        "| --- | --- | --- |",
    ]
    for s in scenarios:
        if s.error:
            lines.append(f"| `{s.name}` | ⛔ | {s.error} |")
            continue
        failed = [c for c in s.checks if not c.passed]
        detail = "; ".join(f"{c.name} — {c.detail}" for c in failed) if failed else "tous les contrôles passent"
        lines.append(f"| `{s.name}` | {'✅' if s.passed else '❌'} | {detail} |")

    lines += ["", "## Détail des contrôles", ""]
    for s in scenarios:
        lines.append(f"### `{s.name}`")
        lines.append("")
        lines.append(f"_{s.description}_")
        lines.append("")
        if s.error:
            lines.append(f"- ⛔ {s.error}")
        for c in s.checks:
            lines.append(f"- {'✅' if c.passed else '❌'} **{c.name}** — {c.detail}")
        lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--label", default="")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--tweaks", type=int, default=2, help="Nombre de retouches à jouer (défaut 2)")
    args = parser.parse_args(argv)

    check_server()
    spec = SPECS["restaurant"]
    scenarios: list[Scenario] = []

    with EvalClient() as client:
        client.login()
        print("\n  Site de départ (génération + review + mise en ligne)…", flush=True)
        session = client.create_session("[eval edit] Chez Amara — restaurant africain à Lyon")
        session_id, slug = session["id"], session["slug"]
        client.agent_code(session_id, spec)
        try:
            client.agent_review(session_id, slug)
        except Exception as exc:  # noqa: BLE001 - une revue en échec ne bloque pas la mise en ligne
            print(f"  (review du site de départ en échec : {type(exc).__name__}) ", file=sys.stderr)
        client.deploy(session_id, slug)
        print(f"  Site {slug} en ligne.\n")

        for name, instruction, applied in TWEAKS[: args.tweaks]:
            print(f"  Retouche « {name} »…", flush=True)
            scenarios.append(scenario_tweak(client, session_id, slug, name, instruction, applied))

        print("  Isolation de la preview…", flush=True)
        scenarios.append(scenario_preview_isolation(client, session_id, slug))

        print("  Refonte complète…", flush=True)
        scenarios.append(scenario_redesign(client, session_id, slug))

        print("  Retour arrière…", flush=True)
        scenarios.append(scenario_rollback(client, session_id, slug))

        print("  Garde-fou de publication…", flush=True)
        scenarios.append(scenario_publish_gate(client, session_id, slug))

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    label = args.label or stamp
    args.out.mkdir(parents=True, exist_ok=True)
    report = args.out / f"edition-{label}.md"
    report.write_text(render_markdown(scenarios, label), encoding="utf-8")

    print()
    for s in scenarios:
        mark = "⛔" if s.error else ("✅" if s.passed else "❌")
        print(f"  {mark} {s.name}")
        for c in s.checks:
            if not c.passed:
                print(f"       ↳ {c.name} : {c.detail}")
        if s.error:
            print(f"       ↳ {s.error}")
    print(f"\n  Rapport : {report}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
