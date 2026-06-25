from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the final real-hardware delivery baseline: rule_program then threshold_control."
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--host", default="your-cloud-host")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--ssh-key", default=r"D:\Embedded-agent\codex_aliyun_ed25519")
    parser.add_argument("--remote-root", default="/home/admin/embedded-agent")
    parser.add_argument("--device-id", default="ra8p1_demo_001")
    parser.add_argument("--text", default="当温度到25度时，舵机来回旋转两次")
    parser.add_argument("--expected-threshold", type=float, default=25.0)
    parser.add_argument("--rule-wait-seconds", type=float, default=20.0)
    parser.add_argument("--threshold", type=float, default=25.0)
    parser.add_argument("--threshold-wait-seconds", type=float, default=5.0)
    parser.add_argument("--cooldown-seconds", type=float, default=2.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--report-file", default="")
    return parser.parse_args()


def run_json_command(command: list[str], cwd: Path) -> tuple[int, dict]:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=240,
        check=False,
    )

    stdout = completed.stdout.strip()
    if not stdout:
        raise RuntimeError(completed.stderr.strip() or "validation returned empty stdout")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"validation did not return JSON: {exc}\nstdout={stdout}") from exc

    return completed.returncode, payload


def build_common_args(args: argparse.Namespace) -> list[str]:
    return [
        "--host",
        args.host,
        "--user",
        args.user,
        "--ssh-key",
        args.ssh_key,
        "--remote-root",
        args.remote_root,
        "--device-id",
        args.device_id,
    ]


def summarize(result: dict) -> dict:
    last_execution = result.get("device_last_execution") or {}
    return {
        "request_id": result.get("request_id"),
        "ok": bool(result.get("ok")),
        "deploy_ack_received": bool(result.get("deploy_ack_received")),
        "script_state": result.get("device_script_state"),
        "last_request_id": result.get("device_last_request_id"),
        "last_script_id": result.get("device_last_script_id"),
        "last_intent_type": result.get("device_last_intent_type"),
        "execution_state": last_execution.get("state"),
        "execution_reason": last_execution.get("reason"),
        "action": last_execution.get("action"),
        "angle": last_execution.get("angle"),
        "threshold": last_execution.get("threshold"),
        "temp": last_execution.get("temp"),
    }


def detect_stale_runtime(summary: dict) -> bool:
    request_id = summary.get("request_id")
    last_request_id = summary.get("last_request_id")
    if not request_id or not last_request_id:
        return False

    return (
        (summary.get("deploy_ack_received") is False)
        and (request_id != last_request_id)
    )


def main() -> int:
    args = parse_args()
    cwd = Path(__file__).resolve().parent.parent
    common = build_common_args(args)

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    rule_command = [
        args.python,
        str(cwd / "tools" / "validate_rule_program_loop.py"),
        *common,
        "--text",
        args.text,
        "--expected-threshold",
        str(args.expected_threshold),
        "--wait-seconds",
        str(args.rule_wait_seconds),
        "--json",
    ]
    threshold_command = [
        args.python,
        str(cwd / "tools" / "validate_threshold_loop.py"),
        *common,
        "--threshold",
        str(args.threshold),
        "--wait-seconds",
        str(args.threshold_wait_seconds),
        "--json",
    ]

    started_at = int(time.time())
    rule_exit, rule_result = run_json_command(rule_command, cwd)

    if args.cooldown_seconds > 0:
        time.sleep(args.cooldown_seconds)

    threshold_exit, threshold_result = run_json_command(threshold_command, cwd)
    finished_at = int(time.time())

    combined = {
        "started_at": started_at,
        "finished_at": finished_at,
        "device_id": args.device_id,
        "cooldown_seconds": args.cooldown_seconds,
        "rule_program": summarize(rule_result),
        "threshold_control": summarize(threshold_result),
        "rule_program_raw": rule_result,
        "threshold_control_raw": threshold_result,
        "ok": (rule_exit == 0 and threshold_exit == 0 and bool(rule_result.get("ok")) and bool(threshold_result.get("ok"))),
    }

    stale_runtime = detect_stale_runtime(combined["rule_program"]) and detect_stale_runtime(combined["threshold_control"])
    combined["stale_runtime_suspected"] = stale_runtime
    if stale_runtime:
        combined["diagnosis"] = (
            "device still publishes old status/telemetry but did not accept new deploy requests; "
            "check ESP32 bridge runtime, board power state, or reflash/reset before treating this as a cloud regression"
        )

    if args.report_file:
        report_path = Path(args.report_file)
        if not report_path.is_absolute():
            report_path = cwd / report_path
        report_path.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
        combined["report_file"] = str(report_path)

    if args.json:
        print(json.dumps(combined, ensure_ascii=False, indent=2))
    else:
        print(
            "delivery baseline "
            f"{'ok' if combined['ok'] else 'failed'}: "
            f"rule={combined['rule_program']['script_state']} "
            f"threshold={combined['threshold_control']['script_state']} "
            f"rule_req={combined['rule_program']['request_id']} "
            f"threshold_req={combined['threshold_control']['request_id']}"
        )

    return 0 if combined["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
