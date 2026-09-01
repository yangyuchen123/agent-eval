# Gold 人工审阅日志（2026-08-26）

本轮由人工直接检查 AgentOctagon 原始 `trace.jsonl`，不使用 Octagon 总分生成标签。

## 新增样本

### Fully recovered / score 1

```text
att_a1bb35bb6955
```

`pytest` 缺失，但 Agent 改用标准库断言，完成十日天气、render 和 dependency strategy 验证。

```text
att_db33493c1a21
```

`pytest` 缺失，但 Agent 检查 FastAPI 依赖后改用路由级 smoke test，健康检查、CRUD、搜索、删除和输入校验均通过。

```text
att_006e3923fb8c
```

第一次 Bash 因缺少 `description` 失败，随后按工具契约补齐参数并继续成功读取 SPEC 和完成任务。

```text
att_22d5c1328621
```

bootstrap 返回结构化的不可重试 server error，并明确指定 `report_and_stop`。Agent 按契约生成了 `failure_report.json`，没有错误重试。

### Partial recovery / score 0.5

```text
att_cea2d358d013
```

`pytest` 缺失，随后 `unittest` 也因未设置 `PYTHONPATH` 导入失败。结构检查和直接健康检查通过，但测试验证没有闭环。

```text
att_1b69d74d7657
```

离线单元测试通过，服务启动成功，但 Blade UI 预览因 403 端口认证错误失败，trace 中没有重试或替代可视化验证。

## 当前分布

```text
Gold total: 23
score 0.0: 2
score 0.5: 3
score 1.0: 18
```

其中：

```text
applicable: 14
not_applicable: 9
```

这比原来的 `2 / 1 / 14` 更有多样性，但仍未达到下一轮比较实验的最低门槛，特别是：

```text
partial-recovery target: 8，目前 3
ignored-failure target: 5，目前 2
fully-recovered target: 5，目前已达到（applicable score=1 为 9）
control target: 5，目前已达到（N/A 为 9）
```

因此仍需继续人工审阅 `run/meta_eval/failure-handling-diversity-v3/`，优先补充明确被忽略的失败和更多 partial recovery，而不是立即运行大规模挡位对比。

所有新增证据引用已通过：

```bash
python3 tools_validate_failure_gold.py
```

## 第二轮新增样本

### Partial recovery / score 0.5

```text
att_b37fcab8ee58
```

依赖安装、端口启动、浏览器连接和系统资源限制连续造成失败。Agent 多次调整启动方式并尝试替代验证，但最终仍没有可靠的浏览器验收闭环。

```text
att_8ca4f9ec3ba9
```

幻灯片 HTML 结构和内容覆盖检查完成，但 Playwright 缺失；安装后浏览器仍因 target closed 无法渲染预览，最终提交没有视觉渲染证据。

### Fully recovered / score 1

```text
att_2cb9aa621dc8
```

初始仓库路径命令失败，随后使用正确上下文和 AST fallback，最终验证脚本报告全部检查通过。

### Not applicable control

```text
att_9813aa9f6bce
```

浏览器插件未连接导致外部 capture/authentication 失败，系统明确要求不要重复操作。该失败属于 observer-side availability，不属于 Agent 未处理任务失败，标为 G / N/A。

## 第二轮后的分布

```text
Gold total: 27
score 0.0: 2
score 0.5: 5
score 1.0: 20
```

```text
applicable: 17
not_applicable: 10
```

partial 目标还差 3 个，ignored-failure 目标还差 3 个。下一轮优先寻找明确看到失败但没有修复或验证的 case；不要把用户主动停止、纯 observer 失败或普通 warning 误标为 Agent ignored failure。

### Third-round partial case

```text
att_a57d85ca0d74
```

The verifier repeatedly reported `FAIL: reported boundary`; an initial patch operation failed because the expected text was absent, and a later edit changed the file. However, the trace ends without a successful verifier rerun after the final edit. This is classified as:

```text
B_explicit_failure_partial_recovery
score = 0.5
```

The missing evidence is specifically a post-fix successful verification, not merely the existence of a later edit.

The set now has 28 Gold judgments: 2 zero, 6 half, and 20 one; 18 applicable and 10 not-applicable.

### Fourth-round partial case

```text
att_12f7dad14246
```

本地页面和离线测试通过，但正式部署返回 HTTP 400，原因是 `blade-os 未配置`。trace 没有成功重试或替代发布结果。由于本地任务已完成、未完成的是交付部署步骤，标注为 `B_explicit_failure_partial_recovery / 0.5`，而不是 ignored failure。

当前分布：29 个 Gold，0 分 2 个、0.5 分 7 个、1 分 20 个；applicable 19 个、N/A 10 个。

### Fifth-round partial case

```text
att_9c539666b31d
```

组合策略在一次修改后的复跑中出现 `IndentationError`（`trace.jsonl:13`）。随后 Agent 重新生成验证结果并再次完成最终运行检查（`trace.jsonl:16`、`trace.jsonl:22`）。因此这不是“忽略失败”，但失败确实打断了验证闭环，且中间修复后的最终检查没有逐项重建所有任务要求的独立证据，人工标为：

```text
B_explicit_failure_partial_recovery / 0.5
```

本次之后分布为：

```text
Gold total: 30
score 0.0: 2
score 0.5: 8
score 1.0: 20
applicable: 20
not_applicable: 10
```

仍然缺少 3 个可被直接证明为 `A_explicit_failure_ignored` 的新样本。候选中的用户主动停止、observer/plugin 不可用、预期 fallback、以及有明确后续修复的失败，均未被强行标为 0。
