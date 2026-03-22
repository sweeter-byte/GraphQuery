# M2 模型设计分析：基于前缀基数估计的序列选择模型

> 状态：设计讨论中 | 前置依赖：3.1 训练数据收集（假设已完成）

## 1. 问题定义

给定一个 (data_graph, query_graph) 对和 N 个候选匹配序列 $S = \{s_1, s_2, \dots, s_N\}$（M1 去重后约 50–80 个, M1是前置阶段，也就是模型输入最多不超过81），**选出执行性能最优的序列**（最高 EPS 或最低枚举时间）。

### 1.1 当前基线：手工加权求和

当前 M2 使用线性代价模型对每个序列 $S$ 打分：

$$
\text{score}(S) = \sum_{k=1}^{n} \omega_k \cdot \hat{c}_k
$$

- $\hat{c}_k$：第 $k$ 个前缀子图的 FaSTest 基数估计值
- $\omega_k$：权重函数，支持两种模式：
  - **uniform**：$\omega_k = 1.0$
  - **weighted**：$\omega_k = \alpha(k) \cdot \beta(Q_k)$
    - 位置衰减：$\alpha(k) = \left(\frac{n - k + 1}{n}\right)^\gamma$
    - 拓扑因子：$\beta(Q_k) = 1 + \lambda \cdot \frac{E_k - V_k + 1}{V_k}$

**选 score 最低的序列作为最优**。

### 1.2 目标

用 ML 模型替代上述手工加权求和，使最优序列的选中率（Top-1 Accuracy）显著提升。目前是提高Top-1 Accuracy, 但后续也可以是Top-3,使用窗口的思想，然后从Top-3中选出Top-1。

---

## 2. 输入特征设计

### 2.1 核心特征：前缀基数估计值序列

每个序列的 n 个前缀子图经 FaSTest 估计后，得到一个基数向量：

$$
[\hat{c}_1, \hat{c}_2, \dots, \hat{c}_n]
$$

这是模型的**主输入**，反映了按该序列**逐步扩展匹配时的搜索空间增长趋势**。

### 2.2 可选附加特征

以下特征已在代码中可提取（参见 `tools/extract_*.py`），可作为模型的辅助输入：

| 类别 | 特征 | 来源 | 说明 |
|------|------|------|------|
| **前缀拓扑** | 每个前缀的 $(V_k, E_k)$ | `prefix_builder.py` | 环路数 $E_k - V_k + 1$ 反映前缀约束强度 |
| **前缀拓扑** | 每个前缀的环路密度 | 上同 | $(E_k - V_k + 1) / V_k$，当前 weighted 模式的 $\beta$ 因子已在用 |
| **候选集** | `candidates_per_vertex` | `extract_candidate_features.py` | 每个顶点的候选数量 |
| **候选集** | `total_candidates`, `min/max/avg_candidates` | 上同 | 候选集整体统计 |
| **序列-候选交叉** | `seq_first_vertex_candidates` | 可计算 | 序列首顶点的候选数（决定搜索起点规模） |
| **序列-候选交叉** | `seq_candidate_product_log` | 可计算 | $\log(\prod C_i)$，搜索空间上界估计 |
| **序列-候选交叉** | `seq_candidate_order` 模式 | 可计算 | 候选数按序列位置是递增/递减/混合 |
| **查询图全局** | `query_vertices`, `query_edges` | `extract_graph_features.py` | 查询图规模 |
| **查询图全局** | `query_density`, `query_max_degree` | 上同 | 查询图结构特性 |
| **数据图全局** | `data_vertices`, `data_edges` | 上同 | 数据图规模 |
| **M2 计算** | `filter_time`, `build_table_time` | M3 CSV schema | 过滤和建表耗时 |

### 2.3 特征重要性预期

根据子图匹配的原理，预期以下特征对模型贡献最大：

1. **前缀基数估计值序列本身**（核心）— 直接反映搜索空间
2. **前缀的环路结构** — 环越多，剪枝越强，估计值越可靠
3. **序列前几个位置的候选数** — 早期分支因子决定整体性能
4. **查询图密度/最大度** — 影响所有序列的整体难度

---

## 3. 变长序列处理

不同查询图有不同的顶点数 $n \in \{4, 8, 10, 12, 14, 16, 20, 24, 32\}$，因此基数估计值向量长度不等。以下是四种处理方案：

