# AgentEval — 设计记忆(DESIGN MEMORY)

> 这份文档是**恢复上下文的单一入口**。项目跨了数月、多个阶段,所有
> 逻辑、设计意图、关键决策的"为什么"、踩过的坑,集中在这里。
> 读完它,你应该能回答:每个文件为什么存在、它怎么工作、当时为什么
> 这么设计。

---

## 0. 一分钟电梯演讲

**AgentEval 是一个"自我改进的评测基础设施"(self-improving evaluation
infrastructure),不是 agent 框架。它是 [HarnessEval-W](https://github.com/mirros-lab/HarnessEval-W)
(世界模型视频评测框架)的**二开**,实际开发约两天 —— 继承其
agentified evaluation 与 evidence-tree 思想,重构为通用框架,并新增
rubric 数据化 / 历史 / 诊断 / 迁移 / capability 等元评测层(见 1.5 节)。**

它回答的元问题是:**"如何定义、验证、改进'评价一个 agent 的标准'?"**
——评价标准(rubric)本身也要被评价、被诊断、被版本化、被迁移。

两个真实 benchmark 验证它:SWE-bench(patch + 容器测试打分)和
GDPVal(交付物 + 人类 rubric + LLM judge)。两种截然不同的评测范式,
共享同一套核心。

## 1. 三条设计边界(最重要,别忘)

| # | 边界 | 理由 |
| --- | --- | --- |
| 1 | **Agent 自迭代闭环不进核心** | "用评测改进 agent"是上层 consumer(另一个仓库)。混进来会把 benchmark/judge/db/agent-framework 四类关注点全拉进核心。核心只负责**评测**。 |
| 2 | **Rubric 自优化进核心** | "如何定义和改进评价标准"是 evaluation framework 的元问题,天然属于这里(Layer 1-4 演进)。 |
| 3 | **案例包解耦,不进框架** | 框架零领域知识。领域案例通过 `build_registry()` / `build_router()` 注入,数据在 JSON 文件。 |

命名纪律:**说 "rubric optimization / calibration",不说 "self-evolving"** ——不过度承诺。

## 1.5 继承关系(★ 最重要:这是 HarnessEval-W 的二开)

**agent-eval 不是从零写的。它是在 `github.com/mirros-lab/HarnessEval-W`
(世界模型视频评测框架)基础上二开的,实际开发时间只有两天。**
务必分清:哪些是原有的、哪些是重构的、哪些是全新开发的。

### HarnessEval-W 是什么(原有,未动)

原仓库是一个 **agentified evaluation** 框架:评测世界模型生成的视频
(6 类任务:physical_transition / offscreen_evolution / drift_resistance /
intentional_transition / exploratory_transition / return_revisit_consistency)。
核心思想:case → LLM planner 路由 skills → 每个 skill 把评测问题分解成
子问题 → 专用 sub-agent 打分 → 父 agent 验证证据并聚合 → **transparent
evidence tree**(完整推理链)。

原有组件(agent-eval 没有原样带进来,但思想继承):

| 原组件 | 作用 |
| --- | --- |
| `pipeline/planner.py` | **LLM planner**:根据 case 上下文路由 skills,记录 skip 理由 |
| `pipeline/runner.py` | SkillTask 执行(shard/phase/发布),digest 缓存 |
| `pipeline/inventory.py` | 视频清单、manifest 加载、rollout 检查 |
| `score.py` / `report.py` | 聚合打分、报告 |
| `skills/`(13 个) | 领域 skills:物理合理性/运动质量/渲染质量/视图轨迹/返回一致性/… |
| `skill_backend/` + `metric_backends/` | VLM 封装 + 度量后端(megasam/unidepth) |
| `benchmark/` + `runs/example` | **原有数据**:世界模型视频案例 + 示例结果 |

### 二开重构(改自原有,两天内完成)

| agent-eval 组件 | 从原有改了什么 |
| --- | --- |
| `protocols.py` | Case/SkillSpec/SkillResult/Plan/CaseEvidence — 把原 dict 型数据模型重构成 frozen dataclass |
| `skills/base.py` | Skill 基类 — 原项目 skill 是模块+契约(CacheContract),二开统一成 `RuleSkill`/`LLMSkill` 二分 + `role`(observation/core/diagnostic) |
| `planner.py` | RuleRouter — 把原 **LLM planner** 简化为确定性规则路由(可审计,零 LLM 成本) |
| `runner.py` | digest 缓存机制继承自原 runner/io,二开为 skill 级缓存 + 自动写 history |
| `io.py` | atomic_write_json / value_digest 思路继承,重构实现 |
| `backends.py` | LLMBackend 全新实现(OpenAI 兼容 + JSON mode + thinking disabled);原项目是 VLM/CLIP 构建,完全不同 |

### 全新开发(二开期间新增,不属于原有)

* **FineGrainedRubric + Rubric/RubricStore**(Layer 1)——把原项目 skill 内嵌的
  rubric 机制(analyze/verify 两阶段、离散阶梯、verbatim 证据)**提炼成
  数据驱动的可复用基类**:新领域只需声明 questions(JSON 数据)。
  这是二开最大的增值:从"每个 skill 手写管道"到"声明即评测"。
* **History + 诊断 + 迁移**(Layer 2-3.3)——原项目没有:history.jsonl、
  question_metrics、cohen_kappa、migration_report 全部新增。
* **Capability / Manifest**(Layer 3.4-3.5)——新增。
* **CLI**(eval/analyze/migrate/verify)——新增(原项目是 python 函数式调用)。
* **两个 benchmark 案例包**(SWE-bench 容器打分 + GDPVal)——全新领域,
  原项目是视频评测,没有任何 agent 评测数据。

### 数据来源(哪些是原有的,哪些是后加的)

| 数据 | 来源 |
| --- | --- |
| HarnessEval-W 的 `benchmark/`(视频案例)、`runs/example`(示例结果) | **原有**(未被带入 agent-eval) |
| `examples/swebench/instances.json`(10 实例) | **后加**:HF `princeton-nlp/SWE-bench_Verified` 拉取,挑最轻实例 |
| `examples/swebench/rubrics/patch_quality.json` | **后加**:自写的 10 题 patch 质量 rubric(v2) |
| `examples/gdpval/cases.json`(3 任务) | **后加**:HF `openai/gdpval` 拉取 |
| `predictions.json`(pi 的 patch)、run/ 下 history/evidence | **后加**:pi(deepseek-v4-flash)真实运行的产物 |

## 2. 四层架构(项目骨架)

| 层 | 回答的问题 | 文件 | 状态 |
| --- | --- | --- | --- |
| 1 Rubric 数据化 | 评价标准如何定义与版本化? | `rubrics.py` + `skills/rubric.py` | ✅ |
| 2 History | 什么分数、哪个 rubric 版本、何时? | `history.py` | ✅ |
| 3.1 诊断 | 哪些问题有区分度?(方差/熵/相关) | `analysis.py` | ✅ |
| 3.2 Judge 可靠性 | LLM judge 可信吗?(κ/ρ/自一致) | `analysis.py` | ✅ |
| 3.3 版本迁移 | v1 结论能被 v2 继承吗?(排序保持) | `analysis.py` | ✅ |
| 3.4 Capability | 跨 benchmark 的潜在能力轴 | `capabilities.py` | ✅ |
| 3.5 Run Manifest | 这份报告在什么条件下产生? | `manifest.py` | ✅ |
| 4 Proposer | LLM 提案 rubric 修改,人批准 | — | ⏸ 门控中 |

**Layer 4 门控**:≥50 cases、≥3 agents、≥2 rubric 版本才启动自动
proposer——数据不足时,LLM 提案学的是噪声。

## 3. 一次 eval 的数据流(全景图)

```
cases.json / instances.json (领域数据)
        │ load_cases()
        ▼
Case {case_id, task, expected, metadata}
        │ build_router() → RuleRouter/LLMRouter
        ▼
Plan {selected_skills: [(skill_id, role, params)]}   ← 存 plan.json,可审计
        │ run_eval(config, cases, outputs)
        ▼
对每个 skill: Skill.evaluate(case, output)
   ├─ RuleSkill     (确定性:patch 应用/测试/artifact 存在性)
   └─ LLMSkill      (Judge: FineGrainedRubric 两阶段)
        │
        ▼
SkillResult {score, subscores, reasons, evidence, status}
        │
        ├─→ evidence/xxx.json   (逐 case 完整证据树)
        ├─→ history.jsonl       (EvalRecord,append-only)
        └─→ summary.json + LEADERBOARD (聚合报告)
        │
        ▼
Run Manifest (run_manifest.json): agent/环境/benchmark/evaluator 快照
```

**缓存机制**:每个 (case, skill) 的结果按 `digest(plan + skill实现 + input)`
缓存。改 rubric/skill/输出 → digest 变 → 自动重算。改 prompt 设计
(`evaluator_version`) 不污染历史。

## 4. 模块地图(每个文件为什么存在、怎么工作)

### 核心(`src/agenteval/`)

| 文件 | 职责 | 关键设计意图 |
| --- | --- | --- |
| `protocols.py` | 纯数据类:`Case` / `SkillSpec` / `SkillResult` / `Plan` / `CaseEvidence` | 所有跨模块通信只通过这些 frozen dataclass。`Case.expected` 是"裁判标准"的载体(rubric items / F2P 测试),不是答案。 |
| `io.py` | JSON/JSONL 读写、`value_digest`、`file_digest` | digest 是缓存正确性的根基:内容哈希而非时间戳。 |
| `backends.py` | `LLMBackend`(OpenAI 兼容),JSON mode、temperature 0、`extra_body thinking disabled` | judge 关闭推理:80 倍提速降本,稳定性更好。 |
| `planner.py` | `Router`(选择 skill)、`RuleRouter` / `LLMRouter`、plan 校验 | "先计划后执行",plan 落盘可审计。 |
| `runner.py` | `run_eval`:计划→执行→缓存→写 evidence/history/manifest | 编排核心。`RunConfig` 携带 agent 元数据。 |
| `score.py` | 聚合:加权 case 分、dataset summary | 框架默认 [0,1] 约定;GDPVal 的加权和(可 >1)是案例包自己实现的。 |
| `report.py` | 渲染 markdown 报告 | — |
| `rubrics.py` | `Rubric` / `RubricQuestion` / `RubricStore` | **Question 是数据**:id/question/anchors/evidence/weight/lineage/capabilities。lineage 是版本迁移的前提。 |
| `history.py` | `EvalRecord` + `HistoryStore`(JSONL append-only) | 无数据库,append-only 简单可靠。queries:by_skill/by_rubric/question_stats/... |
| `analysis.py` | 3.1-3.3 全部统计 | 见第 5 节。 |
| `capabilities.py` | `Capability(id, desc, parent)` + taxonomy 加载/校验 | 未来 ontology 的 schema,现在只做校验不做自动化。 |
| `manifest.py` | `EvaluationRun` + 写/读 run_manifest.json | 可复现性:报告附带产生条件。 |
| `cli.py` | `eval / analyze / migrate / verify` | 见第 9 节。 |

### Skills(`src/agenteval/skills/`)

| 文件 | 内容 | 意图 |
| --- | --- | --- |
| `base.py` | `Skill`(abc) / `RuleSkill` / `LLMSkill`;`role`: observation/core/diagnostic | role 让 Router 能组合"廉价预检 + 核心判定 + 诊断深查"。 |
| `registry.py` | `SkillRegistry`,skill 元数据(版本、输入 schema) | — |
| `rubric.py` | **`FineGrainedRubric`(LLMSkill 子类)** | 把 HarnessEval-W 的 rubric 机制封装成基类:新领域只声明 questions(数据)即可,不复制管道代码。 |

**FineGrainedRubric 的四条机制(核心中的核心)**:
1. **analyze/verify 两阶段分离** — 阶段 1 只读 case(不看 agent 输出)提取预期行为;阶段 2 才对照打分。防"先射箭后画靶"。
2. **离散分数阶梯** — 每题只取 `{0, .25, .5, .75, 1}`,每档有锚点定义。judge 方差从 std≈0.05-0.07 降到 ≈0.012。
3. **逐题强制 verbatim 证据** — 引用的证据必须逐字出现在输出里;伪造引用被拒绝并记入 `fabricated_evidence_rejected`。
4. **聚合策略** — mean / weighted / multiplicative-gate,子类声明。

### 案例包(解耦,注入式)

```
examples/swebench/           examples/gdpval/
├── instances.json           ├── cases.json       (3 任务:prompt+rubric items+交付物名)
├── cases.py  load_instances ├── cases.py  load_cases
├── skills.py                ├── skills.py
│   ├── PatchAppliesSkill    │   ├── GDPValJudgeSkill (FineGrainedRubric 子类)
│   ├── TestResolutionSkill  │   │   聚合 = 加权和(Σ满足项分值,可>1;负分=惩罚)
│   └── PatchQualitySkill    │   └── ArtifactPresenceSkill (规则预检)
├── container.py (docker)    ├── evaluate_gdpval.py
├── run_pi_agent.py/.mjs     └── outputs_demo.json
├── resolve_test_ids.py
└── evaluate_predictions.py
```

## 5. 诊断系统的逻辑(3.1-3.3 的"为什么")

### 3.1 每题的 question_metrics
- **variance/entropy/difficulty**:描述分布形态。
- **discrimination = corr(question, total)**:IRT 风格的项目质量代理。
- **为什么必须用 corr 消歧**:低方差有三种解释(都很好/太容易/judge
  bias)——**排序相关区分它们**:corr 高 = 该题与总分一致(即使方差低
  也有用);corr 低/负 = 噪声或锚点反了(inverted anchors)。
- verdicts:`ceiling`(全满分)/ `floor` / `noisy`(弱或负相关)/ `keep` /
  `insufficient_data`。

### 3.2 judge↔rule agreement
- 同一 case 的 LLM judge 分 vs 规则 skill 分配对。
- **Cohen's κ**:机会校正后的一致(防"永远 pass 的 judge 表面 100% 准")。
- **Spearman ρ**:原始分数的排序一致。
- 边界:全通过时 κ 无定义(p_exp=1),报告显式说明——这是数据问题
  不是 bug。

### 3.3 版本迁移
- **核心信条:比排序,不比绝对分数**。绝对分数会漂移,排序保持
  (Spearman ρ + Kendall τ)才是"v1 结论能否继承到 v2"的信号。
- 漂移分类:`systematic`(全部同号,如评分更严)vs `mixed`(逻辑变了)。
- `RubricQuestion.lineage`(祖先 ID)为未来 proposer 铺路。

## 6. 关键决策表(决策 → 为什么)

| 决策 | 为什么 |
| --- | --- |
| judge 关闭推理(thinking disabled) | 80 倍提速降本,稳定性更好(28k→354 tokens) |
| 离散档位 + 锚点 + 两阶段 + verbatim 证据 | judge 方差 std 0.05-0.07 → 0.012 |
| History 用 JSONL 不用 DB | append-only 简单可靠,规模足够 |
| SWE-bench 用 stdin 传 patch,不用 bind mount | Windows/WSL 下 bind mount 路径会变目录(坑) |
| pi agent 不进容器,只在打分时用容器 | 容器构建慢(8-22s),agent 在 host 跑,镜像直接官方基础 |
| 不装全 swebench 包,只挑轻量实例 | 依赖与镜像成本控制 |
| judge prompt 不给具体 JSON 键示例 | DeepSeek 会照抄示例形状,把 I00.. 改名成 Q1..(contamination) |
| evaluator_version 与 rubric_version 分离 | prompt 设计变化不污染历史数据(migration 前提) |
| GDPVal 聚合用加权和 | GDPVal 总分 = Σ满足项分值,可>1;负分项 = 惩罚 |
| 两阶段 docker:先 collect 再跑 | pytest 8 遇单个过期 node id 会 abort 整个运行(坑) |
| 空 F2P 不算 resolved | 测试模块 import 失败 → F2P 全收集不到 → 空列表误判通过(坑) |

## 7. 踩坑史(每个坑都是教训,别重蹈)

| 现象 | 根因 | 修复 |
| --- | --- | --- |
| git apply 报 corrupt patch | `splitlines()+join` 吞 patch 末尾换行 | 保留原始字节,不 split |
| bind mount 变成目录 | Windows/WSL 路径转换 | 改 stdin 传 patch |
| judge 返回键 Q1-Q37 而非 I00-I37 | prompt 里的 `{"Q1":...}` 示例被照抄 | 删示例,只描述"键必须是 rubric 里列出的 id" |
| 全链路 0.0/None 分数 | DeepSeek 响应格式漂移(扁平 vs 嵌套 dict) | parse 兼容两种格式 |
| GDPVal 总分被 summary 过滤 | 框架 [0,1] 约定,GDPVal 和 >1.0 | GDPVal 包自写 summary(score/max_possible) |
| pytest `no tests ran` | CLI 有 1 个 not found node id → 全 abort,`--continue-on-collection-errors` 无效 | 两阶段:先按文件 collect,过滤,再跑 |
| pylint/pytest 空转通过 | 测试模块 import 失败 → F2P 全 drop → 空列表=通过 | `no_f2p_collected` 保护 |
| `test_capsysbinary.py::test_hello` 找不到 | 数据噪声:缺 testing/ 前缀;test_hello 实际在 test_skipping.py | resolve 用仓库 grep `def <name>` |
| P2P 短名"同文件"假设错误 | 23950 的 test_issue_10326 在 test_sets.py | 必须仓库 grep,不能假设同文件 |
| requests timeout 测试失败 | 容器无外网(ReadTimeout 0.1s) | 从 P2P 剔除 + notes 记录 |
| pylint `py is not a package` | 测试套件 import `py._path`,基础镜像 py 是 shim | Dockerfile 单独装 `py>=1.11` |

## 8. 当前状态(2026-08)

**数据**(SWE-bench 10 实例,全部真实):
- `gold`(参考):10/10 resolved
- `pi`(deepseek-v4-flash,host 跑):10/10 resolved(轻量切片,9-12 行 patch)
- patch_quality 均值 0.893(0.425-1.0)
- GDPVal:3 任务,模拟输出(非真实 agent),judge 机制验证通过

**诊断(真实数据)**:Q2_localization 判定 **ceiling**(轻量切片零区分度,
corr=None → 正确消歧);其余 9 题 keep(corr 0.67-0.97);judge↔rule 全
TP(数据太简单,κ 无定义)。

**门控进度**:10/50 cases、2/3 agents、1/2 rubric 版本 → Layer 4 未解锁。

## 9. CLI 速查

```bash
# 评测(案例包内)
python evaluate_predictions.py --predictions predictions.json --run-root run/pi --agent-name pi --agent-version v1
python evaluate_gdpval.py --outputs outputs_demo.json --run-root run/demo --agent-name pi

# 诊断(rubric 质量问题)
agenteval analyze --history run/pi/history.jsonl --history run/gold/history.jsonl \
    --rubric patch_quality --judge-skill patch_quality --rule-skill test_resolution

# 版本迁移
agenteval migrate --history ... --skill patch_quality --old-version v1 --new-version v2

# 验证 run 完整性
agenteval verify --cases instances.json --run-root run/pi
```

环境变量:`AGENTEVAL_DOCKER`(docker.exe 路径)、`DEEPSEEK_API_KEY`、
`AGENTEVAL_JUDGE_BASE_URL/MODEL`、`unset HF_ENDPOINT`(HF 直连)。

## 10. 路线图

```
现在: 积累真实数据(更多实例/难度分层/第三 agent)
      ├─ 让 pi 有失败案例 → 激活 noisy/inverted/κ 等诊断路径
      ├─ 更多 agents(≥3)→ 能力对比报告
      └─ 迭代 rubric 版本(≥2)→ migrate 有真实数据
然后: 达到门控 → Layer 4 proposer(LLM 提案 + 人批准 + A/B 验证)
未来缝(已记录未实现):Artifact 抽象 / JudgeContract(schema validator
     独立于 prompt)/ Capability rollup(父级聚合)
```

---

**一句话总结设计哲学**:评测框架的价值不在"能跑",而在**评价标准本身
可以被测量、被诊断、被版本化**。数据是唯一的检验标准——所有自动化
(proposer)都被门控在真实数据门槛之后。
