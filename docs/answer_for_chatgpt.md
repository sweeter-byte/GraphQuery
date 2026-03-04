下面是我对你“优化后的图数据库查询系统”需求的**逐条理解 + 系统拆分 + 前后端/通信/架构设计说明**。我会把关键的数据流、模块边界、实时性需求、以及你这个“用基数估计做查询序列排序”的核心机制讲清楚，方便你检查我理解是否完全一致。

> 你上传的说明文档描述的是：基于 FaSTest 的子图匹配基数估计（cardinality estimation）程序，并对其做了多线程加速（OpenMP），包含 **索引阶段（triangle / four-cycle motif index）** 与 **查询阶段（Candidate Space 构建/过滤 + sampling 估计）** 两大阶段。 

---

## 1) 你的目标系统：我理解的“端到端流程”

### A. 系统预置与索引构建（离线/半离线）

1. 系统内置（或可上传）**常见图数据集**（data graph）：例如 human/wordnet/dblp/youtube/patents 等类型（你论文里也用过类似规模的数据）。
2. 用户在前端选择某个数据集后：

   * 后端启动该数据集的 **索引构建任务**（motif index：至少 triangle / four-cycle；以及基础统计信息等）
   * 前端要**可视化展示索引构建过程**（进度、耗时、阶段拆分、可能还有资源占用）

### B. 用户绘制查询图（在线）

3. 前端提供图编辑器：用“顶点/边/标签”等组件画出 query graph（含 vertex label、边连接关系；可能还有方向/属性扩展）。
4. 前端将查询图以结构化格式发送到后端。

### C. 后端生成候选查询序列并实时排序（在线、强交互）

5. 后端收到 query graph 后：

   * 枚举**所有可行的顶点查询顺序序列**（你这里的“查询序列”本质上是一个**matching order / join order** 的候选集合）
   * 前端展示：有哪些序列、数量有多少、以及它们将被评估

6. 对每一个序列：

   * 从序列第一个顶点开始，逐步沿边扩展，形成一系列**查询子图**（prefix subgraphs）
   * 对每个查询子图调用你现有的**子图基数估计程序**得到“该子图在 data graph 上的匹配基数估计”
   * 将这个序列内所有子图的估计值做**累加（累计和）**，作为该序列的代价/评分
   * 后端把每个序列的累计结果**实时推送**给前端
   * 前端对序列列表进行**滚动更新 + 动态排序**（累计和越小越优）

7. 选出累计和最低的“最优序列”后：

   * 前端进行“动态展示查询过程”：即按最优序列从起点开始、逐步扩展到完整查询图（动画/步骤条）
   * 下游接入一个“现有的图查询引擎”，把这个最优序列作为计划输入，让它执行真正的 subgraph matching / pattern query，返回最终结果给前端展示。

---

## 2) 需求拆分：子系统与模块边界

我把它拆成 6 个核心子系统（你后续实现/写报告也更好组织）：

### 2.1 数据集与元数据管理（Dataset Manager）

* 数据集存储：本地文件 / 对象存储 / 数据库登记
* 元信息：|V|、|E|、标签集合、平均度、是否已建索引、索引版本号等
* 提供 API：list datasets / dataset detail / upload / delete（可选）

### 2.2 索引构建服务（Index Build Service）

对应你论文里的 indexing phase：加载图、统计、triangle index、four-cycle index 等（以及你多线程优化策略）。

* 关键要求：**可观测性**（阶段进度、日志、异常、耗时）
* 关键工程点：索引体积可能很大（尤其 four-cycle），需要：

  * 索引落盘策略（内存映射/压缩/分块）
  * 索引版本管理（同一数据集可能多次构建）

### 2.3 查询图建模与校验（Query Graph Service）

* 定义 query graph 的数据结构（顶点、边、标签、可选属性）
* 校验：连通性、是否包含孤立点、标签是否在数据集标签域内（或允许新标签但候选为空）
* 生成后续优化需要的结构：邻接表、度、可能的 spanning tree 等

