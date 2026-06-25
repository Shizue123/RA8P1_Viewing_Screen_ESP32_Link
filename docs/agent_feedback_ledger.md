# Agent Feedback Ledger

Last updated: 2026-06-21
Project: `D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link`

## Hard Rules

1. Before high-risk work, create a local git checkpoint first.
   - New hardware integration
   - New device embedding
   - UI port or large UI rewrite
   - Bus / wiring / protocol changes
   - Security / partition / boot configuration changes

2. Prefer minimum-change integration.
   - Keep current RA8P1/ESP32 interfaces stable when possible.
   - Reuse the existing project instead of building a parallel implementation.

3. For embedded UI on this target:
   - Design for the actual portrait screen, not only desktop mockups.
   - Avoid over-dense layouts, overlapping footer/control areas, and heavy scroll compositions.
   - Prefer a small Chinese subset font over full CJK libraries.
   - Prefer simple rendering paths when target behavior is unstable.

4. Do not rely on float `sscanf`/`scanf` parsing in UI code for runtime display values.
   - Parse with manual splitting or integer-safe formatting.

5. When the user explicitly asks to archive or mark a version:
   - create a commit if there are relevant staged changes
   - add a descriptive tag when it is a milestone or notable checkpoint

## Known Failure Patterns

### 1. Full CJK font caused flash / target issues
- Symptom: firmware grew past the target's effectively writable range and could not be programmed reliably in the current device state.
- Fix direction: use project-specific Chinese subset fonts instead of full LVGL CJK fonts.

### 2. Complex portrait UI caused white screen risk
- Symptom: target showed white screen after a heavier Chinese dashboard port.
- Fix direction: reduce object count, remove scrolling where possible, simplify styles, and verify with a lighter first screen before polishing.

### 3. UI overlap on real panel
- Symptom: footer, controls, and detail sections overlapped even when the desktop layout looked acceptable.
- Fix direction: compress fixed-height sections for the actual 320x480 portrait panel and avoid stacking too many bottom widgets.

### 4. Temperature/humidity cards showed placeholders despite sensor being online
- Symptom: `AHT20` state was online, but temperature and humidity cards remained `--.-C` and `--.-%`.
- Root cause: float `sscanf` parsing in UI code failed on target.
- Fix direction: split the preformatted sample string manually instead of parsing floats with `scanf`.

## Working Preferences From User Feedback

- Archive before risky work, not after.
- Specially mark important versions.
- Record optimization requests and mistakes so future changes account for them.
- During ongoing project work, keep extending this ledger instead of treating feedback as one-off.

## Update Protocol

Append a short entry when one of these happens:

1. The user gives a new recurring preference.
2. A bug reveals a pattern likely to recur.
3. A milestone changes the preferred engineering approach for this project.

Entry format:

```text
YYYY-MM-DD
- Context:
- User feedback or failure:
- Decision:
- Impact on future work:
```

## Entries

2026-05-25
- Context: UI port from HTML mockup to RA8P1 portrait screen.
- User feedback or failure: asked that risky work be archived first; reported white screen, overlap, and missing AHT20 values.
- Decision: switched to archive-first workflow, subset Chinese fonts, lighter portrait UI, and manual value splitting.
- Impact on future work: do not port desktop-style UI directly; verify screen density against the real panel and avoid float `scanf` in display code.

2026-05-25
- Context: project state drifted between this real hardware workspace and the larger `D:\Embedded-agent` repository.
- User feedback or failure: explicitly required that `D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link` be treated as the update baseline for future work.
- Decision: use this workspace as the source of truth for real board, ESP32 bridge, and cloud-link status; sync outward instead of back-porting stale summaries inward.
- Impact on future work: when status differs across repos, trust this workspace first and update downstream docs or snapshots from here.

2026-05-25
- Context: documentation was being refreshed before starting the next-stage cloud Agent work.
- User feedback or failure: required continued updates in this workspace so the next phase starts from the real cloud-linked baseline rather than older UART-only summaries.
- Decision: add explicit next-stage and cloud-orchestration baseline docs under this workspace and keep them aligned with the real board capabilities.
- Impact on future work: treat this workspace docs as the operational entry point for both board-side work and cloud Agent orchestration planning.

2026-05-26
- Context: real hardware smoke deploy validation resumed after the board and ESP32 were re-flashed and powered back on.
- User feedback or failure: cloud graph and MQTT publish path were healthy, but ACK could not be received until the real ESP32 bridge reconnected to the broker.
- Decision: treat "device powered, ESP32 online, AHT20 telemetry flowing" as a prerequisite gate before judging cloud deploy failures; use `screen_text` smoke plus `deploy_ack` as the live baseline.
- Impact on future work: run the real smoke gate first, then move to the first actuator execution loop instead of debugging cloud orchestration in isolation.

2026-05-26
- Context: Plan A validation for the first real threshold-control loop using only the current RA8P1 + ESP32 + AHT20 hardware.
- User feedback or failure: asked to verify the next stage and confirm whether Agent-side deploy had progressed from text display into real board-side execution.
- Decision: keep the cloud `threshold_control` contract unchanged, map the received threshold rule into a local RA8P1 action using the existing backlight path, and treat `execution_state` plus `script_state=TRIGGERED` as the first real execution baseline.
- Impact on future work: new actuator work should preserve the current cloud intent shape and extend the same `deploy_ack -> execution_state -> status` evidence chain instead of introducing a parallel execution model.

2026-05-26
- Context: repeatable validation tooling was added for the threshold-control baseline.
- User feedback or failure: a long auto-generated `request_id` caused the device to execute and publish `execution_state`, but the cloud deployment record still showed `ack_received=false` because the board-side ID path truncated the value.
- Decision: keep validation `request_id` values short for now and treat request-id length as a live protocol constraint until the UART/status buffers are widened end-to-end.
- Impact on future work: smoke and acceptance tools must avoid long request IDs; if ACK and state disagree, check ID truncation before blaming MQTT or cloud orchestration.

2026-05-26
- Context: the board looked broken after reflashing, but the phone hotspot had been left off during recovery testing.
- User feedback or failure: asked to retest after hotspot recovery and confirm whether the threshold-execution milestone was truly back.
- Decision: treat hotspot or equivalent upstream network availability as a hard precondition for board-side cloud validation; revalidated both `screen_text` ACK and `threshold_control` execution after connectivity returned.
- Impact on future work: when the board is powered but validation suddenly regresses to `ACK=false`, check hotspot or Wi-Fi availability before rolling back code or reflashing again.

2026-06-06
- Context: live Aliyun cloud/web drift was repaired after RA8P1 and ESP32 were reflashed and the public site was revalidated.
- User feedback or failure: the public Hermes path needed real browser/API verification, explicit I2C diagnostics, and clearer stage labels; direct API tests initially used the wrong device id and falsely looked like "published but never ACKed".
- Decision: deploy the local `routes.py` stage/diagnostics fixes plus the live chat bundle patches, and treat `ra8p1_demo_001` from `/api/health` as the real public device baseline instead of assuming `ra8p1-device`.
- Impact on future work: when live publish succeeds but state stays empty, verify the device id from `/api/health` and broker client logs first; do not diagnose that situation as a Hermes or MQTT failure until the target id is confirmed.

2026-06-06
- Context: public Hermes deploy semantics were rechecked after the correct device id was confirmed and the cloud service was redeployed.
- User feedback or failure: immediate Hermes replies, deployment history, and deployment detail initially diverged on `screen_text` requests, showing `已 ACK` even after the board had already emitted `execution_state`.
- Decision: add a short post-ACK execution wait in the cloud route, scan request-scoped event history, and keep a narrow `screen_text` fallback so once-only screen display requests can still be reported as `已执行` after the execution event scrolls out of the in-memory event window.
- Impact on future work: when evaluating whether a deploy truly executed, distinguish between immediate reply semantics and later history semantics; use `execution_state` first, but for one-shot `screen_text` on the latest request, `ACK + latest request match + screen_text` is an acceptable executed signal.

2026-05-26
- Context: public API entrypoint and real-hardware smoke tooling were still easy to misjudge during remote validation.
- User feedback or failure: asked to make the公网入口 directly usable and stop `cloud_smoke` from falsely failing on the real board path.
- Decision: expose `http://<cloud-server-ip>/health` through nginx, make `cloud_smoke` auto-resolve `local -> domain -> ip`, and pass `device_id` through the `speech_deploy` path so `speech_ack` is checked against the real device.
- Impact on future work: prefer domain or auto-resolved smoke entrypoints over hard-coded stale URLs, and treat `speech_ack / language_ack / structured_ack` as a matched trio in real-hardware smoke results.

2026-05-31
- Context: the first real SG90 closed loop had already been validated, and the next-stage definition was being updated across the real workspace and the main project.
- User feedback or failure: explicitly asked not to continue `BUZZER` or other new external-hardware work yet, and to move into the next stage instead.
- Decision: redefine the next stage as consolidating the current `threshold_control -> SG90 -> execution_state` execution model, sync that baseline back into `D:\Embedded-agent`, and defer additional actuator expansion.
- Impact on future work: when stage planning conflicts with already-validated hardware reality, treat the verified SG90 loop as the baseline and prioritize model/document/code sync before adding new peripherals.

2026-05-31
- Context: the user clarified the real meaning of "code downlink" after the fixed SG90 threshold loop passed.
- User feedback or failure: the target is not just preset cloud templates; the user wants natural language input, board-to-cloud transfer through ESP32, DeepSeek plus a custom Agent and project data to generate executable control logic, then downlink through ESP32 so RA8P1 controls peripherals.
- Decision: make the next phase "cloud Agent dynamic action plan" first, using a restricted validated action-plan DSL before any arbitrary native code, Lua, or WASM runtime is placed on the board.
- Impact on future work: do not call the current fixed `threshold_control` template the final code-downlink goal; focus on DeepSeek v4 pro, knowledge-grounded generation, safety validation, MQTT downlink, and SG90 execution evidence.

2026-05-31
- Context: phase 2 implementation moved from cloud-only planning into real deploy protocol changes.
- User feedback or failure: the next usable milestone had to become an actual `rule_program` downlink path instead of staying at `/agent/program/interpret` preview only.
- Decision: keep MQTT `deploy_script` compatible, add structured `rule_program` to the payload, let ESP32 prefer structured parsing, and let RA8P1 execute bounded SG90 step sequences with cooldown while preserving the old threshold-control fallback.
- Impact on future work: any real-hardware validation of dynamic action plans now requires the updated ESP32 bridge firmware in addition to the RA8P1 main firmware; old ESP32 builds will only preserve the legacy single-angle threshold path.

2026-05-31
- Context: real-hardware validation resumed immediately after the ESP32 bridge firmware was reflashed with `rule_program` support and the RA8P1 main firmware was rebuilt and reflashed.
- User feedback or failure: the public cloud API stayed reachable, but SSH to `<cloud-server-ip>:22` timed out, which blocked normal server-side code sync and service restart for the new `/agent/program/*` routes.
- Decision: validate the new board-side phase by publishing a structured `deploy_script` with `intent_type=rule_program` directly to MQTT, then confirm `ARMED -> TRIGGERED -> DONE` through the existing device-state API; also re-run the legacy `threshold_control` path to confirm backward compatibility.
- Impact on future work: the board-side `rule_program` path is now proven on real hardware, but the official cloud HTTP API for this phase is not complete until SSH access returns and the server process is updated.

2026-05-31
- Context: the user asked to transfer the "online compile and debug" capability to other computers and other agents.
- User feedback or failure: the process must be reproducible, not dependent on one operator's memory or ad hoc terminal decisions.
- Decision: document the workflow as an agent-oriented runbook with fixed prerequisites, variable placeholders, exact command order, success criteria, and fallback branches.
- Impact on future work: future agents should follow the runbook first and treat undocumented one-off actions as exceptions that must be written back into project memory.

2026-05-31
- Context: the user refined the documentation target after the first runbook draft was written.
- User feedback or failure: they do not want project-specific paths, hosts, or device names in the transferable material; they want the generic technical stack, technical methods, and a reusable prompt for other agents.
- Decision: add a project-agnostic prompt template focused on toolchain categories, execution discipline, verification methods, and fault-isolation order instead of repository-specific context.
- Impact on future work: when documenting reusable agent capability, separate "generic method" from "project instance" so the same workflow can be transplanted to another machine or team.

2026-05-31
- Context: SSH access to the public cloud server recovered later in the session, so the staged `rule_program` API could finally be deployed through the normal service path.
- User feedback or failure: after the new `/agent/program/*` routes were published, the first natural-language HTTP deploys returned `ack_received = false`, which could be mistaken for a full execution failure.
- Decision: separate the validation into three layers: confirm public `openapi` exposure, sniff the MQTT `script` topic to prove cloud publish works, and then re-run a fully structured `/agent/program/deploy` request to verify real board execution independently of ACK handling.
- Impact on future work: treat `rule_program` HTTP deploy as "cloud publish + real execution proven, deploy_ack still pending" until the ESP32/RA8P1 path emits `deploy_ack` for structured programs the same way it already does for the legacy threshold path.

2026-05-31
- Context: the user provided an external successful LVGL 9.3 + FT6336 touch-debug writeup and asked whether the touch path is already solved in this project.
- User feedback or failure: the reference route is valuable, but it comes from another project and may not map 1:1 onto the current RA8P1 screen-link workspace.
- Decision: treat the document as a touch-chain reference, not proof of completion here; keep its reusable lessons (I2C timeout, optional bus recovery, RELEASED-state coordinate clear, safer reset timing), but judge project status only by local code integration.
- Impact on future work: for this workspace, touch is not "solved" until `ft6336_init/scan` is actually wired into a local `lv_port_indev.c/h` path and driven from `hal_entry`, even if a sibling project with similar hardware already proved the general route.

2026-05-31
- Context: the user chose the "best-solution" path for touch, local pinyin input, phased cloud candidates, and `rule_program` ACK completion.
- User feedback or failure: they want touch finished first, then Phase A/B/C/D to proceed in order, while ACK work continues in parallel.
- Decision: wire FT6336 into a new local `lv_port_indev.c/h`, add a modal `Pinyin Input` panel as Phase A scaffolding on the RA8P1 UI, and raise the UART line/queue capacity on both RA8P1 and ESP32 to reduce `rule_program` ACK loss under multi-line structured deploys.
- Impact on future work: the next validation step is now hardware-first, not design-first; touch must be manually tapped on the real panel, and the ESP32 bridge must be reflashed before ACK conclusions are trusted.

2026-06-01
- Context: the first touch bring-up showed live touch counts, but the on-screen corner calibration values collapsed to clipped numbers like `319,479` and `63,479`.
- User feedback or failure: they explicitly asked to stop patching around the UI and instead study working FT6336 examples and rewrite the touch path from reference code.
- Decision: remove the dead `INPUT` entrypoints, switch the board UI into a calibration-first mode, and rewrite `ft6336.c` around a full-frame FT6336 read model inspired by `RAKWireless/RAK14014-FT6336U` and `codewitch-honey-crisis/htcw_ft6336` rather than the previous minimal 4-byte scan.
- Impact on future work: do not trust LVGL button failures as a pure widget problem until raw FT6336 coordinates are verified on-screen; keyboard/input phases must stay blocked until the rewritten touch driver yields believable raw corner coordinates.

