# -*- coding: utf-8 -*-
"""抓取曹杨二中本部的卫星影像瓦片并拼接成一张图。

用途：在没有 2010 之后官方图纸的情况下，给校园地图提供"现状 + 可量距"的参照。
详见 资料/09_现状影像_2026/README.md。

依赖：numpy + opencv（中文路径解码用 imdecode/fromfile）。
瓦片源：ESRI World Imagery（免费、无需 key）。

用法：
    python tools/fetch_satellite.py                 # z=19，校园中心 ±260 m
    python tools/fetch_satellite.py --z 20          # 更清晰（约 0.128 m/px，瓦片数 ×4）
    python tools/fetch_satellite.py --out 资料/09_现状影像_2026/01_卫星拼接_校园_2026.jpg
"""
import argparse
import math
import os
import sys
import urllib.request

import cv2
import numpy as np

# 校园中心（OSM way 78905557 centroid 附近，梅川路 160 号）
LAT0, LON0 = 31.242066, 121.396660
TILE = ("https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}")
UA = {"User-Agent": "Mozilla/5.0 (campus-map research)"}


def deg2num(lat, lon, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    r = math.radians(lat)
    y = (1.0 - math.log(math.tan(r) + 1 / math.cos(r)) / math.pi) / 2.0 * n
    return x, y


def mpp(lat, z):
    """该纬度该层级的分辨率（米/像素）。"""
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** z)


def fetch(x, y, z, cache_dir):
    os.makedirs(cache_dir, exist_ok=True)
    fn = os.path.join(cache_dir, f"esri_{z}_{x}_{y}.jpg")
    if os.path.exists(fn) and os.path.getsize(fn) > 3000:
        return fn
    url = TILE.format(z=z, x=x, y=y)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read()
    with open(fn, "wb") as f:
        f.write(data)
    return fn


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--z", type=int, default=19, help="缩放层级，18~20 实用（默认 19）")
    ap.add_argument("--half", type=float, default=260.0, help="半幅边长（米），默认 260")
    ap.add_argument("--lat", type=float, default=LAT0)
    ap.add_argument("--lon", type=float, default=LON0)
    ap.add_argument("--out", default="sat_mosaic.jpg")
    ap.add_argument("--cache", default=".sat_cache")
    a = ap.parse_args()

    res = mpp(a.lat, a.z)
    n_tiles = max(1, int(math.ceil(2 * a.half / (256 * res))))
    cx, cy = deg2num(a.lat, a.lon, a.z)
    x0 = int(cx) - n_tiles // 2
    y0 = int(cy) - n_tiles // 2
    print(f"z={a.z} 分辨率 {res:.4f} m/px，取 {n_tiles}x{n_tiles} 瓦片，"
          f"覆盖约 {n_tiles * 256 * res:.0f} m")

    big = np.zeros((n_tiles * 256, n_tiles * 256, 3), np.uint8)
    for dy in range(n_tiles):
        for dx in range(n_tiles):
            x, y = x0 + dx, y0 + dy
            fn = fetch(x, y, a.z, a.cache)
            im = cv2.imdecode(np.fromfile(fn, np.uint8), cv2.IMREAD_COLOR)
            if im is None:
                print(f"  跳过损坏瓦片 {x},{y}")
                continue
            big[dy * 256:dy * 256 + im.shape[0], dx * 256:dx * 256 + im.shape[1]] = im
        print(f"  行 {dy + 1}/{n_tiles}")

    ok, buf = cv2.imencode(".jpg", big, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    buf.tofile(a.out)
    print(f"已写出 {a.out}（{big.shape[1]}x{big.shape[0]}，{res:.4f} m/px）")
    print(f"瓦片索引：X {x0}~{x0 + n_tiles - 1}  Y {y0}~{y0 + n_tiles - 1}  Z {a.z}")
    print("记住这组索引，换算像素→经纬度时要用（见 README §7）。")


if __name__ == "__main__":
    sys.exit(main())
