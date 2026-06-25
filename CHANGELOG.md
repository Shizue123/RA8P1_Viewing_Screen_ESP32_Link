# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Public repository scaffolding: LICENSE, CONTRIBUTING, CODE_OF_CONDUCT,
  SECURITY, issue/PR templates, and this changelog.
- `docs/cloud_integration_setup.md` describing how to fill in the
  placeholder credentials before flashing.
- Cloud backend (`cloud/`): FastAPI app, agent_service (Hermes/DeepSeek
  orchestrator with state graph), MQTT service, device state store, Web
  control panel, automation tasks, and pytest suite.

### Changed
- Stripped all real credentials (WiFi, MQTT, cloud API token, server IP)
  from the published source and replaced them with placeholders.

## [0.1.0] - 2026-06-23

### Added
- RA8P1 core: sensor drivers (AHT20, BH1750), device registry, dynamic port
  display, touch HMI via LVGL on ILI9488 + FT6336.
- PCA9548A I2C multiplexer with channel-routed sensor probing.
- SG90 servo (0–180°) on PWM-0 with unified capability model.
- ESP32-S3 UART bridge (115200 bit/s) handling Wi-Fi, MQTT, NTP, cloud handoff.
- Hermes/DeepSeek cloud agent: natural language → `rule_program.v1` with
  validation whitelist and parameter ranges.
- Evidence chain: `deploy_ack → execution_state → status/telemetry`.
- Headless build script `build_headless.sh` and font generation tooling.

### Known Limitations
- SG90 is open-loop; "configured/executed" does not confirm physical servo.
- Cloud models only generate candidate plans and cannot bypass the on-board
  state machine.
- No fresh sensor data → screen, web and dialog must not fabricate values.

[Unreleased]: https://github.com/Shizue123/RA8P1_EnvControl_Terminal/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Shizue123/RA8P1_EnvControl_Terminal/releases/tag/v0.1.0
