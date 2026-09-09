# RubricRefiner / AtomicityValidator 实施说明

日期：2026-09-03

## 范围

当前只处理 BugFind 指定的 compound candidate：

```text
BugFind → RubricRefiner → AtomicityValidator → keep original or accept split
```

只允许 `KEEP` 与 `SPLIT`。不处理 DROP、REWRITE、coverage、overreach、boundary 或其它 defect。

## 输入隔离

Refiner 输入为 task context、原 criterion metadata、BugFind 的 compound reason/evidence。实现不读取 Gold label、Judge score/prediction、flip result 或 A/C/D condition。

## metadata 规则

Refiner 输出仅包含 replacement `criterion_id` 与 `text`。通过 `inherit_metadata` 复制原 criterion 的既有 grounding、scope、evidence_source、hardness、judgment_type、capability 等 metadata，并把 atomicity 标为 `atomic`。Refiner 不做 capability remapping；如模型返回 `capability_reclassification_needed`，交给后续 CapabilityAlignmentAnalyst。

## Validator

`validate_atomicity` 是与 Refiner 分离的确定性第一道检查；`atomicity_validator_prompt` 可用于独立 validator 模型。检查 coverage、atomicity、semantic expansion、over-split 和 redundancy 五个结果。Validator 失败时 runner 保留原 criterion，且不循环修订。

## 共享入口

```bash
python3 tools/run_rubric_refinement.py \
  --candidates candidates.jsonl \
  --out refinement.jsonl \
  --base-url ... \
  --model ...
```

一个 batch 使用一次 Refiner 模型调用；无需每条 criterion 单独调用模型。`--dry-run` 用于链路测试。正式运行由输入 JSONL 冻结候选集和 manifest 记录模型配置、prompt/schema 版本及输入 digest。

## 当前未做

- 未修改 Generator、Gold、B Judge、taxonomy 或 A/C/D protocol；
- 未自动运行 GDPval/RuVer 全量 refinement；
- 未把 Judge stability 当作 Refiner 输入；
- 未实现 Judge regression；需在首轮人工 atomicity reference 确认后进行。
