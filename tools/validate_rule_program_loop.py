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
        description="Validate the real rule_program SG90 sequence loop through the live cloud Agent."
    )
    parser.add_argument("--host", default="your-cloud-host")
    parser.add_argument("--user", default="admin")
    parser.add_argument("--ssh-key", default=r"D:\Embedded-agent\codex_aliyun_ed25519")
    parser.add_argument("--remote-root", default="/home/admin/embedded-agent")
    parser.add_argument("--device-id", default="ra8p1_demo_001")
    parser.add_argument("--text", default="当温度到35度时，舵机来回旋转两次")
    parser.add_argument("--expected-threshold", type=float, default=35.0)
    parser.add_argument("--wait-seconds", type=float, default=8.0)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--request-id", default="")
    return parser.parse_args()


def default_request_id() -> str:
    return f"rpv_{time.time_ns() // 1_000_000}"


def build_remote_script(
    request_id: str,
    remote_root: str,
    device_id: str,
    text: str,
    expected_threshold: float,
    wait_seconds: float,
) -> str:
    payload = {
        "request_id": request_id,
        "remote_root": remote_root,
        "device_id": device_id,
        "text": text,
        "expected_threshold": expected_threshold,
        "wait_seconds": wait_seconds,
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
            "text": CONFIG["text"],
        }}

        deploy = request_json("POST", "/agent/program/interpret/deploy", body)
        time.sleep(CONFIG["wait_seconds"])
        detail = request_json("GET", f"/deployments/{{CONFIG['request_id']}}")
        state = request_json("GET", f"/devices/{{CONFIG['device_id']}}/state")
        events = request_json("GET", f"/devices/{{CONFIG['device_id']}}/events?limit=16")
        messages = request_json("GET", f"/devices/{{CONFIG['device_id']}}/messages?limit=20")

        last_status = (((state.get("state") or {{}}).get("last_status") or {{}}).get("payload") or {{}})
        last_execution = (last_status.get("last_execution") or {{}})
        last_event = ((state.get("state") or {{}}).get("last_event") or {{}})
        event_payload = last_event.get("payload") or {{}}
        recent_events = events.get("events") or []

        execution_states = [
            ((item.get("message") or {{}}).get("payload") or {{}}).get("state")
            for item in recent_events
            if ((item.get("message") or {{}}).get("type") == "execution_state")
        ]
        observed_states = [state for state in execution_states if state]
        if last_execution.get("state"):
            observed_states.append(last_execution.get("state"))
        if event_payload.get("state"):
            observed_states.append(event_payload.get("state"))

        result = {{
            "request_id": CONFIG["request_id"],
            "deploy_ack_received": deploy.get("ack_received"),
            "graph_trace": deploy.get("graph_trace"),
            "program_source": deploy.get("program_source"),
            "deployment": detail.get("deployment"),
            "device_script_state": last_status.get("script_state"),
            "device_last_request_id": last_status.get("last_request_id"),
            "device_last_script_id": last_status.get("last_script_id"),
            "device_last_intent_type": last_status.get("last_intent_type"),
            "device_temp": ((last_status.get("aht20") or {{}}).get("temp")),
            "device_last_execution": last_execution,
            "last_event": last_event,
            "recent_events": recent_events[:8],
            "recent_messages": (messages.get("messages") or [])[:10],
            "execution_states": execution_states,
            "observed_states": observed_states,
        }}

        checks = []
        checks.append(bool(deploy.get("ack_received")))
        checks.append(last_status.get("last_request_id") == CONFIG["request_id"])
        checks.append(last_status.get("last_intent_type") == "rule_program")
        checks.append(last_event.get("type") == "execution_state")
        checks.append(event_payload.get("action") == "SG90")
        checks.append(last_execution.get("action") == "SG90")
        checks.append(event_payload.get("operator") == ">=")
        checks.append(abs(float(event_payload.get("threshold", 0)) - float(CONFIG["expected_threshold"])) < 0.05)
        checks.append(int(last_execution.get("angle", 0)) == 90)
        checks.append(("TRIGGERED" in observed_states) or (last_execution.get("state") == "DONE"))
        checks.append("DONE" in observed_states)
        checks.append(last_execution.get("state") == "DONE")

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
        text=args.text,
        expected_threshold=args.expected_threshold,
        wait_seconds=args.wait_seconds,
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
            f"last_execution={((result.get('device_last_execution') or {}).get('state'))} "
            f"execution_states={','.join(result.get('execution_states') or [])}"
        )

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
