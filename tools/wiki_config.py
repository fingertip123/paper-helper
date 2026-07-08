#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Wiki 图谱与页面类型配置（纯数据）。"""
import re


# 各页面类型的展示配置：标签 + 颜色 + 目录
typeconfig = {
    "source": {"label": "文献", "color": "#7eb8d4", "dir": "sources"},
    "concept": {"label": "概念", "color": "#e8b86d", "dir": "concepts"},
    "entity": {"label": "实体", "color": "#b89fd8", "dir": "entities"},
    "rq": {"label": "研究问题", "color": "#d4899f", "dir": "research-questions"},
    "experiment": {"label": "实验", "color": "#8ec9a8", "dir": "experiments"},
    "synthesis": {"label": "综合", "color": "#8ec4d4", "dir": "synthesis"},
    "comparison": {"label": "对比", "color": "#d4a87a", "dir": "comparisons"},
    "analysis-report": {"label": "研究报告", "color": "#c49ad4", "dir": "analysis"},
    "query": {"label": "问答", "color": "#a8c47a", "dir": "queries"},
    "purpose": {"label": "目标", "color": "#d49a7a", "dir": ""},
    "unknown": {"label": "其他", "color": "#b0a4ad", "dir": ""},
}

# 边类型展示（由源/目标节点 type 推断）
edgeconfig = {
    "引用概念": {"label": "引用概念", "color": "#3d7dd6"},
    "提及实体": {"label": "提及实体", "color": "#9b59d4"},
    "关联问题": {"label": "关联问题", "color": "#e67e22"},
    "文献对照": {"label": "文献对照", "color": "#c0392b"},
    "纳入对比": {"label": "纳入对比", "color": "#d35400"},
    "方法参考": {"label": "方法参考", "color": "#16a085"},
    "综合引用": {"label": "综合引用", "color": "#2980b9"},
    "深度报告": {"label": "深度报告", "color": "#8e44ad"},
    "支撑问题": {"label": "支撑问题", "color": "#f1c40f"},
    "概念-实体": {"label": "概念-实体", "color": "#6c5ce7"},
    "研究目标": {"label": "研究目标", "color": "#e74c3c"},
    "核心概念": {"label": "核心概念", "color": "#f39c12"},
    "对比文献": {"label": "对比文献", "color": "#e84393"},
    "综合文献": {"label": "综合文献", "color": "#00cec9"},
    "探讨概念": {"label": "探讨概念", "color": "#55efc4"},
    "同类关联": {"label": "同类关联", "color": "#95a5a6"},
    "链接": {"label": "链接", "color": "#b0a4ad"},
    "跨文献可比": {"label": "跨文献可比", "color": "#e67e22"},
    "实证支持": {"label": "实证支持", "color": "#27ae60"},
    "方法张力": {"label": "方法张力", "color": "#c0392b"},
    "互补证据": {"label": "互补证据", "color": "#16a085"},
}

# comparison/synthesis 页「显式关系」行 → 边类型
explicitrelmap = {
    "comparable": "跨文献可比",
    "supports": "实证支持",
    "tension": "方法张力",
    "complements": "互补证据",
    "consensus": "同类关联",
}
explicitrelpattern = re.compile(
    r"^-\s*(comparable|supports|tension|complements|consensus)\s*\|\s*(.+?)\s*\|\s*(.+?)(?:\s*\|\s*(.*))?$",
    re.M | re.I,
)

# 知识图谱分层 Y 锚定（0=顶，1=底）
graphlayers = {
    "purpose": 0.08,
    "rq": 0.22,
    "concept": 0.38,
    "entity": 0.38,
    "comparison": 0.48,
    "synthesis": 0.48,
    "experiment": 0.55,
    "query": 0.62,
    "source": 0.78,
    "analysis-report": 0.88,
    "unknown": 0.5,
}

wikilinkpattern = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
frontmatterpattern = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)

