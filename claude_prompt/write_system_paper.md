# Task: Write a LaTeX System Description Document (Chinese + Formal Definitions)

You are working inside the Fastest-par repository.

Your task is to produce a **LaTeX document (written in Chinese)** that describes the system design of the project strictly based on the current repository contents.

The output must be written to:

docs/system_description.tex

Do NOT modify any source code.
Do NOT change existing files.
Only create the `.tex` file.

---

# Step 1 — Read Existing Documentation and Code (Mandatory)

Before writing anything, carefully read:

- docs/stage_a_mvp_tasks.md
- docs/index_artifact_spec.md
- docs/answer_for_chatgpt.md
- README.md

Also inspect relevant implementation files to ensure accuracy:

- server/
- server/services/
- server/routes/
- server/storage.py
- server/models.py
- frontend/index.html

You must ensure the system description **matches the actual implementation**.
Do not invent features that do not exist.
If some behaviors are unclear from code/docs, explicitly mark them as “⚠️ 待确认” and explain what evidence is missing.

---

# Step 2 — Document Goal

The document describes an **optimized graph query planning system** built on top of an existing subgraph cardinality estimator (FaSTest-style CLI).

The system extends the estimator into an interactive system with:

- dataset management and offline index artifacts
- query graph input
- (Stage A) single connected-expansion order generation
- prefix subgraph construction
- prefix cardinality estimation and accumulation
- streaming progress feedback to frontend (SSE)
- a mock downstream execution boundary (Stage A)

The goal is to explain **system architecture, frontend/backend responsibilities, communication protocols, and end-to-end data flow**, not to deeply re-derive the estimator algorithm.

---

# Step 3 — Hard Requirements (Non-Negotiable)

## A. Language and LaTeX Constraints
1) The LaTeX document MUST be written in **Chinese**, including section titles and body text.
2) Use a minimal but compilable LaTeX template. You may use:
   - \documentclass{article}
   - \usepackage[UTF8]{ctex}  (recommended for Chinese)
   - \usepackage{amsmath, amssymb}
   - \usepackage{graphicx}
   - \usepackage{hyperref}
3) The file must compile without errors.

## B. Figures as Placeholders + How to Draw Them
1) At necessary places, insert **figure placeholders** using LaTeX, e.g.:

   \begin{figure}[t]
     \centering
     % TODO: Insert architecture diagram here.
     \caption{系统总体架构示意图（待补图）}
     \label{fig:arch}
   \end{figure}

2) For each placeholder, you MUST explain **how to draw the figure**, and you MAY provide a Mermaid diagram block as guidance (Mermaid is for explanation only; do not require LaTeX to render Mermaid). Example:

   ```mermaid
   flowchart LR
     UI[Frontend] --> API[Backend API]
     API --> SM[Session Manager]
     API --> EA[Estimator Adapter]
     EA --> CLI[Fastest CLI]
    ```

3） Include at least:

One overall architecture diagram placeholder

One data-flow / sequence diagram placeholder

One module-level diagram placeholder (backend internal modules)

## C. Formal Mathematical Definitions (Very Important)

For all concepts that require mathematical precision—especially:

查询图 (Query Graph)

查询序列 / 连通扩展顺序 (Connected Expansion Order)

前缀顶点集合 (Prefix Vertex Set)

前缀子图 (Prefix Subgraph)

查询子图（若使用该术语，需定义其与 prefix subgraph 的关系）

基数估计值与累计代价 (Cardinality Estimate and Accumulated Score)

You MUST provide detailed formal definitions using mathematical language and notation:

define graphs as G = (V, E, L) or similar

define orders as sequences/permutations with connectivity constraint

define prefix induced subgraphs using set-builder notation

state constraints explicitly (e.g., connected-expansion condition)

if there are directed/undirected assumptions, specify clearly (Stage A uses undirected connectivity check)

Definitions must be consistent with docs/stage_a_mvp_tasks.md and the code implementation.

## D. Completeness Requirement

Write as completely as possible:

explain system requirements

explain architecture

explain frontend/backend design

explain communication (REST + SSE)

explain data flow end-to-end

explain file formats and offline index assumptions (artifact schema)

explain Stage A constraints and what is deferred to Stage B/C

Do NOT keep it vague. Aim for a thesis/system-chapter level of detail.

Step 4 — Required Sections (All in Chinese)

Write the document in academic system paper style (中文论文/系统章节风格).
Include the following sections (you may add sub-sections):

1. 引言（Introduction）

Explain:

图查询优化动机

