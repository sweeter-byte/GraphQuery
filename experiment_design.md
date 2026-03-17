# GraphQuery 查询序列优化器有效性验证 — 实验设计

## 核心命题

证明：**M2（序列代价估计）选出的最优序列，在 M3（真实查询引擎）上的执行性能显著优于随机/默认序列**，且 **M1+M2 的优化开销可以被摊销**。

这需要回答三个递进的问题：

1. 我们选出的序列确实更快吗？（有效性）
2. 选序列本身的开销值得吗？（效率性）
3. 在不同条件下结论是否稳健？（鲁棒性）

---

## 实验总览

| 实验编号 | 名称 | 回答的问题 |
|---------|------|-----------|
| E1 | 序列质量对比 | 最优序列 vs 随机/默认序列的真实执行差距有多大？ |
| E2 | 估计精度验证 | M2 的代价排名与 M3 的真实排名一致吗？ |
| E3 | 端到端收益分析 | 加上优化开销后，总时间仍然更短吗？ |
| E4 | 优化开销缩减 | Beam Search / 提前终止能把 M1+M2 开销压到多低？ |
| E5 | 查询规模敏感性 | 查询图越大，优化收益越明显吗？ |
| E6 | 数据集泛化性 | 在不同数据集上结论是否一致？ |
| **E7** | **M1 搜索空间剪枝** | **剪枝策略能否在保持序列质量的前提下显著缩减搜索空间？** |

---

## E1：序列质量对比（核心实验）

**目的**：证明优化器选出的序列在真实执行中显著优于基线。

**方法**：

对每个 (数据集, 查询图) 组合，生成以下序列并送入 M3 执行：

| 序列来源 | 说明 |
|---------|------|
| `OPT` | M2 排名第 1 的序列 |
| `TOP5-AVG` | M2 排名前 5 的序列（取平均） |
| `RAND-k` | 从候选空间中均匀随机采样 k=10 条序列 |
| `DEFAULT` | SubgraphMatchingSurvey 自身的默认 ordering 方法（如 GQL、CFL、RI） |
| `WORST` | M2 排名最末的序列 |

**M3 执行配置**：
- 固定 filter=CFL, engine=LFTJ（或其他合理默认组合）
- `-num MAX`，time_limit=60s
- 记录指标：Total Time、Enumerate Time、#Embeddings、EPS、Call Count

**输出**：
- 表格：每个数据集上各序列来源的平均 EPS 和平均 Total Time
- 箱线图：OPT vs RAND 的 EPS 分布对比
- 加速比：`Speedup = Time(RAND-avg) / Time(OPT)`

**查询工作负载**：
- 每个数据集生成 5 组查询规模：|V_q| = 4, 8, 12, 16, 20
- 每组 50 条查询（Metropolis-Hastings 随机游走生成）
- 共 6 数据集 × 5 规模 × 50 查询 = 1500 个实验点

**可用数据集**：yeast, human, dblp, wordnet, youtube, patents

---

## E2：估计精度验证

**目的**：验证 M2 的代价排名与真实执行排名的相关性。

**方法**：

对每个查询图，取 M2 生成的全部候选序列（或 Top-50），分别：
1. 记录 M2 的代价估计值 `score(O)`
2. 送入 M3 执行，记录真实 `Total Time(O)` 或 `EPS(O)`

**指标**：
- Spearman 秩相关系数 ρ：M2 排名 vs M3 排名
- Top-K 命中率：M2 的 Top-5 中有多少条落在 M3 的 Top-10 内
- 散点图：横轴 M2 score，纵轴 M3 Total Time（期望正相关）

**意义**：即使 M2 的绝对值不准，只要排名一致，优化器就是有效的。

---

## E3：端到端收益分析（关键实验）

**目的**：回答"优化开销 + 最优序列执行 < 随机序列直接执行"是否成立。

**方法**：

定义端到端时间：
```
T_optimized = T_M1(序列生成) + T_M2(代价估计) + T_M3(OPT 执行)
T_baseline  = T_M3(RAND 执行)    // 或 T_M3(DEFAULT 执行)
```

