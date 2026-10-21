"""Display-only hook bridge. Never returns approval decisions or changes tools."""
from __future__ import annotations
import json,os,subprocess,sys,time
from pathlib import Path
from notifications import NotificationStore

MARKER='霜铃气泡提醒（仅通知）'
APP_DIR=Path(__file__).resolve().parent

def hook_definition(python=None,script=None):
    python=Path(python or sys.executable)
    if python.name.casefold()=='pythonw.exe': python=python.with_name('python.exe')
    command=subprocess.list2cmdline([str(python),str(script or Path(__file__).resolve()),'--receive'])
    handler={'type':'command','command':command,'timeout':2,'statusMessage':MARKER}
    hooks={event:[{'hooks':[dict(handler)]}] for event in ('PermissionRequest','PostToolUse','UserPromptSubmit','Stop','Interrupt','SessionEnd')}
    hooks['PreToolUse']=[{'matcher':r'(^|\.)request_user_input(_async)?$|^AskUserQuestion$','hooks':[dict(handler)]}]
    return {'description':'霜铃本地气泡提醒，不批准、拒绝、改写或阻止任何 Codex 操作。','hooks':hooks}

def install_hooks(home=None,python=None,script=None):
    home=Path(home or os.environ.get('CODEX_HOME') or Path.home()/'.codex')
    target=home/'hooks.json'; data={}
    if target.exists():
        data=json.loads(target.read_text(encoding='utf-8-sig'))
        if not isinstance(data,dict) or not isinstance(data.get('hooks',{}),dict): raise ValueError('现有 hooks.json 格式不支持自动合并，请先检查。')
        backup=target.with_name('hooks.json.shuangling-backup-'+str(time.time_ns()))
        backup.write_bytes(target.read_bytes())
    generated=hook_definition(python,script)
    combined=data.setdefault('hooks',{})
    for event,groups in generated['hooks'].items():
        retained=[]
        for group in combined.get(event,[]):
            handlers=[handler for handler in group.get('hooks',[]) if handler.get('statusMessage')!=MARKER]
            if handlers: retained.append({**group,'hooks':handlers})
        combined[event]=retained+groups
    if not data.get('description'): data['description']=generated['description']
    home.mkdir(parents=True,exist_ok=True)
    temporary=target.with_name('hooks.json.shuangling.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); temporary.replace(target)
    return target

def remove_hooks(home=None):
    home=Path(home or os.environ.get('CODEX_HOME') or Path.home()/'.codex')
    target=home/'hooks.json'
    if not target.exists(): return target
    data=json.loads(target.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or not isinstance(data.get('hooks',{}),dict): raise ValueError('现有 hooks.json 格式不支持自动修改。')
    combined=data.get('hooks',{})
    for event,groups in list(combined.items()):
        retained=[]
        for group in groups:
            handlers=[handler for handler in group.get('hooks',[]) if handler.get('statusMessage')!=MARKER]
            if handlers: retained.append({**group,'hooks':handlers})
        if retained: combined[event]=retained
        else: combined.pop(event,None)
    backup=target.with_name('hooks.json.shuangling-backup-'+str(time.time_ns()))
    backup.write_bytes(target.read_bytes())
    temporary=target.with_name('hooks.json.shuangling.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8'); temporary.replace(target)
    return target

def main():
    if '--install' in sys.argv:
        print(install_hooks()); return
    if '--uninstall' in sys.argv:
        print(remove_hooks()); return
    if '--receive' not in sys.argv: return
    try:
        raw=sys.stdin.buffer.read(262145)
        if len(raw)>262144: return
        payload=json.loads(raw.decode('utf-8-sig'))
        if isinstance(payload,dict) and payload.get('session_id') and payload.get('hook_event_name') in ('PreToolUse','PostToolUse','PermissionRequest','Stop','Interrupt','SessionEnd','UserPromptSubmit'):
            NotificationStore(APP_DIR/'state/notifications').receive_hook(payload)
            state=APP_DIR/'state'; state.mkdir(exist_ok=True)
            temporary=state/('hook-health-'+str(time.time_ns())+'.tmp')
            temporary.write_text(json.dumps({'last_event':payload.get('hook_event_name'),'received_at':time.time()}),encoding='utf-8')
            temporary.replace(state/'hook-health.json')
    except Exception:
        # An unavailable widget or bad notification must never block a Codex tool.
        return

if __name__=='__main__': main()
