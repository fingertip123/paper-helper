#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OOXML 样式映射（从 docx_parser 拆分）。"""
import os
import re
import zipfile
import xml.etree.ElementTree as ET

WNS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": WNS}
ANS = "http://schemas.openxmlformats.org/drawingml/2006/main"

def _RgbToHex(orgb):
    if not orgb:
        return ""
    try:
        return "#%02x%02x%02x" % (orgb[0], orgb[1], orgb[2])
    except Exception:
        return ""


def _TwipsToPt(ntwips):
    return round(float(ntwips) / 20.0, 1)


def _ElemRPr(oelem):
    if oelem is None:
        return None
    return oelem.find("{%s}rPr" % WNS)


def _ElemPPr(oelem):
    if oelem is None:
        return None
    return oelem.find("{%s}pPr" % WNS)


def _LoadThemeFonts(scurrent):
    othemes = {}
    if not scurrent or not os.path.isfile(scurrent):
        return othemes
    try:
        with zipfile.ZipFile(scurrent, "r") as oz:
            spath = "word/theme/theme1.xml"
            if spath not in oz.namelist():
                return othemes
            oroot = ET.fromstring(oz.read(spath))
        for sprefix in ("major", "minor"):
            ofont = oroot.find(".//{%s}%sFont" % (ANS, sprefix))
            if ofont is None:
                continue
            for stag, skey in (("latin", "latin"), ("ea", "eastAsia"), ("cs", "cs")):
                oel = ofont.find("{%s}%s" % (ANS, stag))
                if oel is not None:
                    stype = (oel.get("typeface") or "").strip()
                    if stype:
                        othemes["%s_%s" % (sprefix, skey)] = stype
    except Exception:
        pass
    return othemes


def _ResolveThemeFontName(stheme_attr, othemes):
    if not stheme_attr or not othemes:
        return ""
    stheme_attr = stheme_attr.strip()
    smap = {
        "majorEastAsia": ("major", "eastAsia"),
        "minorEastAsia": ("minor", "eastAsia"),
        "majorHAnsi": ("major", "latin"),
        "minorHAnsi": ("minor", "latin"),
        "majorAscii": ("major", "latin"),
        "minorAscii": ("minor", "latin"),
        "majorBidi": ("major", "cs"),
        "minorBidi": ("minor", "cs"),
    }
    okey = smap.get(stheme_attr)
    if not okey:
        return ""
    return othemes.get("%s_%s" % okey) or ""


def _RFontsFromRPr(rpr, othemes=None):
    if rpr is None:
        return ""
    rf = rpr.find("{%s}rFonts" % WNS)
    if rf is None:
        return ""
    for sattr in ("eastAsia", "ascii", "hAnsi", "cs"):
        sval = rf.get("{%s}%s" % (WNS, sattr))
        if sval:
            return sval.strip()
    for sattr, stheme in (
        ("eastAsiaTheme", "majorEastAsia"),
        ("asciiTheme", "majorHAnsi"),
        ("hAnsiTheme", "majorHAnsi"),
        ("cstheme", "majorBidi"),
    ):
        sval = rf.get("{%s}%s" % (WNS, sattr))
        if sval:
            sresolved = _ResolveThemeFontName(sval, othemes)
            if sresolved:
                return sresolved
    return ""


def _SzPtFromRPr(rpr):
    if rpr is None:
        return None
    sz = rpr.find("{%s}sz" % WNS)
    if sz is None:
        return None
    sval = sz.get("{%s}val" % WNS)
    if not sval:
        return None
    try:
        return round(int(sval) / 2.0, 1)
    except Exception:
        return None


def _ColorFromRPr(rpr):
    if rpr is None:
        return ""
    ocolor = rpr.find("{%s}color" % WNS)
    if ocolor is None:
        return ""
    sval = (ocolor.get("{%s}val" % WNS) or "").strip().lower()
    if not sval or sval == "auto":
        return ""
    if sval == "000000":
        return "#000000"
    try:
        return "#%s" % sval[-6:].zfill(6)
    except Exception:
        return ""


def _FlagFromRPr(rpr, stag):
    if rpr is None:
        return False
    oel = rpr.find("{%s}%s" % (WNS, stag))
    if oel is None:
        return False
    sval = oel.get("{%s}val" % WNS)
    return sval is None or sval not in ("0", "false", "off")


def _JcValToCss(sval):
    return {
        "left": "left", "start": "left",
        "center": "center",
        "right": "right", "end": "right",
        "both": "justify", "distribute": "justify", "justify": "justify",
    }.get((sval or "").strip().lower(), "")


def _AlignEnumToCss(nalign):
    try:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        return {
            WD_ALIGN_PARAGRAPH.LEFT: "left",
            WD_ALIGN_PARAGRAPH.CENTER: "center",
            WD_ALIGN_PARAGRAPH.RIGHT: "right",
            WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
        }.get(nalign, "")
    except Exception:
        return ""


def _IndLayoutFromPPr(ppr):
    olayout = {}
    if ppr is None:
        return olayout
    oind = ppr.find("{%s}ind" % WNS)
    if oind is None:
        return olayout

    def _TwipsAttr(sattr):
        sval = oind.get("{%s}%s" % (WNS, sattr))
        if not sval:
            return None
        try:
            return _TwipsToPt(int(sval))
        except Exception:
            return None

    nleft = _TwipsAttr("left")
    nright = _TwipsAttr("right")
    nfirst = _TwipsAttr("firstLine")
    nhang = _TwipsAttr("hanging")
    if nleft is not None:
        olayout["left_pt"] = nleft
    if nright is not None:
        olayout["right_pt"] = nright
    if nhang is not None:
        olayout["hang_pt"] = nhang
        if nleft is None:
            olayout["left_pt"] = nhang
    elif nfirst is not None:
        if nfirst >= 0:
            olayout["first_pt"] = nfirst
        else:
            olayout["hang_pt"] = abs(nfirst)
            olayout["left_pt"] = olayout.get("left_pt", abs(nfirst))
    return olayout


