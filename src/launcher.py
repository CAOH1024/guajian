"""Portable launcher and per-user host-lifecycle watcher. No app patching."""
from __future__ import annotations
import ctypes, csv, json, os, subprocess, sys, time, traceback, tempfile
import xml.etree.ElementTree as ET
from functools import lru_cache
from ctypes import wintypes
from pathlib import Path

WIDGET_PIPE='ShuanglingQuotaWidget_v1'
WATCHER_PIPE='ShuanglingQuotaWatcher_v1'
AUTORUN_NAME='ShuanglingQuotaWatcher'

def log_event(message):
    root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
    try:
        directory=root/'state'; directory.mkdir(exist_ok=True)
        path=directory/'watcher.log'
        if path.exists() and path.stat().st_size>256000:
            path.replace(directory/'watcher.previous.log')
        with path.open('a',encoding='utf-8') as stream:
            stream.write(time.strftime('%Y-%m-%d %H:%M:%S ')+message+'\n')
    except OSError:
        pass

def quiet_run(command):
    return subprocess.run(command,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),timeout=15)

@lru_cache(maxsize=1)
def user_sid():
    result=quiet_run(['whoami.exe','/user','/fo','csv','/nh'])
    if result.returncode:
        raise OSError('Cannot identify current user')
    return next(csv.reader(result.stdout.decode('utf-8',errors='replace').strip().splitlines()))[1]

def task_name():
    return AUTORUN_NAME+'-'+user_sid()

def task_xml(command,sid):
    ns='http://schemas.microsoft.com/windows/2004/02/mit/task'
    ET.register_namespace('',ns)
    root=ET.Element('{'+ns+'}Task',version='1.2')
    def add(parent,name,text=None,**attributes):
        child=ET.SubElement(parent,'{'+ns+'}'+name,attributes); child.text=text; return child
    trigger=add(add(root,'Triggers'),'LogonTrigger')
    add(trigger,'Enabled','true'); add(trigger,'UserId',sid); add(trigger,'Delay','PT5S')
    principal=add(add(root,'Principals'),'Principal',id='Author')
    add(principal,'UserId',sid); add(principal,'LogonType','InteractiveToken'); add(principal,'RunLevel','LeastPrivilege')
    settings=add(root,'Settings')
    for name,value in (('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
                       ('StopIfGoingOnBatteries','false'),('StartWhenAvailable','true'),('AllowStartOnDemand','true'),
                       ('Enabled','true'),('Hidden','true'),('ExecutionTimeLimit','PT0S')):
        add(settings,name,value)
    restart=add(settings,'RestartOnFailure'); add(restart,'Interval','PT1M'); add(restart,'Count','3')
    action=add(add(root,'Actions',Context='Author'),'Exec')
    add(action,'Command',command[0]); add(action,'Arguments',subprocess.list2cmdline(command[1:]))
    add(action,'WorkingDirectory',str(Path(command[0]).parent))
    return ET.tostring(root,encoding='utf-16',xml_declaration=True)

def scheduled_autorun_enabled():
    try:
        result=quiet_run(['schtasks.exe','/Query','/TN',task_name(),'/XML'])
        if result.returncode: return False
        # schtasks declares UTF-16 but writes the console code page when redirected.
        raw=result.stdout
        xml=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('mbcs')
        root=ET.fromstring(xml)
        ns={'t':'http://schemas.microsoft.com/windows/2004/02/mit/task'}
        command=own_command('--watch-host')
        return (root.findtext('.//t:Exec/t:Command',namespaces=ns)==command[0]
                and root.findtext('.//t:Exec/t:Arguments',namespaces=ns)==subprocess.list2cmdline(command[1:])
                and root.findtext('./t:Settings/t:Enabled',namespaces=ns)!='false')
    except (OSError,ValueError,ET.ParseError,subprocess.TimeoutExpired):
        return False

def own_command(*arguments):
    if getattr(sys,'frozen',False):
        return [sys.executable,*arguments]
    return [sys.executable,str(Path(__file__).resolve()),*arguments]

def desktop_host_path(name,path=''):
    name=name.casefold()
    if name=='chatgpt.exe':
        return True
    if name!='codex.exe':
        return False
    p=path.replace('/','\\').casefold()
    if any(part in p for part in ('\\vendor\\','\\node_modules\\','\\resources\\')):
        return False  # Codex app-server / CLI must never keep its own widget alive.
    return ('\\windowsapps\\openai.codex_' in p or p.endswith('\\programs\\codex\\codex.exe')
            or p.endswith('\\codex\\app\\codex.exe'))

def host_process_ids():
    """Read process metadata only. None means enumeration failed, not host exit."""
    class Entry(ctypes.Structure):
        _fields_=[('dwSize',wintypes.DWORD),('cntUsage',wintypes.DWORD),('th32ProcessID',wintypes.DWORD),
                  ('th32DefaultHeapID',ctypes.c_size_t),('th32ModuleID',wintypes.DWORD),('cntThreads',wintypes.DWORD),
                  ('th32ParentProcessID',wintypes.DWORD),('pcPriClassBase',wintypes.LONG),('dwFlags',wintypes.DWORD),
                  ('szExeFile',wintypes.WCHAR*260)]
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateToolhelp32Snapshot.argtypes=[wintypes.DWORD,wintypes.DWORD]; kernel.CreateToolhelp32Snapshot.restype=wintypes.HANDLE
    kernel.Process32FirstW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]; kernel.Process32FirstW.restype=wintypes.BOOL
    kernel.Process32NextW.argtypes=[wintypes.HANDLE,ctypes.POINTER(Entry)]; kernel.Process32NextW.restype=wintypes.BOOL
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]; kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=kernel.CreateToolhelp32Snapshot(2,0)
    if handle in (None,ctypes.c_void_p(-1).value):
        return None
    results=[]
    try:
        entry=Entry(); entry.dwSize=ctypes.sizeof(entry)
        if not kernel.Process32FirstW(handle,ctypes.byref(entry)):
            return None
        while True:
            name=entry.szExeFile.casefold()
            if name in ('chatgpt.exe','codex.exe'):
                path=''
                if name=='codex.exe':
                    process=kernel.OpenProcess(0x1000,False,entry.th32ProcessID)
                    if process:
                        try:
                            buffer=ctypes.create_unicode_buffer(32768); size=wintypes.DWORD(len(buffer))
                            if kernel.QueryFullProcessImageNameW(process,0,buffer,ctypes.byref(size)):
                                path=buffer.value
                        finally:
                            kernel.CloseHandle(process)
                if desktop_host_path(name,path):
                    results.append(int(entry.th32ProcessID))
            if not kernel.Process32NextW(handle,ctypes.byref(entry)):
                break
    finally:
        kernel.CloseHandle(handle)
    return results

