import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer

from travelmind.agentic.builder import build_agentic_travel_graph
from travelmind.agentic.llm_provider import DeepSeekConfig, DeepSeekHTTPProvider
from travelmind.evaluation.agentic_runner import (
    run_deterministic_agentic_policy_experiment,
)
from travelmind.evaluation.answerability_runner import run_answerability_admission_experiment
from travelmind.evaluation.candidate_planning_runner import (
    run_candidate_planning_experiment,
)
from travelmind.evaluation.checkpoint_runner import run_checkpoint_idempotency_drill
from travelmind.evaluation.context_answer_runner import run_context_answer_ablation
from travelmind.evaluation.context_runner import (
    run_context_budget_experiment,
    run_context_budget_sweep,
    run_context_coverage_experiment,
)
from travelmind.evaluation.deepseek_runner import run_deepseek_policy_experiment
from travelmind.evaluation.deepseek_runtime_runner import run_deepseek_runtime_experiment
from travelmind.evaluation.durable_checkpoint_runner import run_durable_checkpoint_drill
from travelmind.evaluation.e2e_planning_runner import (
    build_selected_hybrid_retriever,
    run_e2e_planning_experiment,
)
from travelmind.evaluation.error_analysis import audit_e2e_report
from travelmind.evaluation.harness_runner import run_harness_experiment
from travelmind.evaluation.incremental_ingestion_runner import (
    run_incremental_ingestion_drill,
)
from travelmind.evaluation.index_publish_runner import run_index_publish_drill
from travelmind.evaluation.judge_calibration import (
    HumanLabelsIncompleteError,
    prepare_calibration_packet,
    run_judge_calibration,
)
from travelmind.evaluation.live_agentic_runner import run_live_agentic_experiment
from travelmind.evaluation.memory_runner import run_memory_isolation_experiment
from travelmind.evaluation.observability_runner import run_observability_drill
from travelmind.evaluation.pdf_ingestion_runner import run_pdf_ingestion_drill
from travelmind.evaluation.planning_runner import run_planning_constraint_experiment
from travelmind.evaluation.policy_selection import select_agentic_policies
from travelmind.evaluation.redis_backend_runner import (
    RedisBackendProbeError,
    run_redis_backend_probe,
)
from travelmind.evaluation.refinement_runner import run_context_refinement_experiment
from travelmind.evaluation.regression_gate import run_regression_gate
from travelmind.evaluation.release_audit import run_release_audit
from travelmind.evaluation.repair_runner import run_repair_experiment
from travelmind.evaluation.resilience_runner import run_retrieval_resilience_drill
from travelmind.evaluation.runner import (
    run_bm25_experiment,
    run_dense_experiment,
    run_hybrid_experiment,
    run_reranked_hybrid_experiment,
)
from travelmind.evaluation.runtime_failure_matrix_runner import (
    run_runtime_failure_matrix_experiment,
)
from travelmind.evaluation.runtime_multistep_runner import run_runtime_multistep_experiment
from travelmind.evaluation.runtime_replanning_runner import run_runtime_replanning_experiment
from travelmind.evaluation.slo_runner import run_slo_outage_drill
from travelmind.evaluation.source_fetch_runner import run_source_fetch_drill
from travelmind.evaluation.trajectory_runner import run_trajectory_experiment
from travelmind.graph.builder import build_travel_graph
from travelmind.ingestion.dataset import validate_seed_dataset
from travelmind.ingestion.pdf_sources import PdfSourceDownloader, load_pdf_source_registry
from travelmind.ingestion.publishing import VersionedIndexPublisher
from travelmind.planner.demo import DemoPlanner
from travelmind.retrieval.base import InMemoryRetriever
from travelmind.retrieval.embeddings import (
    BGE_SMALL_ZH_V15,
    DenseDependencyError,
    DenseEmbeddingError,
)
from travelmind.retrieval.reranking import (
    BGE_RERANKER_BASE,
    RerankerDependencyError,
    RerankerInferenceError,
)
from travelmind.schemas import Evidence, TravelRequest

app = typer.Typer(help="TravelMind command-line interface.")


