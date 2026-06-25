# Final Control Panel Delivery Baseline

## Product Shape

The screen is no longer a natural-language input endpoint.

Final role split:

- Cloud / web / API: accepts natural-language requirements and invokes the Agent.
- ESP32: transports deploy messages and acknowledgements between cloud and board.
- RA8P1: executes actuator logic and reports live status.
- Screen: shows status and exposes a small set of touch buttons for control.

## Screen Pages

### Home Page

Purpose:

- show board availability
- show link availability
- show latest sensor reading
- show current program summary
- show current panel state

Visible sections:

- top entry panel with `ACTIONS`
- `LINK`
- `SENSOR`
- `PROGRAM`
- `STATUS`

### Control Page

Purpose:

- expose touch-safe operational buttons
- show compact execution detail

Buttons:

- `STATUS`: return to home page
- `SYNC`: request UART/cloud refresh
- `CLEAR`: clear current rule and publish `UI_CLEAR`
- `DEMO`: run local SG90 demo sequence
- `CENTER`: move SG90 to 90 degrees
- `REFRESH`: same refresh action as `SYNC`

## Accepted Runtime Baseline

### Structured rule_program

Validation command:

```powershell
python .\tools\validate_rule_program_loop.py --json --text "当温度到25度时，舵机来回旋转两次" --expected-threshold 25 --wait-seconds 20
```

Expected result:

- `deploy_ack_received = true`
- `device_last_intent_type = rule_program`
- `device_script_state = DONE`
- `device_last_execution.state = DONE`
- final SG90 angle `90`

### Legacy threshold_control

Validation command:

```powershell
python .\tools\validate_threshold_loop.py --json --threshold 25
```

Expected result:

- `deploy_ack_received = true`
- `device_last_intent_type = threshold_control`
- `device_script_state = TRIGGERED`
- `device_last_execution.state = TRIGGERED`

## Host-Side Acceptance Notes

- `validate_rule_program_loop.py` now trusts final board state instead of requiring every intermediate execution event to still be present in the recent event window.
- Both validation scripts now generate millisecond-granularity default request IDs to avoid collisions during quick or near-parallel reruns.
- Windows subprocess decoding is forced to UTF-8 with replacement so Chinese responses no longer break local JSON parsing.

## Flash / Debug Baseline

### RA8P1

Preferred J-Link executable:

```text
D:\Renseas-RFPV3\JLink_V916a\JLink.exe
```

Reason:

- this version correctly identifies `R7KA8P1KF_CPU0`
- the system `JLink_V890` may misidentify the target as `ARM7`

### ESP32

Preferred workflow:

- open `esp32_s3_uart_link.ino` in Arduino IDE
- board: `ESP32S3 Dev Module`
- choose the correct COM port
- click `Upload`

If the bridge starts dropping structured deploys again, re-check:

- MQTT packet budget
- script buffer budget
- ArduinoJson document size

Current known-good bridge budget:

- `4096` bytes for packet/script/JSON handling

## Recovery Checklist

If cloud deploy seems broken, check in this order:

1. screen page switching still works
2. `ESP32 / WIFI / MQTT` state on the home page
3. `rule_program` acceptance script
4. `threshold_control` acceptance script
5. ESP32 bridge firmware version and reflash status
6. RA8P1 flash tool version (`V9.16a` path)

## Completion Meaning

This delivery baseline means the project is considered functionally complete when:

- cloud-to-board `rule_program` deploy reaches real hardware and finishes
- `threshold_control` baseline still passes
- the screen operates as a stable status/control panel
- the operator can refresh, clear, demo, and center from touch buttons
