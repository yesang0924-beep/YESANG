# -*- coding: utf-8 -*-
"""Relay Console — 本地 AI 网关管理台

一个 pywebview 桌面程序：把 go_proxy(:18047) + gemini-proxy(:18045) 这套
「多上游模型网关」的状态查看、启停、模型池维护、日志与用量汇总收进一个窗口。

引擎本身仍是 D:\\DeepSeek\\bin 下既有的 go_proxy.py / relay-watchdog.py，
本程序只做管理外壳，不复制任何转发逻辑。
"""
import ctypes
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import webview

from tray import TrayController

# ---------------------------------------------------------------- 本机路径配置
# 所有依赖本机环境的路径集中在 config.local.json（不入库，见 config.example.json）。
# 打包后的 exe 若找不到配置，会弹窗提示并退出，而不是带着写死的私人路径分发。
_HERE = Path(__file__).resolve().parent


def _load_local_cfg():
    # 查找顺序：exe 同目录（冻结分发）→ 项目根（源码运行）→ 解包目录（最后兜底）。
    # 刻意不把 config.local.json 打进 exe —— 私人路径不该被裹进分发包。
    cands = []
    if getattr(sys, 'frozen', False):
        cands.append(Path(sys.executable).resolve().parent / 'config.local.json')
    cands.append(_HERE / 'config.local.json')
    meipass = getattr(sys, '_MEIPASS', '')
    if meipass:
        cands.append(Path(meipass) / 'config.local.json')
    for cand in cands:
        try:
            if cand.exists():
                return json.loads(cand.read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            continue
    ctypes.windll.user32.MessageBoxW(
        None,
        '未找到 config.local.json。\n\n请复制 config.example.json 为 config.local.json，'
        '放在程序同目录并按本机实际路径填写后重新启动。',
        'Relay Console — 缺少配置', 0x10)
    sys.exit(1)


_CFG = _load_local_cfg()
BIN = Path(_CFG['bin_dir'])
# 密钥存储模块与网关共用；缺失时回退明文，保证控制台仍能启动。
try:
    import sys as _sys
    _sys.path.insert(0, str(BIN))
    import secret_store
except Exception:  # noqa: BLE001
    secret_store = None
CODEX_DIR = Path(_CFG['codex_dir'])
CATALOG = Path(_CFG['catalog_path'])
CONFIG_TOML = CODEX_DIR / 'config.toml'
STARTUP = Path(os.environ['APPDATA']) / r'Microsoft\Windows\Start Menu\Programs\Startup'
PYTHONW = _CFG['pythonw']
PM2 = _CFG['pm2_cmd']
RUNTIME_PY = _CFG['runtime_python']
DETACHED, NEWGRP, NO_WINDOW = 0x00000008, 0x00000200, 0x08000000
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 强制直连，避开宿主 HTTP_PROXY

_CONFIG_LOCK = threading.RLock()
WATCHDOG_PAUSE = BIN / 'relay-watchdog.pause'
CONTROL_TOKEN_FILE = BIN / 'go-proxy.control'


def atomic_write_text(path, text, encoding='utf-8'):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, 'w', encoding=encoding, newline='') as f:
            f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(str(tmp), str(path))
    finally:
        try:
            if tmp.exists(): tmp.unlink()
        except Exception:
            pass


def atomic_write_json(path, data):
    atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + '\n')


def _validate_catalog(data):
    if not isinstance(data, dict) or not isinstance(data.get('models'), list):
        raise ValueError('模型目录必须是 {"models": [...]} 结构')
    seen = set()
    for m in data['models']:
        if not isinstance(m, dict): raise ValueError('模型目录存在非对象条目')
        slug = m.get('slug')
        if not isinstance(slug, str) or not slug.strip(): raise ValueError('模型目录存在空 slug')
        if slug in seen: raise ValueError('模型目录存在重复 slug: %s' % slug)
        seen.add(slug)


def _validate_routes(data):
    if not isinstance(data, dict) or not isinstance(data.get('upstreams'), dict):
        raise ValueError('路由配置缺少 upstreams')
    if 'routes' in data and not isinstance(data['routes'], list):
        raise ValueError('路由配置 routes 必须是数组')


def read_secret_value(path):
    if secret_store is not None:
        return secret_store.read_secret(path)
    return Path(path).read_text(encoding='utf-8').strip()


def secret_available(path):
    try:
        return bool(read_secret_value(path))
    except Exception:
        return False


def protect_secret_value(text):
    if secret_store is not None:
        return secret_store.protect_text(text)
    return text


def _locked(fn):
    def wrapper(*args, **kwargs):
        with _CONFIG_LOCK: return fn(*args, **kwargs)
    return wrapper


def _audited(action):
    def deco(fn):
        def wrapper(*args, **kwargs):
            result = fn(*args, **kwargs)
            try:
                if isinstance(result, dict) and result.get('ok'):
                    api = args[0] if args else None
                    target = args[1] if len(args) > 1 else (kwargs.get('name') or kwargs.get('slug') or action)
                    api._audit(action, str(target), result.get('msg', ''))
            except Exception:
                pass
            return result
        return wrapper
    return deco


def gateway_health(timeout=2.0):
    try:
        raw = OPENER.open('http://127.0.0.1:%d/healthz' % GATEWAY_PORT, timeout=timeout).read()
        data = json.loads(raw.decode('utf-8', 'replace'))
        return data if isinstance(data, dict) and data.get('ok') is True else None
    except Exception:
        return None


def _read_control_token():
    try:
        if CONTROL_TOKEN_FILE.exists():
            return CONTROL_TOKEN_FILE.read_text(encoding='utf-8').strip()
    except Exception:
        pass
    return ''


def pause_watchdog(seconds=90, reason='relay-console'):
    atomic_write_json(WATCHDOG_PAUSE, {'until': time.time() + max(5, int(seconds)), 'reason': reason})


def resume_watchdog():
    try: WATCHDOG_PAUSE.unlink()
    except FileNotFoundError: pass
    except Exception: pass


def request_gateway_shutdown(timeout=5.0):
    token = _read_control_token()
    if not token: return False, '控制令牌不可用'
    req = urllib.request.Request('http://127.0.0.1:%d/admin/shutdown' % GATEWAY_PORT,
                                 data=b'', method='POST',
                                 headers={'Content-Type': 'application/json',
                                          'X-Relay-Control-Token': token})
    try:
        with OPENER.open(req, timeout=timeout) as resp:
            return resp.status in (200, 202), 'HTTP %s' % resp.status
    except urllib.error.HTTPError as exc:
        return False, 'HTTP %s' % exc.code
    except Exception as exc:
        return False, '%s: %s' % (type(exc).__name__, exc)


def run_hidden(args, timeout=None):
    """带 CREATE_NO_WINDOW 的 subprocess.run。

    GUI 进程里凡是调 netstat / tasklist / taskkill / pm2 这类控制台程序，
    不加这个标志就会**每次调用都闪一个黑窗口**（本程序早前版本正是因此
    被用户看到「动不动就弹黑窗」）。
    """
    return subprocess.run(args, capture_output=True, text=True, errors='replace',
                          timeout=timeout, creationflags=NO_WINDOW)

GATEWAY_PORT = 18047
APP_VERSION = '0.4.0'
CONFIG_SCHEMA_VERSION = 2
EXPECTED_GATEWAY_PROTOCOL = 1
BUDGET_FILE = BIN / 'go-budget.json'
GEMINI_PORT = 18045
UPSTREAM_LABELS = {'go': 'OpenCode Go', 'local': 'Local Relay',
                   'yh': 'Yoshub', 'yhds': 'Yoshub DeepSeek'}