### 2.4 查询序列枚举器（Order Enumerator）

* 输入：query graph
* 输出：一批候选“顶点查询顺序序列”
* 注意：**“所有序列”在最坏情况下是 n!**，因此这里我理解你说的“枚举所有序列”很可能在工程上需要：

  * 设上限（Top-K / Beam / 规则剪枝）
  * 或者限制在“合法扩展序列”（例如必须保持 prefix 子图连通、每一步扩展必须沿边引入新点）
    但你目前描述是“枚举所有顶点查询顺序序列”，我暂时按字面理解：后端会生成一个候选集合，然后逐个评估。

### 2.5 序列评估器（Cardinality-based Sequence Evaluator）

这是你系统的核心创新链路：

* 对每个序列，生成 prefix 子图集合
* 调用并复用你现成的基数估计（FaSTest 风格 filtering+sampling，且你有并行实现）
* 将每个 prefix 的估计值累加为 score
* 实时把 score 推送前端，前端滚动排序

这里有两个隐含但很关键的定义（我按你的表述理解）：

1. **“查询子图”**：按序列逐步扩展时形成的所有 prefix subgraph。
2. **“序列评分”**：对该序列所有 prefix subgraph 的 estimated cardinality 求和（累计和越小越好）。

### 2.6 下游执行引擎适配（Query Engine Adapter）

* 输入：data graph + query graph + 最优序列（作为 plan/matching order）
* 调用现有引擎执行真实查询
* 返回结果：embedding 列表、计数、或聚合结果（取决于你的引擎能力）
* 前端展示：结果表格/子图高亮等

---

## 3) 前端设计：你需要的页面与交互

### 3.1 页面/模块拆分

1. **数据集选择页**

* 展示数据集列表、规模统计、是否已建索引、索引版本
* 选择后进入“索引构建/加载”页

2. **索引构建可视化页**

* 展示阶段进度条（加载/统计/三角索引/四环索引/落盘）
* 实时日志窗口（可选）
* 完成后进入查询编辑页

3. **查询图编辑器页（核心）**

* 画布：点/边编辑、拖拽、删除
* 顶点属性：label（必选）、可扩展属性
* 边属性：无向/有向（按你系统定义）
* 一键“提交查询”

4. **查询序列评估页（核心）**

* 左侧：候选序列列表（可分页/虚拟滚动）
* 列表列信息：序列 ID、当前累计 score、已评估 prefix 数、状态（评估中/完成/失败）
* 支持实时排序：score 越小越靠前
* 右侧：选中某条序列时展示它的 prefix 估计轨迹（例如折线/表格）

5. **最优序列动态展示 + 执行结果页**

* 动画展示：从起点顶点开始逐步扩展
* 展示“最终选中序列”
* 点击“执行查询”调用下游引擎
* 展示最终匹配结果（列表/高亮子图）

---

## 4) 后端设计：服务拆分与关键接口

我建议你后端按“任务型工作流”组织（因为你有：索引构建、序列评估，这些都不是瞬时请求）。

### 4.1 后端内部模块

* API Gateway（HTTP）
* Job Manager（任务创建、状态机、取消）
* Index Service（构建/加载索引）
* Query Service（校验 query graph）
* Order Enumerator（生成候选序列）
* Evaluator（并行评估序列、调用基数估计）
* Engine Adapter（执行真实查询）
* Storage（数据集/索引/结果缓存）
* Observability（日志、指标、trace）

### 4.2 关键状态与数据结构

* Dataset(id, name, path, stats, index_status, index_version, created_at…)
* IndexBuildJob(job_id, dataset_id, stage, progress, logs_ptr, started_at…)
* QuerySession(session_id, dataset_id, query_graph, orders[], status…)
* OrderEval(order_id, session_id, order_seq[], prefix_count, score, timeline[], status…)
* EngineRun(run_id, session_id, best_order_id, status, result_ptr…)

---

