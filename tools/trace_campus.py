# -*- coding: utf-8 -*-
"""按颜色分割从方案二总平面图提取建筑/场地精确轮廓，替换 campus.json 中的粗略多边形。
用法：python tools/trace_campus.py
方法：4x 放大 → 颜色掩膜（浅灰白=建筑/红=跑道/浅蓝=连廊/绿顶=圆形厅）→
      以现有粗略多边形质心为种子取连通域 → findContours + approxPolyDP 简化 → 换算回原图坐标。
替换前做面积比合理性检查（0.4~2.5 倍），异常则保留原多边形并报告。
"""
import json, cv2, numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IMG = ROOT / "资料/05_方案二_62页预览/page_06.gif"
F = 4  # 放大倍数

img = cv2.imdecode(np.fromfile(str(IMG), dtype=np.uint8), cv2.IMREAD_COLOR)  # BGR（中文路径需 imdecode）
assert img is not None
img = cv2.resize(img, None, fx=F, fy=F, interpolation=cv2.INTER_CUBIC)
H, W = img.shape[:2]
b, g, r = img[:, :, 0].astype(int), img[:, :, 1].astype(int), img[:, :, 2].astype(int)
mx = np.maximum(np.maximum(b, g), r); mn = np.minimum(np.minimum(b, g), r)
mean = (b + g + r) // 3

mask_building = ((mx - mn) < 30) & (mean > 172)
mask_track = ((r - g) > 40) & (r - b > 40) & (r > 120)
mask_blue = ((b - r) > 12) & (b > 175) & (g >= r)
mask_green = ((g - r) > 14) & ((g - b) > 14) & (g > 110)

def clean(m):
    k = np.ones((5, 5), np.uint8)
    m = cv2.morphologyEx(m.astype(np.uint8) * 255, cv2.MORPH_CLOSE, k)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    return m

masks = {"building": clean(mask_building), "track": clean(mask_track),
         "blue": clean(mask_blue), "green": clean(mask_green)}

def poly_area(p):
    s = 0.0
    for i in range(len(p)):
        x1, y1 = p[i]; x2, y2 = p[(i + 1) % len(p)]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2

def trace(poly, mask_key, pad=10, eps=5, seed=None, bbox=None):
    """在 poly 的 bbox（外扩 pad 原图px）内取 mask 连通域（含种子）的最大外轮廓，返回原图坐标多边形。
    seed：可选的原图坐标种子点（用于环形跑道等质心不在掩膜上的形状）。"""
    m = masks[mask_key]
    if bbox:
        x0, y0, x1, y1 = [int(v * F) for v in bbox]
    else:
        xs = [p[0] for p in poly]; ys = [p[1] for p in poly]
        x0, x1 = max(0, int((min(xs) - pad) * F)), min(W, int((max(xs) + pad) * F))
        y0, y1 = max(0, int((min(ys) - pad) * F)), min(H, int((max(ys) + pad) * F))
    crop = m[y0:y1, x0:x1]
    n, labels = cv2.connectedComponents(crop)
    # 种子：默认原多边形质心；若落在掩膜外则找最近掩膜像素
    sx, sy = seed if seed else (sum(p[0] for p in poly) / len(poly), sum(p[1] for p in poly) / len(poly))
    cx = int(sx * F - x0); cy = int(sy * F - y0)
    lab = 0
    for rad in (0, 6, 14, 28, 50):
        yy0, yy1 = max(0, cy - rad), min(crop.shape[0], cy + rad + 1)
        xx0, xx1 = max(0, cx - rad), min(crop.shape[1], cx + rad + 1)
        sub = labels[yy0:yy1, xx0:xx1]
        vals = sub[sub > 0]
        if len(vals):
            lab = np.bincount(vals.flatten()).argmax()
            break
    if lab == 0:
        return None
    comp = (labels == lab).astype(np.uint8) * 255
    cnts, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    ap = cv2.approxPolyDP(c, eps, True).reshape(-1, 2)
    pts = [[round((x0 + x) / F, 1), round((y0 + y) / F, 1)] for x, y in ap]
    return pts if len(pts) >= 3 else None

campus_p = ROOT / "model/campus.json"
c = json.load(open(campus_p, encoding="utf-8"))

PLAN = {  # site id -> (mask, pad, eps)
    "cam-001": ("building", 12, 5),  # 体育馆
    "cam-002": ("building", 10, 5),  # 体育馆附楼
    "cam-003": ("building", 10, 5),  # 文杰楼
    "cam-004": ("building", 10, 5),  # 文心楼
    "cam-005": ("building", 10, 5),  # 行政楼
    "cam-006": ("building", 10, 4, (484, 433)),  # 公寓楼（折形；质心在中庭，用带上定点做种子）
    "cam-007": ("building", 12, 5),  # 综合楼主楼
    "cam-008": ("green",   10, 4),   # 综合楼圆形厅（绿顶）
    "cam-009": ("building", 14, 5, (694, 155), (650, 95, 742, 182)),  # 国际部整组（种子在圆厅）
    "cam-010": ("building", 8, 3),   # 国际部椭圆厅
    "cam-020": ("building", 10, 5),  # 未识别北楼
    "cam-021": ("building", 10, 5),  # 未识别中楼
    "cam-011": ("building", 8, 4, (534, 267)),  # 综合楼北翼
    "cam-022": ("building", 8, 4, (728, 96)),  # 东北弧楼
    "cam-030": ("track",   14, 8, (381, 99)),  # 跑道外缘（种子放在环带上，质心是草地）
    "cam-033": ("building", 10, 5),  # 文杰广场圆坛（浅色铺装圆）
    "cam-034": ("building", 10, 5),  # 综合楼前广场台阶
    "cam-040": ("blue",    6, 3),    # 连廊东西
    "cam-041": ("blue",    6, 3),    # 连廊南北
}

report, removed = [], []
new_sites = []
for s in c["sites"]:
    if s["id"] == "cam-035":  # 自行车棚（实为道路）删除
        removed.append(s["name"]); continue
    if s["id"] in PLAN:
        mk, pad, eps = PLAN[s["id"]][:3]
        seed = PLAN[s["id"]][3] if len(PLAN[s["id"]]) > 3 else None
        bbox = PLAN[s["id"]][4] if len(PLAN[s["id"]]) > 4 else None
        old_area = poly_area(s["polygon"])
        pts = trace(s["polygon"], mk, pad, eps, seed, bbox)
        if pts:
            new_area = poly_area(pts)
            ratio = new_area / old_area if old_area else 0
            if 0.35 <= ratio <= 2.8:
                s["polygon"] = pts
                report.append(f"  ✓ {s['id']} {s['name']}: {len(pts)}点, 面积比{ratio:.2f}")
            else:
                report.append(f"  ! {s['id']} {s['name']}: 面积比{ratio:.2f}异常，保留原多边形")
        else:
            report.append(f"  ! {s['id']} {s['name']}: 未取到轮廓，保留原多边形")
    new_sites.append(s)
c["sites"] = new_sites
c["notes"].append("建筑/跑道/连廊轮廓由颜色分割自动提取（tools/trace_campus.py），像素级贴合底图；'自行车棚'site 已删（实为道路）")

json.dump(c, open(campus_p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("已删除:", removed)
print("\n".join(report))
