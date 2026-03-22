# 基于 M1 / M2 / M3 的系统三大模块划分说明

本文基于当前仓库中的代码与文档，对整个系统做一次面向运行时流程的模块划分。
这里不按“前端 / 后端 / C++”这种技术栈分层来拆，而是按系统真正执行查询时的主链路来拆成三个大模块：

- `M1`：查询接入与候选执行序列生成
- `M2`：前缀子图估计与代价评估排序
- `M3`：最优顺序落地执行与真实匹配

这样划分的原因是：当前仓库的核心目标并不是单纯提供一个 Web 界面，而是围绕“生成执行序列 -> 用 FaSTest 估计代价 -> 把最优序列交给 Survey 执行”这条链路组织代码。
前端、FastAPI、pybind 和 C++ 引擎都只是这三步的承载方式。

**新的变更**：M1阶段查询接入的功能不变，但是我们不再实现“执行序列生成”的功能，选择SubgraphMatchingSurvey中的534种技术组合（其论文给出了该数字），SubgraphMatchingSurvey是一个框架，执行流程是"filter-order-engine"。对于任何一种技术组合，执行完"filter-order"后，会输出一个查询序列。我们M1阶段接入534种技术组合，就会产生534个查询序列。然后将这534种查询序列接入后续的M2阶段，让M2完成对这些查询序列的筛选，通过cost模型，给出代价最低的序列，我们认为该序列是最好的序列winner。然后将winner传入SubgraphMatchingSurvey的engine，执行查询。目前存在的问题是engine是一个嵌入，不会输出查询数量，这一点需要修改。

**新的变更**: 之前的M2阶段的cost模型是线性相加，cost越低代表查询序列更优。我们目前使用的SubgraphMatchingSurvey，或者说是改进后的SubgraphMatchingSurvey代码，相当于M1包括"filter-order"，给定查询图和数据集，就能够给出查询序列；M3就是其"engine"，也就是说我们可以把M2阶段的cost模型看成一个与基数估计值以及其他数据相关的待预训练的模型，通过M1,M3的数据，训练出模型，然后使用该模型能够对任意的534种序列给出最好的查询序列，也就是下游M3执行开销最小的序列。当然M2的模型越简单越好，具有很高的泛化能力，以及鲁棒性，不要过于庞大复杂，也许这是一个分类任务，我们只需要找出最优的一个序列即可，其他剩下的序列之间的关系我们并不在意。
---

## 1. 总览

| 模块 | 作用 | 主要输入 | 主要输出 | 核心代码 |
| --- | --- | --- | --- | --- |
| `M1` | 把用户查询图变成一组合法的候选顶点扩展序列 | 查询图 JSON、数据集选择 | 候选顺序 `orders` | `server/services/query_validator.py`、`server/services/order_generator.py`、`server/services/order_strategies/` |
| `M2` | 对每条顺序的前缀子图做基数估计并聚合成分数，选出 winner order | `orders`、归一化查询图、数据图索引 | `best_order`、`best_score`、实时排名 | `server/services/prefix_builder.py`、`server/services/session_pipeline.py`、`server/services/score_aggregator.py`、`server/services/estimator_adapter.py`、`core/pybind/FastestPybind.cc`、`core/lib/` |
| `M3` | 将 `M2` 选出的最优顺序交给真实匹配引擎执行，返回真实 embedding 数和耗时 | `best_order`、查询图、数据图 | `embedding_count`、`total_time_seconds`、`eps` | `server/services/execution_service.py`、`server/services/graph_format_converter.py`、`server/services/survey_engine_adapter.py`、`core/engines/SubgraphMatchingSurvey/` |

从运行时看，主流程就是：

`React 前端提交查询 -> FastAPI 创建 Session -> M1 产生候选顺序 -> M2 逐层估计并排序 -> M3 执行 winner order -> 前端展示结果`

---

## 2. 横向支撑层

虽然本文按 `M1/M2/M3` 来拆，但系统里还有一层横向支撑面，贯穿三个模块：

