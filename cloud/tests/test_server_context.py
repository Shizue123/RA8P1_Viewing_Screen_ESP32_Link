from __future__ import annotations

import unittest

from cloud.app.server_context import latest_aht20_observation, signal_topology


class ServerContextTest(unittest.TestCase):
    def test_signal_topology_projects_standard_ports_from_ports_and_samples(self) -> None:
        topology = signal_topology(
            {
                "device_id": "ra8p1_demo_001",
                "last_seen": 1780900000,
                "last_status": {
                    "type": "status",
                    "timestamp": 1780900000,
                    "payload": {
                        "ports": [
                            {
                                "port_id": "i2c.s1",
                                "physical_port": "I2C-1",
                                "channel": "Bus S1",
                                "type": "i2c",
                                "status": "online",
                                "diag": "ok",
                                "last_sample_ms": 4560,
                                "module": {
                                    "module_id": "aht20",
                                    "module_type": "AHT20",
                                    "driver": "aht20",
                                    "address": "0x38",
                                    "confidence": "exact",
                                },
                                "capabilities": [
                                    {"id": "env.temperature", "unit": "C", "access": "read", "status": "online"},
                                    {"id": "env.humidity", "unit": "%RH", "access": "read", "status": "online"},
                                ],
                            },
                            {
                                "port_id": "i2c.s2",
                                "physical_port": "I2C-2",
                                "channel": "Bus S2",
                                "type": "i2c",
                                "status": "empty",
                                "diag": "not_supported",
                                "last_sample_ms": 0,
                                "module": {
                                    "module_id": "reserved",
                                    "module_type": "reserved",
                                    "driver": "",
                                    "confidence": "reserved",
                                },
                                "capabilities": [],
                            },
                            {
                                "port_id": "pwm.0",
                                "physical_port": "PWM-0",
                                "channel": "P105",
                                "type": "pwm",
                                "status": "online",
                                "diag": "execution_feedback",
                                "last_sample_ms": 4600,
                                "module": {
                                    "module_id": "sg90",
                                    "module_type": "SG90",
                                    "driver": "sg90_servo",
                                    "confidence": "user_confirmed",
                                },
                                "capabilities": [
                                    {"id": "motor.servo.angle", "unit": "degree", "access": "write", "status": "execution_feedback"},
                                ],
                            },
                            {
                                "port_id": "uart.bridge",
                                "physical_port": "UART-BRIDGE",
                                "channel": "UART0",
                                "type": "uart",
                                "status": "online",
                                "diag": "ok",
                                "last_sample_ms": 4700,
                                "module": {
                                    "module_id": "esp32_bridge",
                                    "module_type": "ESP32-S3",
                                    "driver": "esp32_uart_link",
                                    "confidence": "exact",
                                },
                                "capabilities": [
                                    {"id": "bridge.uart.mqtt", "unit": "-", "access": "readwrite", "status": "degraded"},
                                ],
                            },
                        ],
                    },
                },
                "last_telemetry": {
                    "type": "telemetry",
                    "timestamp": 1780900002,
                    "payload": {
                        "samples": [
                            {
                                "port_id": "i2c.s1",
                                "module_type": "AHT20",
                                "capability": "env.temperature",
                                "value": 26.4,
                                "unit": "C",
                                "ts_ms": 4560,
                            },
                            {
                                "port_id": "i2c.s1",
                                "module_type": "AHT20",
                                "capability": "env.humidity",
                                "value": 58.2,
                                "unit": "%RH",
                                "ts_ms": 4560,
                            },
                            {
                                "port_id": "pwm.0",
                                "module_type": "SG90",
                                "capability": "motor.servo.angle",
                                "value": 120,
                                "unit": "degree",
                                "ts_ms": 4600,
                                "source": "execution_feedback",
                            },
                        ],
                    },
                },
            }
        )

        self.assertEqual("signal_topology.v3", topology["schema"])
        channels = {item["id"]: item for item in topology["channels"]}
        self.assertEqual("P309", channels["i2c.s1"]["signals"][0]["pin"])
        self.assertEqual("P306", channels["i2c.s1"]["signals"][1]["pin"])
        self.assertEqual("empty", channels["i2c.s2"]["state"]["status"])
        aht20 = channels["i2c.s1"]["hardware"][0]
        self.assertEqual("AHT20", aht20["hardware_type"])
        self.assertEqual("online", aht20["status"])
        self.assertEqual([26.4, 58.2], [item["value"] for item in aht20["readings"]])
        servo = channels["pwm.0"]["hardware"][0]
        self.assertEqual("SG90", servo["hardware_type"])
        self.assertEqual("online", channels["pwm.0"]["state"]["status"])
        self.assertEqual("execution_feedback", servo["status"])
        self.assertEqual("P105", channels["pwm.0"]["signals"][0]["pin"])
        self.assertIn("servo.sweep", servo["control_methods"])
        self.assertEqual("not_supported_pwm_no_feedback", servo["metadata"]["physical_detection"])
        self.assertEqual("ESP32-S3", channels["uart.bridge"]["hardware"][0]["hardware_type"])

    def test_latest_aht20_observation_prefers_newer_status_over_older_telemetry(self) -> None:
        observation = latest_aht20_observation(
            {
                "type": "status",
                "timestamp": 105,
                "payload": {"aht20": {"status": "online", "temp": 28.8, "humidity": 50.1}},
            },
            {
                "type": "telemetry",
                "timestamp": 100,
                "payload": {"aht20": {"status": "online", "temp": 28.4, "humidity": 49.5}},
            },
        )

        self.assertEqual("status", observation["source"])
        self.assertEqual(105.0, observation["timestamp"])
        self.assertEqual(28.8, observation["payload"]["temp"])

    def test_latest_aht20_observation_keeps_fresh_samples_online_when_port_card_is_stale(self) -> None:
        observation = latest_aht20_observation(
            {
                "type": "status",
                "timestamp": 105,
                "payload": {
                    "ports": [
                        {
                            "port_id": "i2c.s1",
                            "status": "not_inserted",
                            "diag": "unknown",
                            "module": {"module_type": "none"},
                        }
                    ],
                    "samples": [
                        {
                            "port_id": "i2c.s1",
                            "module_type": "AHT20",
                            "capability": "env.temperature",
                            "value": 27.0,
                            "unit": "C",
                        },
                        {
                            "port_id": "i2c.s1",
                            "module_type": "AHT20",
                            "capability": "env.humidity",
                            "value": 54.4,
                            "unit": "%RH",
                        },
                    ],
                },
            },
            None,
        )

        self.assertEqual("online", observation["payload"]["status"])
        self.assertEqual("ok", observation["payload"]["diag"])
        self.assertEqual(27.0, observation["payload"]["temp"])
        self.assertEqual(54.4, observation["payload"]["humidity"])

    def test_latest_aht20_observation_keeps_fresh_legacy_values_online_when_port_card_is_stale(self) -> None:
        observation = latest_aht20_observation(
            {
                "type": "status",
                "timestamp": 106,
                "payload": {
                    "aht20": {
                        "status": "online",
                        "temp": 27.0,
                        "humidity": 54.2,
                        "crc_ok": True,
                    },
                    "ports": [
                        {
                            "port_id": "i2c.s1",
                            "status": "not_inserted",
                            "diag": "unknown",
                            "module": {"module_type": "none"},
                        }
                    ],
                },
            },
            None,
        )

        self.assertEqual("online", observation["payload"]["status"])
        self.assertEqual("ok", observation["payload"]["diag"])
        self.assertEqual(27.0, observation["payload"]["temp"])
        self.assertEqual(54.2, observation["payload"]["humidity"])

    def test_signal_topology_uses_latest_aht20_observation_metadata(self) -> None:
        topology = signal_topology(
            {
                "device_id": "ra8p1_demo_001",
                "last_seen": 105,
                "last_status": {
                    "type": "status",
                    "timestamp": 105,
                    "payload": {
                        "ports": [
                            {
                                "port_id": "i2c.s1",
                                "physical_port": "I2C-1",
                                "channel": "Bus S1",
                                "type": "i2c",
                                "status": "online",
                                "diag": "ok",
                                "last_sample_ms": 210,
                                "module": {
                                    "module_id": "aht20",
                                    "module_type": "AHT20",
                                    "driver": "aht20",
                                    "address": "0x38",
                                    "confidence": "exact",
                                },
                                "capabilities": [
                                    {"id": "env.temperature", "unit": "C", "access": "read", "status": "online"},
                                    {"id": "env.humidity", "unit": "%RH", "access": "read", "status": "online"},
                                ],
                            }
                        ],
                    },
                },
                "last_telemetry": {
                    "type": "telemetry",
                    "timestamp": 100,
                    "payload": {
                        "samples": [
                            {
                                "port_id": "i2c.s1",
                                "module_type": "AHT20",
                                "capability": "env.temperature",
                                "value": 28.4,
                                "unit": "C",
                                "ts_ms": 200,
                            },
                            {
                                "port_id": "i2c.s1",
                                "module_type": "AHT20",
                                "capability": "env.humidity",
                                "value": 49.5,
                                "unit": "%RH",
                                "ts_ms": 200,
                            },
                        ],
                    },
                },
            }
        )

        channels = {item["id"]: item for item in topology["channels"]}
        aht20 = channels["i2c.s1"]["hardware"][0]
        self.assertEqual([28.4, 49.5], [item["value"] for item in aht20["readings"]])
        self.assertEqual("ports_samples_v1", aht20["metadata"]["source"])
        self.assertEqual(210, aht20["metadata"]["last_sample_ms"])

    def test_signal_topology_marks_all_channels_offline_when_device_is_stale(self) -> None:
        topology = signal_topology(
            {
                "device_id": "ra8p1_demo_001",
                "last_seen": 105,
                "_device_online": False,
                "last_status": {
                    "type": "status",
                    "timestamp": 105,
                    "payload": {
                        "ports": [
                            {
                                "port_id": "i2c.s1",
                                "physical_port": "I2C-1",
                                "channel": "Bus S1",
                                "type": "i2c",
                                "status": "online",
                                "diag": "ok",
                                "last_sample_ms": 210,
                                "module": {
                                    "module_id": "aht20",
                                    "module_type": "AHT20",
                                    "driver": "aht20",
                                    "address": "0x38",
                                    "confidence": "exact",
                                },
                                "capabilities": [
                                    {"id": "env.temperature", "unit": "C", "access": "read", "status": "online"},
                                    {"id": "env.humidity", "unit": "%RH", "access": "read", "status": "online"},
                                ],
                            },
                            {
                                "port_id": "pwm.0",
                                "physical_port": "PWM-0",
                                "channel": "P105",
                                "type": "pwm",
                                "status": "configured",
                                "diag": "no_feedback_open_loop",
                                "last_sample_ms": 0,
                                "module": {
                                    "module_id": "sg90",
                                    "module_type": "SG90",
                                    "driver": "sg90_servo",
                                    "confidence": "user_confirmed",
                                },
                                "capabilities": [
                                    {"id": "motor.servo.angle", "unit": "degree", "access": "write", "status": "configured"},
                                ],
                            },
                        ],
                    },
                },
            }
        )

        channels = {item["id"]: item for item in topology["channels"]}
        self.assertEqual("offline", channels["i2c.s1"]["state"]["status"])
        self.assertEqual("offline", channels["i2c.s1"]["hardware"][0]["status"])
        self.assertEqual("offline", channels["pwm.0"]["state"]["status"])
        self.assertEqual("offline", channels["pwm.0"]["hardware"][0]["status"])

    def test_signal_topology_reconciles_stale_i2c_port_with_legacy_devices_and_samples(self) -> None:
        topology = signal_topology(
            {
                "device_id": "ra8p1_live_001",
                "last_seen": 1782036852,
                "last_status": {
                    "type": "status",
                    "timestamp": 1782036852,
                    "payload": {
                        "i2c": {
                            "diag": "ok",
                            "interpretation": "env.multi",
                            "devices": [
                                {"address": "0x70", "type": "9548A-MUX", "status": "present"},
                                {"address": "0x38", "type": "AHT20", "status": "present"},
                                {"address": "0x23", "type": "BH1750", "status": "present"},
                            ],
                        },
                        "hardware_list": [
                            {"address": "0x70", "type": "9548A-MUX", "status": "present", "bus": "i2c.s1"},
                            {"address": "0x38", "type": "AHT20", "status": "present", "bus": "i2c.s1"},
                            {"address": "0x23", "type": "BH1750", "status": "present", "bus": "i2c.s1"},
                        ],
                        "ports": [
                            {
                                "port_id": "i2c.s1",
                                "physical_port": "I2C-1",
                                "channel": "Bus S1",
                                "type": "i2c",
                                "status": "not_inserted",
                                "diag": "unknown",
                                "activation": "inactive",
                                "last_sample_ms": 123,
                                "module": {
                                    "module_id": "none",
                                    "module_type": "none",
                                    "driver": "",
                                    "confidence": "none",
                                    "module_class": "none",
                                },
                                "capabilities": [],
                            }
                        ],
                    },
                },
                "last_telemetry": {
                    "type": "telemetry",
                    "timestamp": 1782036854,
                    "payload": {
                        "samples": [
                            {
                                "port_id": "i2c.s1",
                                "module_type": "AHT20",
                                "capability": "env.temperature",
                                "value": 27.6,
                                "unit": "C",
                                "ts_ms": 4560,
                            },
                            {
                                "port_id": "i2c.s1",
                                "module_type": "AHT20",
                                "capability": "env.humidity",
                                "value": 67.7,
                                "unit": "%RH",
                                "ts_ms": 4560,
                            },
                            {
                                "port_id": "i2c.s1",
                                "module_type": "BH1750",
                                "capability": "env.light.lux",
                                "value": 95.8,
                                "unit": "lux",
                                "ts_ms": 4560,
                            },
                        ],
                    },
                },
            }
        )

        self.assertEqual("signal_topology.v3", topology["schema"])
        channels = {item["id"]: item for item in topology["channels"]}
        i2c_channel = channels["i2c.s1"]
        self.assertEqual("online", i2c_channel["state"]["status"])
        self.assertEqual("channel_active", i2c_channel["state"]["activation"])
        self.assertEqual("env.multi", i2c_channel["state"]["interpretation"])
        self.assertEqual(3, i2c_channel["state"]["detected_count"])
        hardware = {item["hardware_type"]: item for item in i2c_channel["hardware"]}
        self.assertEqual({"9548A-MUX", "AHT20", "BH1750"}, set(hardware))
        self.assertEqual("online", hardware["AHT20"]["status"])
        self.assertEqual("i2c.s1", hardware["BH1750"]["metadata"]["port_id"])
        self.assertEqual([95.8], [item["value"] for item in hardware["BH1750"]["readings"]])
        self.assertEqual(["env.light.lux"], hardware["BH1750"]["capabilities"])
        self.assertEqual("online", hardware["BH1750"]["status"])


if __name__ == "__main__":
    unittest.main()
