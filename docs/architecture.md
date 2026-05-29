# LocalNow 技术架构设计文档

## 项目定位

面向本地生活场景的短时活动规划与执行 Agent。

**核心价值**："帮你把事情做完"——不是搜索推荐，而是接收一句自然语言目标，输出可落地的完整方案，并在用户确认后自动完成所有预订/下单/通知动作。

**两个场景**：
- 家庭场景：用户 + 5岁孩子 + 减肥老婆，距离不远
- 朋友场景：4人（2男2女），下午4-6小时

---

## 系统本质判断

参考 Anthropic *Building Effective Agents*（2024.12）的 Workflow vs Agent 区分：

**本系统是 Workflow，不是自主 Agent。**

原因：执行路径可枚举、步骤可预测、有强制人工确认节点。  
LLM 负责语义理解和创意规划，工具负责所有需要精确性的事情（可用性/距离/价格），两者职责严格划分。

---

## 整体架构图

```
┌─────────────────────────────────────────────────────┐
│              Next.js Frontend (App Router)           │
│                                                      │
│  ChatInput → PlanCards → ConfirmModal → ExecProgress │
│       ↑                                              │
│  EventSource (SSE) ←── 实时节点执行状态               │
│  fetch / axios     ←── REST 请求响应                 │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / SSE
┌──────────────────────▼──────────────────────────────┐
│               FastAPI Backend                        │
│                                                      │
│  POST /session                 启动规划会话           │
│  GET  /session/{id}/stream     SSE 推送 Agent 进度   │
│  POST /session/{id}/confirm    用户确认方案           │
│  GET  /session/{id}/result     获取最终结果           │
└──────────────────────┬──────────────────────────────┘
                       │ in-process
┌──────────────────────▼──────────────────────────────┐
│            LangGraph Workflow Engine                 │
│                                                      │
│  parse_intent → build_constraints → generate_plans  │
│       ↑                                   ↓         │
│  replan ←(all unavailable)── check_availability     │
│                                           ↓         │
│                             ⏸ interrupt (HiL)       │
│                                           ↓         │
│                             execute_bookings (并行)  │
│                                           ↓         │
│                                  send_notification  │
│                                                      │
│  + Instructor 结构化输出                              │
│  + asyncio 并行工具调用                               │
│  + MemorySaver 断点恢复                               │
└──────────┬───────────────────────────────────────────┘
      ┌────┴────┐
┌─────▼───┐  ┌──▼──────────────────────────────────┐
│  Tools  │  │           LLM Factory               │
│ search  │  │  Anthropic / OpenAI / DeepSeek       │
│ check   │  │  Google / Ollama                     │
│ book    │  │  role: main（规划/执行）fast（解析/通知）│
│ notify  │  └─────────────────────────────────────┘
└─────┬───┘
┌─────▼───────────────────────────────────────────────┐
│  ChromaDB in-memory  +  Mock API JSON fixtures       │
│  语义检索（软偏好）    +  结构化过滤（硬约束）            │
└─────────────────────────────────────────────────────┘
```

---

## 规划策略

### 两阶段 Plan-and-Execute（Wang et al. 2023）

**阶段一 — Planner LLM（main model）**
- 输入：结构化约束（从自然语言提取）
- 输出：2套方案骨架（体验类型 + 场所类型，不指定具体门店）
- 技术：CoT prompt 引导约束推理，Instructor 强制结构化输出

**阶段二 — Tool Executor（并行）**
- 输入：方案骨架
- 输出：具体门店 + 实时可用性状态
- 技术：asyncio.gather 并行查询，结果注回 AgentState

**为什么不用纯 ReAct**：ReAct 每步重新推理 next action，长链条存在 lost in the middle 问题（Liu et al. 2023）。规划任务步骤有限且可枚举，Plan-and-Execute 全局视角更稳定。

