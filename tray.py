# -*- coding: utf-8 -*-
"""系统托盘支持：关闭主窗口时收进托盘继续在后台跑，而不是退出。

设计要点
- 图标用 Pillow 现画，不依赖任何外部图片资源（打包更省事）
- pystray 跑在守护线程里，避免和 pywebview 的主线程消息循环打架
- **整块逻辑容错**：托盘起不来只影响"最小化到托盘"这一功能，
  主窗口该能开能关，不能让托盘把程序带崩
"""
import threading

ICON_NAME = 'relay_console'


def _draw_icon(level='ok'):
    """画一个方角图标：底色随状态变化，中间一个圆点。"""
    from PIL import Image, ImageDraw

    bg = {
        'ok': (34, 197, 94),      # 绿：一切正常
        'warn': (245, 158, 11),   # 黄：有隐患
        'fail': (239, 68, 68),    # 红：服务没跑
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

    # ---- 对外 ----
    def start(self):
        """启动托盘线程；失败则静默降级（available=False）。"""
        try:
            import pystray
        except Exception:
            return False
        try:
            menu = pystray.Menu(
                pystray.MenuItem('显示主窗口', self._show, default=True),
                pystray.MenuItem('隐藏到托盘', self._hide),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem('退出', self._quit),
            )
            self.icon = pystray.Icon(ICON_NAME, _draw_icon(self._level),
                                     'Relay Console · 本地 AI 网关', menu)
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

    # ---- 内部 ----
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
