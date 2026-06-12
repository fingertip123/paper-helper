#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PySide6 桌面窗口启动器。

开启窗口的同时在后台线程启动本地 HTTP 服务，窗口内通过 QWebEngine
复用现有 Web 界面（论文库 / 知识图谱 / 设置）。不经浏览器，不依赖终端。
"""
import os
import sys
import socket
import threading
import webbrowser
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as appmod
import wiki_core as core
import single_instance as si

from PySide6.QtCore import QUrl, Qt, QObject, Slot, QMetaObject
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView


def FindFreePort(nprefer):
    """优先使用首选端口；被占用时由系统分配一个空闲端口。"""
    osock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        osock.bind((appmod.host, nprefer))
        osock.close()
        return nprefer
    except OSError:
        osock.close()
    osock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    osock.bind((appmod.host, 0))
    nport = osock.getsockname()[1]
    osock.close()
    return nport


def StartServer(nport):
    """后台线程启动 HTTP 服务（复用 app.py 的 Handler）。构造完成即已监听。"""
    appmod.port = nport
    appmod.desktopmode = True
    core.GenerateIndex()
    oserver = ThreadingHTTPServer((appmod.host, nport), appmod.Handler)
    othread = threading.Thread(target=oserver.serve_forever, daemon=True)
    othread.start()
    return oserver


def IsLocalUrl(oqurl):
    shost = (oqurl.host() or "").lower()
    return shost in ("127.0.0.1", "localhost", "::1") or shost.startswith("127.")


def OpenExternalUrl(oqurl):
    if oqurl.scheme() not in ("http", "https"):
        return False
    if IsLocalUrl(oqurl):
        return False
    webbrowser.open(oqurl.toString())
    return True


def MakeWebPage(oview):
    """创建 Web 页并拦截外部链接（勿子类化 QWebEnginePage，PySide6 会崩溃）。"""
    opage = QWebEnginePage(QWebEngineProfile.defaultProfile(), oview)

    def OnNavigation(orequest):
        if OpenExternalUrl(orequest.url()):
            orequest.reject()

    def OnNewWindow(orequest):
        if OpenExternalUrl(orequest.requestedUrl()):
            return
        orequest.openIn(opage)

    opage.navigationRequested.connect(OnNavigation)
    opage.newWindowRequested.connect(OnNewWindow)
    return opage


class FolderPickerBridge(QObject):
    """主线程文件夹对话框（供 PickFolderNative 备用）。"""

    def __init__(self, owin):
        super().__init__()
        self._owin = owin

    @Slot(result=str)
    def PickFolder(self):
        return QFileDialog.getExistingDirectory(self._owin, "选择导出文件夹") or ""


def PickFolderBlocking(opicker):
    from PySide6.QtCore import Q_RETURN_ARG
    spath = ""
    QMetaObject.invokeMethod(
        opicker,
        "PickFolder",
        Qt.BlockingQueuedConnection,
        Q_RETURN_ARG(str, spath),
    )
    return spath or ""


class MainWindow(QMainWindow):
    def __init__(self, nurl):
        super().__init__()
        self.setWindowTitle("博士论文 Wiki · Paper-Helper")
        self.resize(1280, 860)
        oview = QWebEngineView(self)
        oview.setPage(MakeWebPage(oview))
        oview.settings().setAttribute(QWebEngineSettings.WebAttribute.PdfViewerEnabled, True)
        oview.settings().setAttribute(QWebEngineSettings.WebAttribute.PluginsEnabled, True)
        oview.load(QUrl(nurl))
        self.setCentralWidget(oview)

    @Slot()
    def ActivateWindow(self):
        """被第二次启动的实例唤醒：把窗口从最小化/后台提到前台。"""
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.raise_()
        self.activateWindow()


def Main():
    nport = FindFreePort(appmod.port)
    StartServer(nport)
    nurl = "http://%s:%d/" % (appmod.host, nport)

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    oapp = QApplication(sys.argv)
    oapp.setApplicationName("Paper-Helper")
    oapp.setQuitOnLastWindowClosed(True)

    viconpaths = []
    if getattr(sys, "frozen", False):
        nbase = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
        viconpaths.append(os.path.join(nbase, "assets", "icon.icns"))
        viconpaths.append(os.path.join(nbase, "assets", "icon.png"))
    viconpaths.extend([
        os.path.join(core.rootdir, "assets", "icon.icns"),
        os.path.join(core.rootdir, "assets", "icon.png"),
    ])
    for sicon in viconpaths:
        if os.path.isfile(sicon):
            oapp.setWindowIcon(QIcon(sicon))
            break

    owin = MainWindow(nurl)
    opicker = FolderPickerBridge(owin)
    appmod.desktop_pick_folder = lambda: PickFolderBlocking(opicker)

    # 第二个实例请求唤醒时，跨线程安全地把窗口提到前台
    def RequestActivate():
        QMetaObject.invokeMethod(owin, "ActivateWindow", Qt.QueuedConnection)

    si.SetActivateCallback(RequestActivate)
    owin.show()
    sys.exit(oapp.exec())


if __name__ == "__main__":
    Main()
