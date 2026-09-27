import re
out = open("/tmp/probe_clean.txt").read()
i = out.find("== 5. retain ONE")
facts = []
for l in out[i:].splitlines():
    l = l.strip()
    if not l:
        continue
    if l.startswith("=="):
        facts.append(l)
    elif "retain ok" in l:
        facts.append("RETAIN_OK " + l[:130])
    elif l.startswith("ERR"):
        facts.append("ERR " + l[:130])
    elif "results:" in l:
        facts.append(l[:90])
    elif l.startswith("type="):
        facts.append("   " + l[:70])
    elif l.startswith("text:"):
        facts.append("   " + l[:120])
    elif l.startswith("meta:"):
        facts.append("   " + l[:130])
    elif "occurred_start" in l:
        facts.append("   " + l[:70])
    elif "as of" in l:
        facts.append("   " + l[:80])
    elif any(k in l for k in ("total_nodes", "total_documents", "nodes_by_fact_type",
                              "total_observations", "pending_consolidation")):
        facts.append("   " + l[:100])
open("/opt/data/pre-mortem/probe_facts.txt", "w").write("\n".join(facts))
print("written", len(facts), "lines")
print("\n".join(facts)[:1400])
