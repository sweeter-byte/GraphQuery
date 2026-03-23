# M2 模型选型分析报告

> 基于 `docs/m2_model_design.md` 及现有代码的综合分析

## 1. 推荐模型：LightGBM + LambdaMART

### 1.1 选型理由

| 维度 | 分析 |
|------|------|
| **问题本质** | Learning to Rank，从 50-80 个候选序列选最优，不需预测绝对值 |
| **推理约束** | 当前 `score_aggregator.py` 打分在 μs 级，80 次 LightGBM 推理 < 1ms，完全满足 < 10ms 预算 |
| **数据量** | 千到万级样本（dataset × query × sequence），正是 GBDT 甜区，神经网络易过拟合 |
| **可解释性** | feature importance 可直接验证 §2.3 的特征重要性预期 |
| **开发成本** | LightGBM 原生支持 `lambdarank`，无需自定义损失函数 |

### 1.2 不推荐序列模型（CNN/LSTM）的原因

- 序列长度仅 4-32，统计聚合 + 前 K 位置特征已能捕获关键模式
- 推理开销在毫秒级，80 个序列可能接近 10ms 预算上限
- 调参复杂度高，在当前数据量下收益不确定

---

## 2. 训练方案

### 2.1 特征工程（渐进式）

#### V1 聚合特征（方案 B）— ~15 维

从原始基数估计序列 `[ĉ₁, ĉ₂, ..., ĉₙ]` 提取：

```python
features = {
    # 基本统计
    "sum": sum(c_hats),
    "mean": np.mean(c_hats),
    "std": np.std(c_hats),
    "max": max(c_hats),
    "min": min(c_hats),
    "first": c_hats[0],
    "last": c_hats[-1],

    # 位置相关
    "first_3_mean": np.mean(c_hats[:3]),
    "last_3_mean": np.mean(c_hats[-3:]),

    # 趋势特征
    "increasing_ratio": (相邻递增比例),
    "max_jump": (最大相邻增幅),
    "log_sum": np.log1p(sum(c_hats)),

    # 基线分数（对比用）
    "weighted_sum_uniform": (当前 uniform 模式分数),
    "weighted_sum_decay": (当前 weighted 模式分数),
}
```

#### V2 混合特征（方案 D）— ~30 维

在 V1 基础上加入：

- 前 5 个位置的原始 ĉ_k 值
- 前 5 个位置的 (V_k, E_k)（来自 `prefix_builder.py`）
- 候选集特征：`seq_first_vertex_candidates`、`total_candidates`（来自 `extract_candidate_features.py`）
- 查询图全局：`query_vertices`、`query_density`、`query_max_degree`（来自 `extract_graph_features.py`）

### 2.2 LambdaMART 训练数据格式

LightGBM ranking 模式需要 group-wise 格式：

```python
import lightgbm as lgb

# 每个 (dataset, query_graph) 是一个 group
# group 内每个序列是一个样本
# 标签方案推荐：分档标签 — Top-1=5, Top-3=3, Top-10=1, 其余=0

train_data = lgb.Dataset(
    X_train,           # shape: (total_sequences, n_features)
    label=y_train,     # relevance labels
    group=group_sizes, # e.g., [72, 65, 80, ...] — 每组的序列数
)

params = {
    "objective": "lambdarank",
    "metric": "ndcg",
    "ndcg_eval_at": [1, 3, 5],
    "learning_rate": 0.05,
    "num_leaves": 31,
    "min_data_in_leaf": 5,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
}

model = lgb.train(
    params, train_data,
    valid_sets=[val_data],
    num_boost_round=500,
    callbacks=[lgb.early_stopping(50)],
)
```

### 2.3 数据划分

| 划分方式 | 用途 | 做法 |
|----------|------|------|
| **Query-level split**（主实验） | 对未见 query 的泛化 | 同一 dataset 内 80/20，按 query size 分层 |
| **Dataset-level leave-one-out**（补充） | 跨数据集泛化 | 留一个 dataset 作为测试集 |

### 2.4 集成到现有代码

推理时替换 `score_aggregator.py` 中的逐步加权求和逻辑：

```python
# 现有逻辑 (score_aggregator.py:178):
#   tracker.score += omega * c_hat

# 新逻辑：所有前缀评估完成后，一次性提特征 + 推理
features = extract_features(tracker.estimates, prefix_topologies, candidate_info)
tracker.score = model.predict([features])[0]  # rank score，越大越好
```

---

## 3. 后处理分析

### 3.1 应作为模型输入（而非后处理）的特征

| 特征 | 理由 | 来源 |
|------|------|------|
| 前缀拓扑 (V_k, E_k) | 环路数影响剪枝强度，影响估计值可靠性 | `prefix_builder.py` |
| 候选集统计 | 首顶点候选数决定搜索起点规模 | `extract_candidate_features.py` |
| 查询图全局特征 | 密度/最大度影响整体难度 | `extract_graph_features.py` |

这些特征让模型学到：同样的基数估计值在不同拓扑结构下意味着不同的执行性能。

### 3.2 可能需要后处理的场景

1. **Top-K 窗口策略**：模型选出 Top-3，再用轻量规则（如首顶点候选数最少）从 Top-3 选 Top-1。仅在 Top-1 不理想但 Top-3 好时使用。

2. **异常值过滤**：FaSTest 估计值全为 0 或极端大的序列，在推理前直接过滤。

3. **分组 vs 单一模型**：推荐单一模型 + `query_vertices` 作为特征，而非按 query size 训练多个模型。

---
