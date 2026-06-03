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

from fastapi import APIRouter, HTTPException
from langgraph.types import Command
from sse_starlette.sse import EventSourceResponse

from agent.graph import graph
from api import session_store
from models.schemas import ConfirmRequest, SessionResponse, UserRequest

router = APIRouter()

# 各节点对应的用户友好提示，在 SSE 里展示给前端
_NODE_MESSAGES: dict[str, str] = {
    "parse_intent":      "正在解析您的需求...",
    "search_candidates": "正在搜索附近场所和餐厅...",
    "generate_plans":    "正在生成活动方案...",
    "check_availability":"正在确认可用性...",
    "human_review":      "方案已准备好，等待您确认...",
    "increment_replan":  "正在重新规划...",
    "execute_bookings":  "正在完成预订...",
    "send_notification": "正在发送行程通知...",
    "handle_error":      "规划遇到问题，请稍候...",
}

# 初始化 AgentState 时的默认值（各字段必须存在，parse_intent 节点会覆盖相关字段）
def _initial_state(user_message: str) -> dict:
    return {
        "user_message": user_message,
        "user_request": {},             # Phase 8 填入结构化请求
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
        "error": None,
        "summary_message": "",
    }


# ---------------------------------------------------------------------------
# POST /session
# ---------------------------------------------------------------------------

@router.post("/session", response_model=SessionResponse)
async def create_session(body: UserRequest):
    """创建规划会话，返回 session_id。此时 Agent 尚未启动，等待 /stream 连接后开始。"""
    session_id = str(uuid.uuid4())
    session_store.create(session_id, body.message)
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
            graph_input = _initial_state(session.user_message)
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
                yield {
                    "event": "done",
                    "data": json.dumps(
                        {
                            "summary": values.get("summary_message", ""),
                            "booking_results": [
                                r.model_dump()
                                for r in values.get("booking_results", [])
                            ],
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

    session_store.update(
        session_id,
        status="resuming",
        resume_payload={
            "confirmed": body.confirmed,
            "selected_plan_id": body.selected_plan_id,
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
