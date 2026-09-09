# Failure-handling anchor-aware Gold adjudication v2

该目录不会静默覆盖原始人工 Gold：

```text
run/meta_eval/failure-handling-blind-v1/gold/
```

这里记录了一个已发现的测量有效性问题：当实验修改声明的 score anchors 时，单个旧版
numeric expected score 可能与新的 anchor 语义冲突。稳定的人工对象应当是事实状态和
受 rubric 约束的解释；每条评分梯度都需要明确的 expected anchor。

这个五案例文件是在 retrieval-only 实验暴露冲突后创建的 adjudication candidate。报告
必须同时展示 original-Gold 结果和 anchor-aware 结果，并且不得假装这次事后 adjudication
是在早期实验之前就已经冻结的。
