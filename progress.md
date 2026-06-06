# LocalNow 开发进度

> 当前分支：`feature/amap-integration`
> 上次更新：2026-06-06

---

## 整体计划

```
Phase 1  数据模型扩展                    ✅ 完成（已合并 main）
Phase 2  工具层新文件                    ✅ 完成（已提交）
Phase 3  配置（amap_api_key）            ✅ 完成
Phase 4  parse_intent 混合模式           ✅ 完成（已提交）
Phase 5  search_candidates 真实召回      ✅ 完成（已提交）
Phase 6  Prompt 更新                     待做（planner system prompt 未更新）
Phase 7  generate_plans + 时间验证       待做
Phase 8  API 层（PlanRequest 接入）      ✅ 完成（已提交）
Phase 9  集成测试                        进行中（手动测试阶段）
```

**当前测试状态**：116 个单元测试全部通过

---

## 本次会话重要改动（未提交）

### 冷启动/冷门检索：餐饮维度的语义降级阶梯

**问题**：用户提具体诉求"我想吃爆啦兔头面"，但本地无完全匹配场所。原实现 `special_requirements` 是信息黑洞——LLM 提取出来后既没驱动高德搜索关键词，也没进 planner prompt，搜索退化成通用 `"餐厅 美食 老字号"`。

**方案（3 层语义降级阶梯）**：
1. **提取阶梯**（`prompts/intent_parser/system.txt` + `schemas.py`）：LLM 把"爆啦兔头面"转成 `cuisine_request`（原话）+ `cuisine_keywords` 检索阶梯（具体→宽泛 `["兔头面","川菜面馆","特色面馆","面馆"]`）
2. **逐级检索**（`agent/nodes.py` `_fetch_restaurants_laddered` + `tools/amap_http.py`）：沿阶梯逐级搜高德，命中即停；记录 `{requested, matched_term, exact}`。`fetch_restaurants` 新增 `keywords` / `allow_mock_fallback` 参数，阶梯期间抑制 mock 兜底，便于继续降级
3. **透明推荐**（`generate_plans`）：prompt 告知 LLM 原始诉求 + 是否精确命中；降级命中时挑选最接近的人气餐厅（按 rating 排序），并在 notes 写明"未找到 XXX，这是相近推荐"

**配套**：
- `parse_replan_feedback` / `_ReplanConstraintUpdate` 也支持重规划时改餐饮（"餐厅换成火锅"），复用 replan→search_candidates 回路
- `special_requirements` 现在也进 planner prompt（部分惠及场所维度）
- 新增 state 字段 `cuisine_match`

**已知缺口**：目前只做了**餐饮维度**。场所/活动维度的冷门检索（如"想看莫奈特展""某家特定密室"）走的是 `preferred_categories` 固定关键词，同样会冷启动失败——是对称的待办项。

---

### Bug 修复：城市选择恒返回上海结果（已提 PR，分支 `fix/city-center-geocoding`）

**根本原因**：`search_candidates` 用 5 城 hardcoded dict 取距离过滤中心点，未命中城市静默 fallback 上海坐标，导致目标城市场所被 haversine 全过滤，候选池空，LLM 幻觉生成上海场所。

**修复**：`amap_http.py` 新增 `geocode_city()`——先查 15 城缓存，未命中调高德 Geocoding API 动态解析并缓存；`nodes.py` 改用之，删除 hardcoded dict。境外城市（Zurich）仍受限于高德 API 覆盖范围，记为待办。

---

### Bug 修复：重规划候选池不刷新，方案与上次雷同

**根本原因**：用户拒绝方案后，图路由直接跳回 `generate_plans`，跳过了 `search_candidates`。候选场所池完全未变，LLM 在同一批场所里重新组合，加上 `temperature=0`，结果高度雷同。即使用户反馈"换成公园"，若原始偏好没有 park 类型，候选池里也根本没有公园。

**修复**：

新增 `parse_replan_feedback` 节点（`agent/nodes.py`）：
- 用 fast LLM 从反馈文字提取 `add_categories` / `remove_categories` / `budget_per_person` / `max_distance_km`
- 更新 `constraints.activity.preferred_categories` 和 `preference_weights`

重写图路由（`agent/graph.py`）：
- 用户拒绝路径：`increment_replan` → `parse_replan_feedback` → `search_candidates`（刷新候选池）→ `generate_plans`
- availability 全失败路径：`increment_replan` → `generate_plans`（维持原行为，无用户反馈可解析）
- 区分依据：`_route_after_increment_replan` 检查 `replan_feedback` 是否非空

`generate_plans` 补充（`agent/nodes.py`）：
- 重规划时在 prompt 里注入"已展示给用户的场所，请优先选择新场所"列表，防止候选池有重叠时 LLM 仍复用旧场所

---

### Bug 修复：feedback 未传入 LangGraph

**根本原因**：`ConfirmRequest` Pydantic 模型没有 `feedback` 字段，前端发来的 `feedback` 被 Pydantic 丢弃，`resume_payload` 里也没有存，导致 `human_review` 里 `payload.get("feedback", "")` 永远是空字符串，LLM 收不到任何反馈。

