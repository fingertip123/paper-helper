#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文献原文提取（PDF / docx / 文本）。"""


def ExtractPaperText(nfullpath):
    slow = nfullpath.lower()
    if slow.endswith((".md", ".txt")):
        with open(nfullpath, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if slow.endswith(".docx"):
        from docx import Document
        odoc = Document(nfullpath)
        return "\n".join(p.text for p in odoc.paragraphs if p.text.strip())
    from pdfminer.high_level import extract_text
    return extract_text(nfullpath) or ""
