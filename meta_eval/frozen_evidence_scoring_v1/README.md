# Frozen evidence scoring bundles v1

These five manually reviewed bundles support the scoring-only anchor representation ablation for `observed_failure_handling`.

Design rules:

- Bundles contain evidence-backed runtime facts, a fixed factual claim set, missing facts, and contradictions.
- They intentionally exclude Gold scores, expected statuses, and qualitative scoring words such as `partial`, `substantial`, or `appropriate`.
- The scorer receives no Evidence Tools and may not add, delete, dispute, or reclassify facts.
- Gold labels remain under `run/meta_eval/failure-handling-blind-v1/gold/` and are joined only by the offline analyzer.
- `att_9c539666b31d` is retained as the representation-insensitive negative-control candidate.
