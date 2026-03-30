# M2 设计备忘录：基于 3639315 论文与本地 M1/M3 数据的综合结论

状态：正式设计备忘录  
依据：
- 论文 [3639315.pdf](/home/ranmaoyin/graph_query/Fastest-par/3639315.pdf)
- 本地分析产物 [analysis/m1_m3_analysis.ipynb](/home/ranmaoyin/graph_query/Fastest-par/analysis/m1_m3_analysis.ipynb)
- 本地分析产物 [analysis/processed](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed)

## 1. 目的

本文档用于回答一个具体设计问题：

`M2` 到底应该学习什么，如何定义训练样本、标签、目标引擎和评估指标，才能和论文结论一致，同时又符合当前仓库的真实数据形态。

结论先行：

- `M2` 不应被设计成“挑选一个对所有 engine 都最好的通用 sequence”。
- `M2` 应被设计成“在给定 query 图、数据集以及目标 engine 条件下，从 M1 候选池中选出条件最优 sequence 的 reranker”。
- 当前第一阶段应优先服务稳定引擎，避免把 `VF3` 这类高崩溃率引擎混入主训练目标。
- 训练目标不应仅仅是绝对时间回归，至少要同时支持 ranking 目标，并补充 `EPS` 视角的评估。

## 2. 论文给出的关键结论

### 2.1 枚举阶段主导整体性能

论文明确指出，经典的子图匹配框架仍然是 `filtering-ordering-enumerating`，但最近几年真正的性能提升主要来自枚举阶段对回溯框架的增强，而不是单独优化过滤或顺序本身。

论文原文结论可概括为：

- 回溯阶段主导总成本。
- `RM`、`KSS`、`VEQ` 等增强枚举技术通常优于传统枚举技术。
- 单独讨论过滤或顺序不够，因为最终性能取决于它们如何与枚举技术耦合。

这意味着当前系统中的 `M1` 只能提供候选空间，真正决定 winner sequence 是否有价值的，是该 sequence 在 `M3` 的目标引擎下如何被利用。

### 2.2 输出限制会改变算法排名，EPS 更稳

论文第 4.5 节说明：固定输出上限会显著改变算法排名，因此单纯比较“在某个输出限制下的耗时”存在偏置。论文因此引入 `EPS` 指标，即每秒返回的 embedding 数，用于更稳健地评价性能。

对本仓库而言，这一结论意味着：

- 仅以 `enum_time` 训练或评估 `M2` 是可行的，但并不完整。
- 如果未来需要与论文结论对齐，或者目标是“更高吞吐”而不只是“更短总时间”，则必须并行保留 `EPS` 视角。

### 2.3 组合之间存在强交互

论文第 4.6 到 4.9 节最重要的发现是：`filter`、`order`、`enumeration` 三个阶段之间存在强交互，某个技术并不会在所有上下文中都最好。

直接影响：

- 不能把 sequence 视为完全脱离上下文的全局最优对象。
- 不能期望一个不带 engine 条件的模型，稳定选出对所有 engine 都最好的 sequence。
- 评估某个 sequence 是否优秀，必须至少绑定目标 engine。

## 3. 本地 M1 数据的真实形态

来自 [analysis/processed/m1_all.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/m1_all.parquet) 的统计表明，当前 `M1` 不是“高多样性生成器”，而是“高冗余候选发现器”。

关键统计如下：

- `M1` 总行数：`4,603,300`
- 每个 `(dataset, query_file)` 的 `distinct_filter_order` 中位数：`81`
- 每个 `(dataset, query_file)` 的 `unique_sequences` 中位数：`15`
- `unique_sequences` 的四分位区间：`7-27`
- `duplicated_fraction` 中位数：`0.647`
- `unique_fraction` 中位数：`0.353`
- `max_method_overlap` 中位数：`16`

这些数字来自：

- [analysis/processed/m1_filter_order_coverage.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/m1_filter_order_coverage.parquet)
- [analysis/processed/m1_sequence_diversity.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/m1_sequence_diversity.parquet)

这说明两件事：

1. `M2` 面对的不是超大候选集，而是一个典型规模在十几条 sequence 的 rerank 问题。
2. 训练时必须按 `sequence` 去重，不能直接把每一条 `M1` 记录当成独立样本，否则会把方法生成偏好误当成 sequence 质量。

## 4. 本地 M3 数据的真实形态

