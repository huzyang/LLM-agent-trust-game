# Local verification

## 2026-10-10：dev 分支轻量实验重构

环境：Windows、Python 3.12.4；当前项目虚拟环境。代码和依赖声明已移除 Mesa、CAMEL、MCP。旧环境中的包未自动卸载，使用 import 拦截测试确认实验入口不依赖这些包、tiktoken 或绘图库。

完成的验证：

- 默认配置与 smoke.json：9 人、1 轮、p=0.5，18 次计划调用。paper.json：49 人、50 轮、五种比例、三次重复，73,500 次计划调用；只验证配置，未发起该规模实验。
- 19 项回归测试：网格／种子、论文净收益、成对反向返还、三轮／完整历史、金额不变量、API thinking 参数、临时错误重试、认证与上下文暂停、阶段中途及阶段／结算边界恢复、多 session 恢复、Excel 种子精度及新旧指纹兼容／实际代码变化拒绝。
- HTTP 模拟验证 SDK 请求：DeepSeek thinking.type=disabled；开启时 enabled 且不发送无效 temperature。普通兼容模型不附带 DeepSeek 专属字段。
- 9 人离线流程输出 9 条玩家记录、36 条交易；所有模拟输出带 mock 标记。
- 投资与返还阶段多个断点恢复，结果和不中断运行完全一致，已保存的调用无重复。
- 临时注入超小上下文预算：保存并暂停；仅调高 context_limit 后恢复完成，不将请求失败转成零决策。
- 金额生成检验涵盖 300 组输入，核对非负、预算、两位小数及等额约束。
- 默认真实 DeepSeek 试运行：18 次成功调用，响应模型 deepseek-flash，13,459 tokens；解析失败 0，修正 0，非空 reasoning_content 0。
- 真实输出：9 条玩家记录、36 条交易；总投资 45，总净收益 90，符合论文 SI 式 D12；检查点 complete。
- 沙箱内首次连接失败时保留了 0/18 进度；沙箱外按检查点恢复后完成，未重做已保存决策。
- 当前依赖闭包：实验 26 包，实验＋分析 40 包；由现有环境 metadata 解析基础依赖，不包括未启用 extras。锁文件不代表历史环境或跨平台安装认证。
- git diff --check；实验入口支持模块与直接脚本方式。

真实试运行结果位于 outputs/refactor_smoke_live_20261010/，日志、事件、对话、配置和检查点均保留。API Key 未写入版本文件或输出。

未验证：人类实验效应量或统计显著性复现、49 人全量在线实验、远程模型确定性、所有供应商的非标准参数。论文规则及与真人条件的差异见 trust-game-protocol.md。历史记录中的 +5 收益已经在本次重构中改正，不适用于新实验。

## 2026-09-30：重构前版本的历史验证记录

Checked on 2026-09-30 using a new Python 3.12.14 virtual environment. Direct dependencies are in `requirements.txt`; the installed package versions are in `requirements-lock.txt`.

Completed checks:

- Dependency installation and `python -m pip check`: no broken requirements.
- Import of the simulation model and pair-data analysis module.
- Full and small JSON configuration dry-runs: 7,200 and 18 planned agent-stage calls respectively; no API requests.
- Offline workbook analysis: 36,750 player-round rows, 147,000 directed rows, 750 session-round summaries, 250 treatment-round summaries.
- Summary row counts and across-session means checked against the original player records for each treatment's first round.
- Sum of directed sends checked against the recorded total sends.
- Known Gini examples checked: equal values yield 0; [0, 1] yields 0.5. Negative-payoff groups remain undefined.
- Equal-amount transactions checked to remain present in grouped pair exports.
- A nine-agent, one-round simulation with locally replaced model/chat objects and zero decisions: nine agent-round records, 36 pair records, payoff of 5 per agent. No remote API requests; this validates local flow only.
- The documented matplotlib plotting example executed and its PNG inspected. This is a descriptive example, not a publication-layout certification; automated PDF collision QA was unavailable because the audit runtime lacks PyMuPDF.
- Python source syntax and `git diff --check`.

Not verified:

- DeepSeek authentication, balance, model availability, SDK response parsing against a live endpoint, or a paid experiment.
- Exact correspondence between the example indicators/figures and a manuscript.
- Recovery of historical dependency versions, original workbook provenance, or redistribution permissions.

The current checks use the working-tree prompt templates, which include author edits made before this documentation task. Before a paper release, freeze the intended prompts together with the code and data versions.
