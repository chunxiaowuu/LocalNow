"""
FastAPI 路由。

四个端点：
  POST /session               创建会话，返回 session_id
  GET  /session/{id}/stream   SSE 推送 Agent 执行进度
  POST /session/{id}/confirm  用户确认方案，触发 HiL resume
  GET  /session/{id}/result   获取最终结果
"""

import asyncio
import json
import uuid

from fastapi import APIRouter, HTTPException, Request as FastAPIRequest
from langgraph.types import Command
from sse_starlette.sse import EventSourceResponse

from agent.graph import graph
from api import ratelimit, session_store
from api.auth import identity
from config import config
from models.schemas import ConfirmRequest, PlanRequest, SessionResponse, UserRequest

router = APIRouter()

# 各节点对应的用户友好提示，在 SSE 里展示给前端
_NODE_MESSAGES: dict[str, str] = {
    "parse_intent":      "正在解析您的需求...",
    "search_candidates": "正在搜索附近场所和餐厅...",
    "generate_plans":    "正在生成活动方案...",
    "check_availability":"正在确认可用性...",
    "human_review":      "方案已准备好，等待您确认...",
    "increment_replan":  "正在重新规划...",
    "parse_replan_feedback": "正在根据您的反馈调整方案...",
    "execute_bookings":  "正在完成预订...",
    "send_notification": "正在发送行程通知...",
    "handle_error":      "规划遇到问题，请稍候...",
}

# 初始化 AgentState 时的默认值（各字段必须存在，parse_intent 节点会覆盖相关字段）
def _initial_state(user_message: str, user_request: dict | None = None) -> dict:
    return {
        "user_message": user_message,
        "user_request": user_request or {},
        "scenario": "friends",          # parse_intent 节点会覆盖
        "constraints": None,            # parse_intent 节点会覆盖
        "preference_weights": {},       # parse_intent 节点会覆盖
        "candidate_venues": [],
        "candidate_restaurants": [],
        "day_clusters": [],
        "available_activity_minutes_per_day": 0,
        "candidate_plans": [],
        "availability_results": {},
        "selected_plan": None,
        "user_confirmed": False,
        "booking_results": [],
        "replan_count": 0,
        "replan_feedback": "",
        "replan_base_plan_id": "",
        "error": None,
        "summary_message": "",
    }


# ---------------------------------------------------------------------------
# GET /quota — 当日剩余规划次数（前端展示用）
# ---------------------------------------------------------------------------

@router.get("/quota")
async def quota(raw: FastAPIRequest):
    ident, is_auth = identity(raw)
    limit = config.auth_plans_per_day if is_auth else config.anon_plans_per_day
    used = ratelimit.plans_used_today(ident)
    return {
        "authenticated": is_auth,
        "plans_used": used,
        "plans_limit": limit,
        "plans_remaining": max(0, limit - used),
        "calls_per_plan": config.auth_calls_per_plan if is_auth else config.anon_calls_per_plan,
    }


# ---------------------------------------------------------------------------
# POST /session
# ---------------------------------------------------------------------------

@router.post("/session", response_model=SessionResponse)
async def create_session(raw: FastAPIRequest):
    """
    创建规划会话，支持两种请求格式：
    - PlanRequest（新 UI）：结构化字段，parse_intent 走直接映射路径
    - UserRequest（旧格式）：{message: str}，parse_intent 走全量 LLM 路径
    """
    # 限流：未登录每天 1 个 plan，登录每天 3 个 plan（按身份计数）
    ident, is_auth = identity(raw)
    plan_limit = config.auth_plans_per_day if is_auth else config.anon_plans_per_day
    if not ratelimit.try_consume_plan(ident, plan_limit):
        raise HTTPException(
            status_code=429,
            detail=(
                f"今日规划次数已用完（{'登录' if is_auth else '未登录'}用户每天 {plan_limit} 次）。"
                + ("" if is_auth else "登录后每天可规划 3 次。")
            ),
        )

    data = await raw.json()
    session_id = str(uuid.uuid4())

    if "message" in data and "start_date" not in data:
        # 旧格式：{message: str}
        body = UserRequest(**data)
        session_store.create(session_id, body.message)
    else:
        # 新格式：PlanRequest
        body = PlanRequest(**data)
        duration_days = (body.end_date - body.start_date).days + 1
        pref_str = "、".join(body.preferences) if body.preferences else "综合活动"
        user_message = (
            f"{body.group_size}人，{body.city}，"
            f"{body.start_date} 至 {body.end_date}（{duration_days}天），"
            f"偏好：{pref_str}。"
        )
        if body.free_text:
            user_message += body.free_text
        session_store.create(session_id, user_message, user_request=body.model_dump(mode="json"))

    session_store.update(session_id, is_authenticated=is_auth)
    return SessionResponse(session_id=session_id, status="created")


# ---------------------------------------------------------------------------
# GET /session/{id}/stream
# ---------------------------------------------------------------------------

