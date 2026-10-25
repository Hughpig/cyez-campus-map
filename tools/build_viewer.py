# -*- coding: utf-8 -*-
"""把 model/buildings/*.json 注入查看器模板，生成项目根目录的 viewer.html。
用法：python tools/build_viewer.py   （每次修改模型数据后运行一次）"""
import json, sys, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
BD = ROOT / "model" / "buildings"
TEMPLATE = ROOT / "tools" / "viewer_template.html"
OUT = ROOT / "viewer.html"

buildings = []
for fp in sorted(BD.glob("*.json")):
    if ".part" in fp.name:
        continue
    d = json.load(open(fp, encoding="utf-8"))
    src_dir = d["meta"]["sourceDir"]  # 如 资料/01_本部校区_改扩建方案/楼层平面
    # viewer.html 位于项目根目录，相对路径可直接引用
    d["coordinateSystem"]["sourceDirRel"] = src_dir.replace("\\", "/")
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
    pseudo = {
        "building": c["name"],
        "aliases": [],
        "isCampus": True,
        "meta": c["meta"],
        "coordinateSystem": dict(c["coordinateSystem"], sourceDirRel=c["meta"]["sourceDir"].replace("\\", "/")),
        "floors": [{
            "id": "总图", "levels": [], "sourceImage": c["meta"].get("sourceImageName", ""),
            "sourceImageFull": c["meta"]["sourceImageFull"],
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
print(f"已生成 {OUT}（{len(html)//1024} KB）")
