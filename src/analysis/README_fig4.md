# Fig. 4：逐轮均值散点与个体标准差阴影

主脚本为 `fig4.py`；Windows 入口为 `run_fig4.ps1`。共用 `fig3.py` 的原始数据校验和 Origin 生命周期，以及 `human_data_cache.py` 的人类数据缓存。

三组实验的项目输出可复用已验证的 Fig. 3：prepare 时指定 `--reuse-fig3 "Fig3结果目录"`，保留一个 `--llm-session` 参数用于定位原始列名。实际三组 LLM 数据及来源均读取 Fig. 3 的哈希验证记录，而非仅使用该单个 CSV。人类仍复用完整 50 轮缓存。

`render --project-only` 仅保存 `Fig4.opju`，检查预览放系统临时目录，不生成交付用 PDF/EPS/TIF。新代码首次使用时，以 `--probe --project-only` 完成同一项目的能力验证，检查临时预览后记录视觉审核结果。该项目保持打开，供用户手动导出。阴影采用实色填充模式，避免 Origin 2021 的渐变暗色干扰；原有颜色及透明度不变。

两行两列：上排 LLM、下排人类；左列 Entrusted，右列 Returned。LLM 保留 20 轮，人类完整 50 轮。每个条件、每一轮，计算所有个体金额的均值和样本标准差（ddof=1）。人类三次实验按 (session, individual) 区分身份并合并，共 147 人；当前 LLM 每轮 49 名智能体。重复轮次不合并。阴影是均值 ±1 个体 SD，描述行为差异，不是均值置信区间或实验间不确定性。上下界不截断。

均值为无连线散点，阴影连接相邻轮次的上下界，仅作为显示方式。2026-10-16 确认的 LLM 配色按 p 从 0 到 1 依次为 `#0072B2`、`#E69F00`、`#009E73`、`#CC79A7`、`#D55E00`；阴影透明度 94%，散点为实色。人类保留原配色及 88% 阴影透明度。Fig. 3 原配色不变。所有 SD 数值和范围保持原始计算结果。每行的 p 值图例在右侧 Returned 面板内部，图中不标注 session 数量；数据表和来源记录仍保留实际数量。新的人类逐轮个体 SD 表持久化到 `human_experiment_datas` 的对应缓存中。

从项目根目录准备数据（将路径替换为所选批次的明确 CSV）：

```powershell
python -m src.analysis.fig4 prepare --llm-session "outputs/实验批次/agent_rounds.csv"
```

默认人类原始文件为 `human_experiment_datas/2024_NHB_model_Trust Game.xlsx`。`--human` 和 `--human-cache-dir` 可覆盖默认路径。准备后的目录含 CSV、XLSX、分析方案、来源哈希和源码快照。

Origin 绘图需实体 Windows、Origin 2021+ 及带 originpro 的外部 Python。先运行 EditaPlot doctor 和隔离 origin-smoke，再用当前源码进行完整绘图探测：

```powershell
& $OriginPython src/analysis/fig4.py render --output-dir "探测用准备目录" --probe
```

检查四个导出和 `origin_readback.json` 后，用 `verify_fig4_delivery.py` 审核并在实际看过 PNG 后显式传入 `--visual-reviewed`。以审核后的探测报告为 `--route-evidence`，在新的准备目录正式绘制：

```powershell
& $OriginPython src/analysis/fig4.py render --output-dir "正式准备目录" --route-evidence "探测目录/origin_readback.json"
```

正式运行保留专属 Origin 实例。渲染不会覆盖已有 OPJU，不会接管用户既有 Origin 项目。绘图实现或共享模块变动后必须重新探测。复现源码包中的 `run_this_fig4.ps1` 为本批数据的运行入口（先准备；有对应证据时可指定 render 或 all）。
