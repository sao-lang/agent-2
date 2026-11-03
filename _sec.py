import re
for f in ["05-用pydantic定义输出结构.md","07-最小循环与三种终止.md","08-循环的四种失控.md"]:
    t=open(f,encoding="utf-8").read()
    # print sections 八 onwards raw text with lengths
    parts = re.split(r"^## ", t, flags=re.M)
    print("="*20, f)
    for p in parts[1:]:
        title = p.split("\n",1)[0]
        body = p.split("\n",1)[1] if "\n" in p else ""
        body_nc = re.sub(r"```.*?```","",body,flags=re.S)
        print(f"  {len(re.sub(chr(92)+'s','',body_nc)):6d}  {title}")
