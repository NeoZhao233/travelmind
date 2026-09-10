from travelmind.evaluation.incremental_ingestion_runner import (
    run_incremental_ingestion_drill,
)


def test_typed_parse_conflict_and_incremental_index_drill() -> None:
    report = run_incremental_ingestion_drill()

    assert report["metrics"] == {
        "check_pass_rate": 1,
        "parse_quarantine_accuracy": 1,
        "conflict_policy_accuracy": 1,
        "incremental_key_recompute_ratio": 0.5,
        "no_op_detection_rate": 1,
        "failed_update_state_preservation_rate": 1,
    }
    assert all(report["checks"].values())
