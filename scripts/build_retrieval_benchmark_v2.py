#!/usr/bin/env python3
"""Build the transparent paraphrase-clustered retrieval benchmark v2."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _case(
    query_type: str,
    number: int,
    queries: list[str],
    documents: dict[str, int] | None,
    places: list[str],
    fact_types: list[str],
    tags: list[str],
) -> dict[str, Any]:
    if len(queries) != 3:
        raise ValueError("each intent requires exactly three authored paraphrases")
    query_type_slug = query_type.replace("_", "-")
    return {
        "intent_id": f"v2-{query_type_slug}-{number:02d}",
        "query_type": query_type,
        "queries": queries,
        "relevant_documents": documents or {},
        "expected_place_ids": places,
        "expected_fact_types": fact_types,
        "should_abstain": documents is None,
        "challenge_tags": tags,
        "evaluation_split": "development" if number in {1, 2, 4} else "test",
    }


CASES = [
    _case(
        "semantic",
        1,
        [
            "想了解明清皇宫生活，北京最有代表性的参观点是什么？",
            "哪里能通过宫殿和皇家旧藏认识明清历史？",
            "北京哪个景点最适合看紫禁城建筑与宫廷文化？",
        ],
        {"palace-description-20260908": 3},
        ["palace-museum"],
        ["description"],
        ["implicit-place", "culture"],
    ),
    _case(
        "semantic",
        2,
        [
            "八达岭长城适合带老人走哪一段？",
            "想找坡度较缓的长城路线，有什么建议？",
            "长城哪个入口对行动不便游客更友好？",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "semantic",
        3,
        [
            "想看湖景、长廊和皇家园林建筑，应该去哪里？",
            "北京哪座园林把山水和宫苑建筑结合在一起？",
            "喜欢昆明湖与传统园林景观，推荐哪个景点？",
        ],
        {"summer-palace-description-20260908": 3},
        ["summer-palace"],
        ["description"],
        ["implicit-place", "synonym"],
    ),
    _case(
        "semantic",
        4,
        [
            "想了解古代皇家祭祀和礼乐文化，北京去哪里合适？",
            "哪个景点能看到明清祭天建筑群？",
            "对祈年殿、圜丘和传统礼制感兴趣，应该查哪里？",
        ],
        {"temple-heaven-description-20260908": 3},
        ["temple-of-heaven"],
        ["description"],
        ["implicit-place", "culture"],
    ),
    _case(
        "semantic",
        5,
        [
            "想比较明清宫廷建筑和祭祀建筑，有哪些资料？",
            "北京哪些景点分别体现皇家生活与祭天礼制？",
            "想同时了解紫禁城与皇家祭祀文化，应该查哪些介绍？",
        ],
        {"palace-description-20260908": 3, "temple-heaven-description-20260908": 3},
        ["palace-museum", "temple-of-heaven"],
        ["description"],
        ["multi-relevant", "culture"],
    ),
    _case(
        "semantic",
        6,
        [
            "带轮椅老人找一个免费开放的历史街区",
            "哪里适合行动不便的长辈免费散步且不用预约？",
            "想找全天开放、有无障碍条件的北京老城公园",
        ],
        {"shichahai-access-20260908": 3},
        ["shichahai-park"],
        ["admission", "booking", "accessibility"],
        ["implicit-place", "accessibility"],
    ),
    _case(
        "semantic",
        7,
        [
            "香山秋季红叶最佳观赏路线是什么？",
            "去香山看红叶应该从哪条路线走？",
            "北京香山赏秋有哪些推荐线路？",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "exact",
        1,
        [
            "故宫午门能进吗，神武门能出吗？",
            "故宫的指定入口和出口分别叫什么？",
            "参观故宫可以从北门进入、午门离开吗？",
        ],
        {"palace-route-20260908": 3},
        ["palace-museum"],
        ["access"],
        ["named-entity", "direction"],
    ),
    _case(
        "exact",
        2,
        [
            "雍和宫门票多少钱，可以现场买吗？",
            "雍和宫成人票价和购票渠道是什么？",
            "去雍和宫需要提前几天买票？",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "exact",
        3,
        [
            "故宫门票提前几天、几点开始预约？",
            "故宫是否出售当日票，预约在什么时间放票？",
            "故宫官方预约窗口是提前7日20点吗？",
        ],
        {"palace-booking-20260908": 3},
        ["palace-museum"],
        ["booking"],
        ["number", "booking"],
    ),
    _case(
        "exact",
        4,
        [
            "颐和园旺季普通票和联票各多少钱？",
            "颐和园淡季门票20元、联票50元吗？",
            "查一下颐和园旺季与淡季的门票价格",
        ],
        {"summer-palace-ticket-20260908": 3},
        ["summer-palace"],
        ["admission"],
        ["number", "season"],
    ),
    _case(
        "exact",
        5,
        [
            "天坛旺季联票全价是34元吗？",
            "天坛普通门票和联票的全价分别多少？",
            "买天坛祈年殿联票需要多少钱？",
        ],
        {"temple-heaven-hours-20260908": 3},
        ["temple-of-heaven"],
        ["admission"],
        ["number", "ticket-type"],
    ),
    _case(
        "exact",
        6,
        [
            "国家博物馆提前几天预约，收费吗？",
            "国博免费票要不要实名预约？",
            "中国国家博物馆能预约未来7天内的时段吗？",
        ],
        {"national-museum-booking-20260908": 3},
        ["national-museum-china"],
        ["booking"],
        ["number", "booking"],
    ),
    _case(
        "exact",
        7,
        [
            "北海公园游船每小时多少钱？",
            "北海公园脚踏船押金和租金是多少？",
            "北海公园电瓶船具体怎么收费？",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "metadata",
        1,
        [
            "东城区需要实名预约的博物馆有哪些？",
            "找北京东城范围内必须提前预约的室内博物馆",
            "东城区哪些博物馆不能直接现场进入？",
        ],
        {"palace-booking-20260908": 2, "national-museum-booking-20260908": 3},
        ["palace-museum", "national-museum-china"],
        ["booking"],
        ["district", "category", "multi-relevant"],
    ),
    _case(
        "metadata",
        2,
        [
            "朝阳区有哪些免费当代艺术馆？",
            "找一个北京朝阳区不用预约的美术馆",
            "朝阳区免费室内艺术场馆推荐",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "metadata",
        3,
        [
            "西城区免费、全天开放且有无障碍条件的公园",
            "找西城不用预约的开放型历史公园",
            "西城区门票为零并适合轮椅的景点",
        ],
        {"shichahai-access-20260908": 3},
        ["shichahai-park"],
        ["admission", "booking", "accessibility"],
        ["district", "multi-filter"],
    ),
    _case(
        "metadata",
        4,
        [
            "海淀区皇家园林的票务资料",
            "找北京海淀世界遗产类景点的门票信息",
            "海淀区历史文化园林旺季票价",
        ],
        {"summer-palace-ticket-20260908": 3},
        ["summer-palace"],
        ["admission"],
        ["district", "category"],
    ),
    _case(
        "metadata",
        5,
        [
            "东城区免费的室内博物馆需要预约吗？",
            "找东城免费但实行预约时段的博物馆",
            "北京东城区哪家国家级博物馆免费实名预约？",
        ],
        {"national-museum-booking-20260908": 3},
        ["national-museum-china"],
        ["booking"],
        ["district", "price", "category"],
    ),
    _case(
        "metadata",
        6,
        [
            "北京历史文化类公园中需要实名购票的是哪个？",
            "东城区世界遗产公园的官方预约渠道",
            "找需要提前1至7日购票的历史公园",
        ],
        {"temple-heaven-booking-20260908": 3},
        ["temple-of-heaven"],
        ["booking"],
        ["category", "booking"],
    ),
    _case(
        "metadata",
        7,
        [
            "丰台区适合儿童的室内科技馆有哪些？",
            "找丰台区雨天能玩的亲子场馆",
            "北京丰台儿童科技类室内景点推荐",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "temporal",
        1,
        [
            "普通周一故宫开放吗？",
            "不是节假日的星期一能进故宫吗？",
            "计划周一参观故宫是否会遇到闭馆？",
        ],
        {"palace-opening-20260908": 3},
        ["palace-museum"],
        ["opening_hours"],
        ["weekday", "exception"],
    ),
    _case(
        "temporal",
        2,
        [
            "北海公园冬季几点停止入园？",
            "一月份去北海公园最晚几点能进？",
            "北海公园淡季开放时间是什么？",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "temporal",
        3,
        [
            "十月故宫下午四点以后还能入馆吗？",
            "故宫旺季16:10到达还能检票吗？",
            "故宫四月至十月最晚入馆时间是什么？",
        ],
        {"palace-opening-20260908": 3},
        ["palace-museum"],
        ["opening_hours"],
        ["season", "time-boundary"],
    ),
    _case(
        "temporal",
        4,
        [
            "周一颐和园大门开放时佛香阁也开放吗？",
            "星期一能进入颐和园园中园吗？",
            "非节假日周一参观苏州街会不会闭园？",
        ],
        {"summer-palace-inner-20260908": 3, "summer-palace-hours-20260908": 1},
        ["summer-palace"],
        ["opening_hours"],
        ["scope", "weekday"],
    ),
    _case(
        "temporal",
        5,
        [
            "周一天坛公园和祈年殿都开吗？",
            "非节假日星期一还能看回音壁吗？",
            "天坛大门开放是否代表收费景点周一也开放？",
        ],
        {"temple-heaven-hours-20260908": 3},
        ["temple-of-heaven"],
        ["opening_hours"],
        ["scope", "weekday"],
    ),
    _case(
        "temporal",
        6,
        [
            "六月下午四点半国家博物馆还能入馆吗？",
            "国博夏季延时开放时16:30可以进吗？",
            "十月国博停止入馆时间是否仍是16点？",
        ],
        {"national-museum-hours-20260908": 3},
        ["national-museum-china"],
        ["opening_hours"],
        ["season", "freshness"],
    ),
    _case(
        "temporal",
        7,
        [
            "八达岭长城夜游几点停止检票？",
            "暑期长城夜场营业到几点？",
            "八达岭夜长城周末开放时间是什么？",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "multi_constraint",
        1,
        [
            "周一带父母低预算出游，希望免费、无障碍且不用预约",
            "老人星期一出行，找全天开放又不收门票的地方",
            "预算很少并带轮椅长辈，周一去哪儿不用提前订票？",
        ],
        {
            "shichahai-access-20260908": 3,
            "palace-opening-20260908": 1,
            "national-museum-hours-20260908": 1,
        },
        ["shichahai-park"],
        ["opening_hours", "admission", "booking", "accessibility"],
        ["weekday", "budget", "accessibility"],
    ),
    _case(
        "multi_constraint",
        2,
        [
            "环球影城儿童票身高限制和快速通行价格是什么？",
            "带一米二儿童去环球影城该买什么票？",
            "北京环球度假区儿童票与优速通如何收费？",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
    _case(
        "multi_constraint",
        3,
        [
            "上午从午门进故宫，下午从北侧离开要注意什么？",
            "故宫南进北出并衔接下午行程，需要查哪些规则？",
            "能否从神武门进故宫再从午门出去赶下午景点？",
        ],
        {"palace-route-20260908": 3, "palace-opening-20260908": 1},
        ["palace-museum"],
        ["access", "opening_hours"],
        ["route", "time"],
    ),
    _case(
        "multi_constraint",
        4,
        [
            "周一买天坛联票看祈年殿，这个计划有什么问题？",
            "星期一去天坛收费景点并购买34元联票可行吗？",
            "非节假日周一想看圜丘和回音壁应该如何调整？",
        ],
        {"temple-heaven-hours-20260908": 3, "temple-heaven-booking-20260908": 1},
        ["temple-of-heaven"],
        ["opening_hours", "admission", "booking"],
        ["weekday", "ticket", "booking"],
    ),
    _case(
        "multi_constraint",
        5,
        [
            "周一去颐和园并参观佛香阁，买联票是否合适？",
            "星期一想逛颐和园园中园并控制在60元内可行吗？",
            "周一颐和园大门和苏州街的开放规则是否相同？",
        ],
        {
            "summer-palace-inner-20260908": 3,
            "summer-palace-ticket-20260908": 2,
            "summer-palace-hours-20260908": 1,
        },
        ["summer-palace"],
        ["opening_hours", "admission"],
        ["weekday", "scope", "budget"],
    ),
    _case(
        "multi_constraint",
        6,
        [
            "周一想免费去国家博物馆，还需要预约吗？",
            "预算为零且只有周一有空，国博行程是否可执行？",
            "星期一带证件去免费参观国博，预约后就能进吗？",
        ],
        {"national-museum-hours-20260908": 3, "national-museum-booking-20260908": 3},
        ["national-museum-china"],
        ["opening_hours", "booking"],
        ["weekday", "price", "booking"],
    ),
    _case(
        "multi_constraint",
        7,
        [
            "首都机场转机六小时能否往返长城？",
            "北京机场短暂停留去八达岭来得及吗？",
            "六小时中转想游长城，需要多少交通时间？",
        ],
        None,
        [],
        [],
        ["out-of-corpus", "abstention"],
    ),
]


def build_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in CASES:
        for index, query in enumerate(case["queries"], start=1):
            rows.append(
                {
                    "query_id": f"{case['intent_id']}-p{index}",
                    "query": query,
                    "query_type": case["query_type"],
                    "relevant_documents": case["relevant_documents"],
                    "expected_place_ids": case["expected_place_ids"],
                    "expected_fact_types": case["expected_fact_types"],
                    "should_abstain": case["should_abstain"],
                    "notes": "Codex-authored draft; requires independent human review.",
                    "annotator": "codex_draft",
                    "reviewed": False,
                    "evaluation_split": case["evaluation_split"],
                    "intent_id": case["intent_id"],
                    "paraphrase_id": f"p{index}",
                    "challenge_tags": case["challenge_tags"],
                }
            )
    return rows


def build_review_packet() -> str:
    lines = [
        "# Retrieval benchmark v2 human review packet",
        "",
        "Review one intent cluster at a time. Check the box only if all three paraphrases, the",
        "answerable/no-answer decision, and proposed relevant documents are correct. Record any",
        "correction below the cluster. This file starts with every item pending.",
        "",
    ]
    for case in CASES:
        documents = case["relevant_documents"] or {"<none: should abstain>": 0}
        lines.extend(
            [
                f"## {case['intent_id']} ({case['evaluation_split']})",
                "",
                "- [ ] Independently reviewed and approved",
                f"- Query type: `{case['query_type']}`",
                f"- Should abstain: `{str(case['should_abstain']).lower()}`",
                "- Proposed documents: "
                + ", ".join(f"`{key}` (grade {value})" for key, value in documents.items()),
                "- Paraphrases:",
                *[f"  {index}. {query}" for index, query in enumerate(case["queries"], start=1)],
                "- Correction/reason:",
                "",
            ]
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("evals/datasets/retrieval_benchmark_v2.jsonl"),
    )
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("evals/annotations/retrieval_benchmark_v2_review.md"),
    )
    args = parser.parse_args()
    rows = build_rows()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )
    args.review_output.parent.mkdir(parents=True, exist_ok=True)
    args.review_output.write_text(build_review_packet(), encoding="utf-8")
    print(f"wrote {len(rows)} queries across {len(CASES)} intent clusters to {args.output}")
    print(f"wrote pending human review packet to {args.review_output}")


if __name__ == "__main__":
    main()