2026-06-01
- Context: the user asked whether touch calibration could proceed without repeatedly sending photos, and requested an on-screen indicator showing that a touch signal had been read.
- User feedback or failure: screen-only debug text was too slow and error-prone for calibration, and RTT integration on this machine did not produce a dependable live log despite being compiled into the firmware.
- Decision: add a dedicated on-screen `Signal:` status label driven by the touch debug path, keep the RTT hooks in place, and switch the primary calibration workflow to direct J-Link RAM probing of the latest touch sample (`raw_x/raw_y/mapped_x/mapped_y/pressed/seq`) so the operator only has to tap and report which target they touched.
- Impact on future work: future touch debugging in this workspace should prefer "board tap + host-side RAM read" over photo-based coordinate transcription whenever J-Link is attached, because it is more reproducible and does not consume the ESP32 UART channel.

2026-06-01
- Context: after the FT6336 raw-frame fix, four corner samples were finally readable and produced a usable first-pass calibration box.
- User feedback or failure: the user explicitly warned that these corner values were collected by fingertip and may contain human touch offset, so they should be treated as approximate rather than exact panel-edge truth.
- Decision: store the four-point set as a coarse baseline for bring-up (`TL/TR/BL/BR`) and use it only for rough axis scaling and hit-test recovery, not as final precision calibration constants.
- Impact on future work: if text-entry UI or small-button hit accuracy still feels off, re-calibrate with a smaller contact point (stylus, fingernail, or tighter target markers) before locking the production mapping.

2026-06-01
- Context: repeated LVGL homepage rewrites were slowing progress on the actual natural-language control milestone.
- User feedback or failure: the user explicitly asked to stop spending time on screen polish and prioritize the full functional chain first.
- Decision: downgrade the UI objective to "good enough to enter/send text", keep touch at coarse-calibration quality for now, and prioritize `RA8P1 input -> ESP32 HTTP -> cloud interpret/deploy -> MQTT downlink -> execution` before any further homepage optimization.
- Impact on future work: until the end-to-end chain is proven from board input to actuator execution, avoid major UI rewrites and treat layout refinement as a follow-up track rather than a gate.

2026-06-01
- Context: end-to-end natural-language control validation resumed after the ESP32 bridge was updated to call the cloud `/agent/program/interpret/deploy` API directly.
- User feedback or failure: the chain had to be proven quickly, even if that meant bypassing the unfinished touch/UI flow and injecting input text directly into the board runtime.
- Decision: use J-Link RAM injection to queue a board-side input string, verify `RA8P1 -> ESP32 HTTP -> cloud -> local rule_program apply -> SG90 DONE`, and change the ESP32 bridge to apply the returned deploy message locally instead of waiting for the MQTT script loopback.
- Impact on future work: the functional baseline is now "screen input pending, cloud/execute path proven"; future work should restore the UI on top of this known-good transport path instead of re-debugging cloud execution.

2026-06-06
- Context: after the user reflashed both RA8P1 and ESP32, live hardware diagnosis resumed with J-Link back online and the public Hermes route already repaired.
- User feedback or failure: the cloud now showed `i2c.count = 0` and `aht20.diag = write addr nack`, but that could still be misread as a cloud/parser regression instead of a physical bus issue.
- Decision: verify the real board state directly from RA8P1 RAM (`g_aht20_diag = 2`, `g_i2c_bus_s1_diag = 2`) and read the live UI/status strings over J-Link; then teach cloud `device_diagnostics` to interpret `Bus S1 scan ok + count 0 + write addr nack` as "no device ACK on P511/P512, check AHT20 power/wiring first."
- Impact on future work: when live telemetry shows `i2c.diag = ok`, `i2c.count = 0`, and `AHT20 write addr nack`, treat it as a board-side physical/wiring/power problem before suspecting Hermes, MQTT, or the I2C scan framework.

2026-06-01
- Context: the user asked to keep pushing forward quickly and stop spending time on homepage polish while the chain itself was already working.
- User feedback or failure: previous Chinese-heavy LVGL homepages kept regressing because the panel budget and subset font coverage were both too tight for a dashboard-style layout.
- Decision: replace `app_ui.c` with a minimal ASCII-first two-page UI (`home + input`) and re-validate the proven cloud execution path with live J-Link RAM injection after the rewrite.
- Impact on future work: Phase A should now focus on one physical proof only, `INPUT -> type text -> SEND`, because the transport, cloud deploy, `deploy_ack`, and SG90 execution path were re-proven after the UI simplification under request `nl_886322`.

2026-06-02
- Context: the `INPUT` button still would not open the input page even after the transport chain and minimal UI were already working.
- User feedback or failure: touch counts increased, but the page stayed on the home screen, which showed that "touch detected" was not the same as "button hit".
- Decision: stop guessing at LVGL event types, treat the issue as a touch-hit-test problem, remap FT6336 coordinates to LVGL absolute screen coordinates with the top status-bar offset included, add light release debounce, expand the button click area, and add an on-screen `input hit/miss/release` probe.
- Impact on future work: when touch input works but buttons do not, first verify the full chain `raw touch -> mapped absolute coordinate -> object hit`, because the successful fix here was coordinate-space alignment plus observability, not a stack-size or cloud-chain change.

2026-06-02
- Context: after the touch-hit fix, the user entered `nihao` from the real on-screen keyboard and pressed `SEND` for a second end-to-end verification.
- User feedback or failure: no new deployment appeared in the cloud list, which initially looked like the screen-submit path was still broken.
- Decision: read RA8P1 RAM directly to trace the submit path and verify that `g_pending_input_text` was consumed by the main loop; then replay the same cloud call manually and confirm the backend returns HTTP `422` with `no supported temperature threshold found for rule_program` for bare `nihao`.
- Impact on future work: Phase A is now proven through the real screen path (`input page -> SEND -> cloud request`), and the next blocker is no longer touch or UART transport but Phase B/C itself: pinyin must be resolved into candidate Chinese or a full natural-language command before `/agent/program/interpret/deploy` can succeed.

2026-06-02
- Context: the user changed product direction after Phase A proved that the screen can submit text, but Phase B/C would add substantial input-method complexity.
- User feedback or failure: they no longer want the screen to be the natural-language input endpoint; the screen should only provide page switching and project-required function buttons.
- Decision: drop the touchscreen pinyin/candidate-input roadmap as the primary path and reposition the screen as a lightweight control/status UI, while moving natural-language input upstream to cloud/web/API tooling.
- Impact on future work: future implementation should prioritize button-driven pages such as status, confirm/deploy, retry, stop/clear, and view switching; cloud coding/deploy remains the core milestone, but the screen no longer blocks it through IME requirements.

2026-06-02
- Context: the new button-only control panel was verified on real hardware after the screen-input roadmap was dropped.
- User feedback or failure: `ACTIONS` successfully entered the control page, `SYNC`, `CLEAR`, and `REFRESH` changed the live `Signal` state, and `DEMO` produced visible screen-side activity; however, the initial home/status page was visibly clipped at the bottom.
- Decision: treat the control-page button chain as proven, but shrink the home-page card height budget and shorten its summary text so the five-panel layout actually fits inside the 320x480 body area.
- Impact on future work: for this panel size, control/status homepages should budget total card height against the `448px` body first and keep top-level summaries to 3-4 short lines; the richer diagnostics can stay on the secondary control page without blocking the main status screen.

2026-06-02
- Context: a reflashing attempt failed right after the home-page budget fix even though the build itself succeeded.
- User feedback or failure: the system-wide `C:\Program Files\SEGGER\JLink_V890\JLink.exe` did not recognize the RA8P1 target device and silently fell back to `ARM7`, which made SWD flashing fail.
- Decision: switch back to the previously proven Renesas-side J-Link toolchain at `D:\Renseas-RFPV3\JLink_V916a\JLink.exe` using device `R7KA8P1KF_CPU0` for board flashing in this workspace.
- Impact on future work: when a fresh shell session needs to flash this board, prefer the `V9.16a` J-Link path first; if the target suddenly appears as `ARM7`, stop and swap tools instead of debugging the firmware image.

2026-06-02
- Context: after the button-only control panel was stable, the final remaining regression was that `threshold_control` still worked but structured `rule_program` stopped reaching the board after an ESP32 reflash.
- User feedback or failure: the cloud side published `rule_program` successfully, but the device stayed `IDLE` with no new request/script IDs, which made the failure look like a protocol or firmware-version mismatch rather than a UI problem.
- Decision: enlarge the ESP32 bridge receive budgets (`MQTT packet`, `script buffer`, `ArduinoJson` document) from `1536` to `4096`, add explicit `mqtt oversize / mqtt parse` diagnostics, rebuild the bridge, and reflash again before re-running the structured loop serially.
- Impact on future work: `threshold_control` passing does not prove `rule_program` can survive the same bridge build; on this project, large structured deploys need a larger receive/parse budget than the legacy threshold Lua path.

2026-06-02
- Context: the final serial validation pass was re-run after the ESP32 bridge budget fix and a fresh IDE upload.
- User feedback or failure: the previous `rule_program` validation still showed `ok=false`, but the board-side evidence already showed `ack_received=true`, `last_intent_type=rule_program`, and `script_state=DONE`.
- Decision: fix both validation scripts to force UTF-8 subprocess decoding on Windows, and parameterize `validate_rule_program_loop.py` so the expected threshold is no longer hard-coded to `35`.
- Impact on future work: the current stable acceptance baseline is now real and repeatable on this machine: `rule_program` with `25°C` reaches `DONE` with final SG90 angle `90`, and `threshold_control` with `25°C` reaches `TRIGGERED` with `deploy_ack=true`.

2026-06-02
- Context: after the control-panel UI cleanup, a fresh `rule_program` replay reached `DONE` on the real board, but the validation script still reported `ok=false`.
- User feedback or failure: the false negative came from two host-side issues rather than firmware failure: the script required `TRIGGERED/DONE` to both still be present in the most recent event slice, and the default request IDs were only second-granularity so closely timed validations could collide and overwrite each other.
- Decision: update `validate_rule_program_loop.py` to trust the board's final `last_execution/last_event` state when recent execution events have rolled out of the short history window, and change both validation scripts to use millisecond-granularity default request IDs.
- Impact on future work: when these acceptance scripts are reused on Windows, sequential or near-parallel runs should no longer collide on `request_id`, and a real board-side `DONE` state will not be misclassified just because the event feed has already been dominated by status/telemetry messages.

2026-06-02
- Context: the user asked to finish the last two stages in one pass, meaning the control panel had to be finalized and the project needed a handoff-grade acceptance baseline rather than another partial UI experiment.
- User feedback or failure: the chain itself was already working, but the panel still carried too much debug flavor and there was no single delivery document describing the final operator role split, touch buttons, validation commands, and recovery checklist.
- Decision: freeze the screen as a two-page `status + control` panel, simplify the visible summaries to operational state (`Mode / REQ / SCRIPT / ACK / Action / State`) instead of touch-debug text, add `docs/final_control_panel_delivery_baseline.md`, rebuild and reflash RA8P1, and rerun both real acceptance loops.
- Impact on future work: this workspace now has a final delivery baseline where the screen is not an NL input endpoint, `rule_program` at `25°C` reaches `DONE`, `threshold_control` at `25°C` reaches `TRIGGERED`, and future work should be additive product refinement rather than another architectural pivot.

2026-06-03
- Context: the user asked to finish the local project's final delivery-confirmation stage before moving on to the broader `D:\Embedded-agent` goal tree.
- User feedback or failure: the new combined delivery runner showed a specific stale-session pattern: the board still published telemetry and old status, but fresh deploys no longer advanced `last_request_id` or produced new ACKs.
- Decision: treat this as a live runtime-state issue rather than as evidence that the engineering baseline regressed, add stale-runtime detection to `tools/validate_delivery_baseline.py`, and record the current status in `docs/delivery_confirmation_status_2026-06-03.md`.
- Impact on future work: if combined delivery validation fails while telemetry still flows and the device stays stuck on an older request, check bridge/runtime freshness first; do not immediately treat it as a cloud or protocol regression.

2026-06-03
- Context: after the local project baseline was frozen, the user asked to continue directly toward the broader `D:\Embedded-agent` target instead of stopping at the side workspace.
- User feedback or failure: several main-repo docs still described the project as mock-first or board-startup-stage, which no longer matched the verified `AHT20 + SG90 + control panel` real-hardware baseline.
- Decision: sync the current stage wording into `D:\Embedded-agent` docs (`README`, `交接说明`, `开发文档`, `路线图`, `云端动态动作计划阶段方案`), add a dedicated `主仓目标同步状态_2026-06-03.md`, and mirror the latest local `firmware` source view into the main repo.
- Impact on future work: the main repo can now treat "real chain established, remaining work is goal sync + peripheral coverage + demo acceptance" as the active phase instead of re-debugging whether cloud-to-board execution works at all.

2026-06-03
- Context: the user chose the web page as the formal natural-language entry point and asked to move quickly toward a usable full flow, while keeping the board screen as display/control only.
- User feedback or failure: the old cloud web console still targeted the legacy `intent/Lua` path, so even though the real `rule_program` hardware chain existed, the webpage itself was not aligned to the actual product path.
- Decision: rewrite `D:\Embedded-agent\cloud\web` around `/agent/program/interpret` and `/agent/program/interpret/deploy`, add parsed-program/deploy/state summaries, deploy the new static web files to the live server, and treat the current online board's "old request never advances" symptom as a stale runtime issue rather than as a web implementation failure.
- Impact on future work: the formal UX is now "web NL input -> cloud rule_program deploy -> board screen status/control"; if live requests still do not advance, debug board/bridge freshness first instead of reworking the web console again.

2026-06-03
- Context: the user asked to proceed with the earlier dedicated cloud-agent design, but first reference mature open-source patterns instead of inventing another one-off parser path.
- User feedback or failure: the project already had `ProgramGraph`, manifests, and a verified web deploy path, but lacked an explicit specialized Agent layer for knowledge assembly, planning traces, and long-term run memory.
- Decision: keep large platforms such as Dify and Flowise outside the repo, borrow architecture ideas from LangGraph, PydanticAI, and Mem0, add `specialized_agent_v1` plus `agent_runs` on top of the existing FastAPI/ProgramGraph path, and preserve `/agent/program/*` as the stable public entry while exposing `/agent/runtime/*` for direct Agent introspection.
- Impact on future work: the cloud path is no longer just "parser + deploy"; future DeepSeek integration and multi-peripheral expansion should attach to the specialized Agent layer instead of bypassing it, and `/api/agent/runtime/status` is now the fastest way to confirm which knowledge sources and routing mode the live server is using.

2026-06-03
- Context: follow-up work resumed from the handoff report with DeepSeek switch-over as the first priority, but the live runtime status endpoint was token-protected and local config still defaulted to `LLM_PROVIDER=template`.
- User feedback or failure: it was too easy to mistake a configured provider string for a truly ready DeepSeek planner, especially when `DEEPSEEK_API_KEY` might still be missing and rule-based fallback remains available.
- Decision: extend `specialized_agent_v1` runtime status to report `planner_mode`, DeepSeek configuration readiness, selected model/base URL, and whether rule-based fallback is still available.
- Impact on future work: check `/api/agent/runtime/status` for `planner_mode=deepseek_primary` before calling the DeepSeek migration complete; `llm_provider=deepseek` alone is no longer enough evidence.

