# -*- coding: utf-8 -*-
"""系统托盘支持：关闭主窗口时收进托盘继续在后台跑，而不是退出。

设计要点
- 图标用 Pillow 现画，不依赖任何外部图片资源（打包更省事）
- pystray 跑在守护线程里，避免和 pywebview 的主线程消息循环打架
- **整块逻辑容错**：托盘起不来只影响"最小化到托盘"这一功能，
  主窗口该能开能关，不能让托盘把程序带崩
- 告警闭环：盯看门狗的 relay-alerts.jsonl，新告警弹系统通知（pystray 的
  notify 在 Win10+ 上就是系统 toast，零新增依赖）+ 图标变红 + 菜单留痕
"""
import json
import os
import threading
import time

ICON_NAME = 'relay_console'


def _draw_icon(level='ok'):
    """画一个方角图标：底色随状态变化，中间一个圆点。"""
    from PIL import Image, ImageDraw

    bg = {
        'ok': (34, 197, 94),      # 绿：一切正常
        'warn': (245, 158, 11),   # 黄：有隐患
        'fail': (239, 68, 68),    # 红：服务没跑 / 有未处理告警
    }.get(level, (99, 102, 241))

    size = 64
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((2, 2, size - 3, size - 3), radius=16, fill=bg + (255,))
    d.ellipse((20, 20, 44, 44), fill=(255, 255, 255, 255))
    d.ellipse((28, 28, 36, 36), fill=bg + (255,))
    return img


class TrayController:
    """托盘控制器：持有 icon 引用，供主程序查询是否可用。"""

    def __init__(self, window, on_quit):
        self.window = window
        self.on_quit = on_quit
        self.icon = None
        self.available = False
        self._level = 'ok'
        self._pystray = None           # 模块引用，重建菜单时还要用
        self._latest_alert = None      # 最新一条告警的简述（显示在托盘菜单）
        self._alert_thread = None

    # ---- 对外 ----
    def start(self):
        """启动托盘线程；失败则静默降级（available=False）。"""
        try:
            import pystray
        except Exception:
            return False
        try:
            self._pystray = pystray
            self.icon = pystray.Icon(ICON_NAME, _draw_icon(self._level),
                                     'Relay Console · 本地 AI 网关', self._make_menu())
            threading.Thread(target=self._run, daemon=True).start()
            self.available = True
            return True
        except Exception:
            self.icon = None
            self.available = False
            return False

    def set_level(self, level):
        """状态变化时刷新图标配色（绿/黄/红）。"""
        if not self.available or level == self._level:
            return
        try:
            self._level = level
            self.icon.icon = _draw_icon(level)
        except Exception:
            pass

    def start_alert_watch(self, alerts_file, poll=5):
        """盯看门狗的告警文件：有新告警就弹系统通知 + 图标变红 + 菜单留痕。

        只处理增量 —— 启动时先记下文件尾，历史告警不刷屏通知；
        文件被清空（前端"知道了"）时 offset 自动归零重来。
        """
        if not self.available or self._alert_thread is not None:
            return False

        def loop():
            try:
                offset = os.path.getsize(alerts_file)
            except OSError:
                offset = 0
            while self.available:
                try:
                    size = os.path.getsize(alerts_file)
                    if size < offset:
                        offset = 0                      # 文件被清空/重建
                    if size > offset:
                        with open(alerts_file, 'rb') as f:
                            f.seek(offset)
                            data = f.read()
                            offset = f.tell()
                        for line in data.decode('utf-8', 'replace').splitlines():
                            self._on_alert_line(line)
                except Exception:
                    pass                                # 任何异常都不许弄死监听线程
                time.sleep(poll)

        self._alert_thread = threading.Thread(target=loop, daemon=True)
        self._alert_thread.start()
        return True

    def clear_alert_notice(self):
        """前端清空告警后，同步清掉托盘菜单里的留痕。"""
        self._latest_alert = None
        self._rebuild_menu()

    # ---- 内部 ----
    def _make_menu(self):
        pystray = self._pystray
        return pystray.Menu(
            pystray.MenuItem('显示主窗口', self._show, default=True),
            pystray.MenuItem('隐藏到托盘', self._hide),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('最新告警：' + (self._latest_alert or '（无）'),
                             None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem('退出', self._quit),
        )

    def _rebuild_menu(self):
        if not (self.available and self.icon and self._pystray):
            return
        try:
            self.icon.menu = self._make_menu()
        except Exception:
            pass

    def _on_alert_line(self, line):
        line = (line or '').strip()
        if not line:
            return
        try:
            a = json.loads(line)
            text = '%s · %s' % (a.get('target') or '?', a.get('detail') or '')
            ts = a.get('ts') or ''
        except Exception:
            text, ts = line, ''
        self._latest_alert = ('%s %s' % (ts, text)).strip()[:60]
        try:
            if self.icon:
                self.icon.notify(text[:200] or '看门狗有新告警', 'Relay Console 告警')
        except Exception:
            pass
        self.set_level('fail')          # 图标变红（前端清告警后由健康检查刷回）
        self._rebuild_menu()

    def _run(self):
        try:
            self.icon.run()
        except Exception:
            self.available = False

    def _show(self, icon=None, item=None):
        try:
            self.window.show()
        except Exception:
            pass

    def _hide(self, icon=None, item=None):
        try:
            self.window.hide()
        except Exception:
            pass

    def _quit(self, icon=None, item=None):
        try:
            if self.icon:
                self.icon.stop()
        except Exception:
            pass
        self.available = False
        try:
            self.on_quit()
        except Exception:
            pass
