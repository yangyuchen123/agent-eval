# AgentEval 实验管理标准

版本：v1（2026-09-01）

## 1. 实验不是一次性脚本

实验是可追溯的数据生产过程。实验差异必须通过配置和 manifest 表达，而不是复制一份 Python runner 再修改。

禁止形成：

```text
run_joint.py
run_joint_v2.py
run_two_stage.py
run_ablation.py
run_ablation_fixed.py
run_coding19.py
```

同一类实验只能有一个共享执行入口。

## 2. 目录标准

推荐结构：

```text
experiments/
  runner.py                 # 唯一共享入口
  configs/                  # 声明 treatment/frozen variables
  manifests/                # immutable input/protocol manifests
  results/                  # versioned outputs
```

当前项目已有历史实验目录不重写、不覆盖。后续新实验逐步迁移到该结构。

2026-09-09 状态：`experiments/runner.py`、`configs/`、`manifests/` 尚未落地。
在共享 runner 建立前，禁止再新增根目录 `tools_run_*.py` 或 condition-specific runner。
现有 `tools/` 与根目录 `tools_*.py` 视为过渡兼容入口，不作为新实验模板。

## 3. Manifest 必填字段

每个正式实验 manifest 必须包含：

```yaml
experiment_id:
hypothesis:
dataset:
case_ids:
treatment_variables:
frozen_variables:
judge:
  model:
  provider:
  temperature:
  seed:
protocol_version:
prompt_version:
schema_version:
code_commit:
input_digests:
expected_call_topology:
output_dir:
promotion_status:
```

`treatment_variables` 必须明确本次实验允许改变什么；`frozen_variables` 必须明确什么不得改变。

## 4. 共享 runner 规则

共享 runner 必须：

1. 从 manifest 加载 task/case，而不是读取 mutable `latest`；
2. 验证输入文件 digest；
3. 验证 prompt/schema/code digest；
4. 验证条件间只有声明的 treatment 不同；
5. 记录每次调用的 condition、输入 digest、输出 digest、模型配置和状态；
6. 失败时停止或明确标记 incomplete，不得静默混合旧结果；
7. 输出到新版本目录，不覆盖历史产物。

## 5. A/B/C/D 特例

A/B/C/D 不是四份脚本，而是同一个 runner 的四份 config/condition：

```text
A = original per-rubric QuestionJudge + full trajectory
B = joint multi-rubric Judge + full trajectory
C = shared evidence once + joint score + evidence only
D = shared evidence once + per-rubric score + same evidence packet
```

正式统计分母、task IDs、Gold、trajectory 必须完全一致。

## 6. 结果命名

结果名称必须包含：

```text
experiment_id
protocol_version
condition
input snapshot
```

`A`、`baseline`、`final` 等词不能仅凭文件名使用，必须由 manifest 定义。

如果实现不同，必须使用不同 condition ID，例如：

```text
A_formal_original_question_judge
A2_independent_two_stage_rubric
legacy_M1_multi_question
```

## 7. 小样本 sanity gate

在 19-task 或大规模运行前，必须使用固定 5-task 子集检查：

- task IDs 是否一致；
- criterion 数量是否一致；
- prompt/schema 是否一致；
- model/config 是否一致；
- call topology 是否一致；
- 旧 baseline 是否能复现。

无法复现时，不得直接解释为 dataset composition effect。

## 8. 代码审查要求

新增 `run_*.py` 默认视为实验管理违规。除非明确批准，否则应：

- 扩展共享 runner；
- 新增 config；
- 新增 manifest；
- 不复制业务逻辑。

CI 后续可以增加检查：新 PR 新增 `run_*.py` 时失败，除非有显式 allowlist/批准记录。

## 9. 当前迁移状态

`whole-task-multirubric-coding19-20260901/run_frozen_abcd.py` 是在本标准建立前创建的过渡 runner。它已用于冻结 A/B/C/D 定义和 digest 校验，但不应继续复制出新的 condition-specific runner。

下一步应将其业务逻辑迁移为共享 runner，并把 A/B/C/D 差异放入配置文件。