2026-06-03
- Context: local cloud-agent validation resumed while the board was intentionally not powered, so only the server-side `runtime/status -> interpret -> deploy -> runs` segment could be closed today.
- User feedback or failure: this machine's global `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` settings sent even `127.0.0.1` requests into the local proxy and produced false `502 Bad Gateway` results against a healthy local uvicorn process.
- Decision: add a proxy-bypassing `tools/cloud_smoke/runtime_agent_smoke.py` path and document that localhost validation for this project should use an opener with `ProxyHandler({})` or equivalent no-proxy behavior.
- Impact on future work: when local cloud smoke suddenly returns `502`, verify proxy bypass before debugging FastAPI, MQTT, or the specialized Agent itself.

2026-06-03
- Context: after the board was powered back on, the first priority was to complete the specialized-Agent DeepSeek cutover and then re-run a real hardware deploy instead of stopping at local smoke only.
- User feedback or failure: the live server still exposed old `runtime_status` fields and still defaulted to `LLM_PROVIDER=template`, even though the local code path could already prove `deepseek-v4-pro` planning.
- Decision: update the live `runtime_agent.py`, switch the server `.env` / `cloud/.env` to `LLM_PROVIDER=deepseek` with `DEEPSEEK_MODEL=deepseek-v4-pro`, restart `embedded-agent-cloud`, and verify that `/api/agent/runtime/status` now reports `planner_mode=deepseek_primary`.
- Impact on future work: the formal online baseline is now specialized-Agent + DeepSeek-first, not template-first; future planner/debug work should treat `program_source=specialized_agent_v1:deepseek:deepseek-v4-pro+rule_program_v1` as the expected healthy source string.

2026-06-03
- Context: a clean serial online deploy was re-run after the DeepSeek cutover using a `25°C` threshold so the already-online AHT20 state would trigger immediately on the real board.
- User feedback or failure: parallel validation requests can overwrite `last_request_id` evidence and make a successful deploy look stale if two rule-program requests race each other.
- Decision: re-run a single serial request and verify the same request ID through `deploy_ack`, `last_request_id`, `last_script_id`, `script_state=DONE`, and `last_execution.threshold=25`.
- Impact on future work: when proving a new online milestone, avoid parallel deploy smoke on the same device; the current real-hardware DeepSeek baseline is now `deploy_ack=true` plus board status showing the same request ID reaching `DONE`.

2026-06-03
- Context: the live web page still showed `/api/agent/interpret/deploy` timeouts even after the backend had already switched to DeepSeek-first `rule_program` planning.
- User feedback or failure: the public SPA served by nginx was not the same code as `cloud/web/app.js`; it was a separate bundle under `/var/www/cloudbridge` and its chat module still called the old intent route.
- Decision: patch the active web bundle under `/var/www/cloudbridge/assets/chat-*.js` to use `/agent/program/interpret/deploy`, add a cache-busting version suffix to `/var/www/cloudbridge/index.html`, and raise the DeepSeek HTTP read timeout/retry behavior on the server so the public chat path no longer fails on easy prompts due to a 30s model read timeout.
- Impact on future work: when the public web UI and FastAPI behavior disagree, inspect the nginx-served SPA bundle separately from `cloud/web`; today’s confirmed public baseline is that the chat bundle now points at `program/interpret/deploy` and a live `webfix_*` request reached `ack_received=true` with the device status advancing to the same request ID.

2026-06-03
- Context: the user asked for a simpler explanation of how online flashing and debugging works over a data cable, and wanted material that another computer's agent could follow directly.
- User feedback or failure: the transferable docs should be easier to read, less tied to one project instance, and suitable for handing off to another operator or agent without much background.
- Decision: add a short plain-language markdown handoff focused on `computer -> USB -> J-Link -> SWD -> MCU`, the minimum execution order, and simple fault-layer judgment.
- Impact on future work: when writing transferable embedded runbooks, keep one "engineering-detailed" version and one "plain-language handoff" version so both humans and agents can use them quickly.

2026-06-03
- Context: the public web chat still failed after the backend had already switched to DeepSeek-first planning, and repeated relogin did not clear the error on the user's browser.
- User feedback or failure: the nginx-served SPA could reach the old or compatible deploy route, but its live `client-*.js` request layer only attached `X-API-Token` from volatile in-memory auth state; once that state drifted, the browser kept sending unauthenticated requests and showed `missing or invalid API token`.
- Decision: patch the active public `client-*.js` bundles under `/var/www/cloudbridge/assets` so API requests fall back to `localStorage.getItem("ra8p1-api-token")` when the in-memory store is empty, then verify the public asset contents directly from `https://ra8p1cloud.com/assets/...`.
- Impact on future work: when the public UI shows repeated 401s despite relogin, inspect the live bundled request client instead of only the login form or backend token validator; browser auth drift can survive backend and route fixes unless the deployed SPA has a persistent-token fallback.

2026-06-03
- Context: the user set a new goal to use `Hermes-specialized-for-RA8P1 = Hermes shell + current rule_program control core` until the web natural-language-to-board-execution flow is complete, while the board is currently powered off.
- User feedback or failure: a direct replacement of the hardware control core would risk losing the already verified `rule_program -> ProgramGraph -> MQTT -> ACK/DONE` evidence chain, but the existing Agent still needed a clearer long-running identity, goal, memory, and continuity layer.
- Decision: upgrade the cloud runtime Agent to `hermes_ra8p1_v1`, keep `specialized_agent_v1` only as a compatibility name, expose Hermes identity/goals/memory/cycle hooks in `/agent/runtime/status`, and keep all hardware actions restricted to the existing `rule_program.v1` control core.
- Impact on future work: treat Hermes as the Agent shell and continuity layer, not as a bypass around validation or deployment; while the board is off, validate through no-ACK cloud smoke, and when it is powered on finish the same request through `deploy_ack` plus board `DONE`.

2026-06-03
- Context: after the user powered the board back on, the first real-board Hermes-path validation was rerun using `POST /api/agent/program/interpret/deploy` with `wait_for_ack=true`.
- User feedback or failure: the cloud and device-edge portions advanced, but the board-side closure did not: `program_source=hermes_ra8p1_v1:deepseek:deepseek-v4-pro+rule_program_v1`, deployment record `published=true`, device status advanced to `last_request_id=hermes_live_1780498432930` and `script_state=PENDING`, yet `ack_received=false`, `last_deploy_ack=null`, `uart=waiting`, and `AHT20` stayed `offline`.
- Decision: treat the remaining blocker as a live `ESP32 -> RA8P1 / AHT20` runtime issue instead of a cloud, web, or Hermes-planning issue; preserve the current cloud baseline and debug the serial/board side next.
- Impact on future work: when the public web/API can push a new `last_request_id` to the device and hold `PENDING` without any ACK, focus on RA8P1 UART liveness, board-side sensor bring-up, and whether the bridge ever transitions from `waiting` to `online`; do not spend more time reworking DeepSeek, rule_program, or the web token path.

2026-06-03
- Context: after another power cycle, the board-side runtime recovered enough to retry the full public web/API path again under the Hermes-specialized shell.
- User feedback or failure: one intermediate public request returned `504 Gateway Time-out`, but the deployment record later proved the request had still published and reached `deploy_ack`; a follow-up public request then returned normally and completed end to end.
- Decision: validate success using the public path `POST /api/agent/program/interpret/deploy` with request `hermes_web_ok_1780498943903`, confirm `ack_received=true`, then confirm device `last_request_id=hermes_web_ok_1780498943903`, `last_deploy_ack.request_id=hermes_web_ok_1780498943903`, `last_event.state=DONE`, `script_state=DONE`, `last_execution.threshold=26`, and final `angle=90`.
- Impact on future work: the formal objective is now achieved for the current baseline: public web/API natural language -> `hermes_ra8p1_v1` -> DeepSeek -> `rule_program.v1` -> MQTT -> ESP32 -> RA8P1 -> SG90 -> `ACK/DONE`; if another public request shows `504`, check deployment history before assuming execution failed, because nginx timeout can lag behind a real board-side success.

2026-06-04
- Context: repeated relogin still did not let the user control the board from the public natural-language page, so the full live stack was re-audited from browser UI to cloud API to board telemetry.
- User feedback or failure: the live public SPA under `/var/www/cloudbridge` had drifted from the backend contract in two ways: `client-ZmmAefkc.js` still used a `10s` request timeout, and the natural-language/deploy views still summarized responses as generic failure or fallback text unless the backend returned older `intent_*` plus layered status fields. At the same time, the actual board execution blocker was separate: live device telemetry showed `AHT20.status=offline`, `crc_ok=false`, and temperature-triggered rules stayed `ARMED/ACKED` instead of `TRIGGERED/DONE`.
- Decision: patch `D:\\Embedded-agent\\cloud\\app\\api\\routes.py` so `/agent/program/interpret/deploy` and related deploy endpoints emit UI-compatible `intent_source`, `intent_confidence`, `status`, `publish_layer`, `ack_layer`, `execution_layer`, `latest_device_state`, and a human-readable `message`; deploy that patch to the live server and restart `embedded-agent-cloud` with `sudo`. Patch the live SPA bundles under `/var/www/cloudbridge/assets` so the active client timeout is `90s`, the natural-language summary surfaces backend `message` text for executing states, and deploy cards prefer `execution_layer.detail` over the raw state code. Separately, harden `src/aht20.c` with bus-idle checks, bus-recovery pulses, retryable init/read paths, and open-drain-style line release so the next firmware flash can recover the sensor path cleanly.
- Impact on future work: if the public web UI says natural-language control failed, first distinguish "page misreported a successful deploy" from "board cannot satisfy the trigger". The current public UI baseline is now: browser NL input returns a three-layer success/armed view and explicitly reports `AHT20` offline when that is the real blocker. The remaining unresolved step is physical firmware deployment: this machine currently sees `J-Link driver` as `Disconnected`, so the new `aht20.c` recovery patch cannot be flashed or hardware-verified until the debugger/USB connection is restored.

2026-06-04
- Context: the user clarified that the intended product is not merely a deterministic temperature/servo parser, but a Hermes-centered cloud agent that can research GitHub/web sources, store reusable knowledge, use a model to reason over that knowledge, generate bounded executable control code, and downlink it to the board.
- User feedback or failure: a short-term parser fast path was useful for avoiding public UI timeouts, but it must not be mistaken for the final architecture. Future coding should follow the repo-local `andrej-karpathy-skills` discipline: think before coding, keep changes simple, make surgical edits, and define verifiable success criteria.
- Decision: treat Hermes as the required orchestration shell for future cloud-Agent work, with DeepSeek/model reasoning over project knowledge as the normal planning path and deterministic parsers only as validated fallbacks or latency guards. Before larger coding changes, first check relevant GitHub/open-source projects for reusable patterns.
- Impact on future work: every future Agent/cloud-control milestone should explicitly state whether it advances research ingestion, knowledge storage, model reasoning, code generation, safety validation, downlink, or hardware execution evidence; do not report "natural-language control solved" unless those layers are verified against the requested scope.

2026-06-04
- Context: the user asked to stop treating Hermes as only a local shell abstraction and instead install a complete official Hermes on the cloud host so incoming requests can be processed through it.
- User feedback or failure: the existing `hermes_ra8p1_v1` runtime shell preserved continuity and logging, but planning still depended on direct in-process parsers/DeepSeek calls rather than a full external Hermes runtime with its own tools and workspace context.
- Decision: install the official Hermes Agent under `/home/admin/.hermes/hermes-agent`, verify one-shot execution against DeepSeek on the live cloud host, add a `hermes_official` planner path to the local cloud codebase, and switch the live service `.env` to `LLM_PROVIDER=hermes_official` with explicit Hermes binary/workdir settings. Keep `ProgramGraph` and MQTT downlink as the safety-constrained execution core.
- Impact on future work: the live cloud planner baseline is now `planner_mode=hermes_official_primary`; responses can be attributed to `hermes_official:deepseek-v4-pro+...` instead of only local parsers. The remaining gaps are scope-related, not install-related: `/agent/program/interpret/deploy` is still a rule-program-oriented entry, and board-side `AHT20 offline` still prevents temperature-triggered requests from reaching `TRIGGERED/DONE`.

2026-06-05
- Context: the user goal continued from "Hermes official installed" to "webpage talks directly to cloud Hermes, keeps a conversation session, and can still drive real hardware through the existing safe downlink core".
- User feedback or failure: the active nginx-served SPA under `/var/www/cloudbridge/assets` still used the old `/agent/program/interpret/deploy` chat path, did not preserve `session_id`, and only rendered execution summaries instead of Hermes replies. In parallel, plain conversational `/agent/hermes/chat` requests initially still failed online until the service was restarted with the plain-text fallback already present in `hermes_official.py`.
- Decision: patch the active public `chat-*.js` bundles to call `/agent/hermes/chat`, persist `ra8p1cloud_hermes_session` in `localStorage`, and surface `assistant_message` in the visible chat reply. Add a regression test for non-JSON Hermes chat replies and route the legacy natural-language deploy endpoints (`/agent/interpret/deploy` and `/agent/program/interpret/deploy`) through `HermesChatRequest` whenever `LLM_PROVIDER=hermes_official`, then deploy and restart the live cloud service.
- Impact on future work: the current verified public baseline is now stronger than "Hermes can plan": public `/api/agent/hermes/chat` can answer in Chinese with `status=answered`, reuse the same `session_id` across turns, and in the next turn turn that same session into a real screen command with `action_kind=intent`, `intent_type=screen_text`, and `ack_received=true`. The two legacy deploy routes now also return `hermes_official:deepseek-v4-pro+chat` responses instead of bypassing Hermes. Remaining scope gap: AHT20 is still offline, so temperature-triggered hardware automation is not yet a true end-to-end Hermes success case.

2026-06-05
- Context: after J-Link/USB recovered, the live Hermes path could deploy temperature rules and receive device ACKs, but AHT20 stayed offline so threshold automation remained armed instead of triggered.
- User feedback or failure: servo motion still depends on independent power, and the board is currently connected by data cable for J-Link debugging; ESP32 firmware changes still require the user to flash manually.
- Decision: add RA8P1-side AHT20 diagnostics for I2C ACK/read/calibration/CRC failures, display the diagnostic text in the UI, and publish the offline diagnostic text toward the ESP32. Rebuild and flash RA8P1 with J-Link, then read RAM strings back from the running target. Prepare and compile the ESP32 MQTT status extension that forwards `aht20.diag`, but do not claim it is live until the user flashes ESP32.
- Impact on future work: the confirmed board-side root cause is `write addr nack` (`AHT20_DIAG_WRITE_ADDR_NACK`), meaning RA8P1 does not receive an ACK from the AHT20 at address-write time. Treat the remaining temperature-trigger blocker as physical AHT20 wiring/power/module/address response on Bus S1, not as a Hermes/cloud/parser problem. To expose this exact diagnostic in cloud/web JSON, ask the user to manually flash the newly compiled ESP32 binary first.

