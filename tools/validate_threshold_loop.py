from __future__ import annotations

import argparse
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the real threshold-control loop through the live cloud Agent."
    )
    parser.add_argument("--host", default="your-cloud-host")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--ssh-key", default=r"D:\Embedded-agent\codex_aliyun_ed25519")
    parser.add_argument("--remote-root", default="/home/admin/embedded-agent")
    parser.add_argument("--device-id", default="ra8p1_demo_001")
    parser.add_argument("--threshold", type=float, default=30.0)
    parser.add_argument("--wait-seconds", type=float, default=5.0)
    parser.add_argument("--expect-triggered", action="store_true", default=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--request-id", default="")
    return parser.parse_args()


def default_request_id() -> str:
    # Keep the request id within the current 63-character UART/status path.
    return f"rtv_{time.time_ns() // 1_000_000}"


def build_remote_script(
    request_id: str,
    remote_root: str,
    device_id: str,
    threshold_value: float,
    wait_seconds: float,
    expect_triggered: bool,
) -> str:
    payload = {
        "request_id": request_id,
        "remote_root": remote_root,
        "device_id": device_id,
        "threshold_value": threshold_value,
        "wait_seconds": wait_seconds,
        "expect_triggered": expect_triggered,
    }

    return textwrap.dedent(
        f"""
        import json
        import sys
        import time
        import urllib.request
        from pathlib import Path

        CONFIG = json.loads({json.dumps(json.dumps(payload))})
        BASE = "http://127.0.0.1:8000"
        TOKEN = Path(CONFIG["remote_root"] + "/runtime/api_token.txt").read_text(encoding="utf-8").strip()
        HEADERS = {{"Accept": "application/json", "X-API-Token": TOKEN}}

        def request_json(method, path, body=None):
            data = None
            headers = dict(HEADERS)
            if body is not None:
                data = json.dumps(body).encode("utf-8")
                headers["Content-Type"] = "application/json"
            req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=90) as response:
                return json.loads(response.read().decode("utf-8"))

        body = {{
            "request_id": CONFIG["request_id"],
            "device_id": CONFIG["device_id"],
            "need_confirm": True,
            "wait_for_ack": True,
            "intent": {{
                "intent_type": "threshold_control",
                "target_devices": ["AHT20", "SG90"],
                "conditions": {{"sensor": "AHT20.temp", "operator": ">", "value": CONFIG["threshold_value"]}},
                "actions": [
                    {{"device": "SG90", "method": "servo_set", "params": {{"angle": 180}}}},
                ],
                "loop_interval_ms": 1000,
            }},
        }}

        deploy = request_json("POST", "/agent/deploy", body)
        time.sleep(CONFIG["wait_seconds"])
        detail = request_json("GET", f"/deployments/{{CONFIG['request_id']}}")
        state = request_json("GET", f"/devices/{{CONFIG['device_id']}}/state")
        events = request_json("GET", f"/devices/{{CONFIG['device_id']}}/events?limit=12")
        messages = request_json("GET", f"/devices/{{CONFIG['device_id']}}/messages?limit=16")

        last_status = (((state.get("state") or {{}}).get("last_status") or {{}}).get("payload") or {{}})
        last_execution = (last_status.get("last_execution") or {{}})
        last_event = ((state.get("state") or {{}}).get("last_event") or {{}})
        event_payload = last_event.get("payload") or {{}}

        result = {{
            "request_id": CONFIG["request_id"],
            "deploy_ack_received": deploy.get("ack_received"),
            "graph_trace": deploy.get("graph_trace"),
            "deployment": detail.get("deployment"),
            "device_script_state": last_status.get("script_state"),
            "device_last_request_id": last_status.get("last_request_id"),
            "device_last_script_id": last_status.get("last_script_id"),
            "device_temp": ((last_status.get("aht20") or {{}}).get("temp")),
            "device_last_execution": last_execution,
            "last_event": last_event,
            "recent_events": (events.get("events") or [])[:6],
            "recent_messages": (messages.get("messages") or [])[:8],
        }}

        checks = []
        checks.append(bool(deploy.get("ack_received")))
        checks.append(last_status.get("last_request_id") == CONFIG["request_id"])

        if CONFIG["expect_triggered"]:
            checks.append(last_status.get("script_state") == "TRIGGERED")
            checks.append(last_event.get("type") == "execution_state")
            checks.append(event_payload.get("state") == "TRIGGERED")
            checks.append(event_payload.get("action") == "SG90")
            checks.append(last_execution.get("state") == "TRIGGERED")
            checks.append(last_execution.get("action") == "SG90")
        else:
            checks.append(last_status.get("script_state") in {{"ARMED", "TRIGGERED"}})
            checks.append(last_event.get("type") in {{None, "execution_state"}})

        if event_payload:
            checks.append(event_payload.get("operator") == ">")
            checks.append(abs(float(event_payload.get("threshold", 0)) - CONFIG["threshold_value"]) < 0.05)
            checks.append(int(event_payload.get("angle", 0)) == 180)
            if event_payload.get("sample"):
                checks.append(isinstance(event_payload.get("temp"), (int, float)))
                checks.append(float(event_payload.get("temp", 0)) > 0)

        result["ok"] = all(checks)
        print(json.dumps(result, ensure_ascii=False))
        sys.exit(0 if result["ok"] else 1)
        """
    ).strip()


def main() -> int:
    args = parse_args()
    ssh_key = Path(args.ssh_key)
    if not ssh_key.exists():
        print(f"ssh key not found: {ssh_key}", file=sys.stderr)
        return 2

    request_id = args.request_id or default_request_id()
    if len(request_id) > 63:
        print("request_id too long for current validation baseline; keep it within 63 chars", file=sys.stderr)
        return 2
    remote_script = build_remote_script(
        request_id=request_id,
        remote_root=args.remote_root,
        device_id=args.device_id,
        threshold_value=args.threshold,
        wait_seconds=args.wait_seconds,
        expect_triggered=args.expect_triggered,
    )

    command = [
        "ssh",
        "-i",
        str(ssh_key),
        f"{args.user}@{args.host}",
        "python3 -",
    ]
    completed = subprocess.run(
        command,
        input=remote_script,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        check=False,
    )

    if completed.returncode not in (0, 1):
        sys.stderr.write(completed.stderr)
        return completed.returncode

    raw = completed.stdout.strip()
    if not raw:
        sys.stderr.write(completed.stderr)
        return 1

    result = json.loads(raw)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(
            "validation "
            f"{'ok' if result.get('ok') else 'failed'}: "
            f"request_id={result.get('request_id')} "
            f"script_state={result.get('device_script_state')} "
            f"device_temp={result.get('device_temp')} "
            f"event_temp={((result.get('last_event') or {}).get('payload') or {}).get('temp')}"
        )

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