- 前端界面：`frontend/src/App.tsx`、`DatasetSelector`、`QueryGraphEditor`、`EvaluationDashboard`、`RankingLeaderboard`
- API 与会话管理：`server/main.py`、`server/routes/sessions.py`、`server/storage.py`
- SSE 实时通信：后端 `ScoreAggregator.stream_events()`，前端 `useSessionStream.ts`

这层本身不决定“如何优化查询计划”，但决定了三大模块怎样被触发、怎样把中间结果可视化出来。尤其是：

- `POST /api/sessions` 是 `M1` 的入口
- `GET /api/sessions/{id}/stream` 持续消费 `M2` 的实时事件
- `POST /api/sessions/{id}/execute` 触发 `M3`

换句话说，前后端是承载面，`M1/M2/M3` 才是系统的算法主线。

---

## 3. M1：查询接入与候选执行序列生成

### 3.1 模块职责

`M1` 的目标，是把用户提交的查询图转成一组“合法、连通、可评估”的候选执行顺序。它解决的是“搜索空间从哪里来”的问题。

在当前实现里，`M1` 包含四件事：

1. 查询图合法性检查
2. 顶点 ID 归一化
3. 生成连通扩展顺序
4. 在大搜索空间上做剪枝，减少明显冗余的顺序

### 3.2 主要算法

#### 3.2.1 查询验证与归一化

代码入口：`server/services/query_validator.py`

这里使用的是很标准但很关键的图算法：

- 重复顶点检查：用集合 `vertex_ids` 检测重复 ID
- 边端点检查：验证每条边的 `source/target` 是否存在
- 自环检查：拒绝 `source == target`
- 连通性检查：把查询图视为无向图，在邻接表上做 BFS
- ID 归一化：把任意用户顶点 ID 映射为连续的 `0..n-1`

这里的 BFS 虽然简单，但在系统语义上非常重要，因为后续 `M1` 和 `M2` 都默认查询图是连通的；一旦图不连通，后面的“连通扩展顺序”定义就不成立。

#### 3.2.2 基线顺序生成：Exact DFS / Beam Search

代码入口：`server/services/order_generator.py`

基线实现提供两种策略：

- `enumerate_connected_orders_exact()`：精确 DFS，枚举所有合法连通扩展顺序
- `enumerate_connected_orders_beam()`：Beam Search，逐层截断，只保留前 `beam_width` 条部分顺序

这里的“合法顺序”定义是：

给定顺序 `O = (v1, v2, ..., vn)`，对每个 `k >= 2`，`vk` 必须至少与 `v1..v{k-1}` 中某个顶点相邻。

也就是说，系统并不是在所有 `n!` 个排列上暴力打分，而是在“连通扩展排列”这个子空间上搜索。这个约束直接对应真实子图匹配中的回溯扩展语义。

#### 3.2.3 剪枝版顺序生成：S1-S4

代码入口：`server/services/order_strategies/pruned.py`  
图分析工具：`server/services/order_strategies/graph_analysis.py`

这是当前 `M1` 最有算法含量的一层。它在基线搜索之外，叠加了 4 个剪枝/排序策略：

- `S1` 等价顶点剪枝
  - 依据 `(label, 邻居标签多重集)` 建立等价类
  - 同一扩展层里，只展开一个代表顶点
  - 本质是 symmetry breaking

- `S2` Core-First 排序
  - 先对查询图做 `k-core` 分解
  - 高 core number、度更高的点优先展开
  - 直觉是先放约束更强的点，让后续分支更早收缩

- `S3` A* 启发式搜索
  - 用最小堆维护部分顺序
  - `g(n)`：已放入顺序的累积代价
  - `h(n)`：剩余顶点的启发式下界
  - 当 `f = g + h` 超过当前最好完整解的 `cost_factor` 倍时直接剪掉

- `S4` 邻居安全优先
  - 如果一个候选点的所有查询邻居都已经在当前部分顺序里，它被认为更“安全”
  - 这种点优先展开，因为局部约束更完整

这四个策略叠加后，`M1` 不再只是“列举顺序”，而是在做一个带结构启发式的图搜索。

### 3.3 关键数据结构

`M1` 主要使用的数据结构如下：

