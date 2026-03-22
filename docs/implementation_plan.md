# M1/M2/M3 优化方案实施计划

## 方案概述

### 旧方案 vs 新方案

```
旧方案:
  M1(自研序列生成: DFS/Beam/S1-S4剪枝)
    → M2(线性加权代价模型: score = Σ ω_k * ĉ_k, 基于FaSTest前缀基数估计)
      → M3(CFL + CUSTOM order + LFTJ, 输出上限100000)

新方案:
  M1(SubgraphMatchingSurvey的filter-order组合, 去重后约50-80种)
    → M2(待预训练的轻量级分类模型, 从候选序列中选出winner)
      → M3(SubgraphMatchingSurvey的engine, 无输出上限, 返回真实嵌入数量)
```

### 整体数据流

```
用户提交查询图 + 选择数据集
    │
    ▼
M1: 查询验证 & 归一化
    │
    ▼
M1: 对每种有效 (filter, order) 组合，调用 Survey 执行 filter-order 阶段
    │  输出: ~50-80 个查询序列（可能含重复）
    ▼
M2: 去重 → 用预训练模型从候选序列中选出 winner
    │  输出: best_sequence
    ▼
M3: 将 winner 传入 Survey engine 执行（无 embedding 上限）
    │  输出: embedding_count, time, EPS
    ▼
前端展示结果
```

---

## 阶段一：基础设施准备

| 步骤 | 内容 | 前置依赖 | 状态 |
|------|------|---------|------|
| **1.1** | 编译 SubgraphMatchingSurvey 二进制（vlabel 版本） | 源码已就位 | ⬜ |
| **1.2** | 修改 `survey_engine_adapter.py`：支持不传 `-num` 实现无上限枚举；`max_embeddings` 参数改为可选 | 二进制编译完成 | ⬜ |
| **1.3** | 在一个数据集（如 yeast）上跑 100 种 (filter, order) 组合，确定**静态兼容性表**（哪些组合能成功执行） | 1.1 + 1.2 | ⬜ |
| **1.4** | 下载论文使用的真实世界数据集 | 无 | ⬜ |

### 1.1 编译 SubgraphMatchingSurvey 二进制

```bash
cd core/engines/SubgraphMatchingSurvey/vlabel
mkdir -p build && cd build
cmake .. && make -j$(nproc)
```

编译后二进制位于 `build/matching/SubgraphMatching.out`。

### 1.2 修改 survey_engine_adapter.py

- 将 `max_embeddings` 参数默认值从 `100000` 改为 `None`
- 当 `max_embeddings is None` 时，不传 `-num` 参数（Survey 默认使用 `"MAX"` = 无限制）
- 当 `max_embeddings` 有值时，仍传 `-num <value>` 以保持向后兼容

Survey C++ 代码逻辑（`StudyPerformance.cpp:341-348`）：
```cpp
if (input_max_embedding_num == "MAX") {
    output_limit = std::numeric_limits<size_t>::max();  // 无限制
} else {
    sscanf(input_max_embedding_num.c_str(), "%zu", &output_limit);
}
```

### 1.3 确定静态兼容性表

10 filter × 10 order = 100 种组合，在 yeast 数据集 + 一个小查询图上逐一运行：
- `returncode == 0` 且 stdout 包含 `#Embeddings:` → 可行
- 否则 → 不可行

兼容性是算法级属性，不依赖数据集，只需测试一次。

### 1.4 下载数据集

SIGMOD 2020 数据集（10 个 vertex-labeled）下载地址：
- SharePoint: https://hkustconnect-my.sharepoint.com/:u:/g/personal/ssunah_connect_ust_hk/EQnXTic0PK9Fo1gkdDZRKOIBFIyMeBTP5rbju2ZfQdj-QA?e=SfGa8X

SIGMOD 2024 额外 4 个 edge-labeled 数据集（Wordnet18, FreeBase15k, Telecom, DBpedia）需联系论文作者获取。

---

## M3 运行时间开销分析

### 为什么 M3 是瓶颈？

M3 执行的是**真实的回溯搜索枚举**，是整个流水线中计算量最大的阶段：

| 阶段 | 做什么 | 单次耗时 |
|------|--------|---------|
| M1 (filter+order) | 过滤候选顶点 + 生成匹配序列，`-num 1` 跳过枚举 | ~0.01-1 秒 |
| M2 (模型预测) | 从候选序列中选 winner | ~毫秒级 |
| **M3 (枚举)** | **实际回溯搜索所有子图匹配** | **0.1 秒 ~ 60+ 秒** |

