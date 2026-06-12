#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Paper-Helper 统一程序入口（macOS / Windows / Linux）。

检测依赖 → 系统原生弹窗确认 → 自动安装 → 启动桌面窗口。
由 Paper-Helper.app（mac）或 Paper-Helper.vbs（win）调用，不经终端。
"""
import os
import sys
import subprocess
import importlib.util

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
toolsdir = os.path.join(rootdir, "tools")
sys.path.insert(0, toolsdir)

import single_instance as si  # noqa: E402

vrequired = [
    ("PySide6", "PySide6"),
    ("PySide6.QtWebEngineWidgets", "PySide6"),
    ("pdfminer", "pdfminer.six"),
    ("docx", "python-docx"),
]


def CheckModule(nmodname):
    try:
        return importlib.util.find_spec(nmodname) is not None
    except (ModuleNotFoundError, ValueError, ImportError):
        return False


def MissingPackages():
    vmissing = []
    vseen = set()
    for nmod, npkg in vrequired:
        if not CheckModule(nmod) and npkg not in vseen:
            vmissing.append(npkg)
            vseen.add(npkg)
    return vmissing


def IsGuiMode():
    return os.environ.get("PAPER_HELPER_GUI") == "1"


def AcquireSingleInstance():
    """单实例锁：健康实例会被唤醒到前台；崩溃残留的僵尸进程会被自动清理后接管。"""
    nresult = si.Acquire()
    if nresult is True:
        return True
    if nresult is False:
        # 已有健康实例并已被唤醒到前台，本进程安静退出
        return False
    NativeAlert(
        "Paper-Helper",
        "应用可能已在运行，但无法唤醒窗口。\n\n"
        "请在任务管理器（Windows）或活动监视器（macOS）中\n"
        "结束所有 python / pythonw 进程后，重新启动。",
        "caution",
    )
    return False


def SavePythonPath():
    """记住可用的 Python 路径，供 .app 下次启动时优先选用（避免 Finder PATH 过窄）。"""
    try:
        confdir = os.path.join(rootdir, ".paper-helper")
        os.makedirs(confdir, exist_ok=True)
        with open(os.path.join(confdir, "python.path"), "w", encoding="utf-8") as f:
            f.write(sys.executable)
    except Exception:
        pass


def SetupGuiLogging():
    """GUI 模式将 stdout/stderr 写入日志文件，避免依赖终端。"""
    if sys.platform == "darwin":
        logdir = os.path.join(os.path.expanduser("~"), "Library", "Logs", "Paper-Helper")
    elif sys.platform.startswith("win"):
        logdir = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Paper-Helper", "logs")
    else:
        logdir = os.path.join(os.path.expanduser("~"), ".paper-helper", "logs")
    os.makedirs(logdir, exist_ok=True)
    logpath = os.path.join(logdir, "launch.log")
    flog = open(logpath, "a", encoding="utf-8")
    sys.stdout = flog
    sys.stderr = flog
    print("\n--- Paper-Helper 启动 %s ---" % __import__("datetime").datetime.now())


def EscAppleScript(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def NativeConfirm(stitle, smsg):
    if sys.platform == "darwin":
        scpt = (
            'display dialog "%s" with title "%s" '
            'buttons {"取消", "安装"} default button "安装" with icon note'
        ) % (EscAppleScript(smsg), EscAppleScript(stitle))
        r = subprocess.run(["osascript", "-e", scpt], capture_output=True, text=True)
        return r.returncode == 0 and "安装" in (r.stdout or "")
    if sys.platform.startswith("win"):
        import ctypes
        nret = ctypes.windll.user32.MessageBoxW(0, smsg, stitle, 0x00000004 | 0x00000020)
        return nret == 6
    try:
        r = subprocess.run(
            ["zenity", "--question", "--title=" + stitle, "--text=" + smsg, "--ok-label=安装", "--cancel-label=取消"],
            capture_output=True,
        )
        return r.returncode == 0
    except FileNotFoundError:
        print("%s\n%s" % (stitle, smsg))
        return input("输入 y 确认安装，其他键取消：").strip().lower() in ("y", "yes", "是")


def NativeAlert(stitle, smsg, nicon="note"):
    if sys.platform == "darwin":
        scpt = 'display alert "%s" message "%s" as %s' % (
            EscAppleScript(stitle), EscAppleScript(smsg), nicon,
        )
        subprocess.run(["osascript", "-e", scpt], capture_output=True)
        return
    if sys.platform.startswith("win"):
        import ctypes
        nflags = 0x00000040
        if nicon == "stop":
            nflags = 0x00000010
        elif nicon == "caution":
            nflags = 0x00000030
        ctypes.windll.user32.MessageBoxW(0, smsg, stitle, nflags)
        return
    try:
        subprocess.run(["zenity", "--info", "--title=" + stitle, "--text=" + smsg], capture_output=True)
    except FileNotFoundError:
        print("%s: %s" % (stitle, smsg))


def NativeNotify(stitle, smsg):
    if sys.platform == "darwin":
        scpt = 'display notification "%s" with title "%s"' % (EscAppleScript(smsg), EscAppleScript(stitle))
        subprocess.Popen(["osascript", "-e", scpt])
    elif sys.platform.startswith("win"):
        try:
            subprocess.Popen([
                "powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                '[System.Reflection.Assembly]::LoadWithPartialName("System.Windows.Forms") | Out-Null; '
                '[System.Windows.Forms.MessageBox]::Show("%s","%s")' % (
                    smsg.replace('"', '`"'), stitle.replace('"', '`"'),
                ),
            ])
        except Exception:
            pass


def ShowInstallWait():
    """仅发系统通知，不用空白按钮对话框（避免用户误关导致后台 pip 与界面状态不一致）。"""
    NativeNotify(
        "Paper-Helper",
        "正在安装依赖，请稍候约 1–3 分钟…\n安装完成后将自动打开窗口。",
    )


def PrintInstallBanner(vmissing):
    if IsGuiMode():
        return
    print()
    print("=" * 52)
    print("  Paper-Helper · 正在安装依赖")
    print("=" * 52)
    print("  缺少：%s" % "、".join(vmissing))
    print("  下方将显示 pip 下载/安装进度条，请稍候…")
    print("=" * 52)
    print()
    sys.stdout.flush()


def PipInstall():
    reqpath = os.path.join(rootdir, "requirements.txt")
    if not os.path.isfile(reqpath):
        return False, "未找到 requirements.txt"
    base = [
        sys.executable, "-m", "pip", "install", "-r", reqpath,
        "--disable-pip-version-check", "--progress-bar", "on",
    ]
    vlasterr = ""
    bgui = IsGuiMode()
    for vextra in ([], ["--user"], ["--break-system-packages"], ["--user", "--break-system-packages"]):
        if not bgui:
            print(">>> pip 安装（%s）…" % ("默认" if not vextra else " ".join(vextra)))
            sys.stdout.flush()
        try:
            # GUI 模式下 stdout 已重定向到日志，保留 pip 输出便于排查
            r = subprocess.run(base + vextra)
        except Exception as e:
            vlasterr = str(e)
            if not bgui:
                print(">>> 失败：%s\n" % e)
            continue
        if r.returncode == 0 and not MissingPackages():
            if not bgui:
                print("✓ 所有依赖已就绪。\n")
            return True, ""
        vlasterr = "pip 退出码 %d" % r.returncode
    return False, vlasterr


def RunDesktop():
    sys.path.insert(0, toolsdir)
    import desktop
    desktop.Main()


def IsFrozen():
    return getattr(sys, "frozen", False)


def SetupFrozenRuntime():
    """打包环境运行前的修复：确保 HTTPS 证书可用。

    打包后 stdlib ssl 默认 CA 路径指向构建机，目标机往往不存在，
    会导致调用大模型 API 时 urlopen 抛证书错误。这里优先用 certifi 的
    CA 包，让分析功能在任意机器上都能正常联网。
    """
    try:
        import certifi
        scacert = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", scacert)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", scacert)
    except Exception:
        pass


def Main():
    if not AcquireSingleInstance():
        sys.exit(0)

    if IsGuiMode() or IsFrozen():
        SetupGuiLogging()

    if IsFrozen():
        SetupFrozenRuntime()
        RunDesktop()
        return

    vmissing = MissingPackages()
    if not vmissing:
        SavePythonPath()
        RunDesktop()
        return

    smsg = (
        "检测到缺少运行环境：\n\n"
        + "\n".join("  · %s" % p for p in vmissing)
        + "\n\n是否自动安装？\n（需联网，首次约 1–3 分钟）"
    )
    if not NativeConfirm("Paper-Helper · 缺少依赖", smsg):
        NativeAlert("Paper-Helper", "已取消。安装依赖后可重新启动应用。")
        sys.exit(0)

    ShowInstallWait()
    PrintInstallBanner(vmissing)

    bok, serr = PipInstall()
    if not bok:
        NativeAlert(
            "Paper-Helper · 安装失败",
            "自动安装未成功，请手动在终端执行：\n\n"
            "%s -m pip install -r requirements.txt\n\n"
            "错误：%s" % (sys.executable, serr),
            "stop",
        )
        sys.exit(1)

    vmissing = MissingPackages()
    if vmissing:
        NativeAlert(
            "Paper-Helper · 安装未完成",
            "依赖仍未就绪：%s\n\n当前 Python：\n%s\n\n请在终端执行：\n%s -m pip install -r requirements.txt"
            % ("、".join(vmissing), sys.executable, sys.executable),
            "stop",
        )
        sys.exit(1)

    SavePythonPath()
    NativeAlert("Paper-Helper", "依赖安装完成，正在启动应用…")
    RunDesktop()


if __name__ == "__main__":
    Main()
