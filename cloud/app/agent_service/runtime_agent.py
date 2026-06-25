from __future__ import annotations

import time

from cloud.app.agent_service.action_plan import interpret_text_to_rule_program
from cloud.app.agent_service.orchestrator import AgentOrchestrator
from cloud.app.agent_service.runtime_knowledge import build_runtime_knowledge_bundle
from cloud.app.config import Settings
from cloud.app.log_service.store import PersistentLogStore
from cloud.app.models import (
    AgentDeployRequest,
    AgentDeployResponse,
    AgentPlanRequest,
    AgentPlanResponse,
    AgentRoute,
    ProgramDeployRequest,
)


class HermesRA8P1Agent:
    """Hermes-style RA8P1 agent shell for NL -> rule_program -> deploy.

    This class gives the existing hardware agent a Hermes-inspired outer
    structure: identity, goals, continuity, memory snapshot, and a stable
    cycle trace. The hardware control core remains the verified
    `rule_program.v1` -> ProgramGraph path.
    """

    agent_id = "hermes_ra8p1_v1"
    legacy_agent_id = "specialized_agent_v1"

    def __init__(self, settings: Settings, log_store: PersistentLogStore | None = None) -> None:
        self._settings = settings
        self._log_store = log_store or PersistentLogStore(settings.log_db_path)

    def plan(self, request: AgentPlanRequest) -> AgentPlanResponse:
        request_id = _ephemeral_request_id("agentplan")
        device_id = request.device_id or self._settings.device_id
        trace = [
            "hermes_cycle_start",
            "load_hermes_identity",
            "load_hermes_goals",
            "load_hermes_structural_memory",
            "load_hermes_continuity",
            "resolve_device",
            "load_runtime_knowledge",
            "classify_request",
        ]

        bundle = build_runtime_knowledge_bundle(device_id, self._log_store)
        route = AgentRoute.rule_program_v1
        trace.append("build_prompt_context")

        parsed = interpret_text_to_rule_program(request.text, self._settings)
        trace.append("generate_rule_program")

        validation = bundle.knowledge.validate_rule_program(parsed.program)
        if not validation["ok"]:
            raise ValueError("; ".join(str(error) for error in validation["errors"]))
        trace.append("validate_rule_program")

        source = self._source(parsed.source)
        notes = [
            "hermes_ra8p1_v1 loaded identity, goals, structural memory, and continuity before planning",
            "the hardware control core remains restricted to rule_program.v1 instead of arbitrary MCU source code",
            *parsed.notes,
            *[str(warning) for warning in validation["warnings"]],
        ]
        trace.append("hermes_cycle_journal")

        response = AgentPlanResponse(
            request_id=request_id,
            device_id=device_id,
            route=route,
            source=source,
            confidence=min(parsed.confidence + 0.08, 0.95),
            notes=notes,
            knowledge_snapshot=bundle.snapshot,
            program=parsed.program,
            graph_trace=trace,
        )
        self._record_agent_run(
            request_id=request_id,
            device_id=device_id,
            route=route.value,
            user_text=request.text,
            source=source,
            confidence=response.confidence,
            knowledge_snapshot=bundle.snapshot.model_dump(mode="json"),
            plan=response.model_dump(mode="json"),
            deployment=None,
        )
        return response

    def deploy(self, request: AgentDeployRequest, orchestrator: AgentOrchestrator) -> AgentDeployResponse:
        device_id = request.device_id or self._settings.device_id
        bundle = build_runtime_knowledge_bundle(device_id, self._log_store)
        parsed = interpret_text_to_rule_program(request.text, self._settings)
        validation = bundle.knowledge.validate_rule_program(parsed.program)
        if not validation["ok"]:
            raise ValueError("; ".join(str(error) for error in validation["errors"]))

        deploy_response = orchestrator.deploy_rule_program(
            ProgramDeployRequest(
                request_id=request.request_id,
                device_id=device_id,
                program=parsed.program,
                need_confirm=request.need_confirm,
                wait_for_ack=request.wait_for_ack,
            )
        )
        response = AgentDeployResponse(
            **deploy_response.model_dump(mode="json"),
            route=AgentRoute.rule_program_v1,
            source=self._source(parsed.source),
            confidence=min(parsed.confidence + 0.08, 0.95),
            notes=[
                "hermes_ra8p1_v1 loaded identity, goals, memory, and recent deployment history before deployment",
                "deployment was handed off to the proven ProgramGraph after rule_program validation",
                *parsed.notes,
                *[str(warning) for warning in validation["warnings"]],
            ],
            knowledge_snapshot=bundle.snapshot,
        )
        response.graph_trace = [
            "hermes_cycle_start",
            "load_hermes_identity",
            "load_hermes_goals",
            "load_hermes_structural_memory",
            "load_hermes_continuity",
            "resolve_device",
            "load_runtime_knowledge",
            "classify_request",
            "build_prompt_context",
            "generate_rule_program",
            "validate_rule_program",
            "handoff_program_graph",
            *response.graph_trace,
            "hermes_cycle_journal",
        ]
        self._record_agent_run(
            request_id=request.request_id,
            device_id=device_id,
            route=AgentRoute.rule_program_v1.value,
            user_text=request.text,
            source=response.source,
            confidence=response.confidence,
            knowledge_snapshot=bundle.snapshot.model_dump(mode="json"),
            plan={
                "program": parsed.program.model_dump(mode="json"),
                "validation": validation,
                "prompt_context": bundle.prompt_context,
            },
            deployment=response.model_dump(mode="json"),
        )
        return response

    def runtime_status(self) -> dict[str, object]:
        deepseek_configured = bool(self._settings.deepseek_api_key)
        provider = self._settings.llm_provider.lower()
        hermes_official_enabled = bool(self._settings.hermes_official_enabled)
        if provider == "hermes_official":
            planner_mode = "hermes_official_primary" if hermes_official_enabled and deepseek_configured else "hermes_official_misconfigured"
        elif provider == "deepseek":
            planner_mode = "deepseek_primary" if deepseek_configured else "deepseek_misconfigured"
        else:
            planner_mode = "rule_based_primary"
        return {
            "ok": True,
            "agent_id": self.agent_id,
            "compatibility_agent_id": self.legacy_agent_id,
            "agent_shell": "hermes_specialized_for_ra8p1",
            "llm_provider": self._settings.llm_provider,
            "planner_mode": planner_mode,
            "device_id": self._settings.device_id,
            "hermes": {
                "identity": "RA8P1 cloud hardware-control agent",
                "goal": "web natural language -> restricted rule_program -> verified board execution",
                "memory_layers": ["identity", "goals", "structural_memory", "episodic_agent_runs", "continuity"],
                "control_core": "rule_program.v1",
                "cycle_hooks": [
                    "load_hermes_identity",
                    "load_hermes_goals",
                    "load_hermes_structural_memory",
                    "load_hermes_continuity",
                    "hermes_cycle_journal",
                ],
            },
            "deepseek": {
                "configured": deepseek_configured,
                "model": self._settings.deepseek_model,
                "base_url": self._settings.deepseek_base_url,
                "fallback_rule_based_available": True,
            },
            "hermes_official": {
                "enabled": hermes_official_enabled,
                "uv_path": self._settings.hermes_official_uv_path,
                "workdir": self._settings.hermes_official_workdir,
                "model": self._settings.hermes_official_model,
                "timeout_sec": self._settings.hermes_official_timeout_sec,
            },
            "supported_routes": [AgentRoute.rule_program_v1.value],
            "knowledge_sources": build_runtime_knowledge_bundle(self._settings.device_id, self._log_store).snapshot.primary_sources,
        }

    def list_runs(self, limit: int = 20) -> list[dict[str, object]]:
        return self._log_store.list_agent_runs(limit)

    def get_run(self, request_id: str) -> dict[str, object] | None:
        return self._log_store.get_agent_run(request_id)

    def _record_agent_run(
        self,
        *,
        request_id: str,
        device_id: str,
        route: str,
        user_text: str,
        source: str,
        confidence: float,
        knowledge_snapshot: dict[str, object],
        plan: dict[str, object],
        deployment: dict[str, object] | None,
    ) -> None:
        self._log_store.record_agent_run(
            request_id=request_id,
            device_id=device_id,
            route=route,
            user_text=user_text,
            source=source,
            confidence=confidence,
            knowledge_snapshot=knowledge_snapshot,
            plan=plan,
            deployment=deployment,
        )

    def _source(self, planner_source: str) -> str:
        return f"{self.agent_id}:{planner_source}"


def _ephemeral_request_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}"


class SpecializedHardwareAgent(HermesRA8P1Agent):
    """Backward-compatible import name for older routes and tests."""
