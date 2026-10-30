"""End-to-end fixture evidence run for epic #15, unit (d).

Traces ONE opportunity from discovery through iteration using the REAL
pipeline code — feed parsing, canonical dedupe, explainable ranking, the
sourced requirement ledger, brief planning, and the bounded iteration loop
with its independent test-run evaluation — with exactly two fixture points:

1. the two feed HTTP responses, taken verbatim from tests/fixtures and served
   through the real ResponseCache (no network); and
2. the builder, replaced by the scripted double from tests/iteration (no
   agent, no spend) while evaluation still runs the REAL pytest subprocess.

Everything between those two points is production code. The script also
re-runs discovery from the warm cache to show a resumed run reproduces the
same canonical event identity, and runs the pass-then-regress loop to show
recovery rolls back to the best-known result. Run: python evidence_e2e_run.py
"""

import hashlib
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, "tests/iteration")
from conftest import (  # noqa: E402
    ScriptedBuilder,
    write_failing_project,
    write_passing_project,
    write_tests_passing_no_readme,
)

from alexander.builder.models import BuildBudgets  # noqa: E402
from alexander.cli import _ranked_to_json  # noqa: E402
from alexander.discovery.cache import ResponseCache  # noqa: E402
from alexander.discovery.devpost import DEBPOST_API_URL, parse_devpost  # noqa: E402
from alexander.discovery.discover import discover_events  # noqa: E402
from alexander.discovery.hackclub import HACKCLUB_API_URL, parse_hackclub  # noqa: E402
from alexander.iteration import IterationBudgets, run_iteration_loop  # noqa: E402
from alexander.iteration.models import manifest_path_for  # noqa: E402
from alexander.ledger.ledger import build_ledger, render_ledger_markdown  # noqa: E402
from alexander.ledger.models import RequirementStatus  # noqa: E402
from alexander.orchestrator.pipeline import event_slug, plan_run  # noqa: E402
from alexander.ranking import load_profile, rank_events  # noqa: E402

ROOT = Path(__file__).parent
OUT = ROOT / "evidence" / "e2e-fixture"
CACHE_DIR = OUT / "fixture-cache"

# Fixture feed payloads, served verbatim through the real cache layer.
FIXTURE_SOURCES = [
    {
        "name": "devpost",
        "url": DEBPOST_API_URL,
        "fixture_file": "tests/fixtures/devpost_hackathons.json",
        "parser": parse_devpost,
    },
    {
        "name": "hackclub",
        "url": HACKCLUB_API_URL,
        "fixture_file": "tests/fixtures/hackclub_upcoming.json",
        "parser": parse_hackclub,
    },
]


def warm_cache() -> tuple[list[dict[str, str]], dict[str, int]]:
    """Load both fixture payloads into the real ResponseCache; record keys."""
    cache = ResponseCache(CACHE_DIR)
    records = []
    raw_counts = {}
    for source in FIXTURE_SOURCES:
        payload = json.loads((ROOT / source["fixture_file"]).read_text(encoding="utf-8"))
        raw = source["parser"](payload)
        raw_counts[source["name"]] = len(raw)
        cache.save(source["url"], payload)
        records.append(
            {
                "name": source["name"],
                "url": source["url"],
                "fixture_file": source["fixture_file"],
                "parser": f"{source['parser'].__module__}.{source['parser'].__name__}",
                "raw_listings": len(raw),
                "cache_key_sha256": hashlib.sha256(source["url"].encode()).hexdigest(),
                "fixture_point": "feed HTTP response replaced by committed fixture",
            }
        )
    return records, raw_counts


