# Filter-Order 兼容性表

测试环境：yeast 数据集 + query_dense_16_1.graph，engine = LFTJ

## 结论

- **100 种组合中 81 种可行，19 种不可行**
- **CECI filter 与所有 order 不兼容**（10 种全部失败）
- **CECI order 与所有 filter 不兼容**（10 种全部失败，其中 CECI+CECI 重复计算一次）
- 除 CECI 外，其余 9 filter × 9 order = 81 种组合**全部可行**

## 兼容性矩阵

| filter \ order | QSI | GQL | TSO | CFL | DPiso | CECI | RI | VF2PP | VF3 | RM |
|---------------|-----|-----|-----|-----|-------|------|----|-------|-----|----|
| **LDF**       | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |
| **NLF**       | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |
| **GQL**       | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |
| **TSO**       | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |
| **CFL**       | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |
| **DPiso**     | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |
| **VEQ**       | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |
| **CECI**      | FAIL| FAIL| FAIL| FAIL| FAIL  | FAIL | FAIL|FAIL  | FAIL| FAIL|
| **RM**        | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |
| **CaLiG**     | OK  | OK  | OK  | OK  | OK    | FAIL | OK | OK    | OK  | OK |

## 有效组合列表

去掉 CECI filter 和 CECI order 后，有效 (filter, order) 对共 **81 种**：

- 9 个有效 filter: LDF, NLF, GQL, TSO, CFL, DPiso, VEQ, RM, CaLiG
- 9 个有效 order: QSI, GQL, TSO, CFL, DPiso, RI, VF2PP, VF3, RM

## 备注

- 兼容性是算法级属性，与数据集无关，无需在其他数据集上重复测试
- CECI filter 失败的原因是 CECI 的 filter 阶段产生的候选集格式（column-based）与其他 order 算法不兼容
- CECI order 失败的原因是它依赖 CECI filter 产生的特定数据结构
