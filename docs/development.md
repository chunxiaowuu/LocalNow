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
| `tools/booking.py` | 执行预订/购票/下单动作（已完成） |
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

### tools/availability.py

两个对外接口 + 两个内部 helper：

```python
check_restaurant_availability(restaurant_id, requested_time, party_size) → AvailabilityResult
check_venue_availability(venue_id, requested_time) → AvailabilityResult

_parse_time(t: str) → int           # "17:30" → 1050 分钟，便于大小比较
_next_available_slot(slots, time)   # 找第一个晚于 time 的时间段
```

`AvailabilityResult.retryable` 字段驱动 replan 策略：
- `retryable=True`（时间段冲突）→ 换时间段重试
- `retryable=False`（人数超限 / 场所关闭）→ 换地点

### tools/booking.py

执行预订，调用前先做 final check，防止规划→执行窗口期失效：

```python
book_restaurant(restaurant_id, time_slot, party_size, *, original_time_slot=None) → BookingResult
book_venue(venue_id, party_size, requested_time) → BookingResult
```

`original_time_slot` 与 `time_slot` 不同时，`BookingResult.fallback_applied=True`，
前端据此展示"已为您调整时间"提示。

**全部为 Mock 实现**：无真实 API 调用。工具层面向接口设计，生产环境替换内部实现即可，LangGraph 图和测试不受影响。

**测试覆盖**：36 个 pytest 用例（19 availability + 10 booking + 7 notification），全部通过。

---

## Step 5：LangGraph 状态图

### 文件结构

| 文件 | 职责 |
|------|------|
| `llm/factory.py` | LLM 工厂，`get_llm(role)` 返回对应 provider 的 ChatModel |
| `prompts/intent_parser/system.txt` | parse_intent 节点的 system prompt |
| `prompts/planner/system.txt` | generate_plans 节点的 system prompt（含行程时间估算指令） |
| `prompts/notifier/system.txt` | send_notification 节点的 system prompt |
| `agent/nodes.py` | 所有节点函数 |
| `agent/graph.py` | 图的组装、条件边、编译 |

### LLM 工厂

`get_llm(role)` 通过 `@lru_cache` 缓存实例，避免重复初始化：

```python
# main → 规划节点（强推理），fast → 解析/通知节点（速度优先）
_MODEL_MAP = {
    "anthropic": ("claude-sonnet-4-6", "claude-haiku-4-5-20251001"),
    "openai":    ("gpt-4o",            "gpt-4o-mini"),
    "deepseek":  ("deepseek-chat",     "deepseek-chat"),
    "ollama":    ("qwen3:8b",          "qwen3:8b"),
}
```

切换 provider 只需改 `.env` 里的 `LLM_PROVIDER`，节点代码不动。

### 结构化输出：with_structured_output

所有需要结构化 LLM 输出的节点统一使用 LangChain 的 `with_structured_output(Schema)`，
不引入 Instructor，避免与 LangChain ChatModel 的接口混用问题：

```python
# parse_intent
llm = get_llm("fast").with_structured_output(ConstraintSet)
constraints = llm.invoke([SystemMessage(...), HumanMessage(...)])

# generate_plans（list 需要 wrapper model）
class _PlansResponse(BaseModel):
    plans: list[Plan]

llm = get_llm("main").with_structured_output(_PlansResponse)
response = llm.invoke([...])
```

`with_structured_output` 在 Anthropic 下用 tool_use，在 OpenAI 下用 function calling，
底层自动处理，节点代码与 provider 无关。

### 图结构与执行路径

```
START → parse_intent → search_candidates → generate_plans → check_availability
                                                                    │
                              ┌─────────────────────────────────────┤
                              │ 有可用方案                            │ 全不可用
                              ▼                                      ▼
                         human_review ◄──────────────── increment_replan → generate_plans
                         (interrupt)       用户拒绝        （计数 +1）
                              │
                              │ 用户确认
                              ▼
                      execute_bookings → send_notification → END
                                                                │
                         handle_error → END ◄── replan 超限 ───┘
```

### AgentState 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `candidate_venues` | `list[dict]` | search_candidates 填入，后续只读 |
| `candidate_restaurants` | `list[dict]` | 同上 |
| `candidate_plans` | `Annotated[list[Plan], operator.add]` | 追加语义，replan 保留历史 |
| `availability_results` | `dict[str, AvailabilityResult]` | key 为场所/餐厅 id |
| `replan_count` | `int` | 已重规划次数，超过 `max_replan_count` 进 handle_error |

### HiL（Human-in-the-Loop）实现

暂停点由 `human_review` 节点内部的 `interrupt(payload)` 控制，
payload 携带候选方案数据，前端直接展示：

