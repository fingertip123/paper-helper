#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文献研究阶段状态机（P2）：pending → await_deep → standard → deep。"""

STAGE_PENDING = "pending"
STAGE_AWAIT_DEEP = "await_deep"
STAGE_STANDARD = "standard"
STAGE_DEEP = "deep"

STAGE_RANK = {
    STAGE_PENDING: 1,
    STAGE_AWAIT_DEEP: 2,
    STAGE_STANDARD: 3,
    STAGE_DEEP: 4,
}

STAGE_LABELS = {
    STAGE_PENDING: "待纳入",
    STAGE_AWAIT_DEEP: "待进阶分析",
    STAGE_STANDARD: "标准分析",
    STAGE_DEEP: "深度分析",
}


def ResolveLibStage(bingested, bstandard, bdeep):
    """根据纳入/分析报告存在性解析阶段。"""
    if bdeep:
        return STAGE_DEEP
    if bstandard:
        return STAGE_STANDARD
    if bingested:
        return STAGE_AWAIT_DEEP
    return STAGE_PENDING


def StageRank(sstage):
    return STAGE_RANK.get(sstage or STAGE_PENDING, 1)


def StageLabel(sstage):
    return STAGE_LABELS.get(sstage or STAGE_PENDING, sstage or STAGE_PENDING)
