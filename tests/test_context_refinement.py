from travelmind.context.models import ContextBudget, ContextItem, ContextKind
from travelmind.context.pipeline import RefinedCoverageContextBuilder
from travelmind.context.refinement import EvidenceRefiner


def _item(
    identity: str,
    content: str,
    *,
    priority: int = 80,
    **metadata: str,
) -> ContextItem:
    return ContextItem(
        item_id=f"evidence:{identity}",
        kind=ContextKind.EVIDENCE,
        content=content,
        priority=priority,
        metadata={"document_id": identity, **metadata},
    )


def test_duplicate_evidence_keeps_authoritative_source_and_merges_provenance() -> None:
    content = "故宫通常周一闭馆，法定节假日除外。"
    items = [
        _item("guide", content, authority="third_party"),
        _item("official", content, authority="official_operator"),
    ]

    result = EvidenceRefiner().refine(items)

    assert [item.item_id for item in result.items] == ["evidence:official"]
    assert result.items[0].metadata["merged_document_ids"] == "guide,official"
    assert result.trace.duplicate_groups[0].suppressed_item_ids == ["evidence:guide"]


def test_conflict_prefers_authority_before_freshness() -> None:
    items = [
        _item(
            "official",
            "官方门票为60元。",
            authority="official_operator",
            observed_at="2026-01-01T00:00:00+08:00",
            fact_key="ticket:high",
            fact_value="60",
        ),
        _item(
            "new-guide",
            "攻略称门票为80元。",
            authority="third_party",
            observed_at="2026-09-01T00:00:00+08:00",
            fact_key="ticket:high",
            fact_value="80",
        ),
    ]

    result = EvidenceRefiner().refine(items)

    assert [item.item_id for item in result.items] == ["evidence:official"]
    assert result.trace.conflicts[0].reason_code == "higher_authority"


def test_equal_precedence_conflict_is_retained_as_unresolved() -> None:
    metadata = {
        "authority": "government",
        "observed_at": "2026-09-01T00:00:00+08:00",
        "fact_key": "closing-time",
    }
    items = [
        _item("one", "闭馆时间为17:00。", fact_value="17:00", **metadata),
        _item("two", "闭馆时间为18:00。", fact_value="18:00", **metadata),
    ]

    result = EvidenceRefiner().refine(items)

    assert len(result.items) == 2
    assert result.trace.conflicts[0].status == "unresolved"
    assert result.trace.conflicts[0].suppressed_item_ids == []


def test_near_duplicate_text_with_different_fact_values_is_not_deduplicated() -> None:
    metadata = {
        "authority": "government",
        "observed_at": "2026-09-01T00:00:00+08:00",
        "fact_key": "closing-time",
    }
    items = [
        _item("one", "景区公告显示闭馆时间为17:00。", fact_value="17:00", **metadata),
        _item("two", "景区公告显示闭馆时间为18:00。", fact_value="18:00", **metadata),
    ]

    result = EvidenceRefiner(duplicate_threshold=0.8).refine(items)

    assert result.trace.duplicate_groups == []
    assert result.trace.conflicts[0].status == "unresolved"
    assert len(result.items) == 2


def test_extractive_compression_preserves_late_numeric_and_exception_facts() -> None:
    item = _item(
        "long",
        "这里介绍公园的历史沿革。这里描述周边风景和建筑。"
        "这里还有许多不影响行程的背景信息。旺季联票全价34元；"
        "除法定节假日外，祈年殿周一关闭。",
        aspects="admission,opening_hours",
    )

    result = EvidenceRefiner(compression_target_tokens=45).refine(
        [item], {"admission", "opening_hours"}
    )

    assert "34元" in result.items[0].content
    assert "周一关闭" in result.items[0].content
    assert (
        result.trace.estimated_evidence_tokens_after < result.trace.estimated_evidence_tokens_before
    )
    assert result.trace.compressed_item_ids == ["evidence:long"]


def test_refinement_trace_never_copies_evidence_content() -> None:
    secret = "用户敏感行程证据"
    result = EvidenceRefiner().refine([_item("secret", secret)])

    assert secret not in result.trace.model_dump_json()


def test_refined_pipeline_composes_with_coverage_and_hard_budget() -> None:
    duplicate = "旺季联票全价34元，周一收费景点关闭。"
    items = [
        ContextItem(
            item_id="system",
            kind=ContextKind.SYSTEM,
            content="仅依据证据回答",
            priority=100,
            mandatory=True,
        ),
        _item("guide", duplicate, authority="third_party", aspects="admission"),
        _item(
            "official",
            duplicate,
            authority="official_operator",
            aspects="admission,opening_hours",
        ),
    ]
    budget = ContextBudget(max_context_tokens=220, reserved_output_tokens=50)

    result = RefinedCoverageContextBuilder(budget).build(items, {"admission", "opening_hours"})

    assert "evidence:official" in result.packed.trace.included_item_ids
    assert "evidence:guide" not in result.packed.trace.included_item_ids
    assert result.packed.trace.estimated_input_tokens_after <= budget.input_token_limit
    assert result.refinement_trace.duplicate_groups
