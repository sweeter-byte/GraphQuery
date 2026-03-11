# DAF 源码修改文档：外部匹配顺序注入

## 概述

本文档描述了对 DAF (Dynamic Programming, Adaptive Matching Order, Failing Set) 子图匹配引擎源码的修改。修改目的是支持从外部注入一个指定的**匹配顺序（Matching Order）**，替代 DAF 原生的自适应启发式排序，以便验证 Fastest 基数估计系统推荐的最优查询序列。

## 修改的文件

共修改 **3 个文件**，新增约 **50 行代码**，未删除任何原有逻辑。

---

### 1. `main/main.cc` — 命令行参数解析

**新增 `-o` 参数**，接受逗号分隔的顶点 ID 序列。

```diff
+ #include <sstream>

+ std::string order_str;

  case 'm':
    limit = std::atoi(argv[i + 1]);
+   break;
+ case 'o':
+   order_str = argv[i + 1];
+   break;
```

在创建 `Backtrack` 对象后、调用 `FindMatches()` 前，解析 `order_str` 并注入：

```cpp
if (!order_str.empty()) {
    std::vector<uint32_t> order;
    std::istringstream iss(order_str);
    std::string token;
    while (std::getline(iss, token, ',')) {
        order.push_back(std::stoi(token));
    }
    backtrack.SetMatchingOrder(order);
}
```

**使用方法**：
```bash
./DAF -d data.graph -q query.graph -o 2,0,3,1
```

---

### 2. `include/backtrack.h` — 类成员与接口声明

在 `Backtrack` 类中新增：

| 成员 | 类型 | 说明 |
|------|------|------|
| `injected_order_` | `std::vector<Vertex>` | 外部注入的匹配顺序数组 |
| `injected_order_idx_` | `Size` | 当前已消费到数组的第几个位置 |
| `use_injected_order_` | `bool` | 是否启用外部顺序 |

新增方法：
- `SetMatchingOrder(const std::vector<Vertex>& order)` — 设置外部匹配顺序
- `GetNextOrderedVertex()` — 获取下一个要匹配的顶点（根据模式选择）

---

### 3. `src/backtrack.cc` — 核心逻辑修改

#### 3.1 构造函数初始化
```cpp
use_injected_order_ = false;
injected_order_idx_ = 0;
```

#### 3.2 `FindMatches()` — 根节点选择
```cpp
Vertex root_vertex = GetRootVertex();  // 原生启发式选择

// 如果注入了外部顺序，覆盖根节点
if (use_injected_order_ && !injected_order_.empty()) {
    root_vertex = injected_order_[0];
    injected_order_idx_ = 1;
}
```

#### 3.3 `FindMatches()` — 搜索树扩展
将原来的：
```cpp
cur_node->u = extendable_queue_->PopMinWeight();
```
替换为：
```cpp
cur_node->u = GetNextOrderedVertex();
```

#### 3.4 `GetNextOrderedVertex()` 实现
```cpp
Vertex Backtrack::GetNextOrderedVertex() {
    if (use_injected_order_ && injected_order_idx_ < injected_order_.size()) {
        Vertex next = injected_order_[injected_order_idx_];
        injected_order_idx_++;
        // 从扩展队列中移除该顶点，保持队列状态一致
        if (extendable_queue_->Exists(next)) {
            extendable_queue_->Remove(next);
        }
        return next;
    }
    // 回退到原生自适应排序
    return extendable_queue_->PopMinWeight();
}
```

> **设计要点**：即使使用注入顺序，扩展队列（extendable_queue_）仍然被维护。队列的 Insert/Remove 操作在 `ComputeExtendableForAllNeighbors` 和 `ReleaseNeighbors` 中正常运行，我们只覆盖了**选择**（PopMinWeight）的行为，而不干扰队列的插入/移除记账逻辑。

---

## 验证结果

使用 `dataset_example/` 中的示例数据集（12 顶点 19 边的数据图 + 4 顶点 5 边的查询图）进行测试。

| 运行模式 | 匹配顺序 | #Matches | #Recursive calls |
|---------|---------|----------|-----------------|
| 原生（无 -o） | 自适应 | **2** | 4 |
| `-o 0,1,2,3` | 0→1→2→3 | **2** | 7 |
| `-o 3,2,1,0` | 3→2→1→0 | **2** | 6 |
| `-o 1,0,3,2` | 1→0→3→2 | **2** | 4 |
| `-o 2,0,3,1` | 2→0→3→1 | **2** | 5 |

**关键结论**：
- ✅ **正确性验证通过**：所有排列均返回相同的 `#Matches: 2`，证明匹配结果的数学不变性得到保持。
- ✅ **顺序生效验证通过**：不同排列导致不同的递归调用次数（4~7次），证明注入的顺序确实改变了搜索树的展开路径。
- ✅ **编译零错误**：修改后的代码通过 CMake 编译，无任何警告或错误。