### 4.1 标签规模与删失

来自 [analysis/processed/m3_all.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/m3_all.parquet) 与 [analysis/processed/m3_ok.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/m3_ok.parquet)：

- `M3` 总行数：`3,292,604`
- `OK` 行数：`1,128,422`

按数据集的 `OK` 比例如下：

- `dblp`: `0.763`
- `human`: `0.589`
- `yeast`: `0.495`
- `youtube`: `0.477`
- `patents`: `0.439`
- `eu2005`: `0.424`
- `wordnet`: `0.282`
- `hprd`: `0.239`

这意味着 `M3` 不是一个完整无偏标签集，而是带明显删失的监督集。失败不是随机噪声，而与数据集、engine、query 难度、sequence 本身都有关。

### 4.2 引擎稳定性差异很大

来自 [analysis/processed/failure_average.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/failure_average.parquet)：

- `VF3` 平均失败率 `100%`
- `GQL` 平均失败率 `42.2%`
- `RM` 平均失败率 `40.6%`
- `KSS` 平均失败率 `31.8%`
- `QSI` 平均失败率 `29.3%`
- `LFTJ` 平均失败率 `29.2%`
- `EXPLORE` 平均失败率 `27.3%`

结合论文结论，这里的信号是清晰的：

- `VF3` 不应进入 M2 主训练目标。
- `RM/KSS` 吞吐可能很强，但稳定性弱于 `EXPLORE/LFTJ/QSI`。
- 若当前阶段目标是得到一个可落地、鲁棒的 `M2`，第一阶段主评估引擎应优先选择稳定引擎。

## 5. Sequence 是否 engine-dependent

答案是：明显依赖。

来自 [analysis/processed/universal_best_sequences.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/universal_best_sequences.parquet) 与 [analysis/processed/rank_correlations.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/rank_correlations.parquet)：

- 只有 `9.32%` 的 query 具有跨引擎一致的唯一最佳 sequence
- `distinct_best_sequences` 中位数为 `3`
- 跨引擎 sequence 排名的 Spearman 相关系数中位数约为 `0.60`
- 四分位区间约为 `0.259 - 0.817`

这和论文“interaction effect is significant”的结论高度一致，也直接否定了“训练一个全局通用 sequence scorer 就够了”的想法。

因此，`M2` 至少要满足下面二选一：

1. 为每个目标 engine 单独训练一个 scorer。
2. 训练一个共享模型，但把 `engine` 显式作为条件输入。

如果不这么做，模型会在训练时被互相冲突的监督信号拉扯，导致 top-1 选择不稳定。

## 6. Sequence 选择到底值不值得学

值得，但目标应是“规避坏序列”，而不是执着于绝对值回归。

来自 [analysis/processed/sequence_quality.parquet](/home/ranmaoyin/graph_query/Fastest-par/analysis/processed/sequence_quality.parquet)：

- `median_to_best_ratio` 中位数：`1.033`
- `median_to_best_ratio` 的 75 分位：`1.437`
- `median_to_best_ratio` 的 90 分位：`2.000`
- `worst_to_best_ratio` 中位数：`2.000`
- `worst_to_best_ratio` 的 90 分位：`24.98`

解释如下：

- 很多 query 上，随机挑一个中位水平的 sequence，未必比最佳 sequence 慢很多。
- 但一旦挑到坏 sequence，代价可以非常高。

因此，`M2` 最应该优化的是：

- 把明显差的 sequence 压到后面；
- 保证最佳或近最佳 sequence 稳定进入 top-k；
- 不需要强求精确恢复所有 sequence 的全序关系。

这更像是一个 ranking / reranking 问题，而不是高精度回归问题。

## 7. 当前 M2 的正确问题定义

结合论文与本地数据，推荐将 `M2` 的问题定义更新为：

> 给定 `(dataset, query_graph, target_engine)`，从 `M1` 去重后的 sequence 候选集中，选择一个在 `M3` 中最可能实现最低运行代价或最高吞吐的 sequence。

进一步拆解：

- 输入主键应是 `sequence`，而不是 `filter-order` 组合。
- 目标应是 engine-aware，而不是 engine-agnostic。
- 训练目标应以 ranking 为主，回归为辅。

## 8. 对模型输入的具体要求

### 8.1 必须保留的特征

1. 查询图特征
   - `query_vertices`
   - `query_edges`
   - `density`
   - 其他图结构特征