- 邻接表 `dict[int, set[int]]`
  - 用于 BFS、DFS、候选点生成、邻接判断
- `label_map`
  - 顶点 ID 到标签的映射
- `core: dict[int, int]`
  - `k-core` 分解结果
- 等价类哈希表
  - key 是 `(label, sorted(neighbor_labels))`
  - value 是同构候选顶点列表
- A* 最小堆 `heapq`
  - 状态是 `(f_score, counter, path, in_path, g_score)`
- `path + in_path`
  - `path` 保留顺序语义
  - `in_path` 提供 O(1) 级 membership 判断

这些结构说明 `M1` 的本质是“图搜索 + 剪枝”，而不是简单的组合枚举。

### 3.4 M1 的输出

`M1` 的输出是一个顺序列表：

```text
orders = [
  [0, 1, 2, 3],
  [0, 2, 1, 3],
  ...
]
```

这些顺序随后直接进入 `M2`。因此可以把 `M1` 理解为“候选计划空间生成器”。

---

## 4. M2：前缀子图估计与代价评估排序

### 4.1 模块职责

`M2` 是整个系统的核心。它解决的是“如何评价一个顺序好不好”的问题。

它的工作不是直接跑真实子图匹配，而是：

1. 把每条顺序切成一系列前缀子图
2. 用 FaSTest 对每个前缀做基数估计
3. 把各层估计值聚合成一个总代价
4. 在所有顺序上动态更新排名，最终选出最优顺序

### 4.2 Python 侧算法

#### 4.2.1 前缀子图构建

代码入口：`server/services/prefix_builder.py`

对于顺序 `O = (v1, ..., vn)`，模块逐步构造诱导前缀子图：

- `Q1 = Q[{v1}]`
- `Q2 = Q[{v1, v2}]`
- ...
- `Qk = Q[{v1, ..., vk}]`

实现上它做了三件事：

- 用 `edge_data: frozenset(endpoint) -> edge_label` 做边查找
- 维护 `current_set` 和 `current_edges`，增量加入新顶点后形成新的诱导子图
- 将前缀子图重新编号到局部的 `0..k-1`

这一步的输出是 `PrefixPayload`，它是 Python 和 C++ 之间的内存协议对象。

#### 4.2.2 逐层评估循环

代码入口：`server/services/session_pipeline.py`

`M2` 的调度方式是“按层推进”而不是“按顺序推进”：

- 先评估所有顺序的第 1 层前缀
- 再评估所有顺序的第 2 层前缀
- ...

这样做的好处是：

- 排名能更早形成
- 同层共享前缀更容易去重
- Python 线程池 + C++ OpenMP 的两层并行更容易安排

#### 4.2.3 O1：选择性前缀评估

当前实现里，`M2` 已经把文档中的多项优化真正写进代码：

- `R1` 跳过最后一层
  - 所有顺序的最后一个前缀都是完整查询图
  - 因此只估计一次，再广播给所有顺序

- `R4` 前缀 Memoization
  - 用 `frozenset(order[:k])` 作为 key
  - 相同顶点集的诱导前缀子图只估计一次
  - `prefix_cache` 负责跨层复用
  - `pending_by_key` 负责同层去重

- `R3` 自适应早停
  - 当某条顺序的当前累积分数已经明显差于最好完整解时，直接跳过后续层
  - 剪枝条件由 `multiplier * best_complete_score` 控制

从算法角度看，`M2` 已经不是“老老实实评估所有前缀”，而是在做：

`分层调度 + 缓存去重 + 剪枝 + 并发估计`

#### 4.2.4 O2：位置-拓扑感知的加权代价模型

代码入口：`server/services/score_aggregator.py`

原始代价模型是：

`score(O) = sum(c_hat_k)`

现在扩展成：

`score(O) = sum(omega(k, Q_k) * c_hat_k)`

其中：

- 位置因子 `alpha(k)`：越早的前缀权重越高
- 拓扑因子 `beta(Q_k)`：含环越多、约束越强的前缀权重越高

这意味着 `M2` 在评价顺序时，不再把所有层一视同仁，而是明确表达了：

