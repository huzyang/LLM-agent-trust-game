# LLM-agent-trust-game 使用说明

本项目以 LLM agent 执行 Jia 等人 2025 年 Nature Human Behaviour 论文的空间信任博弈规则。[规则与原文核对](docs/trust-game-protocol.md) · [验证记录](docs/verification.md) · [离线分析](docs/offline-analysis.md)

## 安装与默认运行

推荐 Python 3.12，从项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-experiment.txt
.\.venv\Scripts\python.exe -m pip check
```

实验仅有 openai、python-dotenv、pandas、openpyxl 四项直接依赖，已移除 Mesa、CAMEL、MCP。已有虚拟环境中的旧包不会被自动卸载；希望环境也精简时请使用新虚拟环境。requirements-experiment-lock.txt 是当前实验依赖闭包，共 26 包；requirements.txt / requirements-lock.txt 包含分析依赖，共 40 包，均不是历史实验环境的还原。

复制 .env.example 为 .env，填写 DEEPSEEK_API_KEY；已有 .env 保持不变。模型名现在由 JSON 配置控制，旧 DEEPSEEK_MODEL 环境变量不再控制模型。

```powershell
# 只检查配置，不请求 API，也不生成结果
.\.venv\Scripts\python.exe -m src.experiment.run_main --dry-run
# 离线模拟，输出明确标记为 MOCK
.\.venv\Scripts\python.exe -m src.experiment.run_main --mock
# 真实实验，使用账户额度
.\.venv\Scripts\python.exe -m src.experiment.run_main
```

也支持直接执行 src/experiment/run_main.py。

默认：9 人、1 轮、目标自由比例 0.5、一次重复、deepseek-flash、关闭思考、不报告 BDI、不告知总轮数、基础随机种子 42。正常调用 18 次，重试另计。角色人数向下取整，实际为 4/9，输出同时记录目标比例和实际比例。

默认 max_tokens=512，只用于回答输出；context_limit=131072 是单独的本地上下文上限。保留最近 3 个完整轮次问答，加上当前轮已有消息和始终保留的系统提示；完整对话归档不会删掉。新实验可设置 history_rounds=null 使用完整历史，不自动摘要。

DeepSeek 请求通过 extra_body 设置 thinking.type=disabled；配置 thinking=true 可开启，llm.py 中有注释。其他 OpenAI 兼容供应商可以配置 api_base_url、api_key_env、model_type_list、extra_body；非 DeepSeek 模型不会自动收到 DeepSeek 专属开关。API Key 只放 .env／环境变量。

## 暂停、恢复和日志

每次成功决策后，原始回答、实际执行金额、历史和下一玩家游标一起原子保存。临时网络故障、超时、408/409/429 和服务器错误最多重试两次；认证、余额、配置、上下文错误直接暂停。Ctrl+C 同样暂停。API 故障不会记成零投资。

```powershell
.\.venv\Scripts\python.exe -m src.experiment.run_main --resume "outputs/你的实验目录"
```

恢复时跳过已保存的调用，保留角色、种子、阶段与历史，从环境变量重新加载密钥。源码和提示词须与检查点匹配；JSON 仅允许覆盖 context_limit、max_tokens、request_timeout、max_retries、retry_delay。mock／真实模式不能混用。退出码 0 表示完成／验证成功，2 表示暂停／失败。

本地上下文估计采用 UTF-8 字节量和输出预留，是偏保守的估计，不等于供应商精确 tokenizer；供应商报上下文超限也会暂停。若在供应商已接受请求但本地尚未保存时强制杀进程，恢复可能需要重发这次不确定请求，无法保证远程计费恰好一次。

输出位于 outputs/<时间戳>_llm/，可以用 --output-dir 指定新的空目录：

- run.log：逐玩家调试记录；控制台仅显示配置、阶段进度、重试、暂停和结果路径。
- events.jsonl：完整请求消息、请求结果／错误、usage、原始与执行决策及修正原因。
- checkpoint.json：权威恢复状态；config.json：不含密钥的配置与源码／提示词指纹。
- 每个 run 子目录：agent_rounds.csv、pair_data.xlsx、dialogue.json、summary.json。
- 根目录 agent_rounds.csv、pair_data.xlsx、summary.json：整批已完成实验的汇总。

控制台不打印完整提示词、人物设定或逐玩家决策。25 人以上的阶段每保存十次决策显示一次进度。密钥不会写入配置，日志进行脱敏。详细对话仍应按实验数据保管。

## 规则与修正

按论文 SI 参与者说明和 Fig. A8/A10：投资者净收益=收到返还−发送投资，受托者净收益=3×收到投资−发送返还。未发送的每轮 5-token 禀赋不加入累计收益，已去除旧代码的 +5。两类受托者都必须向四邻居等额返还。每轮全体总收益=2×全体总投资（SI 式 D12）。

非法决策按已约定政策自动修正，不增加模型调用：超预算按比例缩小，受限投资和所有返还四等分，负数／无效值置零，缺邻居补零，非邻居忽略，向下舍入两位小数。完全无法解析采用全零并标记。记录原始回答、执行金额、原因、解析失败和修正次数，并反馈实际执行金额。

交易 A→B 的 returned_amount 现在取 B→A 的返还，修复旧代码取 A→B 返还的方向错误。原有玩家 CSV 字段保留，并加入审计字段。新旧收益与交易口径不同，不能无说明地合并历史结果。

## 论文规模与验证

configs/smoke.json 对应默认小实验。configs/paper.json 使用人类实验规模：49 人、50 轮、五种比例 [0,0.25,0.5,0.75,1]、每组三次重复，正常需要 **73,500 次调用／模型**，不含重试；本次只运行小实验。

```powershell
.\.venv\Scripts\python.exe -m src.experiment.run_main --config configs/paper.json --dry-run
.\.venv\Scripts\python.exe -m unittest discover -s test -p test_experiment.py -v
```

保留现有英文人物设定和 3 轮记忆窗口属于 LLM 实验设计，与真人样本、金钱激励、原中文界面及自由记忆不同。原文明确用“点玩家／边玩家”避免 framing，而现有提示采用 constrained/free。paper.json 对齐规模不等于保证复现人类行为；也不实现论文另行拟合经验转移概率的数值模型。[详细边界与来源](docs/trust-game-protocol.md)。

## 离线人类数据分析

安装 requirements-offline.txt，无需 API Key：

```powershell
.\.venv\Scripts\python.exe -m src.analysis.nhb_analysis --input "src/outputs/2024_NHB_model_Trust Game.xlsx" --output-dir outputs/nhb_offline
```

原始工作簿五种比例、每种三次 session、每次 49 人 50 轮，共 36,750 条玩家记录和 147,000 条方向金额记录。不处理参与者信息表，不改原文件，不跨 session 按玩家编号配对。先计算 session 每轮均值，再等权平均三次 session；负累计收益组的常规 Gini 标为未定义。

它使用原始记录的收益，不自动重算；指标说明见 docs/offline-analysis.md，不宣称精确复刻论文所有图表或统计检验。成对导出保留等额的不同交易：

```powershell
.\.venv\Scripts\python.exe -m src.analysis.pair_data_analysy --input "outputs/实际实验目录/pair_data.xlsx" --output outputs/pair_plot_data.xlsx
```

论文发布前仍需核实原始数据出处、使用条件和许可证，并固定代码、提示词、模型与配置版本。历史数据保持在 src/outputs/，新结果在 outputs/。
