from travelmind.agentic.llm_policies import LLMQueryRouter
from travelmind.agentic.policies import CoverageEvidenceGrader, MissingAspectQueryRewriter
from travelmind.agentic.stack import build_selected_deepseek_stack


def test_selected_stack_uses_only_the_component_that_passed_gate() -> None:
    stack = build_selected_deepseek_stack(api_key="test-key")

    assert isinstance(stack.router, LLMQueryRouter)
    assert isinstance(stack.grader, CoverageEvidenceGrader)
    assert isinstance(stack.rewriter, MissingAspectQueryRewriter)
    assert "test-key" not in repr(stack)
