from __future__ import annotations

from travelmind.agentic.models import EvidenceAssessment, QueryIntent, RoutingDecision
from travelmind.schemas import Evidence, TravelRequest

ASPECT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "admission": ("门票", "票价", "价格", "免费", "预算", "费用"),
    "opening_hours": ("开放", "营业", "周一", "时间", "几点", "闭馆"),
    "booking": ("预约", "免预约", "不用预约", "预订"),
    "route": ("入口", "出口", "交通", "地铁", "路线", "怎么去"),
    "accessibility": ("无障碍", "轮椅", "老人", "父母", "行动不便"),
}

REWRITE_TERMS = {
    "admission": "官方门票 票价 费用",
    "opening_hours": "官方开放时间 闭馆日期",
    "booking": "官方预约规则 是否需要预约",
    "route": "官方入口 出口 交通路线",
    "accessibility": "官方无障碍设施 老年游客",
}


def required_aspects(query: str) -> list[str]:
    return [
        aspect
        for aspect, keywords in ASPECT_KEYWORDS.items()
        if any(keyword in query for keyword in keywords)
    ]


class RuleBasedQueryRouter:
    """Deterministic routing baseline; no claim of learned intent accuracy."""

    def route(self, request: TravelRequest) -> RoutingDecision:
        aspects = required_aspects(request.query)
        temporal = "opening_hours" in aspects
        multi_markers = ("并且", "同时", "希望", "应该", "优先", "带父母")
        is_multi = len(aspects) >= 2 or any(marker in request.query for marker in multi_markers)
        if is_multi:
            intent = QueryIntent.MULTI_CONSTRAINT
        elif temporal:
            intent = QueryIntent.TEMPORAL
        elif aspects:
            intent = QueryIntent.EXACT_FACT
        elif any(word in request.query for word in ("适合", "体验", "文化", "风景")):
            intent = QueryIntent.SEMANTIC
        else:
            intent = QueryIntent.GENERIC
        return RoutingDecision(
            intent=intent,
            retrieval_strategy="hybrid",
            requires_structured_validation=bool(aspects),
            should_decompose=is_multi,
            reason_codes=[f"intent:{intent.value}", *[f"aspect:{item}" for item in aspects]],
        )


class CoverageEvidenceGrader:
    """Check source presence and query-aspect coverage without an LLM."""

    def grade(
        self,
        request: TravelRequest,
        evidence: list[Evidence],
    ) -> EvidenceAssessment:
        aspects = required_aspects(request.query)
        trusted = [
            item for item in evidence if item.source_type in {"official", "structured", "realtime"}
        ]
        evidence_text = " ".join(
            " ".join(
                (
                    item.content,
                    str(item.metadata.get("source_section", "")),
                    " ".join(str(tag) for tag in item.metadata.get("tags", [])),
                )
            )
            for item in trusted
        )
        covered = [
            aspect
            for aspect in aspects
            if any(keyword in evidence_text for keyword in ASPECT_KEYWORDS[aspect])
        ]
        missing = [aspect for aspect in aspects if aspect not in covered]
        coverage = len(covered) / len(aspects) if aspects else float(bool(trusted))
        sufficient = bool(trusted) and not missing
        reason_codes: list[str] = []
        if not evidence:
            reason_codes.append("no_evidence")
        elif not trusted:
            reason_codes.append("no_trusted_evidence")
        if missing:
            reason_codes.extend(f"missing:{aspect}" for aspect in missing)
        if sufficient:
            reason_codes.append("coverage_sufficient")
        return EvidenceAssessment(
            sufficient=sufficient,
            coverage_score=coverage,
            required_aspects=aspects,
            covered_aspects=covered,
            missing_aspects=missing,
            reason_codes=reason_codes,
        )


class MissingAspectQueryRewriter:
    """Expand only missing fact aspects and retain prior queries for traceability."""

    def rewrite(
        self,
        request: TravelRequest,
        previous_queries: list[str],
        assessment: EvidenceAssessment,
        *,
        attempt: int,
    ) -> list[str]:
        del attempt
        expansions = [
            f"{request.query} {REWRITE_TERMS[aspect]}" for aspect in assessment.missing_aspects
        ]
        if not expansions:
            expansions = [f"{request.query} 官方信息 景点规则"]
        return list(dict.fromkeys([*previous_queries, *expansions]))