- 早期爆炸比后期爆炸更危险
- 环结构前缀比树状前缀更能代表真实执行难度

#### 4.2.5 实时排名与 SSE

`ScoreAggregator` 维护每条顺序的：

- `prefix_index`
- `estimates`
- `score`
- `done`

同时维护全局：

- `ranking`
- `best_order_id`
- `best_score`
- `skipped_orders`

它还把大量高频事件做 75ms 的 debounce batching，然后通过 SSE 推给前端。  
因此 `M2` 不仅是算法模块，也是系统可观测性的中心模块。

### 4.3 FaSTest C++ 内核算法

如果只看 Python，很容易误以为 `M2` 的主要工作是“调度”。实际上真正最重的算法都在 FaSTest 内核里。

#### 4.3.1 数据图预处理与索引

代码入口：

- `core/pybind/FastestPybind.cc`
- `core/lib/SubgraphMatching/DataGraph.h`
- `core/lib/DataStructure/Graph.h`

FaSTest 在加载数据图时会做：

- 标签压缩 `TransformLabel`
- 邻接表与 incidence list 构建
- `core number` 计算
- `vertex_by_labels` 构建
- 局部三角形枚举
- 局部四环枚举

并且支持把这些结构序列化到：

- `graph.bin`
- `triangles.bin`
- `four_cycles.bin`

所以 `M2` 的“快”，本质上建立在数据图离线索引之上，而不是仅仅依赖 Python 并发。

#### 4.3.2 图表示

FaSTest 的 `Graph` / `DataGraph` / `PatternGraph` 使用的是紧凑图表示：

- `adj_list`
- `edge_list`
- `edge_to`
- `edge_index_map`
- `incident_edges[v][label]`
- `all_incident_edges[v]`
- `local_triangles`
- `local_four_cycles`

这些结构共同支撑三件事：

- 快速按标签取候选顶点
- 快速判断边和局部结构是否兼容
- 快速做采样时的邻居交集与扩展

#### 4.3.3 Candidate Space 构建

代码入口：

- `core/lib/SubgraphMatching/CandidateSpace.h`
- `core/lib/SubgraphMatching/CandidateFilter.h`

Candidate Space 可以理解为“查询图顶点 -> 数据图候选顶点集合”的约束图。

它的构建过程分三步：

1. `BuildInitialCS`
   - 从候选最少的查询顶点作为根开始
   - 用标签、度数、core number 做第一轮过滤

2. `RefineCS`
   - 做邻居安全过滤
   - 做 Triangle Safety / Four-Cycle Safety 结构过滤
   - 按优先级反复修剪候选集合

3. `ConstructCS`
   - 把候选顶点之间的相容关系组织成 `candidate_neighbors`

这里的关键数据结构包括：

- `candidate_set_[u]`
- `candidate_neighbors[u][cand_idx][adj_idx]`
- `BitsetCS`
- `BitsetEdgeCS`

因此，FaSTest 并不是对原图盲采样，而是先显式构造了一个“候选空间图”。

#### 4.3.4 Tree Sampling

代码入口：`core/lib/SubgraphCounting/CandidateTreeSampling.h`

Tree Sampling 的思路是：

1. 从查询图抽一棵生成树 `QueryTree`
2. 在 Candidate Space 上统计“候选树”的数量
3. 基于这些计数做加权抽样
4. 把树样本再映射回原图，检查是否满足非树边约束

关键算法点：

- 生成树构建默认是基于候选密度的 MST 风格策略
- 根节点倾向选择候选集最小的查询点
- `CountCandidateTrees()` 自底向上做动态规划
- 抽样时使用 `std::discrete_distribution`
- 停止条件不是固定轮数，而是基于 Clopper-Pearson 区间的稳定性判断

这一层的关键数据结构是：

- `QueryTree`
- `num_trees_`
- `sample_candidate_weights_`
- `sample_dist_`
- `root_candidates_`

也就是说，FaSTest 的第一阶段不是简单 Monte Carlo，而是“候选树计数 + 分布驱动抽样”。

#### 4.3.5 Graph Sampling 回退

