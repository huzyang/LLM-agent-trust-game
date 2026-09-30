# -*- coding: utf-8 -*-
import os
import unittest

from src.utils import CommonUtils


class ExpTest(unittest.TestCase):
    """Networks test cases."""

    def test_1(self):
        """Test 1."""
        import pandas as pd

        # 文件路径（请根据实际情况修改）
        # 默认 CSV 文件路径
        csv_dir = os.path.join(
            CommonUtils.get_project_root_path(),
            "datas"
        )
        # 读取数据（请确保文件路径正确）
        file_name = "trustgame.xlsx"
        input_file = os.path.join(csv_dir, file_name)
        output_file = os.path.join(csv_dir, 'trustgame_avg.xlsx')

        # 需要计算平均值的列（不包含 run、id、round 等分组列）
        AVG_COLUMNS = [
            'player.send_T',
            'player.return_T',
            'player.receive_send_T',
            'player.receive_return_T',
            'player.accumulate_payoff',
            'player.payoff'
        ]

        # ========== 处理 ==========
        # 读取所有工作表
        xls = pd.ExcelFile(input_file)
        sheet_names = xls.sheet_names  # 预期为 ['p=0', 'p=0.25', 'p=0.5', 'p=0.75', 'p=1']

        # 存储每个工作表的处理结果
        results = {}

        for sheet in sheet_names:
            # 读取当前工作表
            df = pd.read_excel(xls, sheet_name=sheet)

            # 按 player.id_in_group 和 subsession.round_number 分组
            # 对 AVG_COLUMNS 中的每一列计算平均值（跨 run）
            grouped = df.groupby(
                ['player.id_in_group', 'subsession.round_number'],
                as_index=False
            )[AVG_COLUMNS].mean()

            # 结果数据框
            results[sheet] = grouped

        # ========== 保存 ==========
        with pd.ExcelWriter(output_file, engine='openpyxl') as writer:
            for sheet_name, df_avg in results.items():
                df_avg.to_excel(writer, sheet_name=sheet_name, index=False)

        print(f"处理完成！结果已保存至：{output_file}")
        print(f"共处理 {len(results)} 个工作表：{', '.join(results.keys())}")

    def test_2(self):
        """Test 2."""
        import pandas as pd
        # 默认 CSV 文件路径
        csv_dir = os.path.join(
            CommonUtils.get_project_root_path(),
            "datas"
        )
        # 读取数据（请确保文件路径正确）
        file_name = "trustgame_avg.xlsx"
        input_file = os.path.join(csv_dir, file_name)
        output_file = os.path.join(csv_dir, 'trustgame_avg.xlsx')

        sheet_name = "osf"
        df = pd.read_excel(input_file, sheet_name=sheet_name)

        # 需要计算平均值的列
        target_cols = [
            "player.send_T",
            "player.return_T",
            "player.receive_send_T",
            "player.receive_return_T",
            "player.accumulate_payoff",
            "player.payoff"
        ]

        # 按 p 和 subsession.round_number 分组，计算均值
        grouped = df.groupby(["p", "subsession.round_number"], as_index=False)[target_cols].mean()

        # 调整列顺序（p, round_number, 其他列）
        cols_order = ["p", "subsession.round_number"] + target_cols
        grouped = grouped[cols_order]

        # 保存到新的 Excel 文件
        grouped.to_excel(output_file, index=False)

        print(f"处理完成，结果已保存至：{output_file}")
if __name__ == "__main__":
    unittest.main()
