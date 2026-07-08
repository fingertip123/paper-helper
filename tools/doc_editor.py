#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文档编辑 facade：向后兼容 re-export。

子模块：
  doc_paths        — 路径与清单 I/O
  docx_parser      — .docx / OOXML 读写
  doc_editor_html  — 预览与编辑器 HTML
  doc_revisions    — 版本 stash / diff / commit
  doc_api          — 对外 API 编排
"""
import doc_paths as dpaths
from docx_parser import *  # noqa: F403
from doc_editor_html import *  # noqa: F403
from doc_revisions import *  # noqa: F403
import doc_revisions as _drev
from doc_api import *  # noqa: F403

Init = dpaths.Init
DocsDir = dpaths.DocsDir
ManifestPath = dpaths.ManifestPath
ValidateDocId = dpaths.ValidateDocId
DocDir = dpaths.DocDir
ReadJson = dpaths.ReadJson
WriteJson = dpaths.WriteJson
ReadManifest = dpaths.ReadManifest
WriteManifest = dpaths.WriteManifest
NewDocId = dpaths.NewDocId
CalcTodoProgress = dpaths.CalcTodoProgress

# app.py 使用的私有符号（import * 不导出 _ 前缀）
_HeadRevisionId = _drev._HeadRevisionId
_BootstrapDocPreview = BootstrapDocPreview
_SetParaPlainText = SetParaPlainText
_NormalizeExportFilename = NormalizeExportFilename
_BuildExportDocx = BuildExportDocx
