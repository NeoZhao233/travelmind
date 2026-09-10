# TravelMind interview narrative

## One-sentence positioning

TravelMind 不是把大模型套在旅游问答外面，而是一个评测驱动、证据受约束、发生依赖故障时
能够明确降级或安全失败的旅游规划 Agent。

## 30-second version

我做了一个基于 LangGraph 的旅游规划 Agent，重点不是前端，而是 Agentic RAG、上下文工程、
约束规划和评测闭环。Agent 用显式计划逐步调用工具，遇到中途失败会依据观察修改后续步骤；
34 个受控案例覆盖 4 个工具位置和 6 类故障。检索使用 BM25+BGE+RRF，并构建了 105 条
Query、35 个意图簇的分层评测草案；扩集后 Reranker 仍降低 Recall 并显著增加延迟。
这些新标签还没有人工复核，所以新质量数字不会直接升级为正式简历声明。
工程上还实现了有界重试、Checkpoint、幂等、熔断缓存、索引原子发布和安全失败。

## 2-minute version

这个项目解决的问题是：旅游规划不是生成一段听起来合理的文字，而是要基于可追溯的信息，
同时满足预算、时间、开放状态、预约和地点偏好等约束；当模型或检索失败时，也不能编造行程。

我用 LangGraph 搭了显式状态机。请求先经过 Router，再进入 BM25+BGE 的 Hybrid RAG；证据
不足时只在预算内改写和重试，足够时进入来源保留型上下文构建。Planner 产生结构化行程后，
代码重新计算费用、冲突、开放时间和必要地点等硬约束，只修复受影响的日期，超过修复预算就
安全失败。选择 LangGraph 的原因是这里确实需要分支、有界循环、状态恢复和可观察轨迹，而不
只是顺序调用几个 Prompt。

为了补足真正的 Agentic 执行，我又把计划建模为版本化数据。Runtime 每次只执行一个工具动作，
将成功或失败写成不可变 Observation；瞬时错误重试，策略被破坏时只替换未完成步骤，并复用
已经成功的检索结果。34 个故障案例覆盖瞬时重试、重试耗尽、Schema 错误、证据不足以及
备用路径再次故障，全部满足精确状态、Replan 次数、Tool Call 数和最终地点契约。这个结果
证明的是受控的路径覆盖，不是线上 API 可用性。

项目的另一个重点是评测驱动选择。扩展草案包含 105 条 Query、35 个独立意图簇和 30 条
无答案问题。Hybrid RRF 的 Recall@5 为 0.971，Cross-Encoder 降到 0.958，平均本地延迟从
2.82 ms 增至 216.30 ms，因此继续不进入默认链路。扩集还暴露原始排序器拒答准确率为 0，
所以我把排序与证据准入拆开；开发集调参的 Gate 在测试集达到 0.800 拒答准确率，但因为标签
还没有人工复核，候选仍被阻止晋升。上下文方面，选出的 768-token pipeline 在
7 例真实 DeepSeek A/B 中关键质量指标保持 1.000，同时 Token 下降 45.3%。DeepSeek Planner
多用了 4,475 Token 但目标地点命中没有提升，所以默认仍采用可解释的确定性 Planner。

最后我补了工程兜底：超时、熔断、缓存新鲜度、安全失败、脱敏 Trace、持久化 Checkpoint、
幂等收据，以及数据快照、隔离构建、原子切换和回滚。项目不会把降级成功算成健康成功，也不
会把小样本结果称为生产指标。最终由 v2 发布清单固定旧版证据与新增 Agentic Runtime 证据，
并自动校验哈希和语义声明。

## 5-minute version

### 1. Problem and success definition — 40 seconds

传统旅游问答很容易生成流畅但不可执行的路线。我的成功标准拆成四层：检索能找到正确证据；
上下文在预算内保留必要事实和来源；规划结果满足硬约束；发生依赖故障时能够被观察、降级或
安全失败。这样每一层都能单独评测，避免只凭最终回答的主观观感判断系统。

### 2. Agent control plane — 55 seconds

主流程是 Router、Query 构造、Hybrid Retrieval、Evidence Grader、Context Builder、Planner、
Validator 和 Local Repair。证据不足可以回到 Query Rewrite，但次数写在类型化状态里；校验
失败只修受影响日期，同样有预算。LangGraph 提供显式节点、条件边和 Checkpoint 接口。这里
特别要区分：Checkpoint 保存控制流状态，幂等收据保护可能重复执行的 Planner 或外部操作，
二者解决的问题不同，因此我不声称 exactly-once。

