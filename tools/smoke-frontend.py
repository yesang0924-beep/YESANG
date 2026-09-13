# -*- coding: utf-8 -*-
"""前端冒烟测试：用 pywebview 真实加载构建产物，检查 Vue 是否挂载成功。

只看构建成功不够 —— Vite 产物默认带 crossorigin，在 file:// 下可能被拦截，
必须在真实 webview 里 evaluate_js 才能确认。
"""
import json
import sys
from pathlib import Path
import threading
import time

import webview

INDEX = str(Path(__file__).resolve().parent.parent / 'web' / 'index.html')
RESULT = {'ok': False, 'detail': ''}


def probe(window):
    time.sleep(4)
    try:
        title = window.evaluate_js("document.querySelector('.hero-title')?.textContent || ''")
        cards = window.evaluate_js("document.querySelectorAll('.card').length")
        stats = window.evaluate_js("document.querySelectorAll('.stat').length")
        js_err = window.evaluate_js("window.__vueMounted === undefined ? '' : 'x'")
        RESULT.update(ok=bool(cards), detail=json.dumps(
            {'heroTitle': title, 'cards': cards, 'stats': stats},
            ensure_ascii=False))
    except Exception as exc:
        RESULT['detail'] = 'evaluate_js 失败: %s' % exc
    finally:
        window.destroy()


w = webview.create_window('smoke', INDEX, width=900, height=600)
webview.start(probe, w)

print('结果:', RESULT['detail'])
print('判定:', '✓ Vue 已挂载，页面渲染正常' if RESULT['ok'] else '✗ 页面未渲染（资源加载失败）')
sys.exit(0 if RESULT['ok'] else 1)