代码入口：`core/lib/SubgraphCounting/CandidateGraphSampling.h`

当 Tree Sampling 的成功数太少时，FaSTest 会回退到 Graph Sampling。

它的核心做法是：

- 选择当前最容易继续扩展的查询顶点
  - 优先 open neighbors 多的点
  - 再选相交候选最少的点
- 对已映射邻居的候选列表做交集
- 执行分层递归采样 `StratifiedSampling`
- 在根候选层面用 OpenMP 并行

这里的关键数据结构是：

- `local_candidates`
- `local_candidate_size`
- `seen`
- `root_candidates_`
- 交集迭代器数组 `iterators`

所以 `M2` 的 C++ 估计阶段，实质是：

`Candidate Space 过滤 -> Tree Sampling 估计 -> 低成功率时 Graph Sampling 回退`

### 4.4 M2 的输出

`M2` 输出的不只是一个分数，而是一整套可观测结果：

- 每条顺序的逐层 `c_hat`
- 每条顺序的累计 `score`
- 实时 `ranking`
- `best_order_id`
- `best_order`
- `best_score`

这个 winner order 会直接喂给 `M3`。

---

## 5. M3：最优顺序落地执行与真实匹配

### 5.1 模块职责

`M3` 的作用，是把 `M2` 选出来的“最有前途的顺序”交给真实子图匹配引擎执行，得到真实的：

- `embedding_count`
- `total_time_seconds`
- `eps`

因此 `M3` 解决的是“估计之后，怎么真正执行”的问题。

### 5.2 Python 侧执行编排

代码入口：

- `server/services/execution_service.py`
- `server/services/graph_format_converter.py`
- `server/services/survey_engine_adapter.py`

流程很直接：

1. 把查询图写成 Survey 需要的 `.graph` 文件
2. 如果 `M2` 给出了 `best_order`，就额外生成临时 `order_file`
3. 调 Survey 二进制执行
4. 解析 stdout，抽取时间、embedding 数、EPS 等指标

这里有一个非常重要的系统边界：

- `SurveyEngineAdapter` 默认配置是 `filter=CFL`、`order=GQL`、`engine=LFTJ`
- 但只要传入 `custom_order`，它就会把 `order` 强制切成 `CUSTOM`

这意味着当前系统默认的真实执行路径其实是：

`CFL 过滤 + CUSTOM 顺序 + LFTJ 枚举`

也就是：过滤和枚举仍由 Survey 默认组合负责，而排序这一步由前面的 `M1 + M2` 决定。

### 5.3 Survey 引擎内部算法

#### 5.3.1 图表示

代码入口：`core/engines/SubgraphMatchingSurvey/vlabel/graph/graph.h`

Survey 内部的 `Graph` 使用 CSR 风格结构：

- `offsets_`
- `neighbors_`
- `labels_`
- `reverse_index_offsets_`
- `reverse_index_`
- `core_table_`
- `edge_index_`
- `nlf_`

这套结构支持：

- 按顶点取邻居
- 按标签反查顶点
- 快速做边存在性判断
- 快速做 NLF 过滤

和 FaSTest 相比，Survey 的图表示更偏“真实枚举执行”，不是为估计而生。

#### 5.3.2 过滤阶段

代码入口：`core/engines/SubgraphMatchingSurvey/vlabel/matching/StudyPerformance.cpp`

Survey 支持 10 种过滤算法，包括：

- `LDF`
- `NLF`
- `GQL`
- `TSO`
- `CFL`
- `DPiso`
- `VEQ`
- `CECI`
- `RM`
- `CaLiG`

当前系统默认接入的是 `CFL`。

过滤阶段的输出数据结构是：

- `ui** candidates`
- `ui* candidates_count`
- 有些算法还会生成过滤树，如 `cfl_tree`、`dpiso_tree`

这些候选集合随后还会被 `BuildTable::buildTables()` 组织成边级索引 `edge_matrix`，供后续枚举使用。

#### 5.3.3 自定义顺序注入

代码入口：`GenerateQueryPlan::generateCustomQueryPlan()`

