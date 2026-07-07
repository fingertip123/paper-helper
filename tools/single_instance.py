#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨平台单实例锁 + 窗口唤醒 + 僵尸残留自愈。

固定用 127.0.0.1:18765 作为锁端口：
  · 第一个实例 bind 成功 → 成为主实例，并持续监听该端口；
    收到唤醒命令时回调把主窗口提到前台。
  · 后续实例 bind 失败 → 连接锁端口发唤醒命令：
      - 收到 OK：已有健康实例并已被唤醒 → 自身安静退出。
      - 连不上 / 无响应：判定为崩溃残留的僵尸进程 → 杀掉占用端口的进程后
        重新接管，避免"提示正在运行却看不到窗口"的死锁。
"""
import os
import sys
import time
import socket
import signal
import threading
import subprocess

lockhost = "127.0.0.1"
lockport = 18765

_locksock = None
_activatecallback = None
_pingtoken = b"PAPER-HELPER-SHOW"
_oktoken = b"PAPER-HELPER-OK"


def SetActivateCallback(fcallback):
    """主实例注册：收到唤醒命令时调用（应把主窗口提到前台）。"""
    global _activatecallback
    _activatecallback = fcallback


def _HandleConnection(oconn):
    try:
        oconn.settimeout(3)
        sdata = oconn.recv(64) or b""
        if sdata.strip() == _pingtoken:
            fcb = _activatecallback
            if fcb is not None:
                try:
                    fcb()
                except Exception:
                    pass
            oconn.sendall(_oktoken)
    except Exception:
        pass
    finally:
        try:
            oconn.close()
        except Exception:
            pass


def _ListenLoop(osock):
    while True:
        try:
            oconn, _ = osock.accept()
        except OSError:
            break
        threading.Thread(target=_HandleConnection, args=(oconn,), daemon=True).start()


def _NewLockSocket():
    osock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform.startswith("win"):
        # Windows：独占绑定，避免端口被其他进程劫持；
        # 切勿用 SO_REUSEADDR（在 Windows 上会允许多个进程共绑，破坏单实例语义）。
        nexcl = getattr(socket, "SO_EXCLUSIVEADDRUSE", 0x04)
        try:
            osock.setsockopt(socket.SOL_SOCKET, nexcl, 1)
        except OSError:
            pass
    return osock


def _TryBind():
    global _locksock
    osock = _NewLockSocket()
    try:
        osock.bind((lockhost, lockport))
        osock.listen(5)
    except OSError:
        osock.close()
        return False
    _locksock = osock
    othread = threading.Thread(target=_ListenLoop, args=(osock,), daemon=True)
    othread.start()
    return True


def _PingExisting():
    """连接已有实例并请求唤醒窗口。

    返回 True 仅当对方在限定时间内回了 OK（即确为健康实例）；
    能连上但无响应同样返回 False，以便上层判定为僵尸。
    """
    try:
        oclient = socket.create_connection((lockhost, lockport), timeout=2)
    except OSError:
        return False
    try:
        oclient.sendall(_pingtoken)
        oclient.settimeout(3)
        sresp = oclient.recv(64) or b""
        return _oktoken in sresp
    except OSError:
        return False
    finally:
        try:
            oclient.close()
        except Exception:
            pass


def _FindPortPids():
    """查找占用锁端口的进程 pid（用于清理崩溃残留）。"""
    vpids = []
    try:
        if sys.platform.startswith("win"):
            r = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True, text=True, timeout=10,
            )
            ssuffix = ":%d" % lockport
            for line in (r.stdout or "").splitlines():
                vparts = line.split()
                if len(vparts) >= 5 and vparts[0].upper() == "TCP" \
                        and vparts[1].endswith(ssuffix) and vparts[3].upper() == "LISTENING":
                    if vparts[-1].isdigit():
                        vpids.append(int(vparts[-1]))
        else:
            r = subprocess.run(
                ["lsof", "-nP", "-iTCP:%d" % lockport, "-sTCP:LISTEN", "-t"],
                capture_output=True, text=True, timeout=10,
            )
            for line in (r.stdout or "").splitlines():
                if line.strip().isdigit():
                    vpids.append(int(line.strip()))
    except Exception:
        pass
    return list(set(vpids))


def _KillStalePids(vpids):
    ncurrent = os.getpid()
    for npid in vpids:
        if npid <= 0 or npid == ncurrent:
            continue
        try:
            if sys.platform.startswith("win"):
                subprocess.run(
                    ["taskkill", "/PID", str(npid), "/F", "/T"],
                    capture_output=True, timeout=10,
                )
            else:
                os.kill(npid, signal.SIGKILL)
        except Exception:
            pass


def Acquire():
    """获取单实例锁。

    返回值：
      True  → 本进程为主实例，应继续启动。
      False → 已有健康实例并已被唤醒，本进程应安静退出。
      None  → 端口被占用且无法清理/接管，交由上层提示用户。
    """
    if _TryBind():
        return True

    # 端口被占用：先尝试唤醒已有实例
    if _PingExisting():
        return False

    # 无响应 → 视为崩溃残留的僵尸进程，清理后重新接管
    _KillStalePids(_FindPortPids())
    for _ in range(20):
        if _TryBind():
            return True
        time.sleep(0.25)

    # 清理期间对方若恢复，再给一次唤醒机会
    if _PingExisting():
        return False
    return None