2026-06-05
- Context: continuing the full-Hermes cloud takeover goal after the hardware-side AHT20 diagnostic was proven locally.
- User feedback or failure: live Hermes could answer from raw device state and could deploy/ACK rules, but its API response did not yet expose a structured `device_diagnostics` object, and the Hermes prompt did not explicitly require respecting known hardware blockers such as AHT20 offline or SG90 power limitations.
- Decision: add cloud-side `_device_diagnostics()` extraction, pass diagnostics into `/agent/hermes/chat` as part of the official Hermes device context, return `device_diagnostics` in chat/deploy responses, and update the Hermes prompt with hardware-reality rules. Deploy the patch to `/home/admin/embedded-agent`, restart `embedded-agent-cloud`, and verify `planner_mode=hermes_official_primary`, preview chat returns `device_diagnostics.blocking_conditions`, and a live temperature-rule request reaches `ack_received=true` with device state advancing to the same request ID and `last_execution.state=ARMED`.
- Impact on future work: public web/API now has a stronger Hermes takeover baseline: Hermes receives structured device diagnostics and must describe AHT20 offline as a trigger blocker instead of implying execution. Cloud `aht20.diag` remains `null` until the user manually flashes the prepared ESP32 binary that forwards RA8P1's `write addr nack` diagnostic into MQTT status/telemetry.

2026-06-05
- Context: the user clarified a forward-looking hardware requirement for the I2C subsystem, beyond the current AHT20-only real-board baseline.
- User feedback or failure: it is not sufficient for the system to keep treating the sensor bus as "AHT20 or offline"; the user wants the system to recognize arbitrary device types present on the I2C bus rather than mislabeling every module as AHT20.
- Decision: record "identify arbitrary I2C device types on the bus" as an explicit future requirement. Treat the current implementation as AHT20-specific, not as a generic I2C discovery layer, and plan future work around bus scan + device signature probing + per-device driver registration + cloud manifest/GBrain synchronization.
- Impact on future work: do not present the current `Bus S1` path as generic hot-pluggable I2C support. Future architecture and Hermes knowledge updates should distinguish between "AHT20 fixed driver" and the requested "arbitrary I2C device identification" capability.

2026-06-06
- Context: the user asked for the next concrete milestone after Hermes takeover to include real web debugging, stricter execution-stage semantics, and the first burnable generic-I2C foundation on the actual `D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link` board baseline.
- User feedback or failure: the public runtime still showed only `hardware_list=[AHT20 offline]` with `aht20.diag=write addr nack`, so Hermes could not yet see generic Bus S1 inventory online. The public SPA was also not the same source tree as `D:\Embedded-agent\cloud\web`: the live bundle uses `localStorage['ra8p1-api-token']`, while the local older page still used `ra8p1cloud_api_token`. J-Link flashing from this machine remained blocked at tool/connection level, so firmware compile could be verified but real reflash could not be completed in this session.
- Decision: keep the electrical path stable and avoid an FSP IIC rewrite; instead, add a minimal shared software-I2C module (`src/i2c_bus_s1.[ch]`) that preserves the current pins/bit-bang behavior while enabling bus probe/scan/simple identification, refactor `aht20.c` onto that shared layer, publish `i2c:bus=s1;diag=...;count=...;devices=...` lines over the existing RA8P1->ESP32 UART link, and patch the ESP32 bridge source to (1) parse and forward structured `i2c` state, and (2) send board-side natural-language HTTP requests directly to `/agent/hermes/chat` instead of the older `/agent/program/interpret/deploy` URL. On the cloud side, add canonical `delivery_stage` / `delivery_stage_label` fields plus `device_diagnostics.i2c` and `hardware_capabilities`, and update the local web/design docs to surface stage + I2C state.
- Impact on future work: the compile-verified firmware artifact is now `D:\Renesas-Workspace\RA8P1_Viewing_Screen_ESP32_Link\Debug\RA8P1_Viewing_Screen_ESP32_Link.srec` (built 2026-06-06), and the cloud regression test `python -m pytest cloud\tests\test_action_plan.py` passed after the Hermes/I2C changes. However, none of the new generic-I2C reporting is live on `ra8p1cloud.com` until two hardware steps happen: RA8P1 must be flashed with the new `.srec`, and the ESP32 bridge sketch must be rebuilt/flashed from `esp32-s3-uart-link-arduino\esp32_s3_uart_link\esp32_s3_uart_link.ino`. When the public site still shows only `AHT20 offline` with no `i2c` object, treat that as "new bridge not flashed yet", not as "Hermes ignored the new diagnostics model".

2026-06-06
- Context: after the code-side Hermes/I2C changes were in place, this session retried both a real browser-side natural-language interaction on `https://ra8p1cloud.com/chat` and a local J-Link flash from the current Windows machine.
- User feedback or failure: the live chat page accepted input but surfaced `登录已过期`, `下发失败`, and `错误: missing or invalid API token`, so the current browser session could not exercise a successful public deploy path. In parallel, `JLink.exe -NoGui 1 -ExitOnError 1 -AutoConnect 1 -Device R7KA8P1KF_CPU0 -If SWD -Speed 4000 -CommandFile ...` failed immediately with `Connecting to J-Link via USB...FAILED: Failed to open DLL`, and the machine currently did not enumerate any obvious J-Link / Renesas / ESP32 device through `Win32_PnPEntity`.
- Decision: treat the web blocker for this session as an auth/session problem in the live SPA rather than a Hermes-planning defect, and treat the flash blocker as a host-side debugger/USB availability problem rather than a firmware build problem. Preserve the compiled artifacts and require either a restored browser login/session or a direct deployment path, plus a restored J-Link/USB connection, before claiming live board verification.
- Impact on future work: if a future browser test again says `missing or invalid API token`, debug that as a front-end auth/session state issue first; do not conflate it with Hermes, MQTT, ACK, or board execution. If `JLink.exe` still reports `Failed to open DLL`, first verify that the J-Link probe/driver is visible to Windows before retrying flash scripts, because the current blocker happens before target connect or ELF download begins.

2026-06-06
- Context: the live public web flow was retried again, this time using the real login UI and then comparing the browser-visible result against a direct authenticated call to `/api/agent/hermes/chat`.
- User feedback or failure: a user-provided API token (redacted from project history) returned `401 missing or invalid API token` on the live site, while the currently active public token still accepted `/api/agent/runtime/status` and `/api/agent/hermes/chat`. After logging in through the real `/login` view with the accepted token, the browser chat no longer hit 401, but the visible chat bubble still degraded to old-style `降级兜底 · 置信度 90% / answered · Agent 解析` rendering instead of showing the rich Hermes `assistant_message`. Direct API comparison proved Hermes itself was fine: `/api/agent/hermes/chat` returned a full natural-language answer with `assistant_message`, `status=answered`, and explicit `AHT20 offline: write addr nack` hardware blocking context.
- Decision: classify the current public chat-page issue as a live frontend drift bug, not a Hermes backend bug. The active bundle `assets/ChatView-CP2VQTvJ.js` still uses the older message store/rendering model (`xiyue.chat.v1`, `降级兜底`, legacy payload-summary rendering), so the browser is not faithfully surfacing current Hermes response fields even when the API call succeeds.
- Impact on future work: when the public page shows `降级兜底` but a direct `/api/agent/hermes/chat` call returns a correct `assistant_message`, fix/deploy the live SPA before touching Hermes prompt logic. Also treat `ra8p1cloud.com` token validity as environment-specific: the currently accepted browser/API token is not the same as the redacted user-provided token.

2026-06-06
- Context: after the user manually reflashed both RA8P1 and ESP32 and reconnected the board, live verification resumed from the public web UI and live device state instead of only local builds.
- User feedback or failure: the Windows host still did not enumerate a J-Link probe, but it now exposed a generic `USB 串行设备 (COM15)`, which is consistent with at least one USB-side board/bridge path being alive. More importantly, the public cloud state changed materially: `last_status.payload.i2c` and `last_telemetry.payload.i2c` now exist with `bus=s1`, `diag=ok`, `count=0`, `devices=[]`, while `hardware_list` still reports `AHT20@0x38 offline` with `diag=write addr nack`.
- Decision: treat the generic-I2C firmware/bridge baseline as live on the public system, because the previously absent `i2c` object is now present in both status and telemetry. Use a hardware-independent natural-language command for end-to-end validation: from the real `/chat` page, send `请在屏幕显示 CODEX-I2C-VERIFY。`; verify that the page reports `已下发并收到 ACK`, then confirm by API that `last_request_id`, `last_event.request_id`, and `last_deploy_ack.request_id` all equal the web-generated request id `web_260606_696253_wx2xpu`, with `last_intent_type=screen_text` and `script_state=ACKED`.
- Impact on future work: the live baseline is now stronger than before in two ways: (1) public web natural language -> Hermes -> MQTT -> device ACK is proven again with a real browser-originated request, and (2) the new I2C reporting path is live end-to-end. The remaining blocker is narrower and more physical: Bus S1 itself is healthy (`diag=ok`) but no device is ACKing, so `count=0` and the synthetic `AHT20 offline` entry remains the only hardware item. Also note one remaining cloud/UI drift: public `/api/agent/hermes/chat` still returns `device_diagnostics` without explicit `i2c` / `hardware_capabilities` keys even though `latest_device_state.last_status.payload` already contains them.

2026-06-06
- Context: the user temporarily shifted priority from Hermes/UI work to ESP32 network robustness, with only the ESP32 connected over USB and a new local Wi-Fi environment available (`<wifi-ssid>` / `<wifi-password>`).
- User feedback or failure: the current ESP32 bridge sketch still hard-coded a single SSID (`<wifi-ssid-2>`), which made the board effectively tied to one hotspot instead of being portable across known 2.4 GHz locations.
- Decision: keep the Wi-Fi change minimal and local to the existing Arduino bridge. Replace the single `WiFi.begin(ssid, password)` path with a small built-in profile list plus scan-based selection: the ESP32 now scans nearby APs, matches against known SSIDs, and connects to the strongest visible known network; if none are visible, it falls back to the first configured profile. Seed the first two profiles as `<wifi-ssid>` and `<wifi-ssid-2>`, compile with `arduino-cli --fqbn esp32:esp32:esp32s3`, and flash directly to the live USB-connected ESP32 on `COM10`.
- Impact on future work: the current baseline now supports "multiple known Wi-Fi networks" without introducing BLE provisioning or a heavier settings UI yet. This is intentionally not "connect to arbitrary Wi-Fi"; future work should add persisted profile management and a board-side Wi-Fi settings screen, rather than re-hardcoding more SSIDs into the sketch. After the 2026-06-06 flash, the device again reported `wifi=connected` and `mqtt=connected` through the cloud state, which is sufficient evidence that the standalone ESP32 still boots and rejoins the existing bridge backend after the multi-WiFi change.

2026-06-06
- Context: the user then connected ESP32 back to the RA8P1 board and asked for a visible on-screen Wi-Fi block that shows not only `connected` but also the actual SSID once ESP32 is online.
- User feedback or failure: the existing RA8P1 home screen only had a compact link strip (`ESP32 / WIFI / MQTT`) and the UART protocol only exposed `wifi:connected/disconnected`, so the board had no way to show the Wi-Fi name even though the ESP32 itself knew it.
- Decision: keep the protocol extension minimal. Add a dedicated `WIFI` panel to the RA8P1 home page, add a `g_wifi_name_text` UI field plus `app_ui_set_wifi_name()`, extend the ESP32->RA8P1 UART protocol with `wifi-ssid:<ssid-or-->`, and update the RA8 parser to consume that line without changing the older `wifi:` / `mqtt:` status lines. Rebuild both firmwares, flash RA8P1 successfully over onboard J-Link, and confirm from live RAM that the new UI variables are present and active.
- Impact on future work: this split matters operationally. With only the RA8P1 reflashed, the board can already show the new Wi-Fi panel and it currently reports `WIFI status = connected` but `SSID = "-"`, which proves the screen/UI side is live while the attached ESP32 is still running an older bridge build that does not emit `wifi-ssid:` yet. To complete the feature end to end, the ESP32 must be reflashed again from its direct USB serial port; when that port is absent and only the board's J-Link CDC is exposed, do not expect the SSID text to appear on-screen yet.

2026-06-06
- Context: the public webpage and cloud backend were rebuilt around a server-resident Hermes bridge without requiring hardware.
- User feedback or failure: local-backend wording, browser API Token login, simulated device data, device-first navigation, and AHT20-first modeling did not match the intended product.
- Decision: run FastAPI and the official Hermes API Server as persistent cloud services; use Argon2 users, HttpOnly/Secure cookies, CSRF, roles, lockout, server-side chat history, and per-user Hermes conversations. Replace the public page with Hermes chat, real server knowledge, account management, and an I2C signal-channel model rooted at SDA/SCL. Keep hardware deployment disabled in the public web milestone.
- Impact on future work: web backend processing belongs on the cloud server. Do not reintroduce browser API tokens, fake telemetry, or sensor-first hierarchy. Add future hardware types beneath their physical/logical signal channels, and expose hardware control only after the server/web bridge remains stable.

2026-06-06
- Context: the first account-based web UI still auto-entered an existing session and treated all Hermes messages as one long conversation.
- User feedback or failure: opening the site must show an account chooser; the account page needs switching; chat should follow the Gemini web pattern with recent conversations, new chat, left/right messages, and a persistent bottom composer.
- Decision: remember usernames only, show valid sessions as an explicit continue choice, require password verification when selecting another account, and persist independent server-side conversations with separate Hermes conversation identifiers.
- Impact on future work: never auto-bypass the account entry screen on root load, never store passwords in the browser, and never collapse all user prompts into one global Hermes conversation.

2026-06-06
- Context: the first multi-conversation UI still exposed internal project/runtime names, lacked conversation deletion, and had stale-request races while switching chats.
- User feedback or failure: requested deletable conversations, direct account-chip navigation, removal of server-knowledge navigation, safer password spacing, stable chat switching, URL credential protection, and a completely new public identity.
- Decision: adopt the neutral Vela identity, remove internal names and explanatory login copy, add owner-scoped conversation deletion, cancel and sequence message requests, cache each conversation independently, and strip query strings at both browser and nginx layers.
- Impact on future work: public UI must remain product-neutral; never accept credentials from URL parameters, never log query strings, and protect asynchronous view switching from stale responses.

2026-06-06
- Context: conversation deletion still used the browser's native confirmation dialog, which dimmed and locked the entire page.
- User feedback or failure: requested Gemini-style sidebar actions and a white light theme across the interaction surface.
- Decision: replace native confirmation with a non-modal three-dot sidebar menu, add pin and inline rename, add search and sidebar collapse, and anchor the account entry at the sidebar bottom.
- Impact on future work: destructive conversation actions must stay contextual and non-blocking; avoid browser-native confirm/prompt UI in the public application.

