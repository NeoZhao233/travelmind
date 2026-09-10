from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from travelmind.evaluation.e2e_planning_runner import E2EPlanningDataset

SplitName = Literal["development", "test", "challenge"]
ReviewStatus = Literal["project_authored", "independently_reviewed"]


class EvaluationCaseGovernance(BaseModel):
    case_id: str
    split: SplitName
    author_ids: list[str] = Field(min_length=1)
    reviewer_ids: list[str] = Field(default_factory=list)
    review_status: ReviewStatus = "project_authored"

    @model_validator(mode="after")
    def validate_review_claim(self) -> EvaluationCaseGovernance:
        if self.review_status == "independently_reviewed":
            independent = set(self.reviewer_ids) - set(self.author_ids)
            if not independent:
                raise ValueError("independently_reviewed requires a reviewer who is not an author")
        return self


class EvaluationGovernanceManifest(BaseModel):
    schema_version: int = 1
    dataset_id: str
    dataset_version: str
    task: str
    source_dataset: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    cases: list[EvaluationCaseGovernance] = Field(min_length=1)
    notes: list[str] = Field(default_factory=list)


class DatasetGovernanceError(ValueError):
    """Raised when an evaluation manifest makes an unverifiable claim."""


def _normalize_query(value: str) -> str:
    return re.sub(r"[^\w]+", "", value.casefold())


def _scenario_fingerprint(case: Any) -> str:
    payload = {
        "constraints": case.constraints.model_dump(mode="json", exclude_none=True),
        "expected_place_ids": sorted(case.expected_place_ids),
        "minimum_expected_hits": case.minimum_expected_hits,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def validate_evaluation_governance(root: Path, manifest_path: Path) -> dict[str, Any]:
    root = root.resolve()
    resolved_manifest = (
        manifest_path if manifest_path.is_absolute() else root / manifest_path
    ).resolve()
    manifest = EvaluationGovernanceManifest.model_validate_json(resolved_manifest.read_bytes())
    dataset_path = (root / manifest.source_dataset).resolve()
    if root not in dataset_path.parents:
        raise DatasetGovernanceError("source_dataset must remain inside the project root")
    raw_dataset = dataset_path.read_bytes()
    actual_sha = hashlib.sha256(raw_dataset).hexdigest()
    if actual_sha != manifest.source_sha256:
        raise DatasetGovernanceError("source dataset hash does not match the manifest")

    dataset = E2EPlanningDataset.model_validate_json(raw_dataset)
    dataset_cases = {case.case_id: case for case in dataset.cases}
    governed_ids = [item.case_id for item in manifest.cases]
    duplicate_ids = sorted(case_id for case_id, count in Counter(governed_ids).items() if count > 1)
    if duplicate_ids:
        raise DatasetGovernanceError(f"duplicate governed case IDs: {duplicate_ids}")
    missing = sorted(set(dataset_cases) - set(governed_ids))
    unknown = sorted(set(governed_ids) - set(dataset_cases))
    if missing or unknown:
        raise DatasetGovernanceError(
            f"manifest coverage mismatch; missing={missing}, unknown={unknown}"
        )

    split_by_id = {item.case_id: item.split for item in manifest.cases}
    split_counts = Counter(split_by_id.values())
    if not split_counts["development"] or not split_counts["test"]:
        raise DatasetGovernanceError("development and test splits must both be non-empty")

    leakage: list[dict[str, Any]] = []
    for kind, fingerprint_fn in [
        ("normalized_query", lambda case: _normalize_query(case.query)),
        ("scenario", _scenario_fingerprint),
    ]:
        seen: dict[str, tuple[str, str]] = {}
        for case in dataset.cases:
            fingerprint = fingerprint_fn(case)
            previous = seen.get(fingerprint)
            current = (case.case_id, split_by_id[case.case_id])
            if previous is not None and previous[1] != current[1]:
                leakage.append(
                    {
                        "type": kind,
                        "case_ids": [previous[0], current[0]],
                        "splits": [previous[1], current[1]],
                    }
                )
            seen[fingerprint] = current
    if leakage:
        raise DatasetGovernanceError(f"cross-split leakage detected: {leakage}")

    independently_reviewed = sum(
        item.review_status == "independently_reviewed" for item in manifest.cases
    )
    test_items = [item for item in manifest.cases if item.split == "test"]
    test_is_independently_reviewed = all(
        item.review_status == "independently_reviewed" for item in test_items
    )
    return {
        "dataset_id": manifest.dataset_id,
        "dataset_version": manifest.dataset_version,
        "dataset": manifest.source_dataset,
        "dataset_sha256": actual_sha,
        "manifest": str(resolved_manifest.relative_to(root)),
        "manifest_sha256": hashlib.sha256(resolved_manifest.read_bytes()).hexdigest(),
        "case_count": len(dataset.cases),
        "split_counts": dict(sorted(split_counts.items())),
        "review_counts": {
            "project_authored": len(manifest.cases) - independently_reviewed,
            "independently_reviewed": independently_reviewed,
        },
        "cross_split_leakage_count": 0,
        "test_is_independently_reviewed": test_is_independently_reviewed,
        "test_is_blind": False,
        "claim_boundary": (
            "The test partition is frozen but project-authored; it is not an independent "
            "or blind benchmark."
            if not test_is_independently_reviewed
            else (
                "Labels were independently reviewed, but author exposure still prevents a "
                "blind claim."
            )
        ),
        "case_splits": split_by_id,
    }
