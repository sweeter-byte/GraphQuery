# 系统设计文档 (SDD) 技术实现补充细则

本补充文档旨在解决《图查询计划优化系统 SDD》中遗留的具体技术实现细节，填补架构设计与实际编码之间的空白，为开发团队提供明确的接口契约与实现方案。

---

## 1. 权重调优机制 (Score 评估)

**文档原定**：$\mathrm{score}(O) = \sum_{k=1}^{n} \omega_k \cdot \hat{c}_k$，并提及“目前暂设为 1，后续根据实验结果动态调整”。
**实施方案**：
*   **开发初期与联调阶段**：在系统架构层和代码实现中，严格将所有前缀子图的权重 $\omega_k$ **hardcode 设置为 1**。
*   **后续扩展性**：在后端（Python）的 Score Aggregator 模块中，预留一个 `get_weight(k, n)` 函数。在当前阶段，该函数恒返回 `1.0`。如果未来在实验联调中发现某些前缀的方差极大，需要在模型设计上补充动态定权的逻辑时，只需修改此 Python 函数的内部实现，而无需对 C++ 引擎或前端结构进行任何更改。

---

## 2. API 契约协议：前缀子图的内存表示 (Memory Schema)

**背景挑战**：Python 后端生成前缀顶点集合后，需要通过内存传递给 C++。必须定义明确的内存结构格式，以取代之前的 `.graph` 文件序列化落盘方式。

**实施方案**：
采用 **Python 字典 (Dict) 转换为 C++ `struct` / `std::vector`** 的原生内存互操作方案（结合 Pybind11）。

**Python 端数据结构** (传递给 C++ 的标准格式)：
```python
prefix_graph_payload = {
    "num_vertices": 3,
    "num_edges": 2,
    "vertices": [
        {"id": 0, "label": 1},
        {"id": 1, "label": 1},
        {"id": 2, "label": 2}
    ],
    "edges": [
        {"source": 0, "target": 1, "label": 0},
        {"source": 1, "target": 2, "label": 0}
    ]
}
```

**C++ 端接收接口说明**：
在 C++ 端，我们将不再调用读取文件的 `LoadLabeledGraph(string filename)`，而是新增一个纯内存构建的方法 `LoadGraphFromMemory`，其直接接收由 Pybind11 转换过来的 C++ 标准容器。

---

## 3. C++ 接口重构：Pybind11 动态库封装

**背景挑战**：C++ 核心是一个带 `main` 函数的纯命令行工具。必须将其重构为 Python 可调用的 `.so` 动态库。

**实施方案**：
使用 **Pybind11** 进行无缝的 C++/Python 互操作。这能实现“零磁盘 I/O 开销”和“常驻内存对象”。

### 3.1 C++ 核心类重构 (`FastestCore`)

我们需要在 C++ 端提供一个具有状态的 `Wrapper` 类，以便在 Python 端维持一个长生命周期的执行器实例。

**C++ 伪代码契约 (`FastestPybind.cc`)**：
```cpp
#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

namespace py = pybind11;
using namespace GraphLib;

class FastestWrapper {
private:
    DataGraph data_graph_;
    CardinalityEstimation::CardEstOption opt_;
    // 预留的候选空间与采样器缓存

public:
    FastestWrapper() {}

    // 1. 加载数据图与内存索引 (只在 Session 初始化时调用一次)
    void LoadDataGraphAndIndex(const std::string& dataset_name, const std::string& index_dir) {
        // [未来实现] 从 index_dir 反序列化加载
        // [Stage A 暂定] 依旧全量 Load + Preprocess，但保持在类的成员变量中
        // ...
    }

    // 2. 纯内存接收前缀子图并进行一次估算
    double EstimatePrefix(const py::dict& prefix_payload) {
        PatternGraph prefix_graph;
        
        // 解析 payload，直接使用内存构建 PatternGraph (需在 PatternGraph 加此接口)
        int n_v = prefix_payload["num_vertices"].cast<int>();
        int n_e = prefix_payload["num_edges"].cast<int>();
        // ... 构建 prefix_graph 的顶点与边
        
        prefix_graph.ProcessPattern(data_graph_);
        prefix_graph.EnumerateLocalTriangles();
        prefix_graph.query_EnumerateLocalFourCycles();
        
        CardinalityEstimation::FaSTestCardinalityEstimation estimator(&data_graph_, opt_);
        return estimator.EstimateEmbeddings(&prefix_graph);
    }
};

// Pybind11 模块定义
PYBIND11_MODULE(fastest_core, m) {
    py::class_<FastestWrapper>(m, "FastestEstimator")
        .def(py::init<>())
        .def("load_data_graph_and_index", &FastestWrapper::LoadDataGraphAndIndex)
        .def("estimate_prefix", &FastestWrapper::EstimatePrefix);
}
```

**Python 调用端伪代码**：
```python
import fastest_core

# 1. 服务启动或 Session 创建时加载一次数据和索引 (耗时操作，仅一次)
estimator = fastest_core.FastestEstimator()
estimator.load_data_graph_and_index("yeast", "/path/to/index")

# 2. 对每个前缀只传递内存对象 (极速运算)
score = 0.0
for prefix_payload in prefixes:
    est_val = estimator.estimate_prefix(prefix_payload)
    score += 1.0 * est_val  # 权重固定为 1
```

---

## 4. 离线索引的持久化 (Serialize / Deserialize)

**背景挑战**：C++ 代码目前（例如 `EnumerateLocalTriangles`）都是基于内存即时构建结构化索引，系统要求在用户使用前具备“离线读取”已构建索引的能力以保证实时性。

**实施方案**：
我们必须在 C++ 底层补充落盘和读取的序列化规范。我们将采用轻量级、原生且性能极高的二进制流 (`std::ifstream` / `std::ofstream`) 方案。

### 4.1 持久化时机与职责
开发一个独立的 CLI 命令或模式（例如 `./Fastest --build-index -d yeast`）。该命令在 CI/CD 或管理员维护期运行，专门执行：
1. `D.LoadLabeledGraph`
2. `D.Preprocess()`
3. `D.data_EnumerateLocalFourCycles()`
4. `D.EnumerateLocalTriangles()`
5. **执行 Serialize 操作**

### 4.2 C++ 序列化接口要求
开发人员需要在 `DataGraph` 类及相关结构中实现二进制流的序列化：

```cpp
// 在 DataGraph.h 中新增
class DataGraph {
public:
    // ... 原有代码
    
    // 将在内存中生成的结构化索引写入磁盘
    void SerializeIndex(const std::string& index_dir) {
        // 伪代码: 保存 LocalTriangles
        std::ofstream tri_out(index_dir + "/triangles.bin", std::ios::binary);
        // ... write vector sizes and data
        tri_out.close();
        
        // 伪代码: 保存 FourCycles
        std::ofstream cycle_out(index_dir + "/four_cycles.bin", std::ios::binary);
        // ... write data
        cycle_out.close();
    }
    
    // 线上运行时，直接将二进制文件挂载回内存对象
    void DeserializeIndex(const std::string& index_dir) {
        std::ifstream tri_in(index_dir + "/triangles.bin", std::ios::binary);
        // ... read counts and directly populate vectors/arrays
        tri_in.close();
        
        // ... read FourCycles
    }
};
```

**总结**：通过实现二进制的 `SerializeIndex` 和 `DeserializeIndex`，我们能在不到几百毫秒内将复杂的大数据图结构装载回 Python 中的 `FastestWrapper` 单例中，彻底实现了 SDD 中对实时与预构建解耦的架构要求。
