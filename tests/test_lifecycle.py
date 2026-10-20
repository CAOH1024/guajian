import pathlib,sys,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"src"))
from launcher import Lifecycle,desktop_host_path,is_host_window

class LifecycleTests(unittest.TestCase):
    def test_watcher_restart_closes_orphan_widget_without_host_window(self):
        lifecycle=Lifecycle(grace=5)
        self.assertIsNone(lifecycle.step(False,True,0))
        self.assertEqual(lifecycle.step(False,True,5),'stop')

    def test_background_and_tool_windows_do_not_count_as_open_host(self):
        self.assertTrue(is_host_window(True,0,0))
        self.assertTrue(is_host_window(True,0,0x40000))
        self.assertFalse(is_host_window(False,0,0))
        self.assertFalse(is_host_window(True,123,0))
        self.assertFalse(is_host_window(True,0,0x80))

    def test_close_to_background_stops_and_reopen_restarts(self):
        lifecycle=Lifecycle(grace=5,cooldown=1)
        self.assertEqual(lifecycle.step(is_host_window(True,0,0),False,0),'start')
        self.assertIsNone(lifecycle.step(is_host_window(False,0,0),True,1))
        self.assertEqual(lifecycle.step(is_host_window(False,0,0),True,6),'stop')
        self.assertEqual(lifecycle.step(is_host_window(True,0,0),False,7),'start')

    def test_start_stop_and_reopen(self):
        c=Lifecycle(grace=5)
        self.assertIsNone(c.step(False,False,0))
        self.assertEqual(c.step(True,False,1),'start')
        self.assertIsNone(c.step(True,True,2))
        self.assertIsNone(c.step(False,True,3))
        self.assertIsNone(c.step(False,True,7))
        self.assertEqual(c.step(False,True,8),'stop')
        self.assertIsNone(c.step(False,False,9))
        self.assertEqual(c.step(True,False,15),'start')
    def test_survives_host_restart_and_enumeration_failure(self):
        c=Lifecycle(); c.step(True,True,0); c.step(False,True,1)
        self.assertIsNone(c.step(None,True,100))
        self.assertIsNone(c.step(True,True,101))
    def test_cooldown_prevents_spawn_storm(self):
        c=Lifecycle(); self.assertEqual(c.step(True,False,0),'start')
        self.assertIsNone(c.step(True,False,1))
        self.assertEqual(c.step(True,False,10),'start')
    def test_exclude_our_own_codex_backend(self):
        self.assertTrue(desktop_host_path('ChatGPT.exe'))
        self.assertTrue(desktop_host_path('Codex.exe',r'C:\Program Files\WindowsApps\OpenAI.Codex_1\app\Codex.exe'))
        for path in (r'C:\npm\node_modules\@openai\codex\vendor\codex.exe',r'C:\Apps\Codex\resources\codex.exe',''):
            self.assertFalse(desktop_host_path('codex.exe',path))

if __name__=='__main__': unittest.main(verbosity=2)
