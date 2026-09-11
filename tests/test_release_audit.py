import json
import shutil
from pathlib import Path

from travelmind.evaluation.release_audit import run_release_audit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("release/travelmind-v1.json")
V2_MANIFEST = Path("release/travelmind-v2.json")
V3_MANIFEST = Path("release/travelmind-v3.json")


def test_v1_manifest_stays_frozen_when_dependencies_evolve() -> None:
    report = run_release_audit(PROJECT_ROOT, MANIFEST)

    assert report["release_id"] == "travelmind-interview-v1"
    assert report["status"] == "failed"
    assert report["failed_checks"] == [
        "hash:pyproject.toml",
        "hash:uv.lock",
    ]


def test_v2_manifest_stays_frozen_when_dependencies_evolve() -> None:
    report = run_release_audit(PROJECT_ROOT, V2_MANIFEST)

    assert report["release_id"] == "travelmind-interview-v2"
    assert report["status"] == "failed"
    assert report["failed_checks"] == [
        "hash:pyproject.toml",
        "hash:uv.lock",
    ]


def test_v3_release_adds_harness_evidence_without_rewriting_v1_or_v2() -> None:
    report = run_release_audit(PROJECT_ROOT, V3_MANIFEST)

    assert report["release_id"] == "travelmind-interview-v3"
    assert report["status"] == "passed"
    assert report["summary"] == {
        "check_count": 62,
        "failed_check_count": 0,
        "evidence_file_count": 29,
    }
    assert all(report["checks"].values())
    assert report["checks"]["agentic_runtime_improved_intermediate_recovery"] is True
    assert report["checks"]["harness_contract_checks_passed"] is True
    assert report["checks"]["live_redis_not_misrepresented"] is True


def test_tampered_release_evidence_fails_audit(tmp_path) -> None:
    manifest = json.loads((PROJECT_ROOT / MANIFEST).read_text())
    for relative in manifest["evidence_files"]:
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJECT_ROOT / relative, destination)
    shutil.copy2(PROJECT_ROOT / ".gitignore", tmp_path / ".gitignore")
    manifest_path = tmp_path / MANIFEST
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    evidence = tmp_path / "evals/results/hybrid_rrf_seed.json"
    evidence.write_bytes(evidence.read_bytes() + b"\n")

    report = run_release_audit(tmp_path, manifest_path)

    assert report["status"] == "failed"
    assert report["checks"]["hash:evals/results/hybrid_rrf_seed.json"] is False