### 规模估算

假设 M1 去重后有 N 个唯一序列，需要用多个 engine 跑（训练数据收集阶段）：

| 数据集 | 查询图数 | 估计唯一序列 | × 5 engine | 按 60s 超时上限（最坏） |
|--------|---------|------------|-----------|----------------------|
| yeast (小) | ~1800 | ~5,000-20,000 | 25,000-100,000 次 | ~70 天单核 |
| 大数据集 | 更多 | 更多 | 更多 | 更久 |

**结论：单机串行不现实，需要超算/集群并行。**

### C++ 二进制运行环境

M3 核心是 C++ 编译的 `SubgraphMatching.out`，编译选项：
```
C++14, -O3 -mavx2 -pthread
```

**动态链接依赖**（4 个 `.so` 文件）：
```
build/graph/libgraph.so
build/utility/libutility.so
build/utility/nucleus_decomposition/libnd.so
build/utility/execution_tree/libet.so
```

**单次调用接口**：
```bash
SubgraphMatching.out \
  -d <data_graph_path> \
  -q <query_graph_path> \
  -filter <filter_type> \
  -order <order_type> \
  -engine <engine_type> \
  -time_limit <seconds> \
  [-num <max_embeddings>] \
  [-order_file <custom_order_file>]
```

### 超时与输出控制

存在**两级超时**机制：
1. **C++ 层**：`-time_limit 60`（默认 60 秒），超时后枚举函数返回部分结果
2. **Python 层**：`SIGALRM` 信号（默认 120 秒），包裹整个子进程调用

**输出上限**：`-num <count>` 控制最大嵌入数，默认 `MAX`（无限制），训练数据收集时建议设为 100,000 以控制单次时间。

### 超算部署方案

**可行性**：M3 每次运行完全独立（不同序列 × 不同 engine），天然适合 embarrassingly parallel。

**部署目录结构**：
```
hpc_workspace/
├── bin/SubgraphMatching.out    # C++ 二进制（建议在超算上重新编译）
├── lib/                        # 4 个 .so 文件
├── dataset/                    # 数据图 + 查询图（yeast 仅 7.4MB）
├── tasks/                      # 任务列表 CSV（每行: data_graph, query_graph, filter, order, engine, sequence_file）
├── results/                    # 输出目录
└── submit.sh                   # SLURM array job 脚本
```

**注意事项**：
- 建议在超算上从源码重新编译，避免 glibc 版本和 AVX2 指令集兼容性问题
- 用 SLURM array job 分发任务，每个 task 跑一批序列
- 设置 `LD_LIBRARY_PATH` 指向 `lib/` 目录
- 结果文件按 `dataset/query_id/filter_order_engine.csv` 组织，便于后续合并

---

## 阶段二：实验数据收集

| 步骤 | 内容 | 前置依赖 | 状态 |
|------|------|---------|------|
| **2.1** | 编写批量实验脚本：对每个 (数据集, 查询图) 对，跑所有有效 (filter, order) 组合的 filter-order 阶段，记录输出的查询序列 | 阶段一全部完成 | ⬜ |
| **2.2** | 编写 M3 批量执行脚本：对每个查询序列，用支持 CUSTOM order 的 engine 执行，记录完整字段 | 2.1 | ⬜ |
| **2.3** | 输出原始数据文件（完整字段定义见下方） | 2.2 | ⬜ |

### 2.2 Engine 对 CUSTOM Order 的支持分析

M3 需要用固定的查询序列（CUSTOM order）执行枚举。但并非所有 engine 都接受外部传入的 `matching_order`。

通过分析 `StudyPerformance.cpp` 中各 engine 的调用方式：

**支持 CUSTOM order 的 engine（使用外部传入的 `matching_order`）**：

| Engine | 函数签名 | 说明 |
|--------|---------|------|
| **EXPLORE** | `exploreGraph(..., matching_order, pivots, ...)` | 基础回溯搜索 |
| **LFTJ** | `LFTJ(..., matching_order, ...)` | Leapfrog Trie Join |
| **GQL** | `exploreGraphQLStyle(..., matching_order, ...)` | GraphQL 风格枚举 |
| **QSI** | `exploreQuickSIStyle(..., matching_order, pivots, ...)` | QuickSI 风格 |
| **VF3** | `exploreVF3Style(..., matching_order, pivots, ...)` | VF3 风格 |
| **RM** | `exploreRMStyle(..., matching_order, ...)` | RM 风格 |
| **KSS** | `exploreKSSStyle(..., matching_order, ...)` | KSS 风格 |