2026-06-06
- Context: the account entry needed a more vivid, animated identity without weakening the cloud-only deployment model.
- User feedback or failure: requested a more polished 3D login experience inspired by GSAP projects, while requiring the final site to remain fully usable with the local development computer offline.
- Decision: vendor the compressed GSAP runtime with the cloud static assets, build the scene from lightweight CSS perspective layers and a capped canvas ambience, and provide mobile, low-power, data-saver, and reduced-motion fallbacks.
- Impact on future work: public UI dependencies must be self-hosted with the server deployment; animation libraries, fonts, images, or build services must never become runtime dependencies on a local computer or third-party CDN.

2026-06-06
- Context: the new 3D login scene looked correct but stuttered when the pointer moved through the lower-left animation area.
- User feedback or failure: left-side animation felt unsmooth and repeatedly blocked or snapped when moving downward.
- Decision: remove competing GSAP writes to the same transform property, stop full-screen canvas from repainting continuously, reduce particle count, throttle pointer-driven depth updates through `requestAnimationFrame`, and deploy the `vela-depth-2` static bundle.
- Impact on future work: avoid combining idle tweens and pointer tweens on the same transform axis; for public login motion, prefer event-driven or finite animation over perpetual full-screen repaint loops.

2026-06-06
- Context: after the stutter fix, the login scene no longer had enough visible motion.
- User feedback or failure: requested a galaxy-style rotating scene where the central icon is subtle and planets orbit around it.
- Decision: replace the large card-like logo object with a faint galaxy core, four CSS-driven tilted orbit rings, and five small planets; keep pointer parallax only on the overall scene and deploy the `vela-galaxy-1` static bundle.
- Impact on future work: when adding login-page motion, make the orbiting objects the visual focus and keep the product mark understated; use CSS keyframe orbit motion for continuous ambience rather than JS-driven perpetual repaint loops.

2026-06-06
- Context: the first galaxy scene still visually flattened planets because the planet nodes inherited the orbit ring's 3D/ellipse transform.
- User feedback or failure: planets should look circular or point-like, the center should be a planet rather than a large logo, and orbit colors should feel more like a space/planet system.
- Decision: split each orbit into a colored `orbit-track` and an independent round planet node, keep the track's ellipse perspective off the planet itself, replace the center mark with a textured round main planet carrying only a small low-opacity product mark, and deploy the `vela-galaxy-2` static bundle.
- Impact on future work: preserve round celestial bodies by separating visual orbit perspective from planet rendering; if an orbit is tilted or squashed, the planet must remain a camera-facing circular billboard.

2026-06-06
- Context: the galaxy login still showed clipped edge planets, unnecessary coordinate labels, and an unattractive brown main planet.
- User feedback or failure: framed planets were still cut in half, `VELA FIELD`-style labels were unnecessary, and the central planet color needed to be replaced.
- Decision: remove `contain: paint` from orbit containers so orbiting planets can overflow cleanly, delete all scene coordinate labels, and recolor the main planet to a cooler blue-green planetary gradient with softer light bands; deploy the `vela-galaxy-3` static bundle.
- Impact on future work: never clip orbiting celestial bodies at container edges; keep the login galaxy free of technical labels unless the user explicitly asks for telemetry-style annotation.

2026-06-06
- Context: the login galaxy still read as a copper-like reflective planet rather than the darker meteor-rain tone the user wanted.
- User feedback or failure: requested the palette and motion to reference a black-and-white falling-star image, with orbiting planets or meteor/downfall animation.
- Decision: add a real-width left-stage `auth-atmosphere` backdrop, introduce `meteor-backdrop` and eight CSS-only `meteor-fall` streaks, switch planets to white/ice-blue/cyan-gray gradients, and keep the right login card in the light theme; deploy the `vela-meteor-1` static bundle.
- Impact on future work: for this login page, prefer cool monochrome/cyan celestial palettes and falling-star ambience over warm copper/orange planets; ensure the left animation stage has real layout width before relying on background layers.

2026-06-06
- Context: after several galaxy/meteor experiments, the user asked to return to the earlier white 3D card login scene shown in their screenshot.
- User feedback or failure: the desired rollback target was the pre-galaxy `vela-depth-2` version with the white slab object and subtle orbit lines.
- Decision: restore `/home/admin/embedded-agent/cloud/web` and `/var/www/cloudbridge` from `vela-web-before-galaxy-20260606-192942.tar.gz`, keep a rollback backup of the current meteor version, and sync the local `D:\Embedded-agent\cloud\web` copy to the same `vela-depth-2` files.
- Impact on future work: treat `vela-depth-2` as the preferred login visual baseline unless the user explicitly asks to re-enter galaxy/meteor exploration; avoid redeploying the later `vela-galaxy-*` or `vela-meteor-*` bundles from local stale files.

2026-06-06
- Context: after returning to the white 3D card login scene, the object still sat too low and felt slightly too large.
- User feedback or failure: requested moving the icon/object toward the center and allowing a modest size reduction.
- Decision: create `vela-depth-3` by shrinking the white slab object, moving it up toward the visual center, and reducing/raising the center mark while keeping the depth-2 visual language.
- Impact on future work: preserve the white 3D slab baseline, but keep the slab comfortably centered in the left stage and avoid letting the bottom edge dominate or clip in desktop view.

2026-06-06
- Context: after the public web/cloud milestone, the next objective became connecting the web chat window back to real hardware control while the RA8P1/ESP32 boards were not connected for immediate flashing.
- User feedback or failure: the user wants natural-language custom control such as "when temperature reaches 30C, make the servo move back and forth", but code should be prepared offline first and burned later.
- Decision: keep arbitrary code downlink blocked; expose web-chat hardware control through a guarded `rule_program.v1` path only when `WEB_HARDWARE_CONTROL_ENABLED=true` and the user role is allowed. The web route now prefers deterministic safe parsing for supported AHT20->SG90 grammar, then hands off to the existing ProgramGraph/MQTT path.
- Impact on future work: deploy the cloud/web changes first with hardware control still disabled, then enable the env flag only after MQTT credentials, device id, ESP32 bridge firmware, RA8P1 firmware, AHT20, and SG90 wiring are ready for real ACK/DONE validation.

2026-06-07
- Context: the guarded web-chat hardware-control code was deployed to the Aliyun server for cloud-only testing while the hardware remained unavailable.
- User feedback or failure: the user clarified that the final connection must not depend on the local development computer; testing must prove the cloud server is the runtime bridge.
- Decision: back up the server to `/home/admin/backups/web-hardware-test-before-20260607-075556.tar.gz`, deploy the guarded web/backend files, keep `WEB_HARDWARE_CONTROL_ENABLED=false`, and fix dry-run delivery semantics so `MQTT_ENABLED=false` reports `planned` rather than falsely reporting `published`.
- Impact on future work: current public cloud baseline contains the web hardware-control entry point but it is safely disabled; when hardware is connected, enable the env flag on the cloud server and validate real `ACK/DONE` through MQTT/device state, not through any local relay.

2026-06-07
- Context: the user clarified that the long-term goal is an independent network hardware-control platform for arbitrary users, not only the current RA8P1 demo.
- User feedback or failure: the current AHT20-first natural-language control path needed to start evolving toward hardware catalogs, capability registration, and platform-level natural-language capability mapping.
- Decision: deploy a cloud-only compatibility layer first: add `cloud.app.hardware_catalog`, expose `/hardware/catalog` and `/devices/{device_id}/diagnostics`, map `AHT20.temp -> env.temperature` and `SG90.servo_set -> motor.servo.angle`, while keeping `rule_program.v1` wire payload compatible with the current ESP32/RA8P1 firmware.
- Impact on future work: platform capability work can proceed on the cloud without immediate reflashing; native board/bridge v2 reporting (`buses/devices/capabilities`) should wait until the user powers the hardware and manually handles flashing.

2026-06-07
- Context: the board was powered on after the cloud platform capability layer was deployed.
- User feedback or failure: the next step should proceed, but manual flashing is required if firmware changes are needed.
- Decision: validate the live link first with a safe `screen_text` deploy; cloud publish and same-request `deploy_ack` succeeded for `direct_260607_screen_1780830201`, proving Cloud -> MQTT -> ESP32 -> RA8P1 -> ACK. AHT20 remains offline with `write addr nack` and Bus S1 scan `count=0`. Prepare ESP32-only `cloudbridge.v2` MQTT payload reporting (`buses/devices/capabilities`) while leaving RA8P1 unchanged; compile passes, but do not flash because no direct ESP32 USB serial port is currently visible.
- Impact on future work: burn only the ESP32 bridge when its direct COM port is available, then verify `/devices/ra8p1_demo_001/diagnostics` shows native `source=device_payload_v2`; temperature-triggered servo tests remain blocked until AHT20 wiring/power/address is fixed.

2026-06-07
- Context: the user confirmed AHT20 physical wiring and asked to inspect code because the screen still showed no temperature/humidity.
- User feedback or failure: the live symptom remained `write addr nack`, but code inspection found two likely board-side issues: software I2C Bus S1 used an extremely short CPU-loop delay, and AHT20 calibration checking used `0x18` instead of the documented bit-3 `0x08` mask.
- Decision: patch RA8P1 Bus S1 to use microsecond-level delay, wait for SCL release, expose `scl stuck`, and update AHT20 to check calibration bit 3 and read measurement data as a 7-byte frame after the trigger delay. Build with `make -C Debug all` passed and produced a new `Debug/RA8P1_Viewing_Screen_ESP32_Link.srec`.
- Impact on future work: when wiring is believed correct but AHT20 still reports address NACK, test this RA8P1 timing/protocol firmware before moving to cloud, ESP32, or UI debugging. ESP32 does not need reflashing for this fix.

2026-06-07
- Context: after flashing the stricter SCL-wait build, the screen changed from `write addr nack` to `scl stuck`.
- User feedback or failure: this proved the new diagnostic path was live, but it also showed that Bus S1's SCL line was not reading high when released as an input with internal pull-up.
- Decision: adapt the RA8P1 software-I2C implementation to the current hardware by driving SCL actively high/low, matching the earlier AHT20 bit-bang behavior, while keeping SDA as an input/pull-up release line for ACK/data. Rebuild with `make -C Debug src/i2c_bus_s1.o && make -C Debug all -j4`.
- Impact on future work: for this board revision, do not assume Bus S1 has strong external SCL pull-up. If generic multi-I2C support is pursued later, add an explicit bus electrical-profile setting instead of forcing pure open-drain SCL for every device.

2026-06-07
- Context: after P511/P512 were enabled in e2 studio/FSP and generated into `ra_gen/pin_data.c`, the real screen still showed `scl stuck`, and Wi-Fi/SSID disappeared from the RA8P1 screen.
- User feedback or failure: the FSP pin step was correct, but the RA8P1 software-I2C code was still treating SCL readback as a hard stuck condition even though SCL is now actively driven high. Cloud diagnostics showed ESP32 was actually `wifi=connected`, `mqtt=connected`, and `uart=online`, so the screen Wi-Fi issue was stale UART status display rather than real ESP32 disconnection.
- Decision: remove the SCL readback gate from Bus S1 when using active-high SCL, rebuild RA8P1 successfully, and update the ESP32 bridge so it periodically republishes `wifi:`, `wifi-ssid:`, and `mqtt:` lines to RA8P1 while UART is online.
- Impact on future work: after RA8P1 reflashing, expect AHT20 diagnostics to move past `scl stuck` into either real readings or address/data-level diagnostics. To make the on-screen Wi-Fi name robust after RA8P1 resets, flash the updated ESP32 bridge too.

2026-06-07
- Context: the user reported that the screen no longer shows temperature/humidity and asked to trace the current AHT20 data path.
- User feedback or failure: code and cloud state agree that the screen is not missing a cloud return path; RA8P1 reads AHT20 locally, updates the `SENSOR` panel only on successful samples, and otherwise displays the latest AHT20 diagnostic.
- Decision: confirm the active chain as `AHT20 -> RA8P1 Bus S1 P511/P512 -> aht20.c -> hal_entry.c -> app_ui.c + RA8P1 UART -> ESP32 -> MQTT/cloud`; cloud state still reports `aht20.diag=write addr nack`, `i2c.diag=ok`, and `i2c.count=0`.
- Impact on future work: treat missing on-screen temperature/humidity as an AHT20 ACK/device-detection blocker first, or as "latest RA8P1 firmware not flashed" if the screen still shows the older `scl stuck` diagnostic; do not debug webpage/cloud before confirming the Bus S1 ACK path.

2026-06-07
- Context: after the user confirmed the screen now shows `write addr nack`, another live firmware test was run with J-Link available.
- User feedback or failure: active-high SDA transmit on Bus S1 plus an AHT20 legacy GPIO bit-bang fallback both compiled and flashed successfully, but live RAM still read `g_aht20_diag=3`, `g_i2c_bus_s1_diag=3`, and the UI measurement text remained `write addr nack`.
- Decision: keep the diagnostic conclusion at address-phase no-ACK on P511/P512; the failure persisted across both the shared Bus S1 implementation and the legacy GPIO fallback, so it is unlikely to be only the newer generic-I2C software layer.
- Impact on future work: next checks should be physical/electrical first: AHT20 VCC/GND, SDA/SCL order, actual RA8P1 pad/header mapping for P511/P512, pull-ups/module health, or trying a known-good I2C module on the same Bus S1 before further cloud or planner changes.

2026-06-08
- Context: the user suspected the persistent AHT20 `write addr nack` could be tied to the previous P511/P512 channel and asked to move AHT20 to a different test pin pair.
- User feedback or failure: P511/P512 remained unable to produce an address ACK despite shared Bus S1 and legacy GPIO fallback tests.
- Decision: move AHT20 Bus S1 test wiring to `P510=SDA` and `P513=SCL`, update firmware pin definitions, wiring docs, and local cloud signal/diagnostic text accordingly.
- Impact on future work: when testing this build, wire AHT20 to P510/P513 and treat any remaining `write addr nack` as evidence against the old P511/P512 pad/header path rather than against the cloud/web chain.

2026-06-08
- Context: after reviewing the real PA8P1 front-side photo and RA8P1 hardware docs, the user reported that `P510` is not visible on the extension-board silk screen.
- User feedback or failure: choosing a pin only from MCU/FSP availability can select a pad that is not practically reachable on the user's board.
- Decision: replace the AHT20 Bus S1 test pair with visible unused extension pins `P309=SDA` and `P306=SCL` on bottom connector `JP4`.
- Impact on future work: hardware pin remaps must first pass the real board silk-screen/accessibility check, then code-usage and alternate-function checks.

2026-06-08
- Context: the user flashed/tested the `P309=SDA` and `P306=SCL` AHT20 remap on the real PA8P1 board.
- User feedback or failure: AHT20 successfully produced temperature/humidity readings and the RA8P1 screen displayed them.
- Decision: treat `P309/P306` as the validated AHT20 Bus S1 wiring baseline for this board.
- Impact on future work: do not return AHT20 to `P511/P512` unless explicitly retesting that physical channel; cloud/web diagnostics should describe `P309/P306` as the known-good signal channel.

2026-06-08
- Context: the user asked to clean redundant files across the active RA8P1 workspace and `D:\Embedded-agent`.
- User feedback or failure: temporary J-Link scripts/logs, Playwright screenshots, Arduino build intermediates, runtime scratch files, nested reference-repo git history, and duplicated upstream zip archives had accumulated and obscured the real source baseline.
- Decision: remove only clearly transient or rebuildable artifacts, preserve source/docs/current firmware images/reference working trees, and add ignore rules for recurring scratch patterns.
- Impact on future work: do not store ad hoc probe scripts, screenshots, runtime bundles, or ESP32 build intermediates in the working tree; keep validated source and hardware docs separate from disposable validation output.

