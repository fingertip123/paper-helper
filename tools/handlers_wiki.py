#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki / 知识库 / 配置 / 任务进度 / 新手引导 GET 处理器。"""
import app_context as actx
import auth
import api_response
import health_check as hcheck
import onboarding as onboard
import task_queue
import wiki_core as core
import wiki_graph as wgraph
import wiki_ops as wops
import wiki_refresh as refresh
import bib_io
from app_config import GetUserTheme, LoadConfig, SaveConfig


class HandlerWikiMixin:

    def _GetIndex(self):
        ouser = getattr(self, "_user", None)
        stoken = auth.CookieFromHeaders(self.headers.get("Cookie", "")) if actx.ctx.multiuser else ""
        odata = refresh.RefreshWiki(bwrite_files=True)
        return self._send(200, core.Render(
            odata, servermode=True, desktopmode=actx.ctx.desktopmode,
            stheme=GetUserTheme(), susername=ouser["username"] if ouser else "",
            bcloud=actx.ctx.multiuser, scsrf=auth.IssueCsrf(stoken) if stoken else "",
        ), "text/html; charset=utf-8")


    def _GetApiData(self):
        return self._send(200, refresh.RefreshWiki(bwrite_files=True))


    def _GetApiHealth(self):
        wgraph.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        return self._send(200, hcheck.RunHealthCheck(self._Uid(), LoadConfig()))


    def _GetApiConfig(self):
        return self._send(200, GetConfigForApi())


    def _GetIngestProgress(self):
        return self._send(200, task_queue.GetTaskProgress("ingest", self._Uid()))


    def _GetDeepProgress(self):
        return self._send(200, task_queue.GetTaskProgress("deep", self._Uid()))


    def _GetStandardProgress(self):
        return self._send(200, task_queue.GetTaskProgress("standard", self._Uid()))


    def _GetQueryProgress(self):
        return self._send(200, task_queue.GetTaskProgress("query", self._Uid()))


    def _GetTasksProgress(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        skind = (oq.get("kind") or [""])[0]
        nuid = self._Uid()
        if skind:
            oprog = task_queue.GetTaskProgress(skind, nuid)
            if oprog is None:
                return self._send(400, api_response.ErrorBody("无效任务类型", "BAD_REQUEST"))
            return self._send(200, {"kind": skind, "progress": oprog})
        return self._send(200, {"tasks": task_queue.GetAllTasksProgress(nuid)})


    def _GetOnboarding(self):
        return self._send(200, onboard.GetState())


    def _GetLint(self):
        wgraph.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        return self._send(200, wgraph.RunLint())


    def _GetChapters(self):
        import wiki_workflow as wflow
        wflow.Init(core.wikidir)
        return self._send(200, wflow.GetChapterProgress(refresh.GetWikiData()))


    def _GetSearch(self):
        import urllib.parse
        import wiki_workflow as wflow
        wflow.Init(core.wikidir)
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sq = (oq.get("q") or [""])[0]
        return self._send(200, {"results": wflow.SearchWikiPages(sq)})


    def _GetPage(self):
        import urllib.parse
        oq = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        sid = (oq.get("id") or [""])[0].strip()
        opage = core.GetPageContent(sid)
        if not opage:
            return self._send(404, {"error": "页面不存在"})
        return self._send(200, opage)


    def _GetExportBibtex(self):
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        return self._send(200, {"bibtex": wops.ExportBibtex()})


    def _GetCitations(self):
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        return self._send(200, {"citations": bib_io.ListCitations(refresh.GetWikiData())})


    def _GetLibraryGroups(self):
        return self._send(200, core.BuildLibraryGroups(refresh.GetWikiData()["nodes"]))


    def _PostConfig(self):
        body = self._body()
        SaveConfig(body)
        return self._send(200, {"status": "ok"})


    def _PostLintFix(self):
        wgraph.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        return self._send(200, wgraph.FixLint())
