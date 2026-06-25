from __future__ import annotations

import unittest

from cloud.app.log_service.store import PersistentLogStore


class PersistentLogStoreTest(unittest.TestCase):
    def test_temp_alias_uses_file_backed_store(self) -> None:
        store = PersistentLogStore(":temp:")
        store.record_deploy(
            request_id="req_temp_alias",
            device_id="ra8p1_demo_001",
            topic="cloudbridge/ra8p1_demo_001/script",
            intent={"intent_type": "threshold_control"},
            message={"payload": {"script_id": "script_001", "lua_code": "print('ok')"}},
            lua_validation={"ok": True},
            mqtt_enabled=False,
            published=False,
        )

        deployment = store.get_deployment("req_temp_alias")

        self.assertIsNotNone(deployment)

    def test_records_deploy_and_ack(self) -> None:
        store = PersistentLogStore(":memory:")
        store.record_deploy(
            request_id="req_001",
            device_id="ra8p1_demo_001",
            topic="cloudbridge/ra8p1_demo_001/script",
            intent={"intent_type": "threshold_control"},
            message={"payload": {"script_id": "script_001", "lua_code": "print('ok')"}},
            lua_validation={"ok": True},
            mqtt_enabled=True,
            published=True,
        )
        ack = {"request_id": "req_001", "type": "deploy_ack", "payload": {"code": 0}}
        store.record_ack("ra8p1_demo_001", ack)

        deployment = store.get_deployment("req_001")

        self.assertIsNotNone(deployment)
        assert deployment is not None
        self.assertTrue(deployment["ack_received"])
        self.assertEqual(ack, deployment["ack"])

    def test_records_device_messages(self) -> None:
        store = PersistentLogStore(":memory:")
        store.record_device_message(
            topic="cloudbridge/ra8p1_demo_001/status",
            device_id="ra8p1_demo_001",
            channel="status",
            message={"request_id": "status_tick", "type": "status"},
        )

        messages = store.list_device_messages("ra8p1_demo_001", channel="status")

        self.assertEqual(1, len(messages))
        self.assertEqual("status", messages[0]["channel"])

    def test_records_agent_runs(self) -> None:
        store = PersistentLogStore(":memory:")
        store.record_agent_run(
            request_id="agent_run_001",
            device_id="ra8p1_demo_001",
            route="rule_program_v1",
            user_text="当温度达到30度时让舵机转动",
            source="specialized_agent_v1:rule_based_action_plan_v1",
            confidence=0.81,
            knowledge_snapshot={"device_id": "ra8p1_demo_001"},
            plan={"program": {"version": "rule_program.v1"}},
            deployment={"ack_received": False},
        )

        run = store.get_agent_run("agent_run_001")
        runs = store.list_agent_runs()

        self.assertIsNotNone(run)
        assert run is not None
        self.assertEqual("rule_program_v1", run["route"])
        self.assertEqual("当温度达到30度时让舵机转动", run["user_text"])
        self.assertGreaterEqual(len(runs), 1)


if __name__ == "__main__":
    unittest.main()
