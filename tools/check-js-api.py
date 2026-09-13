# -*- coding: utf-8 -*-
"""静态检查：确认 webview.create_window 注册了 js_api。

背景：pywebview 只在 create_window() 构造时读取 js_api（存为私有 _js_api），
事后写 `window.js_api = api` 是**无效**的 —— 前端会拿不到任何接口，
表现为「状态读取失败 / 后端接口异常 / 一键修复没用」，但程序本身照常启动，
极难靠肉眼发现。此脚本用 AST 静态断言，防止重构时再次踩坑。
"""
import ast
import sys
from pathlib import Path

APP = str(Path(__file__).resolve().parent.parent / 'app.py')


def find_create_window(tree):
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # 匹配 webview.create_window(...)
        if (isinstance(func, ast.Attribute)
                and func.attr == 'create_window'):
            hits.append(node)
    return hits


def main():
    src = open(APP, encoding='utf-8').read()
    tree = ast.parse(src)
    calls = find_create_window(tree)

    if not calls:
        print('✗ 未找到 webview.create_window 调用')
        return 1

    ok = True
    for i, call in enumerate(calls, 1):
        kwargs = {kw.arg for kw in call.keywords}
        has = 'js_api' in kwargs
        print('create_window #%d：关键字参数 = %s' % (i, sorted(kwargs)))
        print('  js_api 已注册？ %s' % ('是 ✓' if has else '否 ✗ ← 前端将无法调用任何接口'))
        ok = ok and has

    # 反向检查：不应存在事后赋值 window.js_api = ...
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Attribute)
                and node.targets[0].attr == 'js_api'):
            bad.append(node.lineno)
    if bad:
        print('✗ 发现无效的事后赋值 window.js_api（第 %s 行）—— pywebview 不认，必须改为构造参数'
              % bad)
        ok = False
    else:
        print('无 window.js_api 事后赋值 ✓')

    print()
    print('判定:', '✓ 通过' if ok else '✗ 未通过')
    return 0 if ok else 1


if __name__ == '__main__':
    sys.exit(main())
