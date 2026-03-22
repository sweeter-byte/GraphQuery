# Verified Notes on the Experimental Design of "A Comprehensive Survey and Experimental Study of Subgraph Matching"

## Scope

This note verifies my previous summary against the local PDF:

- [3639315.pdf](/home/ranmaoyin/graph_query/Fastest-par/3639315.pdf)

It also cross-checks the paper with the bundled artifact/code:

- [README.md](/home/ranmaoyin/graph_query/Fastest-par/core/engines/SubgraphMatchingSurvey/README.md)
- [matchingcommand.h](/home/ranmaoyin/graph_query/Fastest-par/core/engines/SubgraphMatchingSurvey/vlabel/matching/matchingcommand.h)
- [StudyPerformance.cpp](/home/ranmaoyin/graph_query/Fastest-par/core/engines/SubgraphMatchingSurvey/vlabel/matching/StudyPerformance.cpp)
- [config.h](/home/ranmaoyin/graph_query/Fastest-par/core/engines/SubgraphMatchingSurvey/vlabel/configuration/config.h)

## Verification Result

The previous summary was correct in substance.

The following claims are directly confirmed by the PDF:

- The paper is organized around three research questions: trend, unbiased evaluation, and interaction.
- The paper argues that fixed output limits can bias rankings.
- The paper proposes EPS, embeddings per second, as the main efficiency metric.
- The paper selects 10 representative techniques for each of the three stages and evaluates all feasible combinations.
- The total number of feasible combinations is 534.
- The experiments cover both real-world datasets and synthetic datasets.
- The paper evaluates output-limit sensitivity, time-limit sensitivity, edge labels, real queries, automorphism handling, graph meta-features such as treewidth, and scalability.
- The paper uses statistical significance testing, including Friedman and Nemenyi tests.

No major correction is needed, but several points can now be stated more precisely from the PDF instead of from README-level evidence.

## Small Clarifications Over the Previous Summary

- My previous answer listed several real-world datasets as examples. The PDF gives the complete vertex-labeled real-world set used in Table 3: Figeys, YeastS, Human, HPRD, citeseer, WordNet, Standford, DBLP, Twitch, and Youtube.
- The PDF is more precise about workload generation than my earlier answer: query sizes are 10, 20, 30, 40, and 50; each query set contains 1000 queries; edge-labeled query sets contain 100 queries; real queries on DBpedia come from LC-QuAD.
- The PDF is explicit that the main EPS-based evaluation imposes no maximum embedding limit, but does use a 1-second timeout due to the large number of queries.
- The "conventional setting" criticized by the paper is explicitly: stop after `10^5` matchings or after 300 seconds.
- The output-limit sensitivity experiment is explicitly run from `10^5` to `10^9`.
- The EPS stability experiment is explicitly run with time limits 1s, 5s, 10s, 30s, and 60s on the top 50 algorithms with the largest variance in the output-limit experiment.

## What the Paper's Experimental Design Actually Is

## 1. The experiments are driven by three explicit research questions

Section 1 frames the experimental study around:

1. What are the prevailing trends in algorithm development?
2. How to rigorously assess performance without bias?
3. How do interactions between techniques affect evaluation?

This matters because the experiment design is not a generic benchmark suite. It is a problem-driven design where each major experiment answers one of these three questions.

## 2. The core design is stage-wise decomposition plus feasible-combination evaluation

The paper does not treat each subgraph matching system as an indivisible black box.
Instead, it decomposes the framework into:

- filtering
- ordering
- enumeration

In Section 4.1 and Table 2, the paper states that it selects 10 representative techniques for each stage.
The PDF explicitly states that the total number of feasible combinations is 534.

This is the central experimental choice of the paper.
It allows the authors to answer questions like:

- whether a technique is strong in itself
- whether it only works well with specific complementary techniques
- whether the "default combination" used in an original paper hides stronger or weaker pairings

This is much stronger than the usual survey pattern of evaluating only original named algorithms.

## 3. The paper treats evaluation bias from stopping rules as a first-class issue

Section 1.2 and Section 4.5 explicitly attack the conventional evaluation setting used in prior work:

- stop after `10^5` embeddings
- or after 300 seconds

The paper shows that changing the output limit alone can dramatically change method rankings.
This is not a side observation; it is one of the paper's core contributions.

The experimental response is:

- introduce EPS as the main efficiency metric
- remove the maximum embedding cap in the main evaluation
- keep a 1-second timeout to make the large experiment suite tractable
- separately run an output-limit sensitivity experiment from `10^5` to `10^9`
- separately run a time-limit stability experiment at 1s, 5s, 10s, 30s, 60s

This directly supports the interpretation I gave earlier: the stopping rule is itself an experimental factor, not just an implementation detail.

## 4. EPS is the paper's main efficiency metric

Section 4.1 defines two evaluation metrics:

- average candidate size, as a measure of filtering effectiveness
- EPS, embeddings per second, as a measure of efficiency

The paper explicitly says EPS is intended to remain relatively consistent across time and output-size limitations.
It also explicitly notes that a larger EPS does not necessarily imply a larger number of results.

That is an important methodological point: the paper is evaluating algorithmic efficiency, not result volume.

## 5. The workload design is broad, not single-benchmark

The PDF gives a fairly rich workload design.

### Real-world vertex-labeled graphs

Table 3 lists:

- Figeys
- YeastS
- Human
- HPRD
- citeseer
- WordNet
- Standford
- DBLP
- Twitch
- Youtube

The paper also states that experiments were conducted on these 10 datasets with random vertex label sizes:

- 15
- 30
- 45
- 60

