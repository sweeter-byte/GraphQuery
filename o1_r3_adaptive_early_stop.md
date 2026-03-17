# O1-R3 自适应早停（Adaptive Early Stopping）— 实现文档

## 1 问题背景

M2 阶段对每条候选序列逐层评估前缀子图的基数。当序列数量 $|\Omega|$ 较大时，许多序列在评估到中间层时，其累积代价已经远超当前最优序列，继续评估这些"无望"序列是浪费。

已有的 R1（末尾前缀消除）和 R4（前缀 Memoization）减少了冗余的 C++ 调用次数，但它们不会跳过整条序列。R3 从另一个维度优化：直接剪掉不可能成为最优的序列。

## 2 核心思想

类似于 Alpha-Beta 剪枝：在逐层评估过程中，维护一个"当前最优完整序列代价" $S^*$。对于任意序列 $O_i$，若其在第 $k$ 层的累积代价已满足：

$$\text{score}(O_i, k) > \mu \cdot S^*$$

则跳过 $O_i$ 的后续所有层级评估（$k+1, k+2, \ldots, n$）。

其中 $\mu > 1$ 是松弛系数（multiplier），用于容忍估计误差。$\mu = 2.0$ 表示只有当累积代价超过最优的 2 倍时才剪枝。

## 3 参数说明

通过 `early_stop_config` 控制：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | `false` | 是否启用 R3 |
| `multiplier` | float | 2.0 | 松弛系数 $\mu$，越大越保守（剪枝越少） |
| `min_completed` | int | 1 | 至少有多少条序列完整评估后才开始剪枝 |

API 调用示例：

```json
{
  "dataset_id": "yeast",
  "query_graph": {...},
  "early_stop_config": {
    "enabled": true,
    "multiplier": 2.0,
    "min_completed": 1
  }
}
```

不传 `early_stop_config` 或传 `null` 时，R3 不生效，行为与原始代码完全一致。

## 4 剪枝条件

R3 在以下条件全部满足时触发剪枝：

1. `enabled = true`
2. 已有 ≥ `min_completed` 条序列完整评估完毕
3. 目标序列的当前累积代价 > `multiplier × best_complete_score`
4. 目标序列尚未完成评估

一旦某序列被标记为跳过，后续所有层级（包括 R1 广播的最后一层）都会跳过该序列。

## 5 修改的文件

| 文件 | 变更 |
|------|------|
| `server/services/score_aggregator.py` | 新增 `EarlyStopConfig` dataclass；`ScoreAggregator.__init__` 接受 `early_stop_config`；新增 `should_skip_order()` 方法；`record_estimate` 中跟踪完成序列数和最优完成代价 |
| `server/models.py` | 新增 `EarlyStopConfigModel`（Pydantic）；`SessionCreateRequest` 和 `Session` 添加 `early_stop_config` 字段 |
| `server/routes/sessions.py` | 将 `early_stop_config` 从请求传入 Session，转换为 `EarlyStopConfig` dataclass 传给 `ScoreAggregator` |
| `server/services/session_pipeline.py` | 逐层循环中调用 `should_skip_order()` 跳过被剪枝的序列；R1 广播中跳过被剪枝的序列；新增 R3 统计日志 |
| `server/tests/test_r3_early_stop.py` | 新增 9 个测试用例 |

## 6 不动的文件

- `score_aggregator.py` 中的 `get_weight()` — R3 不影响权重计算
- `prefix_builder.py` — 前缀构建不变
- `estimator_adapter.py` — C++ 桥接层不变
- 前端 — 无需改动

## 7 数据流

```
API 请求
  └── early_stop_config: {"enabled": true, "multiplier": 2.0, "min_completed": 1}
        │
        ▼
routes/sessions.py
  └── 转换为 EarlyStopConfig dataclass → 传入 ScoreAggregator(early_stop_config=esc)
        │
        ▼
session_pipeline.py (Step 4 循环)
  └── 每层开始前，对每个 order 调用 aggregator.should_skip_order(order_idx)
      ├── True  → 跳过该 order 的本层评估（r3_skips++）
      └── False → 正常评估（R4 缓存 / C++ 调用）
        │
        ▼
score_aggregator.py
  └── should_skip_order() 检查：
      1. enabled?
      2. _n_completed >= min_completed?
      3. tracker.score > multiplier * _best_complete_score?
      └── 满足则加入 skipped_orders 集合
```

## 8 向后兼容性

| 场景 | 行为 |
|------|------|
| 不传 `early_stop_config` | `enabled=false`，不剪枝，与原始代码完全一致 |
| `enabled=false` | 同上 |
| `enabled=true` | 启用剪枝，使用指定的 multiplier 和 min_completed |
| `prefix_eval_mode="full"` | R3 仍可独立生效（R3 检查在 R4 缓存检查之前） |

## 9 与其他优化的协同

- R1（末尾前缀消除）：被 R3 跳过的序列在 R1 广播阶段也会被跳过
- R4（前缀 Memoization）：R3 检查在 R4 缓存查找之前执行，被跳过的序列不会触发缓存查找
- O2（加权代价）：R3 使用加权后的累积代价做判断，与 O2 自然协同

## 10 预期收益

- 序列数量越多，剪枝效果越明显（更多"无望"序列被提前终止）
- 查询图越大（层数越多），每条被剪枝序列节省的 C++ 调用越多
- 与 R4 互补：R4 减少同层内的重复调用，R3 减少跨层的无效调用

## 11 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| multiplier 过小导致误剪最优序列 | 默认 2.0（宽松），且 min_completed ≥ 1 确保有基线 |
| 基数估计不稳定导致早期代价偏高 | multiplier 提供容错空间；可通过实验调优 |
| 剪枝后序列排名不完整 | 被剪枝序列保留已有的部分代价，仍参与排名（只是代价偏低） |

## 12 正确性保证

1. `enabled=false` 时 `should_skip_order` 始终返回 False，与原始行为完全一致
2. 9 个单元测试覆盖：禁用/启用、阈值判断、min_completed 约束、持久性、Pipeline 集成
3. 全量测试套件 55 个测试通过，无回归