2026-06-08
- Context: after AHT20 read successfully on `P309/P306`, the user asked to open the public web-to-real-hardware control entrance.
- User feedback or failure: the cloud `.env` still lacked the web hardware-control flags, and the live server diagnostics still mentioned the obsolete `P511/P512` wiring.
- Decision: set `WEB_HARDWARE_CONTROL_ENABLED=true`, `WEB_HARDWARE_CONTROL_ROLES=admin`, and `WEB_HARDWARE_WAIT_FOR_ACK=true` on the Aliyun cloud service; restart `embedded-agent-cloud`; sync live diagnostic/signal text to `P309/P306`.
- Impact on future work: the public web hardware-control gate is open for admin users, but current cloud device state still shows `uart=waiting` and stale AHT20 offline telemetry, so real command testing should first confirm RA8P1 -> ESP32 -> MQTT uplink freshness.

2026-06-08
- Context: the user clarified that AHT20 is an observational I2C child device while SG90 is an independent physical actuator, and requested optimization before later testing.
- User feedback or failure: the existing web path mostly supported temperature-triggered `rule_program.v1`, which over-coupled AHT20 observation and SG90 actuation.
- Decision: add web intent routing for `observation_query.v1`, `manual_action.v1`, and `rule_program.v1`; add ESP32 forwarding for `payload.manual_action`; add RA8P1 `manual:start` immediate SG90 sequence execution.
- Impact on future work: webpage natural-language commands can now stay decoupled: AHT20 queries do not actuate, SG90 manual actions do not require temperature, and temperature-triggered servo automation remains a rule-layer composition.

2026-06-08
- Context: the user asked to replace the web signal-channel page's static placeholder with a shape that connects to real hardware data.
- User feedback or failure: the page was still rendering a static-looking I2C card and `/web/context` passed `signal_topology({})`, so live MQTT device state could not appear in the signal map.
- Decision: make `/web/context` read `device_state_store.snapshot()`, upgrade `signal_topology.v2` to expose AHT20 readings on `i2c:s1` plus SG90 on `pwm:servo.1`, and deploy the updated frontend to the actual Nginx root `/var/www/cloudbridge`.
- Impact on future work: when RA8P1/ESP32 publishes status or telemetry, the web signal page should show live AHT20 temperature/humidity, diagnostics, last-seen time, and the independent SG90 PWM actuator channel instead of a static endpoint placeholder.

2026-06-08
- Context: the user noticed that a short follow-up like `现在呢` triggered a temperature-to-servo hardware rule in the web chat.
- User feedback or failure: the pre-LLM hardware route was too aggressive and could bypass conversation-level semantic reasoning, causing ambiguous follow-ups to become physical commands.
- Decision: make the web hardware fast path conservative: observations and manual SG90 actions remain explicit routes, but `rule_program` deploys only when the current utterance itself contains sensor, condition, actuator, and action terms; remove LLM fallback from the pre-router deploy path.
- Impact on future work: ambiguous or contextual follow-ups should flow through the normal conversation/LLM path and must not deploy actuator rules unless the user gives an explicit hardware command in that message.

2026-06-08
- Context: the user rejected relying on a pre-LLM hardware router and clarified that the goal is an independent cloud platform, not local execution.
- User feedback or failure: physical-control decisions should come from model understanding of the current utterance plus conversation context, then be converted into safe structured tool calls.
- Decision: add a cloud `web_hardware_agent` DeepSeek-compatible decision layer for `/web/chat`; when web hardware control is enabled, the cloud model returns `none`, `observation_query`, `manual_action`, or `rule_program`, and the server executes only validated schemas. Legacy regex routes remain internal helpers, not the primary web decision path.
- Impact on future work: natural language hardware control now follows LLM-first tool calling on the server: model reasons over context, server enforces signal-channel/device white lists and parameter bounds, and no local desktop process is required for platform operation.

2026-06-08
- Context: the user reported that webpage AHT20 replies could differ from the RA8P1 screen temperature/humidity display.
- User feedback or failure: the cloud chat response preferred `last_telemetry` even when `last_status` carried a newer AHT20 sample, while the screen showed the immediate RA8P1 reading.
- Decision: make cloud AHT20 observation choose the newest MQTT sample between `status` and `telemetry` by timestamp, expose the selected source/time in web replies, and make the signal-channel page use the same observation selector.
- Impact on future work: when comparing screen and web values, first check the returned `source` and `timestamp`; stale-source drift should be fixed in cloud selection before changing RA8P1 or ESP32 sampling code.

2026-06-08
- Context: the user asked to fix several public web bugs around conversation navigation, repeated empty conversations, stale signal status, and model switching.
- User feedback or failure: clicking conversations from the signal page did not switch back to chat, repeated "new chat" clicks created duplicate empty sessions, stale device data still appeared online, and the UI lacked a visible model configuration page.
- Decision: add a model configuration API/UI, make web chat use effective runtime model settings, synchronize I2C/AHT20/PWM status with device freshness, reuse existing empty conversations, and remove redundant signal-channel text from AHT20 chat replies.
- Impact on future work: web UX bugs should be fixed across backend state and frontend navigation together; model switching must affect server-side Agent settings, not only render a decorative selector.

2026-06-08
- Context: the user clarified that model configuration must be user-extensible, not limited to built-in Hermes/DeepSeek/fallback rows.
- User feedback or failure: the platform should allow configuring providers such as Qwen, Xiaomi/MiMo, Gemini, or any compatible API model from the web UI.
- Decision: add custom OpenAI-compatible model profiles with server-side API key storage, provider/base-url/model fields, admin-only create/delete/switch APIs, and make selected profiles feed the effective backend model settings.
- Impact on future work: prefer provider-profile abstractions over hard-coded model rows; only expose masked key status to the browser and keep full API keys server-side.

2026-06-08
- Context: the user accepted making SG90/PWM status wording more precise after asking how the platform knows AHT20 and SG90 are connected.
- User feedback or failure: PWM servos do not provide protocol-level ACK or presence detection, so showing SG90 as simply "online" can mislead users into thinking physical connection was verified.
- Decision: make PWM channel status show `channel_ready` while the overall device is fresh, keep SG90 endpoint as `configured` or `execution_feedback`, and add metadata that physical detection is not supported for no-feedback PWM.
- Impact on future work: only buses/devices with real discovery or telemetry should use "online" as physical presence proof; open-loop actuators should use channel/readiness/execution-feedback language.

2026-06-08
- Context: the signal-channel page showed AHT20/PWM offline while chat still returned current AHT20 readings, and AHT20 replies showed `上报时间：未知`.
- User feedback or failure: ESP32 MQTT status/telemetry payloads may omit a top-level `timestamp`, which made `device_state.last_seen` become `None` even though fresh AHT20 values were present.
- Decision: when MQTT messages lack `timestamp`, use the cloud receive time as the stored message timestamp/last_seen, keep structured observation source/time for diagnostics, and remove the source/time sentence from natural-language chat replies.
- Impact on future work: freshness should be based on cloud receive time when device-origin timestamps are absent; do not surface low-level source/timestamp diagnostics in normal chat unless explicitly requested.

2026-06-08
- Context: the user asked to fix the RA8P1/ESP32 `request_id` truncation risk before continuing real deploy tests.
- User feedback or failure: the old 31-character validation limit could make the board execute while cloud ACK matching failed when generated IDs were longer.
- Decision: widen RA8P1 UI/protocol ID buffers and ESP32 request/script buffers to 64-byte slots, then update validation scripts and docs to allow IDs up to 63 characters.
- Impact on future work: validation tools may use longer IDs, but any move beyond 63 characters must first enlarge UART line buffers and retest `ack` plus `exec` lines end-to-end.

2026-06-08
- Context: after `P309=SDA` and `P306=SCL` were validated as the only active AHT20 Bus S1 chain, the user asked to remove redundant paths.
- User feedback or failure: keeping a hidden legacy bit-bang fallback could mask Bus S1 failures and complicate webpage-to-real-hardware diagnostics.
- Decision: remove the AHT20-local legacy bit-bang path and route all AHT20 reads/writes through `i2c_bus_s1` at address `0x38`.
- Impact on future work: if AHT20 regresses, diagnose the validated `P309/P306` Bus S1 path directly; do not assume an alternate legacy fallback is still present.

2026-06-08
- Context: the user asked how to move the ESP32 to a new site when the current firmware had hard-coded WiFi credentials, with phone hotspot and PC WiFi available.
- User feedback or failure: cloud-only WiFi switching cannot work while ESP32 is offline because no MQTT/cloud channel exists.
- Decision: implement a browser Web Serial provisioning path: web page `设备配网` sends JSON-lines WiFi commands over USB, ESP32 saves SSID/password in Preferences/NVS, and saved credentials take priority over built-in fallback networks.
- Impact on future work: treat USB serial provisioning as the first-field setup path; add SoftAP/BLE only as optional fallback, and never require WiFi passwords to pass through the cloud server.

2026-06-08
- Context: after adding Web Serial WiFi provisioning, the user asked to remove the old `<wifi-ssid-2>` hotspot from device defaults.
- User feedback or failure: hard-coded personal/site WiFi credentials should not remain as an implicit fallback once field provisioning exists.
- Decision: remove `<wifi-ssid-2>` from the ESP32 built-in `kWifiProfiles` list and update the ESP32 bridge README so only `<wifi-ssid>` remains as a compiled fallback.
- Impact on future work: use the web `设备配网` flow for site-specific WiFi; do not add private venue SSIDs back into firmware defaults unless explicitly requested.

2026-06-08
- Context: the user attempted to compile the ESP32 bridge after the Web Serial provisioning change.
- User feedback or failure: Arduino build failed because `handle_usb_provisioning_line()` called `publish_status_lines_to_uart()` before that function had a visible declaration.
- Decision: add an explicit forward declaration for `publish_status_lines_to_uart()` alongside the other ESP32 bridge helper prototypes.
- Impact on future work: when adding functions inside the anonymous namespace, keep forward declarations complete because Arduino's generated prototypes do not reliably cover this project layout.

2026-06-08
- Context: the browser Web Serial provisioning page failed to open COM10 with `Failed to open serial port`.
- User feedback or failure: Arduino IDE's `serial-monitor` process was still running after ESP32 work and held the COM port exclusively.
- Decision: stop the `serial-monitor` process, verify COM10 can be opened by the OS, and harden the webpage so a failed `SerialPort.open()` resets stale port state and shows a Chinese hint to close Arduino serial tools before retrying.
- Impact on future work: for Web Serial failures, check for Arduino Serial Monitor or other terminal tools first; port-open failures are usually host-side ownership, not MQTT/cloud or ESP32 firmware behavior.

2026-06-09
- Context: the user asked for account-level reuse of previously configured WiFi credentials and questioned whether a 2.4GHz hint was redundant.
- User feedback or failure: the provisioning page needed a selectable WiFi history, but WiFi passwords should not become cloud-side data by default.
- Decision: add a browser-local, username-scoped saved WiFi panel under `设备配网`; save profiles only after ESP32 returns `wifi.set.result ok`, and add a short 2.4GHz-only hint for ESP32-S3/phone hotspot setup.
- Impact on future work: keep WiFi password reuse local to the browser unless the user explicitly accepts server-side secret storage; pure 5GHz hotspot failures should be diagnosed as provisioning input/environment, not ESP32 firmware failure.

2026-06-09
- Context: the user identified that production devices cannot share the fixed `ra8p1_demo_001` identity and proposed a UID/MAC based multi-device path.
- User feedback or failure: the platform needed to distinguish multiple identical RA8P1/ESP32 boards, subscribe to all device status topics, and make chat/signal/control target the currently selected device.
- Decision: add a cloud device registry with generated `device_id` and `device_secret`, subscribe MQTT state to `cloudbridge/+/status|telemetry|event|log`, add a web device selector, make web chat/control resolve selected `device_id`, make RA8P1 publish `R_BSP_UniqueIdGet()` over UART, and make ESP32 register `ra8p1_uid + esp32_mac + esp32_chip_id` then save the returned cloud identity in NVS.
- Impact on future work: keep `ra8p1_demo_001` only as a backward-compatible bootstrap/default device; production tests should verify new boards appear in the web device selector and that MQTT/control topics use the selected generated `device_id`.

2026-06-09
- Context: after reflashing both chips, the web UI still showed `读取设备中`/old `ra8p1_demo_001`, while MQTT telemetry included the RA8P1 UID and AHT20 data.
- User feedback or failure: cloud registration had created a generated device, but live MQTT messages still published to `cloudbridge/ra8p1_demo_001/...` with `identity.registered=false`, so the signal-channel page could not bind the readings to the production `device_id`.
- Decision: harden ESP32 registration by refreshing ESP32 MAC/chip identity before registration, accepting any 2xx registration response, parsing both top-level and nested returned `device_id`, rejecting the demo id as a saved registered identity, disconnecting old MQTT on identity change, and printing the registered id over USB for field diagnosis.
- Impact on future work: if a device keeps reporting under `ra8p1_demo_001`, sniff MQTT first; if `ra8p1_uid` is present but `registered=false`, reflash/check the ESP32 registration path rather than changing RA8P1 I2C/AHT20 code.

2026-06-09
- Context: the user reported that the RA8P1 screen temperature changes while the web/chat values stay frozen at the old AHT20 sample.
- User feedback or failure: the cloud had no non-retained fresh MQTT messages, but chat still answered from stale cached AHT20 data; service restarts could also re-ingest retained MQTT messages as if they were new.
- Decision: make observation replies require fresh `device_state.last_seen` in addition to `AHT20.status=online`, report stale cache age explicitly, ignore MQTT retained messages in the subscriber, and clear stale retained `cloudbridge/...` status/telemetry/event topics.
- Impact on future work: screen-local AHT20 changes prove only the RA8P1 I2C path; cloud freshness must be verified by non-retained MQTT or device-state `last_seen`, and retained MQTT must never be treated as live telemetry.

2026-06-09
- Context: after the ESP32 switched to generated `device_id`, it connected to Mosquitto as `ra8p1_e1b82bb84da7` but the web still could not receive live data.
- User feedback or failure: Mosquitto ACL still allowed only `cloudbridge/ra8p1_demo_001/#`, so new-device publish/subscribe paths were blocked even though cloud code and ESP32 firmware had moved to wildcard topics.
- Decision: update `/etc/mosquitto/acl` to `topic readwrite cloudbridge/#`, fix ACL/password file ownership, restart Mosquitto and the cloud subscriber, and add a frontend fallback that auto-selects the single online registered device when the legacy demo device is offline.
- Impact on future work: multi-device support requires broker ACL, subscriber wildcard, web selector, and firmware topic switch to be changed together; if MQTT connects but no messages arrive, inspect ACL before changing firmware.