def is_host_window(visible,owner,extended_style):
    """A minimized main window still counts; background/tool windows do not."""
    return bool(visible) and not owner and not (extended_style & 0x80)  # WS_EX_TOOLWINDOW

def host_window_process_ids(candidates=None):
    """Read top-level window metadata; closing to tray counts as closing the host.

    Enumerating the current desktop also avoids following another login session's
    host processes. None means detection failed, not that the last window closed.
    """
    candidates=host_process_ids() if candidates is None else candidates
    if candidates is None: return None
    if not candidates: return []
    candidates=set(candidates); found=set()
    user=ctypes.WinDLL('user32',use_last_error=True)
    callback_type=ctypes.WINFUNCTYPE(wintypes.BOOL,wintypes.HWND,wintypes.LPARAM)
    user.EnumWindows.argtypes=[callback_type,wintypes.LPARAM]; user.EnumWindows.restype=wintypes.BOOL
    user.GetWindowThreadProcessId.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes=[wintypes.HWND]; user.IsWindowVisible.restype=wintypes.BOOL
    user.GetWindow.argtypes=[wintypes.HWND,wintypes.UINT]; user.GetWindow.restype=wintypes.HWND
    get_style=user.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p)==8 else user.GetWindowLongW
    get_style.argtypes=[wintypes.HWND,ctypes.c_int]; get_style.restype=ctypes.c_ssize_t
    def visit(hwnd,_):
        pid=wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd,ctypes.byref(pid))
        if pid.value in candidates and is_host_window(user.IsWindowVisible(hwnd),user.GetWindow(hwnd,4),get_style(hwnd,-20)):
            found.add(pid.value)
        return True
    callback=callback_type(visit)
    if not user.EnumWindows(callback,0): return None
    return sorted(found)

class Lifecycle:
    def __init__(self,grace=5,cooldown=10):
        self.grace=grace; self.cooldown=cooldown
        self.was_active=False; self.absent_since=None; self.last_launch=-float('inf')
    def step(self,host_present,widget_running,now):
        if host_present is None:
            return None
        if host_present:
            self.was_active=True; self.absent_since=None
            if not widget_running and now-self.last_launch>=self.cooldown:
                self.last_launch=now
                return 'start'
        elif self.was_active or widget_running:
            if self.absent_since is None:
                self.absent_since=now
            if now-self.absent_since>=self.grace:
                self.was_active=False; self.absent_since=None
                return 'stop'
        return None

def ipc(server,message=b'ping',timeout=150):
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalSocket
    global _ipc_app
    if QCoreApplication.instance() is None:
        _ipc_app=QCoreApplication([])
    socket=QLocalSocket(); socket.connectToServer(server)
    if not socket.waitForConnected(timeout):
        return False
    socket.write(message); socket.waitForBytesWritten(timeout)
    socket.disconnectFromServer()
    return True

