import re, glob
files = sorted(f for f in glob.glob("*.md") if re.match(r"^\d\d-", f))
small_words = ("结语","下一步","再进一步","的位置","的落点","的边界","的成本","小结","总结","后记","附录","读前","练习","术语","常见问题","不写什么","怎么读","约定","最后一句","读完")
tot_tail=0; tot=0
print(f"{'file':40} {'prose':>6} {'tail':>5} {'n<400':>5}  小标题")
for f in files:
    t=open(f,encoding="utf-8").read()
    parts = re.split(r"^## ", t, flags=re.M)[1:]
    secs=[]
    for p in parts:
        title=p.split("\n",1)[0]
        body=p.split("\n",1)[1] if "\n" in p else ""
        body=re.sub(r"```.*?```","",body,flags=re.S)
        secs.append((title, len(re.sub(r"\s","",body))))
    prose=sum(n for _,n in secs)
    # tail = maximal suffix of sections that are small OR match small_words, starting after last big section
    idx=len(secs)
    for i in range(len(secs)-1,-1,-1):
        title,n=secs[i]
        if n<450 and not title.startswith("目录"):
            idx=i
        else:
            break
    # extend upward over matching titles with small size
    tail=sum(n for _,n in secs[idx:])
    names=[t_ for t_,_ in secs[idx:]]
    tot_tail+=tail; tot+=prose
    print(f"{f[:40]:40} {prose:6d} {tail:5d} {len(names):5d}  {'/'.join(names)[:70]}")
print(f"\n合计 prose={tot}  tail={tot_tail}  占比={tot_tail/tot:.1%}")