def _SpacingLayoutFromPPr(ppr):
    olayout = {}
    if ppr is None:
        return olayout
    osp = ppr.find("{%s}spacing" % WNS)
    if osp is None:
        return olayout
    for sattr, skey in (("before", "space_before_pt"), ("after", "space_after_pt")):
        sval = osp.get("{%s}%s" % (WNS, sattr))
        if sval:
            try:
                olayout[skey] = _TwipsToPt(int(sval))
            except Exception:
                pass
    sline = osp.get("{%s}line" % WNS)
    if sline:
        try:
            nline = int(sline)
            srule = (osp.get("{%s}lineRule" % WNS) or "auto").lower()
            if srule == "auto":
                olayout["line_height"] = round(nline / 240.0, 2)
            else:
                olayout["line_height_pt"] = _TwipsToPt(nline)
        except Exception:
            pass
    return olayout


def _StylePPrRPr(opara):
    oppr, orpr = None, None
    try:
        if opara.style and opara.style._element is not None:
            oppr = _ElemPPr(opara.style._element)
            orpr = _ElemRPr(opara.style._element)
            if orpr is None and oppr is not None:
                orpr = _ElemRPr(oppr)
    except Exception:
        pass
    return oppr, orpr


def _ParaLayoutDict(opara, othemes=None):
    olayout = {}
    pf = opara.paragraph_format
    if pf.alignment is not None:
        scss = _AlignEnumToCss(pf.alignment)
        if scss:
            olayout["align"] = scss
    if pf.left_indent is not None:
        olayout["left_pt"] = round(pf.left_indent.pt, 1)
    if pf.right_indent is not None:
        olayout["right_pt"] = round(pf.right_indent.pt, 1)
    if pf.first_line_indent is not None:
        npt = round(pf.first_line_indent.pt, 1)
        if npt > 0:
            olayout["first_pt"] = npt
        elif npt < 0:
            olayout["hang_pt"] = abs(npt)
            olayout["left_pt"] = olayout.get("left_pt", abs(npt))
    if pf.space_before is not None:
        olayout["space_before_pt"] = round(pf.space_before.pt, 1)
    if pf.space_after is not None:
        olayout["space_after_pt"] = round(pf.space_after.pt, 1)
    if pf.line_spacing is not None:
        try:
            from docx.enum.text import WD_LINE_SPACING
            if pf.line_spacing_rule == WD_LINE_SPACING.MULTIPLE:
                olayout["line_height"] = round(float(pf.line_spacing), 2)
            else:
                olayout["line_height_pt"] = round(pf.line_spacing.pt, 1)
        except Exception:
            pass

    ppr = _ElemPPr(opara._element)
    if ppr is not None:
        ojc = ppr.find("{%s}jc" % WNS)
        if ojc is not None and "align" not in olayout:
            scss = _JcValToCss(ojc.get("{%s}val" % WNS))
            if scss:
                olayout["align"] = scss
        for skey, sval in _IndLayoutFromPPr(ppr).items():
            olayout.setdefault(skey, sval)
        for skey, sval in _SpacingLayoutFromPPr(ppr).items():
            olayout.setdefault(skey, sval)

    sppr, _ = _StylePPrRPr(opara)
    if sppr is not None:
        if "align" not in olayout:
            ojc = sppr.find("{%s}jc" % WNS)
            if ojc is not None:
                scss = _JcValToCss(ojc.get("{%s}val" % WNS))
                if scss:
                    olayout["align"] = scss
        for skey, sval in _IndLayoutFromPPr(sppr).items():
            olayout.setdefault(skey, sval)
        for skey, sval in _SpacingLayoutFromPPr(sppr).items():
            olayout.setdefault(skey, sval)
    return olayout


def _LayoutDictToCss(olayout):
    vstyles = []
    if olayout.get("align"):
        vstyles.append("text-align:%s" % olayout["align"])
    if olayout.get("left_pt") is not None:
        vstyles.append("margin-left:%gpt" % olayout["left_pt"])
    if olayout.get("right_pt") is not None:
        vstyles.append("margin-right:%gpt" % olayout["right_pt"])
    if olayout.get("first_pt") is not None:
        vstyles.append("text-indent:%gpt" % olayout["first_pt"])
    if olayout.get("hang_pt") is not None:
        nhang = olayout["hang_pt"]
        nleft = olayout.get("left_pt", nhang)
        vstyles.append("padding-left:%gpt" % nleft)
        vstyles.append("text-indent:-%gpt" % nhang)
    if olayout.get("space_before_pt") is not None:
        vstyles.append("margin-top:%gpt" % olayout["space_before_pt"])
    if olayout.get("space_after_pt") is not None:
        vstyles.append("margin-bottom:%gpt" % olayout["space_after_pt"])
    if olayout.get("line_height") is not None:
        vstyles.append("line-height:%s" % olayout["line_height"])
    elif olayout.get("line_height_pt") is not None:
        vstyles.append("line-height:%gpt" % olayout["line_height_pt"])
    return ";".join(vstyles)


def _ParaStyleCss(opara, othemes=None):
    return _LayoutDictToCss(_ParaLayoutDict(opara, othemes))


