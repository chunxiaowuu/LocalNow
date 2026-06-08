# 测试说明

[English](README.md) | **中文**

## 运行测试

```bash
# 在 backend/ 目录下执行

# 运行全部测试
uv run pytest tests/ -v

# 只运行某个模块
uv run pytest tests/test_availability.py -v
uv run pytest tests/test_booking.py -v
uv run pytest tests/test_notification.py -v
uv run pytest tests/test_graph_routing.py -v

# 按关键词筛选
uv run pytest tests/ -k "fallback"
uv run pytest tests/ -k "no_seat"

# 简洁模式（不显示每个用例名）
uv run pytest tests/ -q
```

## 测试覆盖范围

### Tool 层（36 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_availability.py` | 19 | 餐厅/场所可用性查询、fallback 时间段、边界条件 |
| `test_booking.py` | 10 | 预订执行、final check 拦截、fallback 标记 |
| `test_notification.py` | 7 | 单条/批量通知发送、不支持渠道的错误处理 |

### Agent 层（9 个用例）

| 文件 | 用例数 | 覆盖内容 |
|------|--------|---------|
| `test_graph_routing.py` | 9 | 条件边路由逻辑（不涉及 LLM 调用） |

## 测试策略说明

### 测什么

| 模块 | 测试方式 | 原因 |
|------|---------|------|
| Tool 层（availability/booking/notification） | pytest 单元测试 | 纯确定性逻辑，输入输出固定 |
| Graph 条件边（路由函数） | pytest 单元测试 | 纯函数，控制流正确性至关重要 |
| LLM 节点（parse_intent/generate_plans/send_notification） | 不写断言测试 | 输出非确定性，断言会脆 |
| LLM 节点行为 | LangSmith trace 观测 | 运行时通过 trace 验证输入输出 |

### 为什么不 mock 数据层

Tool 层测试使用**真实数据**，不 mock。

原因：mock 掉数据层后，测试只验证"调用了正确的 mock"，而不是"逻辑是否正确"。mock 掉关键依赖是测试失真的主要来源。

### 关键测试 case

`test_availability.py::TestCheckRestaurantAvailability::test_r001_no_17_30_slot`：验证 demo 核心 fallback 逻辑——外婆家（r001）17:30 无空位，返回 `NO_SEAT` 且 `next_available_slot=18:30`。

`test_graph_routing.py::TestRouteAfterAvailability::test_all_unavailable_at_limit_routes_to_error`：验证重规划次数超限后正确进入 `handle_error` 节点，不会无限循环。

## 共享 Fixture

`conftest.py` 提供 session 级 `store` fixture，整个测试会话只初始化一次数据存储，避免每个测试文件重复加载。
