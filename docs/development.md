# LocalNow 开发文档

记录各模块的技术实现、关键决策和注意事项。

---

## Step 1：项目骨架与环境配置

### 目录结构

```
LocalNow/
├── backend/
│   ├── agent/      # LangGraph 状态图和节点
│   ├── tools/      # 工具函数（搜索/验证/执行/通知）
│   ├── llm/        # LLM 工厂（多 provider 切换）
│   ├── models/     # Pydantic 数据模型
│   ├── data/       # Mock 数据和生成脚本
│   ├── prompts/    # Prompt 模板文件
│   ├── api/        # FastAPI 入口
│   └── config.py   # 全局配置（读取 .env）
├── frontend/       # Next.js 14 前端
└── docs/           # 文档
```

### 包管理：uv

选择 uv 而非 pip/poetry，原因：Astral 出品，依赖解析和安装速度比 pip 快 10-100 倍，lockfile 机制更可靠，2024 年已成为 Python 工具链新标准。

```bash
uv sync          # 安装所有依赖
uv run python x  # 在虚拟环境中执行
```

### 前端：Next.js + shadcn/ui

```bash
npx create-next-app@latest frontend  # TypeScript + Tailwind + App Router
npx shadcn@latest init               # 预制 UI 组件库
```

shadcn/ui 提供 Card、Dialog、Progress 等现成组件，避免在 hackathon 中花时间写基础样式。

### 关键配置

每个子目录必须有 `__init__.py` 才能被 Python 识别为包。pyproject.toml 需要显式声明包路径：

```toml
[tool.hatch.build.targets.wheel]
packages = ["agent", "api", "tools", "llm", "models", "prompts"]
```

---

## Step 2：Pydantic 数据模型

### 三个核心文件

| 文件 | 内容 |
|------|------|
| `config.py` | 读取 .env，全局单例 `config` 对象 |
| `models/schemas.py` | 所有业务数据模型 |
| `agent/state.py` | LangGraph AgentState |

### 模型设计要点

**schemas.py** 定义了整个系统的数据契约，分为五层：

```
枚举层    Scenario / ActivityCategory / ToolErrorCode 等
地理层    Coordinates
实体层    Venue / Restaurant（场所和餐厅）
约束层    ConstraintSet（从用户自然语言提取的结构化约束）
规划层    Plan / TimelineItem（Agent 生成的方案）
执行层    BookingResult / ToolError（执行结果）
API 层    UserRequest / SessionResponse（FastAPI 用）
```

**agent/state.py** 中 `Annotated` + Reducer 是 LangGraph 特有设计：

```python
# operator.add 表示追加语义（新值追加到列表末尾，不覆盖）
candidate_plans: Annotated[list[Plan], operator.add]
booking_results: Annotated[list[BookingResult], operator.add]

# 无 Annotated 表示覆盖语义（新值直接替换旧值）
selected_plan: Plan | None
user_confirmed: bool
```

重规划时旧方案不丢失，保留完整历史便于调试。

### constraint_coverage 字段

`Plan` 模型包含 `constraint_coverage: dict[str, bool]`，要求 LLM 生成方案时自己声明每条约束是否满足：

```python
# LLM 输出示例
constraint_coverage = {
    "kids_friendly": True,
    "low_calorie": True,
    "max_distance_5km": True,
}
```

这是轻量级自我验证，替代独立的 LLM-as-Judge 评估器，适合 demo 规模。

---

## Step 3：Mock 数据层

### 数据规模设计

模拟"用户 5km 范围内的候选池"，而非整个上海：

- 餐厅：50 条（8 手工种子 + 42 LLM 生成）
- 场所：30 条（6 手工种子 + 24 LLM 生成）

每个场景过滤后约 15-20 条有效候选，满足 Agent 规划和 ChromaDB 语义检索的需求。

### 数据生成策略选型

```
方案对比：
  找开源数据集  → 中国本地生活数据几乎无合法开源数据，清洗成本高
  Faker 生成   → tags 语义贫乏，ChromaDB 检索效果差
  LLM 生成     → tags 自然语言丰富，贴近用户真实描述  ← 选择此方案
```

使用 Ollama 本地模型（qwen3:8b）生成，原因：免费、中文效果好、qwen3 是当前最新版本。

### 手工种子数据的作用

手工编写的 8 条餐厅和 6 条场所有两个刻意设计：
- `r001` 外婆家的 17:30 时段没有空位 → 确保 Demo 时 fallback 逻辑必然触发
- `v004/v005/v006` 的 `kids_friendly=false` → 家庭场景过滤后自动排除

