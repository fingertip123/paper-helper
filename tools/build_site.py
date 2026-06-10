#!/usr/bin/env python3
"""生成自包含的静态可视化页面 wiki-viewer.html（可离线 file:// 打开，只读浏览）。

用法：
    python3 tools/build_site.py

注意：静态页面的「添加/分析/刷新」按钮被隐藏；要在网页里进行这些操作，
请改用本地服务：双击 start.command（或运行 python3 tools/app.py）。
所有扫描与渲染逻辑复用 wiki_core，避免重复。
"""

from wiki_core import Main

if __name__ == "__main__":
    Main()
