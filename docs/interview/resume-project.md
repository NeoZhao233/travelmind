# TravelMind resume project entry

## Recommended Chinese version

### TravelMind：评测驱动的旅游规划 Agent Harness

**技术栈：** Python / LangGraph / MCP / Pydantic / BM25 / BGE / Qdrant / RRF / DeepSeek / Redis / SQLite / Pytest

- 基于 LangGraph 构建带类型状态的旅游规划工作流，串联意图路由、混合检索、证据评估、
  有界 Query Rewrite、上下文构建、行程生成、硬约束校验与局部修复；通过状态内重试预算
  阻止无限循环，并用 Checkpoint 与幂等收据避免恢复过程重复执行 Planner。
- 实现显式 Plan—Act—Observe—Replan 运行时，将版本化计划、工具依赖与执行反馈写入状态；
  构建覆盖 4 个工具位置、6 类故障模式的 34 场景注入矩阵，验证瞬时重试、失败后仅替换
  未完成步骤、成功 Observation 复用，以及主备路径均失效时安全停止。
- 抽象 Harness 所有的 Tool Policy 与 Allowlist，通过官方 MCP v2 SDK 暴露检索、可用性、
  预约规则和交通时间工具；6 项故障契约覆盖协议调用、只读传输降级、业务错误可见性、
  Redis Cache 失效绕过及双路径失效安全停止。
- 实现 BM25 与 BGE 中文向量检索并以 RRF 融合；构建 105 条 Query、35 个意图簇的分层
  自建合成评测集，Hybrid Recall@5 为 0.971；Cross-Encoder 降至 0.958 且平均本地延迟
  由 2.82 ms 增至 216.30 ms，因此保留适配器但不进入默认链路。
- 设计 768-token、覆盖率感知且保留来源的上下文流水线；在 7 个真实 DeepSeek A/B
  样例中任务完成、引用和拒答指标均为 1.000，总 Token 相比对照组降低 45.3%。
- 建立从组件 A/B 到冻结回归门禁的评测闭环；实测 DeepSeek Planner 多消耗 4,475
  Token 但目标地点命中率零提升，因而保留确定性 Planner，并将不稳定的 LLM-as-Judge v1
  排除在发布决策之外。
- 实现超时、熔断、分级缓存、安全失败、脱敏遥测、SQLite 持久化恢复以及版本化索引原子
  发布，并实现可选 Redis TTL Cache 与 LangGraph Checkpoint Adapter；复合故障演练中可
  恢复请求完成、双检索失效时安全失败且 Canary 泄漏率为 0，最终
  使用 29 份哈希固定证据与 62 项自动审计约束项目声明。

## Compact version for a one-page resume

### TravelMind：基于 LangGraph 的旅游规划 Agent Harness

**技术栈：** Python / LangGraph / MCP / Hybrid RAG / Qdrant / BGE / DeepSeek / Redis / SQLite

- 设计 Router—Hybrid RAG—证据评估—有界改写—约束规划—校验/局部修复状态图，并以
  Checkpoint、幂等收据和确定性降级保证可恢复执行。
- 增加版本化 Plan—Act—Observe—Replan 运行时，以 34 场景故障矩阵验证瞬时重试、
  Observation 复用、有界重规划及双路径失败时的安全停止。
- 将 4 类旅游工具封装为官方 MCP 结构化接口，以 Harness Allowlist、只读降级、TTL Cache
  和可选 Redis/SQLite Checkpoint 控制权限与状态；6 项 MCP/缓存故障契约全部通过。
- 构建 105 Query/35 意图簇的自建合成检索集；Hybrid Recall@5 为 0.971，并拒绝使其降至
  0.958、平均延迟升至 216.30 ms 的 Cross-Encoder，以及质量零提升的 LLM Planner。
- 构建 768-token 来源保留型上下文流水线，7 例真实 DeepSeek A/B 中关键质量指标为
  1.000、Token 降低 45.3%；以冻结回归门禁、复合故障演练和 62 项发布审计约束声明。

## Claim-to-evidence map

| Resume claim | Evidence | Required qualifier |
| --- | --- | --- |
| Draft Recall@5 0.971 | `hybrid_benchmark_v2_draft.json` | 105 queries/35 Codex-authored intent clusters; not human-reviewed |
| Reranker reduced Recall@5 to 0.958 | `reranked_benchmark_v2_draft.json` | same draft labels; local latency only |
| Context quality 1.000 and tokens -45.3% | `stage4_deepseek_answer_ablation_v4_final.json` | seven real DeepSeek cases |
| Planner added 4,475 tokens with zero lift | `e2e_planning_deepseek_ab_v3_final.json` | five-case repeated real A/B |
| 34 runtime fault contracts passed | `runtime_failure_matrix_v2_draft.json` | project-authored fixture matrix, not production reliability |
| Six Harness/MCP/cache checks passed | `stage13_harness_v1.json` | official in-process MCP; Redis outage is injected, not a live cluster |
| Admission test balanced accuracy 0.878 | `answerability_admission_v2_draft.json` | development-tuned; blocked pending human review |
| Runtime DeepSeek candidate rejected | `stage11_deepseek_runtime_v3_final.json` | seven calls; zero lift, 42.9% normalized |
| Judge rejected | `stage6c_deepseek_judge_reference_v1.json` | AI-assisted reference labels, not human calibration |
| Durable resume made zero repeated Planner calls | `stage7c2_durable_checkpoint_v1.json` | four local independent processes |
| Composite outage passed and leaked no canary | `stage7d_slo_outage_v1.json` | seven synthetic checks, not a production SLO |
| Release audit 62/62 | `release_v3_audit.json` | 29 pinned files plus 33 semantic checks; not model quality itself |

## Statements to avoid

- Do not write “production-grade” or “high availability”; the SLO evidence is synthetic and local.
- Do not write “human-calibrated LLM Judge”; Judge v1 used AI-assisted reference labels and failed.
- Do not claim the Agentic loop improved end-to-end answer quality; it improved controlled recovery
  behavior, while the DeepSeek runtime candidate showed no contract lift.
- Do not claim the reranker or DeepSeek Planner was deployed as the default; both were rejected.
- Do not write “exactly once”; checkpoints recover control state while idempotency receipts reduce
  duplicate side effects.
- Do not present 1.000 on seven cases as 100% production accuracy.
- Always call Stage 12 a project-authored synthetic evaluation set; it is not a human-reviewed or
  external benchmark.
- Do not claim Redis cluster recovery or throughput; the live local Redis lifecycle probe is not yet
  committed.

## Tailoring guidance

- For an **Agent/RAG internship**, keep the retrieval, context, model-selection, and evaluation bullets.
- For an **AI engineering/backend internship**, keep the state machine, typed contracts, recovery,
  index publication, and release-audit bullets.
- Keep three or four bullets on a one-page resume. Preserve the full version as the source of truth
  for interview preparation.
