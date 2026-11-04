import re, glob
files = sorted(f for f in glob.glob("*.md") if re.match(r"^\d\d-", f))[:12]
for f in files:
    t = open(f, encoding="utf-8").read()
    heads = re.findall(r"^## (.+)$", t, re.M)
    print(f"--- {f}  ({len(heads)} H2)")
    print("   " + " | ".join(h.strip() for h in heads))
