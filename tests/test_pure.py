# -*- coding: utf-8 -*-
"""纯函数单元测试：_mask / _scrub / tail / _backup 修剪 / _pick_probe_model / 状态缓存。

运行（项目根目录）：
    uv run --with pytest python -m tests.test_pure -v
或装好 pytest 后：
    python -m pytest tests -q

注意：import app 会读项目根的 config.local.json（模块级配置加载），
该文件缺失时 app 会弹窗退出 —— 本测试假定在本机开发环境运行。
"""
import json
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# 测试环境不装 pywebview；app.py 顶部 import 它但纯函数用不到，打个桩
sys.modules.setdefault('webview', types.ModuleType('webview'))

import app  # noqa: E402


# ---------------------------------------------------------------- _mask
class TestMask:
    def test_empty(self):
        assert app.Api._mask('') == ''
        assert app.Api._mask(None) == ''
        assert app.Api._mask('   ') == ''

    def test_short_key_keeps_head2(self):
        assert app.Api._mask('ab1234') == 'ab****'

    def test_long_key_keeps_head5_tail4(self):
        k = 'sk-abcdefgh12345678'
        masked = app.Api._mask(k)
        assert masked == 'sk-ab********5678'
        assert k[5:-4] not in masked


# ---------------------------------------------------------------- _scrub
class TestScrub:
    def test_masks_key_patterns(self):
        out = app.Api._scrub('Authorization: Bearer sk-abcdef1234567890xyz')
        assert 'abcdef1234567890' not in out
        assert out.startswith('Authorization: Bearer sk-abc')

    def test_multiple_prefixes(self):
        text = 'sk-aaaaaaaabbbbbbbb lq-ccccccccdddddddd sub-eeeeeeeeffffffff'
        out = app.Api._scrub(text)
        assert 'aaaaaaaabbbbbbbb' not in out
        assert 'ccccccccdddddddd' not in out
        assert 'eeeeeeeeffffffff' not in out

    def test_normal_text_untouched(self):
        text = '2026-09-14 request ok, model=go/deepseek-v4.1-flash'
        assert app.Api._scrub(text) == text


# ---------------------------------------------------------------- tail（seek 倒读）
class TestTail:
    def test_last_n_lines(self, tmp_path):
        p = tmp_path / 'x.log'
        p.write_text('\n'.join('line-%d' % i for i in range(1000)), encoding='utf-8')
        assert app.tail(p, 10) == ['line-%d' % i for i in range(990, 1000)]

    def test_missing_file_returns_empty(self, tmp_path):
        assert app.tail(tmp_path / 'nope.log') == []

    def test_empty_file(self, tmp_path):
        p = tmp_path / 'empty.log'
        p.write_text('', encoding='utf-8')
        assert app.tail(p, 10) == []

    def test_long_lines_trigger_chunk_growth(self, tmp_path):
        # 单行 ~500B 时首块（50*240=12000B）只装得下 ~23 行，必须自动扩块
        p = tmp_path / 'big.log'
        p.write_text('\n'.join('x' * 500 + '-%d' % i for i in range(200)), encoding='utf-8')
        lines = app.tail(p, 50)
        assert len(lines) == 50
        assert lines[-1].endswith('-199')
        assert lines[0].endswith('-150')

    def test_fewer_lines_than_requested(self, tmp_path):
        p = tmp_path / 'short.log'
        p.write_text('a\nb\nc', encoding='utf-8')
        assert app.tail(p, 100) == ['a', 'b', 'c']


# ---------------------------------------------------------------- _backup 修剪
class TestBackupPrune:
    def test_keeps_only_recent_n(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app.Api, 'BACKUP_KEEP', 2)
        api = app.Api()
        target = tmp_path / 'cfg.json'
        target.write_text('{}', encoding='utf-8')
        for _ in range(4):
            api._backup(target)
            time.sleep(1.05)          # 备份文件名精度到秒，错开时间戳
        baks = sorted(tmp_path.glob('cfg.json.bak-*'))
        assert len(baks) == 2

    def test_backup_content_matches(self, tmp_path):
        api = app.Api()
        target = tmp_path / 'cfg.json'
        target.write_text('{"a": 1}', encoding='utf-8')
        api._backup(target)
        baks = list(tmp_path.glob('cfg.json.bak-*'))
        assert len(baks) == 1
        assert baks[0].read_text(encoding='utf-8') == '{"a": 1}'


