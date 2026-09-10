from travelmind.evaluation.index_publish_runner import run_index_publish_drill


def test_versioned_index_publish_drill_passes_all_contracts() -> None:
    report = run_index_publish_drill()

    assert report["metrics"] == {
        "check_pass_rate": 1,
        "invalid_publish_block_rate": 1,
        "previous_version_preservation_rate": 1,
        "rollback_success_rate": 1,
        "snapshot_deduplication_rate": 1,
    }
    assert all(report["checks"].values())
