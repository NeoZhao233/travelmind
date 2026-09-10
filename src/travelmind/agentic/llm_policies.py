from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from travelmind.agentic.llm_provider import LLMOutputError, StructuredLLMProvider
from travelmind.agentic.models import EvidenceAssessment, RoutingDecision
from travelmind.schemas import Evidence, TravelRequest

ROUTER_PROMPT_VERSION = "router-v2-nonthinking"
GRADER_PROMPT_VERSION = "grader-v3-explicit-scope"
REWRITER_PROMPT_VERSION = "rewriter-v1"


class LLMPolicyCall(BaseModel):
    component: str
    prompt_version: str
    success: bool
    model: str | None = None
    latency_ms: float | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    provider_attempts: int = 0
    error_type: str | None = None


class LLMPolicyTelemetry:
    def __init__(self) -> None:
        self.calls: list[LLMPolicyCall] = []

    def success(self, component: str, prompt_version: str, result: Any) -> None:
        self.calls.append(
            LLMPolicyCall(
                component=component,
                prompt_version=prompt_version,
                success=True,
                model=result.model,
                latency_ms=result.latency_ms,
                prompt_tokens=result.usage.prompt_tokens,
                completion_tokens=result.usage.completion_tokens,
                total_tokens=result.usage.total_tokens,
                provider_attempts=result.provider_attempts,
            )
        )

    def failure(
        self,
        component: str,
        prompt_version: str,
        exc: Exception,
        result: Any | None = None,
    ) -> None:
        self.calls.append(
            LLMPolicyCall(
                component=component,
                prompt_version=prompt_version,
                success=False,
                model=result.model if result else None,
                latency_ms=result.latency_ms if result else None,
                prompt_tokens=result.usage.prompt_tokens if result else 0,
                completion_tokens=result.usage.completion_tokens if result else 0,
                total_tokens=result.usage.total_tokens if result else 0,
                provider_attempts=result.provider_attempts if result else 0,
                error_type=type(exc).__name__,
            )
        )


class _RewriteOutput(BaseModel):
    queries: list[str] = Field(min_length=1, max_length=3)


class _BasePolicy:
    def __init__(
        self,
        provider: StructuredLLMProvider,
        telemetry: LLMPolicyTelemetry | None = None,
    ) -> None:
        self.provider = provider
        self.telemetry = telemetry or LLMPolicyTelemetry()

    def _complete(
        self,
        *,
        component: str,
        prompt_version: str,
        system_prompt: str,
        payload: dict[str, Any],
        max_tokens: int,
    ) -> Any:
        try:
            result = self.provider.complete_json(
                system_prompt=system_prompt,
                user_prompt=json.dumps(payload, ensure_ascii=False),
                max_tokens=max_tokens,
            )
            return result
        except Exception as exc:
            self.telemetry.failure(component, prompt_version, exc)
            raise


class LLMQueryRouter(_BasePolicy):
    def route(self, request: TravelRequest) -> RoutingDecision:
        result = self._complete(
            component="query_router",
            prompt_version=ROUTER_PROMPT_VERSION,
            system_prompt=(
                "Return JSON only. Classify the travel query. Required schema: "
                '{"intent":"semantic|exact_fact|temporal|multi_constraint|generic",'
                '"retrieval_strategy":"hybrid","requires_structured_validation":true,'
                '"should_decompose":false,"reason_codes":["short_code"]}. '
                "Do not include hidden reasoning or user secrets."
            ),
            payload={"query": request.query, "constraints": request.constraints.model_dump()},
            max_tokens=220,
        )
        try:
            decision = RoutingDecision.model_validate(result.data)
        except ValidationError as exc:
            error = LLMOutputError("Router JSON failed schema validation")
            self.telemetry.failure("query_router", ROUTER_PROMPT_VERSION, error, result)
            raise error from exc
        self.telemetry.success("query_router", ROUTER_PROMPT_VERSION, result)
        return decision


class LLMEvidenceGrader(_BasePolicy):
    def grade(self, request: TravelRequest, evidence: list[Evidence]) -> EvidenceAssessment:
        evidence_payload = [
            {
                "id": item.id,
                "content": item.content[:1200],
                "source_type": item.source_type,
                "section": item.metadata.get("source_section"),
            }
            for item in evidence[:8]
        ]
        result = self._complete(
            component="evidence_grader",
            prompt_version=GRADER_PROMPT_VERSION,
            system_prompt=(
                "Return JSON only. Judge whether trusted evidence fully supports the travel query. "
                'Required schema: {"sufficient":false,"coverage_score":0.0,'
                '"required_aspects":[],"covered_aspects":[],"missing_aspects":[],'
                '"reason_codes":["short_code"]}. Required aspects must contain only facts the '
                "user explicitly asks for; do not add purchase channels, ticket categories, or "
                "other unstated details. Mark sufficient when the supplied trusted evidence "
                "directly answers every explicitly requested fact. For an open-ended discovery "
                "query, one directly relevant trusted description is sufficient. Be conservative "
                "when the evidence is merely related but does not answer the requested fact."
            ),
            payload={"query": request.query, "evidence": evidence_payload},
            max_tokens=350,
        )
        try:
            assessment = EvidenceAssessment.model_validate(result.data)
        except ValidationError as exc:
            error = LLMOutputError("Grader JSON failed schema validation")
            self.telemetry.failure("evidence_grader", GRADER_PROMPT_VERSION, error, result)
            raise error from exc
        if assessment.sufficient and assessment.missing_aspects:
            error = LLMOutputError("Grader marked missing evidence as sufficient")
            self.telemetry.failure("evidence_grader", GRADER_PROMPT_VERSION, error, result)
            raise error
        if not set(assessment.missing_aspects) <= set(assessment.required_aspects):
            error = LLMOutputError("Grader missing aspects are not required aspects")
            self.telemetry.failure("evidence_grader", GRADER_PROMPT_VERSION, error, result)
            raise error
        self.telemetry.success("evidence_grader", GRADER_PROMPT_VERSION, result)
        return assessment


class LLMQueryRewriter(_BasePolicy):
    def rewrite(
        self,
        request: TravelRequest,
        previous_queries: list[str],
        assessment: EvidenceAssessment,
        *,
        attempt: int,
    ) -> list[str]:
        result = self._complete(
            component="query_rewriter",
            prompt_version=REWRITER_PROMPT_VERSION,
            system_prompt=(
                'Return JSON only as {"queries":["..."]}. Produce at most three concise '
                "Chinese retrieval queries targeting only missing evidence. Do not invent facts."
            ),
            payload={
                "query": request.query,
                "previous_queries": previous_queries[-4:],
                "missing_aspects": assessment.missing_aspects,
                "attempt": attempt,
            },
            max_tokens=240,
        )
        try:
            output = _RewriteOutput.model_validate(result.data)
        except ValidationError as exc:
            error = LLMOutputError("Rewriter JSON failed schema validation")
            self.telemetry.failure("query_rewriter", REWRITER_PROMPT_VERSION, error, result)
            raise error from exc
        clean = [item.strip() for item in output.queries if item.strip()]
        if not clean:
            error = LLMOutputError("Rewriter returned no usable query")
            self.telemetry.failure("query_rewriter", REWRITER_PROMPT_VERSION, error, result)
            raise error
        self.telemetry.success("query_rewriter", REWRITER_PROMPT_VERSION, result)
        return list(dict.fromkeys([*previous_queries, *clean]))[:4]
