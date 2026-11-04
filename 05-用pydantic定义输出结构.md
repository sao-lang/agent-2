# 第 5 章 · 用 pydantic 定义输出结构

> **卷 1 · 一次调用（第 1–5 章）**｜[全书目录](./docs/INDEX.md#vol1)｜[本卷导读](./outline/vol01-一次调用.md)
>
> - **知识点**：A10 输出结构声明 —— 一份声明四个出口：本地校验、错误回灌、JSON Schema、配置读取（编号定义见 [知识点-A-模型层](./outline/11-知识点-A-模型层.md)）
> - **本章回答**：为什么校验必须单独成一层；一份字段表怎样同时用于本地校验、模型约束、工具参数与配置
> - **示例目录**：`code/knowledge/ch05_pydantic/`
> - **读完应当能回答**：拿到一份输出字段表，能写出可校验、可回灌、能生成 schema、能读环境变量的一份定义

---

## 目录

[手写校验的缺口](#手写校验的缺口)\
[声明一份结构](#声明一份结构)\
[校验入口与错误回灌](#校验入口与错误回灌)\
[校验开关与默认值](#校验开关与默认值)\
[字段类型的选择](#字段类型的选择)\
[组合结构](#组合结构)\
[四个出口](#四个出口)\
[失败分层与用例](#失败分层与用例)\
[这一章建立的 6 件事](#这一章建立的-6-件事)

## 手写校验的缺口

第 4 章讲了五种把输出变成结构的做法，最后一种是"本地校验 + 自愈重试"，但没讲校验本身怎么写。第一版代码通常长这样（`code/knowledge/ch05_pydantic/partial_checks.py` 的 `check_by_hand`）：

```python
def check_by_hand(payload: dict) -> str:
    if "eligible" not in payload:
        return "缺 eligible"
    if "reason" not in payload:
        return "缺 reason"
    return "通过"
```

它只检查键在不在。四种输入的结果：

```
类型漂移   手写=通过           pydantic=通过
缺字段    手写=缺 reason     pydantic=reason: Field required (input={'eligible': True})
多出字段   手写=通过           pydantic=通过
全对     手写=通过           pydantic=通过
```

四行里手写校验拦住一行，pydantic 也拦住一行，漏掉的是同一批：类型漂移和多出来的字段。第一行 `{"eligible": "true"}` 手写只看键所以通过；pydantic 默认把字符串转成布尔，也通过，这个默认行为叫宽松模式。第三行多了 `confidence`，两者都通过，因为默认不禁止额外字段；额外字段是个信号，说明模型在按自己的理解补东西。于是校验要写清三件事：哪些字段必填、值的类型允不允许转换、多出来的字段怎么办——只声明类型，等于只写了三分之一。

语法合法和结构正确是两件事。`json.loads` 只保证这串文字符合 JSON 语法，它不知道 `eligible` 该是什么类型、`reason` 该不该是字符串、哪些字段必须存在：

```python
raw = '{"eligible": "true", "reason": 123}'
json.loads(raw)      # 成功，得到 {"eligible": "true", "reason": 123}
```

中间隔着一份字段表。这份字段表如果只活在提示词里，会连带三个问题：校验代码会分叉（第 4 章写一份、第 6 章写工具参数时再写一份、评测再写一份，判断条件很快不一样）；错误文案会分叉（"缺 reason"没告诉模型该补成什么类型）；schema 生成不出来（第 4 章第四种做法要把结构交给服务端，只能另抄一遍，两份定义各自演化）。字段表写在代码里，因为三个出口必须同时变：只改字段名不改 schema，服务端按旧结构采样；只改 schema 不改校验，本地放过多出来的字段。

## 声明一份结构

一个退货判定结果，字段表是三行：能不能退、理由、模型自己的置信度。声明成模型只要几行，见 `code/knowledge/ch05_pydantic/error_stats.py`：

```python
from pydantic import BaseModel, Field


class Verdict(BaseModel):
    eligible: bool
    reason: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0, le=1)
```

`Field` 里的约束是可判定的：`min_length=1` 意味着空字符串不合法，`ge=0, le=1` 意味着置信度必须落在区间内。这些约束同时出现在三个地方：校验、报错文案、导出的 JSON Schema。写一遍，三个出口各自得到同一份事实。

类型注解本身不执行。同一份数据交给 dataclass 和 pydantic，结果不同，见 `code/knowledge/ch05_pydantic/dataclass_vs_model.py`：

```python
@dataclass
class VerdictDC:
    eligible: bool
    reason: str
```

```
dataclass： VerdictDC(eligible='true', reason=123)
pydantic： ('reason',) Input should be a valid string
```

dataclass 把 `"true"` 和 `123` 原样存了下来，直到下游用 `eligible == True` 比较时才发现不等；pydantic 在入口就拦住了 `reason`。类型的价值在入口，不在声明。

`Field` 承担全部约束声明，常用的写法只有一张表：

| 写法 | 作用 | 例 |
|---|---|---|
| `gt` / `ge` / `lt` / `le` | 数值区间，开区间与闭区间 | `confidence: float = Field(ge=0, le=1)` |
| `min_length` / `max_length` | 字符串或列表的长度 | `reason: str = Field(min_length=1, max_length=40)` |
| `pattern` | 正则，等价于 JSON Schema 的 `pattern` | `order_id: str = Field(pattern=r"^A\d{4}$")` |
| `description` | 字段说明，随 schema 进请求 | `Field(description="不超过 40 字的理由")` |
| `default` / `default_factory` | 缺失时的取值，后者给可变默认值 | `tags: list[str] = Field(default_factory=list)` |
| `alias` | 对外名字与代码里的名字分开 | `why: str = Field(alias="reason")` |

必填由"有没有默认值"决定，不由注解决定：`eligible: bool` 必填，`eligible: bool = False` 可选。可空与可选是两件事：`reason: str | None` 接受 `null` 但仍必填，`reason: str | None = None` 才允许整条缺失。三个开关决定"入口"有多严：必填与默认值、类型允不允许转换、额外字段怎么办。它们是同一份声明上三个不同的位置。

## 校验入口与错误回灌

校验的入口有两个：`model_validate(payload)` 收字典，`model_validate_json(raw)` 收字符串。两者失败时抛的都是 `ValidationError`，里面是一个错误列表，每条带三个字段：

```
loc = ('items', 1, 'qty') | Input should be greater than or equal to 1 | input = 0
```

一个模型校验一条，一批模型不必再包一层类，直接用 `TypeAdapter`，见 `code/knowledge/ch05_pydantic/type_adapter.py`：

```python
ADAPTER = TypeAdapter(list[Verdict])
ok = ADAPTER.validate_python([{"eligible": True, "reason": "未拆封"}])
```

```
整批： [Verdict(eligible=True, reason='未拆封')]
错误： missing (0, 'reason') | Field required
错误： string_too_short (1, 'reason') | String should have at least 1 character
```

`errors()` 每条有四个键：`type` 是机器可判的错误码（`missing`、`string_too_short`），适合做统计与分支；`loc` 是出错位置，嵌套结构里能一路指到第几个元素；`msg` 是给人读的约束；`input` 是模型实际给的值。回灌时后三样都要带上——只说"qty 不合法"，模型不知道该改成 1 还是 99。回灌的实现只有一条设计决定：不把 `ValidationError` 的字符串形式直接发出去（`code/knowledge/ch05_pydantic/error_feedback.py`）。

```python
def to_feedback(exc: ValidationError) -> str:
    """把错误列表压成一段模型能读的提示，不夹带 Python 堆栈。"""
    lines = ["你上一次的输出不合法，请只输出 JSON 对象，字段如下："]
    for err in exc.errors():
        field = ".".join(str(part) for part in err["loc"])
        lines.append(f"- {field}: {err['msg']}（你给的是 {err['input']!r}）")
    return "\n".join(lines)
```

两个入口的差别只在输入形态：`model_validate` 收已经解析好的字典，`model_validate_json` 收原始字符串并顺带做语法解析，省掉一次 `json.loads`。后者对尾随逗号、注释、单引号一律报错，报错的 `loc` 是 `()`、`type` 是 `json_invalid`，这类错误在回灌时应归到语法层，而不是结构层。选哪个不影响后面的校验强度，只影响错误分类的粒度。

直接 `str(exc)` 会带上 URL、Python 类型名和换行缩进，模型会把这些当格式要求照抄；压成字段、约束、实际值三列，模型能定位。这条链路跑一遍：

```
第 1 次返回：{"eligible": "true", "reason": 123}
校验失败，回灌这段：
你上一次的输出不合法，请只输出 JSON 对象，字段如下：
- reason: Input should be a valid string（你给的是 123）
第 2 次返回：{"eligible": true, "reason": "未拆封"}
通过： eligible=True reason='未拆封'
```

第一次的错误列表里只有 `reason` 一条：`eligible` 的 `"true"` 被宽松模式转成了 `True`，没报错。如果这条链路上字符串 `true` 必须被拒，就要换成下一节的严格模式。

## 校验开关与默认值

pydantic 默认宽松，能转就转：`"true"` 转成 `True`、`"0.83"` 转成 `0.83`。严格模式要求类型一字不差，见 `code/knowledge/ch05_pydantic/strict_vs_lax.py`：

```python
class StrictVerdict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    eligible: bool
    confidence: float
```

同一份脏数据，两种结论：

```
宽松： eligible=True confidence=0.83
严格： ('eligible',) Input should be a valid boolean input= 'true'
严格： ('confidence',) Input should be a valid number input= '0.83'
严格： ('note',) Extra inputs are not permitted input= '模型顺手多写了一个字段'
严格模式只喂合法的值： eligible=True confidence=0.83
```

`strict=True` 改两件事：不做类型转换，`extra="forbid"` 把多出来的字段变成错误。前三条都被拦下，第四条说明它没把合法输入也拒掉。宽松还是严格取决于值从哪来：用户填的表单，宽松是对的，写 `"3"` 想表达的就是 3；模型生成的 JSON，严格更接近事实，它写 `"true"` 说明对类型的把握不稳。`model_config` 里最常用的五项：

| 项 | 作用 | 什么时候开 |
|---|---|---|
| `strict=True` | 不做类型转换 | 值来自模型生成时 |
| `extra="forbid"` | 多出的字段报错 | 结构要与声明严格一致 |
| `populate_by_name=True` | 别名与字段名都接受 | 字段改过名、老调用方还在用 |
| `frozen=True` | 实例不可改 | 校验通过后当只读值传阅 |
| `str_strip_whitespace=True` | 字符串两侧空白先去掉 | 模型常在冒号后多打空格 |

还有一处容易混淆：这里的 `strict` 是 pydantic 的校验开关，和厂商接口里的 `strict` 不是同一个东西；后者约束采样过程，前者约束拿到文本之后的校验。

默认值、必填与别名是同一份声明上的三个位置。同一条缺字段的数据，四种配置的结果，见 `code/knowledge/ch05_pydantic/default_masking.py`：

```
默认值兜底： eligible=True reason=''
必填： Field required
额外字段： Extra inputs are not permitted
字段改名后仍能用旧名： eligible=True why='未拆封'
```

第一行是默认值最常见的误用。`reason: str = ""` 让"模型没给理由"变成"理由为空字符串"，校验通过，下游拿着空理由继续走；业务上若不允许不说明理由，这个默认值就把一条该报错的数据洗成了合法数据。第二行是把 `reason` 改成必填之后的报错，第三行是 `extra="forbid"` 的报错。第四行是别名：模型或老调用方仍用 `reason`，代码里已经改叫 `why`，`alias` 把两者接上，`populate_by_name=True` 允许两个名字都能用。

## 字段类型的选择

字段类型不是越宽松越好，四类值最容易选错，见 `code/knowledge/ch05_pydantic/types_demo.py`：

```
order_id='A1001' amount=Decimal('39.00') created_at=datetime.datetime(2026, 10, 28, 10, 0) channel='app'
金额字段的 schema： {'anyOf': [{'exclusiveMinimum': 0.0, 'type': 'number'}, {'pattern': '^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d{0,2}0*$', 'type': 'string'}], 'description': '退款金额，保留两位小数', 'title': 'Amount'}
枚举字段的 schema： {'description': '提交渠道', 'enum': ['app', 'web', 'phone'], 'title': 'Channel', 'type': 'string'}
三位小数被拒： Decimal input should have no more than 2 decimal places
不在枚举里： Input should be 'app', 'web' or 'phone'
float 相加： 0.30000000000000004
Decimal 相加： 0.3
```

金额用 `Decimal` 不用 `float`：`0.1 + 0.2` 在浮点里是 `0.30000000000000004`，退款金额做累加时会漂，`Decimal("0.1") + Decimal("0.2")` 精确等于 `0.3`。代价是 schema 变复杂，`Decimal` 导出成 `anyOf` 两个分支，比 `number` 长一截，接服务端严格模式时还可能不被接受。时间用 `datetime` 不用字符串：字符串有十几种写法，`2026-10-28`、`10/28/2026`、带时区不带时区，校验器分不出哪个是对的；`datetime` 只接受可解析的写法，解析完就是一个可比较、可做差的值。

有限取值用 `Literal` 不用 `str`：`channel: str` 什么都收，模型写 `"APP"`、`"App"`、`"客户端"` 都合法，下游的分支判断就会漏；`Literal["app", "web", "phone"]` 把取值集合写进 schema，同时把取值集合写进报错文案，最后两行就是这两种约束的实际报错。ID 用 `pattern` 不用自由字符串：订单号 `^A\d{4}$` 这样的模式能挡住大部分格式错误，而且是可判定约束，服务端也认。

取值集合还要在下游按分支处理时用 `Enum`，只要约束不要分支时用 `Literal`：`class Channel(str, Enum): app = "app"` 定义出来的成员可以直接在 `if` 里比较，导出到 schema 与 `Literal` 一样是 `enum`；差别在代码侧，`Literal` 是类型注解、不产生可枚举的常量，重复使用要抄三遍。同一条约束在多处出现时，用 `Annotated` 把它挂到一个别名上，比每处都写一遍 `Field` 更不容易漏：

```python
OrderId = Annotated[str, Field(pattern=r"^A\d{4}$", description="订单号，例如 A1001")]
```可空字段用 `Optional` 或 `| None` 显式声明，不要靠默认值 `""` 表达"没有"：`None` 与空字符串在下游是两个分支，混用之后两者分不开。

## 组合结构

单字段校验管不到组合。先看嵌套：订单里有明细，明细有库存与数量，声明成两个类，见 `code/knowledge/ch05_pydantic/schema_for_api.py`：

```python
class Item(BaseModel):
    sku: str
    qty: int = Field(ge=1, le=99)


class Order(BaseModel):
    order_id: str = Field(pattern=r"^A\d{4}$")
    items: list[Item]
```

导出的 schema 把 `Item` 提到 `$defs` 里，用 `$ref` 引用：

```json
{
  "$defs": {
    "Item": {
      "properties": {
        "sku": {"title": "Sku", "type": "string"},
        "qty": {"maximum": 99, "minimum": 1, "title": "Qty", "type": "integer"}
      },
      "required": ["sku", "qty"],
      "title": "Item",
      "type": "object"
    }
  },
  "properties": {
    "order_id": {"pattern": "^A\\d{4}$", "title": "Order Id", "type": "string"},
    "items": {"items": {"$ref": "#/$defs/Item"}, "title": "Items", "type": "array"}
  },
  "required": ["order_id", "items"],
  "title": "Order",
  "type": "object"
}
```

厂商的严格模式对 `$ref` 的支持并不一致：有的接受，有的要求全部内联，处理办法是把 schema 展开成扁平结构。`pattern`、`minimum`、`maximum` 原样进了 schema，说明它们是 JSON Schema 的关键字，校验器和服务端都认。

第二类组合是跨字段一致性。`eligible=True` 和 `reason="已拆封"` 各自都合法，放在一起是自相矛盾的结论，见 `code/knowledge/ch05_pydantic/validators_demo.py`：

```python
class Verdict(BaseModel):
    eligible: bool
    reason: str

    @model_validator(mode="after")
    def reason_matches_verdict(self):
        if self.eligible and "已拆封" in self.reason and "不影响" not in self.reason:
            raise ValueError("eligible=True 时，reason 不能只说已拆封")
        return self
```

`mode="after"` 表示在字段都校验完之后再跑，函数拿到的是一个已经合法的对象。三条输入：

```
一致       eligible=True reason='未拆封，符合七天无理由'
矛盾       loc = () | Value error, eligible=True 时，reason 不能只说已拆封 | input = {'eligible': True, 'reason': '已拆封'}
矛盾但写明了例外 eligible=True reason='已拆封，但不影响二次销售'
```

第二行的 `loc` 是空元组，这不是缺陷而是信息：错误不属于某个字段，属于整份数据。回灌时照字段名去拼提示，会拼出一句"某个字段不对"，模型不知道该改哪个，所以模型级错误要把整条规则写进提示。第三行说明规则本身要可判定："已拆封"三个字出现在理由里，不等于结论错；写成"包含已拆封就拒绝"，会把"已拆封但不影响二次销售"一起拦掉。

第三类组合是判别联合。一个 agent 的每一步可能是退款、问人、结束之一，字段完全不同，塞进一个模型会有一半字段为空；用裸的 `Union` 则要逐个试，错误信息变成三条规则的并集。做法是给每个分支一个固定的类型标签，见 `code/knowledge/ch05_pydantic/union_demo.py`：

```python
class Refund(BaseModel):
    action: Literal["refund"]
    amount: float = Field(gt=0)


class AskHuman(BaseModel):
    action: Literal["ask_human"]
    question: str = Field(min_length=1)


Action = Annotated[Union[Refund, AskHuman, Stop], Field(discriminator="action")]
```

`Literal["refund"]` 既是类型，也是分支标签；`discriminator="action"` 让校验器先读这个字段，再决定按哪个分支解：

```json
{
  "discriminator": {
    "mapping": {
      "ask_human": "#/$defs/AskHuman",
      "refund": "#/$defs/Refund",
      "stop": "#/$defs/Stop"
    },
    "propertyName": "action"
  },
  "oneOf": [{"$ref": "#/$defs/Refund"}, {"$ref": "#/$defs/AskHuman"}, {"$ref": "#/$defs/Stop"}]
}
```

支持 `discriminator` 的服务端会按 `action` 直接选分支，不做逐个尝试。三种输入的结果：

```
通过： action='refund' amount=39.0
通过： action='ask_human' question='哪一笔订单？'
拒绝： ('refund', 'amount') | Field required | input = {"action": "refund", "question": "哪一笔订单？"}
```

第三行是关键：错误定位落在 `('refund', 'amount')`，即按 action 选中的那个分支里 amount 缺了，而不是笼统地说三个分支都不匹配。

第四类组合是递归：计划树、目录树这类输出的节点类型与子节点类型相同（`code/knowledge/ch05_pydantic/recursive_demo.py`）。

```python
class PlanStep(BaseModel):
    name: str
    children: list["PlanStep"] = []
```

校验通过之后是嵌套对象，schema 里则变成一个自引用：

```json
{
  "$defs": {
    "PlanStep": {
      "properties": {
        "name": {"title": "Name", "type": "string"},
        "children": {"default": [], "items": {"$ref": "#/$defs/PlanStep"},
                     "title": "Children", "type": "array"}
      },
      "required": ["name"],
      "title": "PlanStep",
      "type": "object"
    }
  },
  "$ref": "#/$defs/PlanStep"
}
递归深度 2 也能校验： c
```

两处要留意。顶层变成了 `$ref`：整个 schema 只有一处定义，比展开成固定层数省 token；不是所有服务端都接受自引用，接真实服务前先探一次。递归还带来一个结构管不住的问题：校验器只检查每个节点合法，不限制层数，要限制得在模型上加深度校验或在拼装时截断。

## 四个出口

四个用途在 pydantic 里是同一份东西的四个出口：

| 出口 | 写法 | 用在哪 |
|---|---|---|
| 本地校验 | `Model.model_validate(payload)` | 拿到模型输出后的第一道检查 |
| 错误回灌 | `exc.errors()` | 校验失败后写给模型的提示 |
| JSON Schema | `Model.model_json_schema()` | 服务端约束采样、工具参数声明 |
| 配置 | `BaseSettings` 的子类 | 启动时读环境变量 |

一份定义、四个出口，是 pydantic 在这条链路上不被替代的地方。换成手写校验，四个出口要么各写一份，要么有一个缺失。

第一个出口已经在前面用过；第二个是上文的 `to_feedback`。第三个出口的用法是把 schema 直接放进请求体，见 `code/knowledge/ch05_pydantic/schema_for_api.py`：

```python
reply = client.chat.completions.create(
    model="demo-model",
    messages=[{"role": "user", "content": "把订单 A1001 转成 JSON。"}],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "Order",
            "strict": True,
            "schema": Order.model_json_schema(),
        },
    },
)
```

同一份声明还负责字段说明。提示词里写一遍、schema 里再写一遍，两处会漂移；`Field(description=...)` 让说明只写一次，跟着 schema 一起走，见 `code/knowledge/ch05_pydantic/descriptions_demo.py`：

```python
class Verdict(BaseModel):
    eligible: bool | None = Field(
        description="能否退货：符合条件为 true，明确不符合为 false，信息不足为 null"
    )
    reason: str = Field(
        description="不超过 40 字的理由，必须引用政策条款编号，如 P-7"
    )
```

导出的 schema 里，每段说明原样保留：

```json
{
  "eligible": {
    "type": "anyOf",
    "description": "能否退货：符合条件为 true，明确不符合为 false，信息不足为 null"
  },
  "reason": {
    "type": "string",
    "description": "不超过 40 字的理由，必须引用政策条款编号，如 P-7"
  },
  "confidence": {
    "type": "number",
    "description": "对本次判定的把握程度，0 到 1 之间的小数"
  }
}
必填字段： ['eligible', 'reason', 'confidence']
```

三行说明都不是"尽量准确"这类无法执行的表述：`eligible` 那条把三种取值对应到三种业务情况，模型拿到 `null` 这个许可才不会硬猜；`reason` 那条给了长度和格式两个可判定要求。这和提示词里的六要素不重复，是同一份内容的两个投递口，都从 `Field(description=...)` 取。

第四个出口是配置。配置和模型输出有同一个失效方式：读取时没人检查，用到一半才发现不对。把配置也声明成模型，检查就提前到启动那一刻（`code/knowledge/ch05_pydantic/settings_demo.py`）：

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="forbid")

    base_url: str = "http://127.0.0.1:8000/v1"
    api_key: str = Field(min_length=1)
    timeout_s: float = 30.0
    max_retries: int = 2
```

`env_prefix="AGENT_"` 意味着读的是 `AGENT_API_KEY`、`AGENT_TIMEOUT_S` 这些变量，`extra="forbid"` 让拼错的变量名直接报错：拼错时不会报未知变量，只表现为配置不生效，然后在很远的地方以超时或 401 的形式出现。

```
base_url='http://127.0.0.1:8000/v1' api_key='sk-demo' timeout_s=30.0 max_retries=2
base_url='http://127.0.0.1:8000/v1' api_key='sk-demo' timeout_s=3.5 max_retries=1
配置不合法： ('api_key',) String should have at least 1 character
```

第一行是默认值，第二行是环境变量覆盖之后的结果，第三行是把 `AGENT_API_KEY` 设成空字符串之后的结果，三行都发生在进程启动的几毫秒内。同一份错误留到第一次调用模型时才暴露，表现是 401。配置模型另一个作用是让默认值显式：`timeout_s: float = 30.0` 写在代码里评审时能看到，写成 `os.environ.get` 就藏在字符串里。

校验之后的对象还要交出去：写进消息回灌、存进日志、拼进下一次请求。`model_dump_json()` 直接给字符串，比 `json.dumps(model_dump())` 少一次转换，也不受 `ensure_ascii` 之类开关影响；写日志要人读时加 `indent=2`，回灌进请求时保持紧凑，因为空格也算 token。按别名导出用 `by_alias=True`，否则对外契约里的名字会被代码里的新名字替换掉。

`model_dump()` 给字典，`model_dump_json()` 给字符串，`exclude_none=True` 去掉空值，见 `code/knowledge/ch05_pydantic/dump_demo.py`：

```
model_dump： {'order_id': 'A1001', 'items': [{'sku': 'S-1', 'qty': 2}], 'note': None}
exclude_none： {'order_id': 'A1001', 'items': [{'sku': 'S-1', 'qty': 2}]}
model_dump_json： {"order_id":"A1001","items":[{"sku":"S-1","qty":2}],"note":null}
回读相等： True
原文与重新序列化不同： True
```

最后两行要停一下。`back == order` 是 `True`，两份数据的语义相同；但 `raw != back.model_dump_json()` 也是 `True`，原文里的空格和换行被压成了紧凑格式。语义相等不等于字节相等：`tool_calls` 的 `arguments` 解析成对象再用 `model_dump_json()` 写回去，键序和空白都变了，缓存前缀就对不上。

## 失败分层与用例

校验失败之后做什么，取决于错在哪一层。四类混在一起统一重试，会出现两种坏结果：该失败的反复重试消耗调用费，该重试的直接失败。

| 错误层 | 例子 | 该做什么 |
|---|---|---|
| 语法 | 返回的是 markdown 包裹的 JSON | 重试，提示"只输出 JSON，不要代码块" |
| 结构 | 缺字段、多字段、类型不对 | 重试，回灌字段名、约束和实际值 |
| 约束 | 金额为负、枚举越界、超过 40 字 | 重试，回灌具体约束 |
| 业务 | 订单不存在、用户无权限 | 不重试，走业务分支或转人工 |

判断方法一句话：换一种写法就可能通过吗？能，属于前三层，重试；不能，属于业务层，别让它重试——订单不会因为措辞变了而存在，反复回灌只会拖到步数上限。pydantic 自己不做重试，也不该做：把重试写进校验器，校验就变成会发网络请求的东西。

结构定义会改，最容易出的错是原来被拒的输入悄悄通过了。用例把期望写死，断言"拒在哪个字段"而不是"拒了没有"，见 `code/knowledge/ch05_pydantic/test_shapes.py`：

```python
CASES = [
    ("合法", {"eligible": True, "reason": "未拆封"}, None),
    ("缺理由", {"eligible": True}, "reason"),
    ("空理由", {"eligible": False, "reason": ""}, "reason"),
    ("类型漂移", {"eligible": "yes", "reason": "未拆封"}, "eligible"),
    ("多出字段", {"eligible": True, "reason": "未拆封", "score": 1}, "score"),
]
```

```
OK  合法     期望拒于=None 实际=None
OK  缺理由    期望拒于=reason 实际=reason
OK  空理由    期望拒于=reason 实际=reason
OK  类型漂移   期望拒于=eligible 实际=eligible
OK  多出字段   期望拒于=score 实际=score
```

两条设计决定：同一条数据可能同时违反两条约束，只断言"抛了异常"测不出拒在哪一条，字段名把断言收紧；这组用例与第 4 章的提示词回归用例同类，一个测提示词、一个测结构，一起维护才能防止两边各走各的。

这一层挡不住的只有一样：内容对不对。一份带 `pattern`、`ge`、`min_length` 的结构看起来比自由文本可信，但约束全部作用在形状上；订单是否真实存在、用户有没有权限，都要查库，塞进校验器只会让校验变慢、变难测。开放式问答没有稳定字段，硬套一个 `{"text": str}` 只是多一层包装，那类输出不该建模。

## 这一章建立的 6 件事

1. 手写校验只检查键在不在，类型漂移和多出字段都会漏过去。
2. pydantic 默认宽松，`"true"` 会被转成 `True`；模型输出应该用严格模式加 `extra="forbid"`。
3. `errors()` 里的 `loc`、`msg`、`input` 三样是回灌提示的全部素材。
4. `model_json_schema()` 让同一份声明同时服务本地校验与服务端约束采样。
5. 组合结构有四类：嵌套、跨字段、判别联合、递归，各自的错误定位精度不同。
6. 配置也用同一套声明，把"用到一半才发现不对"提前到启动那一刻。

## 下一章

结构定义好了，下一步是让模型能请求做事。第 6 章讲工具调用：模型只会生成文本，`tool_calls` 是它表达"我想做什么"的唯一格式；参数为什么是字符串、回灌要满足哪三条格式、以及一次往返里哪些部分模型根本管不着。

---

[← 第 4 章 · 提示词工程：从规则到结构化输出](./04-提示词工程-从规则到结构化输出.md)　｜　[卷 1 目录](./docs/INDEX.md#vol1)　｜　[第 6 章 · 工具调用：声明、请求与回灌 →](./06-工具调用-声明-请求与回灌.md)