```python
def human_review(state: AgentState) -> dict:
    plans = state["candidate_plans"][-config.max_candidate_plans:]
    payload = interrupt({"plans": [p.model_dump() for p in plans]})
    # 前端 POST /confirm 后从这里恢复，payload 即用户传入的确认数据
    confirmed = payload.get("confirmed", False)
    selected_id = payload.get("selected_plan_id", "")
    ...
```

`MemorySaver` 将 interrupt 时的完整 state 持久化，resume 后从断点继续，
不需要重跑前面的节点。

---

## Step 6：FastAPI + SSE

### 文件结构

| 文件 | 职责 |
|------|------|
| `api/main.py` | FastAPI 入口，CORS 中间件，挂载 router |
| `api/session_store.py` | 内存会话存储，状态机管理 |
| `api/routes.py` | 4 个 API 端点 |

### 4 个端点

| 端点 | 说明 |
|------|------|
| `POST /session` | 创建会话，返回 session_id |
| `GET /session/{id}/stream` | SSE 长连接，推送 Agent 节点进度 |
| `POST /session/{id}/confirm` | 用户确认/拒绝方案，存储 resume payload |
| `GET /session/{id}/result` | 获取最终结果（done 状态后可用） |

### 会话状态机

```
created → running → interrupted → resuming → running → done
                                                    └→ error
```

### 两段式 SSE 设计

HiL interrupt 把 SSE 流分成两段：

```
第一段：POST /session → GET /stream → 运行到 interrupt → SSE 发 interrupt 事件 → 连接关闭
第二段：POST /confirm（存储用户选择）→ GET /stream → Command(resume=payload) → 运行完成 → done
```

每次 `/stream` 根据 session.status 决定传什么给 graph.astream：
- `created` → 传初始 state
- `resuming` → 传 `Command(resume=payload)`

### SSE 事件格式

| 事件名 | 数据 | 时机 |
|--------|------|------|
| `node_update` | `{node, message}` | 每个节点执行完毕时 |
| `heartbeat` | `{}` | 每 5 秒，无节点事件时保活连接 |
| `interrupt` | `{plans: Plan[]}` | HiL 暂停，展示方案给用户 |
| `done` | `{summary, booking_results}` | 图执行完毕 |
| `error` | `{message}` | 发生异常 |

### asyncio.Queue 解耦设计（SSE 保活）

**问题**：`graph.astream()` 只在节点完成后才 yield chunk。`generate_plans` 用本地 Ollama 需要数分钟，期间若 LLM 调用阻塞 asyncio 事件循环，sse-starlette 的 ping 无法发出，TCP 连接因长时间无数据被浏览器判断为超时断开。

**解决方案**：用 `asyncio.Queue` 把图的执行与 SSE 生成器解耦：

```python
queue = asyncio.Queue()

async def run_graph():
    async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
        await queue.put(("chunk", chunk))
    await queue.put(("done", None))

asyncio.create_task(run_graph())  # 图在独立 task 里跑

while True:
    try:
        kind, payload = await asyncio.wait_for(queue.get(), timeout=5.0)
    except asyncio.TimeoutError:
        yield {"event": "heartbeat", "data": "{}"}  # 保活
        continue
    # 处理 chunk / done / error ...
```

前端注册 `heartbeat` 监听器并忽略，不影响 UI 状态。

---

## Step 7：Next.js 前端

### 文件结构

```
app/
  page.tsx                       # 主页面（Client Component，持有状态机）
  layout.tsx                     # 根布局
components/
  planner/
    ChatInput.tsx                # 用户输入框 + 示例按钮
    AgentProgress.tsx            # Agent 执行进度列表
    PlanCards.tsx                # 候选方案卡片（含 Timeline、费用、约束覆盖）
    ExecSummary.tsx              # 执行结果 + 行程通知消息
lib/
  types.ts                       # TypeScript 类型（与后端 Pydantic schema 对应）
  api.ts                         # API 客户端（createSession / openStream / confirmPlan）
```

### 前端状态机

```typescript
type Phase =
  | { kind: "input" }
  | { kind: "running"; events: ProgressEvent[] }
  | { kind: "interrupted"; events: ProgressEvent[]; plans: Plan[]; sessionId: string }
  | { kind: "executing"; events: ProgressEvent[] }
  | { kind: "done"; summary: string; bookingResults: BookingResult[] }
  | { kind: "error"; message: string }
```

每个 `phase` 对应一个 UI 界面，状态切换完全由 SSE 事件驱动：

```
input ──提交──→ running ──interrupt──→ interrupted ──确认──→ executing ──done──→ done
                                           └──拒绝──→ running（重规划）
```

