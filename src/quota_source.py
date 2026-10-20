"""Read quota through the official Codex JSON-RPC app-server, never auth files."""
from __future__ import annotations
import json, math, os, queue, shutil, subprocess, threading, time
from pathlib import Path

class QuotaError(RuntimeError):
    pass

def find_codex() -> list[str]:
    override = os.environ.get('SHUANGLING_CODEX_EXE')
    candidates = [override, shutil.which('codex.exe')]
    roaming = Path(os.environ.get('APPDATA', str(Path.home() / 'AppData/Roaming')))
    package = roaming / 'npm/node_modules/@openai/codex'
    candidates += [str(package / 'node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/codex/codex.exe'),
                   str(package / 'vendor/x86_64-pc-windows-msvc/codex/codex.exe')]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return [candidate]
    node = shutil.which('node.exe') or shutil.which('node')
    if node and (package / 'bin/codex.js').is_file():
        return [node, str(package / 'bin/codex.js')]
    raise QuotaError('未找到 Codex CLI，请安装或在设置中指定 codex.exe。')

def normalize_quota(result: dict) -> dict:
    """Unknown stays unknown. Derive remaining only from valid used percentages."""
    buckets = result.get('rateLimitsByLimitId') or {}
    bucket = buckets.get('codex') or result.get('rateLimits')
    if not isinstance(bucket, dict):
        if buckets:
            bucket = next(iter(buckets.values()))
        else:
            raise QuotaError('服务未返回套餐额度。请确认 Codex 使用 ChatGPT 账号登录。')
    windows = []
    for key in ('primary', 'secondary'):
        w = bucket.get(key)
        if not isinstance(w, dict):
            continue
        used, duration, reset = w.get('usedPercent'), w.get('windowDurationMins'), w.get('resetsAt')
        if isinstance(used, bool) or not isinstance(used, (int, float)) or not math.isfinite(used):
            continue
        duration = duration if isinstance(duration, (int, float)) and duration > 0 else None
        reset = reset if isinstance(reset, (int, float)) and math.isfinite(reset) else None
        label = '本周' if duration == 10080 else ('5小时' if duration == 300 else (f'{duration/60:g}小时' if duration and duration >= 60 else (f'{duration:g}分钟' if duration else '套餐')))
        windows.append({'key': key, 'used_percent': used, 'remaining_percent': max(0, min(100, 100-used)),
                        'duration_mins': duration, 'resets_at': reset, 'label': label})
    if not windows:
        raise QuotaError('暂未取得可用额度窗口，稍后重试。')
    windows.sort(key=lambda w: w['duration_mins'] if w['duration_mins'] else float('inf'))
    credits = bucket.get('credits')
    return {'windows': windows, 'plan': bucket.get('planType'), 'limit_id': bucket.get('limitId') or 'codex',
            'credits_balance': credits.get('balance') if isinstance(credits, dict) else None,
            'updated_at': time.time(), 'source': 'Codex account/rateLimits/read'}

class CodexClient:
    def __init__(self, command=None):
        self.command = command
        self.process = None
        self.inbox = queue.Queue()
        self.sequence = 0

    def start(self):
        self.close()
        self.inbox = queue.Queue()
        command = self.command or find_codex()
        environment = os.environ.copy()
        environment.setdefault('CODEX_HOME', str(Path.home() / '.codex'))
        self.process = subprocess.Popen(command + ['app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.DEVNULL, text=True, encoding='utf-8', errors='replace',
                                        bufsize=1, env=environment, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        proc, inbox = self.process, self.inbox
        def reader():
            try:
                for line in proc.stdout:
                    try:
                        inbox.put(json.loads(line))
                    except (ValueError, TypeError):
                        pass
            finally:
                inbox.put({'_closed': True})
        threading.Thread(target=reader, daemon=True).start()
        self.request('initialize', {'clientInfo': {'name': 'shuangling_quota_widget', 'title': '霜铃额度挂件', 'version': '1.0.0'}}, timeout=15)
        self.send({'method': 'initialized', 'params': {}})

    def send(self, message):
        if not self.process or self.process.poll() is not None:
            raise QuotaError('Codex 额度服务已退出。')
        try:
            self.process.stdin.write(json.dumps(message, ensure_ascii=False) + '\n')
            self.process.stdin.flush()
        except (OSError, ValueError):
            raise QuotaError('无法连接本机 Codex 额度服务。') from None

    def request(self, method, params=None, timeout=40):
        self.sequence += 1
        request_id = self.sequence
        message = {'id': request_id, 'method': method}
        if params is not None:
            message['params'] = params
        self.send(message)
        deadline = time.monotonic()+timeout
        while True:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise QuotaError('额度读取超时，正在等待重试。')
            try:
                response = self.inbox.get(timeout=remaining)
            except queue.Empty:
                raise QuotaError('额度读取超时，正在等待重试。') from None
            if response.get('_closed'):
                raise QuotaError('Codex 服务未能启动，请检查 CLI 登录状态。')
            if response.get('id') != request_id:
                continue
            if 'error' in response:
                text = str(response['error'].get('message', ''))
                if any(word in text.lower() for word in ('auth', 'login', 'sign in', 'credential', 'token')):
                    raise QuotaError('请先使用 ChatGPT 账号登录 Codex CLI，再刷新。')
                raise QuotaError('额度服务暂时不可用，请稍后重试。')
            return response.get('result') or {}

    def read(self):
        if not self.process or self.process.poll() is not None:
            self.start()
        try:
            return normalize_quota(self.request('account/rateLimits/read'))
        except Exception:
            self.close()
            raise

    def close(self):
        proc, self.process = self.process, None
        if not proc:
            return
        try:
            proc.stdin.close()
            proc.wait(timeout=1)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        for stream in (proc.stdin, proc.stdout):
            try:
                stream.close()
            except (AttributeError, OSError, ValueError):
                pass

if __name__ == '__main__':
    client=CodexClient()
    try:
        print(json.dumps(client.read(),ensure_ascii=False,indent=2))
    finally:
        client.close()
