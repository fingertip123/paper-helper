#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选题与规则管理。"""
import topic_manager as topics
import wiki_core as core
import wiki_ops as wops
import wiki_refresh as refresh
import onboarding as onboard


class HandlerTopicsMixin:

    def _GetTopics(self):
        return self._send(200, {
            "topics": core.TopicsWithCounts(),
            "current": topics.GetCurrentTopicId(),
            "purpose_fields": topics.GetPurposeFieldDefs(),
        })


    def _GetRules(self):
        return self._send(200, topics.GetRules())


    def _GetTopicConfig(self):
        import urllib.parse
        oquery = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
        nid = (oquery.get("id") or [""])[0]
        try:
            return self._send(200, topics.GetTopicConfig(nid))
        except ValueError as e:
            return self._send(400, {"error": str(e)})


    def _topicswitch(self):
        body = self._body()
        try:
            result = topics.SwitchTopic(body.get("id", ""))
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        refresh.InvalidateWikiCache()
        core.ReloadTopicPaths()
        refresh.RefreshWiki(bwrite_files=True)
        return self._send(200, result)


    def _topicnew(self):
        body = self._body()
        try:
            result = topics.CreateTopic(
                body.get("name", "新选题"),
                body.get("fields"),
                True,
                body.get("import_from"),
            )
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        refresh.InvalidateWikiCache()
        core.ReloadTopicPaths()
        refresh.RefreshWiki(bwrite_files=True)
        nqc = result.get("inherited_queries") or 0
        if nqc:
            core.AppendLog("新建选题：%s（%s），继承问答库 %d 页" % (
                result.get("name"), result.get("id"), nqc))
        else:
            core.AppendLog("新建选题：%s（%s）" % (result.get("name"), result.get("id")))
        return self._send(200, result)


    def _topicreset(self):
        result = topics.ResetCurrentTopic()
        refresh.InvalidateWikiCache()
        core.ReloadTopicPaths()
        refresh.RefreshWiki(bwrite_files=True)
        core.AppendLog("重置选题：%s" % result.get("name"))
        return self._send(200, result)


    def _rulessave(self):
        body = self._body()
        skey = body.get("key", "")
        import wiki_workflow as wflow
        sold_fields = {}
        if skey == "purpose":
            sold_fields = topics.ParsePurposeFields(topics.ReadText(topics.RulePath("purpose.md")))
        topics.SaveRule(skey, content=body.get("content"), ofields=body.get("fields"))
        refresh.InvalidateWikiCache(core.wikidir)
        oresult = {"status": "ok"}
        if skey == "purpose" and body.get("fields"):
            vstale = wflow.DetectStaleSources(sold_fields, body.get("fields"))
            if vstale:
                oresult["stale_sources"] = vstale
                oresult["stale_hint"] = "研究问题或论点已变更，以下 %d 篇文献可能需要重新标准/深度分析" % len(vstale)
        return self._send(200, oresult)


    def _topicsnapshot(self):
        wops.Init(core.wikidir, core.rawsourcesdir, core.rootdir)
        oresult = wops.SnapshotTopic()
        core.AppendLog("[snapshot] 选题备份 %s" % oresult.get("path"))
        return self._send(200, oresult)


    def _onboardingsetup(self):
        body = self._body()
        result = onboard.SetupFromTitle(body.get("title", ""))
        core.ReloadTopicPaths()
        return self._send(200, result)


    def _onboardingdismiss(self):
        body = self._body()
        stype = body.get("type", "checklist")
        if stype == "welcome":
            result = onboard.DismissWelcome()
        else:
            result = onboard.DismissChecklist()
        return self._send(200, result)