TravelPlanner（Xie et al. ICML 2024）的实验提供了直接反面数据：ReAct 模式下 GPT-4 在多约束规划任务中最终通过率仅 **0.6%**，主要失败原因是工具调用死循环和上下文信息丢失。我们选择 Workflow 模式固定执行路径，用 LangGraph State 显式管理中间结果，规避了这类问题。

**LangGraph State 对应 TravelPlanner 的 NotebookWrite 工具**：TravelPlanner 发现 Agent 在多轮工具调用后会"遗忘"早期收集的信息，因此设计了专门的外部笔记工具。我们用 `AgentState` 中的 `availability_results`、`candidate_plans` 等字段持久化所有中间结果，不依赖 LLM 上下文记忆，解决了同一问题。

### LLM vs 工具的职责边界

| 任务 | 谁来做 | 原因 |
|------|--------|------|
| "减肥老婆" → low_calorie 约束 | LLM | 语义理解 |
| 生成"活动 + 餐厅"组合思路 | LLM | 创意 + 生活常识 |
| 查哪家餐厅有低卡菜单 | 工具（结构化过滤） | 精确性，LLM 不知道实时数据 |
| 17:30 那家餐厅有没有位 | 工具 | 实时状态 |
| 等位40分钟是否换方案 | LLM | 权衡判断 |

---

## 核心技术选型

### 1. LangGraph（编排）

三个 LCEL 无法解决的需求驱动选型：
- **持久化状态**：TypedDict + Annotated Reducer 控制每字段合并语义
- **Human-in-the-Loop**：`interrupt()` + MemorySaver 断点恢复，用户确认后从断点继续
- **条件回退**：Conditional Edges 处理"所有方案不可用→重规划"

### 2. Instructor + Pydantic v2（结构化输出）

业界标准 validation-retry loop（Jason Liu / instructor-ai）：
- LLM 输出不符合 schema 时，自动将 ValidationError 回注 prompt 让 LLM 自我修正
- 最多重试 3 次
- Plan 输出包含 `constraint_coverage` 字段，LLM 自声明每条约束是否满足（轻量级自我验证）

### 3. RAG + 结构化过滤（检索）

两类查询需求使用不同检索方式：

```
硬约束 → 结构化字段过滤
  kids_friendly=True, distance<=5km, available=True

软偏好 → ChromaDB 语义检索
  "轻松不累"、"适合聊天"、"有点小众"、"不要太吵"
```

ChromaDB in-memory，demo 规模（20-50条）无额外成本。

### 4. 显式约束打分（排序）

替代 LLM 排序，更透明可调试（参考 MT-Bench 可解释性要求）：

```python
score = (0.25 * preference_match
       + 0.20 * availability_score
       + 0.20 * route_efficiency
       + 0.15 * budget_score
       + 0.10 * rating_score
       + 0.10 * group_fit_score)
```

### 5. 结构化错误码 + Replanning

```python
class ToolErrorCode(str, Enum):
    NO_SEAT            = "NO_SEAT"
    TOO_FAR            = "TOO_FAR"
    OVER_BUDGET        = "OVER_BUDGET"
    DELIVERY_UNAVAIL   = "DELIVERY_UNAVAILABLE"
    CLOSED             = "CLOSED"
```

每种错误码对应精确的 Replanning 策略，不依赖 LLM 判断如何修复。

### 6. LLM Factory（多 provider）

LangChain BaseChatModel 统一接口，节点零感知切换：

| Provider | main | fast |
|----------|------|------|
| Anthropic | claude-sonnet-4-6 | claude-haiku-4-5 |
| OpenAI | gpt-4o | gpt-4o-mini |
| DeepSeek | deepseek-chat | deepseek-chat |
| Google | gemini-1.5-pro | gemini-1.5-flash |
| Ollama | llama3.1:70b | llama3.1:8b |

节点与 role 对应：
- `parse_intent` → fast
- `generate_plans` → main（核心推理节点）
- `rank_and_select` → fast
- `execute_bookings` → main（容错要求最高）
- `send_notification` → fast

