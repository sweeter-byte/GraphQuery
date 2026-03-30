# M1/M3 Analysis Report

## Scope

This report analyzes the batch M1 candidate-sequence data under `results/m1_data/` and the batch M3 enumeration data under `results/m3_data/`. The analysis follows the task specification exactly: dataset-quality assessment, M1 sequence diversity, engine/sequence interaction, selection difficulty, position-level effects, and concrete recommendations for the future M2 batch experiment.

## Part 1: Data Overview and Quality

### Row Counts

| dataset | m1_rows | m3_rows | m1_queries | m3_queries |
| --- | --- | --- | --- | --- |
| dblp | 583200 | 222591 | 7200 | 587 |
| eu2005 | 550800 | 148800 | 6800 | 404 |
| hprd | 583200 | 2095855 | 7200 | 4468 |
| human | 583200 | 202145 | 7200 | 718 |
| patents | 553300 | 287603 | 6832 | 801 |
| wordnet | 583200 | 63800 | 7200 | 277 |
| yeast | 583200 | 86400 | 7200 | 174 |
| youtube | 583200 | 185410 | 7200 | 615 |

### M3 Status Distribution by Dataset

| dataset | OK | TIMEOUT | CRASH |
| --- | --- | --- | --- |
| dblp | 169765 | 17922 | 34904 |
| eu2005 | 63054 | 64007 | 21739 |
| hprd | 1662718 | 10485 | 422652 |
| human | 137461 | 33374 | 31310 |
| patents | 126273 | 119102 | 42228 |
| wordnet | 18014 | 36465 | 9321 |
| yeast | 61148 | 7975 | 17277 |
| youtube | 88416 | 69759 | 27235 |

### Engine Reliability

| engine | OK | TIMEOUT | CRASH | ok_rate | timeout_rate | crash_rate | failure_rate |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EXPLORE | 419054.0 | 51378.0 | 0.0 | 89.1% | 10.9% | 0.0% | 10.9% |
| LFTJ | 414808.0 | 55597.0 | 0.0 | 88.2% | 11.8% | 0.0% | 11.8% |
| QSI | 414113.0 | 56258.0 | 0.0 | 88.0% | 12.0% | 0.0% | 12.0% |
| KSS | 410046.0 | 60220.0 | 0.0 | 87.2% | 12.8% | 0.0% | 12.8% |
| GQL | 386156.0 | 84094.0 | 0.0 | 82.1% | 17.9% | 0.0% | 17.9% |
| RM | 282672.0 | 48922.0 | 138771.0 | 60.1% | 10.4% | 29.5% | 39.9% |
| VF3 | 0.0 | 2620.0 | 467895.0 | 0.0% | 0.6% | 99.4% | 100.0% |

Engine focus recommendation: `EXPLORE, LFTJ, QSI`.

Engine exclusion recommendation: `KSS, GQL, RM, VF3`.

Rationale: these focused engines deliver the highest aggregate OK-rates while still winning a meaningful share of per-sequence contests.

## Part 2: M1 Sequence Analysis

### Unique Candidate Counts per Query

| dataset | median | mean | min | max |
| --- | --- | --- | --- | --- |
| dblp | 30.0 | 27.306944444444444 | 1 | 49 |
| eu2005 | 23.0 | 24.043529411764705 | 1 | 49 |
| hprd | 15.0 | 14.344166666666666 | 1 | 43 |
| human | 11.0 | 12.324166666666667 | 0 | 47 |
| patents | 23.0 | 25.815573770491802 | 1 | 49 |
| wordnet | 7.0 | 8.818888888888889 | 0 | 49 |
| yeast | 16.0 | 17.922083333333333 | 1 | 49 |
| youtube | 16.0 | 18.935833333333335 | 1 | 49 |

Overall, the median query has `15` unique sequences and the 75th percentile is `27`.

### Which Filter/Order Pairs Add the Most Diversity

