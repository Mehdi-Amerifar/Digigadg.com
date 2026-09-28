from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, override_settings

from app.tasks.daily_order_summary import prior_tehran_day, send_daily_order_summary


class DailyOrderSummaryTests(SimpleTestCase):
    def test_prior_day_uses_tehran_calendar_midnights(self):
        now = datetime(2026, 9, 28, 5, 30, tzinfo=ZoneInfo("UTC"))
        start, end = prior_tehran_day(now)
        self.assertEqual(start.isoformat(), "2026-09-27T00:00:00+03:30")
        self.assertEqual(end.isoformat(), "2026-09-28T00:00:00+03:30")

    @override_settings(TELEGRAM_BOT_TOKEN="secret-token", TELEGRAM_CHAT_ID="123")
    @patch("app.tasks.daily_order_summary.build_summary", return_value=("report", 2))
    @patch("app.tasks.daily_order_summary.requests.post")
    def test_delivery_sends_summary(self, post, _build_summary):
        post.return_value.json.return_value = {"ok": True}
        send_daily_order_summary()
        self.assertEqual(post.call_args.kwargs["data"], {"chat_id": "123", "text": "report"})
        self.assertEqual(post.call_args.kwargs["timeout"], 15)

    @override_settings(TELEGRAM_BOT_TOKEN="secret-token", TELEGRAM_CHAT_ID="123")
    @patch("app.tasks.daily_order_summary.build_summary", return_value=("report", 2))
    @patch("app.tasks.daily_order_summary.requests.post")
    def test_delivery_failure_does_not_expose_bot_token(self, post, _build_summary):
        post.return_value.raise_for_status.side_effect = RuntimeError(
            "https://api.telegram.org/botsecret-token/sendMessage"
        )
        with self.assertLogs("app.tasks.daily_order_summary", level="ERROR") as logs:
            with self.assertRaisesRegex(RuntimeError, "Daily order summary failed") as raised:
                send_daily_order_summary()
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertNotIn("secret-token", "\n".join(logs.output))

    @override_settings(TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
    def test_missing_credentials_fail_before_querying_orders(self):
        with patch("app.tasks.daily_order_summary.build_summary") as build_summary:
            with self.assertRaisesRegex(RuntimeError, "not configured"):
                send_daily_order_summary()
        build_summary.assert_not_called()