**修复**：
- `models/schemas.py`：`ConfirmRequest` 新增 `feedback: str = ""`
- `api/routes.py`：`resume_payload` 新增 `"feedback": body.feedback`

---

### 架构重大转变：RAG → 高德 API 直接召回

**已废弃**（遗留代码，主流程不再调用）：
- `tools/store.py` — ChromaDB 向量检索，只剩 `booking.py`（mock）还引用
- `tools/search.py` — 两阶检索包装，主流程已不再 import
- `tools/availability.py` — `check_venue/restaurant_availability`，被内联替代

**新架构**：高德 `/v3/place/text` 关键词召回 → haversine 距离过滤 → 程序打分 → greedy 地理聚类

相关文档已更新：`docs/architecture.md`、`docs/development.md` Step 9

---

### Phase 4：parse_intent 混合模式（`agent/nodes.py`）

两条路径：
- **PlanRequest 路径**（新 UI 提交）：偏好标签直接映射 category + 权重，零 LLM；仅 `free_text` 非空时调 fast LLM 提取 `FreeTextConstraints`
- **旧 UserRequest 路径**（纯文字输入）：全量 LLM 提取，行为不变

偏好映射：
```
cultural → [museum, exhibition, citywalk]
nature   → [park, citywalk]
family   → [aquarium, kids_center, park]  → kids_friendly=True
food     → []（food_focused=True）
```

---

### Phase 5：search_candidates 真实召回（`agent/nodes.py`）

- 改为 `async def`，`asyncio.gather + asyncio.to_thread` 并行调高德两路数据
- haversine 距离过滤（城市中心坐标，因高德返回 `distance_km=0`）
- 程序打分：`rating×0.35 + budget_fit×0.20 + 偏好权重×0.45`
- `greedy_cluster` 按 `duration_days` 分组写入 `day_clusters`

---

### Bug 修复：check_availability + execute_bookings 不再查 mock store

**根本原因**：高德 API 返回真实场所 ID（如 `B00156NVZG`），mock store 只有 `v001`/`r001`，ID 不匹配导致所有可用性检查返回"场所不存在"，触发无限重规划直到 handle_error。

**修复**（`agent/nodes.py`）：
- `check_availability` → 新增 `_check_hours()`（正则解析 opening_hours）和 `_check_slots()`（用 available_slots），完全绕过 store
- `execute_bookings` → 直接从候选数据构造 `BookingResult`，detail 标注"演示模式，请前往官方渠道完成"

---

### Phase 8：API 层 PlanRequest 接入

**后端**（`api/routes.py`、`api/session_store.py`）：
- `POST /session` 自动识别格式：`{message: str}` 走旧路径，`{start_date, ...}` 走 PlanRequest 路径
- `session_store.Session` 新增 `user_request: dict` 字段

**前端**（新建 `components/planner/PlannerInput.tsx`）：
- 日期范围、人数步进器、城市、偏好 pill、出行方式 pill、补充说明

---

### 重规划 UX 升级

**新增 state 字段**：`replan_feedback: str`、`replan_base_plan_id: str`

**前端交互**（`PlanCards.tsx`）：
- 选了方案：`[在此基础上调整]` → 展开反馈区，显示模式切换条
  ```
  [ 基于「方案标题」调整 ] | [ 全部重新规划 ]
  ```
- 未选方案：`[重新规划]` → 直接进入全部重规划模式

**后端 prompt**（`agent/nodes.py` `generate_plans`）：

| 模式 | 指令 |
|------|------|
| 基于方案调整 | "用户选择「XXX」作为调整起点（时间线摘要），保留未提异议部分，只修改：{feedback}" |
| 全部重规划 | "用户对上次所有方案都不满意，根据反馈重新设计：{feedback}" |

反馈指令放在 prompt **最前面**，优先级高于候选列表和约束条件。

---

## 遇到的重要问题与解法

### P1：高德 API 返回 `biz_ext: []` 而非 `{}`，导致所有场所映射静默失败

**现象**：`fetch_venues` / `fetch_restaurants` 调用成功（HTTP 200），但返回场所列表为空。

**原因**：高德 `extensions=base` 模式下，无商业数据的场所 `biz_ext` 字段返回空列表 `[]` 而非空对象 `{}`。代码里 `poi.get("biz_ext", {}).get("cost", "0")` 对 `[]` 调用 `.get()` 抛 `AttributeError`，内层 `try/except` 静默跳过每个 POI，最终 `venues = []`。

**修复**：新增 `_biz(poi) -> dict` 辅助函数，检查类型是否为 dict，否则返回 `{}`。同时改 `extensions=base` 为 `extensions=all` 获取评分/价格/营业时间。

---

### P2：check_availability 全部返回"场所不存在"，导致无限重规划直到 handle_error

**现象**：用户提交请求后，后端日志显示多次重规划，最终输出"未能找到合适的方案"。

**原因**：`search_candidates` 换成高德 API 后，候选场所 ID 为真实高德 ID（如 `B00156NVZG`）；但 `check_availability` 仍调用 `tools/availability.py` 里的 `check_venue_availability(id)`，该函数通过 `get_store().venues.get(id)` 查 mock ChromaDB，mock 数据只有 `v001`/`v002`，ID 不匹配，每次都返回 `available=False, message="场所不存在"`。所有方案全部不可用，触发重规划上限后进入 `handle_error`。

