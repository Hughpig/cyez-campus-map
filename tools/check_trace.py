#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图纸贴合度体检：模型地块多边形 vs 2026-10 底图墨线。

原理：把底图二值化取"墨线"，做欧氏距离变换；再沿每个地块的每条边按步长采样，
查每个采样点到最近墨线的距离。描摹准确的地块，边基本压在墨线上，平均距离 < 2px。

用法：
    python tools/check_trace.py                 # 全部地块，只列汇总表
    python tools/check_trace.py -v              # 附每条边的明细（定位是哪条边偏了）
    python tools/check_trace.py --id cam-006    # 只看某几个地块，可重复
    python tools/check_trace.py --top 8         # 只看最差的 8 个
    python tools/check_trace.py --out x.jpg     # 出标记图：把超差边画成红色放大

判定阈值（像素，底图 1528×1080，线宽约 1~2px；0.24 m/px 折算见 --mpp）：
    < 2.0  ok      压线
    2~5    可接受   半个线宽到 1.2m 内
    5~10   偏       需要看一眼
    > 10   差       基本可以确定描错了

注意：图上本来就没有线的地块（纯文字标注的空地、虚线范围）会被误报为"差"，
所以结果要配合 --out 出图看一眼再改。
"""
import argparse
import json
import os
import sys

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMPUS = os.path.join(ROOT, "model", "campus.json")

INK_THR = 200          # 灰度低于此值算墨线（CAD 细线在 JPEG 里是 190~220 的浅灰，
                       # 阈值取 120 会把大部分线当背景，只有文字和粗黑线剩下）
SAMPLE_STEP = 1.5      # 沿边采样步长（px）
OK, WARN, BAD = 2.0, 5.0, 10.0


def load_ink(path):
    g = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_GRAYSCALE)
    if g is None:
        sys.exit("无法读取底图：%s" % path)
    # 不要做形态学开运算：1px 的 CAD 细线会被整个抹掉，半线宽就变成了 3~20px 的假偏差
    ink = (g < INK_THR).astype(np.uint8)
    dist = cv2.distanceTransform(1 - ink, cv2.DIST_L2, 5)
    return g, ink, dist


def sample_edge(p0, p1, step=SAMPLE_STEP):
    """沿线段等距采样，返回 (N,2) 点阵（含两端点，不含重复的终点）"""
    a = np.asarray(p0, float)
    b = np.asarray(p1, float)
    L = float(np.hypot(*(b - a)))
    n = max(2, int(np.ceil(L / step)) + 1)
    t = np.linspace(0.0, 1.0, n)
    return a[None, :] + t[:, None] * (b - a)[None, :], L


def edge_stats(dist, p0, p1):
    pts, L = sample_edge(p0, p1)
    xs = np.clip(pts[:, 0], 0, dist.shape[1] - 1)
    ys = np.clip(pts[:, 1], 0, dist.shape[0] - 1)
    d = dist[np.round(ys).astype(int), np.round(xs).astype(int)]
    return {
        "len": L,
        "mean": float(d.mean()),
        "med": float(np.median(d)),
        "p90": float(np.percentile(d, 90)),
        "max": float(d.max()),
        "off": float((d > WARN).mean()),   # 超差采样点占比
        "pts": pts,
        "d": d,
    }


def poly_stats(dist, poly):
    edges = []
    n = len(poly)
    for i in range(n):
        edges.append(edge_stats(dist, poly[i], poly[(i + 1) % n]))
    lens = np.array([e["len"] for e in edges])
    w = lens / lens.sum()
    mean = float((np.array([e["mean"] for e in edges]) * w).sum())
    return {
        "edges": edges,
        "mean": mean,                                    # 按边长加权的平均距离
        "med": float(np.median([e["med"] for e in edges])),
        "p90": float(np.percentile([e["p90"] for e in edges], 90)),
        "max": float(max(e["max"] for e in edges)),
        "off": float((np.array([e["off"] for e in edges]) * w).sum()),
        "n": n,
    }


def grade(v):
    if v < OK:
        return "ok"
    if v < WARN:
        return "可接受"
    if v < BAD:
        return "偏"
    return "差"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每条边明细")
    ap.add_argument("--id", action="append", help="只看指定地块，可重复")
    ap.add_argument("--top", type=int, default=0, help="只列最差的 N 个")
    ap.add_argument("--mpp", type=float, default=0.24, help="每像素米数，用于折算（默认 0.24）")
    ap.add_argument("--out", help="出标记图（超差边画红、正常边画绿）")
    ap.add_argument("--json", help="把结果写成 json")
    args = ap.parse_args()

    d = json.load(open(CAMPUS, encoding="utf-8"))
    src = d["meta"]["sourceImageFull"]
    if not os.path.isabs(src):
        src = os.path.join(ROOT, src)
    g, ink, dist = load_ink(src)
    print("底图 %s  %dx%d  墨线像素 %d" % (os.path.basename(src), g.shape[1], g.shape[0], int(ink.sum())))

    items = []
    for s in d["sites"]:
        poly = s.get("polygon") or []
        if len(poly) < 3:
            continue
        items.append((s, poly_stats(dist, poly)))
    ol = (d.get("outline") or {}).get("polygon")
    if ol and len(ol) >= 3:
        items.append(({"id": "OUTLINE", "name": "校园边界", "kind": "outline"}, poly_stats(dist, ol)))

    if args.id:
        want = set(args.id)
        items = [it for it in items if it[0]["id"] in want or it[0]["id"] in ("OUTLINE",)]
    items.sort(key=lambda kv: -kv[1]["mean"])
    if args.top:
        items = items[: args.top]

    hdr = "%-9s %-22s %3s %7s %6s %6s %6s %7s  %s" % (
        "id", "名称", "边", "平均px", "中位", "p90", "最大", "超差%", "判级")
    print("\n" + hdr)
    print("-" * len(hdr))
    for s, st in items:
        print("%-9s %-22s %3d %7.2f %6.2f %6.2f %6.2f %6.0f%%  %s" % (
            s["id"], (s.get("name") or "")[:22], st["n"], st["mean"], st["med"],
            st["p90"], st["max"], st["off"] * 100, grade(st["mean"])))
    print("\n折算（%.2f m/px）：平均距离 > %.1f px 即 > %.1f m" % (args.mpp, BAD, BAD * args.mpp))

    if args.verbose:
        for s, st in items:
            worst = sorted(range(st["n"]), key=lambda i: -st["edges"][i]["mean"])[:3]
            print("\n[%s] %s  平均 %.2f px" % (s["id"], s.get("name"), st["mean"]))
            for i in worst:
                e = st["edges"][i]
                p0 = np.asarray(s["polygon"][i] if s["id"] != "OUTLINE" else ol[i], float)
                p1 = np.asarray(s["polygon"][(i + 1) % st["n"]] if s["id"] != "OUTLINE" else ol[(i + 1) % st["n"]], float)
                print("   边%-2d %s→%s 长%5.1f  平均%6.2f  p90%6.2f  超差%.0f%%" % (
                    i, p0.round(0).astype(int).tolist(), p1.round(0).astype(int).tolist(),
                    e["len"], e["mean"], e["p90"], e["off"] * 100))

    if args.out:
        vis = cv2.imdecode(np.fromfile(src, np.uint8), cv2.IMREAD_COLOR)
        for s, st in items:
            poly = s["polygon"] if s["id"] != "OUTLINE" else ol
            for i in range(st["n"]):
                e = st["edges"][i]
                p0 = tuple(np.round(poly[i]).astype(int).tolist())
                p1 = tuple(np.round(poly[(i + 1) % st["n"]]).astype(int).tolist())
                col = (0, 0, 235) if e["mean"] >= BAD else ((0, 165, 255) if e["mean"] >= WARN else (0, 150, 0))
                cv2.line(vis, p0, p1, col, 2, cv2.LINE_AA)
            c = np.mean(np.asarray(poly, float), axis=0).astype(int)
            cv2.putText(vis, "%s %.0f" % (s["id"].replace("cam-", ""), st["mean"]),
                        (c[0] - 16, c[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 0, 200), 1, cv2.LINE_AA)
        cv2.imencode(".jpg", vis, [int(cv2.IMWRITE_JPEG_QUALITY), 90])[1].tofile(args.out)
        print("已出图 %s" % args.out)

    if args.json:
        out = {s["id"]: {k: st[k] for k in ("mean", "med", "p90", "max", "off", "n")}
               for s, st in items}
        json.dump(out, open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("已写 %s" % args.json)

    bad = [s["id"] for s, st in items if st["mean"] >= BAD]
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
