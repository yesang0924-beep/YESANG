# -*- coding: utf-8 -*-
"""隐私审计：扫描 git 仓库（当前文件 + 全部历史提交）中的敏感信息。

检查项：
  1) API 密钥形态（sk- / lq- / sub- 开头的长串）
  2) Bearer 令牌
  3) C:\\Users\\<用户名> 路径 —— 泄露 Windows 用户名
  4) 本机项目路径（D:\\DeepSeek 等）—— 泄露目录结构
  5) 邮箱
  6) 公网/内网 IP（127.0.0.1 与 0.0.0.0 除外）
"""
import io
import re
import subprocess
import sys
from pathlib import Path

CWD = str(Path(__file__).resolve().parent.parent)

PATTERNS = [
    ('API密钥',   r'\b(?:sk|lq|sub)-[A-Za-z0-9_\-]{12,}'),
    ('Bearer令牌', r'Bearer\s+[A-Za-z0-9_\-.]{16,}'),
    ('用户名路径', r'[Cc]:[\\/]+[Uu]sers[\\/]+[A-Za-z0-9_\-]+'),
    ('D盘项目路径', r'[Dd]:[\\/]+(?:DeepSeek|Projects|Antigravity|Obsidian|Telegram)[^\s"\'<>]*'),
    ('邮箱',      r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}'),
    ('IP地址',    r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b'),
]


def git(args):
    r = subprocess.run(['git'] + args, capture_output=True, text=True,
                       errors='replace', cwd=CWD, creationflags=0x08000000)
    return r.stdout


def scan(text, where, out):
    for label, pat in PATTERNS:
        for m in re.finditer(pat, text):
            s = m.group(0)
            if label == 'IP地址' and (s.startswith('127.0.0.1') or s.startswith('0.0.0.0')):
                continue
            if label == '邮箱' and ('@local' in s or 'users.noreply' in s):
                # 本地占位邮箱（user@local 形态）与 GitHub noreply 地址不算泄露
                pass
            out.append((label, where, s))


def main():
    files = [f for f in git(['ls-files']).splitlines() if f.strip()]
    commits = [c.split()[0] for c in
               git(['log', '--format=%H']).splitlines() if c.strip()]

    print('仓库文件 %d 个，历史提交 %d 个' % (len(files), len(commits)))
    print()

    # ---------- 1) 当前 HEAD ----------
    print('=== 1) 当前版本（HEAD）文件内容 ===')
    hits = []
    for f in files:
        t = git(['show', 'HEAD:' + f])
        scan(t, f, hits)
    if hits:
        for label, where, s in hits:
            print('  [%s] %s -> %s' % (label, where, s[:80]))
        print('  命中 %d 处' % len(hits))
    else:
        print('  ✓ 无命中')

    # ---------- 2) 全部历史 ----------
    print()
    print('=== 2) 全部历史提交（逐提交扫描全部文件） ===')
    hhits = []
    for c in commits:
        msg = git(['log', '-1', '--format=%s', c]).strip()
        changed = [l for l in git(['show', '--name-only', '--format=', c]).splitlines() if l.strip()]
        for f in changed:
            t = git(['show', '%s:%s' % (c, f)])
            before = len(hhits)
            scan(t, '%s @ %s' % (f, c[:7]), hhits)
            if len(hhits) > before:
                for label, where, s in hhits[before:]:
                    print('  [%s] %s -> %s' % (label, where, s[:80]))
    if not hhits:
        print('  ✓ 历史中无敏感内容')
    else:
        print('  历史命中 %d 处' % len(hhits))

    # ---------- 3) 提交元数据（作者名/邮箱） ----------
    print()
    print('=== 3) 提交作者信息（会公开显示在 GitHub） ===')
    for line in git(['log', '--format=%an <%ae>']).splitlines():
        if line.strip():
            print('  ' + line.strip())

    print()
    print('=== 结论 ===')
    if not hits and not hhits:
        print('  文件内容层面未发现密钥/令牌泄露。')
    else:
        print('  存在命中项，见上方列表 —— 需要处理。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
