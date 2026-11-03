import re, glob, collections
files = sorted(f for f in glob.glob("*.md") if re.match(r"^\d\d-", f))[:12]
for f in files:
    t = open(f, encoding="utf-8").read()
    # strip code blocks
    t2 = re.sub(r"```.*?```", "", t, flags=re.S)
    sents = [s.strip() for s in re.split(r"[。！？\n]", t2) if len(s.strip())>=12]
    c = collections.Counter(sents)
    dups = {k:v for k,v in c.items() if v>1}
    print(f"--- {f}  重复句 {len(dups)}")
    for k,v in list(dups.items())[:12]:
        print(f"   x{v}  {k[:60]}")
