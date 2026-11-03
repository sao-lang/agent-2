import re, glob
files = sorted(f for f in glob.glob("*.md") if re.match(r"^\d\d-", f))
pat=re.compile(r"^## (.*(结语|下一步|再进一步|小结|总结|的位置|的落点|的边界|的成本|术语|练习|常见问题|怎么读|约定|读前|最后一句|读完).*)$", re.M)
hits=[]
for f in files:
    t=open(f,encoding="utf-8").read()
    for m in pat.finditer(t):
        hits.append((f, m.group(1)))
print("命中", len(hits), "个小节标题：")
for f,h in hits: print(f"  {f[:30]:30} {h}")