### 7. Prompt Caching（Anthropic）

`generate_plans` 的 system prompt 约 1500 tokens，重规划时命中缓存，input token 费用降至 1/10：

```python
{"type": "text", "text": PLANNER_SYSTEM_PROMPT,
 "cache_control": {"type": "ephemeral"}}
```

### 8. FastAPI + SSE（前后端通信）

LangGraph 支持 `stream_mode="updates"` 逐节点流式输出，FastAPI 通过 SSE 转发到前端：
- SSE（单向推送）优于 WebSocket（双向），Agent 执行是单向的
- `sse-starlette` 库实现

### 9. Next.js + shadcn/ui（前端）

shadcn/ui 预制组件（Card/Dialog/Progress/Badge）直接使用，3天内保证 UI 质量。

---

## AgentState 设计

```python
class AgentState(TypedDict):
    # 输入
    user_message: str
    scenario: Literal["family", "friends"]

    # 约束（LLM 从自然语言提取）
    constraints: ConstraintSet

    # 规划（Annotated 追加语义，支持重规划积累）
    candidate_plans: Annotated[list[Plan], operator.add]
    availability_results: dict[str, AvailabilityResult]
    selected_plan: Plan | None

    # 执行
    user_confirmed: bool
    booking_results: Annotated[list[BookingResult], operator.add]

    # 控制
    replan_count: int          # 防止无限回退，最多2次
    error: str | None

    # 输出
    summary_message: str
```

---

## 工具清单

### 查询类（Agent 自动调用）
- `search_venues(type, location, radius, constraints)` → 活动场所列表
- `search_restaurants(location, radius, constraints)` → 餐厅列表
- `semantic_search_venues(query, filters)` → 语义检索（ChromaDB）
- `estimate_travel_time(origin, destination, mode)` → 路程时间

### 验证类（Agent 自动调用）
- `check_venue_availability(venue_id, time, party_size)` → 可用性 + 余票
- `check_restaurant_availability(restaurant_id, time, party_size)` → 座位 + 等位时长

### 执行类（用户确认后调用）
- `book_venue_tickets(venue_id, time, count)` → 购票
- `make_restaurant_reservation(restaurant_id, time, party_size)` → 订座
- `order_addon_service(type, location, delivery_time)` → 蛋糕/鲜花
- `send_message(recipient, content)` → 通知朋友/老婆

---

## 约束结构（两个场景）

```python
SCENARIO_CONSTRAINTS = {
    "family": {
        "activity": {
            "kids_friendly": True,
            "min_age_limit": 5,
            "prefer_indoor": True,
        },
        "restaurant": {
            "has_kids_menu": True,
            "has_low_calorie_options": True,
            "noise_level": ["quiet", "moderate"],
        },
        "logistics": {
            "max_distance_km": 5,
            "travel_mode": ["walk", "taxi"],
        }
    },
    "friends": {
        "activity": {
            "types": ["exhibition", "citywalk", "escape_room"],
        },
        "restaurant": {
            "group_friendly": True,
            "party_size": 4,
            "price_range": "mid",
        },
        "logistics": {
            "max_distance_km": 10,
            "travel_mode": ["taxi", "metro"],
        }
    }
}
```

---

## FastAPI 端点

```
POST /session                   创建规划会话，返回 session_id
GET  /session/{id}/stream       SSE 流：Agent 节点执行进度
POST /session/{id}/confirm      用户确认方案，触发执行阶段
GET  /session/{id}/result       获取完整结果和消息文本
```

---

## 完整技术栈

