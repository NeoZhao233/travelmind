# TravelMind resume project entry

## Recommended Chinese version

### TravelMind：评测驱动的旅游规划 Agent

**技术栈：** Python / LangGraph / Pydantic / BM25 / BGE / Qdrant / RRF / DeepSeek / SQLite / Pytest

- 基于 LangGraph 构建带类型状态的旅游规划工作流，串联意图路由、混合检索、证据评估、
  有界 Query Rewrite、上下文构建、行程生成、硬约束校验与局部修复；通过状态内重试预算
  阻止无限循环，并用 Checkpoint 与幂等收据避免恢复过程重复执行 Planner。
- 实现显式 Plan—Act—Observe—Replan 运行时，将版本化计划、工具依赖与执行反馈写入状态；
  在 4 个受控多步案例中，可恢复的中途失败恢复率由固定计划的 0% 提升至 100%，且重规划
  复用已完成检索、不可恢复场景安全停止。
- 实现 BM25 与 BGE 中文向量检索并以 RRF 融合，在 15 条种子 Query 上取得
  Recall@5 / MRR@5 / NDCG@5 = 0.956 / 0.956 / 0.933；通过固定候选集消融发现
  Cross-Encoder 使 Recall@5 降至 0.900，因此将其保留为可选适配器而非默认链路。
- 设计 768-token、覆盖率感知且保留来源的上下文流水线；在 7 个真实 DeepSeek A/B
  样例中任务完成、引用和拒答指标均为 1.000，总 Token 相比对照组降低 45.3%。
- 建立从组件 A/B 到冻结回归门禁的评测闭环；实测 DeepSeek Planner 多消耗 4,475
  Token 但目标地点命中率零提升，因而保留确定性 Planner，并将不稳定的 LLM-as-Judge v1
  排除在发布决策之外。
- 实现超时、熔断、分级缓存、安全失败、脱敏遥测、SQLite 持久化恢复以及版本化索引原子
  发布；复合故障演练中可恢复请求完成、双检索失效时安全失败且 Canary 泄漏率为 0，最终
  使用 21 份哈希固定证据与 46 项自动审计约束项目声明。

## Compact version for a one-page resume

### TravelMind：基于 LangGraph 的评测驱动旅游规划 Agent

**技术栈：** Python / LangGraph / Hybrid RAG / Qdrant / BGE / DeepSeek / Pydantic / SQLite

- 设计 Router—Hybrid RAG—证据评估—有界改写—约束规划—校验/局部修复状态图，并以
  Checkpoint、幂等收据和确定性降级保证可恢复执行。
- 增加版本化 Plan—Act—Observe—Replan 运行时；4 个受控案例中可恢复中途故障恢复率
  从 0% 提升至 100%，复用成功观察并在双路径失败时安全停止。
- BM25+BGE+RRF 在 15 条种子集达到 Recall@5 0.956；通过消融拒绝使 Recall@5 降至
  0.900 的 Cross-Encoder，并拒绝多消耗 4,475 Token 但质量零提升的 LLM Planner。
- 构建 768-token 来源保留型上下文流水线，7 例真实 DeepSeek A/B 中关键质量指标为
  1.000、Token 降低 45.3%；以冻结回归门禁、复合故障演练和 46 项发布审计约束声明。

## Claim-to-evidence map

| Resume claim | Evidence | Required qualifier |
| --- | --- | --- |
| Recall@5 0.956 | `hybrid_rrf_seed.json` | 15-query seed, not a production benchmark |
| Reranker reduced Recall@5 to 0.900 | `hybrid_bge_reranker_base_seed.json` | fixed Hybrid candidate ablation |
| Context quality 1.000 and tokens -45.3% | `stage4_deepseek_answer_ablation_v4_final.json` | seven real DeepSeek cases |
| Planner added 4,475 tokens with zero lift | `e2e_planning_deepseek_ab_v3_final.json` | five-case repeated real A/B |
| Intermediate-failure recovery 0% to 100% | `stage11_runtime_multistep_v1.json` | four project-authored fixture cases |
| Runtime DeepSeek candidate rejected | `stage11_deepseek_runtime_v3_final.json` | seven calls; zero lift, 42.9% normalized |
| Judge rejected | `stage6c_deepseek_judge_reference_v1.json` | AI-assisted reference labels, not human calibration |
| Durable resume made zero repeated Planner calls | `stage7c2_durable_checkpoint_v1.json` | four local independent processes |
| Composite outage passed and leaked no canary | `stage7d_slo_outage_v1.json` | seven synthetic checks, not a production SLO |
| Release audit 46/46 | `release_v2_audit.json` | 21 pinned files plus 25 semantic checks; not model quality itself |

## Statements to avoid

- Do not write “production-grade” or “high availability”; the SLO evidence is synthetic and local.
- Do not write “human-calibrated LLM Judge”; Judge v1 used AI-assisted reference labels and failed.
- Do not claim the Agentic loop improved end-to-end answer quality; it improved controlled recovery
  behavior, while the DeepSeek runtime candidate showed no contract lift.
- Do not claim the reranker or DeepSeek Planner was deployed as the default; both were rejected.
- Do not write “exactly once”; checkpoints recover control state while idempotency receipts reduce
  duplicate side effects.
- Do not present 1.000 on seven cases as 100% production accuracy.

## Tailoring guidance

- For an **Agent/RAG internship**, keep the retrieval, context, model-selection, and evaluation bullets.
- For an **AI engineering/backend internship**, keep the state machine, typed contracts, recovery,
  index publication, and release-audit bullets.
- Keep three or four bullets on a one-page resume. Preserve the full version as the source of truth
  for interview preparation.
