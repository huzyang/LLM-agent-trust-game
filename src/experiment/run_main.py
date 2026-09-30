"""
主运行脚本
"""
import json
import os
import sys
import logging
import tqdm
import pandas as pd
from datetime import datetime
from src.experiment.params import Params
from src.experiment.model import GameModel, GameScenario
from src.experiment.analysy import TrustGameAnalyzer
from src.utils import CommonUtils

# 添加当前目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

logger = logging.getLogger('experiment')
logger.setLevel(logging.INFO)


def setup_logging(params: Params, timestamp: str):
    """设置日志输出到文件和控制台"""
    output_dir = os.path.join(CommonUtils.get_project_root_path(), "outputs")
    log_file = os.path.join(output_dir, f"{timestamp}_run.log")

    if logger.handlers:
        logger.handlers.clear()

    file_handler = logging.FileHandler(log_file, mode="a", encoding='utf-8')
    file_handler.setLevel(logging.INFO)
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%H:%M:%S')
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.propagate = False


def format_run_time(seconds):
    """
    自动将秒数转换为最合适的单位（时、分、秒）

    参数:
    - seconds: 运行时间（秒）

    返回:
    - 格式化的时间字符串
    """
    if seconds >= 3600:  # 大于等于1小时
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}小时{minutes}分{secs:.2f}秒"
    elif seconds >= 60:  # 大于等于1分钟
        minutes = int(seconds // 60)
        secs = seconds % 60
        return f"{minutes}分{secs:.2f}秒"
    else:  # 小于1分钟
        return f"{seconds:.2f}秒"


def analyze_experiment_results(output_dir: str):
    """
    分析实验结果并生成报告和图表
    """

    # 查找所有CSV文件
    pattern = os.path.join(output_dir, "*.csv")
    import glob
    csv_files = glob.glob(pattern)

    if not csv_files:
        logger.warning(f"未找到CSV文件，跳过分析: {output_dir}")
        return

    logger.info(f"\n{'=' * 60}")
    logger.info(f"📊 开始分析实验结果...")
    logger.info(f"{'=' * 60}")
    logger.info(f"找到 {len(csv_files)} 个CSV文件")

    try:
        # 创建分析器
        analyzer = TrustGameAnalyzer(csv_files)

        # 创建输出目录
        figures_dir = os.path.join(output_dir, "figures")
        report_path = os.path.join(output_dir, "analysis_report.txt")

        # 生成分析报告
        analyzer.generate_report(report_path)
        logger.info(f"✅ 分析报告已保存: {report_path}")

        # 生成图表
        analyzer.plot_figures(figures_dir)
        logger.info(f"✅ 图表已保存: {figures_dir}")

        logger.info(f"✅ 实验分析完成！\n")

    except Exception as e:
        logger.error(f"❌ 实验分析失败: {str(e)}", exc_info=True)


def multi_round_exp(params: Params, timestamp: str):
    """
    执行多轮实验的主函数，针对给定的模型列表进行多轮测试
    参数:
        model_list: 要测试的模型或模型列表
        exp_time: 每个模型要重复实验的次数
        round_num_inform: 是否在输出中显示轮次信息
    """

    model_type_list = params.model_type_list
    iterations = params.iterations
    proportions = params.proportions
    total_iterations = len(model_type_list) * len(proportions) * iterations

    logger.info(f"\n{'#' * 80}")
    logger.info(f"# {'实验配置概览':^76} #")
    logger.info(f"{'#' * 80}")
    logger.info(f"  • 模型列表: {[m.value if hasattr(m, 'value') else str(m) for m in model_type_list]}")
    logger.info(f"  • 博弈类型: {params.game_type}")
    logger.info(f"  • 智能体数量: {params.num_agents}")
    logger.info(f"  • 网格大小: {params.width} x {params.height}")
    logger.info(f"  • 自由玩家比例: {proportions}")
    logger.info(f"  • 每模型迭代次数: {iterations}")
    logger.info(f"  • 每实验轮次: {params.rounds}")
    logger.info(f"  • 总实验次数: {total_iterations}")
    logger.info(f"{'#' * 80}\n")

    run_id = 1
    with tqdm.tqdm(total=total_iterations, desc="Overall Progress") as pbar:
        for model_type in model_type_list:
            model_name = model_type.value if hasattr(model_type, 'value') else str(model_type)
            logger.info(f"\n{'=' * 80}")
            logger.info(f"🔬 开始测试模型: {model_name}")
            logger.info(f"{'=' * 80}")

            # 创建输出目录
            output_dir = os.path.join(CommonUtils.get_project_root_path(), "outputs", f"{timestamp}_{model_type}_{params.game_type}")
            os.makedirs(output_dir, exist_ok=True)

            all_results = []
            all_pair_game_results = []
            for proportion in proportions:
                logger.info(f"\n📌 自由玩家比例: {proportion:.0%}")
                logger.info(f"  ├─ 迭代次数: {iterations}")
                logger.info(f"  └─ 每迭代轮次: {params.rounds}")

                for iteration in range(1, iterations + 1):
                    logger.info(f"\n  ▶️  迭代 {iteration}/{iterations} (Run ID: {run_id})")

                    # 根据参数值构造GameScenario
                    scenario = GameScenario(
                        num_agents=params.num_agents,
                        width=params.width,
                        height=params.height,
                        model_type=model_type,
                        game_type=params.game_type,
                        proportion=proportion,
                        run_id=run_id,
                        iteration=iteration
                    )
                    # 传入GameModel
                    game_model = GameModel(scenario=scenario)
                    results, pair_game_result, all_dialogue = game_model.run_model(params.rounds)

                    # 将每次运行的结果列表扩展到总结果中
                    all_results.extend(results)
                    all_pair_game_results.extend(pair_game_result)
                    dialogue_file_name = f"{timestamp}_run_id-{run_id}_QA-record_p-{proportion}_iter-{iteration}.json"
                    dialogue_file_path = os.path.join(output_dir, dialogue_file_name)
                    try:
                        with open(dialogue_file_path, 'w', encoding='utf-8') as f:
                            json.dump(all_dialogue, f, ensure_ascii=False, indent=2)
                        logger.info(f"  ✅ 对话记录已保存: {dialogue_file_name}")
                    except Exception as e:
                        logger.error(f"  ❌ 保存对话记录失败: {dialogue_file_name}, 错误: {str(e)}")

                    pbar.update(1)
                    pbar.set_postfix({
                        'model': model_name[:15],
                        'prop': f"{proportion:.0%}",
                        'run': run_id,
                        'iter': iteration
                    })
                    run_id += 1

            filename_1 = f"{timestamp}_{params.game_type}_p-{proportions}.csv"
            filepath_1 = os.path.join(output_dir, filename_1)
            df1 = pd.DataFrame(all_results)
            df1.to_csv(filepath_1, index=False, encoding='utf-8')

            filename_2 = f"{timestamp}_{params.game_type}_pair_data.xlsx"
            filepath_2 = os.path.join(output_dir, filename_2)
            df2 = pd.DataFrame(all_pair_game_results)
            df2.to_excel(filepath_2, index=False, sheet_name='sent_returned_amount', engine='openpyxl')

            logger.info(f"\n{'=' * 80}")
            logger.info(f"📊 模型 {model_name} 实验汇总")
            logger.info(f"{'=' * 80}")
            logger.info(f"  • 总数据行数: {len(all_results)}")
            logger.info(f"  • CSV文件: {filename_1}")
            logger.info(f"  • Excel文件: {filename_2}")
            logger.info(f"  • 保存路径: {output_dir}")
            logger.info(f"{'=' * 80}\n")


            # 对当前模型的实验结果进行分析
            # analyze_experiment_results(output_dir)


def main():
    import time
    start_time = time.time()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    params = Params()
    setup_logging(params, timestamp)

    multi_round_exp(params=params, timestamp=timestamp)

    run_time = format_run_time(time.time() - start_time)
    logger.info(f"✅ 实验所有步骤运行完成，总共耗时: {run_time}")


if __name__ == "__main__":
    main()