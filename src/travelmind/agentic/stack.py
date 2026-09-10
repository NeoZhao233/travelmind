from dataclasses import dataclass

from travelmind.agentic.llm_policies import (
    LLMPolicyTelemetry,
    LLMQueryRouter,
)
from travelmind.agentic.llm_provider import DeepSeekConfig, DeepSeekHTTPProvider
from travelmind.agentic.policies import CoverageEvidenceGrader, MissingAspectQueryRewriter
from travelmind.agentic.protocols import EvidenceGrader, QueryRewriter, QueryRouter


@dataclass(frozen=True)
class AgenticPolicyStack:
    router: QueryRouter
    grader: EvidenceGrader
    rewriter: QueryRewriter
    telemetry: LLMPolicyTelemetry
    profile: str


def build_selected_deepseek_stack(
    *,
    api_key: str,
    model: str = "deepseek-v4-flash",
    timeout_seconds: float = 20,
) -> AgenticPolicyStack:
    """Build the Stage 3E mixed stack; graph fallbacks remain deterministic."""

    telemetry = LLMPolicyTelemetry()
    provider = DeepSeekHTTPProvider(
        DeepSeekConfig(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    )
    return AgenticPolicyStack(
        router=LLMQueryRouter(provider, telemetry),
        grader=CoverageEvidenceGrader(),
        rewriter=MissingAspectQueryRewriter(),
        telemetry=telemetry,
        profile="deepseek-router-v2__deterministic-grader-rewriter-v1",
    )
