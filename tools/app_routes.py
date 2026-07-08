#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 路由注册表：将 app.Handler 的 GET/POST 分发从巨型 if/elif 中解耦。"""
from collections import namedtuple

RouteSpec = namedtuple("RouteSpec", "pattern handler bprefix bpass_path")

# GET：pattern 精确匹配；bprefix=True 时 startswith 匹配并传入 path
GET_ROUTES = (
    RouteSpec("/", "_GetIndex", False, False),
    RouteSpec("/index.html", "_GetIndex", False, False),
    RouteSpec("/api/data", "_GetApiData", False, False),
    RouteSpec("/api/health", "_GetApiHealth", False, False),
    RouteSpec("/api/config", "_GetApiConfig", False, False),
    RouteSpec("/api/ingest/progress", "_GetIngestProgress", False, False),
    RouteSpec("/api/deep/progress", "_GetDeepProgress", False, False),
    RouteSpec("/api/standard/progress", "_GetStandardProgress", False, False),
    RouteSpec("/api/query/progress", "_GetQueryProgress", False, False),
    RouteSpec("/api/tasks/progress", "_GetTasksProgress", False, False),
    RouteSpec("/api/onboarding", "_GetOnboarding", False, False),
    RouteSpec("/api/lint", "_GetLint", False, False),
    RouteSpec("/api/chapters", "_GetChapters", False, False),
    RouteSpec("/api/search", "_GetSearch", False, False),
    RouteSpec("/api/page", "_GetPage", False, False),
    RouteSpec("/api/export/bibtex", "_GetExportBibtex", False, False),
    RouteSpec("/api/sources/citations", "_GetCitations", False, False),
    RouteSpec("/api/library/groups", "_GetLibraryGroups", False, False),
    RouteSpec("/api/topics", "_GetTopics", False, False),
    RouteSpec("/api/rules", "_GetRules", False, False),
    RouteSpec("/api/topics/config", "_GetTopicConfig", False, False),
    RouteSpec("/raw/sources/", "_serve_file", True, True),
    RouteSpec("/api/docs", "_GetDocsList", False, False),
    RouteSpec("/api/docs/detail", "_GetDocsDetail", False, False),
    RouteSpec("/api/docs/preview", "_GetDocsPreview", False, False),
    RouteSpec("/api/docs/editor", "_servedoceditor", False, False),
    RouteSpec("/api/docs/media", "_servedocmedia", False, False),
    RouteSpec("/api/docs/revisions", "_GetDocsRevisions", False, False),
    RouteSpec("/api/docs/revision", "_GetDocsRevision", False, False),
    RouteSpec("/api/docs/status", "_GetDocsStatus", False, False),
    RouteSpec("/api/docs/compare", "_GetDocsCompare", False, False),
    RouteSpec("/api/docs/download", "_docsdownload", False, False),
)

POST_ROUTES = (
    RouteSpec("/api/upload", "_upload", False, False),
    RouteSpec("/api/delete", "_delete", False, False),
    RouteSpec("/api/ingest", "_ingest", False, False),
    RouteSpec("/api/ingest/deep", "_deep_analyze", False, False),
    RouteSpec("/api/ingest/standard", "_standard_analyze", False, False),
    RouteSpec("/api/config", "_PostConfig", False, False),
    RouteSpec("/api/shutdown", "_shutdown", False, False),
    RouteSpec("/api/topics/switch", "_topicswitch", False, False),
    RouteSpec("/api/topics/new", "_topicnew", False, False),
    RouteSpec("/api/topics/reset", "_topicreset", False, False),
    RouteSpec("/api/rules/save", "_rulessave", False, False),
    RouteSpec("/api/open/pdf", "_openpdf", False, False),
    RouteSpec("/api/open/url", "_openurl", False, False),
    RouteSpec("/api/source/url", "_sourceurl", False, False),
    RouteSpec("/api/source/tags", "_sourcetags", False, False),
    RouteSpec("/api/library/assign", "_libraryassign", False, False),
    RouteSpec("/api/ingest/cancel", "_ingestcancel", False, False),
    RouteSpec("/api/query", "_query", False, False),
    RouteSpec("/api/lint/fix", "_PostLintFix", False, False),
    RouteSpec("/api/import/bibtex", "_importbibtex", False, False),
    RouteSpec("/api/topics/snapshot", "_topicsnapshot", False, False),
    RouteSpec("/api/onboarding/setup", "_onboardingsetup", False, False),
    RouteSpec("/api/onboarding/dismiss", "_onboardingdismiss", False, False),
    RouteSpec("/api/docs/import", "_docsimport", False, False),
    RouteSpec("/api/docs/meta", "_docsmeta", False, False),
    RouteSpec("/api/docs/extract", "_docsextract", False, False),
    RouteSpec("/api/docs/todo", "_docstodo", False, False),
    RouteSpec("/api/docs/edit", "_docsedit", False, False),
    RouteSpec("/api/docs/save", "_docssave", False, False),
    RouteSpec("/api/docs/restore", "_docsrestore", False, False),
    RouteSpec("/api/docs/restore-working", "_docsrestoreworking", False, False),
    RouteSpec("/api/docs/discard", "_docsdiscard", False, False),
    RouteSpec("/api/docs/export", "_docsexport", False, False),
    RouteSpec("/api/docs/pick-folder", "_docspickfolder", False, False),
    RouteSpec("/api/docs/delete", "_docsdelete", False, False),
)

AUTH_GET_PATHS = frozenset({"/login", "/auth/me"})
CLOUD_FORBIDDEN_POST = frozenset({
    "/api/shutdown",
    "/api/open/pdf",
    "/api/open/url",
    "/api/docs/pick-folder",
})


def MatchRoute(vroutes, path):
    """返回首个匹配的 RouteSpec，无匹配则 None。"""
    for spec in vroutes:
        if spec.bprefix:
            if path.startswith(spec.pattern):
                return spec
        elif path == spec.pattern:
            return spec
    return None


def MatchGet(path):
    return MatchRoute(GET_ROUTES, path)


def MatchPost(path):
    return MatchRoute(POST_ROUTES, path)
