import re, glob, os
files = sorted(glob.glob("*.md"))
files = [f for f in files if re.match(r"^\d\d-", f)][:12]
print(f"{'file':38} {'total':>7} {'prose':>7} {'code':>7} {'table':>7} {'h2':>3} {'h3':>3} {'codeblk':>7}")
for f in files:
    t = open(f, encoding="utf-8").read()
    code = "\n".join(re.findall(r"```.*?```", t, re.S))
    tbl = "\n".join(re.findall(r"^\|.*$", t, re.M))
    total = len(re.sub(r"\s", "", t))
    prose = len(re.sub(r"\s", "", t)) - len(re.sub(r"\s","",code)) - len(re.sub(r"\s","",tbl))
    h2 = len(re.findall(r"^## ", t, re.M)); h3 = len(re.findall(r"^### ", t, re.M))
    cb = len(re.findall(r"```", t))//2
    print(f"{f[:38]:38} {total:7d} {prose:7d} {len(re.sub(r'\s','',code)):7d} {len(re.sub(r'\s','',tbl)):7d} {h2:3d} {h3:3d} {cb:7d}")
