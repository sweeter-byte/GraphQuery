# M1 搜索空间剪枝（Pruned Order Generation）— 实现文档

## 1 问题背景

M1 阶段生成所有合法的连通扩展序列 $\Omega(Q)$。原始实现使用盲目 DFS（精确模式）或简单 Beam Search，搜索空间随查询图顶点数阶乘增长。对于 $|V_Q| = 8$ 的查询图，精确模式可能生成数千条序列，大部分是冗余的（结构等价的序列产生相同的执行代价）。

## 2 四种剪枝策略

### S1: 等价顶点剪枝（Symmetry Breaking）

同一扩展层中，若两个候选顶点具有相同的 (label, degree, 邻居标签多重集)，则它们"结构等价"——只展开一个代表。

**数学定义**：顶点 $u, v$ 等价当且仅当：
- $\ell(u) = \ell(v)$（标签相同）
- $\text{sorted}(\{\ell(w) : w \in N(u)\}) = \text{sorted}(\{\ell(w) : w \in N(v)\})$（邻居标签多重集相同）

**效果**：
| 图类型 | Baseline 序列数 | Pruned 序列数 | 缩减比 |
|--------|----------------|--------------|--------|
| K4（全同标签） | 24 | 1 | 96% |
| Star-5（叶同标签） | 48 | 2 | 96% |
| Triangle（2同标签） | 6 | 3 | 50% |
| Path-5（全异标签） | 16 | 16 | 0% |

### S2: Core-First 排序

计算查询图的 k-core 分解。高 core number 的顶点优先展开（约束更强），度为 1 的叶子顶点推迟到最后。

排序键：`(safety_penalty, -core_number, -degree, vertex_id)`

### S3: A* 启发式搜索

用优先队列替代盲目 DFS：
- $g(n)$ = 已展开顶点的累积代价（基于度数的启发式）
- $h(n)$ = 剩余顶点的下界估计（$\sum_{v \in \text{remaining}} 1/\deg(v)$）
- 剪枝：$f(n) > \text{cost\_factor} \times$ 当前最优完整序列的代价时丢弃

`cost_factor` 默认 2.0，`max_orders` 默认 500。

### S4: 邻居安全优先

候选顶点的所有查询图邻居都已在部分序列中 → "安全"扩展（全约束），优先展开。仅有部分邻居在序列中的"悬挂"扩展降低优先级。

## 3 实现架构

```
server/services/order_strategies/
├── __init__.py          # 调度器：根据 strategy 参数选择 baseline 或 pruned
├── baseline.py          # 薄包装，委托给原始 order_generator.py
├── pruned.py            # 剪枝版序列生成（S1-S4 组合）
└── graph_analysis.py    # 共享图分析工具（k-core、等价类、邻接表）
```

原始 `order_generator.py` 完全不动。

## 4 控制参数

通过 `order_strategy` 字段控制（已在 `SessionCreateRequest` 和 `Session` 中）：

| 值 | 行为 |
|----|------|
| `"baseline"` | 委托给原始 `order_generator.py`，行为完全不变 |
| `"pruned"` | 使用 S1-S4 剪枝策略 |

API 调用示例：

```json
{
  "dataset_id": "yeast",
  "query_graph": {...},
  "order_strategy": "pruned"
}
```

不传 `order_strategy` 时默认 `"baseline"`，与原始代码完全一致。

## 5 文件清单

| 文件 | 状态 | 说明 |
|------|------|------|
| `server/services/order_strategies/__init__.py` | 已有 | OrderStrategy 枚举 + generate_orders 调度器 |
| `server/services/order_strategies/baseline.py` | 已有 | 委托给原始 order_generator |
| `server/services/order_strategies/pruned.py` | 已有 | S1-S4 组合剪枝 |
| `server/services/order_strategies/graph_analysis.py` | 已有 | k-core、等价类、邻接表 |
| `server/services/order_generator.py` | 不动 | 原始基线代码 |
| `server/models.py` | 已有 | `order_strategy` 字段 |
| `server/services/session_pipeline.py` | 已有 | 从 order_strategies 导入 |
| `server/tests/test_m1_pruned_orders.py` | 新增 | 20 个测试用例 |

## 6 数据流

```
API 请求
  └── order_strategy: "pruned"
        │
        ▼
session_pipeline.py (Step 3)
  └── strategic_generate_orders(graph, strategy=session.order_strategy)
        │
        ▼
order_strategies/__init__.py
  └── OrderStrategy("pruned") → generate_orders_pruned(graph)
        │
        ▼
pruned.py
  ├── graph_analysis.build_adjacency()
  ├── graph_analysis.compute_k_core()        → S2 排序依据
  ├── graph_analysis.compute_equivalence_classes() → S1 剪枝依据
  └── A* 搜索循环：
      ├── S1: 每层只展开等价类代表
      ├── S2: 候选按 core number 降序排列
      ├── S3: f > cost_factor * best_cost → 剪枝
      └── S4: 安全扩展优先
```

## 7 向后兼容性

| 场景 | 行为 |
|------|------|
| 不传 `order_strategy` | 默认 `"baseline"`，委托给原始 order_generator |
| `order_strategy = "baseline"` | 同上 |
| `order_strategy = "pruned"` | 使用 S1-S4 剪枝 |
| 无效值 | 抛出 ValueError |

## 8 正确性保证

1. `strategy="baseline"` 时行为与原始完全一致
2. 所有 pruned 序列都是合法的连通扩展序列（测试验证）
3. 20 个单元测试覆盖：图分析工具、等价类剪枝、序列合法性、调度器、Pipeline 集成
4. 全量测试套件通过，无回归

## 9 与 M2 优化的协同

- 序列数减少 → R4 缓存命中率可能降低（更少的共享前缀），但总 C++ 调用次数仍然减少
- 序列数减少 → R3 早停的收益降低（更少的"无望"序列），但总评估量仍然减少
- 净效果：M1 剪枝 + M2 优化叠加，端到端加速