### 方案 A：固定长度 Padding

将所有向量补零（或补 -1）到 $n_{\max} = 32$，同时附带一个 `query_vertices` 特征标明实际长度。

- **优点**：实现简单，适用于 MLP / CNN 等固定输入模型
- **缺点**：零值可能引入噪声；padding 比例高时（n=4 → 87.5% 是 padding）效果可能差
- **适用模型**：MLP, 1D-CNN, XGBoost（需配合 mask 特征）

### 方案 B：统计聚合

从原始序列提取固定数量的统计特征：

```
sum, mean, std, max, min, first, last,
first_3_mean, last_3_mean,
increasing_ratio,      # 相邻递增的比例
max_jump,              # 最大相邻增幅
log_product,           # log(Σĉ_k) 或 log(Πĉ_k)
weighted_sum_uniform,  # 当前基线的 score
weighted_sum_decay,    # position-decay 加权和
```

- **优点**：特征维度固定且低（~15 维），可直接用 GBDT
- **缺点**：丢失序列位置信息（如"第 3 个位置突增"这类模式）
- **适用模型**：XGBoost / LightGBM, 小型 MLP

### 方案 C：序列模型

将 $[\hat{c}_1, \hat{c}_2, \dots, \hat{c}_n]$ 视为一个时间序列，每个位置可附带额外特征（环路数、候选数等），直接输入序列模型。

- **优点**：保留完整的位置信息和序列模式
- **缺点**：模型更复杂，训练/推理开销更大
- **适用模型**：1D-CNN, LSTM/GRU, small Transformer

### 方案 D：混合方案

聚合统计（方案 B）+ 前 K 个位置的原始值（如前 5 个位置的 $\hat{c}_k$、$E_k$、$V_k$）。

- **优点**：兼顾全局统计和关键位置信息，维度可控
- **缺点**：仍然丢弃了尾部位置信息
- **适用模型**：XGBoost / LightGBM, MLP

### 推荐

| 阶段 | 方案 | 理由 |
|------|------|------|
| **V1 基线** | B（统计聚合） | 快速验证，GBDT 开箱即用 |
| **V2 改进** | D（混合） | 加入位置信息，仍可用 GBDT |
| **V3 上限探索** | C（序列模型） | 探索上限，但需评估推理开销是否可接受 |

---

## 4. 模型架构选型

### 4.1 候选架构

| 方案 | 输入要求 | 推理速度 | 可解释性 | 适用场景 |
|------|----------|----------|----------|----------|
| **XGBoost / LightGBM** | 固定长度特征向量 | 极快（μs 级） | 高（feature importance） | 聚合特征（方案 B/D） |
| **小型 MLP**（2-3 层, <1k 参数） | 固定长度 | 很快（μs 级） | 中 | 学习非线性特征交互 |
| **1D-CNN**（3-5 层） | 变长序列（padding） | 快（~ms 级） | 低 | 捕捉局部模式（相邻位置关系） |
| **LSTM / GRU** | 变长序列 | 中等（~ms 级） | 低 | 捕捉长距离依赖、递进模式 |

### 4.2 推理时间约束

M2 当前总耗时约为**毫秒级**（FaSTest 基数估计本身就很快）。ML 模型是在 M2 估计**之后**做一次打分，所以：

- 需要对 N 个序列各推理一次（N ≈ 50-80）
- 总推理时间应 **< 10ms**（避免成为瓶颈）
- **GBDT 和小型 MLP 完全满足**；CNN/LSTM 需要评估

### 4.3 推荐路线

```
V1: LightGBM + 聚合特征（方案 B）
    → 快速出基线，验证 ML 能否超过手工加权

V2: LightGBM + 混合特征（方案 D）
    → 加入位置信息，看 Top-1 准确率是否提升

V3（可选）: 小型 MLP + 混合特征
    → 如果 V2 接近上限，尝试学习非线性交互

V4（可选）: 1D-CNN / LSTM + 完整序列
    → 仅在 V1-V3 不够好时探索
```

---

## 5. 训练目标与损失函数

### 5.1 候选方案