2026-06-13
- Context: the LLM-first web hardware agent parsed a temperature-conditioned SG90 rule from chat.
- User feedback or failure: the model output `program.loop_interval_ms=0`, which violated the backend schema minimum and made the request fail before MQTT downlink.
- Decision: normalize `loop_interval_ms` at the Pydantic model boundary so missing, invalid, or zero values fall back to `1000ms`, clamp valid values to `100..60000ms`, and reinforce the web hardware-agent prompt.
- Impact on future work: do not rely only on prompt wording for numeric safety; LLM-produced control schemas need backend repair or rejection at the shared model layer.

2026-06-13
- Context: the user asked for a temperature-triggered SG90 sweep where speed decreases uniformly across three repeated sweeps.
- User feedback or failure: Hermes correctly chose a temperature rule, but the generated program reused a fixed `duration_ms`, so the reply and downlink did not preserve the speed-decrease requirement.
- Decision: teach the web hardware agent, Hermes/DeepSeek rule prompts, and deterministic rule parser that decreasing speed must be encoded as progressively larger SG90 `duration_ms` values; add a backend repair pass that converts fixed-duration deceleration requests to 300/350/400ms style sequences before deploy.
- Impact on future work: semantic details such as speed profiles must be validated against the structured payload, not just mentioned in assistant text.

2026-06-13
- Context: the user questioned whether the cloud knowledge base truly contains AHT20/SG90 data and used `AG90` while discussing the servo.
- User feedback or failure: device naming, aliases, and common typos can break hardware routing if they only live in prompts instead of schema-level normalization.
- Decision: normalize `AG90`, `servo`, and `SG90-servo` style aliases to `SG90` in web/manual and rule-program schema validation.
- Impact on future work: every new hardware type should define canonical id, aliases, signal channel, capabilities, payload schema, and validation rules before being exposed to the LLM path.

2026-06-14
- Context: the user rejected a hardware-control path that appeared to solve language requests mainly through fixed routing and repair rules instead of model reasoning and active knowledge/tool use.
- User feedback or failure: the previous web hardware agent was a one-shot prompt-to-JSON call; it did not expose live device inspection, capability discovery, project knowledge, or public-document research as model-selectable tools. Its repeat validator also incorrectly removed the final action even when no center-return action existed, and the schema did not normalize `AHT20 + env.temperature` to the wire id `AHT20.temp`.
- Decision: replace the one-shot path with a multi-round DeepSeek-compatible native tool-calling loop. Expose device inspection, capability discovery, local knowledge search, public web search, guarded public-source/PDF reading, candidate validation, and final decision submission. Keep semantic validation as an execution gate, normalize canonical capability ids at the model boundary, count complete sweep pairs correctly, and require a final 90-degree return only when the user explicitly requests a 90-degree center baseline.
- Impact on future work: models should decide which information tools to call and revise candidates from validation feedback; deterministic code should provide schemas, protocol normalization, safety bounds, and proof checks, not silently invent or rewrite user intent. New hardware support should add capability/data contracts and knowledge sources rather than adding natural-language routing branches.

2026-06-14
- Context: the LVGL-UI-replace visual design was migrated onto the current real-hardware firmware baseline.
- User feedback or failure: the replacement UI contained fixed online states, sample sensor values, fake WiFi choices, and other fields that were not connected to the current RA8P1/ESP32 data path.
- Decision: keep the current hardware, UART, MQTT, device-registration, AHT20, touch, and SG90 implementation; migrate only the three-page visual structure. Show a field only when it has a driver, protocol, or configuration source, and update frequent values in place instead of rebuilding the page.
- Impact on future work: UI additions must identify their authoritative source before being displayed. Unknown values stay hidden, and open-loop actuators use channel/execution wording rather than physical-online claims.

2026-06-16
- Context: the board/ESP32/web status model was being unified around standard ports and samples, while the live cloud service still consumed legacy `aht20/i2c/hardware_list` fields.
- User feedback or failure: required the agent to inspect the real server code before changing it, keep web/frontend/backend synchronized, and confirm whether reflashing both chips was necessary.
- Decision: make the cloud backend prefer `ports` and `samples` from device `status/telemetry`, keep legacy fields as compatibility fallback, and treat `RA8P1 + ESP32` reflashing as required for the full unified-state chain while preserving current web compatibility during migration.
- Impact on future work: when live state disagrees across screen, ESP32, and web, check whether the device has been reflashed onto the `ports/samples` firmware first; server/web consumers should not add new hardware rules against legacy-only fields.

2026-06-16
- Context: the user reflashed both RA8P1 and ESP32 and powered the hardware back on for live validation of the unified-state pipeline.
- User feedback or failure: the default public `ra8p1_demo_001` device remained empty, so successful bring-up could be mistaken for a web/backend failure unless the real registered device id was confirmed.
- Decision: verify the live MQTT and cloud API path against the self-registered device `ra8p1_e1b82bb84da7`, confirm `status.ports` and `telemetry.samples` arrive end-to-end, and preserve the web auto-switch behavior that prefers the single online registered device over the offline demo device.
- Impact on future work: after reflashing, first check which generated `device_id` is actually online before debugging cloud state; acceptance for this phase requires `i2c.s1/i2c.s2/pwm.0/uart.bridge` in `ports` and AHT20 samples in `telemetry`.

2026-06-17
- Context: the user tightened the product definition for plug-and-play and explicitly rejected hand-wavy answers unsupported by hardware facts.
- User feedback or failure: first-version plug-and-play must hide GPIO/I2C details from novice users, prefer module/capability language, allow auto-detect when possible, require web confirmation when not possible, and avoid pretending that low-cost I2C or GPIO/PWM modules have stronger identity/detection than the hardware really provides.
- Decision: define V1 as a controlled plug-and-play model, document it in `docs/即插即用模块识别与激活规则_V1.md`, and extend the board-to-ESP32 unified status with `activation`, `module_class`, `model_state`, `binding_source`, and `device_key` so later web/backend work can distinguish hardware fact, capability class, and user-confirmed binding without inventing unsupported certainty.
- Impact on future work: do not market or code this as “fully automatic hardware identity.” `GPIO/PWM` still need user confirmation unless dedicated detect/feedback hardware is added, and class-only I2C probes must not unlock full module capabilities until a real driver/sampler exists.

2026-06-18
- Context: after reflashing and power-up, the user asked for live verification that board, backend, and webpage were actually consistent rather than assumed consistent.
- User feedback or failure: the raw public `/api/devices/{id}/state` payload for `ra8p1_e1b82bb84da7` already contained the new plug-and-play fields in `ports`, but the deployed backend diagnostics and live web asset still reflected the older consumption layer because the final server restart / static-asset replacement step could not complete while SSH port 22 to `<cloud-server-ip>` timed out.
- Decision: verify hardware truth first from public API and MQTT, patch the cloud backend/frontend source to consume `activation`, `module_class`, `model_state`, `binding_source`, and `device_key`, and treat server SSH recovery as the remaining blocker before the live site can become fully consistent.
- Impact on future work: if live web output again lags behind raw device state, distinguish “device already reports new fields” from “cloud process/static asset has not been redeployed” before touching RA8P1 or ESP32 firmware; the remaining live-step commands are just backend restart and `/var/www/cloudbridge/assets/app.js` replacement once SSH is reachable again.

2026-06-18
- Context: SSH connectivity recovered later the same day, allowing the pending live deployment to finish.
- User feedback or failure: the first restart attempt accidentally copied the older server-side `cloud/web/app.js` back onto the live asset, proving that server source drift and live static drift are separate failure modes.
- Decision: re-upload the local `D:\Embedded-agent\cloud\web\app.js` containing the new plug-and-play labels, copy that exact file into `/var/www/cloudbridge/assets/app.js`, restart `embedded-agent-cloud`, and re-verify through the public diagnostics API that backend normalization and live asset now both expose `activation`, `module_class`, `model_state`, `binding_source`, and `device_key`.
- Impact on future work: when updating the public web UI, always treat `/home/admin/embedded-agent/cloud/web/app.js` and `/var/www/cloudbridge/assets/app.js` as two different deployment targets; verify both, otherwise a correct backend can still look “old” in the browser.

2026-06-18
- Context: plug-and-play V1 moved from pure display of board-reported `ports` into the first real user-confirmation loop on the cloud/web side.
- User feedback or failure: the system must not pretend that a user-confirmed module model is the same thing as hardware auto-detection; web, backend, and later Agent actions need one synchronized confirmation source without overwriting raw board facts.
- Decision: add a dedicated cloud-side `module_bindings` store keyed by `device_id + port_id + device_key`, merge that layer into `/web/context` and the web hardware-agent context as additive `user_binding` metadata, and expose only a small in-card confirmation entry instead of rewriting the page.
- Impact on future work: keep `reported_*` hardware facts and `user_binding` configuration separate; future GPIO/PWM/manual-confirm channels must reuse the same split instead of collapsing user choice back into fake auto-identification.

2026-06-18
- Context: the user asked to embed the `D:\Renesas-Workspace\Viewing_Screen` UI into this real hardware workspace without carrying over fake WiFi lists, mock sensors, or fake clock data.
- User feedback or failure: a straight copy of `Viewing_Screen` would have violated the product requirement because it contained static SSIDs, mock AHT20 behavior, and no real ESP32-driven time sync.
- Decision: transplant only the `Viewing_Screen` page structure into `src/app_ui.c`, keep all displayed fields tied to current RA8P1/ESP32 runtime state, add an ESP32-driven `wifi:scan / wifi:connect` UART path for screen WiFi selection, and add one-shot ESP32 NTP sync plus RA8P1 local clock ticking for the top-right time.
- Impact on future work: future UI ports in this workspace must treat mock/demo values as non-migratable by default; every visible field needs an identified live source or it should stay hidden.

2026-06-19
- Context: the user chose `PCA9548A` as the fastest real route to keep `AHT20` and add `BH1750` on the single exposed `I2C-1 / P309+P306` chain.
- User feedback or failure: the product definition does not allow faking this as a second physical `I2C-2`; one standard port may hang multiple same-channel modules, and board/ESP32/web state must stay fact-based.
- Decision: make `i2c_bus_s1` mux-aware, add `BH1750 -> env.light.lux`, keep `i2c.s2` reserved, and represent the shared bus as `i2c.s1` with `9548A-MUX` plus aggregated capabilities instead of inventing a fake second hardware port.
- Impact on future work: when cloud/web consumption is extended for more mux children or same-class duplicates, build on the existing `i2c.s1 + samples` model and add explicit child identity there; do not remap mux children into fake physical ports.

2026-06-19
- Context: after the first `PCA9548A + BH1750` bring-up, the user rejected any screen behavior that looked like a fixed hand-made `BH1750` page instead of plug-and-play.
- User feedback or failure: plug-and-play means “show what is actually inserted”; if one standard port currently carries multiple modules, the screen must display multiple dynamic module entries rather than a single hard-coded hardware page or a fake extra physical port.
- Decision: drive the screen hardware list from the same unified `platform_ports + telemetry.samples` state used by ESP32/web consumption, add dynamic runtime items for mux child modules such as `AHT20` and `BH1750`, and keep module-class wording (`温湿度模块`, `光照模块`) separate from the physical-port truth (`i2c.s1`).
- Impact on future work: any new I2C/GPIO/PWM module UI must be generated from authoritative runtime state or user-confirmed binding metadata, not from fixed pages; a single standard port may fan out to multiple visible modules, but that must never be represented as invented extra physical ports.

2026-06-21
- Context: self-check after a local code update touched the UI path, GPT config header, and headless build workflow.
- User feedback or failure: the new UI had regressed several runtime-fed fields into hard-coded or no-op behavior (`device_id`, clock, WiFi scan/connect), and the local `r_gpt_cfg.h` plus `build_headless.sh` GPT stub no longer matched the FSP driver expectations.
- Decision: restore the full generated GPT config header, stop the headless build script from overwriting it with a minimal stub, add toolchain auto-detect plus explicit `ARM_GCC_BIN` override, and keep the UI WiFi/device/time fields bound to live RA8P1/ESP32 data instead of fixed placeholder lists.
- Impact on future work: do not collapse generated FSP config headers into one-line stubs for convenience, and treat screen-side WiFi/device/time data as live state that must round-trip through the existing UART/API setters rather than local demo placeholders.

2026-06-21
- Context: a later self-check targeted the real plug-and-play list, the WiFi picker, and the dashboard clock after `PCA9548A + AHT20 + BH1750` and the shared PWM channel were already wired on the board.
- User feedback or failure: the screen still looked partly static: inserted mux child modules were not re-listed at runtime, the WiFi sheet showed only the current/known SSID instead of nearby visible networks, and the dashboard clock stayed frozen unless a fresh UART time packet arrived.
- Decision: rebuild the inserted-hardware list from live `device_registry/platform_ports` state whenever the platform refreshes or the hardware page opens, make the ESP32 WiFi scan publish all visible SSIDs while marking `connected/saved/visible`, add a local LVGL timer so the RA8P1 clock continues ticking between sync packets, and surface the shared `PWM-0` channel as `SG90 舵机 / 有源蜂鸣器` with both `motor.servo.angle` and `buzzer.active` capabilities.
- Impact on future work: any screen element that reflects hardware presence, nearby WiFi, or wall-clock time must keep a live local model instead of assuming periodic external pushes; when one physical channel serves multiple logical functions, expose that through capability metadata rather than inventing a fake second port.

2026-06-21
- Context: real-board follow-up after the new UI was flashed exposed a mismatch between the fixed port cards and the actual runtime layout, plus a concern that the ESP32 bridge might be running too hot after power-up.
- User feedback or failure: the inserted-hardware list could show `BH1750`, but the bottom card was hard to enter because the list page had scroll disabled; the `PORTS` page also kept `BH1750` merged under `I2C-1` while `I2C-2` stayed visually empty, and the ESP32 bridge loop was spinning without any end-of-loop yield while heartbeat/status/retry timers were comparatively aggressive.
- Decision: re-enable stable vertical scrolling for the hardware list (still without elastic/momentum), present `BH1750` on the `I2C-2` card in the screen-side logical port view, shorten the shared PWM wording so the buzzer remains visible, slow the ESP32 heartbeat/status/retry intervals, and add a small `delay(10)` at the end of the ESP32 `loop()`.
- Impact on future work: avoid hard-disabling scroll on pages whose item count can grow at runtime, and treat a busy ESP32 `loop()` with no yield as a thermal/power risk even when network requests themselves are only periodic.

2026-06-21
- Context: a later real-board touch pass focused on the inserted-hardware page after the bottom sensor cards became visible.
- User feedback or failure: `温湿度传感器` and `光照传感器` looked present but were hard to open, with strong delay and missed taps, because the list was being rebuilt during live sensor refreshes and the scrollable container could steal touch gestures from the cards.
- Decision: stop rebuilding the hardware list inside every `app_ui_refresh_platform_state()` call, switch list-item entry to `LV_EVENT_PRESSED`, enlarge each card's click area, and keep the current five-card hardware page non-scrollable for maximum tap stability on the real panel.
- Impact on future work: any page that depends on live sensor polling should avoid `lv_obj_clean()/recreate` during active touch interaction; prefer explicit refresh on page entry over continuous structural rebuilds unless true dynamic insertion/removal while the page is open is a hard requirement.