Survey 对 `CUSTOM` 顺序并不是“盲信任”，而是会显式检查：

- 顺序长度是否等于查询顶点数
- 顶点 ID 是否越界
- 是否有重复顶点
- 是否满足 connected expansion

并且为每个位置计算 `pivot`。  
因此 `M3` 接受的不是任意排列，而是一个受约束、可直接用于枚举回溯的匹配顺序。

#### 5.3.4 LFTJ 枚举

代码入口：

- `core/engines/SubgraphMatchingSurvey/vlabel/matching/EvaluateQuery.h`
- `core/engines/SubgraphMatchingSurvey/vlabel/matching/EvaluateQuery.cpp`

当前系统默认枚举引擎是 `LFTJ`，即 Leapfrog Trie Join 风格的枚举。

从实现细节看，它做了这些事：

- 先生成 backward neighbor 结构 `bn`
- 为每一层维护：
  - `idx`
  - `idx_count`
  - `embedding`
  - `idx_embedding`
  - `valid_candidate_idx`
  - `visited_vertices`
- 在每一层通过 `generateValidCandidateIndex()` 对候选做交集收缩
- 用回溯方式遍历所有合法 embedding

因此 `LFTJ` 在这里既有 join/intersection 的思想，也仍然保留显式回溯框架。

如果启用宏或参数，Survey 还支持：

- failing set pruning
- symmetry breaking
- Spectrum 模式
- 其他枚举引擎如 `EXPLORE`、`QSI`、`VF3`、`DPiso`、`VEQ`、`CECI`、`RM`、`KSS`

不过这些是 Survey 的通用能力，不是当前系统默认走的主路径。

### 5.4 关键数据结构

`M3` 主要数据结构包括：

- `.graph` 文本格式
- `order_file`
- `candidates / candidates_count`
- `edge_matrix`
- `matching_order`
- `pivots`
- `bn / bn_count`
- `embedding / visited_vertices`
- Survey 的 CSR 图结构

这些结构说明 `M3` 不再做“估计”，而是在真实搜索空间上做精确枚举。

### 5.5 M3 的输出

`M3` 最终向上层返回：

- `embedding_count`
- `total_time_seconds`
- `enumeration_time_seconds`
- `filter_time_seconds`
- `build_table_time_seconds`
- `plan_time_seconds`
- `memory_mb`
- `call_count`
- `eps`

所以 `M3` 本质上是一个“真实执行验证器”，也是 `M2` 成败的最终裁判。

---

## 6. 三个模块之间的接口关系

可以把三者之间的关系概括成下面这条链：

### 6.1 M1 -> M2

`M1` 输出：

- 归一化查询图 `NormalizedGraph`
- 一组候选顺序 `orders`

`M2` 消费这些顺序，并把每条顺序切成前缀子图序列。

### 6.2 M2 -> M3

`M2` 输出：

- `best_order`
- `best_score`

`M3` 用 `best_order` 覆盖 Survey 的默认排序阶段，把估计最优的顺序变成真实执行顺序。

### 6.3 M3 -> 前端与实验层

`M3` 输出的真实指标反过来又能用于：

- 在前端展示真实执行结果
- 在实验脚本里评估 `M2` 的排序是否真的有效
- 后续调优加权模型和早停阈值

这也是为什么文档里把 `M3` 放进系统主链路，而不是把它看成一个“可选附属功能”。

---

## 7. 最终结论

如果用一句话概括这个仓库的三段式结构，那么可以写成：

- `M1` 负责“找计划”
- `M2` 负责“评计划”
- `M3` 负责“跑计划”

更细一点说：

- `M1` 是搜索空间构造器，核心是图搜索、剪枝和启发式排序
- `M2` 是代价模型与估计内核，核心是前缀诱导子图、Candidate Space、树采样/图采样、缓存和动态排名
- `M3` 是真实执行器，核心是候选过滤、匹配顺序注入和 LFTJ 精确枚举

因此，当前系统并不是一个普通的“图查询可视化平台”，而是一个以查询计划优化为核心、以 FaSTest 估计为中间层、以 Survey 执行为验证闭环的三阶段图查询优化系统。