# ---------------------------------------------------------------- 原子写入/唯一备份
class TestSafeWrite:
    def test_same_second_backups_are_unique(self, tmp_path):
        api = app.Api()
        target = tmp_path / 'cfg.json'
        target.write_text('{}', encoding='utf-8')
        api._backup(target)
        target.write_text('{"changed": true}', encoding='utf-8')
        api._backup(target)
        assert len(list(tmp_path.glob('cfg.json.bak-*'))) == 2

    def test_atomic_json_write_has_no_temp_left(self, tmp_path):
        target = tmp_path / 'catalog.json'
        app.atomic_write_json(target, {'models': [{'slug': 'go/test'}]})
        assert app.read_json(target)['models'][0]['slug'] == 'go/test'
        assert not list(tmp_path.glob('catalog.json.*.tmp'))

    def test_safe_catalog_write_rejects_bad_shape(self, tmp_path):
        api = app.Api()
        target = tmp_path / 'catalog.json'
        target.write_text('{"models": []}', encoding='utf-8')
        try:
            api._safe_write_json(target, {'models': 'bad'}, app._validate_catalog)
        except ValueError:
            pass
        else:
            raise AssertionError('bad catalog shape was accepted')
        assert app.read_json(target) == {'models': []}


# ---------------------------------------------------------------- _pick_probe_model
class TestPickProbeModel:
    def test_picks_first_matching_slug(self, tmp_path, monkeypatch):
        cat = tmp_path / 'cat.json'
        cat.write_text(json.dumps({'models': [{'slug': 'yh/some-model'},
                                              {'slug': 'go/other'}]}), encoding='utf-8')
        monkeypatch.setattr(app, 'CATALOG', cat)
        assert app._pick_probe_model('yh') == 'yh/some-model'

    def test_fallback_when_catalog_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'CATALOG', tmp_path / 'none.json')
        assert app._pick_probe_model('yh') == app.UPSTREAM_PROBE_FALLBACK['yh']

    def test_yhds_not_confused_with_yh(self, tmp_path, monkeypatch):
        # 前缀带斜杠：yhds/ 不应被 yh/ 匹配走
        cat = tmp_path / 'cat.json'
        cat.write_text(json.dumps({'models': [{'slug': 'yhds/deepseek-x'}]}), encoding='utf-8')
        monkeypatch.setattr(app, 'CATALOG', cat)
        assert app._pick_probe_model('yh') == app.UPSTREAM_PROBE_FALLBACK['yh']
        assert app._pick_probe_model('yhds') == 'yhds/deepseek-x'


# ---------------------------------------------------------------- 状态缓存
class TestStatusCache:
    def _stubbed_api(self, monkeypatch, calls):
        monkeypatch.setattr(app, 'run_hidden',
                            lambda *a, **k: types.SimpleNamespace(stdout=''))
        monkeypatch.setattr(app, 'http_ok', lambda *a, **k: True)
        monkeypatch.setattr(app, 'port_open',
                            lambda *a, **k: calls.append(a[0]) or True)
        return app.Api()

    def test_second_call_within_ttl_hits_cache(self, monkeypatch):
        calls = []
        api = self._stubbed_api(monkeypatch, calls)
        api.get_status()
        first = len(calls)
        assert first == 3                      # gemini + 两条境外线路（网关走 http_ok）
        api.get_status()                       # TTL 内应直接吃缓存
        assert len(calls) == first

    def test_invalidation_forces_refresh(self, monkeypatch):
        calls = []
        api = self._stubbed_api(monkeypatch, calls)
        api.get_status()
        api._invalidate_status_cache()
        api.get_status()
        assert len(calls) == 6

    def test_cache_expires_after_ttl(self, monkeypatch):
        calls = []
        api = self._stubbed_api(monkeypatch, calls)
        api._status_cache_ttl = 0.05
        api.get_status()
        time.sleep(0.06)
        api.get_status()
        assert len(calls) == 6