2026-06-21
- Context: the next real-board validation showed a subtler touch bug on the same hardware list page even after live rebuilds were removed.
- User feedback or failure: the card order looked visually correct, but taps felt vertically "shifted" because neighboring cards had overlapping extended click areas, so touching the lower card could trigger the upper one.
- Decision: keep pressed-to-open behavior, but shrink each list item's extra click area and increase vertical row spacing so adjacent touch regions no longer overlap.
- Impact on future work: when compensating for imperfect touch accuracy, never grow hit areas past the available inter-card gap on dense portrait lists; otherwise the UI can feel like the data order is wrong even when the model is correct.

2026-06-21
- Context: real-board retest proved that shrinking list hit areas did not fix the sensor-card offset.
- User feedback or failure: the inserted-hardware heading behaved like the temperature/humidity card, the temperature/humidity card behaved like the light card, and the visible light card did not open.
- Decision: remove the obsolete old-UI touch calibration (`28..287 / 56..432` plus `32px` top offset), report the FT6336 native `320x480` coordinates directly, remove list-item extended hit areas, and bind each card to a stable hardware key instead of a positional index.
- Impact on future work: touch calibration must match the current screen coordinate system; do not retain layout-specific offsets after replacing a full-screen UI, and do not diagnose a whole-row hit shift as card spacing before checking the raw-to-screen transform.

2026-06-21
- Context: the public cloud signal page regressed after a remote restart while the real RA8P1/ESP32 device was still publishing live `status/telemetry`.
- User feedback or failure: the browser stayed pinned to offline `ra8p1_demo_001`, a cloud config drift had silently disabled MQTT subscription in `cloud/.env`, and running remote web-auth tests against the live service polluted the persistent device registry with a fake test device id.
- Decision: restore the live MQTT-enabled remote config before restarting the service, make the web device picker prefer the best non-demo device when the saved demo device is offline, and isolate `test_web_auth.py` with per-test temporary `device_registry.sqlite3` paths instead of the runtime registry.
- Impact on future work: when the web page suddenly shows only baseline channels, verify remote `cloud/.env`/MQTT subscriber state before changing board firmware, and never run tests on the server unless every auth/module/device registry path is redirected to temporary files.

2026-06-21
- Context: the live signal-channel page began showing multiple I2C children (`9548A-MUX`, `AHT20`, `BH1750`) under `I2C-1 / i2c.s1` after the mux-aware telemetry path was restored.
- User feedback or failure: the page could be misread as "all devices were merged into one channel" because it showed one physical bus card with several child cards but did not clearly explain the distinction between the shared bus and attached modules.
- Decision: keep the underlying `i2c.s1 + multiple endpoints` topology unchanged, but update the web wording and card grouping to explicitly distinguish `物理总线/通道`, `总线设备`, and `挂载模块`.
- Impact on future work: whenever one physical port fans out to multiple logical modules, the UI must explain the shared-bus relationship directly instead of relying on users to infer it from addresses or protocol names.

2026-06-22
- Context: remote server access and health checks were revalidated after the public cloud host became unreachable from direct SSH and `/health` briefly returned `502`.
- User feedback or failure: the instance had been restarted and the app recovered, but direct SSH from this workstation could still time out intermittently during short bursts of automated checks because `ufw` used `LIMIT IN` on `22/tcp`.
- Decision: confirm `nginx` and `embedded-agent-cloud` were healthy after reboot, keep the generic SSH rate limit for the internet, and insert a higher-priority allow rule for the current trusted workstation IP before the shared `22/tcp` limit rule.
- Impact on future work: when SSH appears flaky while Workbench or one-off logins still succeed, check `ufw status numbered` before blaming `sshd`; serialize remote diagnostics or add a narrow trusted-IP allow rule instead of globally removing SSH throttling.

2026-06-22
- Context: the QQ bot was connected to the cloud service, but the board was offline and the bot still answered with fabricated "stable" temperature, humidity, online, and actuator status summaries.
- User feedback or failure: when there was no live telemetry and `last_seen` was empty, the QQ bot still claimed `ra8p1_demo_001` was connected, reused stale-style numeric readouts, and risked reporting light/temperature data that the server had not actually received.
- Decision: align QQ bot observation replies with the web truth model, add a deterministic server-state path for temperature/humidity/light/status queries, and forbid "current" numeric sensor answers unless the cloud sees fresh live evidence.
- Impact on future work: chat surfaces must not infer "device connected" from a selected/default device id, and any sensor/status answer must be derived from live cloud state or explicitly labeled as unavailable/stale.

2026-06-22
- Context: follow-up validation after adding QQ bot anti-fabrication guards while the real board was powered on.
- User feedback or failure: Web temperature/humidity reads were routed through an unavailable Hermes profile, QQ still queried the demo device, and fresh legacy AHT20 values were rejected because a stale `i2c.s1=not_inserted` port card overrode them.
- Decision: preserve the existing Web UI and device context, route explicit Web observations directly to live state before model dispatch, select the freshest online registered device for QQ, and let valid fresh sensor values outrank stale port metadata.
- Impact on future work: anti-fabrication checks must be validated both offline and online; they may reject stale data, but must never make model availability or stale topology metadata a prerequisite for reading fresh telemetry.

2026-06-22
- Context: the user required real Hermes orchestration instead of accumulating keyword routes, and Web BH1750 reads failed whenever the UI selected a falsely-ready Hermes profile.
- User feedback or failure: `Hermes Official` and `DeepSeek API` had unclear overlapping behavior, Hermes readiness only checked the DeepSeek key, and light was not represented in the shared observation schema.
- Decision: connect the running loopback Hermes Gateway to the cloud service, use Hermes with the DeepSeek key for structured hardware decisions, add `BH1750/env.light.lux` to the shared observation contract, keep DeepSeek Direct as a switchable lower-latency path, and hide the internal template fallback from the user model list.
- Impact on future work: model choices must describe orchestration behavior rather than only the underlying model name; Hermes plans, the server reads or acts, and both Web and QQ must prove the same live observation path after every model-switch change.

2026-06-22
- Context: live Web and QQBot replies had stopped fabricating stale data, but their answers still felt "unintelligent" because one natural-language request such as "看看温湿度和光照的情况" only returned one sensor class.
- User feedback or failure: the user explicitly required a model-first flow that understands natural language, fetches all required fresh hardware data, and then writes one coherent reply; partial rule-style matching was not acceptable.
- Decision: extend `observation_query` from single-device to multi-device/multi-capability reads, add a second-stage model synthesis step after fresh data retrieval, and keep deterministic fallbacks only as a safety net when synthesis fails.
- Impact on future work: chat surfaces must not stop at intent classification or capability matching; for mixed sensor questions, Web and QQ must cover every requested item in one grounded reply without inventing missing values or dropping part of the request.

2026-06-22
- Context: the user rejected Hermes-only structured planning for ordinary read-only chat because malformed JSON and upstream model-balance failures could surface as raw web errors instead of answers.
- User feedback or failure: they explicitly asked to stop depending on structured Hermes handling for read-only Q&A and instead let the model answer from natural language plus uploaded server-side data, without exposing internal 402/502 failures.
- Decision: make the `hermes_official` read-only web path prefer freeform grounded answers from uploaded live data, detect upstream balance/error text as invalid model output, and then fall back to local observation summaries rather than structured-planner errors.
- Impact on future work: do not force informational sensor/status chat through the same structured action-planning path used for hardware execution; read-only UX must degrade to grounded server data before it ever degrades to raw model/provider errors.

2026-06-22
- Context: the user further clarified that even vague follow-up phrases like `现在呢` should be interpreted from conversation context by the language model rather than treated as isolated keyword queries.
- User feedback or failure: after a successful sensor reply, the next short follow-up still hit the old structured-planner/error path because the model call failed and the local fallback had no access to prior intent.
- Decision: move read-only web chat to a DeepSeek-grounded freeform answer path first, and when the model is unavailable, let the local observation fallback reuse the previous user observation request from conversation history for short follow-up phrases.
- Impact on future work: read-only chat must preserve short-horizon conversational context separately from execution planning; ambiguous follow-ups should inherit the last observation intent before the system gives up or surfaces an error.

2026-06-22
- Context: the user explicitly asked to let Hermes take over read-only web conversation instead of relying on DeepSeek-grounded direct calls or structured planner responses.
- User feedback or failure: after the routing change, direct server-side Hermes gateway verification for the same read-only prompt returned raw provider text `Error code: 402 ... Insufficient Balance`, proving the gateway itself was blocked by its upstream model account rather than by the web routing code.
- Decision: keep the web read-only route ready for Hermes-grounded conversation, but treat direct Hermes reply as blocked until the upstream provider behind Hermes is recharged or replaced; preserve local uploaded-data fallback so the UI does not surface raw gateway failures.
- Impact on future work: when the user asks for Hermes to own the conversation, verify the gateway's own upstream provider health first; routing changes alone cannot make Hermes answer if its backing model account is already returning provider-balance errors.

2026-06-22
- Context: the user required QQBot to behave like a Hermes-led natural-language assistant instead of a keyword-based sensor lookup path.
- User feedback or failure: QQBot could answer, but normal observation chat still favored deterministic observation routes or hardware-agent branches before a grounded Hermes synthesis step, so replies felt rigid and did not clearly reflect "Hermes understands first, then reads latest uploaded data".
- Decision: route QQBot control intents through the existing execution planner only when that planner returns a real action, and otherwise prefer a Hermes gateway freeform reply grounded on the server's latest uploaded temperature/humidity/light snapshot plus live device diagnostics.
- Impact on future work: QQBot informational chat should stay Hermes-grounded by default, and any fallback must remain explicitly tied to current server evidence rather than old keyword templates or stale cached values.

2026-06-22
- Context: competition preparation required cleaning both the real hardware workspace and `D:\Embedded-agent`, then rebuilding documentation from actual project capability.
- User feedback or failure: duplicate snapshots, browser/runtime artifacts, old phase plans and third-party source mirrors obscured the real RA8P1 baseline and made competition claims easy to overstate.
- Decision: create checkpoint `1bbfead` and tag `checkpoint-before-competition-cleanup-20260622`, remove recoverable clutter, use this e2 studio workspace as the only hardware source of truth, and position the project as a plug-and-play environmental control terminal with RA8P1 as the local safety core.
- Impact on future work: competition documents must separate implemented functions from planned TinyML/buzzer work, and `D:\Embedded-agent\Hardware-code` must only be refreshed from this workspace through a clean snapshot.

2026-06-22
- Context: Web chat refused SG90 control and the user required Hermes-led temperature, humidity and light automation plus Web/QQBot long- and short-term tasks without breaking the proven execution chain.
- User feedback or failure: the production Web hardware gate was disabled, SG90 was incorrectly treated as something that should appear in I2C scanning, board-side `rule_program` could only hold one temperature rule, and a production mock-device service was continuously publishing fixed 26.5 C / 52% data.
- Decision: keep SG90 on PWM P105 and reuse the proven `manual_action -> MQTT -> ESP32 -> RA8P1` path; add a cloud SQLite task service for independent sensor rules and scheduled reports; make Web and QQBot share the same model-first validated route; enable admin Web control; disable the production mock-device service and set the real device ID as the default.
- Impact on future work: never infer SG90 presence from I2C; persistent multi-sensor rules belong in the cloud task layer until the board protocol intentionally gains multi-rule storage; production model context and triggers must never consume simulated telemetry.

2026-06-22
- Context: the first live Web SG90 command after enabling hardware control failed with `mqtt_script_secret is required when MQTT publishing is enabled`.
- User feedback or failure: the environment cleanup preserved MQTT connectivity but dropped `MQTT_SCRIPT_SECRET`, so model planning succeeded while the guarded publish step correctly refused to send an unsigned action.
- Decision: restore the existing secret from the June 21 server backup, restart the cloud service, and validate a real `right / 60 degrees / once` manual action through request `web_133700742`, which returned `IDLE -> TRIGGERED -> DONE`.
- Impact on future work: treat `MQTT_ENABLED`, broker credentials, `MQTT_SCRIPT_SECRET`, and `DEVICE_ID` as one atomic production configuration set; after any environment cleanup, verify secret presence by length/hash and run one request-scoped signed actuator smoke test.

2026-06-22
- Context: Hermes misclassified an SG90 clock command as a daily report and manual sequences always returned to center.
- User feedback or failure: bare times must trigger a recurrence question; deleting a conversation should remove its nonpersistent tasks; SG90 should hold its last angle unless reset is explicitly requested; device time must include the date for Web comparison.
- Decision: add explicit once/daily clarification, conversation-scoped task cleanup with a long-lived exception, conversation-scoped auto-reset preferences, scheduled SG90 actions, manual final-angle hold, and full ISO date/time in ESP32 UART/MQTT state.
- Impact on future work: never infer task lifetime from a clock alone, never make a task outlive its conversation without explicit durable intent, and treat actuator reset behavior as an explicit user policy rather than a hidden sequence default.

2026-06-23
- Context: a one-time environment report executed in the backend, but the Web conversation did not display the new assistant message until refreshed; the user's follow-up question was then forced through the structured hardware planner.
- User feedback or failure: ordinary natural-language follow-ups without hardware keywords surfaced Hermes malformed-JSON details and the DeepSeek provider's HTTP 402 balance error, making a working scheduled task appear to have failed and exposing that task context was not being reused.
- Decision: preserve recent conversation and latest-task context for create/update/cancel follow-ups, accept safe Python-style structured objects from Hermes, route ordinary chat to a contextual freeform/local fallback instead of raw provider errors, and poll the active Web conversation for scheduler-inserted messages.
- Impact on future work: scheduled execution and message visibility must be tested as separate links; never force generic conversation through an actuator schema, and never expose model-provider failures when the server can answer from task state or uploaded device data.

2026-06-23
- Context: the Web command `今天十点52分的时候，上报温湿度数据` was submitted at 10:51 but the scheduler interpreted it as 10:00 and declared it expired.
- User feedback or failure: mixed Chinese/Arabic time text such as `十点52分` was only partially matched; model prompts also lacked an explicit full local timestamp, while once-only task specs retained only a clock string instead of an absolute calendar datetime.
- Decision: parse mixed Chinese/Arabic hour-minute-second expressions, support today/tomorrow/day-after and explicit calendar dates, store `target_local_iso` plus `Asia/Shanghai`, inject full temporal context into Hermes, and preserve the exact requested report capabilities.
- Impact on future work: all one-time schedules must resolve to and display an absolute zoned datetime before persistence; parser tests must cover mixed numerals and seconds, and scheduled delivery must be verified to write into the originating conversation.

2026-06-23
- Context: immediately after the full-time parser change, `今天十一点零五分` was still resolved as 11:00.
- User feedback or failure: the Chinese-number helper handled `五` and `十五` but silently converted digit-style Chinese sequences with a leading zero, such as `零五` or `〇五`, to zero.
- Decision: parse zero-padded Chinese digit sequences as decimal digits and add the user's exact sentence as a regression test; verify the deployed production code with an isolated end-to-end due task that writes temperature, humidity and light into its originating Web conversation.
- Impact on future work: time-parser acceptance tests must include spoken leading-zero minutes, not only Arabic digits and canonical Chinese tens; parser success alone is insufficient without scheduled delivery verification.
