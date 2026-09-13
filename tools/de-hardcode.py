# -*- coding: utf-8 -*-
"""一次性：把 tools/build.bat 里的本机硬编码路径改为脚本相对定位。"""
import io
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BS = chr(92)

# 1) smoke-frontend.py 补 Path import
p = ROOT / 'tools' / 'smoke-frontend.py'
s = p.read_text(encoding='utf-8')
if 'from pathlib import Path' not in s:
    s = s.replace('import sys', 'import sys\nfrom pathlib import Path', 1)
    p.write_text(s, encoding='utf-8', newline='\n')
    print('smoke-frontend: 已补 Path import')

# 2) privacy-audit.py 的 CWD 改相对
p = ROOT / 'tools' / 'privacy-audit.py'
s = p.read_text(encoding='utf-8')
old = "CWD = r'" + 'D:' + BS + 'Projects' + BS + "relay-console'"
new = "CWD = str(Path(__file__).resolve().parent.parent)"
if old in s:
    if 'from pathlib import Path' not in s:
        s = s.replace('import sys', 'import sys\nfrom pathlib import Path', 1)
    s = s.replace(old, new, 1)
    p.write_text(s, encoding='utf-8', newline='\n')
    print('privacy-audit: CWD 已改为相对')

# 3) build.bat 的 PY 改探测式
p = ROOT / 'build.bat'
s = p.read_text(encoding='utf-8', errors='replace')
old = 'set PY=' + 'D:' + BS + 'DeepSeek' + BS + 'venv' + BS + 'relaygui' + BS + 'Scripts' + BS + 'python.exe'
new = ('rem Python 解释器：优先项目 venv，其次 PATH\r\n'
       'set PY=venv' + BS + 'Scripts' + BS + 'python.exe\r\n'
       'if not exist "%PY%" set PY=python')
if old in s:
    s = s.replace(old, new, 1)
    p.write_text(s, encoding='utf-8', errors='replace', newline='\r\n')
    print('build.bat: PY 已改为探测式')
else:
    print('build.bat: 未找到目标行')

# 4) .gitignore 补 config.local.json 与过时工具
p = ROOT / '.gitignore'
s = p.read_text(encoding='utf-8')
add = []
for item in ['config.local.json',
             'tools/fix-hidden-windows.py',
             'tools/rebuild-shortcut.py',
             'tools/make-desktop-shortcut.py',
             'tools/verify-shortcut.py']:
    if item not in s:
        s += item + '\n'
        add.append(item)
if add:
    p.write_text(s, encoding='utf-8', newline='\n')
    print('gitignore: 已追加 %s' % ', '.join(add))
