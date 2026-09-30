# LLM-agent-trust-game 使用说明

本仓库提供 LLM 空间信任博弈代码，以及使用 `2024_NHB_model_Trust Game.xlsx` 的离线描述性分析示例。完整参数、限制和故障处理见 [英文 README](README.md)，指标定义见 [离线分析说明](docs/offline-analysis.md)。

## 环境安装

推荐 Python 3.12。所有命令从仓库根目录执行：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-offline.txt
```

离线分析只需上述依赖。在线实验及旧绘图工具还需：

```bash
python -m pip install -r requirements.txt
python -m pip check
```

完整验证环境记录在 `requirements-lock.txt`，可用 `python -m pip install -r requirements-lock.txt` 安装。它是本次整理后检查的环境，不代表历史实验当时使用的全部软件版本。

## 离线分析

无需 API Key 或 API 额度：

```bash
python -m src.analysis.nhb_analysis \
  --input "src/outputs/2024_NHB_model_Trust Game.xlsx" \
  --output-dir outputs/nhb_offline
```

原始工作簿包含五种比例、每种三次 session，每次 49 名玩家、50 轮，共 36,750 条玩家轮次记录。脚本只读取 15 张实验表，不处理参与者信息表。全部四方向金额保留，生成 147,000 条方向金额记录。

计算顺序为：先在每个 session 每轮对玩家求均值，再对三次 session 的均值求等权平均和样本标准差。输出中保留 session 标识，不跨 session 按玩家编号配对平均。遇到负累计收益，该组常规 Gini 标为未定义，不删除负值或自行平移收益。

这是可运行的指标计算示例；尚未与论文各图表建立逐一映射，也不宣称精确复刻论文图表或统计检验。工作簿的 49 人、50 轮与 LLM 默认 36 人、20 轮不同。

## 在线实验步骤

当前作者账户无 DeepSeek 额度，在线调用未验证。配置检查可离线完成：

```bash
python -m src.experiment.run_main --config configs/paper.json --dry-run
```

默认五种比例为 `[0, 0.25, 0.5, 0.75, 1]`。当前其余代码默认：36 人、20 轮、每比例 1 次重复、temperature=1.0、不报告 BDI、不告知总轮数。除五种比例外，其余参数需与最终论文再核对。三次重复可复制配置后将 `iterations` 改为 `3`。

有额度后：

```bash
cp .env.example .env
# 编辑 .env：填写 API Key、供应商的兼容接口地址和实际可用模型名
python -m src.experiment.run_main --config configs/smoke.json
python -m src.experiment.run_main --config configs/paper.json
```

小规模配置预计 18 次代理阶段调用，完整默认配置预计 7,200 次，三次重复为 21,600 次；均未包含重试。SDK 请求数、时间与费用取决于模型和供应商。新结果写入根目录 `outputs/`。`.env` 和新生成结果已加入 Git 忽略规则。

角色分配当前未固定随机种子。API 失败可能被替换成全零决策，须检查日志及对话记录中的 `ERROR`，不要直接当作正常行为统计。远程模型更新也可能影响复现。

## 不再按金额去重

成对数据脚本保留所有交易，包括金额相同的不同邻居交易：

```bash
python -m src.analysis.pair_data_analysy \
  --input "outputs/实际实验目录/实际_pair_data.xlsx" \
  --output outputs/pair_plot_data.xlsx
```

论文发布前还需补齐原始数据出处和使用条件、论文引用、作者信息与许可证，并固定一个与论文对应的版本。