# ---------------------------------------------------------------- 上游并行实测
class TestUpstreamsParallel:
    def test_parallel_order_and_latency(self, monkeypatch):
        import time as _t
        monkeypatch.setattr(app, '_pick_probe_model', lambda k: k + '/probe')

        def slow_open(*a, **k):
            _t.sleep(0.3)          # 每路固定耗时，验证并行总耗时 < 串行之和
            return types.SimpleNamespace()

        monkeypatch.setattr(app.OPENER, 'open', slow_open)
        api = app.Api()
        t0 = _t.monotonic()
        rs = api.test_upstreams()
        elapsed = _t.monotonic() - t0

        assert [r['key'] for r in rs] == list(app.UPSTREAM_LABELS)   # 结果顺序不乱
        assert all(r['state'] == 'ok' for r in rs)
        assert all(isinstance(r['latency_ms'], int) and r['latency_ms'] >= 200 for r in rs)
        assert elapsed < 0.9         # 串行要 1.2s+，并行应远小于此


# ---------------------------------------------------------------- 托盘告警解析
class TestTrayAlertParsing:
    def _tray(self):
        import tray
        return tray.TrayController(window=None, on_quit=None)

    def test_json_line_becomes_summary(self):
        t = self._tray()
        t._on_alert_line('{"ts":"12:00","target":"gateway","detail":"restart failed"}')
        assert t._latest_alert == '12:00 gateway · restart failed'

    def test_bad_json_kept_verbatim(self):
        t = self._tray()
        t._on_alert_line('boom')
        assert t._latest_alert == 'boom'

    def test_blank_line_ignored(self):
        t = self._tray()
        t._on_alert_line('   ')
        assert t._latest_alert is None

    def test_summary_truncated_to_60(self):
        t = self._tray()
        t._on_alert_line('{"ts":"","target":"t","detail":"' + 'x' * 200 + '"}')
        assert len(t._latest_alert) <= 60

    def test_clear_notice_resets(self):
        t = self._tray()
        t._on_alert_line('{"target":"t","detail":"d"}')
        t.clear_alert_notice()
        assert t._latest_alert is None


# ---------------------------------------------------------------- 第二轮可观测性
class TestRound2Observability:
    def test_route_simulation(self, tmp_path, monkeypatch):
        (tmp_path / 'go.key').write_text('x', encoding='utf-8')
        (tmp_path / 'go-routes.json').write_text(json.dumps({
            'upstreams': {'go': {'label': 'Go', 'base': 'http://upstream',
                                  'key_file': 'go.key', 'use_proxy': True}},
            'routes': [{'prefix': 'go/', 'upstream': 'go'}],
            'default_upstream': 'go',
        }), encoding='utf-8')
        monkeypatch.setattr(app, 'BIN', tmp_path)
        r = app.Api().simulate_route('go/deepseek-v4.1-flash')
        assert r['ok'] and r['upstream'] == 'go'
        assert r['real_model'] == 'deepseek-v4.1-flash'
        assert r['has_key'] is True

    def test_hourly_metrics(self, tmp_path, monkeypatch):
        (tmp_path / 'go-metrics.json').write_text(json.dumps({
            'version': 1,
            'buckets': {
                '2026-09-15T01': {'models': {'go/a': {'requests': 2, 'ok': 1, 'err': 1,
                                                       'prompt_tokens': 10, 'completion_tokens': 20,
                                                       'cost_usd': 0.01}}},
                '2026-09-15T02': {'models': {'go/a': {'requests': 1, 'ok': 1, 'err': 0,
                                                       'prompt_tokens': 5, 'completion_tokens': 7,
                                                       'cost_usd': 0.02}}},
            },
        }), encoding='utf-8')
        monkeypatch.setattr(app, 'BIN', tmp_path)
        m = app.Api().get_metrics(24)
        assert len(m['points']) == 2
        assert m['totals']['requests'] == 3 and m['totals']['err'] == 1

    def test_audit_roundtrip(self, tmp_path):
        api = app.Api()
        api.AUDIT_FILE = tmp_path / 'audit.jsonl'
        api._audit('add_model', 'go/test', 'ok')
        events = api.get_audit(10)['events']
        assert events and events[0]['action'] == 'add_model'
        assert events[0]['target'] == 'go/test'


