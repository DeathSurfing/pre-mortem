"""Pre-record / pre-deploy smoke test. One command, clear pass/fail.

Free by default (no LLM calls). Add --llm to spend a few tokens on the reflect path.

  python api/scripts/smoke.py --url http://localhost:8000
  python api/scripts/smoke.py --url https://premortem-api.lexcontra.com --llm
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# A real User-Agent is required: Cloudflare in front of the deployed API returns 403 for
# python-urllib's default UA even though the service itself is healthy.
UA = "pre-mortem-smoke/1.0"


def get(url: str, timeout: int = 90):
    req = urllib.request.Request(url, headers={"user-agent": UA, "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def post(url: str, body: dict | None = None, timeout: int = 300):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"content-type": "application/json", "user-agent": UA,
                                          "accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--llm", action="store_true", help="also exercise the reflect path (costs tokens)")
    args = ap.parse_args()
    base = args.url.rstrip("/")

    print(f"== 1. health ({base}) ==")
    try:
        h = get(f"{base}/health")
    except Exception as e:  # noqa: BLE001
        check("service reachable", False, f"{type(e).__name__}: {e}")
        return 1
    check("service reachable", True)
    check("no config problems", not h.get("problems"), "; ".join(h.get("problems") or []))
    check("hindsight api reachable", bool((h.get("features") or {}).get("api_version")),
          str((h.get("features") or {}).get("api_version")))
    check("bank has the corpus", len(h.get("documents") or []) >= 40,
          f"{len(h.get('documents') or [])} docs (expected ~41: 40 launches + ledger)")
    bank = h.get("bank") or {}
    check("directives present", (bank.get("directives_total") or 0) >= 5, str(bank.get("directives_total")))
    check("corpus size matches the code", bank.get("corpus_expected") == 40, str(bank.get("corpus_expected")))
    disp = bank.get("disposition") or {}
    check("disposition is the skeptic profile", disp.get("literalism") == 5 and disp.get("skepticism") == 4,
          json.dumps(disp))

    print("== 2. observations consolidated (trends available) ==")
    try:
        st = get(f"{base}/api/bank")
        stats = st.get("stats") or {}
        check("observations exist", (stats.get("total_observations") or 0) > 0,
              f"observations={stats.get('total_observations')} pending={stats.get('pending_consolidation')}")
        check("node types include observations", "observation" in (stats.get("nodes_by_fact_type") or {}),
              json.dumps(stats.get("nodes_by_fact_type")))
    except Exception as e:  # noqa: BLE001
        check("bank stats readable", False, str(e))

    print("== 3. the three presets (free: recall only) ==")
    for k in ("A", "B", "C"):
        try:
            a = post(f"{base}/api/assess", {"preset": k, "memory": True})
            print(f"   preset {k}: risk={a.get('risk')} precedents={len(a.get('precedents') or [])} "
                  f"no_precedent={a.get('no_precedent')} flip={'yes' if a.get('flip') else 'no'} "
                  f"llm_calls={a.get('engine', {}).get('llm_calls')}")
        except Exception as e:  # noqa: BLE001
            check(f"preset {k} assess", False, str(e))
            continue
        check(f"preset {k} returns a verdict", a.get("risk") in ("high", "medium", "low", "unknown"))
        ids = [p.get("launch_id") for p in (a.get("precedents") or [])]
        check(f"preset {k} precedents are unique launches", len(ids) == len(set(ids)), str(ids))
        check(f"preset {k} every precedent carries a launch id", all(ids), str(ids))
        if k == "C":
            check("preset C is the no-precedent path", a.get("no_precedent") is True, str(a.get("risk")))
            check("preset C explains itself", bool(a.get("no_precedent_message")))
        if k == "A":
            check("preset A leads with what broke, not the clean mirror",
                  bool(a.get("precedents")) and not a["precedents"][0].get("is_mirror"),
                  str([(p.get("launch_id"), p.get("is_mirror")) for p in (a.get("precedents") or [])][:2]))
            check("preset A has the flip detail", bool(a.get("flip")), json.dumps(a.get("flip"))[:100])

    print("== 4. memory=off contrast (==")
    off = post(f"{base}/api/assess", {"preset": "A", "memory": False})
    check("memory=off returns a baseline", bool(off.get("baseline")), (off.get("baseline") or "")[:70])
    check("memory=off cites nothing", not off.get("precedents"), str(len(off.get("precedents") or [])))

    print("== 5. ledger and replay ==")
    led = get(f"{base}/api/ledger")
    check("ledger has flags", (led.get("flags") or 0) > 0, json.dumps({k: led.get(k) for k in ("flags", "ignored", "costed")}))
    check("ledger promoted at least one class", bool(led.get("promoted_classes")), str(led.get("promoted_classes")))
    try:
        rep = post(f"{base}/api/replay")
        t = rep.get("totals") or {}
        check("replay produced totals", (t.get("launches") or 0) > 0, json.dumps(t))
        check("replay gap is small (agent finds what is derivable)", (t.get("gap") or 0) <= 3, f"gap={t.get('gap')}")
        check("replay states its method honestly", "no lookahead" in (rep.get("method") or "").lower()
              or "occurred_start" in (rep.get("method") or ""), (rep.get("method") or "")[:90])
    except Exception as e:  # noqa: BLE001
        check("replay ran", False, str(e))

    if args.llm:
        print("== 6. reflect path (COSTS TOKENS) ==")
        try:
            r = post(f"{base}/api/assess", {"preset": "A", "memory": True, "engine": "reflect"})
            rt = (r.get("reflect") or {}).get("text")
            check("reflect returned text", bool(rt), (rt or "")[:110])
        except Exception as e:  # noqa: BLE001
            check("reflect ran", False, str(e))

    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    for n, _, d in failed:
        print(f"  FAILED: {n} {d}")
    return 1 if failed else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except urllib.error.URLError as e:
        print(f"could not reach the service: {e}")
        raise SystemExit(1)
