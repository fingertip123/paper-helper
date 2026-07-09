#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP Handler 基础设施：收发、路由分发。"""
import json
import logging

import api_response
import app_context as actx
import app_routes
import request_log
from app_scope import UserScope

logger = logging.getLogger(__name__)


class HandlerBaseMixin:

    def log_message(self, *a):
        pass


    def _send(self, code, body, ctype="application/json; charset=utf-8", vheaders=None):
        self._last_code = code
        if isinstance(body, dict):
            body = api_response.EnrichResponse(body, code)
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, list):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        vheaders = list(vheaders or [])
        srid = request_log.CurrentId()
        if srid:
            vheaders.append(("X-Request-Id", srid))
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for skey, sval in (vheaders or []):
            self.send_header(skey, sval)
        self.end_headers()
        self.wfile.write(body)


    def _body(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        if length > actx.ctx.max_body_bytes:
            raise ValueError("请求体过大（上限 %d MB）" % (actx.ctx.max_body_bytes // (1024 * 1024)))
        return json.loads(self.rfile.read(length).decode("utf-8")) if length else {}

    # ---------- 多用户：会话与认证 ----------


    def do_GET(self):
        path = self.path.split("?", 1)[0]
        self._req_method = "GET"
        self._req_path = path
        request_log.BeginRequest("GET", path)
        try:
            if actx.ctx.multiuser and self._AuthGet(path):
                return
            ouser = getattr(self, "_user", None)
            with UserScope(ouser["root"] if ouser else None):
                return self._HandleGet(path)
        except ValueError as e:
            self._last_code = 400
            return self._send(400, {"error": str(e)})
        except Exception as e:
            request_log.LogException("GET", path, e)
            self._last_code = 500
            if actx.ctx.multiuser:
                return self._send(500, {"error": "服务器内部错误"})
            return self._send(500, {"error": str(e)})
        finally:
            request_log.LogDone("GET", path, self._last_code)


    def do_POST(self):
        self.path = self.path.split("?", 1)[0]
        self._req_method = "POST"
        self._req_path = self.path
        request_log.BeginRequest("POST", self.path)
        try:
            if actx.ctx.multiuser and self._AuthPost():
                return
            ouser = getattr(self, "_user", None)
            with UserScope(ouser["root"] if ouser else None):
                return self._HandlePost()
        except ValueError as e:
            self._last_code = 400
            if "请求体过大" in str(e):
                return self._send(413, {"error": str(e)})
            return self._send(400, {"error": str(e)})
        except Exception as e:
            request_log.LogException("POST", self.path, e)
            self._last_code = 500
            if actx.ctx.multiuser:
                return self._send(500, {"error": "服务器内部错误"})
            return self._send(500, {"error": str(e)})
        finally:
            request_log.LogDone("POST", self.path, self._last_code)


    def _DispatchRoute(self, spec):
        fn = getattr(self, spec.handler)
        if spec.bpass_path:
            return fn(self.path.split("?", 1)[0])
        return fn()

    # ---------- GET 路由处理器 ----------


    def _HandleGet(self, path):
        spec = app_routes.MatchGet(path)
        if not spec:
            return self._send(404, {"error": "not found"})
        try:
            return self._DispatchRoute(spec)
        except ValueError as e:
            if "请求体过大" in str(e):
                return self._send(413, {"error": str(e)})
            return self._send(400, {"error": str(e)})
        except Exception as e:
            request_log.LogException("GET", path, e)
            if actx.ctx.multiuser:
                return self._send(500, {"error": "服务器内部错误"})
            return self._send(500, {"error": str(e)})


    def _HandlePost(self):
        if actx.ctx.multiuser and not self.path.startswith("/auth/") and not self._CheckCsrf():
            return
        spec = app_routes.MatchPost(self.path)
        if not spec:
            return self._send(404, {"error": "not found"})
        try:
            return self._DispatchRoute(spec)
        except ValueError as e:
            if "请求体过大" in str(e):
                return self._send(413, {"error": str(e)})
            return self._send(400, {"error": str(e)})
        except Exception as e:
            request_log.LogException("POST", self.path, e)
            if actx.ctx.multiuser:
                return self._send(500, {"error": "服务器内部错误"})
            return self._send(500, {"error": str(e)})
