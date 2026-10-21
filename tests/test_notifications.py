import json,pathlib,sys,tempfile,time,unittest
from datetime import datetime
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'src'))
from notifications import NotificationStore,HourlyChime
from codex_hooks import install_hooks,remove_hooks,MARKER

class NotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=pathlib.Path(self.temp.name)
        self.store=NotificationStore(self.root/'notifications')
    def tearDown(self): self.temp.cleanup()
    def event(self,event,**extra):
        return {'hook_event_name':event,'session_id':'sample-thread','turn_id':'turn-1',**extra}
    def test_question_and_answer_clear(self):
        payload=self.event('PreToolUse',tool_name='request_user_input',tool_input={'questions':[{'question':'选择哪种布局？'}]})
        self.store.receive_hook(payload)
        self.assertEqual(self.store.current()['kind'],'question')
        self.assertEqual(self.store.current()['summary'],'选择哪种布局？')
        self.store.receive_hook({**payload,'hook_event_name':'PostToolUse'})
        self.assertIsNone(self.store.current())
    def test_async_question_stays_until_user_prompt(self):
        payload=self.event('PreToolUse',tool_name='functions.request_user_input_async',tool_input={'questions':[{'title':'使用哪个设置？'}]})
        self.store.receive_hook(payload); self.store.receive_hook({**payload,'hook_event_name':'PostToolUse'})
        self.assertEqual(self.store.current()['kind'],'question')
        self.store.receive_hook(self.event('UserPromptSubmit')); self.assertIsNone(self.store.current())
    def test_permission_clears_after_tool_and_never_persists_command(self):
        payload=self.event('PermissionRequest',tool_name='Bash',tool_input={'command':'secret-command-do-not-save','description':'需要访问指定文件'})
        self.store.receive_hook(payload)
        self.assertEqual(self.store.current()['kind'],'permission')
        for path in (self.root/'notifications').glob('*.json'):
            self.assertNotIn('secret-command-do-not-save',path.read_text(encoding='utf-8'))
        self.store.receive_hook(self.event('PostToolUse',tool_name='Bash',tool_input={'command':'secret-command-do-not-save'}))
        self.assertIsNone(self.store.current())
    def test_completion_clear_wait_and_expire(self):
        self.store.receive_hook(self.event('PermissionRequest',tool_name='Bash',tool_input={}))
        self.store.receive_hook(self.event('Stop'))
        self.assertEqual(self.store.current()['kind'],'completed')
        self.assertIsNone(self.store.current(time.time()+13))
    def test_independent_threads_priorities_and_interrupt(self):
        self.store.emit('completed',session='other')
        self.store.receive_hook(self.event('PermissionRequest',tool_name='Bash',tool_input={}))
        self.assertEqual(self.store.current()['kind'],'permission')
        self.store.receive_hook(self.event('Interrupt'))
        self.assertEqual(self.store.current()['kind'],'interrupted')
    def test_no_completion_for_stop_hook_continuation(self):
        self.store.receive_hook(self.event('Stop',stop_hook_active=True))
        self.assertIsNone(self.store.current())
    def test_new_round_clears_previous_completion(self):
        self.store.receive_hook(self.event('Stop'))
        self.assertEqual(self.store.current()['kind'],'completed')
        self.store.receive_hook(self.event('UserPromptSubmit'))
        self.assertIsNone(self.store.current())
    def test_hook_config_merges_preserves_existing_and_no_permission_decision(self):
        home=self.root/'codex'; home.mkdir()
        existing={'hooks':{'Stop':[{'hooks':[{'type':'command','command':'existing-command'}]}]}}
        (home/'hooks.json').write_text(json.dumps(existing),encoding='utf-8')
        for _ in range(2): install_hooks(home,self.root/'python.exe',self.root/'codex_hooks.py')
        result=json.loads((home/'hooks.json').read_text(encoding='utf-8'))
        self.assertEqual(result['hooks']['Stop'][0]['hooks'][0]['command'],'existing-command')
        owned=[handler for group in result['hooks']['Stop'] for handler in group['hooks'] if handler.get('statusMessage')==MARKER]
        self.assertEqual(len(owned),1)
        self.assertNotIn('permissionDecision',json.dumps(result))
        remove_hooks(home)
        remaining=json.loads((home/'hooks.json').read_text(encoding='utf-8'))
        self.assertEqual(remaining['hooks'],existing['hooks'])

class HourlyTests(unittest.TestCase):
    def stamp(self,hour,minute=0,second=0,day=20): return datetime(2026,10,day,hour,minute,second).timestamp()
    def test_no_startup_or_duplicate_chime(self):
        clock=HourlyChime()
        self.assertIsNone(clock.poll(self.stamp(10,59,59)))
        self.assertEqual(clock.poll(self.stamp(11))['title'],'现在是 11:00')
        self.assertIsNone(clock.poll(self.stamp(11,0,1)))
    def test_wake_mid_hour_and_disable_do_not_chime(self):
        clock=HourlyChime(); clock.poll(self.stamp(10))
        self.assertIsNone(clock.poll(self.stamp(12,15)))
        self.assertIsNone(clock.poll(self.stamp(13),enabled=False))
    def test_midnight(self):
        clock=HourlyChime(); clock.poll(self.stamp(23,59,59))
        self.assertEqual(clock.poll(self.stamp(0,day=21))['title'],'现在是 00:00')

if __name__=='__main__': unittest.main()