def autorun_enabled():
    if scheduled_autorun_enabled(): return True
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
            value,_=winreg.QueryValueEx(key,AUTORUN_NAME)
        return value==subprocess.list2cmdline(own_command('--watch-host'))
    except OSError:
        return False

def install_autostart():
    import winreg
    # Hand off an existing watcher before updating a moved portable app path.
    if ipc(WATCHER_PIPE,b'stop-only'):
        deadline=time.monotonic()+3
        while time.monotonic()<deadline and ipc(WATCHER_PIPE):
            time.sleep(0.05)
    installed=False
    try:
        with tempfile.TemporaryDirectory(prefix='shuangling-task-') as directory:
            path=Path(directory)/'startup.xml'; path.write_bytes(task_xml(own_command('--watch-host'),user_sid()))
            result=quiet_run(['schtasks.exe','/Create','/TN',task_name(),'/XML',str(path),'/F'])
        installed=result.returncode==0 and scheduled_autorun_enabled()
        log_event('Scheduled logon task '+('registered' if installed else 'unavailable; using Run fallback'))
    except (OSError,ValueError,subprocess.TimeoutExpired) as exc:
        log_event('Scheduled logon task unavailable: '+type(exc).__name__)
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if installed:
            try: winreg.DeleteValue(key,AUTORUN_NAME)
            except FileNotFoundError: pass
        else:
            winreg.SetValueEx(key,AUTORUN_NAME,0,winreg.REG_SZ,subprocess.list2cmdline(own_command('--watch-host')))
    subprocess.Popen(own_command('--watch-host'),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))

def remove_autostart():
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run',0,winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key,AUTORUN_NAME)
    except FileNotFoundError:
        pass
    try: quiet_run(['schtasks.exe','/Delete','/TN',task_name(),'/F'])
    except (OSError,ValueError,subprocess.TimeoutExpired): pass
    ipc(WATCHER_PIPE,b'quit')

def watch_hosts():
    from PySide6.QtCore import QCoreApplication,QTimer
    from PySide6.QtNetwork import QLocalServer
    app=QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    if ipc(WATCHER_PIPE):
        return
    QLocalServer.removeServer(WATCHER_PIPE)
    server=QLocalServer()
    if not server.listen(WATCHER_PIPE):
        raise RuntimeError('Cannot create watcher IPC: '+server.errorString())
    log_event('Window-aware watcher started pid='+str(os.getpid()))
    lifecycle=Lifecycle()
    paused=False
    last_hosts=None
    def on_command():
        nonlocal paused
        connection=server.nextPendingConnection()
        if not connection: return
        connection.waitForReadyRead(150)
        command=bytes(connection.readAll())
        connection.close()
        if command==b'quit':
            log_event('Watcher and widget stopped by command')
            ipc(WIDGET_PIPE,b'quit'); app.quit()
        elif command==b'stop-only':
            log_event('Watcher handed off')
            app.quit()
        elif command==b'pause':
            paused=True
    server.newConnection.connect(on_command)
    def poll_once():
        nonlocal paused,last_hosts
        hosts=host_window_process_ids()
        if hosts is not None and tuple(hosts)!=last_hosts:
            last_hosts=tuple(hosts)
            log_event('Host main-window process IDs: '+json.dumps(hosts))
        if hosts == []:
            paused=False
        action=lifecycle.step(None if hosts is None else bool(hosts),ipc(WIDGET_PIPE),time.monotonic())
        if action=='start' and not paused:
            process=subprocess.Popen(own_command(),creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            log_event('Host window open; widget started pid='+str(process.pid))
        elif action=='stop':
            ipc(WIDGET_PIPE,b'quit')
            log_event('Last host window closed; widget stopped')
    def poll():
        try: poll_once()
        except Exception as exc: log_event('Poll failed; retrying: '+type(exc).__name__)
    timer=QTimer(); timer.timeout.connect(poll); timer.start(1500)
    poll(); app.exec()

def main():
    if '--watch-host' in sys.argv:
        watch_hosts(); return
    if '--install-autostart' in sys.argv:
        install_autostart(); return
    if '--uninstall-autostart' in sys.argv:
        remove_autostart(); return
    if '--stop-watcher' in sys.argv:
        ipc(WATCHER_PIPE,b'quit'); return
    if '--host-status' in sys.argv:
        print(json.dumps({'host_pids':host_process_ids(),'host_window_pids':host_window_process_ids(),'autostart':autorun_enabled()})); return
    from widget import main as run_widget
    run_widget()

if __name__=='__main__':
    try:
        main()
    except Exception:
        root=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
        try:
            (root/'state').mkdir(exist_ok=True)
            (root/'state/startup-error.log').write_text(traceback.format_exc(),encoding='utf-8')
        except OSError:
            pass
        raise