**不支持 CUSTOM order 的 engine（使用自己的内部序列结构）**：

| Engine | 函数签名 | 原因 |
|--------|---------|------|
| **VEQ** | `exploreVEQStyle(..., veq_tree, ...)` | 依赖 VEQ 专属树结构，不接受 matching_order |
| **DPiso** | `exploreDPisoStyle(..., dpiso_tree, dpiso_order, weight_array, ...)` | 依赖 DPiso 树 + 权重数组 |
| **CECI** | `exploreCECIStyle(..., ceci_tree, ceci_order, TE_Candidates, NTE_Candidates, ...)` | 依赖 CECI 树 + 专属候选结构 |
| **Spectrum** | `spectrum_analysis(...)` | 特殊用途，枚举多个随机序列 |

**⚠️ 重要发现：C++ 二进制当前不支持 `-order_file` 参数**

Python 适配器（`survey_engine_adapter.py`）传递 `-order CUSTOM -order_file <path>`，但 C++ 代码中：
1. `matchingcommand.cpp` 没有注册 `-order_file` 参数
2. `StudyPerformance.cpp` 的 order type 分支中没有 "CUSTOM" 选项
3. 传入 "CUSTOM" 时会 print "not supported" 但**不会 exit**，导致 `matching_order` 为 NULL

**解决方案**：需要修改 `StudyPerformance.cpp` 添加 CUSTOM order 支持（从文件读取序列），或在 Python 层用其他方式传递序列。

**M3 数据收集建议**：使用 **7 个支持 CUSTOM order 的 engine**（EXPLORE, LFTJ, GQL, QSI, VF3, RM, KSS），排除 VEQ/DPiso/CECI/Spectrum。所有 engine 都支持 `-num MAX`（无嵌入数上限）。

### 2.3 M3 输出字段完整性分析

#### 当前计划记录的字段

原计划：`dataset, query_id, filter, order, sequence, embedding_count, time_seconds, eps`

**问题：字段过少，不足以支撑后续 ML 建模。**

#### C++ 二进制实际输出的全部字段

`StudyPerformance.cpp` stdout 输出（已由 Python 适配器解析）：

| 字段 | 来源 | 说明 | 角色 |
|------|------|------|------|
| `embedding_count` | `#Embeddings: <N>` | 找到的子图匹配数 | **标签** |
| `total_time_seconds` | `Total time (seconds): <f>` | 总执行时间 | **标签** |
| `enumeration_time_seconds` | `Enumerate time (seconds): <f>` | 枚举阶段时间 | **标签** |
| `filter_time_seconds` | `Filter vertices time (seconds): <f>` | 过滤阶段时间 | 上下文 |
| `build_table_time_seconds` | `Build table time (seconds): <f>` | 建表时间 | 上下文 |
| `plan_time_seconds` | `Generate query plan time (seconds): <f>` | 生成序列时间 | 上下文 |
| `load_time_seconds` | `Load graphs time (seconds): <f>` | 图加载时间 | 上下文 |
| `preprocessing_time_seconds` | `Preprocessing time (seconds): <f>` | 预处理总时间 | 上下文 |
| `memory_mb` | `Memory cost (MB): <f>` | 内存消耗 | 上下文 |
| `call_count` | `Call Count: <N>` | 回溯搜索调用次数 | **标签** |
| `candidates_per_vertex` | `Candidates Per Vertex: <csv>` | 每个查询顶点的候选数 | **特征** |
| `total_candidates` | `Total Candidates: <N>` | 候选顶点总数 | **特征** |

此外，`printGraphMetaData()` 输出：
| 字段 | 来源 | 说明 |
|------|------|------|
| `query_vertices` | `\|V\|: <N>` | 查询图顶点数 |
| `query_edges` | `\|E\|: <N>` | 查询图边数 |
| `query_labels` | `\|Σ\|: <N>` | 查询图标签种类数 |
| `query_max_degree` | `Max Degree: <N>` | 查询图最大度 |
| `data_vertices` | 同上 | 数据图顶点数 |
| `data_edges` | 同上 | 数据图边数 |

#### ML 建模需要的完整字段设计

分为三类：**元信息**（标识行）、**特征**（ML 输入）、**标签**（ML 目标）。

**元信息字段**（标识每一行）：
```
dataset, query_file, filter, order, engine, sequence, timed_out
```

