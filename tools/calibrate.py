# -*- coding: utf-8 -*-
"""按《投资估算表》各楼总面积，用外轮廓多边形面积反推每栋楼的 metersPerPixel。

用法：python tools/calibrate.py   （直接改写 model/buildings/*.json 的 metersPerPixel 字段）

标定依据（119页PDF p118 投资估算表）：
  综合楼（含地下车库） 12209 m² / 9 层
  宿舍楼（公寓楼）     6030  m² / 6 层
  行政楼（结构加固）   3100  m² / 3 层
  体育馆附楼：无总面积，但该图纸上有可读尺寸标注（4200/12000mm），转录代理已标 0.09 m/px，保留
  文杰楼 / 国际部综合楼 / 人文艺术楼：无面积锚点，用"同楼教室开间与已标定楼对比"估计
"""
import json, math, statistics, sys, io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
ROOT = Path(__file__).resolve().parent.parent
BD = ROOT / "model" / "buildings"

GFA = {  # 总建筑面积锚点（m²）
    "综合楼": 12209,
    "公寓楼": 6030,
    "行政楼": 3100,
}

def poly_area(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0

def bbox(poly):
    xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
    return max(xs) - min(xs), max(ys) - min(ys)

def load(name):
    return json.load(open(BD / name, encoding="utf-8"))

def save(name, d):
    json.dump(d, open(BD / name, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def set_scale(d, val, basis):
    d["coordinateSystem"]["metersPerPixel"] = round(val, 4)
    d["coordinateSystem"]["metersPerPixelBasis"] = basis

report = []

# 1) 有面积锚点的楼：s = sqrt(GFA / Σ(外轮廓像素面积×该图代表层数))
#    注意"标准层"一张图代表多个真实楼层，必须按 levels 数加权
for name, gfa in GFA.items():
    d = load(name + ".json")
    total_px = sum(poly_area(f["outline"]["polygon"]) * len(f["levels"]) for f in d["floors"])
    s = math.sqrt(gfa / total_px)
    set_scale(d, s, f"由投资估算表：全楼总面积{gfa}㎡，按各图代表层数加权的外轮廓像素面积合计{total_px:.0f}px² 反推（估计值，误差约±10%）")
    save(name + ".json", d)
    per_floor = {f["id"]: round(poly_area(f["outline"]["polygon"]) * s * s * len(f["levels"])) for f in d["floors"]}
    report.append((name, s, gfa, per_floor))

# 2) 体育馆附楼：保留代理按尺寸标注标的 0.09
d = load("体育馆附楼.json")
s_tygf = d["coordinateSystem"].get("metersPerPixel") or 0.09
report.append(("体育馆附楼", s_tygf, None, {f["id"]: round(poly_area(f["outline"]["polygon"]) * s_tygf ** 2) for f in d["floors"]}))

# 3) 无锚点的楼：教室/宿舍开间与已标定楼对比
def module_px(d, types):
    """取指定 type 房间的最大 bbox 边长中位数（px）"""
    dims = []
    for f in d["floors"]:
        for r in f["rooms"]:
            if r["type"] in types:
                w, h = bbox(r["polygon"])
                dims.append(max(w, h))
    return statistics.median(dims) if dims else None

s_zhl = report[0][1]
for name, ref, types in [("国际部综合楼", s_zhl, {"classroom"}), ("人文艺术楼", s_zhl, {"classroom", "art", "music"})]:
    d = load(name + ".json")
    m = module_px(d, types)
    refd = load("综合楼.json")
    mref = module_px(refd, {"classroom"})
    s = s_zhl * mref / m
    set_scale(d, s, f"无面积锚点：以本楼教室开间 {m:.0f}px 与综合楼教室开间 {mref:.0f}px（{s_zhl:.4f} m/px）对比估计，误差可能±15%")
    save(name + ".json", d)
    report.append((name, s, None, {f["id"]: round(poly_area(f["outline"]["polygon"]) * s * s) for f in d["floors"]}))

# 文杰楼：若行政楼与体育馆附楼比例接近，说明老楼图纸同比例，用行政楼的比例
d = load("文杰楼.json")
s_xzl = report[2][1]
s_wjl = s_xzl
set_scale(d, s_wjl, f"无面积锚点：老楼图纸（行政楼 {s_xzl:.4f} m/px 与体育馆附楼 {s_tygf:.4f} m/px 接近）按同比例估计，误差可能±15%")
save("文杰楼.json", d)
report.append(("文杰楼", s_wjl, None, {f["id"]: round(poly_area(f["outline"]["polygon"]) * s_wjl ** 2 * len(f["levels"])) for f in d["floors"]}))

print(f"{'楼名':<8} {'m/px':>8}  各图外轮廓面积×代表层数(m²)")
for name, s, gfa, per in report:
    fl = "  ".join(f"{k}:{v}" for k, v in per.items())
    anchor = f"(锚点{gfa}㎡)" if gfa else "(估计)"
    print(f"{name:<8} {s:>8.4f}  {anchor} {fl}")
