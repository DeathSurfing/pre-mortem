import re
t = open("/opt/data/pre-mortem/probe_free_out.txt").read()
keep = []
for l in t.splitlines():
    s = l.strip()
    if not s or "PydanticDeprecated" in l or s.startswith("warnings.warn") or s.startswith("File \"") or s.startswith("^"):
        continue
    if s.startswith("print(") or s.startswith("'") and s.endswith("'"):
        continue
    keep.append(s[:150])
open("/opt/data/pre-mortem/probe_free_clean.txt", "w").write("\n".join(keep))
print("KEPT", len(keep))
