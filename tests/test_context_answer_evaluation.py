from pathlib import Path

from travelmind.agentic.llm_provider import LLMUsage, StructuredLLMResult
from travelmind.evaluation.context_answer_runner import run_context_answer_ablation

ROOT = Path(__file__).resolve().parents[1]


class ReferenceFakeProvider:
    def complete_json(self, *, system_prompt: str, user_prompt: str, max_tokens: int):
        del system_prompt, max_tokens
        if "实时排队人数" in user_prompt:
            data = {"answer": "证据不足", "claims": [], "abstained": True}
        elif "从哪个门" in user_prompt:
            data = {
                "answer": "午门进入，神武门离开",
                "claims": [
                    {"text": "午门进入，神武门离开", "evidence_ids": ["palace-route-20260908"]}
                ],
                "abstained": False,
            }
        elif "普通门票和联票" in user_prompt:
            data = {
                "answer": "普通门票30元，联票60元",
                "claims": [
                    {
                        "text": "普通门票30元，联票60元",
                        "evidence_ids": ["summer-palace-ticket-20260908"],
                    }
                ],
                "abstained": False,
            }
        elif "周一去故宫" in user_prompt:
            data = {
                "answer": "周一闭馆，法定节假日除外",
                "claims": [
                    {
                        "text": "周一闭馆，法定节假日除外",
                        "evidence_ids": ["palace-opening-20260908"],
                    }
                ],
                "abstained": False,
            }
        elif "行动不便的父母" in user_prompt:
            data = {
                "answer": "什刹海免费、无需预约且有无障碍条件",
                "claims": [
                    {
                        "text": "什刹海免费、无需预约且有无障碍条件",
                        "evidence_ids": ["shichahai-access-20260908"],
                    }
                ],
                "abstained": False,
            }
        elif "计划周一去天坛" in user_prompt:
            data = {
                "answer": "祈年殿周一关闭，联票34元",
                "claims": [
                    {
                        "text": "祈年殿周一关闭，联票34元",
                        "evidence_ids": ["temple-heaven-hours-20260908"],
                    }
                ],
                "abstained": False,
            }
        elif "佛香阁" in user_prompt:
            data = {
                "answer": "佛香阁周一关闭",
                "claims": [
                    {"text": "佛香阁周一关闭", "evidence_ids": ["summer-palace-inner-20260908"]}
                ],
                "abstained": False,
            }
        else:
            data = {
                "answer": "祈年殿周一关闭，联票34元",
                "claims": [
                    {
                        "text": "祈年殿周一关闭，联票34元",
                        "evidence_ids": ["temple-heaven-hours-20260908"],
                    }
                ],
                "abstained": False,
            }
        prompt_tokens = len(user_prompt)
        return StructuredLLMResult(
            data=data,
            model="fake",
            usage=LLMUsage(
                prompt_tokens=prompt_tokens, completion_tokens=20, total_tokens=prompt_tokens + 20
            ),
            latency_ms=1,
            provider_attempts=1,
        )


def test_answer_ablation_contract_selects_smaller_context_without_quality_loss() -> None:
    report = run_context_answer_ablation(ROOT, ReferenceFakeProvider())

    assert report["selection"]["gate_passed"] is True
    assert report["metrics"]["unbounded"]["task_success_rate"] == 1
    assert report["metrics"]["refined_coverage"]["task_success_rate"] == 1
    assert (
        report["metrics"]["refined_coverage"]["total_tokens"]
        < report["metrics"]["unbounded"]["total_tokens"]
    )
