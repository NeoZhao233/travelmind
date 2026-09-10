import json
import shutil
from pathlib import Path

from travelmind.evaluation.release_audit import run_release_audit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("release/travelmind-v1.json")


def test_release_manifest_hashes_and_semantic_claims_pass() -> None:
    report = run_release_audit(PROJECT_ROOT, MANIFEST)

    assert report["status"] == "passed"
    assert report["summary"] == {
        "check_count": 33,
        "failed_check_count": 0,
        "evidence_file_count": 15,
    }
    assert all(report["checks"].values())


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