对每个查询，记录：
- `T_M1`：order_generator 耗时
- `T_M2`：所有前缀估计的总耗时（含并行）
- `T_M3_OPT`：最优序列的执行耗时
- `T_M3_RAND`：随机序列的执行耗时（取 10 条的中位数）
- `T_M3_DEFAULT`：默认 ordering 的执行耗时

**输出**：
- 堆叠柱状图：T_M1 + T_M2 + T_M3_OPT vs T_M3_RAND vs T_M3_DEFAULT
- 盈亏平衡分析：在什么条件下 T_optimized < T_baseline
- 净收益率：`(T_baseline - T_optimized) / T_baseline × 100%`

**预期结论分区**：
- 小查询（|V_q| ≤ 6）：优化开销可能不值得，直接执行更快
- 中查询（8 ≤ |V_q| ≤ 16）：优化收益开始显现
- 大查询（|V_q| ≥ 20）：优化收益显著，因为差序列的执行时间爆炸式增长

---

## E4：优化开销缩减实验

**目的**：探索如何降低 M1+M2 的开销，使端到端收益更早出现。

### E4a：Beam Width 对开销和质量的影响

| beam_width | M1+M2 耗时 | OPT 的 M3 执行时间 | 端到端总时间 |
|-----------|-----------|-------------------|------------|
| 10 | | | |
| 25 | | | |
| 50 | | | |
| 100 | | | |
| 200 | | | |
| EXACT | | | |

**输出**：双 Y 轴折线图 — 左轴 M1+M2 耗时，右轴 OPT 的 M3 执行质量（EPS）

### E4b：提前终止策略

在 M2 逐层估计过程中，如果某序列在前 k 层的累积代价已经超过当前最优的 2 倍，则剪枝。

对比：
- 无剪枝（当前实现）
- 2× 阈值剪枝
- 1.5× 阈值剪枝

记录：剪枝后剩余序列数、M2 总耗时、最终 OPT 质量是否下降

### E4c：并行度对 M2 吞吐的影响

固定 beam_width=50，变化 python_threads：

| python_threads | omp_threads | M2 总耗时 | 加速比 |
|---------------|-------------|----------|-------|
| 1 | 1 | | |
| 2 | 1 | | |
| 4 | 1 | | |
| 8 | 1 | | |
| 核心数 | 1 | | |

---

## E5：查询规模敏感性

**目的**：验证"查询图越大，优化收益越大"的假设。

**方法**：固定数据集（如 yeast），变化 |V_q| = 4, 6, 8, 10, 12, 16, 20

对每个规模，记录：
- OPT 的 EPS vs RAND 的 EPS
- 加速比 Speedup(|V_q|)
- M1+M2 开销占比

**输出**：折线图 — 横轴查询规模，纵轴加速比。期望看到随 |V_q| 增大加速比单调递增。

---

## E6：数据集泛化性

**目的**：确认结论不依赖于特定数据集。

**方法**：固定 |V_q|=12, beam_width=50，在全部 6 个数据集上重复 E1 和 E3。

**输出**：
- 热力图：行=数据集，列=序列来源（OPT/RAND/DEFAULT），值=平均 EPS
- 每个数据集的加速比汇总表
- Friedman 检验：跨数据集的排名是否显著一致

---

## 实验执行要点

### 查询生成
沿用 Survey 论文的方法：在数据图上做 Metropolis-Hastings 随机游走，提取诱导子图作为查询。SubgraphMatchingSurvey 的代码中已有此功能。

### M3 执行参数
```bash
./SubgraphMatching.out -d <data_graph> -q <query_graph> \
  -filter CFL -order <ORDER_TO_TEST> -engine LFTJ \
  -num MAX -time_limit 60
```

注意：`-order` 参数在 Survey 引擎中是指 ordering 方法（如 CFL、RI），而非我们生成的具体序列。要测试我们的自定义序列，需要修改引擎接口或通过文件传入预定义序列。

