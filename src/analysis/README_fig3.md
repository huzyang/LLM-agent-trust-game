# Fig. 3 reproducible Origin pipeline

**主脚本：`src/analysis/fig3.py`。** 在仓库根目录运行；Windows 启动入口为 `src/analysis/run_fig3.ps1`。

| 文件 | 用途 |
| --- | --- |
| `fig3.py` | 主脚本：原始记录 → 统计/绘图数据表 → 可编辑 Origin 图形 |
| `run_fig3.ps1` | 启动及环境检查，自动定位项目与默认数据路径 |
| `test_fig3_data_contract.py` | 数据完整性和重复输入保护测试，支持模块与直接文件运行 |
| `requirements_fig3.txt` | 本工具依赖清单；独立于其他分析脚本的依赖 |
| `FIG3_LATEST_OUTPUT.txt` | 最近一次已验证交付目录的位置记录 |

本目录提供从原始记录到数据表、再到可编辑 Origin 图形的源码。当前图为 **LLM 单场次初版**，不替换论文中的最终图。人类数据保留全部三个场次，双方观察窗口均为前20轮。

## 环境与执行

数据处理可独立运行；Origin 绘图需实体 Windows 10/11 x64、64位 Python 3.10–3.12，以及本地安装且自动化接口可调用的 Origin/OriginPro 2021 或更新版本。当前验证目标为 Origin 2021 9.80.200。脚本不安装、修改 Origin，也不附着到已有用户窗口。

在仓库根目录创建 Python 环境并安装依赖（已有 `.venv` 可直接复用）：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r src/analysis/requirements_fig3.txt
```

从原始数据一键生成数据表及 Origin 图形：

```powershell
.\.venv\Scripts\python.exe -m src.analysis.fig3 all `
  --human "E:\huzy_work\ubuntu_files\llm_paper_review\NHB_Experiment Data\2. Trust Game.xlsx" `
  --llm-session "E:\huzy_work\DevLearningCode\LLM-agent-trust-game\outputs\20261011_000304_540158_llm_01"
