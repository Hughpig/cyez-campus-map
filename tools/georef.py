# -*- coding: utf-8 -*-
"""模型坐标 ↔ 卫星影像 / 经纬度 的配准换算。

用途：把 model/campus.json 里的像素坐标贴到 2026 年卫星底图上，出对比图，
      供"逐栋精确化"时边改边核对。

用法：
    python tools/georef.py --site cam-007            # 出单地块对比图
    python tools/georef.py --site cam-007 --zoom 3   # 放大 3 倍
    python tools/georef.py --all                     # 全部地块拼一张总览
    python tools/georef.py --px 1219 1437            # 查一个模型像素点的经纬度

配准来源：model/campus.json 的 4 栋形状可靠建筑质心 ↔ OSM 2026 建筑质心，最小二乘仿射。
        只用 cam-001/009/010/011（剔除描摹本身错的 007/008/022）。
精度：残差 0.3~1.6 m（RMS 1.1 m），等效 0.2413 m/px、旋转 −3.42°。
      图纸对现实是仿射（有约 3% 各向异性），不是纯相似。v1 用 9 对控制点、RMS 8.4 m，
      是因为把描错的楼也当成真值了 —— 2026-10-27 重拟合。
"""
import argparse
import json
import math
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AFFINE = os.path.join(ROOT, "资料", "09_现状影像_2026", "georef_affine.json")
MOSAIC = os.path.join(ROOT, "资料", "09_现状影像_2026", "01_卫星拼接_校园_2026.jpg")
CAMPUS = os.path.join(ROOT, "model", "campus.json")

# 拼接图对应的瓦片窗口（z=19）；重抓图后必须同步改，见 资料/09_现状影像_2026/README.md
X0, Y0, Z = 438935, 214201, 19
TILE = 256
S = 156543.03392 * math.cos(math.radians(31.242)) / (2 ** Z)   # 米/像素 ≈ 0.2553


def load_transform():
    af = json.load(open(AFFINE, encoding="utf-8"))
    return np.array(af["A"], float), af["lat0"], af["lon0"]


def px_to_lonlat(P, A, lat0, lon0):
    """模型像素 → 经纬度。"""
    P = np.asarray(P, float)
    xm = A[0, 0] * P[..., 0] + A[0, 1] * P[..., 1] + A[0, 2]
    ym = A[1, 0] * P[..., 0] + A[1, 1] * P[..., 1] + A[1, 2]
    lon = lon0 + xm / (111320 * math.cos(math.radians(lat0)))
    lat = lat0 - ym / 111320
    return np.stack([lat, lon], -1)


def lonlat_to_mosaic(lat, lon):
    """经纬度 → 拼接图像素（x, y）。"""
    n = 2 ** Z
    lat = np.asarray(lat, float)
    lon = np.asarray(lon, float)
    x = (lon + 180.0) / 360.0 * n * TILE - X0 * TILE
    r = np.radians(lat)
    y = (1.0 - np.log(np.tan(r) + 1 / np.cos(r)) / math.pi) / 2.0 * n * TILE - Y0 * TILE
    return np.stack([x, y], -1)


def px_to_mosaic(P):
    """模型像素 → 拼接图像素（一步到位）。"""
    A, lat0, lon0 = load_transform()
    ll = px_to_lonlat(P, A, lat0, lon0)
    return lonlat_to_mosaic(ll[..., 0], ll[..., 1])


def mosaic_to_lonlat(x, y):
    n = 2 ** Z
    lon = (x + X0 * TILE) / (n * TILE) * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + Y0 * TILE) / (n * TILE)))))
    return lat, lon


def render(sites, box=None, zoom=1.0, out="_work/georef_check.jpg"):
    import cv2
    img = cv2.imdecode(np.fromfile(MOSAIC, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise SystemExit("找不到卫星拼接图：" + MOSAIC)
    canvas = img.copy()
    for st in sites:
        q = px_to_mosaic(st["polygon"]).astype(np.int32)
        col = (0, 0, 255) if st.get("kind") == "building" else (0, 200, 255)
        cv2.polylines(canvas, [q], True, col, 1, cv2.LINE_AA)
        cv2.putText(canvas, st["id"][4:], (int(q[:, 0].mean()) - 8, int(q[:, 1].mean()) - 3),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 200), 1, cv2.LINE_AA)
    if box is None:
        allp = np.vstack([px_to_mosaic(s["polygon"]) for s in sites])
        box = (allp[:, 0].min() - 30, allp[:, 1].min() - 30,
               allp[:, 0].max() + 30, allp[:, 1].max() + 30)
    x0, y0, x1, y1 = [int(v) for v in box]
    sub = canvas[max(0, y0):y1, max(0, x0):x1]
    if zoom != 1.0:
        sub = cv2.resize(sub, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_CUBIC)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    cv2.imencode(".jpg", sub, [int(cv2.IMWRITE_JPEG_QUALITY), 90])[1].tofile(out)
    return out, sub.shape


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", help="地块 id，如 cam-007")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--out", default=None)
    ap.add_argument("--px", nargs=2, type=float, help="查模型像素坐标 → 经纬度")
    a = ap.parse_args()

    if a.px:
        A, lat0, lon0 = load_transform()
        ll = px_to_lonlat(np.array([a.px]), A, lat0, lon0)[0]
        mp = px_to_mosaic(np.array([a.px]))[0]
        print(f"模型 px ({a.px[0]:.0f}, {a.px[1]:.0f})")
        print(f"  经纬度 {ll[0]:.6f}, {ll[1]:.6f}")
        print(f"  拼接图 px ({mp[0]:.0f}, {mp[1]:.0f})")
        return

    sites = json.load(open(CAMPUS, encoding="utf-8"))["sites"]
    if a.site:
        sites = [s for s in sites if s["id"] == a.site]
        if not sites:
            raise SystemExit("没有这个地块：" + a.site)
        out = a.out or f"_work/georef_{a.site}.jpg"
    elif a.all:
        out = a.out or "_work/georef_all.jpg"
    else:
        ap.error("给 --site / --all / --px 之一")
    path, shape = render(sites, zoom=a.zoom, out=out)
    print(f"已出图 {path}  {shape}")


if __name__ == "__main__":
    main()