### 统计显著性
- 每组实验至少 50 个查询点
- 报告均值 ± 标准差
- 使用 Wilcoxon 符号秩检验比较 OPT vs RAND 的配对差异
- p < 0.05 视为显著

### 超时处理
- M3 执行超时（60s）的查询标记为 TIMEOUT
- 超时查询的 EPS 按 `#Embeddings / 60` 计算
- 单独报告各方法的超时率

---

## 预期结果与论文叙事

理想情况下，实验数据应支撑以下叙事：

1. **E1 + E2** → "我们的代价估计能有效区分好序列和差序列"
2. **E3** → "尽管优化有开销，但对中大规模查询，端到端时间仍然更短"
3. **E4** → "通过 Beam Search + 剪枝 + 并行，优化开销可以压缩到 X 秒以内"
4. **E5** → "查询越复杂，优化收益越大，这符合直觉"
5. **E6** → "结论在多个真实数据集上一致成立"
6. **E7** → "M1 搜索空间剪枝在保持序列质量的前提下显著缩减搜索空间和端到端耗时"

如果 E3 在小查询上不成立，这不是坏结果 — 它精确划定了优化器的适用边界，反而增强论文的可信度。

---

## E7：M1 搜索空间剪枝实验

### 7.1 背景与动机

M1 阶段负责生成候选扩展序列。原始实现（baseline）提供两种模式：

- **Exact DFS**：枚举所有合法连通扩展序列，复杂度 O(n!)，仅适用于 |V_q| ≤ 7
- **Beam Search**：逐层扩展 + Top-b 截断，返回至多 beam_width 条序列

两者均为"盲目搜索"——不利用查询图的结构特征来指导搜索方向或裁剪冗余分支。当查询图规模增大时，搜索空间爆炸，M1 耗时成为端到端瓶颈。

为此，我们实现了 **pruned 策略**，组合四种剪枝技术（S1-S4），在 A* 框架下协同工作。

### 7.2 M1 实现详述

#### 代码结构

```
server/services/
├── order_generator.py                  # 原始实现（不修改，作为基线）
└── order_strategies/
    ├── __init__.py                     # 策略调度器（OrderStrategy 枚举 + generate_orders 分发）
    ├── baseline.py                     # 薄包装，委托给 order_generator.py
    ├── pruned.py                       # 剪枝版序列生成（S1-S4 组合）
    └── graph_analysis.py              # 共享图分析工具
```

调度器通过 `strategy` 参数选择实现：

```python
# server/services/order_strategies/__init__.py
def generate_orders(graph, beam_width=None, exact_threshold=7, strategy="baseline"):
    if strategy == "pruned":
        return generate_orders_pruned(graph, ...)
    return generate_orders_baseline(graph, ...)
```

前端/API 通过 `SessionCreateRequest.order_strategy` 字段传入，默认 `"baseline"`。

#### Baseline 实现（order_generator.py）

**Exact DFS 模式**（|V_q| ≤ exact_threshold 且 beam_width=None）：
- 从每个顶点出发，DFS 枚举所有满足连通扩展约束的全排列
- 连通扩展约束：序列中第 k 个顶点必须与前 k-1 个顶点中的至少一个相邻
- Tie-breaking：按 (label, vertex_id) 升序
- 时间复杂度：O(n!) 最坏情况

**Beam Search 模式**（|V_q| > exact_threshold 或指定 beam_width）：
- 逐层扩展：第 k 层将所有长度为 k 的部分序列各扩展一个顶点
- 每层截断：保留前 beam_width 条（按生成顺序，无评分）
- 返回至多 beam_width 条完整序列

#### Pruned 实现（pruned.py）— 四种策略

**S1：等价顶点剪枝（Symmetry Breaking）**

预处理阶段计算等价类：两个顶点等价当且仅当它们具有相同的 `(label, sorted_neighbor_label_multiset)`。

```python
# graph_analysis.py — compute_equivalence_classes
# 例：三角形 v0(label=0, 邻居标签=[0,1]), v1(label=0, 邻居标签=[0,1]) → 同一等价类
# v2(label=1, 邻居标签=[0,0]) → 独立等价类
```

