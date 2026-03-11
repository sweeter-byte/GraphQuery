# GraphQuery 升级优化任务清单 (V2)

本文档将整个系统的升级计划拆解为四个独立且互不干扰的核心开发阶段，以方便按模块逐步执行与验收。

---

## 任务一：引入 EPS 代价模型与基线测试模块 (EPS Integration)
**模块属性：后处理与数据科学评估层**
**核心目标：** 修改查询规划中的评价指标，由简单的中间结果大小（基数大小）替换为更科学、更能反映实际运行效率的无偏指标 EPS (Expected Processing Size)，并补齐测试打分机制。

**详细要点：**
1. **研究转换：** 精读论文 *"A Comprehensive Survey and Experimental Study of Subgraph Matching"* 中的 EPS 体系，理清在给定 Data Graph 和 Query 前缀子图条件下计算预期探索开销的具体公式。
2. **算法重构：** 在 Python 端的 `order_generator.py` 和 `CandidateFilter.h` C++ 端调整代价得分的积累函数，令 $cost(Sequence) = \sum EPS$。
3. **真实引擎对比：** 构建独立测试脚本 (`server/tests/`)，把我们生成的任意搜索序列导入 DAF 匹配引擎进行物理运行记录计时。
4. **效果论证图表:** 写一段数据搜集与绘图代码，自动生成【序列EPS预估值 vs 真实DAF耗时】的回归散点图，用以写入论文并提供数据支撑。

---

## 任务二：A* 启发式搜索与图结构剪枝引擎 (A* & Structural Pruning)
**模块属性：核心搜索算法层**
**核心目标：** 将纯穷举的或简单的 Beam Search 生成器，升级为结合图论规律的前向启发式 A* 搜索，通过“有效避免坏的查询骨架”来削减状态规模。

**详细要点：**
1. **A* $f(n)=g(n)+h(n)$ 框架搭建：**
   - $g(n)$ 是当前步骤累计的 EPS代价（由任务一提供）。
   - $h(n)$ 是启发下界评估，需要设计合理的惩罚因子。如：对树形扩展设置惩罚，对包含环(Cycle)/稠密核心(Core)结构的高选择性顶点赋予更高的优先级估值。
2. **结构化空间剪枝逻辑：** 在压入 `PriorityQueue` 前，新增硬性规则（如“若存在两个同等标签度数的对称扩展点，只选取一个破缺分支”、“核心子图必须先匹配完成才能拓展至树叶”）。
3. **指标追踪与空间压缩收益图表：** 代码必须输出并持久化记录每一轮查询**“生成的节点总空间（State Space Size）”**。从而对比有无开启剪枝模式情况下的空间膨胀曲线，作为论文一大亮点输出。

---

## 任务三：单机高性能架构：无感预加载与多核验证并发 (Architecture & Preloading)
**模块属性：前后端系统工程层**
**核心目标：** 不盲目膨胀到多 IP 集群，而是在现有的 Python + C++ Pybind 混合架构上挖掘极致的单机并发与响应体验。

**详细要点：**
1. **后台图谱数据热启动 (Dataset Preloading)：**
   - **前端交互变更：** 监听 `DatasetSelector.tsx` 的选中交互改动，如果用户切换下拉菜单（即使还没点击查询执行），浏览器立即触发 `POST /api/dataset/load`。
   - **单例驻留保障：** 让底层进程将图谱 Index 即刻拉入内存死锁驻留（现有 `EstimatorAdapter` 是做到了），从而将正式点击“提交查询”后的等待期缩小为零。
2. **单节点高并发协程验证：**
   - 彻底优化并配置 `session_pipeline.py`。既然 Index (Data Graph) 是共享读的（Read-Only Memory），即可在 Python 层大胆释放 GIL（因 pybind 已通过 release gil 设置），建立庞大的 Thread Pool (或 Process Pool)。系统将依据宿主机的实际逻辑核心数极限打满处理几十上百条序列 EPS 预测分支。

---

## 任务四：基于 React Flow 优化的动态前端呈现体系 (UX Flow Visualization)
**模块属性：UI/UX与演示增强层**
**核心目标：** 解决现有页面跳动带来的负面感受，并将冷硬的数据以高端的视觉流（Visual Flow）传达给教授。

**详细要点：**
1. **画布 (Canvas) 艺术质感与自然连线翻新：** 
   - 抛弃原生上下固定的锚点（Target/Source Handles）。改造 `QueryGraphEditor.tsx` 为 `Loose` 连通模式，让所有新节点生成的连线依据最短曼哈顿或引力直接平滑挂载到圆弧上。
   - 节点的背景色更换为渐变光晕和高端科技风阴影（不再使用基础 Tailwind 单色配置）。
2. **滚榜组件性能及防“鬼影”缓冲控制：**
   - 为 Leaderboard List 引入 Debounce / Throttle 漏斗缓冲机制（通过 `score_aggregator.py` 后台暂缓或前端接收后截流）。降低 React 每秒的渲染打入率（例如降至 `60fps` 缓动）。
   - 保留 Framer Motion，利用 `layout="position"` 及 Spring Effect 展现名次匀速下滑或新记录平移上窜的顺滑弹跳感。
3. **横向悬浮的序列生长切片 (Prefix Flow Drawer)：** 
   - 增设排行榜（Leaderboard）**每行的单击展开能力**。
   - 弹出独立层：用类似于电影分镜（Film Strip）的方式，横向连放几张微型 React Flow 图块，从只有一个起始节点，逐步连带出边，最终还原整图的序列增长动画。并在每一步旁边，醒目镶嵌该步特有的 EPS / 代价评估值。