# 探测模型优先从 catalog 按前缀动态挑（上游下架旧模型时不会误报），
#  catalog 里一个都没有时才回退到这里的占位。
UPSTREAM_PROBE_FALLBACK = {'go': 'go/deepseek-v4.1-flash', 'local': 'local/gemini-3.7-flash',
                           'yh': 'yh/grok-4.6', 'yhds': 'yhds/deepseek-v4.1-flash'}
PREFIX_LABELS = {'go/': '[Go]', 'local/': '[Local]', 'yh/': '[Yoshub]', 'yhds/': '[YS-DS]'}

# 网关的 chat-only 名单（需要协议翻译的模型），同步界面用来提示"这个模型要翻译"
CHAT_ONLY_FILE = BIN / 'chat-only-models.json'


def _load_chat_only_names():
    try:
        data = json.loads(CHAT_ONLY_FILE.read_text(encoding='utf-8'))
        return {k for k, v in data.items() if v and not k.startswith('_')}
    except Exception:
        return set()


CHAT_ONLY_NAMES = _load_chat_only_names()


def _pick_probe_model(key):
    """给某上游挑一个探测模型：catalog 里按前缀找第一个，找不到回退占位。"""
    prefix = key + '/'
    data = read_json(CATALOG, {'models': []}) or {'models': []}
    for m in data.get('models', []):
        slug = m.get('slug', '')
        if slug.startswith(prefix):
            return slug
    return UPSTREAM_PROBE_FALLBACK.get(key, prefix + 'deepseek-v4.1-flash')


# ---------------------------------------------------------------- 基础工具
def port_open(port: int, timeout: float = 1.5) -> bool:
    s = socket.socket()
    s.settimeout(timeout)
    try:
        s.connect(('127.0.0.1', port))
        return True
    except Exception:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


def http_ok(url: str, timeout: float = 6.0) -> bool:
    try:
        OPENER.open(url, timeout=timeout)
        return True
    except urllib.error.HTTPError:
        return True          # 有响应即视为存活
    except Exception:
        return False


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:
        return default


def tail(path: Path, lines: int = 120):
    """读文件末尾 N 行：seek 到尾部倒读，不全量加载。

    旧实现是 read_text 读整个文件 —— go-proxy.log 跑久了几十 MB，
    前端每 12s 的日志刷新都会跟着卡一下。现在按行均长估算首块大小，
    行数不够再成倍扩块，直到读够或扩到整个文件。
    """
    try:
        size = path.stat().st_size
        if size == 0:
            return []
        with path.open('rb') as f:
            chunk = min(size, max(8192, lines * 240))
            while True:
                f.seek(max(0, size - chunk))
                data = f.read().decode('utf-8', errors='replace').splitlines()
                if len(data) > lines or chunk >= size:
                    return data[-lines:]
                chunk = min(size, chunk * 4)
    except Exception:
        return []


def spawn_detached(args):
    return subprocess.Popen(args, cwd=str(BIN),
                            creationflags=DETACHED | NEWGRP | NO_WINDOW, close_fds=True)


def pid_listening(port: int):
    out = run_hidden(['netstat', '-ano', '-p', 'TCP']).stdout or ''
    pids = set()
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[1].endswith(':%d' % port) and parts[3] == 'LISTENING':
            pids.add(parts[4])
    return pids


def process_command_line(pid):
    try:
        out = run_hidden(['wmic', 'process', 'where', 'ProcessId=%s' % pid,
                          'get', 'CommandLine', '/value']).stdout or ''
        for line in out.splitlines():
            if line.lower().startswith('commandline='):
                return line.split('=', 1)[1].strip()
    except Exception:
        pass
    return ''


def kill_pids(pids, expected=None):
    for pid in pids:
        if expected:
            cmd = process_command_line(pid)
            if cmd and expected.lower() not in cmd.lower():
                continue
            if not cmd:
                info = (run_hidden(['tasklist', '/FI', 'PID eq %s' % pid, '/FO', 'CSV']).stdout or '').lower()
                if 'python' not in info:
                    continue
        run_hidden(['taskkill', '/PID', pid, '/F'])


def process_alive(pid: str) -> bool:
    if not pid or not pid.isdigit():
        return False
    out = run_hidden(['tasklist', '/FI', 'PID eq %s' % pid, '/FO', 'CSV']).stdout or ''
    low = out.lower()
    return ('python' in low or 'node' in low) and ('no tasks' not in low)