| 层级 | 技术 | 职责 |
|------|------|------|
| 前端框架 | Next.js 14 (App Router) | 页面路由 |
| UI 组件 | Tailwind CSS + shadcn/ui | 快速高质量 UI |
| 实时通信 | SSE (EventSource) | Agent 进度推送 |
| 后端框架 | FastAPI + uvicorn | 异步 API |
| SSE 库 | sse-starlette | FastAPI SSE 封装 |
| Agent 编排 | LangGraph | 状态图 + interrupt |
| 结构化输出 | Instructor + Pydantic v2 | LLM 输出验证重试 |
| 语义检索 | ChromaDB in-memory | 软偏好查询 |
| LLM 接入 | LangChain 多 provider | main/fast 双档 |
| 可观测性 | LangSmith | 全链路 trace |
| Mock 数据 | JSON fixtures + faker | 餐厅/活动数据 |

---

## 三天开发计划

| Day | 后端 / Agent | 前端 |
|-----|-------------|------|
| Day 1 | LangGraph 状态图骨架 + 全部 Tool + Mock API + ChromaDB | Next.js 初始化 + ChatInput + AgentProgress 骨架 |
| Day 2 | FastAPI 端点 + SSE 流 + 两个场景端到端跑通 + Replanning | PlanCards + ConfirmModal + useAgentStream hook |
| Day 3 | 异常处理完善 + LangSmith 接入 | ExecProgress + 前后端联调 + 样式打磨 |

---

## 参考来源

| 设计决策 | 来源 |
|---------|------|
| Workflow vs Agent 区分 | Anthropic *Building Effective Agents*（2024.12）|
| Plan-and-Execute 模式 | Wang et al. 2023 + LangGraph 官方教程 |
| Lost in the middle 问题 | Liu et al. 2023 |
| Instructor 结构化输出 | Jason Liu / instructor-ai |
| Prompt Caching | Anthropic API 文档 |
| Human-in-the-loop | LangGraph 官方文档 interrupt() |
| 显式打分优于 LLM 排序 | MT-Bench 可解释性要求（Zheng et al. 2023）|
| ReAct 在多约束规划中的失败率（反面证据） | Xie et al. *TravelPlanner* ICML 2024 |

---

## 与 TravelPlanner 的对比分析

> 参考：Xie et al. "TravelPlanner: A Benchmark for Real-World Planning with Language Agents"，ICML 2024 Spotlight。[ArXiv 2402.01622](https://arxiv.org/abs/2402.01622)

### 定位差异

| 维度 | TravelPlanner | LocalNow |
|------|--------------|----------|
| 目标 | 学术基准，评测 LLM 规划能力上限 | 产品 Demo，展示 Agent 编排工程实践 |
| Agent 模式 | ReAct（自主决策工具调用顺序） | Workflow（执行路径固定可枚举） |
| 数据规模 | 380 万条真实数据 | 80 条 Mock 数据 |
| 时间跨度 | 多天跨城市旅行 | 半天本地活动 |
| 约束评估 | Micro/Macro Pass Rate 定量指标 | LLM 自声明 constraint_coverage |

### 我们的选型为何正确

TravelPlanner 的核心实验结论：ReAct 模式下 GPT-4 最终通过率仅 0.6%，失败原因集中在两点：
1. **工具调用失控**：陷入死循环，30 步内未能完成规划
2. **上下文信息丢失**：多轮工具调用后早期结果被推出上下文窗口

LocalNow 的架构设计对应解决了这两个问题：
- Workflow 固定路径 → 消除工具调用死循环
- LangGraph State 显式持久化 → 消除信息遗忘

### 三层约束分类的启发

TravelPlanner 将约束分为三层：硬约束（用户明确指定）、常识约束（隐含推理，如"同天活动同城市"）、环境约束（动态状态，如"餐厅无空位"）。

LocalNow 的映射：
- 硬约束 → `ConstraintSet` 显式建模
- 常识约束 → 交给 LLM prompt 处理（接受此简化，demo 规模合理）
- 环境约束 → `AvailabilityResult` + replan 机制

### 可借鉴但尚未实现

`constraint_coverage: dict[str, bool]` 字段已预留（`Plan` 模型中），后续可在 `evaluate.py` 中加入方案质量评估，计算约束满足率，与 TravelPlanner 的 Micro Pass Rate 对应。
