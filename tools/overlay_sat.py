# -*- coding: utf-8 -*-
"""把整张总平面图（线稿）按配准参数压到 2026 卫星拼接图上，出一张"图纸 vs 现状"对照图。

和 tools/georef.py 的区别：
  georef.py   只能叠 model/campus.json 里已有的地块多边形 —— 看的是"模型"准不准
  本工具        叠的是图纸原图线稿            —— 看的是"图纸"准不准

用法：
    python tools/overlay_sat.py                       # 全校园
    python tools/overlay_sat.py --box 1470 1130 1830 1470 --zoom 2.3 --out _work/x.jpg
    python tools/overlay_sat.py --color 255 45 45     # 换叠加色（BGR）

配准参数来自 资料/09_现状影像_2026/georef_affine.json（v2：4 栋楼质心，残差 1.1 m）。
"""
import argparse
import json
import os

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
AFFINE = os.path.join(ROOT, "资料", "09_现状影像_2026", "georef_affine.json")
MOSAIC = os.path.join(ROOT, "资料", "09_现状影像_2026", "01_卫星拼接_校园_2026.jpg")
DRAWING = os.path.join(ROOT, "资料", "08_方案三总平面图", "方案三总平面图_高清.jpg")

# 拼接图对应的瓦片窗口（z=19），重抓图后必须同步改，见 资料/09_现状影像_2026/README.md
X0, Y0, Z = 438935, 214201, 19
TILE = 256


def model_to_mosaic_matrix():
    """model px → 拼接图 px 的 2×3 仿射矩阵。"""
    af = json.load(open(AFFINE, encoding="utf-8"))
    A = np.array(af["A"], float)
    lat0, lon0 = af["lat0"], af["lon0"]

    def mosaic_of(lat, lon):
        n = 2 ** Z
        x = (lon + 180.0) / 360.0 * n * TILE - X0 * TILE
        r = np.radians(lat)
        y = (1.0 - np.log(np.tan(r) + 1 / np.cos(r)) / np.pi) / 2.0 * n * TILE - Y0 * TILE
        return np.array([x, y])

    # 用 A 的线性部分量出"模型 1px 对应拼接图多少 px"，再配一个平移把原点对上。
    STEP = 0.001                                     # 试探用的角度步长（度）
    o = mosaic_of(lat0, lon0)
    ex = mosaic_of(lat0, lon0 + STEP) - o            # 东西向位移（东为正）
    ny = mosaic_of(lat0 - STEP, lon0) - o            # 南北向位移（取南向，与坐标系的 y 向下一致）
    ex_u = ex / np.linalg.norm(ex)                   # 单位向量
    ny_u = ny / np.linalg.norm(ny)
    # 拼成"米 → 拼接图 px"的基：1° 经度 ≈ 111320*cos(lat0) 米，1° 纬度 ≈ 111320 米
    mx = np.linalg.norm(ex) / (111320.0 * np.cos(np.radians(lat0)) * STEP)
    my = np.linalg.norm(ny) / (111320.0 * STEP)
    L = np.array([[mx * ex_u[0], my * ny_u[0]],
                  [mx * ex_u[1], my * ny_u[1]]])
    M = np.zeros((2, 3))
    M[:, :2] = L @ A[:, :2]
    M[:, 2] = L @ A[:, 2] + o
    return M


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_work/drawing_on_satellite.jpg")
    ap.add_argument("--box", nargs=4, type=int, metavar=("X0", "Y0", "X1", "Y1"),
                    help="拼接图上的裁剪窗口")
    ap.add_argument("--zoom", type=float, default=1.0)
    ap.add_argument("--color", nargs=3, type=int, default=[255, 45, 45],
                    help="叠加色，BGR；默认偏红")
    ap.add_argument("--strength", type=float, default=0.8, help="线稿不透明度 0~1")
    a = ap.parse_args()

    import cv2

    M = model_to_mosaic_matrix().astype(np.float32)
    sat = cv2.imdecode(np.fromfile(MOSAIC, np.uint8), cv2.IMREAD_COLOR)
    dw = cv2.imdecode(np.fromfile(DRAWING, np.uint8), cv2.IMREAD_GRAYSCALE)
    if sat is None or dw is None:
        raise SystemExit("找不到卫星拼接图或图纸原图")

    ink = (255.0 - dw.astype(np.float32))
    warp = cv2.warpAffine(ink, M, (sat.shape[1], sat.shape[0]), flags=cv2.INTER_LINEAR, borderValue=0)
    alpha = np.clip(warp / 255.0 * 1.4, 0, 1)[..., None]
    out = sat.astype(np.float32) * (1 - alpha * a.strength) + \
        np.array(a.color, np.float32) * (alpha * a.strength)
    out = np.clip(out, 0, 255).astype(np.uint8)

    if a.box:
        x0, y0, x1, y1 = a.box
        out = out[max(0, y0):y1, max(0, x0):x1]
    if a.zoom != 1.0:
        out = cv2.resize(out, None, fx=a.zoom, fy=a.zoom, interpolation=cv2.INTER_CUBIC)

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    cv2.imencode(".jpg", out, [int(cv2.IMWRITE_JPEG_QUALITY), 92])[1].tofile(a.out)
    print("已出图 %s  %s" % (a.out, out.shape))


if __name__ == "__main__":
    main()