### SSE 前端处理

```typescript
const es = openStream(sessionId);

es.addEventListener("node_update", (e) => {
  // 追加进度条目，当前步骤转圈
  setPhase(prev => ({ kind: "running", events: [...prev.events, newEvent] }));
});

es.addEventListener("interrupt", (e) => {
  es.close();  // 关闭第一段 SSE
  setPhase({ kind: "interrupted", plans: data.plans, sessionId });
});

// 用户确认后重开 SSE（第二段）
await confirmPlan(sessionId, true, planId);
startStream(sessionId);  // 传 Command(resume=...) 给后端
```

---

## Step 8：数据模型扩展 + Gemini 接入 + 可用性修复

### 数据模型扩展（schemas.py / state.py）

为接入高德真实 API 和结构化 UI 输入做准备，扩展了以下模型：

**新增枚举 `ActivityPreference`**：对应前端 UI 偏好标签（nature / cultural / museum / social / food / family），与后端 `ActivityCategory` 解耦——前端标签是用户语言，后端分类是系统语言，中间由 `parse_intent` 做映射。

**`ConstraintSet` 新增字段**：

| 字段 | 说明 |
|------|------|
| `city: str = "上海"` | 供高德 API 查询使用 |
| `start_time: str = "10:00"` | 方案起始时间 |
| `duration_days: int = 1` | 多天行程支持 |
| `food_focused: bool = False` | 食物偏好标签激活时，多拉餐厅候选 |

**`Venue` 新增 `typical_visit_minutes: int = 90`**：按 `ActivityCategory` 分类给出默认游玩时长，供 `generate_plans` 做时间预算约束。

**`TimelineItem` 新增 `day: int = 1`**：多天行程中每个活动标注所属天数，配合每天独立时长验证。

**新增 `PlanRequest`**：结构化 UI 请求模型（含 `start_date / end_date / preferences / max_distance_km` 等），与现有 `UserRequest(message: str)` 共存，Phase 8 接入 API 时替换。

**新增 `FreeTextConstraints`**：LLM 从 `free_text` 中提取的补充约束，所有字段可选（`None` 表示未提及），避免覆盖结构化字段的默认值。

**`AgentState` 新增字段**：`user_request`、`preference_weights`、`day_clusters`、`available_activity_minutes_per_day`，详见架构文档 AgentState 设计。

---

### Gemini LLM 接入（llm/factory.py / config.py）

**`config.py` `.env` 路径修复**：将 `env_file=".env"` 改为 `Path(__file__).parent / ".env"`（绝对路径）。原始相对路径以 uvicorn 的工作目录为准，从项目根目录启动时找不到 `backend/.env`，导致 `llm_provider` 回落默认值 `"anthropic"` 并因 key 未设置报认证错误。

**新增 `gemini` provider**：使用 `langchain_openai.ChatOpenAI` + Google AI Studio 的 OpenAI 兼容端点（`https://generativelanguage.googleapis.com/v1beta/openai/`），无需额外 SDK。main/fast 均使用 `gemini-2.5-flash`。

```python
if provider == "gemini":
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=model_name,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        api_key=config.google_api_key,
        temperature=0,
    )
```

---

### 可用性检查与预订一致性修复

发现三处逻辑不一致，统一修复：

**问题**：`check_availability` 和 `execute_bookings` 不看 `booking_required`，但 `_plan_is_available` 看，导致 `booking_required=False` 的餐厅跳过可用性检查，方案被错误认为可用推给用户，到预订阶段才失败。

**修复原则**：

| 函数 | `booking_required=True` | `booking_required=False` |
|------|------------------------|--------------------------|
| `check_availability` | 检查时间槽可用性 | 只检查营业时间 |
| `_plan_is_available` | 检查所有餐厅/场所（不看此字段） | 同左 |
| `execute_bookings` | 执行订座 | 跳过（walk-in，无需预约） |

**`human_review` 只展示完全可用方案**：将 `plan_is_available` 提取为模块级函数 `_plan_is_available`，`human_review` 在 `interrupt()` 前过滤，只把每一项都确认可用的方案推给用户。

---

### generate_plans 重规划改进（nodes.py）

**问题**：重规划时 LLM 不知道上次哪些时间段失败，继续生成相同时间，反复触发 `max_replan_count` 上限后报"无法找到合适方案"。

**修复**：两处改进：
1. 餐厅候选格式化展示 `available_slots`：`可预约时段：17:30、18:00、18:30、19:00`，LLM 直接从有效时段选
2. 重规划时注入失败原因：`上次规划失败，请避开以下时段/场所：- 老正兴菜馆 15:55 无空位`