@router.get("/session/{session_id}/stream")
async def stream_session(session_id: str):
    """
    SSE 长连接，实时推送 Agent 每个节点的执行进度。

    两种调用场景：
      1. 首次连接（status=created）：传入初始状态启动图
      2. 确认后重连（status=resuming）：传入 Command(resume=...) 恢复 interrupt
    """
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator():
        config = {"configurable": {"thread_id": session_id}}

        # 根据会话状态决定传什么给 graph.astream
        if session.status == "created":
            graph_input = _initial_state(session.user_message, session.user_request)
            session_store.update(session_id, status="running")
        elif session.status == "resuming":
            graph_input = Command(resume=session.resume_payload)
            session_store.update(session_id, status="running")
        else:
            yield {
                "event": "error",
                "data": json.dumps(
                    {"message": f"会话状态异常：{session.status}"},
                    ensure_ascii=False,
                ),
            }
            return

        # Queue 解耦图执行与 SSE 生成器：
        # 图在独立 asyncio task 里跑，每完成一个节点就把 chunk 放入队列；
        # SSE 生成器每 5 秒从队列取一次，取不到就发 heartbeat 保活连接，
        # 无论 LLM 跑多久都不会因为无数据导致连接超时。
        queue: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()  # 结束信号

        async def run_graph() -> None:
            try:
                async for chunk in graph.astream(graph_input, config, stream_mode="updates"):
                    await queue.put(("chunk", chunk))
            except Exception as exc:
                import traceback
                traceback.print_exc()   # 打印完整调用栈到终端
                await queue.put(("error", exc))
            finally:
                await queue.put(("done", _SENTINEL))

        asyncio.create_task(run_graph())

        try:
            while True:
                try:
                    kind, payload = await asyncio.wait_for(queue.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    # 5 秒内没有新 chunk，发 heartbeat 保活连接
                    yield {"event": "heartbeat", "data": "{}"}
                    continue

                if kind == "error":
                    raise payload

                if kind == "done":
                    break

                # kind == "chunk"
                chunk = payload
                for node_name, node_output in chunk.items():
                    if node_name == "__interrupt__":
                        interrupt_value = node_output[0].value
                        session_store.update(session_id, status="interrupted")
                        yield {
                            "event": "interrupt",
                            "data": json.dumps(interrupt_value, ensure_ascii=False, default=str),
                        }
                    else:
                        message = _NODE_MESSAGES.get(node_name, f"{node_name} 执行中...")
                        yield {
                            "event": "node_update",
                            "data": json.dumps(
                                {"node": node_name, "message": message},
                                ensure_ascii=False,
                            ),
                        }

            # 图跑完，检查是否正常结束（非 interrupt）
            if session_store.get(session_id).status == "running":
                final = graph.get_state(config)
                values = final.values
                session_store.update(
                    session_id,
                    status="done",
                    result={"summary": values.get("summary_message", ""), "values": values},
                )
                selected = values.get("selected_plan")
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "summary": values.get("summary_message", ""),
                            "booking_results": [
                                r.model_dump()
                                for r in values.get("booking_results", [])
                            ],
                            # 确认后的方案（含 timeline + 地图/预订链接），供前端生成行程清单
                            "plan": selected.model_dump() if selected else None,
                            "error": values.get("error"),
                        },
                        ensure_ascii=False,
                        default=str,
                    ),
                }

        except Exception as e:
            session_store.update(session_id, status="error")
            yield {
                "event": "error",
                "data": json.dumps({"message": str(e)}, ensure_ascii=False),
            }

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# POST /session/{id}/confirm
# ---------------------------------------------------------------------------

@router.post("/session/{session_id}/confirm")
async def confirm_session(session_id: str, body: ConfirmRequest):
    """
    用户确认或拒绝方案。

    收到请求后将 resume payload 存入 session，
    前端随即重连 /stream，下次 stream 调用会以 Command(resume=...) 恢复图的执行。
    """
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status != "interrupted":
        raise HTTPException(status_code=400, detail="Session is not waiting for confirmation")

    # 限流：拒绝（=带反馈重规划/修改 plan）按 session 计数；未登录≤3 次、登录≤9 次
    if not body.confirmed:
        call_limit = (
            config.auth_calls_per_plan if session.is_authenticated else config.anon_calls_per_plan
        )
        if session.modify_count >= call_limit:
            raise HTTPException(
                status_code=429,
                detail=(
                    f"该方案的修改次数已用完（{'登录' if session.is_authenticated else '未登录'}"
                    f"用户每个方案最多 {call_limit} 次）。"
                    + ("" if session.is_authenticated else "登录后每个方案可修改 9 次。")
                ),
            )
        session_store.update(session_id, modify_count=session.modify_count + 1)

    session_store.update(
        session_id,
        status="resuming",
        resume_payload={
            "confirmed": body.confirmed,
            "selected_plan_id": body.selected_plan_id,
            "feedback": body.feedback,
        },
    )
    return {"status": "ok", "message": "确认已收到，请重新连接 /stream 继续执行"}


# ---------------------------------------------------------------------------
# GET /session/{id}/result
# ---------------------------------------------------------------------------

@router.get("/session/{session_id}/result")
async def get_result(session_id: str):
    """获取会话最终结果（done 状态后可用）。"""
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status not in ("done", "error"):
        raise HTTPException(status_code=202, detail=f"Session still {session.status}")

    return {
        "session_id": session_id,
        "status": session.status,
        "result": session.result,
    }
