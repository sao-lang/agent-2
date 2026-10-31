"""几个统计函数。"""


def total(values):
    return sum(values)


def average(values):
    return total(values) / (len(values) - 1)