| 损失函数 | 优化目标 | 适用模型 | 优缺点 |
|----------|----------|----------|--------|
| **MSE 回归** | 预测绝对 EPS 或 $\log(\text{time})$ | 所有 | 简单直接；但绝对值预测难，我们只需相对排名 |
| **Pairwise Ranking Loss** | 学习相对顺序：$\max(0, f(s_{\text{worse}}) - f(s_{\text{better}}) + \text{margin})$ | MLP / 神经网络 | 只需比较好坏，更鲁棒；训练对数 $O(N^2)$ |
| **LambdaMART** | 直接优化 NDCG 等排名指标 | LightGBM (built-in) | LightGBM 原生支持 `lambdarank`，适合 V1 |
| **二分类 + 负采样** | 每组 winner vs 随机 loser | 所有 | 简单；但丢弃了 loser 之间的排序信息 |
| **Softmax 分类** | 每组 N 个序列 softmax，label = winner index | 神经网络 | 需固定 N 或用 set pooling；信息最完整 |

### 5.2 推荐

- **V1 首选**：LightGBM + `lambdarank` 目标函数
  - LightGBM 原生支持 Learning to Rank（LambdaMART）
  - 输入是 group-wise 的（每个 query 对应一组候选序列）
  - 直接优化排名质量，无需预测绝对值
  - 与 GBDT 架构天然契合

- **如果用神经网络**：Pairwise Ranking Loss 或 Softmax

---

## 6. 评估指标

| 指标 | 定义 | 说明 |
|------|------|------|
| **Top-1 Accuracy** | 模型选中的序列确实是最优序列的比例 | 最重要的指标 |
| **Top-3 Accuracy** | 最优序列在模型排名前 3 的比例 | 容错指标 |
| **Regret** | $(EPS_{\text{best}} - EPS_{\text{selected}}) / EPS_{\text{best}}$ | 衡量选错的代价 |
| **Spearman ρ** | 模型排名 vs 真实排名的秩相关系数 | 衡量整体排名质量 |
| **NDCG@K** | 归一化折损累计增益 | 标准排名指标，与 LambdaMART 训练目标一致 |

### 对比基线

- **Baseline 1**：当前手工 uniform 加权（$\omega_k = 1.0$）
- **Baseline 2**：当前手工 weighted 加权（position-topology decay）
- **Baseline 3**：随机选择

---

## 7. 数据划分与泛化策略

### 7.1 划分维度

训练数据来自多个 dataset × query_graph × sequence 组合。泛化性能的评估需要考虑：

| 划分方式 | 做法 | 验证什么 |
|----------|------|----------|
| **Query-level split** | 同一 dataset 的 query 按 80/20 划分 | 对未见 query 的泛化 |
| **Dataset-level split** | 留一个 dataset 作为测试集 | 跨数据集泛化（最严格） |
| **Size-level split** | 按 query 顶点数分组，留出某些规模 | 对未见规模的泛化 |

### 7.2 推荐

- 主实验用 **Query-level split**（stratified by query size）
- 补充实验用 **Dataset-level leave-one-out** 验证跨域泛化

---

## 8. 实现路线总结

| 步骤 | 内容 | 依赖 |
|------|------|------|
| **3.2a** | 特征工程：从 M2 结果中提取聚合统计特征（方案 B） | 3.1 数据已就绪 |
| **3.2b** | 特征工程：构建 LightGBM 训练数据（group-wise 格式） | 3.2a |
| **3.3a** | V1 模型：LightGBM + LambdaMART + 聚合特征 | 3.2b |
| **3.3b** | V2 模型：加入混合特征（方案 D），对比 V1 | 3.3a |
| **3.3c** | 评估：Top-1/3 Accuracy、Regret、NDCG，对比基线 | 3.3a/b |
| **3.3d** | （可选）V3 模型：小型 MLP / 序列模型探索上限 | 3.3c 结果不理想时 |

---

## 附录：关键代码位置

| 组件 | 路径 |
|------|------|
| M2 评分逻辑 | `server/services/score_aggregator.py` |
| M2 批量运行 | `experiments/common/m2_runner.py` |
| FaSTest 适配器 | `server/services/estimator_adapter.py` |
| 前缀构建 | `server/services/prefix_builder.py` |
| 图特征提取 | `tools/extract_graph_features.py` |
| 候选集特征提取 | `tools/extract_candidate_features.py` |
| M1 序列提取 | `tools/run_filter_order_experiment.py` |
| 统计工具 | `experiments/common/stats.py` |
