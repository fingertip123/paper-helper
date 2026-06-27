#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文献原文提取（PDF / docx / 文本），含扫描版 OCR 回退。"""
import logging

logger = logging.getLogger(__name__)

_NMIN_TEXT = 200
_NOCR_MAX_PAGES = 8


def _ExtractTextFile(nfullpath):
    with open(nfullpath, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _ExtractDocx(nfullpath):
    from docx import Document
    odoc = Document(nfullpath)
    return "\n".join(p.text for p in odoc.paragraphs if p.text.strip())


def _ExtractPdfPdfminer(nfullpath):
    from pdfminer.high_level import extract_text
    return extract_text(nfullpath) or ""


def _ExtractPdfPymupdf(nfullpath):
    try:
        import fitz
    except ImportError:
        return ""
    try:
        odoc = fitz.open(nfullpath)
        vparts = []
        for i in range(len(odoc)):
            vparts.append(odoc[i].get_text() or "")
        odoc.close()
        return "\n".join(vparts)
    except Exception as e:
        logger.debug("pymupdf 提取失败：%s", e)
        return ""


def _ExtractPdfOcr(nfullpath, nmaxpages=_NOCR_MAX_PAGES):
    try:
        import fitz
        import pytesseract
        from PIL import Image
        import io
    except ImportError:
        return ""
    try:
        odoc = fitz.open(nfullpath)
        vparts = []
        nlimit = min(len(odoc), nmaxpages)
        for i in range(nlimit):
            opix = odoc[i].get_pixmap(dpi=200)
            oimg = Image.open(io.BytesIO(opix.tobytes("png")))
            vparts.append(pytesseract.image_to_string(oimg, lang="eng+chi_sim") or "")
        odoc.close()
        return "\n".join(vparts)
    except Exception as e:
        logger.debug("OCR 提取失败：%s", e)
        return ""


def ExtractPaperText(nfullpath, buserocr=True):
    slow = nfullpath.lower()
    if slow.endswith((".md", ".txt")):
        return _ExtractTextFile(nfullpath)
    if slow.endswith(".docx"):
        return _ExtractDocx(nfullpath)

    stext = _ExtractPdfPdfminer(nfullpath)
    if len(stext.strip()) >= _NMIN_TEXT:
        return stext

    spymupdf = _ExtractPdfPymupdf(nfullpath)
    if len(spymupdf.strip()) > len(stext.strip()):
        stext = spymupdf

    if len(stext.strip()) >= _NMIN_TEXT or not buserocr:
        return stext

    socr = _ExtractPdfOcr(nfullpath)
    if len(socr.strip()) > len(stext.strip()):
        return socr
    return stext
