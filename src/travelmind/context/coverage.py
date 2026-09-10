from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from travelmind.domain.models import FactType

_QUERY_TERMS: dict[FactType, tuple[str, ...]] = {
    FactType.OPENING_HOURS: (
        "开放",
        "闭馆",
        "周一",
        "几点",
        "入馆",
        "上午",
        "下午",
    ),
    FactType.ADMISSION: ("门票", "联票", "预算", "免费", "价格", "多少钱"),
    FactType.BOOKING: ("预约", "实名", "余票"),
    FactType.ACCESSIBILITY: ("无障碍", "行动不便", "长辈", "父母", "老人"),
    FactType.ACCESS: ("入口", "出口", "哪个门", "路线", "北侧", "南侧", "离开"),
    FactType.TRANSPORT: ("交通", "地铁", "公交", "打车", "步行"),
    FactType.DESCRIPTION: ("历史", "文化", "建筑", "园林", "湖景", "代表性"),
}

_FILTER_ASPECTS: dict[str, FactType] = {
    "weekday": FactType.OPENING_HOURS,
    "month": FactType.OPENING_HOURS,
    "time": FactType.OPENING_HOURS,
    "time_period": FactType.OPENING_HOURS,
    "scope": FactType.OPENING_HOURS,
    "season": FactType.ADMISSION,
    "ticket_type": FactType.ADMISSION,
    "admission_max_cny": FactType.ADMISSION,
    "low_budget": FactType.ADMISSION,
    "booking_required": FactType.BOOKING,
    "accessibility": FactType.ACCESSIBILITY,
    "route_direction": FactType.ACCESS,
}


def infer_coverage_targets(query: str, hard_filters: dict[str, Any] | None = None) -> set[str]:
    """Infer evidence aspects from runtime inputs without consulting evaluation labels."""

    targets = {
        aspect.value
        for aspect, terms in _QUERY_TERMS.items()
        if any(term in query for term in terms)
    }
    for key in hard_filters or {}:
        aspect = _FILTER_ASPECTS.get(key)
        if aspect is not None:
            targets.add(aspect.value)
    return targets or {FactType.DESCRIPTION.value}


def encode_aspects(aspects: Iterable[str | FactType]) -> str:
    return ",".join(sorted({str(getattr(item, "value", item)) for item in aspects}))


def decode_aspects(value: str | None) -> set[str]:
    return {item for item in (value or "").split(",") if item}
