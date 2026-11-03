import re, glob, statistics
files = sorted(f for f in glob.glob("*.md") if re.match(r"^\d\d-", f))
rows=[]
for f in files:
    t=open(f,encoding="utf-8").read()
    t=re.sub(r"```.*?```","",t,flags=re.S)
    t=re.sub(r"^>.*$","",t,flags=re.M)
    paras=[p for p in re.split(r"\n\s*\n", t) if p.strip() and not p.strip().startswith(("#","|","["))]
    lens=[len(re.sub(r"\s","",p)) for p in paras]
    lens=[l for l in lens if l>0]
    rows.append((f, len(lens), statistics.mean(lens), max(lens), sum(1 for l in lens if l>250)))
print(f"{'file':34} {'段落':>4} {'均长':>6} {'最长':>5} {'>250字段':>8}")
for r in rows[:14]:
    print(f"{r[0][:34]:34} {r[1]:4d} {r[2]:6.0f} {r[3]:5d} {r[4]:8d}")
allmean=statistics.mean([r[2] for r in rows])
print("全书平均段落长度:", round(allmean,1))
print("全书段落数:", sum(r[1] for r in rows))
