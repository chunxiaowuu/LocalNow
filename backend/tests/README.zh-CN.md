# 测试说明

[English](README.md) | **中文**

## 运行测试

```bash
# 在 backend/ 目录下执行

# 运行全部测试
uv run pytest tests/ -v

# 只运行某个模块
uv run pytest tests/test_amap_http.py -v
uv run pytest tests/test_timeline_validation.py -v
uv run pytest tests/test_graph_routing.py -v

# 按关键词筛选
uv run pytest tests/ -k "fallback"
uv run pytest tests/ -k "no_seat"

# 简洁模式
uv run pytest tests/ -q
```

## 测试覆盖（131 个用例）

| 层 | 文件 | 覆盖内容 |
|----|------|---------|
| 数据 / 工具 | `test_amap_http.py`、`test_geo.py`、`test_travel.py` | 地图客户端（geocode + 周边搜索 + 字段映射 + fallback）、haversine 距离、地理聚类、交通时间估算 |
| 可用性 / 预订 / 通知 | `test_availability.py`、`test_booking.py`、`test_notification.py` | 时段可用性 + fallback 时段、预订执行 + final check、通知发送 |
| Agent | `test_graph_routing.py`、`test_timeline_validation.py` | 条件边路由（不涉及 LLM）、程序化时间/预算校验 |
| 模型 / E2E | `test_phase1_models.py`、`test_e2e.py` | Pydantic schema 契约、端到端流程 |

## 测试策略说明

### 测什么

| 模块 | 测试方式 | 原因 |
|------|---------|------|
| 确定性工具（geo / travel / availability / booking / validation） | pytest 单元测试 | 输入输出固定，纯逻辑 |
| 地图客户端（`amap_http`） | 单元测试 + mock 掉 HTTP 调用 | 断言请求构造 + 响应→模型映射 + fallback，不触网 |
| Graph 条件边（路由函数） | pytest 单元测试 | 纯函数，控制流正确性至关重要 |
| LLM 节点（parse_intent / generate_plans / send_notification） | 不写断言测试 | 输出非确定性，断言会脆 |
| LLM 节点行为 | LangSmith trace 观测 | 运行时通过 trace 验证输入输出 |

### 只在最外层边界 mock

测试运行**真实的工具逻辑**，只 mock 最外层依赖（地图 HTTP 调用）。mock 掉内部逻辑后，测试只验证"调用了正确的 mock"而非"逻辑是否正确"——这是测试失真的主要来源。

### 关键测试 case

`test_availability.py::TestCheckRestaurantAvailability::test_r001_no_17_30_slot`：验证核心 fallback 逻辑——餐厅 `r001` 17:30 无空位，返回 `NO_SEAT` 且 `next_available_slot=18:30`。

`test_graph_routing.py::TestRouteAfterAvailability::test_all_unavailable_at_limit_routes_to_error`：验证重规划次数超限后进入 `handle_error` 节点，不会无限循环。

`test_amap_http.py`：验证地图客户端把 POI 正确映射为 `Venue`/`Restaurant`，并在无 API Key 或调用失败时降级到本地 mock 数据。