子图匹配的高代价

为什么需要中间子图/前缀子图的基数估计

系统的目标与边界（强调 Stage A）

2. 用户需求分析（User Requirements Analysis）

Clearly distinguish:

用户界面需求（UI/交互）

系统功能需求（API/流程/约束）
Must cover:

数据集选择与索引加载展示（注意：索引离线构建、在线加载/检查）

查询图构建与提交

查询计划（顺序）评估过程展示（Stage A：单一顺序；后续可扩展多顺序）

实时进度反馈（SSE）

结果展示与（mock）下游执行边界

3. 系统总体架构（System Architecture）

Explain separation of:

Frontend

Backend

Estimator CLI/Kernel
Insert an architecture figure placeholder + Mermaid guidance.
Explain responsibilities:

Frontend interface

Backend API server

Session manager

Query processing pipeline

Estimator adapter

4. 前端设计（Frontend Design）

Describe:

数据集选择器

QueryGraph JSON 编辑/输入

session 提交与状态展示

SSE 进度展示（曲线/累计值）

结果/错误展示
Mention Stage A minimal UI philosophy.

5. 后端设计（Backend Design）

Describe backend modules and responsibilities:

dataset registry and index status detection

session manager state machine (queued/running/completed/failed)

query validation + normalization (old_id -> new_id)

connected expansion order generator (Stage A only: one deterministic order)

prefix builder

estimator adapter (CLI invocation, file generation, stdout parsing)
Also explain Stage A concurrency constraint: max 1 running session, return 409 if exceeded.

Include a backend module diagram placeholder + Mermaid guidance.

6. 前后端通信方式（Communication）

Explain:

REST endpoints and request/response schemas (high-level but accurate)

SSE streaming endpoint and event types

event ordering guarantees in Stage A

Include a sequence diagram placeholder + Mermaid guidance.

7. 系统数据流（End-to-End Data Flow）

Provide step-by-step workflow:

dataset selection

index readiness check + coarse index loading events

query graph submission

validation + normalization

generate connected expansion order (single)

build prefix subgraphs

invoke CLI estimator to estimate each prefix

accumulate score and stream events

session completion + result retrieval (+ mock execute)

Be explicit about which module owns each step.

8. 形式化定义：查询子图与前缀子图（Formal Definitions）

This is the most important section.

At minimum, define:

8.1 查询图

Let query graph be Q = (V_Q, E_Q, \ell_V, \ell_E) where:

V_Q: vertex set

E_Q: edge set

\ell_V: vertex label function

\ell_E: edge label function

8.2 连通扩展顺序（查询序列）

Define an order O = (v_1, ..., v_n) as a permutation of V_Q
satisfying connected-expansion constraint:

for every k > 1, exists i < k s.t. (v_i, v_k) in E_Q (treating E_Q as undirected for connectivity)
Explain deterministic tie-breaking used in Stage A if present in code.

8.3 前缀顶点集合与前缀子图

Define prefix vertex set:

S_k = {v_1, ..., v_k}
Define prefix subgraph as induced subgraph:

Q_k = Q[S_k] with E_k = {(u,w) in E_Q | u in S_k and w in S_k}
State: edges are inherited from the original query graph (not arbitrarily chosen).

8.4 基数估计与累计代价

Define estimator output:

\hat{c}_k = Est(Q_k; G, I) (data graph G and index artifacts I)
Define accumulated score:

score(O) = \sum_{k=1}^{n} \hat{c}_k (Stage A evaluates exactly one O)

Also clarify the difference between:

Stage A: single O

Stage B/C: multiple O and ranking

Use math environment and precise notation. Provide clear explanations in Chinese.

9. 实现说明与工程假设（Implementation Notes）

Briefly describe:

Python backend implementation style

estimator CLI invocation model

file-based prefix .graph generation and list file

dataset directory structure

offline index artifact assumption (ref docs/index_artifact_spec.md)

Do not include unnecessary low-level code listings.

10. 小结与扩展路线（Conclusion & Roadmap）

Summarize Stage A capabilities and explicitly state what is deferred:

multi-order enumeration (Top-K)

ranking and pruning

memoization / prefix reuse

real downstream engine integration

online index build

Step 5 — Final Checks

Before finishing:

Ensure all text is Chinese.

Ensure mathematical definitions are consistent and precise.

Ensure all described features exist in code/docs.

Ensure placeholders for figures exist and each includes “how to draw” + Mermaid guidance.

Ensure the .tex file compiles.

Then write the final LaTeX file to:
docs/system_description.tex