def _jsonable(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


@app.callback()
def main() -> None:
    """Run TravelMind development and evaluation commands."""


@app.command()
def demo(query: str) -> None:
    """Run the deterministic demo graph without external services or API keys."""

    documents = [
        Evidence(
            id="demo-palace-museum",
            content="故宫博物院是北京重要的历史文化景点，参观前应核验预约与开放信息。",
            source_url="https://example.invalid/demo",
            source_type="official",
            score=0.9,
            retrieved_at=datetime.now(UTC),
            metadata={"place_id": "palace-museum", "name": "故宫博物院", "cost": 60},
        )
    ]
    graph = build_travel_graph(
        retriever=InMemoryRetriever(documents),
        planner=DemoPlanner(),
    )
    result = graph.invoke({"request": TravelRequest(query=query)})
    serializable = {
        key: value.model_dump(mode="json") if hasattr(value, "model_dump") else value
        for key, value in result.items()
    }
    serializable["evidence"] = [item.model_dump(mode="json") for item in result["evidence"]]
    serializable["violations"] = [item.model_dump(mode="json") for item in result["violations"]]
    typer.echo(json.dumps(serializable, ensure_ascii=False, indent=2, default=str))


@app.command("agentic-demo")
def agentic_demo(query: str) -> None:
    """Run the deterministic Stage 3A routing, grading, and rewrite graph."""

    evidence = Evidence(
        id="demo-complete-official-evidence",
        content=(
            "官方信息：门票票价、开放时间、预约规则、入口交通与无障碍设施，"
            "均应在出行前按最新公告复核。"
        ),
        source_url="https://example.invalid/agentic-demo",
        source_type="official",
        score=1.0,
        retrieved_at=datetime.now(UTC),
        metadata={"place_id": "demo-place", "name": "示例景点", "cost": 0},
    )
    graph = build_agentic_travel_graph(
        retriever=InMemoryRetriever([evidence]),
        planner=DemoPlanner(),
    )
    result = graph.invoke({"request": TravelRequest(query=query)})
    typer.echo(json.dumps(_jsonable(result), ensure_ascii=False, indent=2, default=str))


@app.command("validate-data")
def validate_data(
    root: Annotated[
        Path,
        typer.Option("--root", help="Project root containing data/seed and evals/datasets."),
    ] = Path("."),
) -> None:
    """Validate Stage 1 seed records, references, chunks, and retrieval labels."""

    summary = validate_seed_dataset(root.resolve())
    typer.echo(summary.model_dump_json(indent=2))


@app.command("eval-agentic")
def eval_agentic(
    root: Annotated[
        Path,
        typer.Option("--root", help="Project root containing the agentic seed labels."),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report path."),
    ] = None,
) -> None:
    """Evaluate deterministic routing and evidence-grading policies."""

    project_root = root.resolve()
    report = run_deterministic_agentic_policy_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote agentic policy report to {destination}")
    typer.echo(
        json.dumps(
            {
                "routing_metrics": report["routing_metrics"],
                "grading_metrics": report["grading_metrics"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("eval-trajectory")
def eval_trajectory(
    root: Annotated[
        Path,
        typer.Option("--root", help="Project root containing trajectory labels."),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report path."),
    ] = None,
) -> None:
    """Compare direct and Agentic control on scripted retrieval trajectories."""

    project_root = root.resolve()
    report = run_trajectory_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote trajectory report to {destination}")
    typer.echo(
        json.dumps(
            {
                "direct_metrics": report["direct_metrics"],
                "agentic_metrics": report["agentic_metrics"],
                "retrieval_call_amplification": report["retrieval_call_amplification"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("eval-runtime-replanning")
def eval_runtime_replanning(
    root: Annotated[
        Path,
        typer.Option("--root", help="Project root containing runtime failure labels."),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report path."),
    ] = None,
) -> None:
    """Compare fixed-plan and replanning runtimes on controlled tool failures."""

    project_root = root.resolve()
    report = run_runtime_replanning_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote runtime replanning report to {destination}")
    typer.echo(json.dumps(report["agentic_metrics"], ensure_ascii=False, indent=2))


@app.command("eval-runtime-multistep")
def eval_runtime_multistep(
    root: Annotated[
        Path,
        typer.Option("--root", help="Project root containing multi-step runtime labels."),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report path."),
    ] = None,
) -> None:
    """Evaluate mid-flight replanning and completed-observation reuse."""

    project_root = root.resolve()
    report = run_runtime_multistep_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote multi-step runtime report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-runtime-failure-matrix")
def eval_runtime_failure_matrix(
    root: Annotated[
        Path,
        typer.Option("--root", help="Project root containing the Stage 12 fault matrix."),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report path."),
    ] = None,
) -> None:
    """Evaluate retry, replan, reuse, and safe stop over the expanded fault matrix."""

    project_root = root.resolve()
    report = run_runtime_failure_matrix_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote runtime failure matrix report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-harness")
def eval_harness(
    root: Annotated[
        Path,
        typer.Option("--root", help="Project root for the Stage 13 harness drill."),
    ] = Path("."),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report path."),
    ] = None,
) -> None:
    """Evaluate MCP boundaries, safe fallback, cache policy, and safe stop."""

    project_root = root.resolve()
    report = run_harness_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote Stage 13 harness report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-redis-backend")
def eval_redis_backend(
    redis_url: Annotated[
        str,
        typer.Option("--redis-url", envvar="TRAVELMIND_REDIS_URL"),
    ] = "redis://127.0.0.1:16379/0",
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report path."),
    ] = None,
) -> None:
    """Probe live Redis cache TTL and checkpoint lifecycle without exposing its URL."""

    try:
        report = run_redis_backend_probe(redis_url)
    except RedisBackendProbeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2) from None
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote Stage 13 Redis report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-answerability-admission")
def eval_answerability_admission(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Tune admission on development labels and evaluate once on the frozen test split."""

    project_root = root.resolve()
    report = run_answerability_admission_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote answerability admission report to {destination}")
    typer.echo(
        json.dumps(
            {
                "test": report["metrics_by_split"]["test"],
                "selection": report["selection"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("eval-live-agentic")
def eval_live_agentic(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
    limit: Annotated[int, typer.Option("--limit", min=1)] = 3,
    local_files_only: Annotated[
        bool, typer.Option("--local-files-only/--allow-model-download")
    ] = True,
) -> None:
    """Compare Direct and Agentic paths over the real local Hybrid RRF stack."""

    project_root = root.resolve()
    report = run_live_agentic_experiment(
        project_root, limit=limit, local_files_only=local_files_only
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote live Agentic report to {destination}")
    typer.echo(
        json.dumps(
            {
                "direct_metrics": report["direct_metrics"],
                "agentic_metrics": report["agentic_metrics"],
                "rank_call_amplification": report["rank_call_amplification"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("eval-deepseek")
def eval_deepseek(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path, typer.Option("--output")] = Path(
        "evals/results/deepseek_policy_candidate.json"
    ),
    model: Annotated[str, typer.Option("--model")] = "deepseek-v4-flash",
    base_url: Annotated[str, typer.Option("--base-url")] = "https://api.deepseek.com",
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=0.1)] = 20,
) -> None:
    """Run the live DeepSeek Router/Grader candidate; requires DEEPSEEK_API_KEY."""

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise typer.BadParameter(
            "DEEPSEEK_API_KEY is missing; no live quality or cost claim was generated."
        )
    project_root = root.resolve()
    provider = DeepSeekHTTPProvider(
        DeepSeekConfig(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    )
    report = run_deepseek_policy_experiment(project_root, provider)
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(f"Wrote DeepSeek candidate report to {destination}")


@app.command("eval-deepseek-runtime")
def eval_deepseek_runtime(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path, typer.Option("--output")] = Path(
        "evals/results/stage11_deepseek_runtime_candidate.json"
    ),
    model: Annotated[str, typer.Option("--model")] = "deepseek-v4-flash",
    base_url: Annotated[str, typer.Option("--base-url")] = "https://api.deepseek.com",
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=0.1)] = 20,
) -> None:
    """Evaluate the live DeepSeek runtime planner with deterministic fallback."""

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise typer.BadParameter(
            "DEEPSEEK_API_KEY is missing; no live runtime-planner result was claimed."
        )
    project_root = root.resolve()
    provider = DeepSeekHTTPProvider(
        DeepSeekConfig(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
    )
    report = run_deepseek_runtime_experiment(project_root, provider)
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(f"Wrote DeepSeek runtime report to {destination}")
    typer.echo(
        json.dumps(
            {"metrics": report["metrics"], "selection": report["selection"]},
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("eval-context-answers")
def eval_context_answers(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path, typer.Option("--output")] = Path(
        "evals/results/stage4_deepseek_answer_ablation_v1.json"
    ),
    model: Annotated[str, typer.Option("--model")] = "deepseek-v4-flash",
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=0.1)] = 30,
) -> None:
    """Run the live Stage 4F answer-level context A/B."""

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise typer.BadParameter(
            "DEEPSEEK_API_KEY is missing; no answer-level claim was generated."
        )
    project_root = root.resolve()
    provider = DeepSeekHTTPProvider(
        DeepSeekConfig(api_key=api_key, model=model, timeout_seconds=timeout_seconds)
    )
    report = run_context_answer_ablation(project_root, provider)
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(f"Wrote Stage 4 answer report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("select-agentic-policies")
def select_policies(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    candidate: Annotated[Path | None, typer.Option("--candidate")] = None,
) -> None:
    """Apply Stage 3E quality/reliability gates to an optional candidate report."""

    project_root = root.resolve()
    baseline = json.loads(
        (project_root / "evals/results/agentic_policy_rule_v1_seed.json").read_text()
    )
    candidate_report = None
    if candidate is not None:
        candidate_path = candidate if candidate.is_absolute() else project_root / candidate
        candidate_report = json.loads(candidate_path.read_text())
    result = select_agentic_policies(baseline=baseline, candidate=candidate_report)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


@app.command("eval-context")
def eval_context(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
    max_context_tokens: Annotated[int, typer.Option("--max-context-tokens", min=64)] = 768,
    reserved_output_tokens: Annotated[int, typer.Option("--reserved-output-tokens", min=1)] = 192,
    safety_margin_tokens: Annotated[int, typer.Option("--safety-margin-tokens", min=0)] = 64,
) -> None:
    """Run the Stage 4A/4B baseline-versus-budget context experiment."""

    project_root = root.resolve()
    report = run_context_budget_experiment(
        project_root,
        max_context_tokens=max_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote context budget report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-context-sweep")
def eval_context_sweep(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Select the smallest Stage 4B budget that passes the pilot recall gate."""

    project_root = root.resolve()
    report = run_context_budget_sweep(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote context budget sweep to {destination}")
    typer.echo(
        json.dumps(
            {"selected_max_context_tokens": report["selected_max_context_tokens"]},
            indent=2,
        )
    )


@app.command("eval-context-coverage")
def eval_context_coverage(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
    max_context_tokens: Annotated[int, typer.Option("--max-context-tokens", min=64)] = 768,
    reserved_output_tokens: Annotated[int, typer.Option("--reserved-output-tokens", min=1)] = 192,
    safety_margin_tokens: Annotated[int, typer.Option("--safety-margin-tokens", min=0)] = 64,
) -> None:
    """Compare rank-order packing with Stage 4C coverage-aware packing."""

    project_root = root.resolve()
    report = run_context_coverage_experiment(
        project_root,
        max_context_tokens=max_context_tokens,
        reserved_output_tokens=reserved_output_tokens,
        safety_margin_tokens=safety_margin_tokens,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote context coverage report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-context-refinement")
def eval_context_refinement(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
    compression_target_tokens: Annotated[
        int, typer.Option("--compression-target-tokens", min=16)
    ] = 45,
    duplicate_threshold: Annotated[
        float, typer.Option("--duplicate-threshold", min=0.8, max=1.0)
    ] = 0.92,
) -> None:
    """Evaluate Stage 4D deduplication, conflict handling, and compression."""

    project_root = root.resolve()
    report = run_context_refinement_experiment(
        project_root,
        compression_target_tokens=compression_target_tokens,
        duplicate_threshold=duplicate_threshold,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote context refinement report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-memory")
def eval_memory(
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 4E controlled memory isolation and lifecycle probes."""

    report = run_memory_isolation_experiment()
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote memory isolation report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-retrieval")
def eval_retrieval(
    root: Annotated[
        Path,
        typer.Option("--root", help="Project root containing data and evaluation labels."),
    ] = Path("."),
    dataset: Annotated[
        Path,
        typer.Option("--dataset", help="Retrieval JSONL path relative to the project root."),
    ] = Path("evals/datasets/retrieval_seed.jsonl"),
    output: Annotated[
        Path | None,
        typer.Option("--output", help="Optional JSON report path, relative to the project root."),
    ] = None,
    retriever: Annotated[
        str,
        typer.Option(
            "--retriever",
            help="Retrieval baseline: bm25, dense, hybrid, or reranked.",
        ),
    ] = "bm25",
    limit: Annotated[int, typer.Option("--limit", min=1)] = 10,
    k1: Annotated[float, typer.Option("--k1", min=0.01)] = 1.5,
    b: Annotated[float, typer.Option("--b", min=0.0, max=1.0)] = 0.75,
    apply_filters: Annotated[
        bool,
        typer.Option(
            "--apply-filters/--no-apply-filters",
            help="Apply only the metadata filters implemented by the BM25 baseline.",
        ),
    ] = False,
    model_name: Annotated[
        str,
        typer.Option("--model-name", help="FastEmbed model used by the dense baseline."),
    ] = BGE_SMALL_ZH_V15,
    local_files_only: Annotated[
        bool,
        typer.Option(
            "--local-files-only/--allow-model-download",
            help="Forbid network access and require an already cached embedding model.",
        ),
    ] = False,
    rrf_k: Annotated[int, typer.Option("--rrf-k", min=1)] = 60,
    candidate_limit: Annotated[int, typer.Option("--candidate-limit", min=1)] = 10,
    channel_timeout_seconds: Annotated[
        float, typer.Option("--channel-timeout-seconds", min=0.001)
    ] = 5.0,
    reranker_model_name: Annotated[
        str,
        typer.Option("--reranker-model-name", help="FastEmbed cross-encoder model."),
    ] = BGE_RERANKER_BASE,
    rerank_candidate_limit: Annotated[int, typer.Option("--rerank-candidate-limit", min=1)] = 10,
    reranker_timeout_seconds: Annotated[
        float, typer.Option("--reranker-timeout-seconds", min=0.001)
    ] = 5.0,
) -> None:
    """Run a reproducible Stage 2 retrieval baseline."""

    project_root = root.resolve()
    if retriever == "bm25":
        report = run_bm25_experiment(
            project_root,
            limit=limit,
            k1=k1,
            b=b,
            apply_filters=apply_filters,
            dataset_path=dataset,
        )
    elif retriever in {"dense", "hybrid", "reranked"}:
        if apply_filters:
            raise typer.BadParameter(
                f"The {retriever} baseline does not implement metadata filters consistently."
            )
        from travelmind.retrieval.dense import DenseIndexError, DenseRetrievalError
        from travelmind.retrieval.hybrid import HybridRetrievalError

        try:
            if retriever == "dense":
                report = run_dense_experiment(
                    project_root,
                    limit=limit,
                    model_name=model_name,
                    local_files_only=local_files_only,
                    dataset_path=dataset,
                )
            elif retriever == "hybrid":
                report = run_hybrid_experiment(
                    project_root,
                    limit=limit,
                    k1=k1,
                    b=b,
                    model_name=model_name,
                    local_files_only=local_files_only,
                    rrf_k=rrf_k,
                    candidate_limit=candidate_limit,
                    channel_timeout_seconds=channel_timeout_seconds,
                    dataset_path=dataset,
                )
            else:
                if rerank_candidate_limit < limit:
                    raise typer.BadParameter("--rerank-candidate-limit must be at least --limit")
                report = run_reranked_hybrid_experiment(
                    project_root,
                    limit=limit,
                    k1=k1,
                    b=b,
                    model_name=model_name,
                    reranker_model_name=reranker_model_name,
                    local_files_only=local_files_only,
                    rrf_k=rrf_k,
                    hybrid_candidate_limit=candidate_limit,
                    channel_timeout_seconds=channel_timeout_seconds,
                    rerank_candidate_limit=rerank_candidate_limit,
                    reranker_timeout_seconds=reranker_timeout_seconds,
                    dataset_path=dataset,
                )
        except (
            DenseDependencyError,
            DenseEmbeddingError,
            DenseIndexError,
            DenseRetrievalError,
            HybridRetrievalError,
            RerankerDependencyError,
            RerankerInferenceError,
        ) as exc:
            raise typer.BadParameter(str(exc)) from exc
    else:
        raise typer.BadParameter("retriever must be one of: bm25, dense, hybrid, reranked")
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return

    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote retrieval report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-planning-constraints")
def eval_planning_constraints(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 5A deterministic hard-constraint scenarios."""

    project_root = root.resolve()
    report = run_planning_constraint_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote planning constraint report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-candidate-planning")
def eval_candidate_planning(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 5B explainable candidate-planning scenarios."""

    project_root = root.resolve()
    report = run_candidate_planning_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote candidate planning report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-itinerary-repair")
def eval_itinerary_repair(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 5C bounded local-repair scenarios."""

    project_root = root.resolve()
    report = run_repair_experiment(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote itinerary repair report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-e2e-planning")
def eval_e2e_planning(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
    retriever: Annotated[str, typer.Option("--retriever")] = "bm25",
    live_deepseek: Annotated[bool, typer.Option("--live-deepseek/--offline")] = False,
    model: Annotated[str, typer.Option("--model")] = "deepseek-v4-flash",
    base_url: Annotated[str, typer.Option("--base-url")] = "https://api.deepseek.com",
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=0.1)] = 20,
) -> None:
    """Run Stage 5D retrieval-to-repair planning evaluation and optional live A/B."""

    project_root = root.resolve()
    if retriever == "bm25":
        selected_retriever = None
    elif retriever == "hybrid":
        try:
            selected_retriever = build_selected_hybrid_retriever(project_root)
        except Exception as exc:
            raise typer.BadParameter(f"Hybrid retriever unavailable: {type(exc).__name__}") from exc
    else:
        raise typer.BadParameter("retriever must be one of: bm25, hybrid")

    provider = None
    if live_deepseek:
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            raise typer.BadParameter(
                "DEEPSEEK_API_KEY is missing; no live planning claim was generated."
            )
        provider = DeepSeekHTTPProvider(
            DeepSeekConfig(
                api_key=api_key,
                model=model,
                base_url=base_url,
                timeout_seconds=timeout_seconds,
            )
        )
    report = run_e2e_planning_experiment(
        project_root,
        provider=provider,
        retriever=selected_retriever,
        retriever_name=retriever,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote end-to-end planning report to {destination}")
    typer.echo(
        json.dumps(
            {"metrics": report["metrics"], "selection": report["selection"]},
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("audit-e2e-evaluation")
def audit_e2e_evaluation(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    report: Annotated[Path, typer.Option("--report")] = Path(
        "evals/results/e2e_planning_deepseek_ab_v3_final.json"
    ),
    manifest: Annotated[Path, typer.Option("--manifest")] = Path(
        "evals/datasets/e2e_planning_seed.manifest.json"
    ),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Validate dataset governance and add split/error diagnostics to an E2E report."""

    project_root = root.resolve()
    audited = audit_e2e_report(
        project_root,
        report_path=report,
        manifest_path=manifest,
    )
    serialized = json.dumps(audited, ensure_ascii=False, indent=2)
    if output is None:
        typer.echo(serialized)
        return
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(f"{serialized}\n", encoding="utf-8")
    typer.echo(f"Wrote governed evaluation audit to {destination}")
    typer.echo(
        json.dumps(
            {
                "governance": audited["governance"],
                "split_metrics": audited["split_metrics"],
                "issue_counts": audited["issue_counts"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("prepare-judge-calibration")
def prepare_judge_calibration(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    source_report: Annotated[Path, typer.Option("--source-report")] = Path(
        "evals/results/stage4_deepseek_answer_ablation_v4_final.json"
    ),
    variant: Annotated[str, typer.Option("--variant")] = "refined_coverage",
    output: Annotated[Path, typer.Option("--output")] = Path(
        "evals/annotations/judge_calibration_seed_v1.json"
    ),
) -> None:
    """Create a source-variant-blinded packet for human judge calibration labels."""

    project_root = root.resolve()
    packet = prepare_calibration_packet(
        project_root, source_report_path=source_report, variant=variant
    )
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(packet, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(f"Wrote {len(packet['items'])} unlabeled calibration items to {destination}")
    typer.echo("No LLM judge was called; fill human_scores and annotator_id first.")


@app.command("eval-judge-calibration")
def eval_judge_calibration(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    dataset: Annotated[Path, typer.Option("--dataset")] = Path(
        "evals/annotations/judge_calibration_seed_v1.json"
    ),
    output: Annotated[Path, typer.Option("--output")] = Path(
        "evals/results/stage6c_deepseek_judge_calibration_v1.json"
    ),
    repeats: Annotated[int, typer.Option("--repeats", min=2)] = 3,
    model: Annotated[str, typer.Option("--model")] = "deepseek-v4-flash",
    timeout_seconds: Annotated[float, typer.Option("--timeout-seconds", min=0.1)] = 20,
) -> None:
    """Calibrate a live DeepSeek judge against completed human rubric labels."""

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise typer.BadParameter(
            "DEEPSEEK_API_KEY is missing; no judge calibration claim was generated."
        )
    project_root = root.resolve()
    dataset_path = dataset if dataset.is_absolute() else project_root / dataset
    provider = DeepSeekHTTPProvider(
        DeepSeekConfig(
            api_key=api_key,
            model=model,
            timeout_seconds=timeout_seconds,
        )
    )
    try:
        report = run_judge_calibration(dataset_path, provider, repeats=repeats)
    except HumanLabelsIncompleteError as exc:
        raise typer.BadParameter(str(exc)) from exc
    destination = output if output.is_absolute() else project_root / output
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    typer.echo(f"Wrote judge calibration report to {destination}")
    typer.echo(json.dumps(report["selection"], ensure_ascii=False, indent=2))


@app.command("check-regression-gate")
def check_regression_gate(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    profile: Annotated[Path, typer.Option("--profile")] = Path(
        "evals/baselines/e2e_planning_release_v1.json"
    ),
    candidate_audit: Annotated[Path, typer.Option("--candidate-audit")] = Path(
        "evals/results/stage6ab_evaluation_audit_v1.json"
    ),
    candidate_variant: Annotated[str, typer.Option("--candidate-variant")] = ("deterministic"),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Apply the immutable Stage 6D quality, safety, reliability, and cost gates."""

    project_root = root.resolve()
    report = run_regression_gate(
        project_root,
        profile_path=profile,
        candidate_audit_path=candidate_audit,
        candidate_variant=candidate_variant,
    )
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote regression gate report to {destination}")
    typer.echo(json.dumps({"status": report["status"], **report["summary"]}, indent=2))
    if not report["gate_passed"]:
        raise typer.Exit(code=1)


@app.command("eval-observability")
def eval_observability(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 7A trace correlation, redaction, and sink-outage drills."""

    project_root = root.resolve()
    report = run_observability_drill(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote observability drill report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-retrieval-resilience")
def eval_retrieval_resilience(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 7B circuit-open, cache-freshness, and half-open recovery drills."""

    project_root = root.resolve()
    report = run_retrieval_resilience_drill()
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote retrieval resilience report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-checkpointing")
def eval_checkpointing(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 7C logical-resume, idempotency, and checkpoint-outage drills."""

    project_root = root.resolve()
    report = run_checkpoint_idempotency_drill()
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote checkpoint/idempotency report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-durable-checkpointing")
def eval_durable_checkpointing(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 7C.2 cross-process SQLite checkpoint and receipt drills."""

    project_root = root.resolve()
    try:
        report = run_durable_checkpoint_drill()
    except ModuleNotFoundError as exc:
        raise typer.BadParameter(
            "SQLite checkpoint extra is missing; run ./scripts/bootstrap.sh --extra checkpoint"
        ) from exc
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote durable checkpoint report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-slo-outages")
def eval_slo_outages(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 7D synthetic SLO and multi-dependency outage gates."""

    project_root = root.resolve()
    report = run_slo_outage_drill(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote SLO/outage report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-index-publishing")
def eval_index_publishing(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 8A snapshot, atomic index publication, and rollback drills."""

    project_root = root.resolve()
    report = run_index_publish_drill()
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote index publication report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-source-fetching")
def eval_source_fetching(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 8B conditional fetch, retry, and freshness-policy drills."""

    project_root = root.resolve()
    report = run_source_fetch_drill()
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote source-fetch report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("eval-incremental-ingestion")
def eval_incremental_ingestion(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 8C typed parse, conflict, and incremental-index drills."""

    project_root = root.resolve()
    report = run_incremental_ingestion_drill()
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote incremental-ingestion report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))


@app.command("list-pdf-sources")
def list_pdf_sources(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
) -> None:
    """List governed official PDF sources without downloading them."""

    project_root = root.resolve()
    registry = load_pdf_source_registry(project_root / "data/sources/pdf_sources.json")
    payload = [
        {
            "source_id": source.source_id,
            "title": source.title,
            "authority": source.authority,
            "parser_profile": source.parser_profile,
            "content_scopes": source.content_scopes,
        }
        for source in registry.sources
    ]
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("fetch-pdf-source")
def fetch_pdf_source(
    source_id: str,
    root: Annotated[Path, typer.Option("--root")] = Path("."),
) -> None:
    """Safely fetch one official PDF into the ignored content-addressed snapshot store."""

    project_root = root.resolve()
    registry = load_pdf_source_registry(project_root / "data/sources/pdf_sources.json")
    try:
        source = registry.get(source_id)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    publisher = VersionedIndexPublisher(project_root / "data/raw/pdf-ingestion")
    downloader = PdfSourceDownloader(publisher, now=lambda: datetime.now(UTC))
    result = downloader.download(source)
    typer.echo(
        json.dumps(
            {
                "source_id": result.source_id,
                "content_sha256": result.payload.content_sha256,
                "byte_count": result.payload.byte_count,
                "pdf_version": result.payload.pdf_version,
                "fetch_mode": result.diagnostics.mode,
                "snapshot_path": (
                    f"data/raw/pdf-ingestion/snapshots/{result.snapshot.content_sha256}.raw"
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


@app.command("eval-pdf-ingestion")
def eval_pdf_ingestion(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Run Stage 10A official-PDF admission and snapshot drills."""

    project_root = root.resolve()
    report = run_pdf_ingestion_drill(project_root)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote PDF ingestion report to {destination}")
    typer.echo(json.dumps(report["metrics"], ensure_ascii=False, indent=2))
    if report["status"] != "passed":
        raise typer.Exit(code=1)


@app.command("release-audit")
def release_audit(
    root: Annotated[Path, typer.Option("--root")] = Path("."),
    manifest: Annotated[Path, typer.Option("--manifest")] = Path("release/travelmind-v3.json"),
    output: Annotated[Path | None, typer.Option("--output")] = None,
) -> None:
    """Verify pinned TravelMind evidence and selected/rejected component claims."""

    project_root = root.resolve()
    report = run_release_audit(project_root, manifest)
    serialized = json.dumps(report, ensure_ascii=False, indent=2)
    if output is not None:
        destination = output if output.is_absolute() else project_root / output
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"{serialized}\n", encoding="utf-8")
        typer.echo(f"Wrote release audit to {destination}")
    typer.echo(json.dumps({"status": report["status"], **report["summary"]}, indent=2))
    if report["status"] != "passed":
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
