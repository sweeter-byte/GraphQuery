# M2 前缀子图去重优化 — 实现文档

## 1 问题背景

M2 阶段对每条候选序列 $O = (v_1, v_2, \ldots, v_n)$ 的每个前缀子图 $Q_k = Q[\{v_1, \ldots, v_k\}]$ 调用 C++ FaSTest 引擎做基数估计。原始实现中，若有 $|\Omega|$ 条序列、$n$ 个顶点，则总共需要 $n \times |\Omega|$ 次 C++ 调用。

但这些调用中存在大量冗余：不同序列在不同层级可能产生**完全相同的前缀子图**（顶点集合相同 → 诱导子图相同 → 基数估计值相同）。

## 2 核心思想

> 对所有序列的所有前缀子图，建立一个**去重后的唯一前缀集合**，只对集合中的每个唯一前缀调用一次 C++ 估计，然后通过索引将结果映射回各序列的各层级。

### 2.1 去重的数学基础

前缀子图 $Q_k$ 由查询图 $Q$ 在顶点集 $S_k = \{v_1, \ldots, v_k\}$ 上的诱导子图决定。两个前缀子图相同，当且仅当它们的顶点集合相同：

$$Q[S_a] = Q[S_b] \iff S_a = S_b$$

因此，以 `frozenset(vertex_ids)` 作为去重 key 是精确无损的。

### 2.2 冗余来源

| 冗余类型 | 示例 | 说明 |
|---------|------|------|
| 尾部共享 | 所有序列的第 $n$ 层前缀 | $Q_n = Q$ 本身，对所有序列相同 |
| 前缀共享 | $(v_0, v_1, v_2, v_3)$ 和 $(v_0, v_1, v_3, v_2)$ 的第 2 层 | 顶点集 $\{v_0, v_1\}$ 相同 |
| 跨层共享 | 不同序列在不同层级恰好产生相同顶点集 | 较少见但存在 |

## 3 当前实现方案

实现分为两个优化规则，均在 `session_pipeline.py` Step 4 中生效：

### 3.1 R1：末尾前缀消除（Skip Last Prefix）

最后一层（level $n-1$）的前缀子图就是完整查询图 $Q$，对所有序列完全相同。

- 主循环只遍历 `range(n - 1)`
- 循环结束后，单独估计一次 $Q_n$，将结果广播给所有序列
- 节省：$|\Omega| - 1$ 次 C++ 调用

### 3.2 R4：前缀 Memoization（Prefix Deduplication Cache）

维护全局缓存 `prefix_cache: dict[frozenset[int], float]`，在每层估计前检查：

```
对每条序列 O_i 的第 k 层：
  prefix_key = frozenset(O_i[:k+1])

  1. 查 prefix_cache → 命中 → 直接复用，跳过 C++ 调用
  2. 查 pending_by_key（同层内其他序列已提交相同 key）→ 等待结果后复用
  3. 都未命中 → 提交 C++ 估计，结果写入 cache 并广播给等待者
```

关键设计：**同层内的去重**通过 `pending_by_key` 字典实现。同一层中多条序列共享相同前缀时，只有第一条提交到线程池，其余序列在结果返回后自动获得相同估计值。

### 3.3 控制参数

通过 `prefix_eval_mode` 参数控制：

| 值 | 行为 | 用途 |
|----|------|------|
| `"optimized"`（默认） | R1 + R4 全部启用 | 生产使用 |
| `"full"` | 禁用所有优化，逐层逐序列全量估计 | 实验对照基线 |

API 调用示例：
```json
{
  "dataset_id": "yeast",
  "query_graph": {...},
  "prefix_eval_mode": "optimized"
}
```

## 4 实现细节

### 4.1 修改的文件

| 文件 | 变更 |
|------|------|
| `server/models.py` | `SessionCreateRequest` 和 `Session` 添加 `prefix_eval_mode` 字段 |
| `server/routes/sessions.py` | 将 `prefix_eval_mode` 传入 Session 构造 |
| `server/services/session_pipeline.py` | Step 4 循环重写，加入 R1 + R4 逻辑 |
| `server/tests/test_m2_prefix_optimization.py` | 新增 5 个测试用例 |

### 4.2 不动的文件

- `score_aggregator.py` — 接口不变，`record_estimate()` 照常调用
- `prefix_builder.py` — 前缀子图仍然全量预构建（用于 C++ 调用的 payload）
- `estimator_adapter.py` — C++ 桥接层不变
- 前端 — SSE 事件格式不变，前端无感知

### 4.3 数据流

```
原始流程（full 模式）：
  for level in range(n):
    for order in orders:
      c_hat = C++_estimate(prefix[order][level])   ← n × |Ω| 次调用

优化流程（optimized 模式）：
  for level in range(n - 1):                        ← R1: 跳过最后一层
    unique_prefixes = deduplicate(orders, level)     ← R4: 去重
    for prefix_key in unique_prefixes:
      c_hat = C++_estimate(prefix_key)               ← 只调用 |unique| 次
      broadcast(c_hat → all orders with this key)

  c_hat_last = C++_estimate(Q_n)                     ← R1: 估计一次
  broadcast(c_hat_last → all orders)                  ← 广播给所有序列
```

## 5 节省量分析

### 5.1 R1 节省

固定节省 $|\Omega| - 1$ 次调用。

### 5.2 R4 节省

取决于序列间的前缀共享程度。设第 $k$ 层有 $U_k$ 个唯一前缀顶点集：

$$\text{R4 节省} = \sum_{k=0}^{n-2} (|\Omega| - U_k)$$

典型场景：
- 三角形图（3 顶点）：6 条序列，第 0 层 3 个唯一前缀，第 1 层 3 个唯一前缀 → 节省 6 次
- 路径图（4 顶点）：多条序列共享前 2 个顶点 → 节省随序列数增长

### 5.3 总节省

$$\text{总节省} = \underbrace{(|\Omega| - 1)}_{\text{R1}} + \underbrace{\sum_{k=0}^{n-2} (|\Omega| - U_k)}_{\text{R4}}$$

## 6 正确性保证

1. R1 精确无损：$Q_n = Q$ 对所有序列相同，这是数学事实
2. R4 精确无损：相同顶点集的诱导子图完全相同，基数估计值必然相同
3. 排序不变：优化前后每条序列的每层估计值完全一致，因此代价排序不变
4. 测试验证：5 个单元测试覆盖 R1 广播一致性、R4 缓存命中、全量评估完整性

## 7 Git 记录

- Commit: `188264d`
- 分支: `main`
- 消息: `feat: M2 selective prefix evaluation — R1 skip-last + R4 memoization`
