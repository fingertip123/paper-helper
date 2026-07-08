#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多用户认证与 LLM 配额。"""
import app_context as actx
import app_routes
import auth
from app_config import ApplyConfigDefaults, LoadConfigRaw
from job_state import (
    GetDeepActiveUid, GetIngestJob, GetQueryJob, GetStandardActiveUid,
    ingest_active_uid, ingestlock, query_active_uid, querylock,
)
from llm_client import HasUsableApiKey


class HandlerAuthMixin:

    def _SessionUser(self):
        return auth.ResolveSession(auth.CookieFromHeaders(self.headers.get("Cookie", "")))


    def _AuthGet(self, path):
        """多用户模式下的 GET 认证网关。返回 True 表示已应答。"""
        if path == "/login":
            self._send(200, auth.LOGIN_HTML, "text/html; charset=utf-8")
            return True
        if path == "/auth/me":
            ouser = self._SessionUser()
            self._send(200, {"username": ouser["username"] if ouser else ""})
            return True
        ouser = self._SessionUser()
        if not ouser:
            if path in ("/", "/index.html"):
                self._send(200, auth.LOGIN_HTML, "text/html; charset=utf-8")
            else:
                self._send(401, {"error": "未登录，请刷新页面重新登录"})
            return True
        self._user = ouser
        return False


    def _RequestSecure(self):
        return self.headers.get("X-Forwarded-Proto", "").lower() == "https"


    def _AuthPost(self):
        """多用户模式下的 POST 认证网关。返回 True 表示已应答。"""
        if self.path == "/auth/register":
            body = self._body()
            try:
                auth.Register(body.get("username", ""), body.get("password", ""))
                stoken = auth.Login(body.get("username", ""), body.get("password", ""),
                                    self.client_address[0])
            except ValueError as e:
                self._send(200, {"error": str(e)})
                return True
            self._send(200, {"status": "ok"},
                       vheaders=[("Set-Cookie", auth.MakeSetCookie(stoken, bsecure=self._RequestSecure()))])
            return True
        if self.path == "/auth/login":
            body = self._body()
            try:
                stoken = auth.Login(body.get("username", ""), body.get("password", ""),
                                    self.client_address[0])
            except ValueError as e:
                self._send(200, {"error": str(e)})
                return True
            self._send(200, {"status": "ok"},
                       vheaders=[("Set-Cookie", auth.MakeSetCookie(stoken, bsecure=self._RequestSecure()))])
            return True
        if self.path == "/auth/logout":
            auth.Logout(auth.CookieFromHeaders(self.headers.get("Cookie", "")))
            self._send(200, {"status": "ok"},
                       vheaders=[("Set-Cookie", auth.MakeSetCookie("", bclear=True, bsecure=self._RequestSecure()))])
            return True
        ouser = self._SessionUser()
        if not ouser:
            self._send(401, {"error": "未登录，请刷新页面重新登录"})
            return True
        self._user = ouser
        if self.path in app_routes.CLOUD_FORBIDDEN_POST:
            self._send(403, {"error": "云端多用户模式不支持此操作"})
            return True
        return False


    def _Uid(self):
        ouser = getattr(self, "_user", None)
        return ouser["uid"] if ouser else 0


    def _CheckLlmQuota(self, ncalls):
        """多用户模式：使用共享内置 Key 时的每日限额。返回错误提示或空串。"""
        if not actx.ctx.multiuser or actx.ctx.llmdailylimit <= 0:
            return ""
        oraw = ApplyConfigDefaults(LoadConfigRaw())
        if HasUsableApiKey(oraw):
            return ""  # 用户配置了自己的 Key，不限额
        if not auth.CheckAndCountLlm(self._Uid(), ncalls, actx.ctx.llmdailylimit):
            return ("今日共享模型额度已用完（%d 次/天）。"
                    "可在「偏好设置」填写自己的免费 API Key（如智谱），不受限额。" % actx.ctx.llmdailylimit)
        return ""


    def _CheckCsrf(self):
        if not actx.ctx.multiuser:
            return True
        stoken = auth.CookieFromHeaders(self.headers.get("Cookie", ""))
        if not auth.VerifyCsrf(stoken, self.headers.get("X-Yz-CSRF", "")):
            self._send(403, {"error": "CSRF 校验失败，请刷新页面后重试"})
            return False
        return True


    def _BusyOwnerUid(self, sbusy):
        """返回当前占用某类 LLM 任务的用户 uid（多用户隔离用）。"""
        if sbusy == "ingest":
            with ingestlock:
                return GetIngestJob(ingest_active_uid).get("uid")
        if sbusy == "query":
            with querylock:
                return GetQueryJob(query_active_uid).get("uid")
        if sbusy == "deep":
            return GetDeepActiveUid()
        if sbusy == "standard":
            return GetStandardActiveUid()
        return None


    def _MaybeOtherUserBusy(self, obusy):
        """多用户模式下，若占用者是其他用户，替换为通用「他人任务」提示。"""
        if not obusy or not actx.ctx.multiuser:
            return obusy
        if self._BusyOwnerUid(obusy.get("busy")) not in (0, None, self._Uid()):
            return {"status": "busy", "busy": obusy.get("busy"),
                    "message": "服务器正在处理其他用户的任务，请稍后再试。"}
        return obusy
