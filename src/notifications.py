"""Local-only, display-only Codex hook notifications and hourly clock."""
from __future__ import annotations
import hashlib,json,time,uuid
from datetime import datetime
from pathlib import Path

PRIORITY={'question':100,'permission':90,'interrupted':70,'completed':50,'hourly':10}
TITLES={'question':'等你回答','permission':'权限确认中','interrupted':'本轮已中断','completed':'本轮已完成','hourly':'整点报时'}

def short_text(value,limit=76):
    if not isinstance(value,str): return ''
    value=' '.join(value.split())
    return value if len(value)<=limit else value[:limit-1]+'…'

def question_tool(name):
    return name.rsplit('.',1)[-1] in ('request_user_input','request_user_input_async','AskUserQuestion')

class NotificationStore:
    def __init__(self,directory): self.directory=Path(directory)
    def _write(self,key,data):
        self.directory.mkdir(parents=True,exist_ok=True)
        target=self.directory/(key+'.json'); temporary=target.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8'); temporary.replace(target)
    def entries(self,now=None):
        now=time.time() if now is None else now
        result=[]
        if not self.directory.exists(): return result
        for path in self.directory.glob('*.json'):
            try:
                data=json.loads(path.read_text(encoding='utf-8'))
                if data.get('kind') not in PRIORITY: continue
                if data.get('expires_at',0)<=now:
                    path.unlink(missing_ok=True); continue
                result.append((path,data))
            except (OSError,ValueError,TypeError): continue
        return result
    def current(self,now=None):
        values=[data for _,data in self.entries(now)]
        return max(values,key=lambda value:(PRIORITY[value['kind']],value.get('created_at',0)),default=None)
    def emit(self,kind,summary='',session='',turn='',key=None,now=None,lifetime=12,**metadata):
        now=time.time() if now is None else now
        key=key or uuid.uuid4().hex
        self._write(key,{'kind':kind,'title':TITLES[kind],'summary':short_text(summary),
                         'session':session,'turn':turn,'created_at':now,'expires_at':now+lifetime,**metadata})
    def clear(self,session,turn=None,pending_only=False,now=None):
        for path,data in self.entries(now):
            if data.get('session')==session and (turn is None or data.get('turn')==turn) and (not pending_only or data['kind'] in ('question','permission')):
                path.unlink(missing_ok=True)
    @staticmethod
    def tool_key(payload):
        # Raw tool inputs, command lines and full chats are never persisted.
        inputs=payload.get('tool_input')
        if isinstance(inputs,dict): inputs={key:value for key,value in inputs.items() if key not in ('description','justification')}
        value=[payload.get('session_id',''),payload.get('turn_id',''),payload.get('tool_name',''),inputs]
        return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def receive_hook(self,payload,now=None):
        now=time.time() if now is None else now
        event=payload.get('hook_event_name'); session=payload.get('session_id')
        if not isinstance(session,str) or not session: return
        turn=payload.get('turn_id',''); tool=payload.get('tool_name','')
        inputs=payload.get('tool_input') or {}
        if not isinstance(inputs,dict): inputs={}
        key=self.tool_key(payload)
        if event=='PermissionRequest':
            self.emit('permission',inputs.get('description') or inputs.get('justification') or '请回 Codex 查看权限请求',session,turn,key,now,86400,tool=tool)
        elif event=='PreToolUse' and question_tool(tool):
            questions=inputs.get('questions') or []
            first=questions[0] if questions and isinstance(questions[0],dict) else {}
            summary=first.get('question') or first.get('title') or 'Codex 有问题需要你回答'
            self.emit('question',summary,session,turn,key,now,86400,tool=tool,asynchronous=tool.endswith('_async'))
        elif event=='PostToolUse':
            path=self.directory/(key+'.json')
            if path.exists():
                try:
                    pending=json.loads(path.read_text(encoding='utf-8'))
                    if not pending.get('asynchronous'): path.unlink(missing_ok=True)
                except (OSError,ValueError,TypeError): pass
        elif event in ('UserPromptSubmit','SessionEnd','Interrupt'):
            self.clear(session,now=now)
            if event=='Interrupt': self.emit('interrupted','任务已暂停，请回 Codex 查看',session,turn,now=now)
        elif event=='Stop':
            if payload.get('stop_hook_active'): return
            self.clear(session,pending_only=True,now=now)
            self.emit('completed','本轮处理结束，可以回 Codex 查看结果',session,turn,
                      key=hashlib.sha256((session+'|'+str(turn)+'|completed').encode()).hexdigest(),now=now)

class HourlyChime:
    def __init__(self): self.last_hour=None
    def poll(self,now=None,enabled=True):
        now=time.time() if now is None else now
        local=datetime.fromtimestamp(now); hour=local.strftime('%Y-%m-%d %H')
        previous=self.last_hour; self.last_hour=hour
        if previous is None or previous==hour or not enabled or local.minute!=0 or local.second>30: return None
        return {'kind':'hourly','title':local.strftime('现在是 %H:00'),'summary':'整点报时 · 使用电脑时记得适当休息',
                'created_at':now,'expires_at':now+12}