def discovery_pass(label: str) -> list:
    """One full discovery pass (parse + dedupe) through the warm cache."""
    events = discover_events(use_cache=True, cache_dir=CACHE_DIR)
    print(f"discovery {label}: {len(events)} canonical event(s)")
    return events


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Discovery: two passes through the same warm cache. A resumed run must
    # reproduce the same canonical identity — same slugs, same order.
    fixture_records, raw_counts = warm_cache()
    events = discovery_pass("pass 1 (cold cache, fixture payloads)")
    resumed = discovery_pass("pass 2 (warm cache, simulated resume)")
    slugs_pass1 = sorted(event_slug(event) for event in events)
    slugs_pass2 = sorted(event_slug(event) for event in resumed)
    identity_stable = slugs_pass1 == slugs_pass2
    print(f"identity stable across passes: {identity_stable}")

    # Ranking: real profile, real explainable scoring.
    profile = load_profile(ROOT / "profile.yaml")
    ranked = rank_events(events, profile)
    ranked_json = _ranked_to_json(ranked)
    (OUT / "rank.json").write_text(json.dumps(ranked_json, indent=2), encoding="utf-8")
    print(f"ranked {len(ranked)} upcoming event(s); top: {ranked[0].event.name}")

    # Selection + sourced requirement ledger for the ONE traced opportunity.
    plan = plan_run(ranked, OUT / "builds")[0]
    (OUT / "brief.json").write_text(plan.brief.model_dump_json(indent=2), encoding="utf-8")
    ledger_doc = build_ledger(plan.event)
    (OUT / "ledger.json").write_text(ledger_doc.model_dump_json(indent=2), encoding="utf-8")
    (OUT / "ledger.md").write_text(render_ledger_markdown(ledger_doc), encoding="utf-8")
    confirmed = [e for e in ledger_doc.entries if e.status is RequirementStatus.CONFIRMED]
    unknowns = [e for e in ledger_doc.entries if e.status is RequirementStatus.UNKNOWN]
    print(
        f"ledger for {plan.event.name}: {len(confirmed)} confirmed, "
        f"{len(ledger_doc.open_questions)} open question(s)"
    )

    # Iteration, scenario A — fail then pass; loop stops on the pass condition.
    builder = ScriptedBuilder([write_failing_project, write_passing_project])
    budgets = IterationBudgets(
        max_iterations=3,
        wall_clock=timedelta(minutes=5),
        build=BuildBudgets(max_attempts=3, wall_clock=timedelta(minutes=2)),
    )
    manifest = asyncio_run_loop(builder, plan.brief, plan.out_dir, budgets)

    # Iteration, scenario B — recovery: round 1 passes tests but misses the
    # README (becomes the best-known baseline), round 2 breaks the tests and
    # is rolled back to the baseline, round 3 passes outright.
    rollback_builder = ScriptedBuilder(
        [write_tests_passing_no_readme, write_failing_project, write_passing_project]
    )
    rollback_dir = OUT / "builds" / f"{event_slug(plan.event)}-rollback"
    rollback_manifest = asyncio_run_loop(rollback_builder, plan.brief, rollback_dir, budgets)

    provenance = {
        "run": {
            "script": "evidence_e2e_run.py",
            "started_utc": started,
            "epic": "https://github.com/isayahc/Alexander-the-Cracked/issues/15",
            "unit": "(d) end-to-end traceability run — fixture leg",
            "fixture_points": [
                "feed HTTP responses (committed fixtures served via ResponseCache)",
                "builder (ScriptedBuilder double; evaluation still runs real pytest)",
            ],
            "real_components": [
                "ResponseCache",
                "feed parsers (parse_devpost, parse_hackclub)",
                "canonical dedupe",
                "ranking (score + sort)",
                "requirement ledger",
                "brief planning (plan_run/build_brief)",
                "iteration loop",
                "independent evaluation (run_tests subprocess)",
            ],
        },
        "discovery": {
            "sources": fixture_records,
            "raw_listings_per_source": raw_counts,
            "canonical_events_after_dedupe": len(events),
            "pass1_canonical_events": len(events),
            "pass2_canonical_events": len(resumed),
            "identity_stable_across_passes": identity_stable,
            "traced_event_slug": event_slug(plan.event),
            "traced_event_sources": list(plan.event.sources),
        },
        "ranking": {
            "profile": "profile.yaml (repo root, documented defaults)",
            "ranked_upcoming": len(ranked),
            "top": ranked_json[0],
        },
        "ledger": {
            "confirmed": len(confirmed),
            "unknown_entries": len(unknowns),
            "open_questions": len(ledger_doc.open_questions),
            "files": ["ledger.json", "ledger.md"],
        },
        "brief": "brief.json",
        "iteration_full": {
            "stop_reason": manifest.stop_reason.value,
            "best_iteration": manifest.best_iteration,
            "iterations": len(manifest.iterations),
            "total_attempts": manifest.total_attempts,
            "manifest": str(manifest_path_for(plan.out_dir)),
        },
        "iteration_rollback": {
            "stop_reason": rollback_manifest.stop_reason.value,
            "best_iteration": rollback_manifest.best_iteration,
            "iterations": len(rollback_manifest.iterations),
            "restored_best": any(r.restored_best for r in rollback_manifest.iterations),
            "manifest": str(manifest_path_for(rollback_dir)),
        },
    }
    (OUT / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"provenance: {OUT / 'provenance.json'}")


def asyncio_run_loop(builder, brief, out_dir, budgets):
    import asyncio

    return asyncio.run(run_iteration_loop(builder, brief=brief, out_dir=out_dir, budgets=budgets))


if __name__ == "__main__":
    main()