**标签字段**（M3 执行结果，用于标注 winner/loser）：
```
embedding_count, enumeration_time_seconds, total_time_seconds, call_count, eps
```

**特征字段**（ML 模型输入候选）：

| 特征 | 来源 | 说明 |
|------|------|------|
| `query_vertices` | 查询图 | 顶点数 |
| `query_edges` | 查询图 | 边数 |
| `query_density` | 计算 | 2*E / (V*(V-1)) |
| `query_labels` | 查询图 | 标签种类数 |
| `query_max_degree` | 查询图 | 最大度 |
| `data_vertices` | 数据图 | 顶点数 |
| `data_edges` | 数据图 | 边数 |
| `candidates_per_vertex` | C++ 输出 | 逗号分隔的每顶点候选数 |
| `total_candidates` | C++ 输出 | 候选总数 |
| `min_candidates` | 计算 | 最小候选数 |
| `max_candidates` | 计算 | 最大候选数 |
| `avg_candidates` | 计算 | 平均候选数 |
| `filter_time_seconds` | C++ 输出 | 过滤耗时 |
| `build_table_time_seconds` | C++ 输出 | 建表耗时 |
| `memory_mb` | C++ 输出 | 内存消耗 |

**序列相关特征**（需额外从序列 + 候选数推导）：

| 特征 | 说明 |
|------|------|
| `seq_first_vertex_candidates` | 序列首顶点的候选数（起点选择影响大） |
| `seq_candidate_order` | 序列中顶点按候选数排列的模式（递增/递减/混合） |
| `seq_candidate_product_log` | log(Π candidates[seq[i]])，估计搜索空间大小 |

#### 建议的完整 CSV schema

```
dataset, query_file, filter, order, engine, sequence,
query_vertices, query_edges, query_density, query_labels, query_max_degree,
data_vertices, data_edges,
candidates_per_vertex, total_candidates, min_candidates, max_candidates, avg_candidates,
filter_time_seconds, build_table_time_seconds, memory_mb,
embedding_count, enumeration_time_seconds, total_time_seconds, call_count, eps, timed_out
```

### 并行化设计

**M1 阶段**（本地即可）：filter-order 组合执行可多进程并行，单次耗时短。

**M3 阶段**（建议超算）：
- 每次运行完全独立，适合 SLURM array job 大规模并行
- 将所有 (dataset, query_id, sequence, engine) 组合写入任务列表 CSV
- 每个 SLURM task 处理一批任务，设置 `-time_limit 60 -num 100000`
- 结果收集后合并为阶段三所需的训练数据格式
- 使用 7 个支持 CUSTOM order 的 engine：EXPLORE, LFTJ, GQL, QSI, VF3, RM, KSS

---

## 阶段三：数据后处理 & 模型训练

| 步骤 | 内容 | 前置依赖 | 状态 |
|------|------|---------|------|
| **3.1** | 用 Python 脚本对原始数据做后处理：按 (dataset, query_id) 分组，标注 winner/loser | 2.3 | ⬜ |
| **3.2** | 特征工程：确定 M2 模型的输入特征（基数估计值 + 待讨论的其他特征） | 3.1 | ⬜ |
| **3.3** | 模型选型 & 训练：选择轻量级分类模型，训练并评估泛化性能 | 3.2 | ⬜ |
| **3.4** | 将训练好的模型集成回 M2 模块 | 3.3 | ⬜ |

### 标注策略

- 按 (dataset, query_id) 分组
- EPS 最高（或执行时间最短）的序列标为 winner
- 其余标为 loser
- 后续可尝试不同标注策略（如 top-3 为 winner、按百分位划分等）

### 模型要求

- 简单、轻量级
- 高泛化能力、鲁棒性
- 分类任务：只需找出最优的 1 个序列
- 不关心其余序列之间的排序关系

---

## 阶段四：系统集成

| 步骤 | 内容 | 前置依赖 | 状态 |
|------|------|---------|------|
| **4.1** | 重写 M1 模块：用 Survey filter-order 替代自研序列生成，接入并行化 | 阶段一 | ⬜ |
| **4.2** | 重写 M2 模块：用训练好的模型替代线性加权评分 | 阶段三 | ⬜ |
| **4.3** | 修改 M3 模块：确保无上限输出、正确解析结果 | 1.2 | ⬜ |
| **4.4** | 端到端测试 | 4.1 + 4.2 + 4.3 | ⬜ |
