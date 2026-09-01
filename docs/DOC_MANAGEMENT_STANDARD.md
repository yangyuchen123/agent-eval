# AgentEval 文档与研究产物管理标准

版本：`docs-standard-v1`  
生效日期：2026-08-31  
适用范围：`/home/yang/agent-eval/docs`、`run/` 下实验产物、根目录研究脚本、`archive/`。

## 1. 目标

文档、实验协议、脚本和结果必须能够回答：

```text
它是什么？
当前是否有效？
依赖哪些输入？
谁可以消费？
是否可以复现？
什么时候可以归档？
```

禁止把设计、运行结果、脚本、Gold、原始数据和临时调试输出混在一个目录中。

## 2. 顶层目录职责

```text
agent-eval/
├── docs/              当前有效的规范、架构、接口和研究入口
├── src/               AgentEval 生产代码
├── judge/             Judge 生产代码
├── rubrics/           当前 rubric/schema
├── tools/             当前仍维护的通用工具（如建立）
├── run/               当前实验运行入口或兼容指针
├── meta_eval/         当前维护的 Gold/fixture 定义（如建立）
└── archive/YYYY-MM-DD/历史冻结材料
```

归档内部按研究线继续分层：

```text
archive/YYYY-MM-DD/<topic>/
├── docs/
├── scripts/
├── run/
├── fixtures/
├── reports/
└── ARCHIVE_INDEX.md
```

## 3. 文档状态

每份当前文档必须在标题后声明：

```text
状态：current | draft | experimental | deprecated | archived
```

状态含义：

- `current`：当前实现或决策依据；
- `draft`：尚未批准，只能作为提案；
- `experimental`：只适用于某个实验，不作为生产契约；
- `deprecated`：仍保留，但已有替代文件；
- `archived`：不可作为当前实现依据，只用于历史追溯。

## 4. 命名规则

### 当前规范

使用稳定名称：

```text
ARCHITECTURE.md
INTERFACES.md
SYSTEM_BOUNDARIES.md
DOC_INDEX.md
```

### 实验文档

必须包含日期和实验 ID：

```text
<MODULE>_<EXPERIMENT>_YYYY-MM-DD.md
```

例如：

```text
META_EVAL_ANCHOR_WORDING_2X2_ABLATION_2026-08-27.md
```

### 归档目录

目录名使用：

```text
archive/YYYY-MM-DD/<topic>/
```

不得使用 `latest`、`new`、`final2`、`tmp` 作为唯一定位依据。

## 5. 实验文档必须包含的字段

每次实验至少记录：

```yaml
experiment_id:
date:
status:
hypothesis:
changed_component:
changed_variable:
frozen_components:
fixture_set:
input_refs:
input_digests:
output_refs:
metrics:
known_limitations:
promotion_status:
```

实验结果必须与实验协议、脚本、输入 digest 和输出 digest 分开保存，但通过 manifest 关联。

## 6. 脚本管理

- 生产入口放在 `src/`、`judge/` 或明确的 CLI 包内；
- 一次性研究脚本不得继续散落在仓库根目录；
- 研究脚本应放在 `tools/<topic>/` 或归档 `archive/.../scripts/`；
- 根目录旧脚本如果必须兼容，根目录只能保留薄 wrapper；
- wrapper 必须指向唯一 canonical script，不得复制业务逻辑；
- 脚本必须记录输入根目录，优先使用 `AGENT_EVAL_ROOT`，不得依赖脚本所在路径推断业务数据；
- 真实运行脚本必须显式说明是否允许 Harbor/Pi、是否调用 LLM、输出目录和 cache 行为。

## 7. 实验产物管理

```text
run/<experiment-id>/
├── manifest.json
├── inputs/       可选，只保存小型索引，不复制大型历史数据
├── results/
├── reports/
└── logs/
```

大型 trace、artifact 和原始数据只保存引用和 digest，不复制进报告目录。

## 8. Gold、fixture 与结果的边界

- Gold 是评价参照，不得由 Judge 运行结果覆盖；
- fixture 是冻结引用清单，不是新的 trace/artifact schema；
- historical result 不得自动变成 current benchmark knowledge；
- smoke/debug fixture 默认不能成为 difficulty 或 benchmark-design learning signal；
- component-level 结论必须有 component-level Gold，否则只能标为 diagnostic-only。

## 9. 归档规则

满足以下任一条件的材料进入 archive：

- 实验已完成且不再作为当前默认路径；
- 被新实验或新协议替代；
- 只用于历史复盘或 badcase 分析；
- 结果已冻结但数据集设计不足；
- 脚本只服务于一次性实验。

归档必须同时生成：

```text
ARCHIVE_INDEX.md
ARCHIVE_MANIFEST.json
path mapping / compatibility pointer
```

归档后不得静默修改；若需修正，建立新的归档版本。

## 10. 索引和评审规则

`docs/DOC_INDEX.md` 是当前入口。每个 current 文档必须在索引中出现；每个 archived topic 必须在 archive index 中出现。

研究结论必须区分：

```text
engineering fact
observed result
causal claim
generalization claim
```

小样本、单 case、无独立 Gold 的结果默认只能写为 `observed result` 或 `diagnostic-only`。

## 11. 当前执行约束

本标准不要求立即重构生产代码。首先执行：

1. 新文档进入 `docs/` 并更新 `DOC_INDEX.md`；
2. 实验进入独立 `run/<experiment-id>/`；
3. 完成后移入 `archive/YYYY-MM-DD/<topic>/`；
4. 根目录脚本只保留兼容 wrapper；
5. 所有实验通过 manifest 关联输入、输出和 digest。
