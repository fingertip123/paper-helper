#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成符合 macOS 规范的 app 图标（透明底、安全边距、无黑角）。

用法：python3 tools/build_icon.py
产出：assets/icon.png、icon.icns、icon.ico
"""
import os
import stat
import shutil
import struct
import subprocess
import sys

rootdir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
assetsdir = os.path.join(rootdir, "assets")
srcpath = os.path.join(assetsdir, "icon.png")
outpng = os.path.join(assetsdir, "icon.png")
outicns = os.path.join(assetsdir, "icon.icns")
outico = os.path.join(assetsdir, "icon.ico")
ntarget = 1024
ncontent = 0.82  # macOS 图标内容约占 82%，避免程序坞显得过大


def EnsurePillow():
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "pillow", "-q", "--break-system-packages"],
        )
        return True


def FixIcon():
    from PIL import Image

    if not os.path.isfile(srcpath):
        raise SystemExit("未找到 %s" % srcpath)
    oimg = Image.open(srcpath).convert("RGBA")
    ow, oh = oimg.size
    if ow != oh:
        nside = min(ow, oh)
        left = (ow - nside) // 2
        top = (oh - nside) // 2
        oimg = oimg.crop((left, top, left + nside, top + nside))

    # 黑角 / 深色背景 → 透明
    vdata = oimg.getdata()
    vnew = []
    for r, g, b, a in vdata:
        if r < 28 and g < 28 and b < 32:
            vnew.append((0, 0, 0, 0))
        else:
            vnew.append((r, g, b, a))
    oimg.putdata(vnew)

    ninner = int(ntarget * ncontent)
    oimg = oimg.resize((ninner, ninner), Image.Resampling.LANCZOS)
    ocanvas = Image.new("RGBA", (ntarget, ntarget), (0, 0, 0, 0))
    noffset = (ntarget - ninner) // 2
    ocanvas.paste(oimg, (noffset, noffset), oimg)
    ocanvas.save(outpng, "PNG")
    print("已生成 %s（%dx%d，透明底 + 安全边距）" % (outpng, ntarget, ntarget))


def BuildIcns():
    osetdir = os.path.join(assetsdir, "icon.iconset")
    if os.path.isdir(osetdir):
        shutil.rmtree(osetdir)
    os.makedirs(osetdir)
    vsizes = [16, 32, 128, 256, 512]
    for n in vsizes:
        subprocess.run(
            ["sips", "-z", str(n), str(n), outpng, "-o", "%s/icon_%dx%d.png" % (osetdir, n, n)],
            capture_output=True,
        )
        subprocess.run(
            ["sips", "-z", str(n * 2), str(n * 2), outpng, "-o", "%s/icon_%dx%d@2x.png" % (osetdir, n, n)],
            capture_output=True,
        )
    r = subprocess.run(["iconutil", "-c", "icns", osetdir, "-o", outicns], capture_output=True, text=True)
    shutil.rmtree(osetdir, ignore_errors=True)
    if r.returncode != 0:
        raise SystemExit("iconutil 失败：%s" % (r.stderr or r.stdout))
    print("已生成 %s" % outicns)


def BuildIco():
    opng256 = os.path.join(assetsdir, "_icon_256.png")
    subprocess.run(["sips", "-z", "256", "256", outpng, "-o", opng256], capture_output=True)
    with open(opng256, "rb") as f:
        png = f.read()
    hdr = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 22)
    with open(outico, "wb") as f:
        f.write(hdr + entry + png)
    os.remove(opng256)
    print("已生成 %s" % outico)


def Main():
    os.makedirs(assetsdir, exist_ok=True)
    EnsurePillow()
    FixIcon()
    if sys.platform == "darwin":
        BuildIcns()
    else:
        print("跳过 icon.icns（需在 macOS 上运行 iconutil）")
    BuildIco()


if __name__ == "__main__":
    Main()
