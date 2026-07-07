#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""云端多用户服务入口（Render / Koyeb / VPS / Docker 通用）。

环境变量：
    PORT                  监听端口（默认 8765）
    HOST                  监听地址（默认 0.0.0.0）
    YANZHAN_DATA_DIR      用户数据根目录（默认 <项目根>/data；生产环境务必指向持久盘）
    YANZHAN_MULTIUSER     是否启用多用户登录（默认 1；设 0 退化为单用户公开实例）
    YANZHAN_LLM_DAILY     共享内置 Key 时每用户每日 LLM 调用上限（默认 60，0 = 不限）

启动：python3 tools/server.py
"""
import os
import sys
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as appmod  # noqa: E402
import auth  # noqa: E402
import wiki_core as core  # noqa: E402
import job_state  # noqa: E402


def Setup():
    sdataroot = os.environ.get("YANZHAN_DATA_DIR") or os.path.join(core.rootdir, "data")
    appmod.multiuser = os.environ.get("YANZHAN_MULTIUSER", "1") != "0"
    appmod.llmdailylimit = int(os.environ.get("YANZHAN_LLM_DAILY", "60"))
    appmod.host = os.environ.get("HOST", "0.0.0.0")
    appmod.port = int(os.environ.get("PORT", "8765"))
    if not appmod.multiuser and appmod.host not in ("127.0.0.1", "localhost", "::1"):
        print("错误：单用户模式（YANZHAN_MULTIUSER=0）不允许绑定公网地址。")
        print("请设置 YANZHAN_MULTIUSER=1 启用登录，或将 HOST 设为 127.0.0.1。")
        sys.exit(1)
    if appmod.multiuser:
        auth.Init(sdataroot, appmod.baseroot)
        job_state.SetMultiuserMode(True)
    else:
        job_state.SetMultiuserMode(False)
    return sdataroot


def Main():
    sdataroot = Setup()
    oserver = ThreadingHTTPServer((appmod.host, appmod.port), appmod.Handler)
    print("研栈云端服务已启动：%s:%d（多用户：%s，数据目录：%s）" % (
        appmod.host, appmod.port, "开" if appmod.multiuser else "关", sdataroot))
    try:
        oserver.serve_forever()
    except KeyboardInterrupt:
        oserver.shutdown()


if __name__ == "__main__":
    Main()