在搜索的每个扩展层，同一等价类中只展开一个代表顶点。效果：对称查询图（如正则图）的搜索空间大幅缩减。

实测：三角形图（v0, v1 同标签）从 6 条序列缩减为 3 条。

**S2：Core-First 排序**

预处理阶段对查询图做 k-core 分解（迭代剥离算法）：

```python
# graph_analysis.py — compute_k_core
# 返回 {vertex_id: core_number}
# 高 core number → 顶点处于图的"稠密核心"，约束更强
```

候选顶点排序键：`(-core_number, -degree, vertex_id)`。高 core number 的顶点优先展开，度为 1 的叶子顶点自然被推迟。

直觉：先展开约束最强的顶点，使 M2 的前缀估计在早期就能区分好坏序列。

**S3：A* 启发式搜索**

用优先队列（最小堆）替代盲目 DFS/Beam：

- 状态：`(f_score, counter, path_tuple, in_path_frozenset, g_score)`
- `g(n)` = 已展开顶点的累积代价 = Σ degree(v_i)，对已放置顶点
- `h(n)` = 剩余顶点的下界估计 = Σ 1/degree(v_j)，对未放置顶点
- `f(n) = g(n) + h(n)`
- 剪枝条件：`f(n) > cost_factor × best_complete_cost`（默认 cost_factor=2.0）

启发函数设计理由：
- g 用度数作为代价：高度数顶点展开代价高（候选匹配多）
- h 用逆度数之和作为下界：低度数顶点约束弱，未来代价更高
- h 是可容许的（admissible）：实际代价 ≥ h，保证 A* 找到最优解

**S4：邻居安全优先**

候选顶点分为两类：
- **安全扩展**：该顶点在查询图中的所有邻居都已在部分序列中（全约束）
- **悬挂扩展**：仅部分邻居在序列中（部分约束）

排序键中 safety_penalty = 0（安全）或 1（悬挂），安全扩展优先。

直觉：安全扩展意味着该顶点的所有边约束都可以在匹配时被利用，过滤效果最强。

#### 四种策略的协同工作流

```
输入：NormalizedGraph Q

1. 预处理
   ├── build_adjacency(Q)           → adj
   ├── compute_k_core(Q)            → core: {vid: core_number}
   ├── compute_equivalence_classes(Q) → equiv: {(label, nbr_labels): [vids]}
   └── degree_map                    → {vid: degree}

2. 初始化 A* 优先队列
   ├── 对所有顶点按 (-core, -degree, vid) 排序
   └── 每个等价类仅入队一个代表（S1 在根层生效）

3. A* 主循环
   while heap 非空 and |results| < max_orders:
     ├── 弹出 f 最小的状态
     ├── 若 f > 2 × best_complete → 跳过（S3 剪枝）
     ├── 若为完整序列 → 加入 results，更新 best_cost
     └── 否则：
         ├── 收集候选顶点（邻接 + 未放置）
         ├── 按 (safety_penalty, -core, -degree, vid) 排序（S2 + S4）
         ├── 同一等价类仅保留一个代表（S1 在扩展层生效）
         ├── 计算 new_f = new_g + new_h
         ├── 若 new_f > 2 × best_cost → 跳过（S3 剪枝）
         └── 入队

4. 返回 results（至多 max_orders 条）
```

### 7.3 实验设计

#### E7a：搜索空间缩减率

**目的**：量化剪枝策略对搜索空间的缩减效果。

**方法**：对每个 (数据集, 查询图) 组合，分别运行 baseline 和 pruned，记录：

| 指标 | 说明 |
|------|------|
| `N_baseline` | baseline 生成的序列数 |
| `N_pruned` | pruned 生成的序列数 |
| `T_M1_baseline` | baseline 的 M1 耗时（秒） |
| `T_M1_pruned` | pruned 的 M1 耗时（秒） |
| `heap_expansions` | A* 搜索中堆弹出次数（衡量实际搜索量） |
| `pruned_by_S1` | 被等价类剪枝跳过的候选数 |
| `pruned_by_S3` | 被 f > 2×best 剪枝跳过的状态数 |