2. Sequence 本身的结构特征
   - 顶点顺序
   - 前缀子图拓扑
   - 前缀基数估计值

3. 目标 engine
   - 作为显式条件输入

4. 可选上下文
   - 数据集 ID
   - 候选集统计

### 8.2 不应作为主学习对象的字段

- `filter`
- `order`

它们可以保留用于分析、ablation 或 side feature，但不应主导模型。原因是它们在 `M1` 中高度冗余，且真正的优化对象是去重后的 sequence。

## 9. 标签设计建议

### 9.1 第一阶段主标签

推荐同时维护两套标签：

1. `enum_time` 标签
   - 适合“选出完成时间最短 sequence”的部署目标
2. `EPS` 标签
   - 适合与论文对齐，避免被固定输出规模偏置误导

### 9.2 训练目标建议

优先级建议如下：

1. `LambdaMART` / pairwise ranking
2. top-k 命中率优化
3. 辅助回归 `log(enum_time)` 或 `log(EPS)`

原因是：

- 当前候选集规模较小，天然适合 learning-to-rank。
- 我们更在意“winner 是否正确”，而不是所有 sequence 的绝对值预测误差。

## 10. 引擎范围建议

### 10.1 第一阶段主评估引擎

推荐：

- `EXPLORE`
- `LFTJ`
- `QSI`

原因：

- 这是当前最稳定的三个引擎。
- 它们代表了较稳健的基线执行行为。
- 用它们训练出的 `M2` 更容易解释，也更容易排除失败噪声。

### 10.2 第二阶段扩展引擎

可以逐步加入：

- `RM`
- `KSS`

原因：

- 它们经常是最快赢家。
- 但失败率明显更高，直接混入主训练集会污染监督信号。

### 10.3 明确排除

当前阶段应排除：

- `VF3`

原因：

- 在本地数据中几乎完全失效。

## 11. 评估协议建议

### 11.1 训练集构造

- 仅使用 `status = OK` 的记录做性能标签。
- 对 `M1` 先按 `(dataset, query_file, sequence)` 去重。
- 再按 `(dataset, query_file, sequence, engine)` 与 `M3` 关联。

### 11.2 主指标

- Top-1 accuracy
- Top-3 accuracy
- Regret
- NDCG / pairwise agreement

### 11.3 辅助指标

- `enum_time` 视角
- `EPS` 视角
- 跨数据集泛化
- 跨 engine 泛化

## 12. 当前阶段最稳的工程结论

1. `M2` 不要建成一个“全局通用 winner 预测器”，而要建成“目标 engine 条件下的 sequence reranker”。
2. `M1` 训练前必须 sequence 去重，否则样本权重会被重复生成偏置污染。
3. 第一阶段只在稳定引擎上建立主模型，避免失败噪声。
4. 训练目标优先做 ranking，而不是绝对时间回归。
5. 评估指标必须同时保留 `enum_time` 与 `EPS` 两个口径。
6. `RM/KSS` 的高性能值得在第二阶段单独建模，但不要和鲁棒基线混为一谈。

## 13. 对现有文档的关系

本备忘录不替代以下文档，而是对其做约束和修正：

- [docs/m2_model_design.md](/home/ranmaoyin/graph_query/Fastest-par/docs/m2_model_design.md)
- [docs/m2_model_analysis.md](/home/ranmaoyin/graph_query/Fastest-par/docs/m2_model_analysis.md)
- [docs/m1_m2_m3_system_partition.md](/home/ranmaoyin/graph_query/Fastest-par/docs/m1_m2_m3_system_partition.md)

其中最需要修正的一点是：

之前的表述容易把 `M2` 理解成“对所有 sequence 做统一评分并选一个全局 best order”。根据论文与本地数据，这个表述应改为“对给定目标 engine 的 sequence 候选做条件评分并选 winner”。

## 14. 下一步实现建议

1. 在训练数据构建阶段，新增 `engine` 条件列，并显式生成 `(query, sequence, engine)` 级别样本。
2. 先用 `EXPLORE/LFTJ/QSI` 构造稳定标签集，训练第一版 `M2`。
3. 在评估脚本中同时输出 `enum_time` 与 `EPS` 两套 Top-1/Top-3/Regret。
4. 将 `RM/KSS` 单独做二阶段扩展实验，判断是否值得为高性能但低稳定性的引擎训练专属模型。