# ---------------------------------------------------------------- API（暴露给前端 JS）
class Api:
    def __init__(self, tray=None):
        # 托盘控制器（可能为 None —— 托盘起不来不影响其它功能）
        self._tray = tray
        # 状态缓存：UI 一轮操作会连环拉 get_health/get_status，TTL 内直接吃缓存，
        # 免得每次点击都跑一轮 netstat/tasklist。改状态的动作结束时要主动失效它。
        self._status_cache = None        # (monotonic_ts, status_dict)
        self._status_cache_ttl = 3.0     # 秒

    # ---- 状态 ----
    def _invalidate_status_cache(self):
        self._status_cache = None

    def get_status(self):
        now = time.monotonic()
        if self._status_cache and now - self._status_cache[0] < self._status_cache_ttl:
            return self._status_cache[1]
        watch_pid_file = BIN / 'relay-watchdog.pid'
        watch_pid = watch_pid_file.read_text(encoding='utf-8').strip() if watch_pid_file.exists() else ''
        gem_pids = pid_listening(GEMINI_PORT)
        gw_health = gateway_health(timeout=2)
        gw_up = gw_health is not None or http_ok('http://127.0.0.1:%d/healthz' % GATEWAY_PORT, timeout=2)
        st = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'ports': [
                {'port': GATEWAY_PORT, 'name': 'go_proxy', 'desc': 'OpenCode Go 返代',
                # /healthz 探测：端口开着 ≠ 进程活着（假死时 TCP 仍在监听）。
                # 老网关没这端点会回 404，兼容回退到任何 HTTP 响应视为存活。
                'up': gw_up, 'health': gw_health},
                {'port': GEMINI_PORT, 'name': 'gemini-proxy', 'desc': '本地 Gemini 反代',
                 'up': port_open(GEMINI_PORT)},
            ],
            'watchdog': {'pid': watch_pid, 'alive': process_alive(watch_pid)},
            'proxy_ports': [
                {'port': 7897, 'name': '境外线路 A', 'desc': '访问 OpenCode Go / Yoshub 走这条',
                 'up': port_open(7897)},
                {'port': 60696, 'name': '境外线路 B', 'desc': '备用线路，A 不通时自动切换',
                 'up': port_open(60696)},
            ],
            'gemini_pids': sorted(gem_pids),
            'autostart': (STARTUP / 'relay-watchdog.cmd').exists(),
        }
        self._status_cache = (now, st)
        return st

    def get_health(self):
        """整体健康度总评 + 可展开的分项体检。"""
        st = self.get_status()
        gateway = st['ports'][0]; gemini = st['ports'][1]
        gateway_up = gateway['up']; gemini_up = gemini['up']
        watchdog_up = st['watchdog']['alive']
        proxy_up = any(p['up'] for p in st['proxy_ports'])
        checks = [
            {'name': '模型网关', 'ok': gateway_up, 'detail': '端口 %d，/healthz %s' % (GATEWAY_PORT, '正常' if gateway.get('health') else '仅端口可用')},
            {'name': '守护进程', 'ok': watchdog_up, 'detail': '网关异常时自动拉起' if watchdog_up else '未运行，异常后不会自动恢复'},
            {'name': '本地反代', 'ok': gemini_up, 'detail': '端口 %d' % GEMINI_PORT},
            {'name': '境外线路', 'ok': proxy_up, 'detail': '至少一条出口线路可用' if proxy_up else '未检测到可用出口线路'},
        ]
        budget = self._budget_status()
        checks.append({'name': '费用预算', 'ok': budget['ok'],
                       'detail': budget['message']})
        problems = []
        if not budget['ok']:
            problems.append(budget['message'])
        if not gateway_up: problems.append('模型网关（18047）没在运行 —— Codex 现在无法调用任何模型')
        elif not watchdog_up: problems.append('守护进程没在运行 —— 网关一旦挂掉不会自动恢复')
        if not gemini_up:
            local_n = sum(1 for m in self.get_models() if m['group'] == '[Local]')
            problems.append('本地 Gemini 反代（18045）没在运行 —— [Local] 组 %d 个模型不可用' % local_n)
        if not proxy_up:
            problems.append('没检测到境外线路（你的代理软件没开）—— 访问 OpenCode Go / Yoshub 会走直连，可能变慢或超时')
        level = 'fail' if not gateway_up else ('warn' if problems else 'ok')
        if self._tray is not None: self._tray.set_level(level)
        gateway_protocol = (gateway.get('health') or {}).get('control_protocol')
        versions = {
            'console': APP_VERSION,
            'config_schema': CONFIG_SCHEMA_VERSION,
            'gateway_protocol': gateway_protocol,
            'expected_gateway_protocol': EXPECTED_GATEWAY_PROTOCOL,
        }
        return {'level': level, 'problems': problems, 'checks': checks,
                'versions': versions, 'status': st}

    def _wait_gateway_healthy(self, timeout=25):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if gateway_health(timeout=1.0) is not None: return True
            time.sleep(0.4)
        return False

    def _start_gateway_wait(self, timeout=25):
        spawn_detached([PYTHONW, str(BIN / 'go_proxy.py')])
        return self._wait_gateway_healthy(timeout)

    def _stop_gateway_wait(self, timeout=25):
        """等端口释放；超时则兜底按 PID 终止。

        ⚠️ 两个陷阱（2026-09-16 记录，改这段前务必先读）：
          1. 内部会发 `/admin/shutdown`，而网关收到它**不是"停"，而是"排干旧的 +
             派生新实例接管"**。所以端口**永远等不到自己空出来**，实际总是走到下面的
             兜底 `kill_pids` —— 也就是说这里是"先白白等满 25s，再杀"。
          2. `restart_gateway` 曾额外再发一次 `/admin/shutdown` → 派生两个实例 → 双绑。
             已改为走 `_wait_gateway_replaced`（见下）。若哪天要给 restart 复用本函数，
             请**只发一次**停机。
        `stop_all` 仍在用本函数：它的兜底 kill 是有效的，只是会慢 25s。
        """
        requested, detail = request_gateway_shutdown()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not port_open(GATEWAY_PORT, timeout=0.5):
                return True, '优雅停机' if requested else '进程已退出'
            time.sleep(0.4)
        pids = pid_listening(GATEWAY_PORT)
        if pids: kill_pids(pids, expected='go_proxy.py')
        time.sleep(1)
        return (not port_open(GATEWAY_PORT, timeout=0.5), '优雅停机' if requested else '兜底终止')

    def one_click(self):
        """一键修复：按依赖顺序处理，并对网关启动结果做真实健康检查。"""
        actions = []; st = self.get_status()
        if not st['ports'][0]['up']:
            pause_watchdog(90, 'relay-console one-click')
            try:
                kill_pids(pid_listening(GATEWAY_PORT), expected='go_proxy.py')
                actions.append('启动模型网关并通过健康检查' if self._start_gateway_wait(25) else '模型网关启动后健康检查失败')
            finally:
                resume_watchdog()
        if not st['watchdog']['alive']:
            try: (BIN / 'relay-watchdog.pid').unlink()
            except Exception: pass
            spawn_detached([PYTHONW, str(BIN / 'relay-watchdog.py')]); actions.append('启动守护进程')
        if not st['ports'][1]['up']:
            try:
                run_hidden(['cmd', '/c', PM2, 'restart', 'gemini-proxy'], timeout=120)
                actions.append('重启本地 Gemini 反代')
            except Exception: pass
        time.sleep(2); self._invalidate_status_cache()
        return {'actions': actions or ['一切正常，无需修复'], 'health': self.get_health()}
    UPSTREAM_PROBE_TIMEOUT = 45          # 单路上游实测超时（秒）

    def _probe_one_upstream(self, key):
        """单路上游实测，返回带 latency_ms 的结果条目。独立出来供线程池并行调用。"""
        model = _pick_probe_model(key)
        body = json.dumps({'model': model,
                           'input': [{'role': 'user',
                                      'content': [{'type': 'input_text', 'text': 'hi'}]}],
                           'max_output_tokens': 16}).encode()
        req = urllib.request.Request('http://127.0.0.1:%d/v1/responses' % GATEWAY_PORT,
                                     data=body,
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer x'})
        entry = {'key': key, 'label': UPSTREAM_LABELS.get(key, key), 'model': model}
        t0 = time.monotonic()
        try:
            OPENER.open(req, timeout=self.UPSTREAM_PROBE_TIMEOUT)
            entry.update(state='ok', detail='')
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:80]
            entry.update(state='warn' if exc.code in (429, 503) else 'fail',
                         detail='HTTP %s %s' % (exc.code, detail))
        except Exception as exc:
            entry.update(state='fail', detail=type(exc).__name__)
        entry['latency_ms'] = int((time.monotonic() - t0) * 1000)
        return entry

    def test_upstreams(self):
        """四路上游并行实测：最坏耗时从串行 4×45s 降到 45s，并给出每路延迟。"""
        keys = list(UPSTREAM_LABELS)
        with ThreadPoolExecutor(max_workers=len(keys)) as pool:
            return list(pool.map(self._probe_one_upstream, keys))   # map 保序

    # ---- 启停 ----
    def start_all(self):
        started = []; st = self.get_status()
        if not st['ports'][0]['up']:
            pause_watchdog(90, 'relay-console start-all')
            try:
                if self._start_gateway_wait(25): started.append('go_proxy')
            finally: resume_watchdog()
        pid_file = BIN / 'relay-watchdog.pid'
        pid = pid_file.read_text(encoding='utf-8').strip() if pid_file.exists() else ''
        if not process_alive(pid):
            try: pid_file.unlink()
            except Exception: pass
            spawn_detached([PYTHONW, str(BIN / 'relay-watchdog.py')]); started.append('relay-watchdog')
        time.sleep(2); self._invalidate_status_cache()
        return {'started': started, 'status': self.get_status()}

    def stop_all(self):
        pause_watchdog(90, 'relay-console stop-all')
        try: self._stop_gateway_wait(25)
        finally: resume_watchdog()
        pid_file = BIN / 'relay-watchdog.pid'
        pid = pid_file.read_text(encoding='utf-8').strip() if pid_file.exists() else ''
        if process_alive(pid): run_hidden(['taskkill', '/PID', pid, '/F'])
        try: pid_file.unlink()
        except Exception: pass
        time.sleep(1); self._invalidate_status_cache()
        return {'status': self.get_status()}

    def _wait_gateway_replaced(self, before, timeout=40):
        """等一个**不同的**网关实例通过健康检查。

        ★ 为什么需要它：网关侧的 `/admin/shutdown` **不是"停掉"，而是"排干旧的 + 派生
          一个新实例接管"**（go_proxy 的 `_respawn_self`，2026-09-15 起为了让重启不留
          空窗）。所以重启的正确姿势是「发一次停机 + 等新实例」，而不是「停掉再手动启
          一个」—— 后者会造成**双实例**。

        判据优先用 `healthz.singleton.pid`（唯一能区分实例的字段），拿不到时退回
        「uptime_s 很小」= 刚起来不久。
        """
        old_pid = ((before or {}).get('singleton') or {}).get('pid')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            h = gateway_health(timeout=1.0)
            if h:
                pid = (h.get('singleton') or {}).get('pid')
                if old_pid is not None and pid is not None:
                    if pid != old_pid:
                        return True
                elif (h.get('uptime_s') or 99999) < 90:
                    return True
            time.sleep(0.4)
        return False

    def restart_gateway(self):
        """暂停守护 → 请求**一次**优雅停机（网关自派生子实例接管）→ 等新实例健康。

        ★ 2026-09-16 修：原实现**连发两次** `/admin/shutdown`（本函数一次 +
          `_stop_gateway_wait` 内部又一次）。而网关侧每收到一次 `/admin/shutdown`
          都会派生一个新实例接管，于是「两次停机 = 派生两个实例」—— 实测出现
          18047 上两个 PID 同时 LISTENING（双绑：熔断 / 缓存 / 用量状态被劈成两份，
          现场表现为「新代码明明部署了却没生效」）。
          现在：**只发一次** → 等新实例接管 → 只有确实没接管才兜底启动。
          兜底启动是安全的：网关侧有单实例硬锁，多起的那次会被拒绝启动。
        """
        steps = []
        pause_watchdog(120, 'relay-console restart')
        try:
            before = gateway_health(timeout=1.0) or {}
            requested, detail = request_gateway_shutdown()
            steps.append('已请求优雅停机（%s）' % detail if requested
                         else '网关不支持优雅停机（%s），走兜底' % detail)
            if self._wait_gateway_replaced(before, timeout=40):
                steps.append('新实例已接管并通过 /healthz 检查'); ok = True
            else:
                steps.append('未观察到新实例接管，兜底启动')
                ok = self._start_gateway_wait(25)
                steps.append('兜底启动成功' if ok else '兜底启动后健康检查仍失败')
            self._invalidate_status_cache()
            return {'ok': ok, 'steps': steps, 'status': self.get_status()}
        finally:
            resume_watchdog()
    # ---- 模型池 ----
    def get_models(self):
        data = read_json(CATALOG, {'models': []}) or {'models': []}
        models = []
        for m in data.get('models', []):
            slug = m.get('slug', '')
            group = next((v for k, v in PREFIX_LABELS.items() if slug.startswith(k)), '[其他]')
            models.append({
                'slug': slug,
                'display': m.get('display_name', slug),
                'desc': m.get('description', ''),
                'group': group,
                'ctx': m.get('context_window', 0),
                'priority': m.get('priority', 999),
            })
        models.sort(key=lambda x: x['priority'])
        return models

    @_audited('remove_model')
    @_locked
    def remove_model(self, slug):
        data = read_json(CATALOG, {'models': []}) or {'models': []}
        before = len(data.get('models', []))
        data['models'] = [m for m in data.get('models', []) if m.get('slug') != slug]
        if len(data['models']) == before:
            return {'ok': False, 'msg': '未找到该模型'}
        self._safe_write_json(CATALOG, data, _validate_catalog)
        return {'ok': True, 'msg': '已移除 %s' % slug, 'models': self.get_models()}

    @_audited('add_model')
    @_locked
    def add_model(self, slug, display, upstream):
        slug = (slug or '').strip()
        if not slug:
            return {'ok': False, 'msg': '模型 id 不能为空'}
        if not slug.startswith(upstream):
            slug = upstream + slug
        data = read_json(CATALOG, {'models': []}) or {'models': []}
        if any(m.get('slug') == slug for m in data.get('models', [])):
            return {'ok': False, 'msg': '该模型已存在'}
        tpl = dict(data['models'][0]) if data.get('models') else {}
        tpl.update({'slug': slug,
                    'display_name': (display or slug).strip(),
                    'description': 'added via Relay Console',
                    'priority': max([m.get('priority', 0) for m in data.get('models', [])] or [0]) + 1})
        data.setdefault('models', []).append(tpl)
        self._safe_write_json(CATALOG, data, _validate_catalog)
        return {'ok': True, 'msg': '已添加 %s' % slug, 'models': self.get_models()}

    @_audited('move_model')
    @_locked
    def move_model(self, slug, direction):
        """上移/下移模型 —— priority 决定客户端模型下拉菜单里的顺序。"""
        data = read_json(CATALOG, {'models': []}) or {'models': []}
        models = data.get('models', [])
        # 稳定排序拿到当前顺序（priority 并列时保持文件内先后）
        order = sorted(range(len(models)),
                       key=lambda i: (models[i].get('priority', 999), i))
        pos = next((p for p, i in enumerate(order) if models[i].get('slug') == slug), -1)
        if pos < 0:
            return {'ok': False, 'msg': '未找到该模型'}
        q = pos - 1 if direction == 'up' else pos + 1
        if q < 0 or q >= len(order):
            return {'ok': True, 'msg': '已经在边缘，没动', 'models': self.get_models()}
        order[pos], order[q] = order[q], order[pos]
        for p, i in enumerate(order, 1):        # 顺手把 priority 归一化成 1..N
            models[i]['priority'] = p
        self._safe_write_json(CATALOG, data, _validate_catalog)
        return {'ok': True, 'msg': '已调整顺序', 'models': self.get_models()}

    @_audited('rename_model')
    @_locked
    def rename_model(self, slug, display):
        """改显示名（客户端下拉菜单里看到的名字）。"""
        display = (display or '').strip()
        if not display:
            return {'ok': False, 'msg': '显示名不能为空'}
        data = read_json(CATALOG, {'models': []}) or {'models': []}
        for m in data.get('models', []):
            if m.get('slug') == slug:
                m['display_name'] = display
                self._safe_write_json(CATALOG, data, _validate_catalog)
                return {'ok': True, 'msg': '已改名', 'models': self.get_models()}
        return {'ok': False, 'msg': '未找到该模型'}

    # ---- 模型池同步（从上游 /v1/models 拉取）----
    def fetch_upstream_models(self, name):
        """拉取某上游的可用模型列表，并标注哪些已在池中。"""
        cfg = read_json(BIN / 'go-routes.json', {}) or {}
        up = (cfg.get('upstreams') or {}).get(name)
        if not up:
            return {'ok': False, 'msg': '未找到上游 %s' % name}

        base = (up.get('base') or '').rstrip('/')
        key = ''
        kf = BIN / (up.get('key_file') or '')
        if kf.exists():
            try:
                key = read_secret_value(kf).strip()
            except Exception:
                key = ''

        # 与网关一致：经线路的上游要显式走代理，本地上游必须直连
        opener = (urllib.request.build_opener() if up.get('use_proxy', True) else OPENER)
        headers = {'Authorization': 'Bearer ' + key}
        # OpenCode Go 强制要求会话头，缺了会被 Cloudflare 拦成 403/1010
        if up.get('opencode_session'):
            sf = BIN / 'go-proxy.session'
            if sf.exists():
                try:
                    headers['x-opencode-session'] = sf.read_text(encoding='utf-8').strip()
                except Exception:
                    pass
            headers['User-Agent'] = 'WorkBuddy/1.0 (relay-console)'
        req = urllib.request.Request(base + '/v1/models', headers=headers)
        try:
            data = json.loads(opener.open(req, timeout=25).read().decode('utf-8', 'replace'))
        except urllib.error.HTTPError as exc:
            return {'ok': False, 'msg': 'HTTP %s %s' % (
                exc.code, exc.read().decode('utf-8', 'replace')[:120])}
        except Exception as exc:
            return {'ok': False, 'msg': '%s: %s' % (type(exc).__name__, exc)}

        raw_ids = data.get('data') or data.get('models') or []
        ids = []
        for m in raw_ids:
            mid = m.get('id') if isinstance(m, dict) else m
            if mid:
                ids.append(str(mid))
        ids = sorted(set(ids))

        prefix = ''
        for r in (cfg.get('routes') or []):
            if r.get('upstream') == name:
                prefix = r.get('prefix') or ''
                break

        pool = {m.get('slug') for m in (read_json(CATALOG, {'models': []}) or {'models': []}).get('models', [])}
        known_chat_only = _load_chat_only_names()
        models = [{'id': i, 'slug': prefix + i, 'in_pool': (prefix + i) in pool,
                   'known_chat_only': i in known_chat_only} for i in ids]
        return {'ok': True, 'upstream': name, 'label': up.get('label', name),
                'prefix': prefix, 'total': len(models), 'models': models}

    @_audited('import_models')
    @_locked
    def import_models(self, name, ids):
        """把选中的模型批量加入池（自动加前缀）。"""
        ids = ids or []
        if not ids:
            return {'ok': False, 'msg': '没有选中任何模型'}

        cfg = read_json(BIN / 'go-routes.json', {}) or {}
        prefix = ''
        for r in (cfg.get('routes') or []):
            if r.get('upstream') == name:
                prefix = r.get('prefix') or ''
                break

        data = read_json(CATALOG, {'models': []}) or {'models': []}
        existing = {m.get('slug') for m in data.get('models', [])}
        tpl = dict(data['models'][0]) if data.get('models') else {}
        pri = max([m.get('priority', 0) for m in data.get('models', [])] or [0])

        added = []
        for raw in ids:
            mid = str(raw).strip()
            if not mid:
                continue
            slug = mid if mid.startswith(prefix) else prefix + mid
            if slug in existing:
                continue
            m = dict(tpl)
            m.update({'slug': slug, 'display_name': '[%s] %s' % (name, mid),
                      'description': 'imported from %s' % name,
                      'context_window': 1000000, 'max_context_window': 1000000,
                      'priority': pri + 1})
            pri += 1
            data['models'].append(m)
            existing.add(slug)
            added.append(slug)

        if not added:
            return {'ok': False, 'msg': '选中的模型都已在池中'}

        self._backup(CATALOG)
        CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'ok': True, 'msg': '已导入 %d 个模型' % len(added),
                'added': added, 'models': self.get_models()}

    def probe_model(self, slug):
        t0 = time.time()
        body = json.dumps({'model': slug,
                           'input': [{'role': 'user',
                                      'content': [{'type': 'input_text',
                                                   'text': 'reply with exactly: PONG'}]}],
                           'max_output_tokens': 200}).encode()
        req = urllib.request.Request('http://127.0.0.1:%d/v1/responses' % GATEWAY_PORT,
                                     data=body,
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer x',
                                              'x-relay-timeout': '8'})
        try:
            # 探活超时压缩至 8 秒（网关侧），客户端留 10s 余量，
            # 让「上游无应答」以网关的结构化错误返回，而不是客户端先抛 socket timeout
            resp = OPENER.open(req, timeout=10)
            latency_ms = int((time.time() - t0) * 1000)
            data = json.loads(resp.read().decode('utf-8', 'replace'))
            text = ''
            for item in (data.get('output') or []):
                for c in (item.get('content') or []):
                    if c.get('type') == 'output_text':
                        text += c.get('text', '')
            return {'ok': True, 'text': (text or 'PONG')[:400], 'latency_ms': latency_ms, 'state': 'ok'}
        except urllib.error.HTTPError as exc:
            latency_ms = int((time.time() - t0) * 1000)
            raw = exc.read().decode('utf-8', 'replace')[:300]
            msg = 'HTTP %d' % exc.code
            if exc.code == 503 or 'no available channel' in raw.lower():
                msg = '服务中断/无可用渠道 (503)'
            elif exc.code == 502 or 'proxy_error' in raw.lower():
                msg = '上游无应答/熔断冷却 (502)'
            elif exc.code == 429:
                msg = '上游限流 (429)'
            else:
                msg = 'HTTP %d: %s' % (exc.code, raw)
            return {'ok': False, 'text': msg, 'latency_ms': latency_ms, 'state': 'fail'}
        except (socket.timeout, TimeoutError, urllib.error.URLError) as exc:
            latency_ms = int((time.time() - t0) * 1000)
            err_str = str(exc)
            if 'timed out' in err_str.lower():
                msg = '上游无响应/超时 (8s) · 官网可能已崩溃'
            else:
                msg = '网络连接失败: %s' % err_str
            return {'ok': False, 'text': msg, 'latency_ms': latency_ms, 'state': 'fail'}
        except Exception as exc:
            latency_ms = int((time.time() - t0) * 1000)
            return {'ok': False, 'text': '%s: %s' % (type(exc).__name__, exc), 'latency_ms': latency_ms, 'state': 'fail'}

    # ---- 上游配置 ----
    def get_upstreams(self):
        cfg = read_json(BIN / 'go-routes.json', {}) or {}
        out = []
        for name, up in (cfg.get('upstreams') or {}).items():
            key_file = BIN / (up.get('key_file') or '')
            out.append({
                'name': name,
                'label': up.get('label', name),
                'base': up.get('base', ''),
                'key_file': up.get('key_file', ''),
                'has_key': secret_available(key_file),
                'use_proxy': up.get('use_proxy', True),
            })
        out.sort(key=lambda x: x['name'])
        return {'upstreams': out, 'routes': cfg.get('routes', []),
                'default': cfg.get('default_upstream', '')}

    # ---- 上游配置（可编辑）----
    @staticmethod
    def _mask(key):
        """密钥只回传掩码，绝不明文送到前端。"""
        k = (key or '').strip()
        if not k:
            return ''
        if len(k) <= 10:
            return k[:2] + '*' * (len(k) - 2)
        return '%s%s%s' % (k[:5], '*' * 8, k[-4:])

    def get_upstream_configs(self):
        cfg = read_json(BIN / 'go-routes.json', {}) or {}
        out = []
        for name, up in (cfg.get('upstreams') or {}).items():
            kf = BIN / (up.get('key_file') or '')
            key = ''
            if kf.exists():
                try:
                    key = read_secret_value(kf).strip()
                except Exception:
                    key = ''
            out.append({
                'name': name,
                'label': up.get('label', name),
                'base': up.get('base', ''),
                'key_file': up.get('key_file', ''),
                'key_masked': self._mask(key),
                'has_key': bool(key),
                'use_proxy': up.get('use_proxy', True),
                'opencode_session': up.get('opencode_session', False),
                'routes': [r.get('prefix') for r in (cfg.get('routes') or [])
                           if r.get('upstream') == name],
            })
        out.sort(key=lambda x: x['name'])
        return {'upstreams': out, 'default': cfg.get('default_upstream', '')}

    @_audited('update_upstream')
    @_locked
    def update_upstream(self, name, base=None, use_proxy=None, key=None):
        """更新某个上游的 base / use_proxy / 密钥。留 None 表示该字段不动。

        base 变更需要重启网关才生效（路由配置在进程启动时读取）。
        """
        path = BIN / 'go-routes.json'
        cfg = read_json(path, None)
        if not cfg or name not in (cfg.get('upstreams') or {}):
            return {'ok': False, 'msg': '未找到上游 %s' % name}

        up = cfg['upstreams'][name]
        changed = []

        if base is not None and base.strip():
            up['base'] = base.strip().rstrip('/')
            changed.append('接口地址')
        if use_proxy is not None:
            up['use_proxy'] = bool(use_proxy)
            changed.append('线路模式')

        if key is not None and key.strip():
            kf_name = up.get('key_file') or ('%s.key' % name)
            kf = BIN / kf_name
            self._safe_write_secret(kf, key.strip())
            up['key_file'] = kf_name
            changed.append('密钥')

        if not changed:
            return {'ok': False, 'msg': '没有需要修改的内容'}

        self._safe_write_json(path, cfg, _validate_routes)
        return {'ok': True, 'msg': '已更新 %s：%s' % (name, '、'.join(changed)),
                'need_restart': '接口地址' in changed,
                'configs': self.get_upstream_configs()}

    def test_upstream_config(self, base, key, model='', use_proxy=True, name=''):
        """用一个「待测试」的配置直接发请求，不写入任何文件。

        用于在保存前先确认地址+密钥是否真的通。
        key 留空且给了 name 时，回退用该上游已存的密钥（前端只持有掩码，拿不到明文）。
        """
        base = (base or '').strip().rstrip('/')
        key = (key or '').strip()
        if not base:
            return {'ok': False, 'text': '接口地址为空'}

        cfg = read_json(BIN / 'go-routes.json', {}) or {}

        if not key and name:
            up = (cfg.get('upstreams') or {}).get(name) or {}
            kf = BIN / (up.get('key_file') or '')
            if kf.exists():
                try:
                    key = read_secret_value(kf).strip()
                except Exception:
                    key = ''

        # 挑一个该上游自己的模型来试：从 catalog 里找前缀匹配的，找不到再退回通用占位
        probe_model = (model or '').strip()
        if not probe_model:
            prefixes = [r.get('prefix') for r in (cfg.get('routes') or [])
                        if r.get('upstream') == name and r.get('prefix')]
            catalog = read_json(CATALOG, {'models': []}) or {'models': []}
            for m in catalog.get('models', []):
                slug = m.get('slug', '')
                if any(slug.startswith(p) for p in prefixes):
                    probe_model = slug
                    break
            if not probe_model:
                probe_model = 'deepseek-v4.1-flash'

        url = '%s/v1/chat/completions' % base
        body = json.dumps({'model': probe_model,
                           'messages': [{'role': 'user', 'content': 'hi'}],
                           'max_tokens': 8}).encode()
        req = urllib.request.Request(
            url, data=body,
            headers={'Content-Type': 'application/json',
                     'Authorization': 'Bearer %s' % key})

        opener = OPENER if not use_proxy else urllib.request.build_opener()
        try:
            resp = opener.open(req, timeout=25)
            return {'ok': True, 'text': 'HTTP %s，配置可用' % resp.status}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', 'replace')[:200]
            # 4xx/5xx 说明地址可达（只是鉴权或模型名的问题），仍有诊断价值
            return {'ok': exc.code in (400, 404),
                    'text': 'HTTP %s %s' % (exc.code, detail)}
        except Exception as exc:
            return {'ok': False, 'text': '%s: %s' % (type(exc).__name__, exc)}

    # ---- 日志与用量 ----
    def get_logs(self, which='go-proxy', lines=150):
        mapping = {
            'go-proxy': BIN / 'go-proxy.log',
            'watchdog': BIN / 'relay-watchdog.log',
            'gateway-access': BIN / 'go-proxy.log',
        }
        path = mapping.get(which, BIN / 'go-proxy.log')
        return {'path': str(path), 'lines': tail(path, int(lines))}

    def get_error_summary(self, limit=600):
        """从两份日志尾部做轻量错误聚类，不依赖第三方日志系统。"""
        rules = [
            ('rate_limit', ('429', 'rate_limit', 'rate limit', '限流')),
            ('dns', ('getaddrinfo', 'name or service', 'nodename', 'dns')),
            ('tls', ('ssl', 'tls', 'certificate', 'unexpected_eof')),
            ('timeout', ('timed out', 'timeout', '超时')),
            ('auth', ('401', '403', 'unauthorized', 'forbidden', '鉴权')),
            ('request', ('400', 'invalid_request', 'not supported', 'bad json', '格式错误')),
            ('network', ('connection', 'connect', 'refused', 'reset', 'network', '断流')),
        ]
        counts = {}
        samples = {}
        files = [BIN / 'go-proxy.log', BIN / 'relay-watchdog.log']
        for path in files:
            for raw in tail(path, int(limit)):
                line = (raw or '').strip()
                low = line.lower()
                if not any(tag in low for tag in ('error', 'warning', 'exception', 'fail', '失败', '错误', '告警')):
                    continue
                category = 'other'
                for name, needles in rules:
                    if any(n in low for n in needles):
                        category = name
                        break
                counts[category] = counts.get(category, 0) + 1
                if len(samples.setdefault(category, [])) < 2:
                    samples[category].append(line[-220:])
        items = [{'category': k, 'count': v, 'samples': samples.get(k, [])}
                 for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        return {'items': items, 'total': sum(counts.values()), 'source_lines': limit}

    def get_usage(self):
        """用量统计：减去「清零基线」后返回 —— 清零不动网关数据文件，只记快照。"""
        data = read_json(BIN / 'go-usage.json', {}) or {}
        snap = read_json(BIN / 'go-usage-baseline.json', {}) or {}
        bmodels = (snap.get('data') or {}).get('models') or {}
        since = snap.get('taken_at') or data.get('started', 0)
        models = []
        for name, st in (data.get('models') or {}).items():
            b = bmodels.get(name) or {}

            def diff(k, _st=st, _b=b):
                return max(0, _st.get(k, 0) - _b.get(k, 0))

            models.append({
                'model': name,
                'requests': diff('requests'),
                'ok': diff('ok'),
                'err': diff('err_429') + diff('err_network') + diff('err_other'),
                'in_tokens': diff('prompt_tokens'),
                'out_tokens': diff('completion_tokens'),
                'cost': round(max(0.0, st.get('cost_usd', 0.0) - b.get('cost_usd', 0.0)), 4),
            })
        models.sort(key=lambda x: x['requests'], reverse=True)
        return {'since': since, 'models': models}

    def _budget_status(self):
        cfg = read_json(BUDGET_FILE, {}) or {}
        hourly_limit = max(0.0, float(cfg.get('hourly_usd', 0) or 0))
        daily_limit = max(0.0, float(cfg.get('daily_usd', 0) or 0))
        metrics = self.get_metrics(24)
        now_hour = time.strftime('%Y-%m-%dT%H')
        today = time.strftime('%Y-%m-%d')
        hour_spent = sum(p['cost'] for p in metrics['points'] if p['hour'] == now_hour)
        day_spent = sum(p['cost'] for p in metrics['points'] if p['hour'].startswith(today))
        hour_ok = hourly_limit <= 0 or hour_spent < hourly_limit
        day_ok = daily_limit <= 0 or day_spent < daily_limit
        if not (hourly_limit or daily_limit):
            message = '未设置预算；可在预算面板中启用'
        elif not hour_ok:
            message = '本小时费用 $%.4f 已达预算 $%.4f' % (hour_spent, hourly_limit)
        elif not day_ok:
            message = '今日费用 $%.4f 已达预算 $%.4f' % (day_spent, daily_limit)
        else:
            message = '本小时 $%.4f / $%.4f · 今日 $%.4f / $%.4f' % (
                hour_spent, hourly_limit, day_spent, daily_limit)
        return {'ok': hour_ok and day_ok, 'configured': bool(hourly_limit or daily_limit),
                'hourly_usd': hourly_limit, 'daily_usd': daily_limit,
                'hour_spent': round(hour_spent, 4), 'day_spent': round(day_spent, 4),
                'message': message}

    def get_budget(self):
        return self._budget_status()

    @_audited('set_budget')
    def set_budget(self, hourly_usd, daily_usd):
        try:
            hourly = max(0.0, float(hourly_usd or 0))
            daily = max(0.0, float(daily_usd or 0))
        except Exception:
            return {'ok': False, 'msg': '预算必须是数字'}
        self._safe_write_json(BUDGET_FILE, {'hourly_usd': hourly, 'daily_usd': daily})
        return {'ok': True, 'msg': '预算已更新', 'budget': self._budget_status()}

    def get_metrics(self, hours=24):
        """返回最近 N 小时按小时聚合的请求/错误/成本趋势。"""
        data = read_json(BIN / 'go-metrics.json', {}) or {}
        buckets = data.get('buckets') or {}
        points = []
        for hour, bucket in sorted(buckets.items()):
            totals = {'requests': 0, 'ok': 0, 'err': 0, 'in_tokens': 0, 'out_tokens': 0, 'cost': 0.0}
            for st in (bucket.get('models') or {}).values():
                totals['requests'] += int(st.get('requests', 0) or 0)
                totals['ok'] += int(st.get('ok', 0) or 0)
                totals['err'] += int(st.get('err', 0) or 0)
                totals['in_tokens'] += int(st.get('prompt_tokens', 0) or 0)
                totals['out_tokens'] += int(st.get('completion_tokens', 0) or 0)
                totals['cost'] += float(st.get('cost_usd', 0.0) or 0.0)
            points.append({'hour': hour, **totals, 'cost': round(totals['cost'], 4)})
        points = points[-max(1, int(hours)):]
        totals = {
            'requests': sum(p['requests'] for p in points),
            'ok': sum(p['ok'] for p in points),
            'err': sum(p['err'] for p in points),
            'in_tokens': sum(p['in_tokens'] for p in points),
            'out_tokens': sum(p['out_tokens'] for p in points),
            'cost': round(sum(p['cost'] for p in points), 4),
        }
        return {'hours': hours, 'points': points, 'totals': totals}

    def simulate_route(self, model):
        """只读模拟一个模型名会匹配到哪条路由。"""
        model = (model or '').strip()
        cfg = read_json(BIN / 'go-routes.json', {}) or {}
        routes = cfg.get('routes') or []
        matched = False
        prefix = ''
        upstream_name = cfg.get('default_upstream', '')
        for r in routes:
            p = r.get('prefix') or ''
            if p and model.startswith(p):
                matched = True
                prefix = p
                upstream_name = r.get('upstream') or upstream_name
                break
        real_model = model[len(prefix):] if matched and prefix else model
        upstream = (cfg.get('upstreams') or {}).get(upstream_name) or {}
        key_file = BIN / (upstream.get('key_file') or '')
        return {
            'ok': bool(upstream_name and upstream),
            'input': model,
            'matched': matched,
            'prefix': prefix,
            'upstream': upstream_name,
            'label': upstream.get('label', upstream_name or '未匹配'),
            'base': upstream.get('base', ''),
            'real_model': real_model,
            'chat_only': real_model in _load_chat_only_names(),
            'use_proxy': upstream.get('use_proxy', True),
            'has_key': secret_available(key_file),
            'message': '命中 %s -> %s' % (prefix or '(默认)', upstream_name or '未配置'),
        }

    @_audited('reset_usage')
    def reset_usage(self):
        """把当前用量记为基线 —— 界面统计从此刻从 0 开始（网关原数据不动）。"""
        cur = read_json(BIN / 'go-usage.json', {}) or {}
        try:
            atomic_write_json(BIN / 'go-usage-baseline.json',
                              {'taken_at': time.time(), 'data': cur})
        except Exception as exc:
            return {'ok': False, 'msg': '%s: %s' % (type(exc).__name__, exc)}
        return {'ok': True, 'msg': '已清零，从此刻重新统计', 'usage': self.get_usage()}

    # ---- 告警与审计 ----
    ALERTS_FILE = BIN / 'relay-alerts.jsonl'
    AUDIT_FILE = BIN / 'relay-audit.jsonl'
    AUDIT_KEEP = 500

    def _audit(self, action, target='', detail=''):
        """记录配置/运维动作；不记录密钥值。"""
        rec = {
            'ts': time.strftime('%Y-%m-%d %H:%M:%S'),
            'action': action,
            'target': target,
            'detail': detail,
        }
        with _CONFIG_LOCK:
            try:
                with self.AUDIT_FILE.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                lines = tail(self.AUDIT_FILE, self.AUDIT_KEEP + 1)
                if len(lines) > self.AUDIT_KEEP:
                    atomic_write_text(self.AUDIT_FILE, '\n'.join(lines[-self.AUDIT_KEEP:]) + '\n')
            except Exception:
                pass

    def get_audit(self, limit=50):
        out = []
        try:
            for line in tail(self.AUDIT_FILE, int(limit)):
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
        except Exception:
            pass
        out.reverse()
        return {'events': out, 'count': len(out)}

    def get_alerts(self, limit=50):
        """只读告警文件尾部，避免长期运行后把整个 JSONL 读进内存。"""
        out = []
        try:
            for line in tail(self.ALERTS_FILE, int(limit)):
                line = line.strip()
                if not line: continue
                try: out.append(json.loads(line))
                except Exception: continue
        except Exception: pass
        out.reverse()
        return {'alerts': out, 'count': len(out)}
    def clear_alerts(self):
        try:
            if self.ALERTS_FILE.exists():
                self._backup(self.ALERTS_FILE)
                atomic_write_text(self.ALERTS_FILE, '')
        except Exception:
            pass
        if self._tray is not None:
            self._tray.clear_alert_notice()      # 托盘菜单里的"最新告警"同步清掉
        return {'ok': True}

    # ---- 诊断包 ----
    @staticmethod
    def _scrub(text):
        """脱敏：密钥打码 + 用户目录折叠。

        四层防护：
        1) sk-/lq-/sub- 前缀的密钥留首尾打码
        2) Bearer 头里的任意长 token
        3) JSON/env 里的 api_key/secret/token/password 字段值
        4) 用户目录路径折叠成 ~（诊断包发出去不暴露本机用户名）
        """
        def repl(m):
            s = m.group(0)
            if len(s) <= 10:
                return s[:2] + '*' * (len(s) - 2)
            return s[:6] + '*' * 10 + s[-4:]
        text = re.sub(r'\b(?:sk|lq|sub)-[A-Za-z0-9_\-]{12,}\b', repl, text)
        text = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_\-\.]{12,}',
                      lambda m: m.group(1) + '***', text)
        text = re.sub(r'(?i)((?:api[_-]?key|secret|token|password)["\']?\s*[:=]\s*["\']?)[^"\'\s,}]{8,}',
                      lambda m: m.group(1) + '***', text)
        home = str(Path.home())
        if home:
            text = text.replace(home, '~')
        return text

    def export_diagnostics(self):
        """把日志、配置、状态打包成 zip 放桌面，密钥自动打码。"""
        import zipfile

        ts = time.strftime('%Y%m%d-%H%M%S')
        desk = Path(os.path.expanduser('~')) / 'Desktop'
        out = desk / ('relay-diag-%s.zip' % ts)

        def tail_text(path, n=600):
            # 复用全局 seek 版 tail，大日志不再整文件读入内存
            lines = tail(path, n)
            return '\n'.join(lines) if lines else '(空或读取失败)'

        try:
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
                # 1) 系统与进程快照
                info = [
                    '生成时间: %s' % time.strftime('%Y-%m-%d %H:%M:%S'),
                    '平台: %s' % sys.platform,
                    'Python: %s' % sys.version.replace('\n', ' '),
                    'exe: %s' % ('已冻结' if getattr(sys, 'frozen', False) else '源码运行'),
                    '',
                    '--- 端口 ---',
                ]
                for port, label in [(GATEWAY_PORT, 'go_proxy'), (GEMINI_PORT, 'gemini-proxy'),
                                    (7897, '境外线路A'), (60696, '境外线路B')]:
                    info.append('  %-14s :%-6d %s' % (label, port, 'OPEN' if port_open(port) else 'CLOSED'))
                z.writestr('system.txt', '\n'.join(info))

                # 2) 健康快照
                try:
                    hz = OPENER.open('http://127.0.0.1:%d/healthz' % GATEWAY_PORT,
                                     timeout=8).read().decode('utf-8', 'replace')
                    z.writestr('healthz.json', hz)
                except Exception as exc:
                    z.writestr('healthz.json', json.dumps(
                        {'error': '%s: %s' % (type(exc).__name__, exc)}, ensure_ascii=False))

                # 3) 日志（尾部若干行）
                z.writestr('logs/go-proxy.log', tail_text(BIN / 'go-proxy.log', 800))
                z.writestr('logs/relay-watchdog.log', tail_text(BIN / 'relay-watchdog.log', 300))

                # 4) 配置（全部脱敏）
                for name in ['go-routes.json', 'chat-only-models.json', 'go-proxy.env', 'go-metrics.json', 'go-budget.json', 'relay-audit.jsonl']:
                    p = BIN / name
                    if p.exists():
                        try:
                            z.writestr('config/' + name, self._scrub(p.read_text(encoding='utf-8')))
                        except Exception:
                            pass
                if CATALOG.exists():
                    try:
                        z.writestr('config/wb-model-catalog.json',
                                   self._scrub(CATALOG.read_text(encoding='utf-8')))
                    except Exception:
                        pass
                if (BIN / 'go-usage.json').exists():
                    try:
                        z.writestr('config/go-usage.json',
                                   self._scrub((BIN / 'go-usage.json').read_text(encoding='utf-8')))
                    except Exception:
                        pass

                # 5) 自启与守护状态
                extra = []
                extra.append('Startup 目录内容:')
                try:
                    for f in sorted(os.listdir(STARTUP)):
                        extra.append('  ' + f)
                except Exception as exc:
                    extra.append('  (读取失败: %s)' % exc)
                extra.append('')
                extra.append('看门狗 pid = %s' % (
                    (BIN / 'relay-watchdog.pid').read_text(encoding='utf-8').strip()
                    if (BIN / 'relay-watchdog.pid').exists() else '(无)'))
                z.writestr('state.txt', '\n'.join(extra))

            size = out.stat().st_size / 1024
            return {'ok': True, 'path': str(out),
                    'msg': '诊断包已生成（%.0f KB）：%s' % (size, out.name)}
        except Exception as exc:
            return {'ok': False, 'msg': '%s: %s' % (type(exc).__name__, exc)}

    # ---- 开机自启 ----
    @_audited('set_autostart')
    def set_autostart(self, enabled):
        target = STARTUP / 'relay-watchdog.cmd'
        if enabled:
            content = ('@echo off\r\n'
                       'rem local AI relay watchdog autostart (login)\r\n'
                       'start "" "%s" "%s"\r\n' % (PYTHONW, BIN / 'relay-watchdog.py'))
            atomic_write_text(target, content, encoding='utf-8')
        else:
            try:
                target.unlink()
            except Exception:
                pass
        self._invalidate_status_cache()          # autostart 字段变了
        return {'ok': True, 'enabled': target.exists()}

    # ---- 其它 ----
    def open_folder(self, which='bin'):
        paths = {'bin': BIN, 'codex': CODEX_DIR, 'log': BIN}
        path = paths.get(which, BIN)
        subprocess.Popen(['explorer', str(path)], creationflags=NO_WINDOW)
        return {'ok': True}

    BACKUP_KEEP = 10          # 每个文件最多保留的历史备份份数

    def _backup(self, path: Path):
        """写前备份；同秒内多次修改也生成唯一文件，失败返回 False。"""
        try:
            if not path.exists(): return True
            stamp = time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
            (path.parent / ('%s.bak-%s' % (path.name, stamp))).write_text(
                path.read_text(encoding='utf-8'), encoding='utf-8')
            olds = sorted(path.parent.glob('%s.bak-*' % path.name), reverse=True)
            for f in olds[self.BACKUP_KEEP:]:
                try: f.unlink()
                except Exception: pass
            return True
        except Exception:
            return False

    def _safe_write_text(self, path: Path, text: str, encoding='utf-8'):
        with _CONFIG_LOCK:
            if not self._backup(path): raise OSError('备份失败，已阻止写入: %s' % path)
            atomic_write_text(path, text, encoding=encoding)

    def _safe_write_json(self, path: Path, data, validator=None):
        with _CONFIG_LOCK:
            if validator is not None: validator(data)
            if not self._backup(path): raise OSError('备份失败，已阻止写入: %s' % path)
            atomic_write_json(path, data)

    def _safe_write_secret(self, path: Path, text: str):
        self._safe_write_text(path, protect_secret_value(text))


