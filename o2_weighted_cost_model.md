# O2 位置-拓扑感知加权代价模型 — 实现文档

## 1 问题背景

M2 阶段对每条候选序列 $O = (v_1, v_2, \ldots, v_n)$ 计算代价：

$$\text{Cost}(O) = \sum_{k=1}^{n} \omega_k \cdot \hat{c}_k$$

原始实现中 $\omega_k \equiv 1.0$（等权求和），即所有前缀子图对代价的贡献相同。

但这与子图匹配的实际执行过程不符：

- **位置效应**：序列前部的顶点决定搜索树的根结构，对执行时间的影响远大于末尾顶点。早期高基数意味着搜索树在根部爆炸，后续剪枝难以弥补。
- **拓扑效应**：含环的前缀子图约束更强，其基数估计值对执行时间的预测能力更高。树形前缀约束弱，估计值的信息量较低。

## 2 加权代价模型

用参数化权重函数替代等权求和：

$$\text{Cost}(O) = \sum_{k=1}^{n} \omega(k, Q_k) \cdot \hat{c}_k$$

其中：

$$\omega(k, Q_k) = \alpha(k) \cdot \beta(Q_k)$$

### 2.1 位置因子 $\alpha(k)$

$$\alpha(k) = \left(\frac{n - k + 1}{n}\right)^\gamma$$

- $\gamma > 0$ 为衰减指数
- $\gamma = 1$：线性衰减，第 1 个前缀权重为 1.0，最后一个为 $1/n$
- $\gamma > 1$：前部权重更集中，衰减更快
- $\gamma < 1$：衰减更平缓，接近等权

直觉：序列前部的前缀对执行时间影响更大，应赋予更高权重。

### 2.2 拓扑因子 $\beta(Q_k)$

$$\beta(Q_k) = 1 + \lambda \cdot \frac{\max(|E_k| - |V_k| + 1, \ 0)}{|V_k|}$$

- $|E_k|, |V_k|$：前缀子图 $Q_k$ 的边数和顶点数
- $|E_k| - (|V_k| - 1)$：超出树的多余边数（环数的近似）
- 当 $Q_k$ 是树时 $\beta = 1$（无额外权重）
- 含环越多 $\beta$ 越大，表示该前缀约束更强、估计值更有信息量

### 2.3 超参数

| 参数 | 含义 | 建议搜索范围 | 默认值 |
|------|------|------------|--------|
| $\gamma$ | 位置衰减指数 | {0.5, 1.0, 1.5, 2.0} | 1.0 |
| $\lambda$ | 拓扑敏感系数 | {0.0, 0.5, 1.0, 2.0} | 0.0 |

当 $\gamma = 1, \lambda = 0$ 时，$\omega(k, Q_k) = \alpha(k)$，退化为纯位置衰减。
当 $\gamma = 0$ 时（虽然不建议），$\alpha = 1$，退化为纯拓扑加权。

### 2.4 数值示例

以 4 顶点查询图为例（$n = 4$），$\gamma = 1.0, \lambda = 1.0$：

| 层级 $k$ | $\alpha(k)$ | 前缀拓扑 | $|E_k|$ | $|V_k|$ | $\beta(Q_k)$ | $\omega(k)$ |
|----------|-------------|---------|---------|---------|--------------|-------------|
| 1 | 1.00 | 单顶点 | 0 | 1 | 1.00 | 1.00 |
| 2 | 0.75 | 边 | 1 | 2 | 1.00 | 0.75 |
| 3 | 0.50 | 三角形 | 3 | 3 | 1.33 | 0.67 |
| 4 | 0.25 | 完整图 | 5 | 4 | 1.50 | 0.38 |

对比等权模型（$\omega_k = 1.0$），加权模型显著降低了末尾前缀的贡献，同时提升了含环前缀的权重。

## 3 实现方案

### 3.1 控制参数

通过 `weight_config` 参数控制：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `mode` | str | `"uniform"` | `"uniform"` = 等权（$\omega = 1.0$），`"weighted"` = 位置-拓扑加权 |
| `gamma` | float | 1.0 | 位置衰减指数 |
| `lam` | float | 0.0 | 拓扑敏感系数 |

API 调用示例：

```json
{
  "dataset_id": "yeast",
  "query_graph": {...},
  "weight_config": {
    "mode": "weighted",
    "gamma": 1.5,
    "lam": 1.0
  }
}
```

不传 `weight_config` 或传 `null` 时，等价于 `mode="uniform"`，行为与原始代码完全一致。

### 3.2 修改的文件

