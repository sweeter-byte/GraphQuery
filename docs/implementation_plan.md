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

## 阶段二：实验数据收集

| 步骤 | 内容 | 前置依赖 | 状态 |
|------|------|---------|------|
| **2.1** | 编写批量实验脚本：对每个 (数据集, 查询图) 对，跑所有有效 (filter, order) 组合的 filter-order 阶段，记录输出的查询序列 | 阶段一全部完成 | ⬜ |
| **2.2** | 编写 M3 批量执行脚本：对每个查询序列，用固定 engine（如 LFTJ）执行，记录 embedding_count、time、EPS | 2.1 | ⬜ |
| **2.3** | 输出原始数据文件，每行格式：`dataset, query_id, filter, order, sequence, embedding_count, time_seconds, eps` | 2.2 | ⬜ |

### 并行化设计

M1 阶段的 filter-order 组合执行可以并行化：
- 多进程/多线程同时运行多个 Survey 子进程
- 需要控制并发度，避免 CPU/内存过载

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
