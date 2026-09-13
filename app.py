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
import time
import urllib.error
import urllib.request
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
CODEX_DIR = Path(_CFG['codex_dir'])
CATALOG = Path(_CFG['catalog_path'])
CONFIG_TOML = CODEX_DIR / 'config.toml'
STARTUP = Path(os.environ['APPDATA']) / r'Microsoft\Windows\Start Menu\Programs\Startup'
PYTHONW = _CFG['pythonw']
PM2 = _CFG['pm2_cmd']
RUNTIME_PY = _CFG['runtime_python']
DETACHED, NEWGRP, NO_WINDOW = 0x00000008, 0x00000200, 0x08000000
OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # 强制直连，避开宿主 HTTP_PROXY


def run_hidden(args, timeout=None):
    """带 CREATE_NO_WINDOW 的 subprocess.run。

    GUI 进程里凡是调 netstat / tasklist / taskkill / pm2 这类控制台程序，
    不加这个标志就会**每次调用都闪一个黑窗口**（本程序早前版本正是因此
    被用户看到「动不动就弹黑窗」）。
    """
    return subprocess.run(args, capture_output=True, text=True, errors='replace',
                          timeout=timeout, creationflags=NO_WINDOW)

GATEWAY_PORT = 18047
GEMINI_PORT = 18045
UPSTREAM_LABELS = {'go': 'OpenCode Go', 'local': 'Local Relay',
                   'yh': 'Yoshub', 'yhds': 'Yoshub DeepSeek'}
