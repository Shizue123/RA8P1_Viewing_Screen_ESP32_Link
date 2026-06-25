# Rule Program Execution Baseline

## Goal

Validate the new structured `rule_program` path on real hardware without breaking the legacy `threshold_control` deploy path.

```text
Structured deploy_script(rule_program)
-> MQTT
-> ESP32 parses rule_program first
-> RA8P1 stores bounded SG90 step sequence
-> AHT20 threshold check
-> SG90 sequence execution
-> execution_state / status / deploy_ack back to cloud
```

## Real Hardware Result

Validated on `2026-05-31` with:

- updated ESP32 bridge firmware
- updated RA8P1 main firmware
- live board connected to the public MQTT broker

Observed results:

- `rule_program` with threshold `>= 35` entered `ARMED`
- `last_intent_type = rule_program`
- event operator reported `>=`
- `rule_program` with threshold `>= 27` executed on the live board
- execution states included `TRIGGERED` then `DONE`
- final `last_execution.state = DONE`
- final `last_execution.reason = PROGRAM_DONE`
- final `last_execution.action = SG90`
- final `last_execution.angle = 90`

## Compatibility Result

The legacy path still works after the firmware upgrade:

- classic cloud `threshold_control` deploy still ACKs
- high threshold request enters `ARMED`
- low threshold request still reaches `TRIGGERED`

## Public HTTP Result

The official cloud HTTP entrypoint is now live on `2026-05-31`.

- public `openapi.json` now exposes:
  - `/agent/program/interpret`
  - `/agent/program/interpret/deploy`
  - `/agent/program/deploy`
- MQTT topic sniffing confirmed that public HTTP deploy requests really publish `deploy_script` messages to `cloudbridge/ra8p1_demo_001/script`
- a fully structured `POST /agent/program/deploy` request executed successfully on the live board
- final live-board state reported:
  - `last_request_id = rps234670`
  - `last_intent_type = rule_program`
  - `script_state = DONE`
  - `last_execution.reason = PROGRAM_DONE`
  - `last_execution.action = SG90`
  - `last_execution.angle = 90`

## Important Limitation

`deploy_ack` is still missing for `rule_program` over the public HTTP path.

- both `/agent/program/interpret/deploy` and `/agent/program/deploy` can return `ack_received = false`
- despite that, the board can still execute the structured program and report `execution_state` plus final `status`
- this means the remaining gap is now narrowed to ACK parity for structured programs, not the overall cloud-to-board execution path

## What This Means

What is now proven:

- board-side structured `rule_program` ingestion
- bounded SG90 action sequence execution
- cooldown-aware sequence completion reporting
- public `/agent/program/*` HTTP publish path
- backward compatibility for the old threshold path

What is still pending:

- make `deploy_ack` work for structured `rule_program` the same way it does for legacy `threshold_control`
- add an ACK-aware regression check so future cloud deploys fail only when publish or execution truly fail
