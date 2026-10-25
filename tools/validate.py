# -*- coding: utf-8 -*-
"""校验 model/buildings/*.json 的结构与引用一致性。用法：python tools/validate.py"""
import json, sys, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
BD = Path(__file__).resolve().parent.parent / "model" / "buildings"

TYPES = {"classroom","lab","lecture","music","art","library","reading","auditorium",
         "office","meeting","admin","dorm","dorm-utility","dining","kitchen","gym",
         "hall","corridor","stairs","elevator","entrance","toilet","storage","equipment",
         "parking","circulation-helper","courtyard","other"}

errors, warns = [], []
files = sorted(p for p in BD.glob("*.json") if ".part" not in p.name)

for fp in files:
    b = json.load(open(fp, encoding="utf-8"))
    bname = fp.stem
    ids = set()
    for f in b["floors"]:
        fid = f["id"]
        tag = f"{bname}/{fid}"
        # 结构
        for key in ("id","levels","sourceImage","pdfPage","outline","grid","rooms","openings","vertical"):
            if key not in f: errors.append(f"{tag}: 缺字段 {key}")
        # outline
        if len(f.get("outline",{}).get("polygon",[])) < 3:
            errors.append(f"{tag}: outline 少于3点")
        # rooms
        img_w, img_h = f.get("imageSize", [1164, 873])
        for r in f.get("rooms", []):
            rid = r.get("id","")
            if rid in ids: errors.append(f"{tag}: 房间id重复 {rid}")
            ids.add(rid)
            if len(r.get("polygon",[])) < 3: errors.append(f"{rid}: polygon少于3点")
            if r.get("type") not in TYPES:
                errors.append(f"{rid}: 非法type {r.get('type')}")
            for x,y in r.get("polygon",[]):
                if not (-5 <= x <= img_w+5 and -5 <= y <= img_h+5):
                    errors.append(f"{rid}: 坐标越界 ({x},{y})"); break
            if not r.get("name"): warns.append(f"{rid}: 空name")
        # openings 引用
        for o in f.get("openings", []):
            for rid in o.get("between", []):
                if rid != "outside" and rid not in ids:
                    errors.append(f"{tag}: opening 引用不存在的房间 {rid}")
        # vertical 引用
        for v in f.get("vertical", []):
            if v.get("roomId") and v["roomId"] not in ids:
                errors.append(f"{tag}: vertical 引用不存在的房间 {v['roomId']}")
        # outline 是否包含所有房间（粗查：房间bbox应在outline bbox内留裕量）
        op = f["outline"]["polygon"]
        obx = [p[0] for p in op]; oby = [p[1] for p in op]
        for r in f.get("rooms", []):
            rx = [p[0] for p in r["polygon"]]; ry = [p[1] for p in r["polygon"]]
            if min(rx) < min(obx)-30 or max(rx) > max(obx)+30 or min(ry) < min(oby)-30 or max(ry) > max(oby)+30:
                warns.append(f"{r['id']}: 房间bbox明显超出outline bbox（可能outline漏画该部分）")

print(f"检查 {len(files)} 个文件")
print(f"错误 {len(errors)} 个:")
for e in errors: print("  ✗", e)
print(f"警告 {len(warns)} 个:")
for w in warns: print("  ⚠", w)
sys.exit(1 if errors else 0)
