import re, sys
t = open(sys.argv[1] if len(sys.argv) > 1 else "/tmp/seed3.txt").read()
keep = []
for l in t.splitlines():
    s = l.strip()
    if re.match(r"^\[(PASS|FAIL)\]", s) or "checks passed" in s or s.startswith("FAILED:") or s.startswith("EXIT=") \
       or "totals:" in s or s.startswith("stats:") or "deleted" in s or s.startswith("==") or "directive" in s.lower():
        keep.append(s[:180])
open("/tmp/summary.txt", "w").write("\n".join(keep))
print(len(keep), "lines -> /tmp/summary.txt")
