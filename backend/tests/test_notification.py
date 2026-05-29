"""notification 工具单元测试。"""

from models.schemas import BookingStatus
from tools.notification import send_notification, send_trip_summary


class TestSendNotification:

    def test_success_default_channel(self):
        result = send_notification("老婆", "今天下午行程已确认")
        assert result.status == BookingStatus.success
        assert result.action == "发消息"
        assert result.target_name == "老婆"

    def test_success_sms_channel(self):
        result = send_notification("老婆", "行程确认", channel="sms")
        assert result.status == BookingStatus.success

    def test_unsupported_channel_fails(self):
        result = send_notification("老婆", "测试", channel="telegram")
        assert result.status == BookingStatus.failed
        assert "telegram" in result.detail

    def test_detail_contains_recipient(self):
        result = send_notification("朋友群", "集合时间确认")
        assert "朋友群" in result.detail


class TestSendTripSummary:

    def test_sends_to_all_recipients(self):
        recipients = ["小王", "小李", "小张"]
        results = send_trip_summary(recipients, "下午三点见！")
        assert len(results) == 3
        assert all(r.status == BookingStatus.success for r in results)

    def test_recipient_names_preserved(self):
        results = send_trip_summary(["老婆"], "行程已安排好")
        assert results[0].target_name == "老婆"

    def test_empty_recipients(self):
        results = send_trip_summary([], "无人接收")
        assert results == []
