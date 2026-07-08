#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenAI 兼容 LLM 客户端（与 app / research_deep 解耦，避免循环导入）。"""
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

apikeymask = "***"


class IngestCancelled(Exception):
    """用户取消 LLM 任务（纳入研究 / 深度分析等）。"""


def IsPlaceholderApiKey(skey):
    skey = (skey or "").strip()
    return not skey or skey in (apikeymask, "****", "•••", "······")


def HasUsableApiKey(oconfig):
    return not IsPlaceholderApiKey(oconfig.get("api_key"))


_sslcontext = None
browserua = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def SslContext():
    global _sslcontext
    if _sslcontext is not None:
        return _sslcontext
    import ssl
    try:
        import certifi
        _sslcontext = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        _sslcontext = ssl.create_default_context()
    return _sslcontext


def SleepWithCancel(nseconds, fcancel=None):
    nend = time.time() + nseconds
    while time.time() < nend:
        if fcancel and fcancel():
            raise IngestCancelled("用户已取消")
        time.sleep(min(0.35, max(0.05, nend - time.time())))


def UrlopenJsonWithCancel(oreq, fcancel=None, ntimeout=300):
    if not fcancel:
        with urllib.request.urlopen(oreq, timeout=ntimeout, context=SslContext()) as resp:
            return json.loads(resp.read().decode("utf-8"))
    oholder = {"obj": None, "err": None}

    def work():
        try:
            with urllib.request.urlopen(oreq, timeout=ntimeout, context=SslContext()) as resp:
                oholder["obj"] = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            oholder["err"] = e

    othread = threading.Thread(target=work, daemon=True)
    othread.start()
    while othread.is_alive():
        if fcancel():
            raise IngestCancelled("用户已取消")
        othread.join(0.35)
    if oholder["err"]:
        raise oholder["err"]
    return oholder["obj"]


def _RetryAfterSeconds(oerr, ndefault):
    try:
        sval = oerr.headers.get("Retry-After")
        if sval and sval.strip().isdigit():
            return min(int(sval.strip()), 60)
    except Exception:
        pass
    return ndefault


def ValidateBaseUrl(sbase):
    """校验 LLM base_url，返回去掉末尾斜杠的规范 URL。"""
    sbase = (sbase or "").strip()
    if not sbase:
        raise ValueError("未配置 base_url，请在「偏好设置」中填写 API 地址")
    ourl = urlparse(sbase)
    if ourl.scheme not in ("http", "https"):
        raise ValueError("base_url 须以 http:// 或 https:// 开头，当前：%s" % sbase)
    if not ourl.netloc:
        raise ValueError("base_url 格式无效（缺少主机名）：%s" % sbase)
    return sbase.rstrip("/")


def BuildChatUrl(oconfig):
    return ValidateBaseUrl(oconfig.get("base_url")) + "/chat/completions"


