# Claude Code — Strict Stage A Implementation Directive

You are implementing Stage A (MVP) only.

Before writing any code:

1. Re-read:
   - docs/stage_a_mvp_tasks.md
   - docs/index_artifact_spec.md

2. Confirm the following constraints explicitly in your response:

---

## Stage A Hard Constraints (Non-Negotiable)

- Only ONE connected expansion order per session.
- Do NOT enumerate multiple orders.
- Do NOT implement Top-K ranking.
- Do NOT implement pruning.
- Do NOT implement memoization.
- Do NOT refactor estimator into a library.
- Do NOT modify C++ kernel.
- Use CLI invocation exactly as documented.
- Max running sessions = 1.
- No session queue.
- No multi-process pool.
- No background indexing.
- No online index build.
- No advanced frontend framework required.
- JSON editor + SSE progress is sufficient.

If you attempt to expand beyond these boundaries,
stop and explain why.

---

## Implementation Order (Strict)

Follow this order:

1. Backend skeleton
2. Dataset registry
3. Session manager (state machine)
4. Query validation + ID normalization
5. Connected expansion order (single deterministic)
6. Prefix builder
7. CLI adapter (spawn + parse)
8. SSE streaming
9. Mock execute endpoint
10. Minimal frontend

Do NOT reorder this plan.

---

## Deliverables per Step

After each step:
- Show directory tree.
- Show files created.
- Explain design decisions briefly.
- Show how it aligns with spec.

Do NOT implement all at once.

Proceed step by step.

---

## Goal

Achieve a working Stage A MVP
with a single connected expansion order
and prefix cardinality accumulation.

Stop once Stage A is complete.

No Stage B features allowed.

