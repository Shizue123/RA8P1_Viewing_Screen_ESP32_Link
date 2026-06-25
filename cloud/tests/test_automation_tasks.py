from __future__ import annotations

import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from cloud.app.api.web_routes import _build_servo_sweep_sequence, _normalize_model_automation_task
from cloud.app.automation_tasks import (
    AutomationTaskService,
    automation_task_from_text,
    contextual_automation_task_from_text,
)
from cloud.app.config import Settings
from cloud.app.device_state.store import device_state_store


class AutomationTaskParserTest(unittest.TestCase):
    def test_parses_independent_temperature_humidity_and_light_rules(self) -> None:
        cases = [
            (
                "当温度达到32度时，舵机向左和向右各转动2次，30度",
                "env.temperature",
                ">=",
                32.0,
                "both",
                2,
                30,
            ),
            (
                "当湿度达到60%时，舵机持续向左转动两次，2次，60度",
                "env.humidity",
                ">=",
                60.0,
                "left",
                2,
                60,
            ),
            (
                "当光照低于50lux时，舵机持续向右转动三次，均为30度",
                "env.light.lux",
                "<",
                50.0,
                "right",
                3,
                30,
            ),
        ]
        for text, capability, operator, value, direction, times, angle in cases:
            with self.subTest(text=text):
                parsed = automation_task_from_text(text)
                self.assertIsNotNone(parsed)
                spec = parsed["spec"]
                self.assertEqual(capability, spec["capability"])
                self.assertEqual(operator, spec["operator"])
                self.assertEqual(value, spec["value"])
                self.assertEqual(direction, spec["direction"])
                self.assertEqual(times, spec["times"])
                self.assertEqual(angle, spec["angle"])

    def test_parses_short_and_daily_report_tasks(self) -> None:
        now = int(datetime(2026, 6, 22, 20, 0, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        ambiguous = automation_task_from_text("晚上九点十分时向我汇报温湿度情况和光照情况", now=now)
        once = automation_task_from_text("今天晚上九点十分时向我汇报温湿度情况和光照情况", now=now)
        daily = automation_task_from_text("每天早上八点向我汇报温湿度和光照情况", now=now)
        self.assertEqual("clarify", ambiguous["operation"])
        self.assertIn("每天执行", ambiguous["question"])
        self.assertEqual("once", once["schedule_kind"])
        self.assertEqual("21:10", once["spec"]["local_time"])
        self.assertGreater(once["next_run_at"], now)
        self.assertEqual("daily", daily["schedule_kind"])
        self.assertEqual("08:00", daily["spec"]["local_time"])
        self.assertGreater(daily["next_run_at"], now)
        self.assertTrue(daily["survives_conversation"])

    def test_mixed_chinese_hour_and_arabic_minute_preserves_full_datetime(self) -> None:
        now = int(datetime(2026, 6, 23, 10, 51, 11, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        parsed = automation_task_from_text("今天十点52分的时候，上报温湿度数据", now=now)
        self.assertEqual("scheduled_report", parsed["task_type"])
        self.assertEqual("once", parsed["schedule_kind"])
        self.assertEqual("10:52", parsed["spec"]["local_time"])
        self.assertEqual("2026-06-23T10:52:00+08:00", parsed["spec"]["target_local_iso"])
        self.assertEqual(
            ["env.temperature", "env.humidity"],
            parsed["spec"]["capabilities"],
        )
        self.assertEqual(
            int(datetime(2026, 6, 23, 10, 52, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()),
            parsed["next_run_at"],
        )

    def test_chinese_leading_zero_minute_is_not_dropped(self) -> None:
        now = int(datetime(2026, 6, 23, 11, 4, 25, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        parsed = automation_task_from_text(
            "今天十一点零五分的时候，上报温湿度和光照的情况",
            now=now,
        )
        self.assertEqual("11:05", parsed["spec"]["local_time"])
        self.assertEqual("2026-06-23T11:05:00+08:00", parsed["spec"]["target_local_iso"])
        self.assertEqual(
            ["env.temperature", "env.humidity", "env.light.lux"],
            parsed["spec"]["capabilities"],
        )
        self.assertEqual(
            int(datetime(2026, 6, 23, 11, 5, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()),
            parsed["next_run_at"],
        )

    def test_once_schedule_supports_seconds_and_explicit_calendar_date(self) -> None:
        now = int(datetime(2026, 6, 23, 10, 51, 11, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        parsed = automation_task_from_text(
            "2026年6月24日十点52分30秒上报温湿度",
            now=now,
        )
        self.assertEqual("10:52:30", parsed["spec"]["local_time"])
        self.assertEqual("2026-06-24T10:52:30+08:00", parsed["spec"]["target_local_iso"])
        self.assertEqual(
            int(datetime(2026, 6, 24, 10, 52, 30, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()),
            parsed["next_run_at"],
        )

    def test_2126_scheduled_servo_requires_recurrence_clarification(self) -> None:
        now = int(datetime(2026, 6, 22, 21, 25, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        ambiguous = automation_task_from_text("21点26分时，舵机向右转动60度", now=now)
        once = automation_task_from_text("今天21点26分时，舵机向右转动60度", now=now)
        daily = automation_task_from_text("每天21点26分时，舵机向右转动60度", now=now)
        self.assertEqual("clarify", ambiguous["operation"])
        self.assertEqual("scheduled_action", once["task_type"])
        self.assertEqual("once", once["schedule_kind"])
        self.assertFalse(once["spec"]["auto_reset"])
        self.assertEqual("right", once["spec"]["direction"])
        self.assertEqual(60, once["spec"]["angle"])
        self.assertEqual("daily", daily["schedule_kind"])
        self.assertTrue(daily["survives_conversation"])

    def test_contextual_followup_can_change_time_without_repeating_task_subject(self) -> None:
        now = int(datetime(2026, 6, 23, 10, 20, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        latest = {
            "task_id": "task_context",
            "task_type": "scheduled_report",
            "schedule_kind": "once",
            "next_run_at": int(
                datetime(2026, 6, 23, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()
            ),
            "spec": {"local_time": "10:30"},
        }
        parsed = contextual_automation_task_from_text(
            "算了，你改成10点25吧",
            conversation_history=[
                {"role": "user", "content": "今天早上十点半汇报温湿度和光照"},
                {"role": "assistant", "content": "已建立一次性汇报任务。"},
                {"role": "user", "content": "算了，你改成10点25吧"},
            ],
            latest_task=latest,
            now=now,
        )
        self.assertEqual("update", parsed["operation"])
        self.assertEqual("task_context", parsed["task_id"])
        self.assertEqual("10:25", parsed["spec"]["local_time"])
        self.assertEqual("2026-06-23T10:25:00+08:00", parsed["spec"]["target_local_iso"])
        self.assertEqual(
            int(datetime(2026, 6, 23, 10, 25, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp()),
            parsed["next_run_at"],
        )

    def test_contextual_followup_completes_prior_recurrence_question(self) -> None:
        now = int(datetime(2026, 6, 23, 10, 20, tzinfo=ZoneInfo("Asia/Shanghai")).timestamp())
        parsed = contextual_automation_task_from_text(
            "今天早上；算了，你改成10点25吧",
            conversation_history=[
                {"role": "user", "content": "当时间来到10点23分时，上报温湿度和光照情况"},
                {"role": "assistant", "content": "是今天这一次，还是每天都上报？"},
                {"role": "user", "content": "今天早上；算了，你改成10点25吧"},
            ],
            latest_task={
                "task_id": "task_sensor",
                "task_type": "sensor_rule",
                "schedule_kind": "",
                "spec": {"capability": "env.temperature"},
            },
            now=now,
        )
        self.assertEqual("create", parsed["operation"])
        self.assertEqual("scheduled_report", parsed["task_type"])
        self.assertEqual("once", parsed["schedule_kind"])
        self.assertEqual("10:25", parsed["spec"]["local_time"])
        self.assertEqual("一次性10:25环境汇报", parsed["name"])

    def test_contextual_followup_can_cancel_latest_task(self) -> None:
        parsed = contextual_automation_task_from_text(
            "刚才那个不要了",
            conversation_history=[],
            latest_task={"task_id": "task_context"},
        )
        self.assertEqual({"operation": "cancel", "task_id": "task_context"}, parsed)

    def test_servo_sequences_preserve_legacy_both_and_add_single_directions(self) -> None:
        self.assertEqual(
            [60, 120, 60, 120],
            [angle for angle, _duration in _build_servo_sweep_sequence(30, 2, 350)],
        )
        self.assertEqual(
            [30, 90, 30],
            [
                angle
                for angle, _duration in _build_servo_sweep_sequence(
                    60, 2, 350, direction="left"
                )
            ],
        )
        self.assertEqual(
            [120, 90, 120, 90, 120],
            [
                angle
                for angle, _duration in _build_servo_sweep_sequence(
                    30, 3, 350, direction="right"
                )
            ],
        )
        self.assertEqual(
            [150, 90],
            [
                angle
                for angle, _duration in _build_servo_sweep_sequence(
                    60, 1, 350, direction="right", auto_reset=True
                )
            ],
        )

    def test_normalizes_contextual_model_nested_task_shape(self) -> None:
        normalized = _normalize_model_automation_task(
            {
                "trigger": {
                    "sensor": "BH1750.lux",
                    "operator": "<",
                    "value": 50,
                },
                "action": {
                    "device": "SG90",
                    "direction": "right",
                    "angle": 30,
                    "times": 3,
                },
                "description": "沿用上一轮上下文建立光照任务",
            }
        )
        self.assertEqual("create", normalized["operation"])
        self.assertEqual("sensor_rule", normalized["task_type"])
        self.assertEqual("env.light.lux", normalized["spec"]["capability"])
        self.assertEqual("right", normalized["spec"]["direction"])

        hermes_shape = _normalize_model_automation_task(
            {
                "trigger": {
                    "sensor": "AHT20",
                    "capability": "env.humidity",
                    "operator": ">=",
                    "value": 60,
                },
                "actions": [
                    {
                        "device": "SG90",
                        "params": {"angle": 30, "duration_ms": 500},
                    }
                ],
                "repeat": 2,
                "amplitude_deg": 60,
                "direction": "left",
                "cooldown_ms": 30000,
            }
        )
        self.assertEqual("env.humidity", hermes_shape["spec"]["capability"])
        self.assertEqual(60, hermes_shape["spec"]["angle"])
        self.assertEqual(2, hermes_shape["spec"]["times"])
        self.assertEqual("left", hermes_shape["spec"]["direction"])


class AutomationTaskServiceTest(unittest.TestCase):
    def test_three_rules_coexist_and_trigger_from_real_uploaded_samples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            db_path = str(Path(directory) / "tasks.sqlite3")
            settings = Settings(
                device_id="automation-device",
                automation_task_db_path=db_path,
                mqtt_enabled=False,
            )
            service = AutomationTaskService(settings)
            texts = [
                "当温度达到32度时，舵机向左和向右各转动2次，30度",
                "当湿度达到60%时，舵机持续向左转动2次，60度",
                "当光照低于50lux时，舵机持续向右转动3次，30度",
            ]
            for text in texts:
                parsed = automation_task_from_text(text)
                service.create_task(
                    owner_channel="web",
                    owner_id="1",
                    conversation_id="conversation-1",
                    device_id=settings.device_id,
                    task_type=parsed["task_type"],
                    name=parsed["name"],
                    spec=parsed["spec"],
                )
            now = int(time.time())
            device_state_store.update_from_mqtt(
                f"cloudbridge/{settings.device_id}/telemetry",
                {
                    "type": "telemetry",
                    "timestamp": now,
                    "payload": {
                        "samples": [
                            {"capability": "env.temperature", "value": 32.2, "unit": "C"},
                            {"capability": "env.humidity", "value": 61.0, "unit": "%RH"},
                            {"capability": "env.light.lux", "value": 42.0, "unit": "lux"},
                        ]
                    },
                },
            )
            executed: list[str] = []
            with patch.object(
                service,
                "_execute_servo",
                side_effect=lambda task, _observation: executed.append(task["name"]) or {"ok": True},
            ):
                service.run_once(now=now + 1)
                service.run_once(now=now + 2)

            self.assertEqual(3, len(service.list_tasks("web", "1")))
            self.assertEqual(3, len(executed))
            service.close()

    def test_conversation_delete_cancels_only_nonpersistent_tasks_and_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(automation_task_db_path=str(Path(directory) / "tasks.sqlite3"))
            service = AutomationTaskService(settings)
            short = service.create_task(
                owner_channel="web",
                owner_id="1",
                conversation_id="conversation-1",
                device_id="device-1",
                task_type="scheduled_action",
                name="今天动作",
                spec={"local_time": "21:26", "direction": "right", "angle": 60, "times": 1},
                schedule_kind="once",
                next_run_at=int(time.time()) + 60,
            )
            long = service.create_task(
                owner_channel="web",
                owner_id="1",
                conversation_id="conversation-1",
                device_id="device-1",
                task_type="scheduled_action",
                name="每日动作",
                spec={"local_time": "21:26", "direction": "right", "angle": 60, "times": 1},
                schedule_kind="daily",
                next_run_at=int(time.time()) + 60,
                survives_conversation=True,
            )
            service.set_servo_auto_reset_preference("web", "1", "conversation-1", True)

            cancelled = service.cancel_conversation_tasks("web", "1", "conversation-1")

            self.assertEqual(1, cancelled)
            self.assertFalse(service.get_task(short["task_id"])["enabled"])
            self.assertTrue(service.get_task(long["task_id"])["enabled"])
            self.assertFalse(service.servo_auto_reset_preference("web", "1", "conversation-1"))
            service.close()

    def test_update_task_reenables_completed_schedule(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(automation_task_db_path=str(Path(directory) / "tasks.sqlite3"))
            service = AutomationTaskService(settings)
            task = service.create_task(
                owner_channel="web",
                owner_id="1",
                conversation_id="conversation-1",
                device_id="device-1",
                task_type="scheduled_report",
                name="一次汇报",
                spec={"local_time": "10:20"},
                schedule_kind="once",
                next_run_at=int(time.time()) - 1,
            )
            service._record_result(task["task_id"], {"ok": True}, int(time.time()), enabled=False)
            updated = service.update_task(
                task["task_id"],
                "web",
                "1",
                spec={"local_time": "10:25"},
                schedule_kind="once",
                next_run_at=int(time.time()) + 60,
            )
            self.assertTrue(updated["enabled"])
            self.assertEqual("10:25", updated["spec"]["local_time"])
            service.close()

    def test_due_report_reads_requested_sensors_and_writes_original_web_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            settings = Settings(
                automation_task_db_path=str(Path(directory) / "tasks.sqlite3"),
                auth_db_path=str(Path(directory) / "auth.sqlite3"),
            )
            service = AutomationTaskService(settings)
            task = service.create_task(
                owner_channel="web",
                owner_id="7",
                conversation_id="conversation-original",
                device_id="device-1",
                task_type="scheduled_report",
                name="一次性10:52环境汇报",
                spec={
                    "local_time": "10:52",
                    "target_local_iso": "2026-06-23T10:52:00+08:00",
                    "timezone": "Asia/Shanghai",
                    "capabilities": ["env.temperature", "env.humidity"],
                },
                schedule_kind="once",
                next_run_at=100,
            )
            store = MagicMock()
            with (
                patch(
                    "cloud.app.api.web_routes._build_observation_query_response",
                    return_value={"assistant_message": "温度 27.1 C，湿度 53.2%。"},
                ) as observe,
                patch("cloud.app.auth.AuthStore", return_value=store),
            ):
                service.run_once(now=100)

            query = observe.call_args.kwargs["query"]
            self.assertEqual(["AHT20"], query.devices)
            self.assertEqual(["env.temperature", "env.humidity"], query.capabilities)
            store.append_chat_message.assert_called_once_with(
                7,
                "conversation-original",
                "assistant",
                "【任务 一次性10:52环境汇报】\n温度 27.1 C，湿度 53.2%。",
            )
            self.assertFalse(service.get_task(task["task_id"])["enabled"])
            service.close()


if __name__ == "__main__":
    unittest.main()