def CallLlm(oconfig, vmessages, bjson=True, fcancel=None):
    url = BuildChatUrl(oconfig)
    nbaseurl = oconfig.get("base_url") or ""
    bnoauth = not HasUsableApiKey(oconfig)
    payload = {
        "model": oconfig.get("model") or "gpt-4o-mini",
        "messages": vmessages,
        "temperature": 0.2,
    }
    if bjson and "pollinations.ai" not in nbaseurl:
        payload["response_format"] = {"type": "json_object"}
    data = json.dumps(payload).encode("utf-8")
    oheaders = {"Content-Type": "application/json", "User-Agent": browserua}
    if HasUsableApiKey(oconfig):
        oheaders["Authorization"] = "Bearer " + oconfig["api_key"].strip()
    req = urllib.request.Request(url, data=data, method="POST", headers=oheaders)

    nmaxtry = 6 if bnoauth else 2
    slasterr = ""
    for ntry in range(nmaxtry):
        if fcancel and fcancel():
            raise IngestCancelled("用户已取消")
        try:
            obj = UrlopenJsonWithCancel(req, fcancel=fcancel)
            if not obj.get("choices"):
                raise RuntimeError("接口未返回有效结果：" + json.dumps(obj, ensure_ascii=False)[:200])
            return obj["choices"][0]["message"]["content"]
        except IngestCancelled:
            raise
        except urllib.error.HTTPError as e:
            sdetail = e.read().decode("utf-8", "ignore")[:300]
            if e.code in (429, 503) and ntry < nmaxtry - 1:
                SleepWithCancel(_RetryAfterSeconds(e, 16 if bnoauth else 4), fcancel)
                continue
            if e.code in (500, 502, 504) and ntry < nmaxtry - 1:
                SleepWithCancel(3, fcancel)
                continue
            if e.code == 429:
                raise RuntimeError(
                    "免费接口繁忙(限流)。请等待约 15 秒后重试，"
                    "或在「设置」中改用带 Key 的免费模型（更稳定）。"
                )
            if e.code in (401, 403):
                raise RuntimeError(
                    "接口拒绝访问(%s)。该免费端点可能已变更或需要 Key，"
                    "建议在「设置」中改用带 Key 的免费模型。" % e.code
                )
            raise RuntimeError("接口返回 %s：%s" % (e.code, sdetail))
        except urllib.error.URLError as e:
            slasterr = str(getattr(e, "reason", e))
            if ntry < nmaxtry - 1:
                SleepWithCancel(3, fcancel)
                continue
            raise RuntimeError("网络连接失败：%s" % slasterr)
    raise RuntimeError(slasterr or "调用失败")


def CallLlmStream(oconfig, vmessages, fcancel=None, fonchunk=None):
    """流式调用；不支持 stream 的端点回退为一次性返回。"""
    nbaseurl = oconfig.get("base_url") or ""
    if "pollinations.ai" in nbaseurl:
        sfull = CallLlm(oconfig, vmessages, bjson=False, fcancel=fcancel)
        if fonchunk and sfull:
            fonchunk(sfull)
        return sfull

    url = BuildChatUrl(oconfig)
    payload = {
        "model": oconfig.get("model") or "gpt-4o-mini",
        "messages": vmessages,
        "temperature": 0.2,
        "stream": True,
    }
    data = json.dumps(payload).encode("utf-8")
    oheaders = {"Content-Type": "application/json", "User-Agent": browserua}
    if HasUsableApiKey(oconfig):
        oheaders["Authorization"] = "Bearer " + oconfig["api_key"].strip()
    req = urllib.request.Request(url, data=data, method="POST", headers=oheaders)

    vparts = []
    try:
        with urllib.request.urlopen(req, timeout=300, context=SslContext()) as resp:
            while True:
                if fcancel and fcancel():
                    raise IngestCancelled("用户已取消")
                sline = resp.readline()
                if not sline:
                    break
                sline = sline.decode("utf-8", errors="ignore").strip()
                if not sline.startswith("data:"):
                    continue
                spayload = sline[5:].strip()
                if spayload == "[DONE]":
                    break
                try:
                    oobj = json.loads(spayload)
                    sdelta = (
                        oobj.get("choices", [{}])[0]
                        .get("delta", {})
                        .get("content", "")
                    )
                except Exception:
                    sdelta = ""
                if sdelta:
                    vparts.append(sdelta)
                    if fonchunk:
                        fonchunk(sdelta)
    except IngestCancelled:
        raise
    except Exception:
        if vparts:
            return "".join(vparts)
        return CallLlm(oconfig, vmessages, bjson=False, fcancel=fcancel)
    return "".join(vparts)


def ParseLlmJson(ntext):
    s = ntext.strip()
    s = re.sub(r"^```(json)?\s*|\s*```$", "", s, flags=re.IGNORECASE)
    start, end = s.find("{"), s.rfind("}")
    if start >= 0 and end > start:
        s = s[start:end + 1]
    return json.loads(s)
