# 固定评测集：Octagon LLM Judge 5-case v1

创建日期：2026-09-02。固定 5 个明确依赖 LLM-as-judge 的 AgentOctagon task，用于 AgentEval 与 `octagon-evals` 的 Judge 正确率/稳定性对照。

## 任务

1. `gdpval-source-faithfulness-official` / `gdpval_fall_music_tour_official`：Excel source-faithfulness。
2. `presentbench-academia-official` / `presentbench_academia_official`：学术 PPT。
3. `presentbench-advertising-official` / `presentbench_advertising_official`：广告 PPT。
4. `user-programming-scenario-visitor-appointment` / `user_programming_scenario_visitor_appointment_001`：访客预约 workflow。
5. `user-programming-scenario-weather-forecast` / `user_programming_scenario_weather_forecast_001`：天气 Web UI 与浏览器证据。

`manifest.json` 固定 task ID、选择策略和回放规则；`tasks.jsonl` 保存任务快照、Judge 维度、相关 rubric/reference 的 SHA-256 及建集时的历史 attempt 参考。原始文件仍位于 `/home/yang/agent-octagon-envs`，运行前必须校验 digest。

环境自带 Judge/scorer 输出不得直接当作 correctness Gold；正确率实验需要独立 human-reviewed Gold。稳定性实验默认每个 task 重复 5 次，并记录具体 attempt_id、model、rubric/prompt version 和代码 digest。


## Agent runtrace

本版本已经把每个 task 的 canonical completed attempt 的 semantic runtrace 放入 `runtraces/<attempt_id>/`，并在 `tasks.jsonl` 保存源路径、固定副本 digest 和 run metadata。主要包括 `trace.jsonl`、`trajectory.json`/`conversation.jsonl`、`wire.jsonl` 以及必要的 supporting runtime records。原始 `events.jsonl` 不复制到 Judge 主输入：它是可能含大量重复 delta 和 capture 噪声的 raw stream，只保留源文件 digest/reference。

## 系统问题排除

固定集使用 `case_eligibility` 和 manifest 的 `system_failure_exclusion`：

- transport、runtime、capture/parser、evaluator、auth、local process restart 等系统问题不算作 Agent 的错误，也不能降低 Judge accuracy；
- 只要 canonical attempt 的 task-solving trace 有效，过滤系统记录后仍保留该 case；
- 如果一个 case 只剩系统失败证据，则标记 `case_system_invalid`，从 accuracy denominator 删除；
- Agent 可见的命令失败、依赖缺失、业务验证失败、Agent recovery 和错误完成声明都属于正常评测证据，不能被系统过滤。

本次 5 个 canonical attempt 均为 `completed` 且 execution/scoring error 为空；其中任何 capture-only 或 system-layer records 仍按上述规则排除。
