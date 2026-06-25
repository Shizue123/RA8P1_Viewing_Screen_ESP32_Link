from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from cloud.app.agent_service.web_hardware_agent import decide_web_hardware_action
from cloud.app.api.web_routes import _web_device_context
from cloud.app.config import Settings
from cloud.app.model_config import effective_model_settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test model-first hardware automation decisions.")
    parser.add_argument("text")
    args = parser.parse_args()

    settings = effective_model_settings(Settings())
    decision = decide_web_hardware_action(
        args.text,
        settings,
        conversation_history=[{"role": "user", "content": args.text}],
        device_context=_web_device_context(settings),
    )
    print(
        json.dumps(
            {
                "provider": settings.llm_provider,
                "action_kind": decision.action_kind,
                "automation_task": decision.automation_task,
                "manual_action": (
                    decision.manual_action.model_dump(mode="json")
                    if decision.manual_action is not None
                    else None
                ),
                "reasoning_summary": decision.reasoning_summary,
                "tool_trace": decision.tool_trace,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