UPSTREAM_PROBE = {'go': 'go/deepseek-v4.1-flash', 'local': 'local/gemini-3.7-flash',
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
    try:
        data = path.read_text(encoding='utf-8', errors='replace').splitlines()
        return data[-lines:]
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


def kill_pids(pids):
    for pid in pids:
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

    # ---- 状态 ----
    def get_status(self):
        watch_pid_file = BIN / 'relay-watchdog.pid'
        watch_pid = watch_pid_file.read_text(encoding='utf-8').strip() if watch_pid_file.exists() else ''
        gem_pids = pid_listening(GEMINI_PORT)
        return {
            'time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'ports': [
                {'port': GATEWAY_PORT, 'name': 'go_proxy', 'desc': 'OpenCode Go 返代',
                 'up': port_open(GATEWAY_PORT)},
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

    def get_health(self):
        """整体健康度总评 —— 驱动界面顶部那条傻瓜式大横幅。"""
        st = self.get_status()
        gateway_up = st['ports'][0]['up']
        gemini_up = st['ports'][1]['up']
        watchdog_up = st['watchdog']['alive']
        proxy_up = any(p['up'] for p in st['proxy_ports'])

        problems = []
        if not gateway_up:
            problems.append('模型网关（18047）没在运行 —— Codex 现在无法调用任何模型')
        elif not watchdog_up:
            problems.append('守护进程没在运行 —— 网关一旦挂掉不会自动恢复')
        if not gemini_up:
            problems.append('本地 Gemini 反代（18045）没在运行 —— [Local] 组 3 个模型不可用')
        if not proxy_up:
            problems.append('没检测到境外线路（你的代理软件没开）—— 访问 OpenCode Go / Yoshub 会走直连，可能变慢或超时')

        if not gateway_up:
            level = 'fail'
        elif problems:
            level = 'warn'
        else:
            level = 'ok'

        # 顺手让托盘图标配色跟随健康状态
        if self._tray is not None:
            self._tray.set_level(level)

        return {'level': level, 'problems': problems, 'status': st}

    def one_click(self):
        """一键修复：把能自动处理的问题全部处理掉。"""
        actions = []
        st = self.get_status()
        if not st['ports'][0]['up']:
            spawn_detached([PYTHONW, str(BIN / 'go_proxy.py')])
            actions.append('启动模型网关')
        if not st['watchdog']['alive']:
            try:
                (BIN / 'relay-watchdog.pid').unlink()
            except Exception:
                pass
            spawn_detached([PYTHONW, str(BIN / 'relay-watchdog.py')])
            actions.append('启动守护进程')
        if not st['ports'][1]['up']:
            try:
                run_hidden(['cmd', '/c', PM2, 'restart', 'gemini-proxy'], timeout=120)
                actions.append('重启本地 Gemini 反代')
            except Exception:
                pass
        time.sleep(5)
        return {'actions': actions or ['一切正常，无需修复'], 'health': self.get_health()}

    def test_upstreams(self):
        results = []
        for key, model in UPSTREAM_PROBE.items():
            body = json.dumps({'model': model,
                               'input': [{'role': 'user',
                                          'content': [{'type': 'input_text', 'text': 'hi'}]}],
                               'max_output_tokens': 16}).encode()
            req = urllib.request.Request('http://127.0.0.1:%d/v1/responses' % GATEWAY_PORT,
                                         data=body,
                                         headers={'Content-Type': 'application/json',
                                                  'Authorization': 'Bearer x'})
            entry = {'key': key, 'label': UPSTREAM_LABELS.get(key, key), 'model': model}
            try:
                OPENER.open(req, timeout=45)
                entry.update(state='ok', detail='')
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode('utf-8', 'replace')[:80]
                entry.update(state='warn' if exc.code in (429, 503) else 'fail',
                             detail='HTTP %s %s' % (exc.code, detail))
            except Exception as exc:
                entry.update(state='fail', detail=type(exc).__name__)
            results.append(entry)
        return results

    # ---- 启停 ----
    def start_all(self):
        started = []
        if not port_open(GATEWAY_PORT):
            spawn_detached([PYTHONW, str(BIN / 'go_proxy.py')])
            started.append('go_proxy')
        pid_file = BIN / 'relay-watchdog.pid'
        pid = pid_file.read_text(encoding='utf-8').strip() if pid_file.exists() else ''
        if not process_alive(pid):
            try:
                pid_file.unlink()
            except Exception:
                pass
            spawn_detached([PYTHONW, str(BIN / 'relay-watchdog.py')])
            started.append('relay-watchdog')
        time.sleep(4)
        return {'started': started, 'status': self.get_status()}

    def stop_all(self):
        kill_pids(pid_listening(GATEWAY_PORT))
        pid_file = BIN / 'relay-watchdog.pid'
        pid = pid_file.read_text(encoding='utf-8').strip() if pid_file.exists() else ''
        if process_alive(pid):
            run_hidden(['taskkill', '/PID', pid, '/F'])
        try:
            pid_file.unlink()
        except Exception:
            pass
        time.sleep(1)
        return {'status': self.get_status()}

    def restart_gateway(self):
        kill_pids(pid_listening(GATEWAY_PORT))
        time.sleep(1)
        spawn_detached([PYTHONW, str(BIN / 'go_proxy.py')])
        for _ in range(15):
            time.sleep(1)
            if port_open(GATEWAY_PORT):
                break
        return {'status': self.get_status()}

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

    def remove_model(self, slug):
        data = read_json(CATALOG, {'models': []}) or {'models': []}
        before = len(data.get('models', []))
        data['models'] = [m for m in data.get('models', []) if m.get('slug') != slug]
        if len(data['models']) == before:
            return {'ok': False, 'msg': '未找到该模型'}
        self._backup(CATALOG)
        CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'ok': True, 'msg': '已移除 %s' % slug, 'models': self.get_models()}

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
        self._backup(CATALOG)
        CATALOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        return {'ok': True, 'msg': '已添加 %s' % slug, 'models': self.get_models()}

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
                key = kf.read_text(encoding='utf-8').strip()
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
        models = [{'id': i, 'slug': prefix + i, 'in_pool': (prefix + i) in pool,
                   'known_chat_only': i in CHAT_ONLY_NAMES} for i in ids]
        return {'ok': True, 'upstream': name, 'label': up.get('label', name),
                'prefix': prefix, 'total': len(models), 'models': models}

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
        body = json.dumps({'model': slug,
                           'input': [{'role': 'user',
                                      'content': [{'type': 'input_text',
                                                   'text': 'reply with exactly: PONG'}]}],
                           'max_output_tokens': 200}).encode()
        req = urllib.request.Request('http://127.0.0.1:%d/v1/responses' % GATEWAY_PORT,
                                     data=body,
                                     headers={'Content-Type': 'application/json',
                                              'Authorization': 'Bearer x'})
        try:
            resp = OPENER.open(req, timeout=120)
            data = json.loads(resp.read().decode())
            text = ''
            for item in (data.get('output') or []):
                for c in (item.get('content') or []):
                    if c.get('type') == 'output_text':
                        text += c.get('text', '')
            return {'ok': True, 'text': (text or '(空响应)')[:400]}
        except urllib.error.HTTPError as exc:
            return {'ok': False, 'text': 'HTTP %s %s' % (
                exc.code, exc.read().decode('utf-8', 'replace')[:300])}
        except Exception as exc:
            return {'ok': False, 'text': '%s: %s' % (type(exc).__name__, exc)}

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
                'has_key': bool(key_file.exists() and key_file.read_text(encoding='utf-8').strip()),
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
                    key = kf.read_text(encoding='utf-8').strip()
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
            self._backup(kf) if kf.exists() else None
            kf.write_text(key.strip(), encoding='utf-8')
            up['key_file'] = kf_name
            changed.append('密钥')

        if not changed:
            return {'ok': False, 'msg': '没有需要修改的内容'}

        self._backup(path)
        path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
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
                    key = kf.read_text(encoding='utf-8').strip()
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

    def get_usage(self):
        data = read_json(BIN / 'go-usage.json', {}) or {}
        models = []
        for name, st in (data.get('models') or {}).items():
            models.append({
                'model': name,
                'requests': st.get('requests', 0),
                'ok': st.get('ok', 0),
                'err': st.get('err_429', 0) + st.get('err_network', 0) + st.get('err_other', 0),
                'in_tokens': st.get('prompt_tokens', 0),
                'out_tokens': st.get('completion_tokens', 0),
                'cost': round(st.get('cost_usd', 0.0), 4),
            })
        models.sort(key=lambda x: x['requests'], reverse=True)
        return {'since': data.get('started', 0), 'models': models}

    # ---- 告警 ----
    ALERTS_FILE = BIN / 'relay-alerts.jsonl'

    def get_alerts(self, limit=50):
        """读取看门狗写下的告警（自愈失败才会记）。"""
        out = []
        try:
            if self.ALERTS_FILE.exists():
                lines = self.ALERTS_FILE.read_text(encoding='utf-8').splitlines()
                for line in lines[-int(limit):]:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        continue
        except Exception:
            pass
        out.reverse()          # 最新的在前
        return {'alerts': out, 'count': len(out)}

    def clear_alerts(self):
        try:
            if self.ALERTS_FILE.exists():
                self._backup(self.ALERTS_FILE)
                self.ALERTS_FILE.write_text('', encoding='utf-8')
        except Exception:
            pass
        return {'ok': True}

    # ---- 诊断包 ----
    @staticmethod
    def _scrub(text):
        """脱敏：把 sub-xxx / sk-xxx / lq-xxx 这类密钥打码，只留首尾。"""
        def repl(m):
            s = m.group(0)
            if len(s) <= 10:
                return s[:2] + '*' * (len(s) - 2)
            return s[:6] + '*' * 10 + s[-4:]
        return re.sub(r'\b(?:sk|lq|sub)-[A-Za-z0-9_\-]{12,}\b', repl, text)

    def export_diagnostics(self):
        """把日志、配置、状态打包成 zip 放桌面，密钥自动打码。"""
        import zipfile

        ts = time.strftime('%Y%m%d-%H%M%S')
        desk = Path(os.path.expanduser('~')) / 'Desktop'
        out = desk / ('relay-diag-%s.zip' % ts)

        def tail_text(path, n=600):
            try:
                lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
                return '\n'.join(lines[-n:])
            except Exception as exc:
                return '(读取失败: %s)' % exc

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
                for name in ['go-routes.json', 'chat-only-models.json', 'go-proxy.env']:
                    p = BIN / name
                    if p.exists():
                        try:
                            z.writestr('config/' + name, self._scrub(p.read_text(encoding='utf-8')))
                        except Exception:
                            pass
                if CATALOG.exists():
                    try:
                        z.writestr('config/wb-model-catalog.json',
                                   CATALOG.read_text(encoding='utf-8'))
                    except Exception:
                        pass
                if (BIN / 'go-usage.json').exists():
                    try:
                        z.writestr('config/go-usage.json',
                                   (BIN / 'go-usage.json').read_text(encoding='utf-8'))
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
    def set_autostart(self, enabled):
        target = STARTUP / 'relay-watchdog.cmd'
        if enabled:
            content = ('@echo off\r\n'
                       'rem local AI relay watchdog autostart (login)\r\n'
                       'start "" "%s" "%s"\r\n' % (PYTHONW, BIN / 'relay-watchdog.py'))
            target.write_text(content, encoding='ascii', newline='')
        else:
            try:
                target.unlink()
            except Exception:
                pass
        return {'ok': True, 'enabled': target.exists()}

    # ---- 其它 ----
    def open_folder(self, which='bin'):
        paths = {'bin': BIN, 'codex': CODEX_DIR, 'log': BIN}
        path = paths.get(which, BIN)
        subprocess.Popen(['explorer', str(path)], creationflags=NO_WINDOW)
        return {'ok': True}

    def _backup(self, path: Path):
        try:
            stamp = time.strftime('%Y%m%d-%H%M%S')
            (path.parent / ('%s.bak-%s' % (path.name, stamp))).write_text(
                path.read_text(encoding='utf-8'), encoding='utf-8')
        except Exception:
            pass


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

    webview.start(setup, window)


if __name__ == '__main__':
    main()