**修复**：完全绕过 mock store，改为内联检查：
- `_check_hours(item_dict, time)`：正则提取 `opening_hours` 中第一个 `HH:MM-HH:MM` 片段判断营业时间
- `_check_slots(rest_dict, time, party_size)`：直接用 `available_slots` 列表判断餐厅预约可用性

---

### P3：execute_bookings 返回"场所不存在"导致预订失败

**现象**：用户确认方案后，预订结果显示"场所 B0GRC7D2OB 不存在"。

**原因**：与 P2 同根——`book_venue` / `book_restaurant` 同样通过 ID 查 mock store，高德 ID 不存在。

**修复**：`execute_bookings` 直接从候选数据构造 `BookingResult`，`status=success`，`detail` 标注"演示模式，请前往官方渠道完成"。

---

### P4：用户反馈未传入 LangGraph，重规划方案与上次完全相同

**现象**：用户在"重新规划"时输入了反馈文字，但生成的新方案和上次一模一样。

**原因（两层）**：
1. `ConfirmRequest` Pydantic 模型没有 `feedback` 字段，前端传来的 `feedback` 被 Pydantic 直接丢弃，`resume_payload` 里根本没有存 feedback，`human_review` 里 `payload.get("feedback", "")` 永远是空字符串。
2. 即使 feedback 能传到，原来的实现是把反馈拼在 prompt **末尾**，被前面的显式约束（`start_time: 10:00`、候选列表）压制，加上 `temperature=0` 确定性极高，LLM 基本复现上次结果。

**修复**：
- `ConfirmRequest` 新增 `feedback: str = ""`，`routes.py` 的 `resume_payload` 加入 `feedback`
- `generate_plans` 重构：重规划时将指令块放在 prompt **最前面**，内容包含用户反馈、上次方案摘要（供 LLM 对比），且区分"基于方案调整"和"全部重规划"两种指令措辞

---

### P5：confirm 接口 404，前端显示"操作失败"

**现象**：测试重规划时，前端报"操作失败"，后端日志 `POST /session/{id}/confirm 404 Not Found`。

**原因**：改完代码重启了后端，session 存储在内存 dict 中，重启后全部清空。前端仍持有旧 session_id，发 confirm 时找不到对应 session。

**处理**：刷新前端页面重新发起规划即可。根本解法是将 session 存储换为 Redis（已记录为已知问题，生产阶段处理）。

---

## 已知问题 / 待优化

1. **planner system prompt 未更新**：不了解 `day` 字段和多天行程，生成质量有提升空间（Phase 6）
2. **available_slots 固定默认值**：餐厅时段写死，需接入大众点评/美团才能获取真实时段
3. **amap 场所价格常为空**：博物馆/公园类 `price_per_person=0`，预算过滤对这类场所不起作用
4. **booking 为演示模式**：detail 标注演示，接入真实 API 后直接替换
5. **session 为内存存储**：后端重启后 session 丢失，前端需重新发起规划（生产环境替换为 Redis）

---

## 当前文件结构（关键改动文件）

```
backend/
├── agent/
│   ├── graph.py          ✅ human_review 支持 replan_base_plan_id
│   ├── nodes.py          ✅ Phase 4/5 + 可用性/预订修复 + replan prompt
│   └── state.py          ✅ replan_feedback / replan_base_plan_id 字段
├── api/
│   ├── routes.py         ✅ PlanRequest/UserRequest 双格式 + feedback 存入 resume_payload
│   └── session_store.py  ✅ user_request 字段
├── tools/
│   ├── travel.py         ✅ Phase 2
│   ├── geo.py            ✅ Phase 2
│   └── amap_http.py      ✅ Phase 2+3（真实 API 验证通过）
├── models/schemas.py     ✅ ConfirmRequest 新增 feedback 字段
├── config.py             ✅ amap_api_key
└── .env                  AMAP_API_KEY 已填入

frontend/
├── app/page.tsx           ✅ PlannerInput + handleReject(feedback, basePlanId)
├── components/planner/
│   ├── PlannerInput.tsx   ✅ 新建，结构化输入表单
│   └── PlanCards.tsx      ✅ 重规划模式选择 + 反馈文本框
└── lib/
    ├── api.ts             ✅ createSession(PlanRequest) / confirmPlan(+feedback)
    └── types.ts           ✅ PlanRequest / TravelMode / ActivityPreference 类型
```

---

## 下一步

**优先**：提交本次所有改动到 `feature/amap-integration`

**Phase 6 — Prompt 更新**
- `prompts/planner/system.txt`：支持多天 `day` 字段、交通时间估算
- `prompts/intent_parser/system.txt`：LLM 路径补充城市/适老化提取规则

**Phase 7 — 时间验证**
```python
validate_timeline(plan, constraints) -> list[str]
  # ① 时间连续性  ② 每天总时长  ③ 人均费用
# 有错误 → 附错误列表重试（最多2次）
```
