import ast
from datetime import datetime, timedelta
import math
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]))
from nhl_research import *

class SeasonTests(unittest.TestCase):
    def test_scope_and_type(self):
        rows=[{'game_date':'2026-10-01','gameId':2026020001,'PTS':2,'TOI':'20:30'},
              {'game_date':'2026-04-01','gameId':2025021100,'PTS':9,'TOI':'15:00'},
              {'game_date':'2026-05-01','gameId':2025030101,'PTS':20},
              {'game_date':'2026-10-02','PTS':99}]
        result=season_summary(rows,'20262027',['PTS'])
        self.assertEqual(result['Seas_PTS'],2)
        self.assertEqual(result['Prior_PTS'],9)
        self.assertEqual(result['CURRENT_SEASON_GP'],1)
        self.assertEqual(result['L5_TOI_MIN'],20.5)
        self.assertEqual(game_type(rows[-1]),None)
        self.assertEqual(annotate_log(rows[1])['SEASON_ID'],'20252026')
    def test_new_player(self):
        result=season_summary([],'20262027',['PTS'])
        self.assertEqual(result['CURRENT_SEASON_GP'],0)
        self.assertTrue(result['LIMITED_SAMPLE'])
    def test_toi(self):
        self.assertEqual(toi_minutes('19:30'),19.5)
        self.assertIsNone(toi_minutes('20:80'))
        self.assertIsNone(toi_minutes(''))

class PriceTests(unittest.TestCase):
    def test_exact_line_and_book(self):
        pick={'player':'Test Player','prop_type':'PTS','line':0.5,'lean':'OVER'}
        props=[{'PLAYER_NAME':'Test Player','METRIC':'PTS','DK_LINE':1.5,'BEST_OVER_BOOK':'wrong','BEST_OVER_ODDS':400},
               {'PLAYER_NAME':'Test Player','METRIC':'PTS','DK_LINE':0.5,'BEST_OVER_BOOK':'book','BEST_OVER_ODDS':130}]
        captured=capture_pick_price(pick,props,'2026-10-07T10:00:00-04:00')
        self.assertEqual(captured['PICK_ODDS'],130)
        self.assertEqual(captured['PICK_BOOK'],'book')
        self.assertEqual(capture_pick_price(pick,props[:1],'now'),{'PRICE_STATUS':'UNPRICED'})
    def test_settlement(self):
        self.assertEqual(settled_units('YES',150,'book'),1.5)
        self.assertEqual(settled_units('YES',-200,'book'),.5)
        self.assertEqual(settled_units('NO',150,'book'),-1)
        self.assertEqual(settled_units('PUSH',-110,'book'),0)
        for result,odds,book in [('DNP',100,'book'),('YES',None,'book'),('YES',-110,''),('YES',0,'book'),('YES',float('nan'),'book'),('YES',150,float('nan'))]:
            self.assertIsNone(settled_units(result,odds,book))
    def test_grader_metrics(self):
        import pandas as pd
        import numpy as np
        path=Path(__file__).parents[1]/'NHLGrader5-4.py'
        tree=ast.parse(path.read_text())
        env={'pd':pd,'np':np,'math':math,'settled_units':settled_units,'PICK_PERF_STANDARD_ODDS':-115,'PICK_PERF_MIN_SAMPLE':25,'PICK_PERF_WILSON_Z':1.96,'timestamp_est':'test'}
        for name in ['wilson_lower_bound','pick_perf_rate','pick_perf_metrics_row']:
            node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
            exec(compile(ast.Module(body=[node],type_ignores=[]),'<grader>','exec'),env)
        rows=[{'HIT':'YES','PICK_ODDS':150,'PICK_BOOK':'one'}, {'HIT':'NO','PICK_ODDS':-200,'PICK_BOOK':'two'}, {'HIT':'PUSH','PICK_ODDS':-110,'PICK_BOOK':'one'}, {'HIT':'YES'}, {'HIT':'DNP','PICK_ODDS':100,'PICK_BOOK':'one'}]
        df=pd.DataFrame(rows);df['clv_edge']=np.nan
        result=env['pick_perf_metrics_row'](df,'overall','','all_time')
        self.assertEqual(result['N_PRICED'],3)
        self.assertEqual(result['N_UNPRICED'],1)
        self.assertEqual(result['N_PICKS_DECISIVE'],3)
        self.assertEqual(result['ACTUAL_PROFIT_UNITS'],.5)
        self.assertAlmostEqual(result['ACTUAL_ROI_PCT'],16.667,3)
        self.assertAlmostEqual(result['HIT_RATE'],.667,3)

if __name__=='__main__':unittest.main()
