import ast
from datetime import date, timedelta
from pathlib import Path
import unittest

import pandas as pd


class PerformanceWindowsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        source = Path(__file__).resolve().parents[1] / 'NHLGrader5-4.py'
        tree = ast.parse(source.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'pick_perf_window_df')
        namespace = {'pd': pd, 'timedelta': timedelta}
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), 'exec'), namespace)
        cls.window = staticmethod(namespace['pick_perf_window_df'])

    def test_exact_calendar_windows(self):
        today = date(2026, 11, 13)
        dates = pd.date_range('2026-07-01', '2026-11-14')
        frame = pd.DataFrame({'date_parsed': dates})
        for days in (7, 30, 90):
            with self.subTest(days=days):
                result = self.window(frame, f'last_{days}d', days, today)
                self.assertEqual(len(result), days)
                self.assertEqual(result.date_parsed.min().date(), today - timedelta(days=days - 1))
                self.assertEqual(result.date_parsed.max().date(), today)

    def test_november_reconciliation_boundary(self):
        frame = pd.DataFrame({'date_parsed': pd.to_datetime(
            ['2026-10-14', '2026-10-15', '2026-11-13', '2026-11-14', None])})
        result = self.window(frame, 'last_30d', 30, date(2026, 11, 13))
        self.assertEqual(result.index.tolist(), [1, 2])
        result = self.window(frame, 'all_time', None, date(2026, 11, 13))
        self.assertEqual(result.index.tolist(), [0, 1, 2])
