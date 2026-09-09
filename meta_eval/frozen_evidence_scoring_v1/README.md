# Frozen evidence scoring bundles v1

这五个经过人工审核的 bundle 用于对 `observed_failure_handling` 进行仅评分阶段的
anchor 表示消融实验。

设计规则：

- bundle 包含有证据支持的 runtime facts、固定的 factual claim set、缺失事实和矛盾信息；
- bundle 有意排除 Gold 分数、预期状态，以及 `partial`、`substantial`、`appropriate` 等定性评分词；
- scorer 不接收 Evidence Tools，也不得新增、删除、质疑或重新分类事实；
- Gold 标签保存在 `run/meta_eval/failure-handling-blind-v1/gold/`，只由离线分析器进行关联；
- `att_9c539666b31d` 保留为与表示方式无关的负控制候选案例。