手工数据放在合并数组的前面，保证关键场景记录在 ChromaDB 检索中优先出现。

### 分批生成

单次生成 42 条餐厅约需 8400 tokens 输出，超过 `max_tokens=4096` 限制导致 JSON 截断。解决方案：每批 15 条，分批生成再合并。

```python
def generate(prompt, label, total, batch_size=15):
    # 分批调用，每批独立重试，互不影响
```

### ID 管理

不信任 LLM 生成的 ID，合并后统一重新分配：

```python
def reassign_ids(data, prefix):
    for i, item in enumerate(data):
        item["id"] = f"{prefix}{i+1:03d}"  # r001, r002 ...
```

### ChromaDB 的角色

两类查询使用不同检索方式：

```
硬约束（精确）→ JSON 结构化字段过滤
  has_kids_menu=True, distance<5km, available=True

软偏好（模糊）→ ChromaDB 语义检索
  "轻松不累"、"适合聊天"、"有点小众"
```

tags 字段是语义检索的核心输入，这也是选择 LLM 生成数据而非 Faker 的根本原因。

### 数据评估

`data/evaluate.py` 对生成数据做三层验证：
1. **结构验证**：加载进 Pydantic 模型，字段缺失/类型错误立即报出
2. **分布验证**：家庭/朋友场景覆盖各 > 40%，价格区间合理
3. **LLM 语义抽查**：用 qwen3:8b 检查名称/tags/字段是否逻辑一致

评估结论由代码计算得出，不写死文字，避免结论与实际不符。

---

## Step 4：Tool 层（进行中）

Tool 层分五个文件，职责分离：

| 文件 | 职责 |
|------|------|
| `tools/store.py` | ChromaDB 初始化与检索接口（已完成） |
| `tools/search.py` | 两阶检索：硬约束过滤 + 语义排序（已完成） |
| `tools/availability.py` | 查询场所/餐厅的时间段可用性（已完成） |
| `tools/booking.py` | 执行预订/购票/下单动作（待写） |
| `tools/notification.py` | 发送行程确认通知（待写） |

### tools/store.py

**核心设计**：`get_store()` 惰性单例

```python
_store: DataStore | None = None

def get_store() -> DataStore:
    global _store
    if _store is None:
        _store = DataStore()
    return _store
```

惰性初始化而非模块级 `store = DataStore()`，避免测试环境或数据文件未生成时 import 就报 `FileNotFoundError`。

**ChromaDB 初始化**：

```python
client = chromadb.EphemeralClient()   # 纯内存，语义比 Client() 更明确
venue_col = client.create_collection("venues", embedding_function=_EF)
venue_col.add(
    ids=[v["id"] for v in venues_raw],
    documents=[f"{v['name']} {' '.join(v.get('tags', []))}" for v in venues_raw],
    metadatas=[_venue_metadata(v) for v in venues_raw],
)
```

嵌入文本 = `名称 + tags 拼接`，坐标等嵌套字段不进 metadata（ChromaDB 只支持 str/int/float/bool），而是保留在 `_raw` dict 里重建完整 Pydantic 对象。

**版本检查**：chromadb `$in` 操作符在 0.5.0 之前有 bug，import 时立即校验：

```python
major, minor, *_ = (int(x) for x in chromadb.__version__.split(".")[:3])
if (major, minor) < (0, 5):
    raise RuntimeError(f"chromadb >= 0.5.0 required, found {chromadb.__version__}")
```

### tools/search.py

**两阶检索原则**：

```
硬约束（kids_friendly、距离、预算等）→ ChromaDB where 子句精确过滤
软偏好（"安静"、"适合聊天"等自然语言）→ 向量相似度排序
两者在一次 query() 调用中完成
```

**约束映射规则**：仅当约束为 True / 非空时才加入 where 过滤，避免过度收窄候选池：

```python
kids_friendly = True if ac.kids_friendly else None   # False 不过滤
```

朋友场景（`kids_friendly=False`）不加过滤，所有场所进候选池，由语义排序决定优先级。

**`preferred_categories` 在 Python 层过滤**：与其他 AND 条件组合时 ChromaDB `$in` 嵌套层级较深，行为无明确保证；数据量小（30条）Python 过滤无性能问题。

---

## Step 5：LangGraph 状态图

> 待补充

---

## Step 6：FastAPI + SSE

> 待补充

---

## Step 7：Next.js 前端

> 待补充
