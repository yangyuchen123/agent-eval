# Failure-handling anchor-aware Gold adjudication v2

This directory does **not** silently overwrite the original human Gold under
`run/meta_eval/failure-handling-blind-v1/gold/`.

It records a discovered measurement-validity issue: when an experiment changes
the declared score anchors, a single legacy numeric expected score may conflict
with the new anchor semantics. The stable human object should be the factual
state and rubric-bound interpretation; each ladder then needs an explicit
expected anchor.

The five-case file is an adjudication candidate created after the retrieval-only
experiment exposed the conflict. Reports must show both original-Gold and
anchor-aware results and must not pretend this post-hoc adjudication was frozen
before earlier experiments.