| filter | order | query_count | rows | unique_sequences | median_unique_sequences |
| --- | --- | --- | --- | --- | --- |
| GQL | GQL | 7200 | 56831 | 56772 | 1.0 |
| VEQ | GQL | 7200 | 56831 | 56767 | 1.0 |
| CFL | GQL | 7200 | 56831 | 56761 | 1.0 |
| GQL | VF3 | 7200 | 56831 | 56759 | 1.0 |
| GQL | RM | 7200 | 56831 | 56757 | 1.0 |
| VEQ | VF3 | 7200 | 56831 | 56755 | 1.0 |
| VEQ | RM | 7200 | 56831 | 56750 | 1.0 |
| GQL | RI | 7200 | 56831 | 56738 | 1.0 |
| TSO | GQL | 7200 | 56831 | 56738 | 1.0 |
| NLF | GQL | 7200 | 56832 | 56736 | 1.0 |
| VEQ | RI | 7200 | 56831 | 56731 | 1.0 |
| CFL | RM | 7200 | 56831 | 56730 | 1.0 |
| CFL | VF3 | 7200 | 56831 | 56727 | 1.0 |
| TSO | RM | 7200 | 56831 | 56709 | 1.0 |
| TSO | VF3 | 7200 | 56831 | 56708 | 1.0 |

### Sequence Diversity

| dataset | unique_fraction | duplicated_fraction | max_method_overlap |
| --- | --- | --- | --- |
| dblp | 0.37037037037037035 | 0.4074074074074074 | 10.0 |
| eu2005 | 0.2839506172839506 | 0.5357142857142857 | 11.0 |
| hprd | 0.18518518518518517 | 0.6 | 17.0 |
| human | 0.13580246913580246 | 0.75 | 18.0 |
| patents | 0.2839506172839506 | 0.5278637770897833 | 11.0 |
| wordnet | 0.08641975308641975 | 0.75 | 35.0 |
| yeast | 0.19753086419753085 | 0.631578947368421 | 15.0 |
| youtube | 0.19753086419753085 | 0.7018518518518518 | 18.0 |

Dense vs sparse candidate diversity:

| dataset | mode | unique_sequences |
| --- | --- | --- |
| dblp | dense | 29.0 |
| dblp | sparse | 31.0 |
| eu2005 | dense | 27.0 |
| eu2005 | sparse | 18.0 |
| hprd | dense | 15.0 |
| hprd | sparse | 15.0 |
| human | dense | 9.0 |
| human | sparse | 13.0 |
| patents | dense | 22.0 |
| patents | sparse | 25.0 |
| wordnet | dense | 7.0 |
| wordnet | sparse | 7.0 |
| yeast | dense | 16.0 |
| yeast | sparse | 16.0 |
| youtube | dense | 16.0 |
| youtube | sparse | 16.0 |

## Part 3: Engine Performance and Sequence-Engine Interaction

### Which Engine Is Fastest Most Frequently

| dataset | engine | fastest_count | fastest_share |
| --- | --- | --- | --- |
| dblp | RM | 4792 | 0.6224993504806443 |
| dblp | EXPLORE | 2611 | 0.33917900753442454 |
| dblp | KSS | 244 | 0.0316965445570278 |
| dblp | LFTJ | 51 | 0.006625097427903352 |
| eu2005 | RM | 2012 | 0.6971586971586972 |
| eu2005 | LFTJ | 748 | 0.2591822591822592 |
| eu2005 | KSS | 100 | 0.03465003465003465 |
| eu2005 | EXPLORE | 26 | 0.009009009009009009 |
| hprd | KSS | 19518 | 0.3156668984813443 |
| hprd | GQL | 19037 | 0.3078876291827724 |
| hprd | RM | 13229 | 0.21395416538629491 |
| hprd | EXPLORE | 5060 | 0.08183597224693115 |
| hprd | LFTJ | 3766 | 0.06090795879089777 |
| hprd | QSI | 1221 | 0.019747375911759475 |
| human | RM | 1971 | 0.520877378435518 |
| human | EXPLORE | 689 | 0.18208245243128965 |
| human | KSS | 650 | 0.17177589852008457 |
| human | GQL | 287 | 0.07584566596194503 |
| human | LFTJ | 139 | 0.036733615221987315 |
| human | QSI | 48 | 0.012684989429175475 |
| patents | EXPLORE | 4140 | 0.42318307267709293 |
| patents | RM | 3012 | 0.30788101809260965 |
| patents | KSS | 1586 | 0.1621179597260554 |
| patents | LFTJ | 1023 | 0.10456915056731064 |

