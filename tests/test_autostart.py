import pathlib,sys,unittest,xml.etree.ElementTree as ET
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/"src"))
from launcher import task_xml,scheduled_autorun_enabled

class AutostartTests(unittest.TestCase):
    def test_schtasks_redirected_console_encoding(self):
        command=[r'C:\Apps\pythonw.exe',r'C:\Apps\launcher.py','--watch-host']
        output=task_xml(command,'S-test').decode('utf-16').encode('mbcs')
        # Windows redirects console bytes while keeping the UTF-16 declaration.
        with patch('launcher.quiet_run',return_value=SimpleNamespace(returncode=0,stdout=output)),patch('launcher.task_name',return_value='test'),patch('launcher.own_command',return_value=command):
            self.assertTrue(scheduled_autorun_enabled())

    def test_logon_task_is_per_user_non_elevated_and_restarts(self):
        root=ET.fromstring(task_xml([r'C:\My Apps\挂件\ShuanglingQuota.exe','--watch-host'],'S-1-5-21-test'))
        ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        def value(path): return root.findtext(path,namespaces=ns)
        self.assertEqual(value('.//t:LogonTrigger/t:UserId'),'S-1-5-21-test')
        self.assertEqual(value('.//t:Principal/t:RunLevel'),'LeastPrivilege')
        self.assertEqual(value('.//t:Principal/t:LogonType'),'InteractiveToken')
        self.assertEqual(value('.//t:RestartOnFailure/t:Count'),'3')
        self.assertEqual(value('.//t:Exec/t:Arguments'),'--watch-host')
        self.assertEqual(value('.//t:Exec/t:Command'),r'C:\My Apps\挂件\ShuanglingQuota.exe')
        self.assertEqual(value('.//t:Settings/t:ExecutionTimeLimit'),'PT0S')

if __name__=='__main__': unittest.main()
