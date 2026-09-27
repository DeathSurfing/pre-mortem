"""Pre-record / pre-deploy smoke test. One command, clear pass/fail.

Tests the BUSINESS red-flagger, which is what ships and what the demo shows. Free by default: it drives the
streaming endpoint and checks the event sequence, and the verdict path uses no LLM.

  python api/scripts/smoke.py --url http://localhost:8000
  python api/scripts/smoke.py --url https://premortem-api.lexcontra.com --deep

--deep additionally exercises the seeded bank contents and the ledger. Both modes cost nothing extra
beyond the prose calls the stream itself makes.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

RESULTS: list[tuple[str, bool, str]] = []

# A real User-Agent is required: Cloudflare in front of the deployed API returns 403 for python-urllib's
# default UA even though the service itself is healthy.
UA = "pre-mortem-smoke/1.0"


def check(name: str, cond: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(cond), detail))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def get(url: str, timeout: int = 120):
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


def stream_events(base: str, preset: str, timeout: int = 300) -> list[dict]:
    """Drive the SSE endpoint and return the parsed events."""
    url = f"{base}/api/biz/redflag/stream?preset={preset}"
    req = urllib.request.Request(url, headers={"user-agent": UA, "accept": "text/event-stream"})
    events: list[dict] = []
    with urllib.request.urlopen(req, timeout=timeout) as r:
        for raw in r:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                events.append(json.loads(line[5:].strip()))
            except Exception:  # noqa: BLE001
                pass
    return events


def by_type(events: list[dict], kind: str) -> list[dict]:
    return [e for e in events if e.get("type") == kind]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://localhost:8000")
    ap.add_argument("--deep", action="store_true", help="also check bank contents and the ledger")
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
    laya = h.get("laya") or {}
    check("laya enabled", bool(laya.get("enabled")), json.dumps(laya)[:120])
    check("laya loaded (or loads on first use)", laya.get("error") is None, str(laya.get("error")))

    # /health is liveness and deliberately answers from local state only, so Hindsight reachability moved to
    # /health/deep when a slow dependency was found to be marking the container unhealthy and having Traefik
    # withdraw the route. Assert the split explicitly, so a future edit cannot quietly put a network call back
    # into the healthcheck path.
    check("liveness makes no remote call", "features" not in h and "documents" not in h,
          f"unexpected networked keys: {sorted(set(h) & {'features', 'documents'})}")
    check("liveness names the business bank", h.get("bank_id") == "bizdecisions", str(h.get("bank_id")))

    deep = get(f"{base}/health/deep")
    check("hindsight api reachable", bool((deep.get("features") or {}).get("api_version")),
          str((deep.get("features") or {}).get("api_version")))
    check("deep health lists bank documents", len(deep.get("documents") or []) > 0,
          str(len(deep.get("documents") or [])))
    check("models configured", bool((h.get("models") or {}).get("llm")), str(h.get("models")))

    print("== 2. prompts available ==")
    try:
        prompts = get(f"{base}/api/biz/prompts")
        keys = {p["key"] for p in prompts}
        # every preset the corpus defines must be exposed AND resolvable. Assert the required ones are
        # present rather than an exact set, so adding a preset (D, E, ...) does not fail the gate.
        check("all presets exposed", {"A", "B", "C", "D", "E"} <= keys, str(sorted(keys)))
    except Exception as e:  # noqa: BLE001
        check("prompts reachable", False, str(e))

    print("== 3. streaming pipeline, per preset ==")
    expected = {
        "A": ("high", "pricing"),
        "B": ("high", "hiring"),
        "C": ("unknown", "expansion"),
    }
    for key, (want_risk, want_domain) in expected.items():
        try:
            ev = stream_events(base, key)
        except Exception as e:  # noqa: BLE001
            check(f"preset {key} stream", False, f"{type(e).__name__}: {e}")
            continue

        order = [e["type"] for e in ev if e.get("type") != "delta"]
        check(f"preset {key} streamed events", len(ev) > 0, f"{len(ev)} events")
        check(f"preset {key} reached done", bool(by_type(ev, "done")), str(order[:9]))
        check(f"preset {key} emitted deltas", len(by_type(ev, "delta")) > 0,
              f"{len(by_type(ev, 'delta'))} deltas")

        cls = (by_type(ev, "classify") or [{}])[0]
        check(f"preset {key} classified as {want_domain}", cls.get("domain") == want_domain,
              f"got {cls.get('domain')}/{cls.get('decision_type')}")
        check(f"preset {key} has laya signals", bool(cls.get("laya")),
              json.dumps(cls.get("laya"))[:110])

        vd = (by_type(ev, "verdict") or [{}])[0]
        check(f"preset {key} risk is {want_risk}", vd.get("risk") == want_risk,
              f"got {vd.get('risk')} conf {vd.get('confidence')}")

        pr = (by_type(ev, "precedents") or [{}])[0]
        precs = pr.get("precedents") or []
        ids = [p.get("launch_id") for p in precs]
        check(f"preset {key} precedents unique", len(ids) == len(set(ids)), str(ids))
        check(f"preset {key} every precedent has an id", all(ids), str(ids))
        if key == "C":
            check("preset C refuses (no precedent)", vd.get("no_precedent") is True, str(vd.get("risk")))
            check("preset C lists declined neighbours", len(pr.get("declined") or []) > 0,
                  f"{len(pr.get('declined') or [])} declined")
        else:
            check(f"preset {key} cites precedents in prose",
                  bool((by_type(ev, "done") or [{}])[0].get("citations_in_prose")),
                  str((by_type(ev, "done") or [{}])[0].get("citations_in_prose")))
            check(f"preset {key} no unverified attributions",
                  not ((by_type(ev, "done") or [{}])[0].get("attribution_unverified")),
                  str((by_type(ev, "done") or [{}])[0].get("attribution_unverified")))

    print("== 4. no-lookahead is enforced in code, not claimed ==")
    try:
        gt = get(f"{base}/api/biz/ground-truth")
        t = gt.get("totals") or {}
        check("ground truth available", (t.get("decisions") or 0) > 0, json.dumps(t))
        check("derivable coverage in (0,1)", 0 < (t.get("derivable_coverage") or 0) < 1,
              str(t.get("derivable_coverage")))
    except Exception as e:  # noqa: BLE001
        check("ground truth reachable", False, str(e))

    if args.deep:
        print("== 5. bank contents and ledger (deep) ==")
        try:
            b = get(f"{base}/api/biz/bank")
            st = b.get("stats") or {}
            check("bank has documents", (st.get("total_documents") or 0) >= 36, str(st.get("total_documents")))
            check("observations consolidated", (st.get("total_observations") or 0) > 0,
                  f"observations={st.get('total_observations')} pending={st.get('pending_consolidation')}")
            cfg = (b.get("config") or {}).get("config") or {}
            check("disposition is the skeptic profile",
                  cfg.get("disposition_literalism") == 5 and cfg.get("disposition_skepticism") == 4,
                  json.dumps({k: v for k, v in cfg.items() if "disposition" in k}))
            check("directives present", len(b.get("directives") or []) >= 5, str(len(b.get("directives") or [])))
        except Exception as e:  # noqa: BLE001
            check("bank readable", False, str(e))

        try:
            led = get(f"{base}/api/biz/ledger")
            check("ledger has flags", (led.get("flags") or 0) > 0,
                  json.dumps({k: led.get(k) for k in ("flags", "ignored", "costed")}))
            check("ledger promotes classes", bool(led.get("promoted_classes")), str(led.get("promoted_classes")))
            check("ledger is not double-counting", (led.get("flags") or 0) <= 10,
                  f"flags={led.get('flags')} (5 seeded; more means duplicate ingestion)")
        except Exception as e:  # noqa: BLE001
            check("ledger readable", False, str(e))

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