### Sequence Effect vs Engine Effect

| dataset | sequence_variance_mean | engine_variance_mean | variance_ratio |
| --- | --- | --- | --- |
| dblp | 12.359800815582275 | 12.546574592590332 | 0.9684410027702897 |
| eu2005 | 59.57240867614746 | 121.2487907409668 | 0.5058175353143325 |
| hprd | 2.2251622766589207e-08 | 1.9400925310719686e-08 | 1.242124886261142 |
| human | 0.0004925418470520526 | 0.002588016097433865 | 0.5335016029460364 |
| patents | 14.062782287597656 | 88.92130279541016 | 0.332136979102966 |
| wordnet | 98.39132690429688 | 329.3741149902344 | 0.2998461371537261 |
| yeast | 0.00017354591545881703 | 0.00017696213035378605 | 0.9927430634055805 |
| youtube | 4.364936113357544 | 19.623687744140625 | 0.36036857784553805 |

Median variance ratio across all queries: `0.98`.

Interpretation: values above `1.0` mean sequence choice matters more than engine choice for a fixed query graph.

### Cross-Engine Ranking Consistency

Median Kendall's tau across all query-level engine pairs: `0.486`.

Universal-best-sequence rate: `9.3%`.

| engine_a | engine_b | kendall_tau |
| --- | --- | --- |
| EXPLORE | QSI | 0.6669424177216946 |
| EXPLORE | LFTJ | 0.6363636363636364 |
| LFTJ | QSI | 0.6 |
| EXPLORE | RM | 0.5978856345160221 |
| LFTJ | RM | 0.5507755005609098 |
| KSS | RM | 0.5144957554275265 |
| GQL | KSS | 0.5 |
| QSI | RM | 0.4666666666666666 |
| GQL | LFTJ | 0.4516881268917855 |
| EXPLORE | GQL | 0.4370036867375631 |
| GQL | RM | 0.4285714285714286 |
| EXPLORE | KSS | 0.35355339059327373 |

Conclusion: the optimal sequence is meaningfully engine-dependent.

## Part 4: Sequence Quality and Selection Difficulty

### Best/Worst Speedup and Random-Pick Penalty

| dataset | median_to_best_ratio | worst_to_best_ratio | sequence_count |
| --- | --- | --- | --- |
| dblp | 1.157360315322876 | 2.3166301250457764 | 12.0 |
| eu2005 | 1.114104986190796 | 2.4281373023986816 | 8.0 |
| hprd | 1.0 | 2.0 | 9.0 |
| human | 1.0493096113204956 | 1.5980210304260254 | 4.0 |
| patents | 1.1555882692337036 | 2.2658228874206543 | 10.0 |
| wordnet | 1.024176836013794 | 1.1492688655853271 | 4.0 |
| yeast | 1.1111111640930176 | 5.000000476837158 | 14.0 |
| youtube | 1.0483136177062988 | 1.3396227359771729 | 6.0 |

Median best-vs-median penalty: `1.03x`.

Median best-vs-worst speedup ceiling: `2.00x`.

### Difficulty by Query Size

| query_vertices | worst_to_best_ratio | median_to_best_ratio |
| --- | --- | --- |
| 4 | 1.4285715818405151 | 1.0439560413360596 |
| 5 | 1.7859389781951904 | 1.0996859073638916 |
| 6 | 2.367587089538574 | 1.1084864139556885 |
| 7 | 2.0606062412261963 | 1.119156837463379 |
| 8 | 2.85918927192688 | 1.1972180604934692 |
| 9 | 2.7647058963775635 | 1.1230074167251587 |
| 10 | 2.021524429321289 | 1.117261528968811 |
| 11 | 2.6774227619171143 | 1.0593324899673462 |
| 12 | 3.8983659744262695 | 1.1687605381011963 |
| 13 | 3.246739149093628 | 1.1596205234527588 |
| 14 | 3.0448317527770996 | 1.1785166263580322 |
| 16 | 3.000000238418579 | 1.0619792938232422 |
| 20 | 12.601221084594727 | 1.5329114198684692 |
| 24 | 113.05952453613281 | 1.7500001192092896 |
| 28 | 18.62152862548828 | 2.1665968894958496 |
| 32 | 860.2314453125 | 3.002671003341675 |