### Real-world graphs with real vertex and edge labels

Table 4 lists:

- Wordnet18
- FreeBase15k
- Telecom
- DBpedia

### Synthetic graphs

Section 4.1 states:

- ER is used for random graphs
- RMAT is used for power-law graphs

Default synthetic settings are:

- `|V| = 1M`
- `|E| = 5M`
- `|Sigma| = 30`

Scalability experiments vary:

- `|V|` in `0.05M, 0.1M, 0.5M, 1M`
- `|E|` in `5M, 10M, 15M, 20M`
- `|Sigma|` in `15, 30, 45, 60`

## 6. Query workload generation is also explicitly controlled

Section 4.1 states that query graphs are generated using the same approach as previous studies:

- a Metropolis-Hastings random walk on data graphs
- induced subgraphs extracted as queries

The paper specifies:

- query sizes: 10, 20, 30, 40, 50
- each query set contains 1000 queries
- for real edge-labeled graphs, each query set contains 100 queries
- for DBpedia real queries, LC-QuAD is used

Section 4.3 further clarifies that LC-QuAD queries are usually small, around 3 to 5 vertices, and often have relatively few embeddings.

## 7. The interaction experiments are not rhetorical; they are operationalized carefully

My previous answer said the paper treats interaction as a primary experimental object. The PDF confirms this strongly.

Section 4.6 gives a concrete interaction design:

- fix the ordering method as RI
- exhaustively combine `fLDF` and `fVEQ`
- with `eLFTJ` and `eVEQ`

The paper then shows:

- replacing the filter barely matters for `eLFTJ`
- replacing the filter matters substantially for `eVEQ`
- `eVEQ + fLDF` can even perform worse than `fLDF + eLFTJ` on some datasets

This is exactly the kind of evidence needed to argue that single-technique evaluation can be misleading.

Sections 4.7, 4.8, and 4.9 then apply a second interaction-aware design:

- evaluate each filter under its best complementary order and enumeration choices
- evaluate each ordering technique under its best complementary filter and enumeration choices
- evaluate each enumeration technique under its best complementary filter and ordering choices

This is a critical methodological move.
It means the paper is not only comparing raw techniques, but also comparing them under near-favorable complementary settings.

## 8. The paper evaluates more than one notion of difficulty

The experiments are not limited to "dataset A vs dataset B."
They explicitly vary multiple difficulty-related factors:

- output size
- query size
- treewidth
- edge label size
- automorphism presence
- graph size and density
- label cardinality

Examples:

- Section 4.4 studies automorphism-aware single-solution handling.
- Section 4.5 studies output-limit effects and EPS stability.
- Section 4.10 studies output size and query size jointly.
- Section 4.11 studies treewidth.
- Section 4.12 studies scalability on synthetic graphs.

This confirms the earlier claim that the paper treats workload structure as an important part of evaluation design.

## 9. Statistical testing is part of the experiment design

Section 4.2 explicitly reports:

- Friedman test with `p = 6.21 x 10^-9`
- Nemenyi post-hoc test for paired comparison

The PDF also states that per-method effectiveness differences across datasets are very significant with `p < 10^-9`.

This confirms that the paper is not relying purely on visual ranking plots; it also attempts to support conclusions statistically.

## 10. The artifact code matches the paper's evaluation logic

The bundled artifact supports the experimental structure described in the paper:

- [matchingcommand.h](/home/ranmaoyin/graph_query/Fastest-par/core/engines/SubgraphMatchingSurvey/vlabel/matching/matchingcommand.h) exposes independent controls for filter, order, engine, output cap, time limit, and spectrum/order-count parameters.
- [StudyPerformance.cpp](/home/ranmaoyin/graph_query/Fastest-par/core/engines/SubgraphMatchingSurvey/vlabel/matching/StudyPerformance.cpp) records:
  - load time
  - filter time
  - build-table time
  - query-plan generation time
  - enumeration time
  - preprocessing time
  - total time
  - memory cost
  - number of embeddings
  - call count
- The same file also contains support for "Spectrum" mode, which is consistent with exploring multiple matching orders rather than only a single fixed order.

So the code artifact is aligned with the paper's experimental claims rather than being only a simplified demo implementation.

## Final Judgment on the Previous Summary

The previous summary was correct.

More specifically:

- The factual claims about the paper's goals, EPS, output-limit bias, 534 feasible combinations, real-world plus synthetic evaluation, significance tests, edge-label evaluation, automorphism evaluation, and treewidth/scalability evaluation are all confirmed by the PDF.
- The earlier framing that the paper is really about stage-wise system evaluation rather than only named-algorithm benchmarking is also supported by the PDF.
- The earlier statement that the paper treats output-limit choice as an important source of bias is not merely an interpretation; it is one of the paper's explicit claims.

The only thing missing from the earlier answer was precision, not correctness.
Now that the PDF is available locally, the details above should be treated as the verified version.

## Practical Takeaway for Fastest-par

If the goal is to build paper-grade experiments on top of `Fastest-par + SubgraphMatchingSurvey`, the paper suggests the following experimental principles:

- Treat `filter`, `order`, and `engine` as separate experimental factors.
- Do not rely only on fixed-output-limit total runtime.
- Report EPS when the downstream task is enumeration-heavy.
- Include sensitivity analysis for output limits or time limits if ranking stability matters.
- Evaluate plans under multiple downstream engines, because the paper shows strong interaction across stages.
- When comparing one technique, compare it both:
  - in its original/default combination
  - under its best complementary combination

These recommendations are not external advice; they follow directly from the paper's own experimental design.

