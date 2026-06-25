from __future__ import annotations

import threading
import time
import unittest

from cloud.app.device_state.store import DeviceStateStore


class DeviceStateStoreTest(unittest.TestCase):
    def test_tracks_deploy_ack(self) -> None:
        store = DeviceStateStore()
        message = {
            "request_id": "req_001",
            "timestamp": 123,
            "type": "deploy_ack",
            "payload": {"code": 0, "message": "ok"},
        }

        store.update_from_mqtt("cloudbridge/ra8p1_demo_001/event", message)
        state = store.snapshot("ra8p1_demo_001")

        self.assertEqual(123, state["last_seen"])
        self.assertEqual(message, state["last_deploy_ack"])
        self.assertEqual(1, len(state["events"]))

    def test_ignores_unrelated_topic(self) -> None:
        store = DeviceStateStore()
        store.update_from_mqtt("bad/topic", {"type": "status"})

        state = store.snapshot("ra8p1_demo_001")

        self.assertIsNone(state["last_status"])

    def test_uses_receive_time_when_mqtt_message_has_no_timestamp(self) -> None:
        store = DeviceStateStore()
        before = int(time.time())

        store.update_from_mqtt(
            "cloudbridge/ra8p1_demo_001/status",
            {"type": "status", "payload": {"aht20": {"status": "online", "temp": 27.4, "humidity": 49.8}}},
        )
        state = store.snapshot("ra8p1_demo_001")

        self.assertGreaterEqual(state["last_seen"], before)
        self.assertEqual(state["last_seen"], state["last_status"]["timestamp"])

    def test_waits_for_matching_ack(self) -> None:
        store = DeviceStateStore()
        message = {
            "request_id": "req_wait",
            "timestamp": 123,
            "type": "deploy_ack",
            "payload": {"code": 0, "message": "ok"},
        }

        def publish_later() -> None:
            time.sleep(0.05)
            store.update_from_mqtt("cloudbridge/ra8p1_demo_001/event", message)

        thread = threading.Thread(target=publish_later)
        thread.start()
        ack = store.wait_for_deploy_ack("ra8p1_demo_001", "req_wait", timeout_sec=1)
        thread.join()

        self.assertEqual(message, ack)

    def test_wait_for_ack_times_out(self) -> None:
        store = DeviceStateStore()

        ack = store.wait_for_deploy_ack("ra8p1_demo_001", "missing", timeout_sec=0.01)

        self.assertIsNone(ack)


if __name__ == "__main__":
    unittest.main()
