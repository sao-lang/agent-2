from src.calc import average


def summarize(rows):
    return f"平均 {average([r['value'] for r in rows]):.2f}"