# ---------------------------------------------------------------- 第三轮安全与治理
class TestRound3SecurityAndBudget:
    def test_secret_store_roundtrip(self, tmp_path):
        target = tmp_path / 'key.txt'
        app.secret_store.write_secret(target, 'sk-secret-value')
        assert app.secret_store.read_secret(target) == 'sk-secret-value'
        assert target.read_text(encoding='utf-8').startswith('dpapi:')

    def test_budget_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'BIN', tmp_path)
        monkeypatch.setattr(app, 'BUDGET_FILE', tmp_path / 'go-budget.json')
        (tmp_path / 'go-metrics.json').write_text(json.dumps({'version': 1, 'buckets': {}}), encoding='utf-8')
        api = app.Api()
        r = api.set_budget(1.5, 8)
        assert r['ok'] is True
        assert api.get_budget()['hourly_usd'] == 1.5
        assert api.get_budget()['daily_usd'] == 8

    def test_error_summary_classifies_rate_limit(self, tmp_path, monkeypatch):
        monkeypatch.setattr(app, 'BIN', tmp_path)
        (tmp_path / 'go-proxy.log').write_text('2026-09-15 ERROR HTTP 429 rate_limit_exceeded\n', encoding='utf-8')
        items = app.Api().get_error_summary()['items']
        assert items and items[0]['category'] == 'rate_limit'


# ---------------------------------------------------------------- 模型排序/改名
class TestModelOps:
    def _catalog(self, tmp_path, monkeypatch, models):
        p = tmp_path / 'cat.json'
        p.write_text(json.dumps({'models': models}), encoding='utf-8')
        monkeypatch.setattr(app, 'CATALOG', p)
        return p

    def test_move_swaps_and_renumbers(self, tmp_path, monkeypatch):
        p = self._catalog(tmp_path, monkeypatch,
                          [{'slug': 'a', 'priority': 5},
                           {'slug': 'b', 'priority': 5},
                           {'slug': 'c', 'priority': 5}])
        api = app.Api()
        r = api.move_model('c', 'up')
        assert r['ok']
        assert [m['slug'] for m in r['models']] == ['a', 'c', 'b']
        saved = json.loads(p.read_text(encoding='utf-8'))
        pris = sorted(m['priority'] for m in saved['models'])
        assert pris == [1, 2, 3]                 # priority 被归一化

    def test_move_at_edge_is_noop(self, tmp_path, monkeypatch):
        self._catalog(tmp_path, monkeypatch,
                      [{'slug': 'a', 'priority': 1}, {'slug': 'b', 'priority': 2}])
        api = app.Api()
        r = api.move_model('a', 'up')
        assert r['ok'] and '边缘' in r['msg']
        assert [m['slug'] for m in r['models']] == ['a', 'b']

    def test_rename_writes_display_name(self, tmp_path, monkeypatch):
        p = self._catalog(tmp_path, monkeypatch, [{'slug': 'a', 'priority': 1}])
        api = app.Api()
        r = api.rename_model('a', '新名字')
        assert r['ok']
        saved = json.loads(p.read_text(encoding='utf-8'))
        assert saved['models'][0]['display_name'] == '新名字'

    def test_rename_missing_slug(self, tmp_path, monkeypatch):
        self._catalog(tmp_path, monkeypatch, [{'slug': 'a'}])
        assert not app.Api().rename_model('nope', 'x')['ok']

    def test_rename_empty_rejected(self, tmp_path, monkeypatch):
        self._catalog(tmp_path, monkeypatch, [{'slug': 'a'}])
        assert not app.Api().rename_model('a', '   ')['ok']


