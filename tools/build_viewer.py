# -*- coding: utf-8 -*-
"""把 model/buildings/*.json 注入查看器模板，生成项目根目录的 viewer.html。
用法：python tools/build_viewer.py   （每次修改模型数据后运行一次）

叠加原图处理：模型里 sourceImage 指向 资料/ 下的原图（不入库）。本脚本把每张被
引用的图生成压缩 JPEG 副本到 img/（长边≤1400px），并把 viewer 的叠加路径指向副本，
使 viewer.html 在本地双击与 GitHub Pages 上都能显示叠加。"""
import json, sys, io
from pathlib import Path

import cv2
import numpy as np

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
BD = ROOT / "model" / "buildings"
TEMPLATE = ROOT / "tools" / "viewer_template.html"
OUT = ROOT / "viewer.html"
IMG_DIR = ROOT / "img"


def prep_image(src_rel, out_name, max_side=1400, quality=80):
    """把 资料/ 下的原图生成/刷新压缩副本 img/<out_name>，返回相对路径；缺失返回 None。"""
    src = ROOT / src_rel
    if not src.exists():
        print(f"  [warn] 叠加原图缺失：{src_rel}")
        return None
    IMG_DIR.mkdir(exist_ok=True)
    out = IMG_DIR / out_name
    if (not out.exists()) or out.stat().st_mtime < src.stat().st_mtime:
        im = cv2.imdecode(np.fromfile(str(src), dtype=np.uint8), cv2.IMREAD_COLOR)
        if im is None:
            print(f"  [warn] 叠加原图无法解码：{src_rel}")
            return None
        h, w = im.shape[:2]
        sc = min(1.0, max_side / max(h, w))
        if sc < 1.0:
            im = cv2.resize(im, (max(1, round(w * sc)), max(1, round(h * sc))),
                            interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", im, [cv2.IMWRITE_JPEG_QUALITY, quality])
        if not ok:
            return None
        buf.tofile(str(out))
    return f"img/{out_name}"


buildings = []
img_total = 0
for bi, fp in enumerate(sorted(BD.glob("*.json")), 1):
    if ".part" in fp.name:
        continue
    d = json.load(open(fp, encoding="utf-8"))
    src_dir = d["meta"]["sourceDir"]  # 如 资料/01_本部校区_改扩建方案/楼层平面
    # viewer.html 位于项目根目录，相对路径可直接引用
    d["coordinateSystem"]["sourceDirRel"] = src_dir.replace("\\", "/")
    for fi, fl in enumerate(d["floors"], 1):
        rel = fl.get("sourceImageFull")  # 完整相对路径优先（如图不在本楼 sourceDir 下）
        if not rel:
            si = fl.get("sourceImage")
            rel = f"{src_dir}/{si}".replace("\\", "/") if si else None
        if not rel:
            continue
        full = prep_image(rel, f"b{bi:02d}f{fi:02d}.jpg")
        if full:
            fl["sourceImageFull"] = full
    buildings.append(d)
    n_rooms = sum(len(f["rooms"]) for f in d["floors"])
    print(f"  载入 {d['building']}: {len(d['floors'])} 层 {n_rooms} 房间")

# 校园总图（若有）作为列表第一项；site 带 linkTo 时可点击跳转到对应楼栋
campus_fp = ROOT / "model" / "campus.json"
if campus_fp.exists():
    c = json.load(open(campus_fp, encoding="utf-8"))
    kind_map = {"building": "other", "sport": "gym", "garden": "courtyard",
                "plaza": "courtyard", "gate": "entrance", "other": "other"}
    rooms = []
    for s in c["sites"]:
        r = {"id": s["id"], "name": s["name"], "type": kind_map.get(s["kind"], "other"),
             "polygon": s["polygon"], "confidence": s.get("confidence", "medium"),
             "note": (("[%s] " % s["kind"]) if s["kind"] != "building" else "") + (s.get("note") or "")}
        if s.get("linkTo"):
            r["linkTo"] = s["linkTo"]
        rooms.append(r)
    campus_img = prep_image(c["meta"]["sourceImageFull"], "campus.jpg")
    pseudo = {
        "building": c["name"],
        "aliases": [],
        "isCampus": True,
        "meta": c["meta"],
        "coordinateSystem": dict(c["coordinateSystem"], sourceDirRel=c["meta"]["sourceDir"].replace("\\", "/")),
        "floors": [{
            "id": "总图", "levels": [], "sourceImage": c["meta"].get("sourceImageName", ""),
            "sourceImageFull": campus_img or c["meta"]["sourceImageFull"],
            "pdfPage": None,
            "imageSize": c["coordinateSystem"]["imageSize"],
            "outline": c["outline"], "grid": {"vertical": [], "horizontal": []},
            "rooms": rooms, "openings": [], "vertical": [], "notes": c.get("notes", []),
        }],
    }
    buildings.insert(0, pseudo)
    print(f"  载入 {c['name']}: {len(rooms)} 个地块（含 {sum(1 for r in rooms if 'linkTo' in r)} 个可跳转楼栋）")

model = {"buildings": buildings}
tpl = open(TEMPLATE, encoding="utf-8").read()
assert "/*__MODEL_DATA__*/null" in tpl, "模板缺少数据占位符"
html = tpl.replace("/*__MODEL_DATA__*/null", json.dumps(model, ensure_ascii=False))
open(OUT, "w", encoding="utf-8").write(html)
if IMG_DIR.exists():
    img_total = sum(f.stat().st_size for f in IMG_DIR.glob("*.jpg"))
print(f"已生成 {OUT}（{len(html)//1024} KB）；img/ 压缩叠加图 {img_total//1024} KB")
