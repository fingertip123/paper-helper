#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多用户模式：注册 / 登录 / 会话 / 每用户数据目录（SQLite，轻量无第三方依赖）。

仅在云端多用户部署（tools/server.py，YANZHAN_MULTIUSER=1）时启用；
桌面 / 本地单用户模式完全不经过本模块。

数据布局：
    <dataroot>/users.db            用户与会话
    <dataroot>/u-<uid>/            每个用户独立的数据根（topics/、.yanzhan/ 等）
"""
import os
import re
import time
import hmac
import json
import shutil
import sqlite3
import secrets
import hashlib
import threading
from datetime import datetime

SESSION_COOKIE = "yz_session"
SESSION_DAYS = 30
PBKDF2_ITERS = 200_000

_dataroot = ""
_baseroot = ""  # 主项目根：用于给新用户复制 templates/
_dblock = threading.Lock()
_loginfail = {}  # ip -> [fail_count, window_start]


def Init(ndataroot, nbaseroot=""):
    global _dataroot, _baseroot
    _dataroot = ndataroot
    _baseroot = nbaseroot or ""
    os.makedirs(_dataroot, exist_ok=True)
    with _Db() as odb:
        odb.executescript(
            "CREATE TABLE IF NOT EXISTS users("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " username TEXT UNIQUE NOT NULL,"
            " pwhash BLOB NOT NULL, salt BLOB NOT NULL,"
            " created TEXT NOT NULL);"
            "CREATE TABLE IF NOT EXISTS sessions("
            " token TEXT PRIMARY KEY, uid INTEGER NOT NULL,"
            " created REAL NOT NULL, expires REAL NOT NULL);"
            "CREATE TABLE IF NOT EXISTS llm_usage("
            " uid INTEGER NOT NULL, day TEXT NOT NULL, count INTEGER NOT NULL,"
            " PRIMARY KEY(uid, day));"
        )


def _Db():
    odb = sqlite3.connect(os.path.join(_dataroot, "users.db"), timeout=10)
    odb.execute("PRAGMA journal_mode=WAL")
    return odb


def _HashPassword(spassword, bsalt):
    return hashlib.pbkdf2_hmac("sha256", spassword.encode("utf-8"), bsalt, PBKDF2_ITERS)


def ValidateUsername(susername):
    return bool(re.match(r"^[A-Za-z0-9_\u4e00-\u9fa5-]{2,24}$", susername or ""))


def UserDataDir(nuid):
    return os.path.join(_dataroot, "u-%d" % nuid)


def _PrepareUserDir(nuid):
    """新用户数据目录：复制主项目 templates/，其余由 topic_manager 首次播种。"""
    sdir = UserDataDir(nuid)
    os.makedirs(sdir, exist_ok=True)
    if _baseroot:
        stpl_src = os.path.join(_baseroot, "templates")
        stpl_dst = os.path.join(sdir, "templates")
        if os.path.isdir(stpl_src) and not os.path.isdir(stpl_dst):
            shutil.copytree(stpl_src, stpl_dst)
    return sdir


def Register(susername, spassword):
    susername = (susername or "").strip()
    if not ValidateUsername(susername):
        raise ValueError("用户名需 2-24 位：中文 / 字母 / 数字 / 下划线")
    if len(spassword or "") < 6:
        raise ValueError("密码至少 6 位")
    bsalt = secrets.token_bytes(16)
    bhash = _HashPassword(spassword, bsalt)
    with _dblock, _Db() as odb:
        try:
            ocur = odb.execute(
                "INSERT INTO users(username, pwhash, salt, created) VALUES(?,?,?,?)",
                (susername, bhash, bsalt, datetime.now().strftime("%Y-%m-%d %H:%M")),
            )
        except sqlite3.IntegrityError:
            raise ValueError("用户名已被占用")
        nuid = ocur.lastrowid
    _PrepareUserDir(nuid)
    return nuid


def _ThrottleLogin(sip):
    ofail = _loginfail.get(sip)
    nnow = time.time()
    if ofail and nnow - ofail[1] < 600 and ofail[0] >= 10:
        raise ValueError("尝试过于频繁，请 10 分钟后再试")


def _RecordLoginFail(sip):
    ofail = _loginfail.get(sip)
    nnow = time.time()
    if not ofail or nnow - ofail[1] >= 600:
        _loginfail[sip] = [1, nnow]
    else:
        ofail[0] += 1


def Login(susername, spassword, sip=""):
    _ThrottleLogin(sip)
    with _dblock, _Db() as odb:
        orow = odb.execute(
            "SELECT id, pwhash, salt FROM users WHERE username=?", ((susername or "").strip(),)
        ).fetchone()
    if not orow or not hmac.compare_digest(bytes(orow[1]), _HashPassword(spassword or "", bytes(orow[2]))):
        _RecordLoginFail(sip)
        raise ValueError("用户名或密码错误")
    nuid = orow[0]
    stoken = secrets.token_urlsafe(32)
    nnow = time.time()
    with _dblock, _Db() as odb:
        odb.execute(
            "INSERT INTO sessions(token, uid, created, expires) VALUES(?,?,?,?)",
            (stoken, nuid, nnow, nnow + SESSION_DAYS * 86400),
        )
        odb.execute("DELETE FROM sessions WHERE expires < ?", (nnow,))
    _PrepareUserDir(nuid)
    return stoken


def Logout(stoken):
    if not stoken:
        return
    with _dblock, _Db() as odb:
        odb.execute("DELETE FROM sessions WHERE token=?", (stoken,))


def ResolveSession(stoken):
    """token → {uid, username, root} 或 None。"""
    if not stoken:
        return None
    with _dblock, _Db() as odb:
        orow = odb.execute(
            "SELECT s.uid, u.username FROM sessions s JOIN users u ON u.id=s.uid"
            " WHERE s.token=? AND s.expires > ?", (stoken, time.time()),
        ).fetchone()
    if not orow:
        return None
    return {"uid": orow[0], "username": orow[1], "root": UserDataDir(orow[0])}


def CookieFromHeaders(scookieheader):
    for spart in (scookieheader or "").split(";"):
        skey, _, sval = spart.strip().partition("=")
        if skey == SESSION_COOKIE:
            return sval
    return ""


def MakeSetCookie(stoken, bclear=False):
    if bclear:
        return "%s=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0" % SESSION_COOKIE
    return "%s=%s; Path=/; HttpOnly; SameSite=Lax; Max-Age=%d" % (
        SESSION_COOKIE, stoken, SESSION_DAYS * 86400)


def CheckAndCountLlm(nuid, ncalls, nlimit):
    """每用户每日 LLM 调用限额（保护共享内置 Key）。超额返回 False。"""
    if nlimit <= 0:
        return True
    sday = datetime.now().strftime("%Y-%m-%d")
    with _dblock, _Db() as odb:
        orow = odb.execute(
            "SELECT count FROM llm_usage WHERE uid=? AND day=?", (nuid, sday)).fetchone()
        nused = orow[0] if orow else 0
        if nused + ncalls > nlimit:
            return False
        odb.execute(
            "INSERT INTO llm_usage(uid, day, count) VALUES(?,?,?)"
            " ON CONFLICT(uid, day) DO UPDATE SET count=count+?",
            (nuid, sday, ncalls, ncalls),
        )
    return True


LOGIN_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>研栈 · 登录</title>
<style>
  :root{--bg1:#faf6f4;--panel:#fffcfb;--border:#eadfd9;--text:#4a3f47;--muted:#9a8a94;--accent:#c9789a;--accent2:#d9a0b8}
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:"Noto Sans SC","PingFang SC",-apple-system,sans-serif;background:linear-gradient(160deg,#faf6f4,#f5ece8);min-height:100vh;display:flex;align-items:center;justify-content:center;color:var(--text)}
  .box{width:min(380px,92vw);background:var(--panel);border:1px solid var(--border);border-radius:20px;padding:34px 30px;box-shadow:0 12px 40px rgba(74,63,71,.1)}
  h1{font-size:22px;text-align:center;margin-bottom:6px}
  .sub{font-size:12px;color:var(--muted);text-align:center;margin-bottom:22px;line-height:1.6}
  .tabs{display:flex;gap:8px;margin-bottom:18px}
  .tabs button{flex:1;padding:9px;border-radius:10px;border:1px solid var(--border);background:transparent;color:var(--muted);font-size:14px;cursor:pointer}
  .tabs button.on{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
  label{display:block;font-size:12px;color:var(--muted);margin:14px 0 5px}
  input{width:100%;padding:11px 12px;border-radius:10px;border:1px solid var(--border);background:#fff;font-size:14px;color:var(--text)}
  input:focus{outline:none;border-color:var(--accent)}
  .go{width:100%;margin-top:22px;padding:12px;border:none;border-radius:10px;background:linear-gradient(135deg,var(--accent),var(--accent2));color:#fff;font-size:15px;font-weight:600;cursor:pointer}
  .go:disabled{opacity:.6}
  .err{margin-top:12px;font-size:12px;color:#d4566e;text-align:center;min-height:18px}
</style>
</head>
<body>
<div class="box">
  <h1>🌷 研栈</h1>
  <div class="sub">个人学术知识库 · 注册后数据相互独立</div>
  <div class="tabs">
    <button id="tab_login" class="on" onclick="SwitchTab('login')">登录</button>
    <button id="tab_reg" onclick="SwitchTab('reg')">注册</button>
  </div>
  <label>用户名</label>
  <input id="username" placeholder="2-24 位：中文 / 字母 / 数字 / 下划线" autocomplete="username">
  <label>密码</label>
  <input id="password" type="password" placeholder="至少 6 位" autocomplete="current-password" onkeydown="if(event.key==='Enter')Go()">
  <button class="go" id="gobtn" onclick="Go()">登 录</button>
  <div class="err" id="err"></div>
</div>
<script>
let MODE="login";
function SwitchTab(m){
  MODE=m;
  document.getElementById("tab_login").classList.toggle("on",m==="login");
  document.getElementById("tab_reg").classList.toggle("on",m==="reg");
  document.getElementById("gobtn").textContent=m==="login"?"登 录":"注册并登录";
  document.getElementById("err").textContent="";
}
async function Go(){
  const u=document.getElementById("username").value.trim();
  const p=document.getElementById("password").value;
  const btn=document.getElementById("gobtn"),err=document.getElementById("err");
  err.textContent="";btn.disabled=true;
  try{
    const r=await fetch("/auth/"+(MODE==="login"?"login":"register"),{
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify({username:u,password:p})});
    const d=await r.json();
    if(d.error){err.textContent=d.error;btn.disabled=false;return}
    location.href="/";
  }catch(e){err.textContent="网络错误："+e.message;btn.disabled=false}
}
</script>
</body>
</html>
"""