# ---------------------------------------------------------------- 用量基线
class TestUsageBaseline:
    def _usage_file(self, tmp_path, monkeypatch):
        usage = tmp_path / 'go-usage.json'
        usage.write_text(json.dumps({
            'started': 1,
            'models': {'m1': {'requests': 10, 'ok': 9, 'err_429': 1,
                              'prompt_tokens': 100, 'completion_tokens': 50,
                              'cost_usd': 0.5}},
        }), encoding='utf-8')
        monkeypatch.setattr(app, 'BIN', tmp_path)
        return usage

    def test_reset_then_zero(self, tmp_path, monkeypatch):
        usage = self._usage_file(tmp_path, monkeypatch)
        api = app.Api()
        assert api.get_usage()['models'][0]['requests'] == 10
        r = api.reset_usage()
        assert r['ok']
        after = api.get_usage()
        assert after['models'][0]['requests'] == 0
        assert after['models'][0]['cost'] == 0
        assert after['since'] > 1
        # 网关原始数据文件不被清零动作改动
        assert json.loads(usage.read_text(encoding='utf-8'))['models']['m1']['requests'] == 10

    def test_new_counts_after_reset_still_show(self, tmp_path, monkeypatch):
        usage = self._usage_file(tmp_path, monkeypatch)
        api = app.Api()
        api.reset_usage()
        data = json.loads(usage.read_text(encoding='utf-8'))
        data['models']['m1']['requests'] = 13
        data['models']['m1']['cost_usd'] = 0.8
        usage.write_text(json.dumps(data), encoding='utf-8')
        after = api.get_usage()
        assert after['models'][0]['requests'] == 3
        assert abs(after['models'][0]['cost'] - 0.3) < 1e-9


# ---------------------------------------------------------------- _scrub 加固
class TestScrubHardening:
    def test_bearer_token_masked(self):
        out = app.Api._scrub('Authorization: Bearer abcdefgh12345678ijkl')
        assert 'abcdefgh12345678' not in out
        assert 'Bearer ***' in out

    def test_json_key_fields_masked(self):
        out = app.Api._scrub('{"api_key": "abcd1234efgh5678", "name": "x"}')
        assert 'abcd1234efgh5678' not in out

    def test_env_key_fields_masked(self):
        out = app.Api._scrub('API_KEY=abcd1234efgh5678')
        assert 'abcd1234efgh5678' not in out

    def test_token_count_fields_not_masked(self):
        # max_output_tokens / prompt_tokens 这类计数字段不能被误伤
        text = '"max_output_tokens": 16384, "prompt_tokens": 999'
        assert app.Api._scrub(text) == text

    def test_home_dir_folded(self):
        from pathlib import Path as _P
        out = app.Api._scrub(str(_P.home()) + '\\bin\\go_proxy.py')
        assert str(_P.home()) not in out
        assert out.startswith('~')


