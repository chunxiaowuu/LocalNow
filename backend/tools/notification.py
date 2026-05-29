"""
行程通知工具。

在所有预订执行完毕后，向相关人员发送行程确认消息。
消息内容由 LangGraph send_notification 节点用 fast LLM 生成，
本工具只负责"发送"动作（Mock 实现，不调用真实微信/短信 API）。

生产环境替换：仅需修改本文件内部实现，LangGraph 图和调用方不受影响。
"""

import logging

from models.schemas import BookingResult, BookingStatus

logger = logging.getLogger(__name__)

# 支持的通知渠道，生产环境各自对接真实 API
SUPPORTED_CHANNELS = {"wechat", "sms", "in_app"}


def send_notification(
    recipient: str,
    content: str,
    channel: str = "wechat",
) -> BookingResult:
    """
    向指定接收人发送通知消息。

    recipient: 接收人名称，如"老婆"、"朋友群"
    content:   消息正文，由 LLM 生成后传入
    channel:   发送渠道，默认微信
    """
    if channel not in SUPPORTED_CHANNELS:
        return BookingResult(
            action="发消息",
            target_name=recipient,
            status=BookingStatus.failed,
            detail=f"不支持的通知渠道：{channel}，可选：{', '.join(SUPPORTED_CHANNELS)}",
        )

    # Mock 发送：记录日志，模拟成功
    logger.info("[notification] channel=%s recipient=%s content=%s", channel, recipient, content)

    return BookingResult(
        action="发消息",
        target_name=recipient,
        status=BookingStatus.success,
        detail=f"已通过 {channel} 向「{recipient}」发送行程确认",
    )


def send_trip_summary(
    recipients: list[str],
    content: str,
    channel: str = "wechat",
) -> list[BookingResult]:
    """
    向多个接收人批量发送同一条行程消息。

    家庭场景：recipients=["老婆"]
    朋友场景：recipients=["小王", "小李", "小张"]
    """
    return [send_notification(r, content, channel) for r in recipients]