**查询工作负载**：
- 每个数据集 × 5 种规模（|V_q| = 4, 8, 12, 16, 20）× 50 条查询
- 共 6 × 5 × 50 = 1500 个实验点

**输出**：
- 表格：各数据集上的平均缩减率 `1 - N_pruned / N_baseline`
- 折线图：横轴 |V_q|，纵轴缩减率（期望随规模增大而增大）
- 柱状图：T_M1_baseline vs T_M1_pruned 的对比

#### E7b：序列质量保持验证

**目的**：验证剪枝不会丢失高质量序列。

**方法**：

1. 对每个查询图，分别用 baseline 和 pruned 生成序列
2. 两组序列都送入 M2 进行代价估计
3. 比较两组的 Top-1 序列在 M3 上的真实执行性能

| 指标 | 说明 |
|------|------|
| `score_baseline_top1` | baseline Top-1 序列的 M2 估计代价 |
| `score_pruned_top1` | pruned Top-1 序列的 M2 估计代价 |
| `EPS_baseline_top1` | baseline Top-1 序列的 M3 真实 EPS |
| `EPS_pruned_top1` | pruned Top-1 序列的 M3 真实 EPS |
| `quality_ratio` | `EPS_pruned_top1 / EPS_baseline_top1`（≥1 表示无损或更优） |

**输出**：
- 散点图：横轴 EPS_baseline_top1，纵轴 EPS_pruned_top1（期望点分布在 y=x 线附近或上方）
- 配对 Wilcoxon 检验：pruned Top-1 的 EPS 是否显著劣于 baseline Top-1
- 质量保持率：`quality_ratio ≥ 0.95` 的查询占比

**预期**：pruned 丢弃的是等价/低质量序列，Top-1 质量应基本无损（quality_ratio ≈ 1.0）。

#### E7c：各剪枝策略的消融实验（Ablation Study）

**目的**：量化每种剪枝策略的独立贡献。

**方法**：逐一关闭某种策略，观察搜索空间和序列质量的变化。

| 配置 | S1 等价类 | S2 Core-First | S3 A* 剪枝 | S4 安全优先 |
|------|----------|--------------|-----------|-----------|
| Full（默认） | ✓ | ✓ | ✓ | ✓ |
| -S1 | ✗ | ✓ | ✓ | ✓ |
| -S2 | ✓ | ✗ | ✓ | ✓ |
| -S3 | ✓ | ✓ | ✗ | ✓ |
| -S4 | ✓ | ✓ | ✓ | ✗ |
| Baseline | ✗ | ✗ | ✗ | ✗ |

对每种配置记录：
- 生成序列数 N
- M1 耗时 T_M1
- Top-1 序列的 M2 代价
- Top-1 序列的 M3 EPS（可选，开销大时抽样）

**查询工作负载**：固定 yeast 数据集，|V_q| = 8, 12, 16 各 30 条查询

**输出**：
- 堆叠柱状图：各配置的 N 和 T_M1
- 表格：各策略关闭后的序列数增幅 `(N_{-Si} - N_full) / N_full`
- 雷达图：四种策略在"缩减率"和"质量保持"两个维度上的贡献

#### E7d：A* cost_factor 参数敏感性

**目的**：确定 S3 剪枝阈值 `cost_factor` 的最佳取值。

**方法**：固定其他策略全开，变化 cost_factor：

| cost_factor | 含义 | 预期效果 |
|------------|------|---------|
| 1.2 | 激进剪枝 | 序列少，可能丢失好序列 |
| 1.5 | 中等剪枝 | 平衡点 |
| 2.0（默认） | 保守剪枝 | 序列较多，质量有保障 |
| 3.0 | 宽松剪枝 | 接近无剪枝 |
| ∞ | 无 S3 剪枝 | 等价于关闭 S3 |

记录：N_pruned、T_M1、Top-1 EPS