### Position Analysis

Best/worst sequence agreement by position:

| position | same_vertex |
| --- | --- |
| 1 | 0.6071856287425149 |
| 2 | 0.3317995587771825 |
| 3 | 0.289536716041601 |
| 4 | 0.3013236684525685 |
| 5 | 0.3043948823006455 |
| 6 | 0.3226276764142298 |
| 7 | 0.30544516129032256 |
| 8 | 0.301582579723941 |
| 9 | 0.2962445065920895 |
| 10 | 0.2937021339876571 |
| 11 | 0.2965612341635784 |
| 12 | 0.3003757380568975 |
| 13 | 0.2986102091180673 |
| 14 | 0.2912878161679616 |
| 15 | 0.2607003891050584 |
| 16 | 0.2865644312199588 |
| 17 | 0.23609534619750283 |
| 18 | 0.24290578887627695 |
| 19 | 0.2674990541051835 |
| 20 | 0.29701097237987134 |
| 21 | 0.26163182737693863 |
| 22 | 0.25151719487525287 |
| 23 | 0.2805124747134187 |
| 24 | 0.3054619015509103 |
| 25 | 0.2817796610169492 |
| 26 | 0.3008474576271186 |
| 27 | 0.3082627118644068 |
| 28 | 0.3580508474576271 |
| 29 | 0.18055555555555555 |
| 30 | 0.19444444444444445 |
| 31 | 0.19444444444444445 |
| 32 | 0.3611111111111111 |

Vertex-choice correlation strength by position:

| position | median_eta_squared |
| --- | --- |
| 21 | 0.6500317256446355 |
| 22 | 0.644253472229317 |
| 23 | 0.6287325353683875 |
| 18 | 0.617900440625365 |
| 17 | 0.6175860897795249 |

Interpretation: smaller agreement and larger eta-squared indicate that the position strongly differentiates runtime.

## Part 5: Implications for M2

| question | recommendation |
| --- | --- |
| Engine recommendation | Focus on EXPLORE, LFTJ, QSI because they combine the highest OK-rates with competitive speed. |
| Sequence ranking stability | Engine-dependent enough to keep a multi-engine check: only 9.3% of queries have a universal best sequence and the median variance ratio is 0.98. |
| Candidate reduction | Typical queries expose about 15 unique sequences (75th percentile 27). An HPC batch can cap evaluation at top-27 unique sequences per query without discarding the typical search space. |
| Critical positions | The most informative positions are 21, 22, 23; estimate every prefix for small queries, but for larger queries prioritize early layers and the first cyclic prefix. |
| Performance ceiling | Median best-vs-median penalty is 1.03x and median best-vs-worst speedup is 2.00x. |
| M2 batch experiment | Recommended engine set: EXPLORE, LFTJ, QSI. Include all 8 datasets, both dense and sparse patterns, and emphasize sizes 8, 12, 16, 24, and 32. Per query, evaluate up to 32 unique sequences when available, or all unique sequences if fewer. |

### Recommended M2 Batch Experiment

1. Datasets: keep all 8 datasets to preserve cross-domain generalization.
2. Pattern coverage: include both `dense` and `sparse` queries for every dataset.
3. Query sizes: prioritize sizes `8, 12, 16, 24, 32`, while still retaining smaller sizes as sanity checks.
4. Engines: focus on `EXPLORE, LFTJ, QSI` for the main experiment; retain one lower-reliability engine only if you want a stress-test split.
5. Sequence budget: evaluate up to `32` unique sequences per query by default; for queries with fewer than 32 unique sequences, keep all of them.
6. Prefix budget: compute all prefixes for small queries; for larger queries, ensure early prefixes and the first cyclic prefix are always included, because position effects concentrate near the front of the sequence.

## Artifact Locations

- Notebook: `analysis/m1_m3_analysis.ipynb`
- Processed tables: `analysis/processed/*.parquet`
- Figures: `analysis/figures/part*.png`