```

其他电脑只需更改输入路径。默认交付目录在第一批 LLM 原始数据所在目录内，名为 `agent_rounds_EditaPlot_YYYYMMDD_HHMMSS`。`--output-dir` 可指定新的输出目录，已有目录不会由 `prepare` 或 `all` 覆盖。

在当前作者电脑上可直接执行下面的命令，从任何目录调用该启动文件均可：

```powershell
.\src\analysis\run_fig3.ps1 -CheckOnly              # 只检查解释器、依赖及输入路径，不启动 Origin
.\src\analysis\run_fig3.ps1                         # 原始数据处理 + Origin 绘图
.\src\analysis\run_fig3.ps1 -Mode prepare           # 只生成分析表
.\src\analysis\run_fig3.ps1 -Mode render -OutputDirectory '已准备的数据目录'
```

启动脚本优先使用仓库 `.venv`，然后尝试脚本目录 `.venv`、本机已有 Anaconda 或 PATH 中的 Python。Origin 部分优先使用同一解释器；若其缺少 `originpro`，可复用当前用户已安装的 EditaPlot 环境，也可通过 `-OriginPythonExecutable` 显式指定。数据解释器可用 `-PythonExecutable` 指定，不会自动安装依赖。普通复现者安装 `requirements_fig3.txt` 后可在一个环境内执行全部步骤，**不需要 Codex 或 EditaPlot**。

三场次例子：

```powershell
.\src\analysis\run_fig3.ps1 -LlmSessions @('第一批目录', '第二批目录', '第三批目录') -HumanWorkbook '人类原始数据.xlsx'
```

只生成数据表：将 `all` 换成 `prepare`。已有数据表单独绘图：

```powershell
.\.venv\Scripts\python.exe -m src.analysis.fig3 render --output-dir "已生成的数据表目录"
```

加入三个独立重复时，将 `--llm-session` 重复三次，分别传入三个独立运行目录。**不要同时传入汇总 CSV 和其中的子运行 CSV**。同一文件内容重复输入会报错，缺轮次、重复记录、人数不符及主要运行配置不一致也会报错。每个运行目录内使用的是汇总 `agent_rounds.csv`；`run_id` 在这里区分 p 条件，不被当作独立重复次数。`iteration` 才是该目录内的重复标识，目录本身也参与场次标识。

## 图形与数据口径

八个面板按行编号 `(a)`–`(h)`；四列依次为 LLM 投资额、人类投资额、LLM 返还额、人类返还额。

- 上排展示个人前20轮平均金额的分布：原生 Origin 箱体、全部个人均值散点和均值线，撤去均值95% CI。
- 下排展示个人均值的总体均值与常规双侧95% t 区间。
- LLM 金额使用 `total_sent`、`total_returned`，人类使用 `player.send_T`、`player.return_T`。均为每轮面向四名邻居的总金额，不作除以4或归一化。
- 人类每个条件147人，LLM 初版每个条件49个智能体。每个人的20轮先求均值，不把20轮当作20个独立样本。
- `p` 是设计的名义比例，仍使用 0、0.25、0.5、0.75、1。LLM 实际实现比例保存在选定记录表中，不悄悄改动横轴。
- 散点的横向抖动只用于避免重叠，使用固定随机种子；所有纵轴值和所有观测均保留。
- 两类人群在同一指标上使用一致的纵轴范围；不使用断轴放大差异。
- LLM 五色来自原 OPJU 的 `Graph4`/`round_mean_sent`；人类五色来自 `Graph8`/`Graph9`，与既有 Fig. 4 一致。精确颜色写在 `fig3.py`。

## CI、SD 与推断边界

下排：`mean ± t(0.975, n−1) × s / sqrt(n)`，其中 `s` 是个人20轮均值的样本标准差，`n` 是个人数。它是基于个体独立假设的常规区间，**未处理同一网络内的互动依赖，不表示场次间不确定性**。初版不能用这一 CI 声称“已经解决审稿人的独立重复问题”。没有进行人类与 LLM 的显著性检验或方差差异检验。

`session_summary.csv` 单独列出各场次均值和个人均值 SD；`between_session_summary.csv` 列出场次均值之间的 SD。LLM 当前仅一个场次，因此其场次间 SD 为缺失值，不填0、不虚构另外两次重复。后续传入三个 LLM 目录会重新计算所有个人分布、均值、CI 和场次汇总。

人类的20轮均值替代原项目的50轮均值；因此不能继续使用原人类均值数值标记而声称已经统一窗口。原 OPJU 内部分表格为36智能体实验，故不作为当前49智能体图的原始数值来源。

## 输出与二次编辑

`Fig3.opju` 含八个原生图层、链接工作表、数据曲线、误差棒和可编辑文本；不是位图背景。另保留单面板图便于手工调整。可在 Origin 中修改字体、颜色、坐标轴和图层布局；修改数据处理口径或追加实验时应重新运行源码。

为兼容 Origin 2021，下排的 CI 由工作表关联的纵向区间线、端帽和均值点组成，均为可编辑曲线。p 刻度文字为单独可编辑的文本对象，避免箱图模板对分类刻度的特殊处理；若手动改变横轴范围或移动图层，也要相应调整这些文字。

主要文件：

- `Fig3.png`、`Fig3.pdf`、`Fig3.tif`：Origin 导出。
- `Fig3_plot_data.xlsx`：完整分析表、绘图宽表和场次汇总；另有同名 CSV。
- `individual_means.csv`：每个个人的20轮均值，附人群、场次和条件标识。
- `summary.csv`：均值、个人层面 SD/SE/CI、个人数和场次数。
- `round_means.csv`：各场次每轮均值，用于检查时间变化，不自动判定收敛。
- `analysis_plan.json`：列映射、已确认选择、原始文件哈希和配置。
- `validation.json`：数据完整性检查。
- `origin_readback.json`：图层、坐标轴、颜色及保存后重新打开项目的数据核验。
- `source_manifest.json`：执行源码哈希和命令参数。

所有原始输入只读。人类工作簿中的人口信息表不参与计算、不导出。LLM 的修正标记只用于审核，修正过的决策仍保留，不作未经确认的排除。

## 方法来源

Origin 使用官方外部 Python 接口：[GLayer.add_plot](https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GLayer.html)、[图页与导出](https://docs.originlab.com/originpro/classoriginpro_1_1graph_1_1GPage.html)、[项目保存](https://docs.originlab.com/originpro/namespaceoriginpro_1_1project.html)、[图层属性](https://docs.originlab.com/labtalk/ref/layer-obj/)、[箱体属性](https://docs.originlab.com/labtalk/ref/layer-plotn-obj/)。

本轮仅生成项目、数据和源码，不改论文、图注或审稿回复。20轮是统一的比较窗口；更长期稳定性需更长期数据，不能由这一窗口自动推出。

本机原数据目录后改名为 `20261011_000304_540158_llm_01`，CSV 和配置文件哈希与原目录一致。当前启动脚本已更新路径，仍只分析第一批。

默认 LLM 路径基于仓库根目录计算，默认人类路径基于同一工作目录下的 `ubuntu_files/llm_paper_review` 计算。目录结构不同时请显式传入 `-LlmSessions` 和 `-HumanWorkbook`。`render` 模式只需准备好的输出目录，源文件哈希仍会由主脚本核验。每次执行均生成新目录，默认保留新建 Origin 窗口；`-CloseOrigin` 可在成功后关闭此次运行拥有的窗口。

## 验证与测试

```powershell
.\.venv\Scripts\python.exe -m src.analysis.fig3 --help
.\.venv\Scripts\python.exe -m unittest src.analysis.test_fig3_data_contract -v
.\.venv\Scripts\python.exe src/analysis/test_fig3_data_contract.py -v
```

测试覆盖完整场次、缺失轮次、重复观测及将同一文件误当作两个独立重复输入的保护。测试中的合成数据不会进入科学图形。

迁移验证记录见 `fig3_migration_validation.json`：模块入口和直接脚本测试均通过；已从仓库外完成启动依赖检查，并用项目 `.venv` 处理真实数据。统计结果与上一份已验证图形的数据一致，CI 的末位浮点差异低于 `3e-12`，由 SciPy 版本差异引起。迁移后的完整 Origin 绘图复测执行申请未获批准，因此此次没有重新启动 Origin 绘图；原绘图实现已在迁移前通过保存、导出及重新打开检查。

箱体范围显式设置为本机 Origin 2021 的现代枚举 `boxRange=3`（`OC_const.h` 中 `BCBT_25_75=2` 的1基接口），并在保存后再次读回。旧网页把 No Box 纳入 Range 枚举，与本机将 Box Style 分开的枚举不同，不能直接照旧网页编号推断统计含义。