**输出**：双 Y 轴折线图 — 左轴序列数/耗时，右轴 Top-1 EPS

#### E7e：端到端收益（M1 剪枝对 E3 的影响）

**目的**：验证 M1 剪枝能否缩短端到端总时间。

**方法**：对比两条完整流水线：

```
Pipeline A（baseline）: M1_baseline → M2 → M3(OPT_A)
Pipeline B（pruned）:   M1_pruned  → M2 → M3(OPT_B)
```

记录：

| 指标 | Pipeline A | Pipeline B |
|------|-----------|-----------|
| T_M1 | T_M1_baseline | T_M1_pruned |
| T_M2 | T_M2_A（序列多，估计慢） | T_M2_B（序列少，估计快） |
| T_M3 | T_M3_A | T_M3_B |
| T_total | T_M1 + T_M2 + T_M3 | T_M1 + T_M2 + T_M3 |

**关键洞察**：M1 剪枝不仅缩短 T_M1，还因为序列数减少而缩短 T_M2（M2 需要对每条序列的每个前缀做代价估计）。

**输出**：
- 堆叠柱状图：Pipeline A vs B 的 T_M1 + T_M2 + T_M3 分解
- 加速比：`T_total_A / T_total_B`
- 按查询规模分组的加速比趋势

### 7.4 实验执行要点

#### API 调用方式

```python
import httpx

# Baseline
resp = httpx.post("http://localhost:8000/api/sessions", json={
    "dataset_id": "yeast",
    "query_graph": {...},
    "order_strategy": "baseline",
})

# Pruned
resp = httpx.post("http://localhost:8000/api/sessions", json={
    "dataset_id": "yeast",
    "query_graph": {...},
    "order_strategy": "pruned",
})
```

#### 直接调用（绕过 API，用于精确计时）

```python
from server.services.order_strategies import generate_orders
import time

t0 = time.perf_counter()
orders_baseline = generate_orders(graph, strategy="baseline")
t_baseline = time.perf_counter() - t0

t0 = time.perf_counter()
orders_pruned = generate_orders(graph, strategy="pruned")
t_pruned = time.perf_counter() - t0
```

#### 消融实验的实现方式

当前 pruned.py 中四种策略紧密耦合在 A* 循环中。消融实验需要在 `generate_orders_pruned` 中添加开关参数：

```python
def generate_orders_pruned(
    graph, ...,
    enable_symmetry: bool = True,    # S1
    enable_core_first: bool = True,  # S2
    enable_astar_prune: bool = True, # S3
    enable_safety: bool = True,      # S4
)
```

#### 统计要求

- 每组实验至少 30 个查询点（消融实验）或 50 个查询点（主实验）
- 报告均值 ± 标准差
- 配对比较使用 Wilcoxon 符号秩检验，p < 0.05 视为显著
- M1 耗时测量：每个查询重复 3 次取中位数（消除 JIT/缓存波动）

### 7.5 预期结果

1. **E7a**：pruned 在 |V_q| ≥ 8 时缩减率 > 30%，|V_q| ≥ 16 时 > 60%
2. **E7b**：quality_ratio ≥ 0.95 的查询占比 > 90%，即剪枝基本无损
3. **E7c**：S1（等价类）对对称图贡献最大，S3（A* 剪枝）对大图贡献最大
4. **E7d**：cost_factor=2.0 是合理默认值，1.5 在大多数场景下也安全
5. **E7e**：Pipeline B 的 T_total 在 |V_q| ≥ 8 时显著优于 Pipeline A，主要收益来自 T_M2 的缩减

### 7.6 论文叙事整合

E7 的结果与现有实验的关系：

- **E7a + E7c** → "我们的剪枝策略有效缩减了搜索空间，且各策略贡献互补"
- **E7b** → "剪枝不牺牲序列质量，Top-1 序列的执行性能基本无损"
- **E7e + E3** → "M1 剪枝使端到端收益的盈亏平衡点从 |V_q|=8 提前到 |V_q|=6"
- **E7d** → "cost_factor 参数提供了搜索空间与质量之间的可调旋钮"