## 5) 前后端通信方式：哪些用 HTTP，哪些用流式推送

你这个系统有**强实时更新**（索引构建进度、序列评估滚动排序），所以我理解需要 **HTTP + WebSocket（或 SSE）** 组合。

### 5.1 HTTP（请求-响应）适合做

* 获取数据集列表/详情
* 发起索引构建任务（返回 job_id）
* 提交 query graph（返回 session_id）
* 拉取候选序列列表（分页）
* 触发“执行最优序列的真实查询”（返回 run_id）
* 获取最终结果（或下载结果）

### 5.2 WebSocket / SSE（服务器推送）适合做

* 索引构建 job 的进度事件：stage_changed / progress / log_line
* 序列评估 session 的增量事件：

  * order_created（候选序列生成）
  * order_progress（某序列又评估了一个 prefix，score 更新）
  * order_done / order_failed
  * leaderboard_update（可选：推送 Top-K 变化）

**为什么必须推送：**你希望“实时传送到前端，前端滚动排序”，如果用轮询会产生高频请求与延迟；推送更自然。

---

## 6) 系统架构图（文字版）

**用户浏览器（前端）**

* Dataset UI
* Index Progress UI
* Query Graph Editor
* Order Leaderboard + Live Sort
* Best Plan Visualization
* Result Viewer

⬇️ HTTP（REST） + WS/SSE（事件流）

**后端 API 层**

* Auth（可选）
* Dataset APIs
* Index Job APIs
* Query Session APIs
* Engine Run APIs

**后端任务与计算层**

* Index Build Worker（CPU 重任务，多线程）
* Order Enumeration Worker（可能 combinational）
* Cardinality Estimation Worker（调用你现有多线程程序/库）
* Result Execution Worker（调用现有图查询引擎）

**存储层**

* Dataset store（原始图）
* Index store（motif index 等）
* Session store（序列、score、timeline）
* Result store（最终查询结果/缓存）

---

## 7) 我觉得你需求里“最值得阐述/可能要提前定规则”的点

下面这些是我从你描述中读到的“隐含难点”，你写系统设计/实现时往往必须先定清楚：

1. **“枚举所有序列”是否真的全量？**
   如果 query graph 有 20~32 个点，n! 不可能全量枚举。工程上通常需要“合法扩展序列 + 剪枝/Top-K”。
   但如果你的 query graph 规模较小（例如课堂 demo 8~12 点），全量还有可能。

2. **序列的“prefix 子图”如何定义成严格可复现？**
   你说“从一个顶点开始，逐步依靠边进行拓展”。这通常意味着每一步加一个新顶点时，必须选一条连接到已匹配部分的边，以保持连通 prefix。
   这会把“序列”从纯排列变成“带扩展约束的序列”。

3. **实时更新的粒度**

   * 你要不要每完成一个 prefix 就推一次？
   * 还是每个序列完成后推一次？
     你的描述更像“每个序列持续更新累计值”，所以我理解是前者（更实时）。

4. **估计程序的复用方式**
   现有基数估计（FaSTest 风格）本身需要 data graph 的索引与 query graph；你现在要对很多 prefix subgraph 重复估计。
   这意味着要考虑：

   * prefix 估计是否能复用中间 Candidate Space（增量更新）
   * 或者就直接多次调用（但要控制耗时）

---

如果你接下来要“检查我理解是否正确”，你可以重点看我是否准确抓住了你这三件事：

* **序列评分 = 对该序列所有 prefix 子图的估计值求累计和，最小者最优**
* **前端需要两类实时可视化：索引构建过程 + 序列评估滚动排序**
* **最优序列不仅用于展示，还要作为 plan 输入喂给下游真实图查询引擎执行**

你如果确认“我理解对了”，我下一步可以继续把：

* query graph 的 JSON schema、
* WebSocket 事件协议、
* 以及后端任务状态机（IndexJob / QuerySession / EvalOrder / EngineRun）
  直接按你这个系统写成可落地的接口草案。