# ------------------------------- 重启网关：只发一次停机（2026-09-16 事故回归）
class TestRestartGatewaySingleShutdown:
    """回归 2026-09-16 双绑事故。

    事实：网关侧的 `/admin/shutdown` **不是"停掉"，而是"排干旧的 + 派生一个新实例
    接管"**（go_proxy 的 `_respawn_self`，为了让重启不留空窗）。所以：
      * `restart_gateway` 必须**只发一次**停机，然后等新实例接管；
      * 原实现额外在 `_stop_gateway_wait` 里又发了一次 → 两次停机 = 派生两个实例
        → 实测 18047 上两个 PID 同时 LISTENING（熔断/缓存/用量被劈成两份）。
    """

    class _Stub:
        """不是 Api 子类 —— 用 Api.__new__ 造一个不走 __init__ 的真实实例。"""

        @classmethod
        def make(cls, replaced=True):
            st = app.Api.__new__(app.Api)
            st.calls = []
            st._start_gateway_wait = lambda timeout=25: (st.calls.append('start'), True)[1]
            st._stop_gateway_wait = lambda timeout=25: (st.calls.append('stop_wait'), (True, 'x'))[1]
            st._invalidate_status_cache = lambda: None
            st.get_status = lambda: {'ok': True}
            st._wait_gateway_replaced = lambda before, timeout=40: replaced
            return st

    def _patch(self, monkeypatch, health_seq):
        monkeypatch.setattr(app, 'pause_watchdog', lambda *a, **k: None)
        monkeypatch.setattr(app, 'resume_watchdog', lambda *a, **k: None)
        seq = list(health_seq)

        def _h(timeout=2.0):
            return seq.pop(0) if seq else (health_seq[-1] if health_seq else {})

        monkeypatch.setattr(app, 'gateway_health', _h)
        shutdowns = []

        def _sd(timeout=5.0):
            shutdowns.append(1)
            return True, 'HTTP 202'

        monkeypatch.setattr(app, 'request_gateway_shutdown', _sd)
        return shutdowns

    def test_只发一次停机(self, monkeypatch):
        """核心断言：多发一次停机就会多派生一个实例（双绑）。"""
        shutdowns = self._patch(
            monkeypatch, [{'ok': True, 'uptime_s': 500, 'singleton': {'pid': 111}}])
        out = app.Api.restart_gateway(self._Stub.make(replaced=True))
        assert len(shutdowns) == 1, (
            'restart_gateway 发了 %d 次 /admin/shutdown —— 网关每次都会派生新实例，'
            '发两次就会双绑' % len(shutdowns))
        assert out['ok'] is True

    def test_新实例接管后不再兜底启动(self, monkeypatch):
        """已经有新实例接管时，不该再 spawn 一个（否则就是双实例）。"""
        self._patch(monkeypatch, [{'ok': True, 'uptime_s': 500, 'singleton': {'pid': 111}}])
        st = self._Stub.make(replaced=True)
        app.Api.restart_gateway(st)
        assert st.calls == [], '已接管却仍执行了 %s' % st.calls

    def test_未接管时兜底启动(self, monkeypatch):
        """确实没有新实例时才兜底启动（此时网关侧单实例锁会拒绝多余的那次）。"""
        self._patch(monkeypatch, [{'ok': True, 'uptime_s': 500, 'singleton': {'pid': 111}}])
        st = self._Stub.make(replaced=False)
        out = app.Api.restart_gateway(st)
        assert st.calls == ['start'], '应当且只应当兜底启动一次，实际 %s' % st.calls
        assert out['ok'] is True


class TestWaitGatewayReplaced:
    """`_wait_gateway_replaced` 的判据：pid 变化优先，退而用「uptime 很小」。"""

    def test_pid变化即判定已接管(self, monkeypatch):
        seq = [{'ok': True, 'singleton': {'pid': 111}},
               {'ok': True, 'singleton': {'pid': 222}}]

        def _h(timeout=2.0):
            return seq.pop(0) if seq else {'ok': True, 'singleton': {'pid': 222}}

        monkeypatch.setattr(app, 'gateway_health', _h)
        assert app.Api._wait_gateway_replaced(None, {'singleton': {'pid': 111}},
                                              timeout=5) is True

    def test_pid未变则超时(self, monkeypatch):
        monkeypatch.setattr(app, 'gateway_health',
                            lambda timeout=2.0: {'ok': True, 'singleton': {'pid': 111}})
        monkeypatch.setattr(app.time, 'sleep', lambda *_a: None)
        assert app.Api._wait_gateway_replaced(None, {'singleton': {'pid': 111}},
                                              timeout=0.3) is False

    def test_拿不到pid时退回uptime判据(self, monkeypatch):
        monkeypatch.setattr(app, 'gateway_health',
                            lambda timeout=2.0: {'ok': True, 'uptime_s': 3})
        assert app.Api._wait_gateway_replaced(None, {}, timeout=2) is True
