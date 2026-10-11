# Trust game：论文规则与 LLM 实验实现

核对日期：2026-10-10。论文：Jia et al., *Social networking agency and prosociality are inextricably linked in economic games*, Nature Human Behaviour (2025), DOI [10.1038/s41562-025-02289-0](https://doi.org/10.1038/s41562-025-02289-0)。

本次读取的本地 PDF 共 69 页，包含 ResearchGate 封面、作者稿正文、Extended Data 及补充材料。下面的页码均为 PDF 物理页码，另注明补充材料原页码，避免不同版本混淆。

## 来源与实现映射

| 实验要素 | 原文依据 | 实现 |
| --- | --- | --- |
| 固定四邻居、角色整个 session 不变，能观察邻居类型 | 正文 Methods，PDF p11；SI Appendix A，PDF p29 | 周期边界四邻居邻接表，角色只初始化一次 |
| 每轮所有人先投资，再所有人返还 | 正文 Results，PDF p5；Methods p11 | investor → 整理收到的投资 → trustee → 整理收到的返还 → 结算 |
| 每轮最多发送 5 tokens，金额非负、最多两位小数 | SI Fig. A7/A9，PDF p38/p40 | Decimal 预算约束与向下舍入 |
| 受限投资者必须等额，自由投资者可区别分配 | 正文 p5/p11；SI trust-game instructions p33 | 第一阶段按角色执行等额或自由分配 |
| 投资乘以 3；两类受托者均向四邻居等额返还 | SI Fig. A3 p34、A7/A9 p38/p40 | 返还预算=3×收到的总投资，返还一律等额 |
| 投资者收益=收到的返还−发送的投资 | SI instructions p33；Fig. A8/A10 p39/p41 | 去除旧代码的额外 +5 |
| 受托者收益=3×收到的投资−发送的返还 | 同上 | 两阶段净收益之和进入累计收益 |
| 全体每轮总收益=2×总投资 | SI Appendix D.2.2，式 D12，PDF p64 | 回归测试及结果校验 |
| 不告知总轮数 | Methods p12；SI p29 | 默认 total_round_info=false |
| 人类实验每 session 49 人、50 轮；每处理三次 | Methods p11/p12；SI Table A1 p30 | configs/paper.json：49 人、50 轮、五种比例、三次重复 |

论文收益说明容易与标准信任博弈的“保留未发送的禀赋”混淆。本实验的未发送禀赋不计入累计收益。SI Fig. A8 的投资者示例：发送 1.12、收到 3.95，净收益为 2.83；受托者收到 6.03、返还 5.20，净收益为 0.83。图中累计余额为 32.56+2.83+0.83=36.22。式 D12 同样给出 Q=−A+R+(3A−R)=2A。这些证据比仅依据常见博弈定义更明确。

## LLM 实验设定与人类实验的差别

默认试运行是 9 人、1 轮、目标比例 0.5、一次重复、deepseek-flash、不思考。它用于验证代码与接口。paper.json 才采用人类实验的规模和重复数，正常需要 73,500 次代理阶段调用，不含重试；本次没有运行这个大规模配置。

角色数量采用 floor(N×p)，保留既有实现；9 人、p=0.5 对应 4 名自由玩家，实际比例 4/9。49 人时混合组对应 12、24、36 名自由玩家。论文提供目标比例，但本地文本未明确人数取整方法，因此输出保存目标比例、实际人数和实际比例，不声称这一定对应每个原始 session 的实际人数。

系统提示沿用仓库的英文人物设定和行为背景，修正计分公式；这些人物不等同于论文的中国大学生样本。论文原界面采用“点玩家／边玩家”减轻措辞 framing；现有英文提示使用 constrained/free。论文是匿名实验，代码没有模拟真人的金钱激励、理解测验和 30 秒界面操作。论文数值模拟在 Appendix D 中使用经验转移概率和固定返还率，本项目以 LLM 决策代替，不复刻那套数值算法。

默认每位智能体保留最近 3 个完整轮次的投资／返还问答，再加上当前轮已有问答。系统提示始终保留。history_rounds=null 可切换完整历史，不进行自动摘要。这是作者选择的 LLM 记忆条件；论文的人类参与者记忆没有被人为限制为三轮。完整原始对话仍保存在 dialogue.json 和 checkpoint.json，不因请求窗口截断而删除。

## 决策修正政策

1. 解析最终金额字典；受托者也支持单个总返还额。
2. 负数、非有限数、非数值金额置 0；缺少邻居补 0，非邻居编号忽略。
3. 总额超预算时按比例缩小。受限投资者及所有受托者保持合法总额后四等分。
4. 每个金额向下保留两位小数，保证不超预算；等额分配时不为用尽剩余分币而破坏等额规则。
5. 完全无法解析时采用全零，明确标记 parse_failed。空字典和无效金额也会触发记录的修正。
6. 保存原始文本、解析值、执行值、修正原因和失败标记；下一次提示反馈实际执行金额。

论文的人类界面对非法输入提示重新输入；本项目采用自动修正以减少额外模型调用。API 故障与解析失败分开：API 请求失败永远不替换成玩家全零决策。

投资者发给受托者的成对记录，returned_amount 为受托者反向返给投资者的金额；旧代码取的是投资者自己发出的返还，已修正。原有玩家 CSV 字段保留，并增加种子、实际比例和修正／解析标记。历史输出不会被重算，因此新旧收益和成对返还口径不可直接混用。

## 实现与版本记录

Mesa、CAMEL、MCP 均从实验源码和新依赖声明中移除。网格、角色、金额传递、计分、阶段推进由普通 Python 实现；兼容接口仅使用 openai SDK。基础种子派生独立 session 种子，控制角色分配；远程 LLM 输出不承诺确定性。

保存 schema_version、核心源码与提示词 SHA-256、接口地址、请求模型名、实际返回模型名、每次响应 ID、usage、生成设置和完整对话。暂停恢复要求源码和提示词匹配。日志和输出不保存 API Key。代码在 dev 分支实现，历史数据仍位于 src/outputs/。

DeepSeek 非思考请求使用 extra_body={"thinking":{"type":"disabled"}}。thinking=true 切换 enabled，llm.py 中有对应注释。其他兼容供应商使用 api_base_url、api_key_env、model_type_list 和 extra_body 配置；不会向非 DeepSeek 模型自动发送 DeepSeek 专属参数。依据：[DeepSeek Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)。
