# 第 5 章 · 用 pydantic 定义输出结构

> **卷 1 · 一次调用（第 1–5 章）**｜[全书目录](./docs/INDEX.md#vol1)｜[本卷导读](./outline/vol01-一次调用.md)
>
> - **知识点**：A10 输出结构声明 —— 一份声明四个出口：本地校验、错误回灌、JSON Schema、配置读取（编号定义见 [知识点-A-模型层](./outline/11-知识点-A-模型层.md)）
> - **本章回答**：pydantic 的常用面各管什么；一份声明怎样同时服务本地校验、模型约束、工具参数与配置
> - **示例目录**：`code/knowledge/ch05_pydantic/`
> - **读完应当能回答**：拿到一份输出字段表，能写出可校验、可回灌、能生成 schema、能读环境变量的一份定义

---

## 目录

[手写校验的缺口](#手写校验的缺口)\
[声明一份结构](#声明一份结构)\
[校验入口与错误结构](#校验入口与错误结构)\
[校验器](#校验器)\
[校验开关与赋值校验](#校验开关与赋值校验)\
[字段类型](#字段类型)\
[组合与生成](#组合与生成)\
[导出与序列化](#导出与序列化)\
[四个出口](#四个出口)\
[失败分层与用例](#失败分层与用例)\
[这一章建立的 8 件事](#这一章建立的-8-件事)

## 手写校验的缺口

第 4 章五种做法里的最后一种是"本地校验 + 自愈重试"，但没讲校验本身怎么写。第一版代码通常只检查键在不在，见 `code/knowledge/ch05_pydantic/partial_checks.py`：

```python
def check_by_hand(payload: dict) -> str:
    if "eligible" not in payload:
        return "缺 eligible"
    if "reason" not in payload:
        return "缺 reason"
    return "通过"
```

四种输入的结果：

```
类型漂移   手写=通过           pydantic=通过
缺字段    手写=缺 reason     pydantic=reason: Field required (input={'eligible': True})
多出字段   手写=通过           pydantic=通过
全对     手写=通过           pydantic=通过
```

四行里手写校验拦住一行，漏掉的是类型漂移和多出来的字段。`{"eligible": "true"}` 手写只看键所以通过，pydantic 默认把字符串转成布尔也通过——这个默认行为叫宽松模式；多出的 `confidence` 两者都放过，因为默认不禁止额外字段。于是校验要写清三件事：哪些字段必填、类型允不允许转换、多出来的字段怎么办，只声明类型等于只写了三分之一。

再往下一层，语法合法和结构正确是两件事。`json.loads` 只保证这串文字符合 JSON 语法，它不知道哪个字段该是什么类型、哪些必须存在：

```python
raw = '{"eligible": "true", "reason": 123}'
json.loads(raw)      # 成功，得到 {"eligible": "true", "reason": 123}
```

中间隔着一份字段表。这份字段表如果只活在提示词里，会连带三个问题：校验代码会分叉（第 4 章写一份、第 6 章写工具参数时再写一份、评测再写一份，判断条件很快不一样）；错误文案会分叉（"缺 reason"没告诉模型该补成什么类型）；schema 生成不出来（第 4 章第四种做法要把结构交给服务端，只能另抄一遍，两份定义各自演化）。字段表写在代码里，因为三个出口必须同时变：只改字段名不改 schema，服务端按旧结构采样；只改 schema 不改校验，本地放过多出来的字段。

## 声明一份结构

一个退货判定结果，字段表是三行：能不能退、理由、置信度。声明成模型只要几行，见 `code/knowledge/ch05_pydantic/error_stats.py`：

```python
from pydantic import BaseModel, Field


class Verdict(BaseModel):
    eligible: bool
    reason: str = Field(min_length=1, max_length=40)
    confidence: float = Field(ge=0, le=1)
```

`Field` 承担全部约束，常用的写法只有一张表：

| 写法 | 作用 | 例 |
|---|---|---|
| `gt` / `ge` / `lt` / `le` | 数值区间，开区间与闭区间 | `confidence: float = Field(ge=0, le=1)` |
| `min_length` / `max_length` | 字符串或列表长度 | `reason: str = Field(min_length=1, max_length=40)` |
| `pattern` | 正则，等价于 JSON Schema 的 `pattern` | `order_id: str = Field(pattern=r"^A\d{4}$")` |
| `description` | 字段说明，随 schema 进请求 | `Field(description="不超过 40 字的理由")` |
| `default` / `default_factory` | 缺失时的取值，后者给可变默认值 | `tags: list[str] = Field(default_factory=list)` |
| `alias` | 对外名字与代码里的名字分开 | `why: str = Field(alias="reason")` |
| `exclude` | 导出时跳过该字段 | `internal: str = Field(exclude=True)` |

必填由"有没有默认值"决定，不由注解决定：`eligible: bool` 必填，`eligible: bool = False` 可选。可空与可选是两件事：`reason: str | None` 接受 `null` 但仍必填，`reason: str | None = None` 才允许整条缺失。

外对接口常用驼峰、对内常用下划线，`alias_generator` 一行就能对上，见 `code/knowledge/ch05_pydantic/surface_tour.py` 第 1 段：

```python
class OrderIn(BaseModel):
    model_config = ConfigDict(alias_generator=lambda s: s.upper(), populate_by_name=True)

    order_id: str
    days: int = Field(ge=0, validation_alias=AliasChoices("days", "signed_days"))
```

```
  按别名收   ： order_id='A1001' days=3
  dump 用别名： {'ORDER_ID': 'A1001', 'DAYS': 3}
  dump 用字段名： {'order_id': 'A1001', 'days': 3}
```

`validation_alias` 与 `alias_generator` 的分工是"收"与"发"：`AliasChoices` 让同一个字段接受多个名字，`alias_generator` 决定导出时用什么名字，`populate_by_name=True` 让代码里的字段名也能用。三者都不改变校验强度，只改变名字怎么对上。

## 校验入口与错误结构

校验的入口有两个：`model_validate(payload)` 收已经解析好的字典，`model_validate_json(raw)` 收原始字符串并顺带做语法解析。两者失败时都抛 `ValidationError`，每条错误有四个键：`type` 是机器可判的错误码（`missing`、`string_too_short`、`json_invalid`），适合做统计与分支；`loc` 是位置；`msg` 是给人读的约束；`input` 是实际给的值。回灌时后三样都要带上：只说"qty 不合法"，模型不知道该改成 1 还是 99。

一个模型校验一条，一批模型不必包一层类，用 `TypeAdapter`，见 `code/knowledge/ch05_pydantic/type_adapter.py`：

```python
ADAPTER = TypeAdapter(list[Verdict])
ok = ADAPTER.validate_python([{"eligible": True, "reason": "未拆封"}])
```

```
整批： [Verdict(eligible=True, reason='未拆封')]
错误： missing (0, 'reason') | Field required
错误： string_too_short (1, 'reason') | String should have at least 1 character
```

顶层不是对象时用 `RootModel`：模型只有一个"根值"，可以直接是列表或字典，见 `surface_tour.py` 第 2 段。

```python
class Tags(RootModel[list[str]]):
    pass
```

```
  根值    ： ['退货', '七天']
  dump    ： ['退货', '七天']
```

两个入口的差别只在输入形态。`model_validate_json` 省掉一次 `json.loads`，但它对尾随逗号、注释、单引号一律报错，此时 `loc` 是 `()`、`type` 是 `json_invalid`——这类错误应归到语法层而不是结构层。选哪个不影响校验强度，只影响错误分类的粒度。

## 校验器

单字段的约束用 `Field` 就够；值需要变形、需要两个字段一起判断、需要读外部信息时，才写校验器。两类三种，见 `surface_tour.py` 第 3 段：

```python
class Refund(BaseModel):
    days: int
    window: int = 7

    @field_validator("days", mode="before")
    @classmethod
    def strip_unit(cls, v: object) -> object:
        if isinstance(v, str) and v.endswith("天"):
            return int(v[:-1])
        return v

    @field_validator("days")
    @classmethod
    def not_negative(cls, v: int, info: ValidationInfo) -> int:
        if v < 0:
            raise ValueError(f"{info.field_name} 不能为负")
        return v

    @model_validator(mode="before")
    @classmethod
    def fill_window(cls, data: object, info: ValidationInfo) -> object:
        ctx = info.context or {}
        if isinstance(data, dict) and "window" not in data and "window" in ctx:
            return {**data, "window": ctx["window"]}
        return data

    @model_validator(mode="after")
    def within_window(self):
        if self.days > self.window:
            raise ValueError(f"{self.days} 天超出窗口 {self.window} 天")
        return self
```

```
  before 去单位 ： days=3 window=7
  上下文补窗口  ： days=30 window=60
  模型级错误    ： () | Value error, 30 天超出窗口 5 天
```

三种的区别在于拿到什么。`field_validator(mode="before")` 拿到的是原始值，用来做清洗（去掉"天"）；`field_validator` 默认在类型转换之后跑，拿到的是已经合法的值，用来做补充判断，第二个参数 `ValidationInfo` 能读到字段名与 `context`；`model_validator(mode="after")` 拿到的是整份已校验对象，用来做跨字段判断，这类错误的 `loc` 是空元组，说明它不属于某个字段。`model_validator(mode="before")` 拿不到对象，它适合补外部信息或在解析前改结构。`context` 从 `model_validate(..., context={...})` 传进来，是给校验器递运行时参数的正规入口，不用全局变量。

同一条规则要在多个模型里用，写成注解比写成方法更省：`Annotated[int, AfterValidator(not_negative)]` 把校验函数挂到类型上，字段声明处只写别名，规则改一处、所有用到它的模型一起变。注解式校验器同样能拿到 `ValidationInfo`，与 `@field_validator` 的能力一致，区别只在复用方式：方法属于某一个类，注解属于类型。类的组合校验没有注解形式，跨字段规则仍然要写在 `model_validator` 里。

数量上要克制：一条规则能写成 `Field` 就写成 `Field`，校验器越少，schema 与报错都越干净。

## 校验开关与赋值校验

`model_config` 里最常用的六项：

| 项 | 作用 | 什么时候开 |
|---|---|---|
| `strict=True` | 不做类型转换 | 值来自模型生成时 |
| `extra="forbid"` | 多出的字段报错 | 结构要与声明严格一致 |
| `populate_by_name=True` | 别名与字段名都接受 | 字段改过名、老调用方还在用 |
| `frozen=True` | 实例不可改 | 校验通过后当只读值传阅 |
| `validate_assignment=True` | 赋值时也校验 | 对象构造后还会被改 |
| `str_strip_whitespace=True` | 字符串两侧空白先去掉 | 模型常在冒号后多打空格 |

宽松与严格之差，用同一份脏数据看最清楚，见 `code/knowledge/ch05_pydantic/strict_vs_lax.py`：

```python
class StrictVerdict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    eligible: bool
    confidence: float
```

```
宽松： eligible=True confidence=0.83
严格： ('eligible',) Input should be a valid boolean input= 'true'
严格： ('confidence',) Input should be a valid number input= '0.83'
严格： ('note',) Extra inputs are not permitted input= '模型顺手多写了一个字段'
严格模式只喂合法的值： eligible=True confidence=0.83
```

前三条都被拦下，第四条说明它没把合法输入也拒掉。值从哪来决定开不开：用户填的表单，宽松是对的，写 `"3"` 想表达的就是 3；模型生成的 JSON，严格更接近事实，它写 `"true"` 说明对类型的把握不稳。注意这里的 `strict` 是 pydantic 的校验开关，和厂商接口里的 `strict` 不是同一个东西——后者约束采样过程，前者约束拿到文本之后的校验。

`validate_assignment=True` 让构造之后的赋值也走校验，`model_construct` 则相反，它跳过校验直接塞值，只在"数据已经在别处校验过、这里只为省时间"时用，见 `surface_tour.py` 第 5 段：

```
  正常赋值  ： 1
  赋值被拒  ： int_parsing
  construct ： steps='一步' | 类型 str
```

第三行是 `model_construct` 的代价：字段类型和声明不一致，它不报错，下游什么时候炸取决于谁先用它。

## 字段类型

字段类型不是越宽松越好。内置类型里，与 agent 输出最相关的几组：

| 类型 | 用途 | 注意 |
|---|---|---|
| `UUID` / `date` / `datetime` | 标识与时间 | 接受字符串但解析成对象，比字符串好比较 |
| `Decimal` | 金额 | 浮点累加会漂，`Decimal` 精确；schema 会变长 |
| `Literal[...]` / `Enum` | 有限取值 | 取值集合同时进 schema 与报错 |
| `Json[dict]` / `Json[list]` | 值是"一段 JSON 文本" | 自动解析成对象，写错时报 `json_invalid` |
| `PositiveInt`、`Annotated[int, Field(gt=0)]` | 有范围的整数 | 后者能带 `description` 与 `strict` |
| `SecretStr` / `Path` / `AnyUrl` | 密钥、路径、URL | `SecretStr` 导出时打码，不进日志 |
| `constr` / `conint` | v1 的约束类型 | v2 统一用 `Annotated` 加 `Field` |

四类最容易选错的，`code/knowledge/ch05_pydantic/types_demo.py` 各跑了一遍：

```
order_id='A1001' amount=Decimal('39.00') created_at=datetime.datetime(2026, 10, 28, 10, 0) channel='app'
金额字段的 schema： {'anyOf': [{'exclusiveMinimum': 0.0, 'type': 'number'}, {'pattern': '^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d{0,2}0*$', 'type': 'string'}], 'description': '退款金额，保留两位小数', 'title': 'Amount'}
枚举字段的 schema： {'description': '提交渠道', 'enum': ['app', 'web', 'phone'], 'title': 'Channel', 'type': 'string'}
三位小数被拒： Decimal input should have no more than 2 decimal places
不在枚举里： Input should be 'app', 'web' or 'phone'
float 相加： 0.30000000000000004
Decimal 相加： 0.3
```

金额用 `Decimal` 不用 `float`：`0.1 + 0.2` 在浮点里是 `0.30000000000000004`，退款金额做累加会漂。代价是 schema 变复杂，`Decimal` 导出成 `anyOf` 两个分支，接服务端严格模式时还可能不被接受。时间用 `datetime` 不用字符串：字符串有十几种写法，校验器分不出哪个对；`datetime` 只接受可解析的写法，解析完就是可比较、可做差的值。ID 用 `pattern`，有限取值用 `Literal` 或 `Enum`——`channel: str` 什么都收，模型写 `"APP"`、`"客户端"` 都合法，下游的分支判断就会漏。

严格类型与 `Json` 的写法，见 `surface_tour.py` 第 6 段：

```python
class Payload(BaseModel):
    id: uuid.UUID
    qty: Annotated[int, Field(strict=True, gt=0)]
    meta: Json[dict]
```

```
  uuid          ： 12345678-1234-5678-1234-567812345678
  Json 自动解析 ： {'a': 1} dict
  strict 拒绝   ： int_type
```

同一条约束在多处出现时，用 `Annotated` 挂到别名上，比每处写一遍 `Field` 更不容易漏：

```python
OrderId = Annotated[str, Field(pattern=r"^A\d{4}$", description="订单号，例如 A1001")]
```

## 组合与生成

单字段校验管不到组合。嵌套是最常见的一种：订单里有明细，见 `code/knowledge/ch05_pydantic/schema_for_api.py`：

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

一个 agent 的每一步可能做几件事之一，字段完全不同，塞进一个模型会有一半字段为空；用裸的 `Union` 则要逐个试，错误信息变成所有分支的并集。做法是给每个分支一个类型标签，用它判别，见 `code/knowledge/ch05_pydantic/union_demo.py`：

```python
class Refund(BaseModel):
    action: Literal["refund"]
    amount: float = Field(gt=0)


class AskHuman(BaseModel):
    action: Literal["ask_human"]
    question: str = Field(min_length=1)


Action = Annotated[Union[Refund, AskHuman, Stop], Field(discriminator="action")]
```

```
通过： action='refund' amount=39.0
通过： action='ask_human' question='哪一笔订单？'
拒绝： ('refund', 'amount') | Field required | input = {"action": "refund", "question": "哪一笔订单？"}
```

第三行是关键：模型把 `refund` 的参数写成了 `ask_human` 的，错误定位落在 `('refund', 'amount')`，即按 `action` 选中的那个分支里缺了什么，而不是笼统地说三个分支都不匹配。

计划树、目录树这类输出的节点类型与子节点类型相同，用自引用，见 `code/knowledge/ch05_pydantic/recursive_demo.py`：

```python
class PlanStep(BaseModel):
    name: str
    children: list["PlanStep"] = []
```

schema 里变成 `$ref` 指向自己。两处要留意：顶层成了 `$ref`，整个结构只定义一次，比展开成固定层数省 token；不是所有服务端都接受自引用，接真实服务前先探一次。递归还带来一个结构管不住的问题——校验器只检查每个节点合法，不限制层数，要限制得在模型上加深度校验或在拼装时截断。

结构还会变。字段少时可以继承，字段在运行时才知道时用 `create_model`，要复用同一个容器时用泛型，见 `surface_tour.py` 第 7 段：

```python
Page = create_model("Page", items=(list[dict], ...), total=(int, 0))


class Box(BaseModel, Generic[T]):
    value: T
```

```
  create_model ： items=[{'a': 1}] total=0
  泛型实例     ： value=3
```

## 导出与序列化

校验之后的对象要交出去：写进消息回灌、存进日志、拼进下一次请求。`model_dump()` 给字典，`model_dump_json()` 给字符串，`exclude_none=True` 去掉空值，见 `code/knowledge/ch05_pydantic/dump_demo.py`：

```
model_dump： {'order_id': 'A1001', 'items': [{'sku': 'S-1', 'qty': 2}], 'note': None}
exclude_none： {'order_id': 'A1001', 'items': [{'sku': 'S-1', 'qty': 2}]}
model_dump_json： {"order_id":"A1001","items":[{"sku":"S-1","qty":2}],"note":null}
回读相等： True
原文与重新序列化不同： True
```

最后两行要停一下。`back == order` 是 `True`，语义相同；但 `raw != back.model_dump_json()` 也是 `True`，原文里的空格和换行被压成了紧凑格式。语义相等不等于字节相等：`tool_calls` 的 `arguments` 解析成对象再用 `model_dump_json()` 写回去，键序和空白都变了，前缀就对不上，缓存的连续前缀也就断了。

导出参数一张表：

| 参数 | 作用 | 用在哪 |
|---|---|---|
| `by_alias=True` | 用别名导出 | 对外用驼峰、对内用下划线时 |
| `exclude_none=True` | 去掉 `None` 字段 | 回灌时省 token |
| `exclude={...}` / `include={...}` | 按字段裁剪 | 日志要比请求少一些字段时 |
| `indent=2` | 缩进 | 写给人看的日志 |
| `round_trip=True` | 按校验时的形态再导出 | 需要和输入逐字对上时 |

导出的形状也能改。`field_serializer` 改单个字段的形态，`computed_field` 加一个只在导出时出现的派生值，见 `surface_tour.py` 第 4 段：

```python
class Money(BaseModel):
    cents: int = Field(description="最小单位：分")

    @computed_field
    @property
    def yuan(self) -> str:
        return f"{self.cents / 100:.2f}"

    @field_serializer("cents")
    def dump_cents(self, v: int) -> str:
        return f"{v}分"
```

```
  dump      ： {'cents': '3900分', 'yuan': '39.00'}
  dump_json ： {"cents":"3900分","yuan":"39.00"}
```

对象本身还有两个常用操作，见 `surface_tour.py` 第 8 段：

```
  copy(update) ： title='政策' body='' draft=True
  exclude      ： {'title': '政策', 'draft': False}
```

`model_copy(update={...})` 造一份改了字段的副本，它不重新校验——改出来的值若不合法，要到下一次校验才暴露；`model_dump(exclude={...})` 按字段裁剪，日志里常用来去掉长文本。

## 四个出口

到这里，同一份声明已经有了四个用途：

| 出口 | 写法 | 用在哪 |
|---|---|---|
| 本地校验 | `Model.model_validate(payload)` | 拿到模型输出后的第一道检查 |
| 错误回灌 | `exc.errors()` | 校验失败后写给模型的提示 |
| JSON Schema | `Model.model_json_schema()` | 服务端约束采样、工具参数声明 |
| 配置 | `BaseSettings` 的子类 | 启动时读环境变量 |

第三个出口的用法是把 schema 直接放进请求体，见 `code/knowledge/ch05_pydantic/schema_for_api.py`：

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

厂商的严格模式对 schema 有三条硬要求：所有字段都进 `required`、`additionalProperties` 为 `false`、`$ref` 展开或服务端支持。`model_json_schema()` 默认只把没有默认值的字段放进 `required`，接严格模式前要自己补一次，见 `surface_tour.py` 第 9 段：

```python
schema = Verdict.model_json_schema()
strict_schema = {**schema, "required": list(schema["properties"]), "additionalProperties": False}
```

```
默认  ： {"properties": {"note": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Note"}, "reason": {"description": "理由", "title": "Reason", "type": "string"}}, "required": ["reason"], "title": "Verdict", "type": "object"}
严格版： {"additionalProperties": false, "properties": {"note": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": null, "title": "Note"}, "reason": {"description": "理由", "title": "Reason", "type": "string"}}, "required": ["reason", "note"], "title": "Verdict", "type": "object"}
```

严格版把 `note` 也放进了 `required`：可选字段在严格模式下必须显式给 `null`，模型因此不能省略它。这也是为什么给模型看的字段表里，可选字段写成 `str | None` 而不是"有默认值"。

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

```
必填字段： ['eligible', 'reason', 'confidence']
```

三行说明都不是"尽量准确"这类无法执行的表述：`eligible` 那条把三种取值对应到三种业务情况，模型拿到 `null` 这个许可才不会硬猜；`reason` 那条给了长度和格式两个可判定要求。

第四个出口是配置。配置和模型输出有同一个失效方式：读取时没人检查，用到一半才发现不对。把配置也声明成模型，检查就提前到启动那一刻，见 `code/knowledge/ch05_pydantic/settings_demo.py`：

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", extra="forbid")

    base_url: str = "http://127.0.0.1:8000/v1"
    api_key: str = Field(min_length=1)
    timeout_s: float = 30.0
    max_retries: int = 2
```

```
base_url='http://127.0.0.1:8000/v1' api_key='sk-demo' timeout_s=30.0 max_retries=2
base_url='http://127.0.0.1:8000/v1' api_key='sk-demo' timeout_s=3.5 max_retries=1
配置不合法： ('api_key',) String should have at least 1 character
```

`env_prefix="AGENT_"` 意味着读的是 `AGENT_API_KEY`、`AGENT_TIMEOUT_S` 这些变量；`extra="forbid"` 让拼错的变量名直接报错——拼错时不会报未知变量，只表现为配置不生效，然后在很远的地方以超时或 401 的形式出现。嵌套配置用 `env_nested_delimiter`，从文件读用 `_env_file`，两者都是 `SettingsConfigDict` 上的一个键。

## 失败分层与用例

校验失败之后做什么，取决于错在哪一层。四类混在一起统一重试，会出现两种坏结果：该失败的反复重试消耗调用费，该重试的直接失败。

| 错误层 | 例子 | 该做什么 |
|---|---|---|
| 语法 | 返回的是 markdown 包裹的 JSON | 重试，提示"只输出 JSON，不要代码块" |
| 结构 | 缺字段、多字段、类型不对 | 重试，回灌字段名、约束和实际值 |
| 约束 | 金额为负、枚举越界、超过 40 字 | 重试，回灌具体约束 |
| 业务 | 订单不存在、用户无权限 | 不重试，走业务分支或转人工 |

判断方法一句话：换一种写法就可能通过吗？能，属于前三层，重试；不能，属于业务层，别让它重试——订单不会因为措辞变了而存在，反复回灌只会拖到步数上限。pydantic 自己不做重试，也不该做：把重试写进校验器，校验就变成会发网络请求的东西。

单条失败只说明这一次不对，看不出哪类错在反复发生。把一批失败按字段与 `type` 归并，才知道该改提示词、改 schema，还是改业务分支：`reason` 大量报 `missing`，说明提示词没把"必须给理由"写成可判定要求；`confidence` 零星越界，更像偶发，加一次重试就够。计数的用途是排序，具体原因还要看 `input`。

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

同一条数据可能同时违反两条约束，只断言"抛了异常"测不出拒在哪一条，字段名把断言收紧。这组用例与第 4 章的提示词回归用例同类，一个测提示词、一个测结构，一起维护才能防止两边各走各的。

这一层挡不住的只有一样：内容对不对。一份带 `pattern`、`ge`、`min_length` 的结构看起来比自由文本可信，但约束全部作用在形状上；订单是否真实存在、用户有没有权限都要查库，塞进校验器只会让校验变慢、变难测。开放式问答没有稳定字段，硬套一个 `{"text": str}` 只是多一层包装，那类输出不该建模。

## 这一章建立的 8 件事

1. 手写校验只检查键在不在，类型漂移和多出字段都会漏过去。
2. `Field` 一张表覆盖约束：区间、长度、正则、说明、默认值、别名、导出排除。
3. 校验入口两个（字典 / JSON 字符串），整批用 `TypeAdapter`，顶层非对象用 `RootModel`。
4. `errors()` 的 `type`、`loc`、`msg`、`input` 是回灌的错误素材，`type` 用来分支。
5. 校验器三种：`field_validator` 的 before/after、`model_validator` 的 before/after；`context` 是递运行时参数的正规入口。
6. `model_config` 六项决定"入口有多严"：`strict`、`extra`、`populate_by_name`、`frozen`、`validate_assignment`、`str_strip_whitespace`。
7. `model_dump` 的 `by_alias`、`exclude_none`、`exclude` 决定导出形状，`field_serializer` 与 `computed_field` 决定导出内容。
8. `model_json_schema()` 接严格模式前要补 `required` 与 `additionalProperties`；`Field(description=...)` 让说明只写一次，`BaseSettings` 让配置在启动时报错。

## 下一章

结构定义好了，下一步是让模型能请求做事。第 6 章讲工具调用：模型只会生成文本，`tool_calls` 是它表达"我想做什么"的唯一格式；参数为什么是字符串、回灌要满足哪三条格式、以及一次往返里哪些部分模型根本管不着。

---

[← 第 4 章 · 提示词工程：从规则到结构化输出](./04-提示词工程-从规则到结构化输出.md)　｜　[卷 1 目录](./docs/INDEX.md#vol1)　｜　[第 6 章 · 工具调用：声明、请求与回灌 →](./06-工具调用-声明-请求与回灌.md)