Stage 11 进一步增加独立的 Plan—Act—Observe—Replan Runtime：计划有稳定 ID 和递增版本，
每次只执行一个类型化工具步骤，再根据 Observation 决定继续、重试、重规划或安全停止。成功
Observation 跨版本保留，失败 Observation 不会变成行程证据；工具调用、重规划和单步尝试均
有独立上限，因此模型无法制造无限循环。

### 3. Retrieval and context experiments — 65 seconds

检索层用 BM25 补精确实体和规则词，BGE 向量补语义表达，再以 RRF 融合，避免直接校准两种
不可比分数。扩展草案将 105 条 Query 聚合为 35 个意图簇，按意图隔离 development/test，
并加入 30 条无答案问题。Hybrid Recall@5 为 0.971，按意图簇 Bootstrap 的区间是
[0.920, 1.000]；Cross-Encoder 降到 0.958 且延迟大幅上升，因此没有因为它“更高级”就上线。
这里我会主动说明标签由 Codex 草拟且未人工复核，区间解决不了标签有效性问题。

上下文不是简单拼接 top-k。我做了 Token 预算、约束覆盖、去重、冲突处理、抽取式压缩和来源
保留，选出 768-token 的 refined-coverage 方案。7 个真实 DeepSeek A/B 样例中，任务、引用
和拒答指标为 1.000，总 Token 比对照组少 45.3%。这里我会主动说明样本很小，只能证明本项目
的 pipeline 决策，不代表通用准确率。

### 4. Planning and evaluation decisions — 55 seconds

Planner 不是让 LLM 随意生成。确定性候选构造会考虑开放窗口、预约、预算、节奏、换乘 buffer
和带来源的旅行时间；生成后由 Validator 重新计算。真实 DeepSeek 排序 A/B 中，模型多消耗
4,475 Token 和约 877ms 每次调用，但目标地点命中率没有提升，所以冻结门禁选择确定性方案。

我也尝试了 LLM-as-Judge。虽然 21 次调用全部结构合法且无 fallback，但重复一致性和 Kappa
未通过门禁，加上标签只是 AI 辅助参考，所以 Judge v1 被标为 reference-only，不能参与发布
决策。这是项目中很重要的负结果：能调用模型不等于测量有效。

### 5. Failure handling and release — 65 seconds

运行时对检索依赖加入超时、熔断和分级缓存；动态信息过期时失败关闭，只有明确静态信息可在
有限窗口内使用陈旧缓存。遥测采用字段 allowlist 和 Canary 检查，监控后端失效不会拖垮业务。
复合故障演练中，单路可恢复故障通过确定性路径完成；BM25 和向量检索同时失效时不返回无证据
行程，而是安全失败，Canary 泄漏为零。

数据侧使用内容寻址快照、Parser quarantine、冲突策略、增量重算、隔离索引构建与原子指针
切换，坏版本不能污染当前服务版本。SQLite 实验用四个独立进程验证恢复和收据重放时 Planner
重复调用为零，但我不会把它包装成分布式数据库结论。

最后我建立 v2 发布清单，将 21 份关键代码锁、架构决策和实验报告做 SHA-256 固定，再验证
25 项语义声明，共 46 项审计全部通过。这保证我面试里说的每个数字都能落到版本化证据上。

## Intentional interview hooks

讲述时可以主动留下以下追问入口，而不是一次讲完所有实现：

- “Reranker 为什么会让指标下降？”用于进入候选集、领域错配和 top-k 排序目标。
- “为什么选 LangGraph？”用于进入分支、有界循环、Checkpoint 和状态可观察性。
- “Checkpoint 是否保证 exactly-once？”用于展示幂等和分布式语义边界。
- “为什么不用 LLM Planner？”用于展示增量价值门禁和成本意识。
- “模型都失效怎么办？”用于展示分层 fallback 和安全失败原则。
- “这些指标可信吗？”用于主动说明数据规模、标签来源和 Judge 拒绝结果。

## Answer pattern for deep follow-ups

每个深入问题按同一个结构回答：

1. **问题：** 该组件具体解决什么失败模式。
2. **选择：** 为什么采用当前实现，而不是候选方案。
3. **证据：** 对应数据集、指标、消融或故障注入结果。
4. **边界：** 当前实验不能证明什么。
5. **生产演进：** 数据量、基础设施或观测窗口扩大后如何升级。

例如回答“为什么不默认使用 Reranker”：目标是改善 Hybrid 候选的 top-k 顺序；但扩集消融
中 Recall@5 从 0.971 降到 0.958，平均本地延迟从 2.82 ms 增到 216.30 ms，因此拒绝。可能
原因包括通用模型领域错配、
候选规模小和 pointwise 相关性与最终覆盖目标不一致。生产演进应先扩充独立标注和 hard negative，
再尝试领域微调或约束感知 loss，而不是直接把模型接回默认链路。
