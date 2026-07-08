#!/usr/bin/env python3
"""Wiki 公共核心 facade：向后兼容 re-export，实现已拆分至子模块。

子模块：
  wiki_paths      — 数据根与选题路径
  wiki_config     — 图谱/页面类型配置
  wiki_markdown   — Markdown 解析与边推断
  wiki_source_meta — source_meta.json 与 URL
  wiki_library    — 论文库去重、阶段元数据
  wiki_scan       — Wiki 扫描与选题统计
  wiki_data       — 页面读取、日志、待纳入列表
  wiki_render     — HTML 页面渲染（模板在 viewer/）
  wiki_graph      — 图谱巡检服务（P2）
  source_stage    — 文献阶段状态机（P2）
  data_context    — 数据根绑定与缓存失效（P2）
  health_check    — 服务健康检查（P2）
"""

import logging

import wiki_config as cfg
import wiki_paths as paths
import wiki_markdown as md
import wiki_source_meta as smeta
import wiki_library as lib
import wiki_scan as scan
import wiki_data as data
import wiki_render as render

logger = logging.getLogger(__name__)

_PATH_ATTRS = frozenset({"rootdir", "wikidir", "rawsourcesdir", "outputpath"})

# --- P2：图谱 / 阶段 / 上下文 / 健康（延迟加载，避免与 wiki_refresh 循环依赖）---
_P2_EXPORTS = {
    "RunLint": ("wiki_graph", "RunLint"),
    "RunLintQuick": ("wiki_graph", "RunLintQuick"),
    "RunLintWithOdata": ("wiki_graph", "RunLintWithOdata"),
    "FixLint": ("wiki_graph", "FixLint"),
    "LintIsClean": ("wiki_graph", "LintIsClean"),
    "ResolveLibStage": ("source_stage", "ResolveLibStage"),
    "StageRank": ("source_stage", "StageRank"),
    "StageLabel": ("source_stage", "StageLabel"),
    "DataContext": ("data_context", "DataContext"),
    "RunHealthCheck": ("health_check", "RunHealthCheck"),
}


def __getattr__(name):
    if name in _PATH_ATTRS:
        return getattr(paths, name)
    oexp = _P2_EXPORTS.get(name)
    if oexp:
        import importlib
        return getattr(importlib.import_module(oexp[0]), oexp[1])
    raise AttributeError("module %r has no attribute %r" % (__name__, name))


# --- 路径 ---
ResolveRootDir = paths.ResolveRootDir
ReloadTopicPaths = paths.ReloadTopicPaths
SetDataRoot = paths.SetDataRoot

# --- 配置 ---
typeconfig = cfg.typeconfig
edgeconfig = cfg.edgeconfig
graphlayers = cfg.graphlayers
explicitrelmap = cfg.explicitrelmap
explicitrelpattern = cfg.explicitrelpattern
wikilinkpattern = cfg.wikilinkpattern
frontmatterpattern = cfg.frontmatterpattern

# --- Markdown ---
ParseFrontmatter = md.ParseFrontmatter
SourcePageIngested = md.SourcePageIngested
IsSourceKeyIngested = md.IsSourceKeyIngested
ExtractLinks = md.ExtractLinks
FilenameToKey = md.FilenameToKey
ParseSourceFilename = md.ParseSourceFilename
MergeWikiIntoNode = md.MergeWikiIntoNode
BuildNodeIndex = md.BuildNodeIndex
InferEdgeType = md.InferEdgeType
ParseRelEndpoint = md.ParseRelEndpoint
ExtractExplicitRelations = md.ExtractExplicitRelations
RefreshEdgeMeta = md.RefreshEdgeMeta
ComputePageRank = md.ComputePageRank
ExtractMarkdownSections = md.ExtractMarkdownSections
StripWikiMarkup = md.StripWikiMarkup
ExtractSourceResearch = md.ExtractSourceResearch
GetSummary = md.GetSummary

# --- 文献元数据 ---
SourceMetaPath = smeta.SourceMetaPath
ReadSourceMeta = smeta.ReadSourceMeta
WriteSourceMeta = smeta.WriteSourceMeta
NormalizeUrl = smeta.NormalizeUrl
GetPendingSourceUrl = smeta.GetPendingSourceUrl
SetPendingSourceUrl = smeta.SetPendingSourceUrl
FindSourcePagePath = smeta.FindSourcePagePath
UpdateSourceFrontmatterUrl = smeta.UpdateSourceFrontmatterUrl
SetPaperUrl = smeta.SetPaperUrl
MergePendingUrlToSource = smeta.MergePendingUrlToSource
ListSources = smeta.ListSources
LIB_TAG_PREFIX = smeta.LIB_TAG_PREFIX
GetSourceMetaEntry = smeta.GetSourceMetaEntry
SaveSourceMetaEntry = smeta.SaveSourceMetaEntry
GetLibTags = smeta.GetLibTags
GetLibRq = smeta.GetLibRq
GetLibChapter = smeta.GetLibChapter
SetLibTags = smeta.SetLibTags
SetLibRq = smeta.SetLibRq
SetLibChapter = smeta.SetLibChapter
AssignSourceGroup = smeta.AssignSourceGroup

# --- 论文库 ---
BindRawfileToSource = lib.BindRawfileToSource
ResolveRawfileForKey = lib.ResolveRawfileForKey
EnsureNodeRawfile = lib.EnsureNodeRawfile
BuildLibraryGroups = lib.BuildLibraryGroups
HasDeepReportFile = lib.HasDeepReportFile
HasStandardReportFile = lib.HasStandardReportFile
MergeSourceNodes = lib.MergeSourceNodes
DedupeSourceNodes = lib.DedupeSourceNodes
SortAuthorKey = lib.SortAuthorKey
SourceTimestamps = lib.SourceTimestamps
EnrichSourceLibraryMeta = lib.EnrichSourceLibraryMeta
_SameSource = lib._SameSource
_MergeSourceMetaEntries = lib._MergeSourceMetaEntries
_SourceCanonicalScore = lib._SourceCanonicalScore

# --- 扫描 ---
ScanWiki = scan.ScanWiki
CountDeadLinks = scan.CountDeadLinks
CountTopicSources = scan.CountTopicSources
TopicsWithCounts = scan.TopicsWithCounts

# --- 数据 API ---
BuildData = data.BuildData
PendingSources = data.PendingSources
GetPageContent = data.GetPageContent
ResolveWikiPagePath = data.ResolveWikiPagePath
GenerateIndex = data.GenerateIndex
AppendLog = data.AppendLog

# --- 渲染 ---
Render = render.Render


def Main():
    odata = BuildData()
    with open(paths.outputpath, "w", encoding="utf-8") as f:
        f.write(Render(odata, servermode=False))
    print("已生成: %s" % paths.outputpath)
    print("页面 %d 个，关联 %d 条" % (len(odata["nodes"]), len(odata["edges"])))


if __name__ == "__main__":
    Main()
