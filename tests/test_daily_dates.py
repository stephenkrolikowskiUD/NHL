import ast
from datetime import datetime, date
from pathlib import Path
from zoneinfo import ZoneInfo
import unittest

source = (Path(__file__).parents[1] / 'NHLEngine5-4.py').read_text()
tree = ast.parse(source)
namespace = {'datetime': datetime, 'date': date, 'EASTERN': ZoneInfo('America/New_York')}
for node in tree.body:
    if isinstance(node, ast.FunctionDef) and node.name in {'event_eastern_date', 'get_nhl_season_id'}:
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<engine helpers>', 'exec'), namespace)

class DailyDates(unittest.TestCase):
    def test_late_game_stays_on_eastern_slate(self):
        self.assertEqual(namespace['event_eastern_date']('2026-10-08T02:00:00Z'), '2026-10-07')
    def test_winter_offset(self):
        self.assertEqual(namespace['event_eastern_date']('2027-01-02T04:30:00Z'), '2027-01-01')
    def test_bad_or_naive_timestamps(self):
        for value in [None, '', 'garbage', '2026-10-07T20:00:00']:
            self.assertEqual(namespace['event_eastern_date'](value), '')
    def test_season_rollover(self):
        self.assertEqual(namespace['get_nhl_season_id'](datetime(2026,10,7)), '20262027')
        self.assertEqual(namespace['get_nhl_season_id'](datetime(2027,1,7)), '20262027')
    def test_unverified_schedule_is_not_empty_slate(self):
        block=next(n for n in tree.body if isinstance(n,ast.If) and any(isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='schedule_confirmed' for t in x.targets) for x in n.body))
        calls=[]
        class Stop:
            def exit(self,code):raise SystemExit(code)
        env={**namespace,'games':[],'schedule_data':None,'sched2':None,'TODAY':'2026-10-07','safe_upload':lambda *x:calls.append(x),'sys':Stop()}
        script=compile(ast.Module(body=[block],type_ignores=[]),'<schedule guard>','exec')
        with self.assertRaises(RuntimeError):exec(script,env)
        self.assertFalse(calls)
        env['schedule_data']={'gameWeek':[{'date':'2026-10-07','games':[]}]}
        with self.assertRaises(SystemExit):exec(script,env)
        self.assertEqual(calls[0][0],'Slate_Status')
        self.assertEqual(calls[0][1][0]['GAME_COUNT'],0)

if __name__=='__main__': unittest.main()
