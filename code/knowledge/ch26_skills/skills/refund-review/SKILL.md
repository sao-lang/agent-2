---
name: refund-review
description: 处理电商退货审查，判断某笔订单是否符合退货条件。当用户询问订单能否退货、需要核对签收天数与政策窗口、或要求给出退货结论时使用。需要订单号；缺订单号时先索取。
---

# 退货审查

## 步骤

1. 取订单签收天数：调 `order__get_order`，读 `signed_days_ago`。
2. 取政策窗口：调 `order__get_policy`，读 `window_days`。
3. 判定：`signed_days_ago <= window_days` 则可退，否则不可退。
4. 组织回复：用 `templates/reply.md`，结论在前、依据在后。
5. 交付前校验：跑 `scripts/check.py`，确认结论与两个数字一致。

## 判定规则

- 签收天数按自然日算，签收当天记为第 0 天。
- 窗口以政策返回的 `window_days` 为准，不在正文里写死 7 天。
- 两者相等算可退（第 7 天当天仍可退）。
- 缺 `signed_days_ago` 时不得推断，先向用户要订单号。

## 资料

- `references/policy.md`：退货政策完整条款（第 3 步判定前必读）。
- `references/exception.md`：例外情形（定制商品、预售、生鲜时读）。

## 脚本

- `scripts/check.py`：校验结论与两个数字是否一致。
- `tests/test_check.py`：上面这个脚本的离线单测，改脚本后先跑它。

## 边界

- 只处理退货。换货、维修、发票重开、物流查询不属于本流程。
- 只回答"某笔订单能不能退"。政策条文本身怎么规定，走检索，不激活本流程。
- 退款到账时间不属于本流程，转财务。