def _acquire_single_instance() -> bool:
    """命名互斥量做单实例保护：已有实例在跑就返回 False。

    没有这层保护时，用户每双击一次快捷方式就会新开一整套窗口 + 一队
    WebView2 渲染进程（实测点 4 次 → 4 个实例 / 30 个 msedgewebview2）。
    """
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.CreateMutexW(None, False, 'Local\\RelayConsole_SingleInstance')
    if not handle:
        return True                      # 拿不到互斥量就别拦着用户
    if kernel32.GetLastError() == 183:   # ERROR_ALREADY_EXISTS
        ctypes.windll.user32.MessageBoxW(
            None,
            'Relay Console 已经在运行中。\n\n请到任务栏找它的窗口，不要重复启动。',
            'Relay Console', 0x40)
        return False
    _SINGLETON['handle'] = handle        # 持有引用，进程存活期间不释放
    return True


_SINGLETON = {}


def _resource(rel: str) -> str:
    """兼容 PyInstaller 冻结环境：解包资源在 sys._MEIPASS 下。"""
    base = getattr(sys, '_MEIPASS', str(Path(__file__).resolve().parent))
    return os.path.join(base, *rel.split('/'))


def main():
    if not _acquire_single_instance():
        sys.exit(0)

    # api 必须先于 window 构造，且通过 create_window(js_api=...) 注册 ——
    # pywebview 只在构造时读取该参数（存为私有 _js_api），事后赋值无效。
    api = Api()
    index = _resource('web/index.html')
    window = webview.create_window(
        'Relay Console — 本地 AI 网关',
        index,
        js_api=api,                     # ★ 必须在此处注册，否则前端拿不到任何接口
        width=1120, height=760, min_size=(900, 620),
        background_color='#0e1013',
    )

    # 托盘需要 window，故在窗口建好后回注给 api（仅用于同步图标状态）
    tray = TrayController(window, on_quit=window.destroy)
    api._tray = tray

    def on_closing():
        """关闭窗口时收进托盘继续后台运行；托盘不可用则按常规退出。"""
        if tray.available:
            window.hide()
            return False          # 返回 False 取消真正的关闭
        return True

    try:
        window.events.closing += on_closing
    except Exception:
        pass                       # 事件接口不可用就当没有托盘

    def setup(_window):
        tray.start()
        tray.start_alert_watch(str(Api.ALERTS_FILE))   # 看门狗新告警 -> 系统通知+图标变红

    webview.start(setup, window)


if __name__ == '__main__':
    main()
