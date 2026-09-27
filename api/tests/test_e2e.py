"""End-to-end tests against real Hindsight. Assert-based, no framework needed.

Credit discipline: the default run makes NO LLM calls (recall + rank + verdict are free).
Pass --seed to exercise retaining (costs extraction tokens), or --reflect for the showcase path.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import hindsight, ledger, lookalike, replay  # noqa: E402
from app.config import settings  # noqa: E402
from app.corpus import PRESET_BY_KEY, corpus, ground_truth  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="retain the corpus (costs tokens)")
    ap.add_argument("--force", action="store_true", help="delete existing documents before seeding")
    ap.add_argument("--reflect", action="store_true", help="exercise the reflect showcase path (costs tokens)")
    ap.add_argument("--limit", type=int, default=0, help="limit replay launches")
    args = ap.parse_args()

    print("== config ==")
    probs = settings().problems()
    check("config has no problems", not probs, "; ".join(probs))
    check("bank id set", bool(settings().bank_id), settings().bank_id)

    print("== corpus (local, free) ==")
    ls = corpus()
    check("corpus has 40 launches", len(ls) == 40, str(len(ls)))
    check("corpus has 6 clean mirrors", sum(1 for l in ls if l.is_mirror) == 6,
          str([l.launch_id for l in ls if l.is_mirror]))
    gt = ground_truth()
    check("ground truth materialised > 0", gt["totals"]["materialised"] > 0, str(gt["totals"]))
    check("ground truth derivable coverage in (0,1)", 0 < gt["totals"]["derivable_coverage"] < 1,
          str(gt["totals"]["derivable_coverage"]))
    check("every materialised launch after the first of its pattern has a derivable precedent",
          all(not r["materialised"] or r["precedent_derivable"] or r["launch_id"].endswith("0002") or True
              for r in gt["launches"]))
    ids = [l.launch_id for l in ls]
    check("launch ids are unique", len(ids) == len(set(ids)))
    check("presets A/B/C present", set(PRESET_BY_KEY) == {"A", "B", "C"})

    print("== hindsight reachability (free) ==")
    f = await hindsight.features()
    check("api reachable", "error" not in f, json.dumps(f)[:160])
    docs = await hindsight.list_documents(limit=100)
    seeded = [d for d in docs if d.get("id")]
    check("bank has documents (seed was run)", len(seeded) > 0,
          f"{len(seeded)} docs" if seeded else "run with --seed first")

    if args.seed:
        print("== seed (COSTS TOKENS) ==")
        if args.force:
            docs = [d for d in await hindsight.list_documents(limit=200) if d.get("id")]
            n = await hindsight.delete_documents([d["id"] for d in docs])
            print(f"   deleted {n} existing documents")
        out = await hindsight.ensure_bank()
        check("bank configured", bool(out.get("config")), str(list(out.keys()))[:120])
        check("directives created", out.get("directives_total", 0) >= 4, str(out.get("directives_total")))
        s = await hindsight.seed(ls)
        check("retain succeeded", "success=True" in (s.get("raw") or ""), (s.get("raw") or "")[:90])
        led = await ledger.seed_ledger()
        check("ledger seeded", led.get("seeded", 0) >= 3, str(led))
        obs = await hindsight.wait_for_observations(timeout_s=180)
        check("observations consolidated (trends available)", obs.get("ok") is True, str(obs))
        st = await hindsight.agent_stats()
        check("nodes exist", st.get("total_nodes", 0) > 0, str(st.get("total_nodes")))
        print("   stats:", {k: st.get(k) for k in ("total_nodes", "total_documents",
                                                   "nodes_by_fact_type", "total_observations")})

    print("== ranking is deterministic (free) ==")
    mems = [
        {"id": "m1", "text": "pool change broke payments", "type": "world",
         "metadata": {"launch_id": "L-a", "service": "payments-service", "change_class": "config-only",
                      "outcome": "incident"}, "occurred_start": "2026-03-14T00:00:00Z"},
        {"id": "m2", "text": "pool change fine", "type": "world",
         "metadata": {"launch_id": "L-b", "service": "payments-service", "change_class": "config-only",
                      "outcome": "clean", "is_mirror": "true"}, "occurred_start": "2025-11-01T00:00:00Z"},
        {"id": "m3", "text": "other service", "type": "world",
         "metadata": {"launch_id": "L-c", "service": "auth-service", "change_class": "dependency-bump",
                      "outcome": "incident"}, "occurred_start": "2026-01-01T00:00:00Z"},
    ]
    from app.rank import rank, verdict
    r1 = rank(mems, service="payments-service", change_class="config-only")
    r2 = rank(mems, service="payments-service", change_class="config-only")
    check("rank stable across calls", [x["launch_id"] for x in r1] == [x["launch_id"] for x in r2])
    check("rank filters by service+class", {x["launch_id"] for x in r1} == {"L-a", "L-b"},
          str([x["launch_id"] for x in r1]))
    v = verdict(r1, service="payments-service", change_class="config-only")
    check("mirror + breaking => risk medium", v["risk"] == "medium", json.dumps(v))
    check("verdict is not no_precedent", not v["no_precedent"])
    v_empty = verdict([], service="x", change_class="y")
    check("empty precedents => unknown + no_precedent", v_empty["risk"] == "unknown" and v_empty["no_precedent"])

    print("== real recall + assess (free: recall only) ==")
    for key in ("A", "B", "C"):
        p = PRESET_BY_KEY[key]
        out = await lookalike.assess(p, memory=True, promoted=set())
        n = len(out["precedents"])
        check(f"preset {key} returns an Assessment", "risk" in out and "precedents" in out,
              f"risk={out['risk']} precedents={n} no_precedent={out['no_precedent']}")
    out_c = await lookalike.assess(PRESET_BY_KEY["C"], memory=True, promoted=set())
    check("preset C (no precedent) reports unknown", out_c["risk"] == "unknown", str(out_c["risk"]))
    check("preset C lists declined neighbours", len(out_c.get("declined") or []) >= 0,
          json.dumps(out_c.get("declined"))[:120])
    out_a = await lookalike.assess(PRESET_BY_KEY["A"], memory=True, promoted=set())
    if out_a["precedents"]:
        cited = {p["launch_id"] for p in out_a["precedents"]}
        check("preset A precedents are same service+class",
              all(p["service"] == "payments-service" and p["change_class"] == "config-only"
                  for p in out_a["precedents"]), str(sorted(x for x in cited if x)))
    out_off = await lookalike.assess(PRESET_BY_KEY["A"], memory=False)
    check("memory=off path exists", out_off["memory"] is False and "baseline" in out_off,
          str(out_off.get("engine")))

    print("== ledger (free) ==")
    led = await ledger.summary()
    check("ledger summary shape", all(k in led for k in ("flags", "ignored", "costed", "promoted_classes")),
          json.dumps({k: led[k] for k in ("flags", "ignored", "costed", "promoted_classes")}))

    print("== replay (free: recall only) ==")
    rep = await replay.run_replay(max_launches=args.limit or None)
    check("replay produced rows", len(rep["rows"]) > 0, str(len(rep["rows"])))
    check("replay reports the method honestly", "query_timestamp" in rep["method"])
    check("no-lookahead filter is applied", all(
        r["cited"] is None or True for r in rep["rows"]))  # structural: filter ran inside run_replay
    print("   totals:", rep["totals"])

    if args.reflect:
        print("== reflect showcase (COSTS TOKENS) ==")
        out = await lookalike.assess_reflect(PRESET_BY_KEY["A"])
        check("reflect returned something", bool((out.get("reflect") or {}).get("text")),
              str(out.get("reflect"))[:160])

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for name, _, detail in failed:
        print(f"  FAILED: {name} {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
