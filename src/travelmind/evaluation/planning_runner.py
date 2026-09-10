from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, model_validator

from travelmind.planner.constraints import validate_itinerary
from travelmind.schemas import Itinerary, PlanningValidationContext, TravelConstraints


class PlanningConstraintCase(BaseModel):
    case_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    itinerary: Itinerary
    constraints: TravelConstraints = Field(default_factory=TravelConstraints)
    context: PlanningValidationContext | None = None
    expected_codes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def expected_codes_are_unique(self) -> PlanningConstraintCase:
        if len(self.expected_codes) != len(set(self.expected_codes)):
            raise ValueError("expected_codes must be unique")
        return self


def _load_cases(path: Path) -> list[PlanningConstraintCase]:
    cases = [
        PlanningConstraintCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    case_ids = [case.case_id for case in cases]
    if not cases:
        raise ValueError("planning constraint dataset is empty")
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("planning constraint case_id values must be unique")
    return cases


def run_planning_constraint_experiment(project_root: Path) -> dict[str, Any]:
    dataset_path = project_root / "evals/datasets/planning_constraints_seed.jsonl"
    raw = dataset_path.read_bytes()
    cases = _load_cases(dataset_path)
    results: list[dict[str, Any]] = []
    exact_matches = 0
    expected_safety_cases = 0
    detected_safety_cases = 0
    clean_cases = 0
    clean_passes = 0

    for case in cases:
        violations = validate_itinerary(case.itinerary, case.constraints, case.context)
        actual_codes = sorted({item.code for item in violations})
        expected_codes = sorted(case.expected_codes)
        exact_match = actual_codes == expected_codes
        exact_matches += int(exact_match)
        if expected_codes:
            expected_safety_cases += 1
            detected_safety_cases += int(set(expected_codes).issubset(actual_codes))
        else:
            clean_cases += 1
            clean_passes += int(not actual_codes)
        results.append(
            {
                "case_id": case.case_id,
                "description": case.description,
                "expected_codes": expected_codes,
                "actual_codes": actual_codes,
                "exact_match": exact_match,
            }
        )

    return {
        "experiment": "stage5a-deterministic-constraint-validation",
        "dataset": str(dataset_path.relative_to(project_root)),
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "limitations": [
            "Project-authored controlled scenarios, not natural-traffic production data.",
            "Availability records are fixtures; live-source freshness is not tested.",
            "Travel-time feasibility is deferred to Stage 5B.",
        ],
        "metrics": {
            "case_count": len(cases),
            "exact_match_accuracy": exact_matches / len(cases),
            "safety_case_detection_rate": (
                detected_safety_cases / expected_safety_cases if expected_safety_cases else 0.0
            ),
            "clean_case_pass_rate": clean_passes / clean_cases if clean_cases else 0.0,
        },
        "cases": results,
    }


def write_planning_constraint_report(project_root: Path, output: Path) -> dict[str, Any]:
    report = run_planning_constraint_experiment(project_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        f"{json.dumps(report, ensure_ascii=False, indent=2)}\n",
        encoding="utf-8",
    )
    return report
