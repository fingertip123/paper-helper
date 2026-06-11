---
type: concept
title: 双重差分（Difference-in-Differences, DiD）
aliases: [difference-in-differences, DiD, 双重差分, staggered DiD, 交错双重差分]
sources: [kaplaner-2025, zheng-2026]
tags: [方法, 因果识别]
created: 2026-06-10
updated: 2026-06-10
---

# 双重差分（Difference-in-Differences, DiD）

## 定义

利用处理组与对照组在政策冲击前后的差异之差，识别政策的因果效应的准实验方法。当处理在不同时间分批发生时，称交错 DiD（staggered DiD）。

## 核心要点

- 关键假设：平行趋势（parallel trends）。
- 本库中两项实证均依赖 DiD：
  - [[kaplaner-2025]]：标准 DiD，识别 [[acid-rain-program|酸雨计划]] 对 EPA 检查的影响。
  - [[zheng-2026]]：交错 DiD，识别 [[5v7h-highway|5V7H]] 分阶段建成对 [[dietary-quality|膳食质量]] 的影响。

## 与其他概念的关系

- 应用于：[[policy-triage]]、[[transport-infrastructure]] 的因果评估
- 对比：[[dasgupta-2020]] 的观测性调查识别

## 出处

- [[kaplaner-2025]]、[[zheng-2026]]