| 文件 | 变更 |
|------|------|
| `server/services/score_aggregator.py` | 新增 `WeightConfig` dataclass；`get_weight(k, n)` 扩展为 `get_weight(k, n, *, n_edges, n_vertices, config)`；`ScoreAggregator.__init__` 接受 `weight_config`；`record_estimate` 接受 `n_edges, n_vertices` |
| `server/models.py` | 新增 `WeightConfigModel`（Pydantic）；`SessionCreateRequest` 和 `Session` 添加 `weight_config` 字段 |
| `server/routes/sessions.py` | 将 `weight_config` 从请求传入 Session，并转换为 `WeightConfig` dataclass 传给 `ScoreAggregator` |
| `server/services/session_pipeline.py` | 4 个 `record_estimate` 调用点传入前缀的 `n_edges` 和 `n_vertices` |
| `server/tests/test_o2_weighted_cost.py` | 新增 13 个测试用例 |

### 3.3 不动的文件

- `prefix_builder.py` — `PrefixPayload` 已有 `num_vertices` 和 `num_edges` 字段，无需修改
- `estimator_adapter.py` — C++ 桥接层不变
- 前端 — SSE 事件中 `weight` 字段已存在（`prefix_progress` 事件），前端无需改动

### 3.4 关键代码

权重函数（`score_aggregator.py`）：

```python
def get_weight(k, n, *, n_edges=0, n_vertices=0, config=None):
    if config is None or config.mode == "uniform":
        return 1.0

    alpha = ((n - k + 1) / n) ** config.gamma

    if n_vertices > 0 and config.lam > 0:
        excess_edges = n_edges - (n_vertices - 1)
        beta = 1.0 + config.lam * max(excess_edges, 0) / n_vertices
    else:
        beta = 1.0

    return alpha * beta
```

Pipeline 调用（`session_pipeline.py`，以正常 C++ 结果为例）：

```python
pfx = all_prefixes[order_idx][level]
events = aggregator.record_estimate(
    order_idx, level, c_hat,
    n_edges=pfx.num_edges, n_vertices=pfx.num_vertices,
)
```

### 3.5 数据流

```
API 请求
  └── weight_config: {"mode": "weighted", "gamma": 1.5, "lam": 1.0}
        │
        ▼
routes/sessions.py
  └── 转换为 WeightConfig dataclass → 传入 ScoreAggregator(weight_config=wc)
        │
        ▼
session_pipeline.py (Step 4 循环)
  └── 每次 record_estimate 时传入 prefix 的 n_edges, n_vertices
        │
        ▼
score_aggregator.py
  └── get_weight(k, n, n_edges=..., n_vertices=..., config=self.weight_config)
      └── 返回 alpha * beta → 乘以 c_hat → 累加到 score
```

## 4 向后兼容性

| 场景 | 行为 |
|------|------|
| 不传 `weight_config` | `mode="uniform"`，$\omega = 1.0$，与原始代码完全一致 |
| `weight_config.mode = "uniform"` | 同上 |
| `weight_config.mode = "weighted"` | 启用加权，使用指定的 $\gamma, \lambda$ |
| 旧版前端调用 | 无 `weight_config` 字段 → 默认 `None` → uniform 模式 |

`record_estimate` 的 `n_edges` 和 `n_vertices` 参数为 keyword-only 且有默认值 0，不传时 `beta = 1.0`，不影响已有调用方。

## 5 实验对照设计

O2 的有效性需要通过实验验证（见 `experiment_design.md` 中 E-O2 和 `m2_optimization_proposal.md` 3.2 节）。关键实验：

1. **超参数网格搜索**（E-O2b）：在标定集上搜索最优 $(\gamma, \lambda)$
2. **加权 vs 等权排序对比**（E-O2a）：比较两种模式的 Top-1 序列在 M3 中的真实执行时间
3. **跨数据集泛化性**（E-O2c）：验证在一个数据集上调优的参数在其他数据集上是否仍然有效

实验时通过 API 参数切换模式：

```python
# 等权基线
resp = httpx.post(url, json={..., "weight_config": {"mode": "uniform"}})

# 加权模型
resp = httpx.post(url, json={..., "weight_config": {"mode": "weighted", "gamma": 1.5, "lam": 1.0}})
```

## 6 正确性保证

1. `mode="uniform"` 时 `get_weight` 返回 1.0，与原始硬编码行为完全一致
2. 13 个单元测试覆盖：权重数学公式、边界条件、聚合器集成、Pipeline 端到端
3. 全量测试套件 46 个测试通过，无回归

## 7 Git 记录

- Commit: `a8ae31a`
- 分支: `main`
- 消息: `feat: O2 position-topology aware weighted cost model + E8 experiment design`
