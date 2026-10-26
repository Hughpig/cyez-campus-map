# -*- coding: utf-8 -*-
"""数据体检：结构 / 引用 / 几何 / 底图 四类检查，覆盖 model/buildings/*.json 与 model/campus.json。

用法：
    python tools/validate.py        # 全量体检
    python tools/validate.py -v     # 额外打印每栋楼的统计

退出码：0 = 无错误（警告不影响退出码）；1 = 有错误。

零第三方依赖（不需要 opencv/numpy），任何机器上 `python tools/validate.py` 都能跑。
重叠与覆盖率用扫描线算法近似计算，精度 2px，足够发现真问题。

检查项：
  1. 结构：必填字段、type/kind 词表、顶点数、坐标越界（按该层 imageSize）
  2. 引用：房间 id 唯一、门洞/垂直交通引用的房间存在、campus.linkTo 指向真实楼栋
  3. 几何：多边形真自交（渲染成"蝴蝶结"的元凶）、零长度边、房间互相重叠、
          房间溢出外轮廓、楼层房间覆盖率
  4. 底图：原图是否存在、实际像素尺寸与该层 imageSize 是否一致
          （尺寸不一致会让"原图叠加"整体错位，这是历史踩过的坑）
"""
import json
import struct
import sys
import io
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
BD = ROOT / "model" / "buildings"
CAMPUS = ROOT / "model" / "campus.json"

TYPES = {"classroom", "lab", "lecture", "music", "art", "library", "reading", "auditorium",
         "office", "meeting", "admin", "dorm", "dorm-utility", "dining", "kitchen", "gym",
         "hall", "corridor", "stairs", "elevator", "entrance", "toilet", "storage", "equipment",
         "parking", "circulation-helper", "courtyard", "other"}
KINDS = {"building", "sport", "garden", "plaza", "gate", "other"}
DEFAULT_SIZE = [1164, 873]

STEP = 2.0                 # 扫描线步长（px）
OVERLAP_RATIO = 0.25       # 真重叠：交叠占较小房间 >25%
OVERLAP_MIN_PX2 = 500      # 且绝对面积 >500px²（过滤共边 1~2px 的误差）
NEST_RATIO = 0.50          # 小房间有 >50% 落在大房间里 = 嵌套（大房间≥2倍面积）
COVER_LOW = 0.80           # 房间覆盖率低于 80% → 可能漏房间
COVER_HIGH = 1.08          # 房间合计超出外轮廓 8% → 可能溢出

errors, warns, infos, passed = [], [], [], []


def E(cat, msg):
    errors.append((cat, msg))


def W(cat, msg):
    warns.append((cat, msg))


def I(cat, msg):
    infos.append((cat, msg))


def ok(msg):
    passed.append(msg)


# ---------------------------------------------------------------- 向量几何
def shoelace(poly):
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _cross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def _proper_intersect(a, b, c, d):
    d1 = _cross(c, d, a)
    d2 = _cross(c, d, b)
    d3 = _cross(a, b, c)
    d4 = _cross(a, b, d)
    return (d1 > 0) != (d2 > 0) and (d3 > 0) != (d4 > 0)


def self_intersections(poly):
    """返回真自交的边对。相邻边共享顶点属正常，已排除。"""
    n = len(poly)
    if n < 4:
        return []
    pts = [(float(p[0]), float(p[1])) for p in poly]
    bad = []
    for i in range(n):
        a, b = pts[i], pts[(i + 1) % n]
        for j in range(i + 1, n):
            c, d = pts[j], pts[(j + 1) % n]
            if len({a, b, c, d}) < 4:
                continue
            if _proper_intersect(a, b, c, d):
                bad.append((i, j))
    return bad


def degenerate_edges(poly, eps=0.01):
    n = len(poly)
    out = []
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if abs(x1 - x2) <= eps and abs(y1 - y2) <= eps:
            out.append(i)
    return out


def bbox(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def point_in_poly(pt, poly):
    """射线法，与自交多边形一起用没意义，仅用于轮廓内判断。"""
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


# ---------------------------------------------------------------- 扫描线（重叠/覆盖率）
def row_intervals(poly, y):
    """水平线 y 与多边形相交的 x 区间列表（even-odd）。"""
    xs = []
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 <= y < y2) or (y2 <= y < y1):
            xs.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
    xs.sort()
    out = []
    for i in range(0, len(xs) - 1, 2):
        if xs[i + 1] > xs[i]:
            out.append((xs[i], xs[i + 1]))
    return out


def merge_intervals(iv):
    if not iv:
        return []
    iv = sorted(iv)
    out = [list(iv[0])]
    for a, b in iv[1:]:
        if a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def overlap_length(iv1, iv2):
    """两组已排序区间的交叠总长。"""
    i = j = 0
    total = 0.0
    while i < len(iv1) and j < len(iv2):
        a1, b1 = iv1[i]
        a2, b2 = iv2[j]
        lo = max(a1, a2)
        hi = min(b1, b2)
        if hi > lo:
            total += hi - lo
        if b1 < b2:
            i += 1
        else:
            j += 1
    return total


def raster_report(items, outline_poly=None):
    """items = [(id, name, polygon, area)]。
    返回 (真重叠列表, 嵌套/弱重叠列表, 覆盖率)。用扫描线逐行求区间，不依赖第三方库。"""
    if not items:
        return [], [], 1.0
    all_y = [p[1] for _, _, poly, _ in items for p in poly]
    y_lo, y_hi = min(all_y), max(all_y)
    rows = {}
    box = {}
    for rid, name, poly, area in items:
        box[rid] = bbox(poly)
        per_row = {}
        y = y_lo + STEP / 2
        while y < y_hi:
            iv = row_intervals(poly, y)
            if iv:
                per_row[y] = iv
            y += STEP
        rows[rid] = per_row

    # 覆盖率：逐行合并所有房间区间
    union_area = 0.0
    outline_rows = {}
    if outline_poly:
        oy = [p[1] for p in outline_poly]
        y = min(oy) + STEP / 2
        while y < max(oy):
            iv = row_intervals(outline_poly, y)
            if iv:
                outline_rows[y] = iv
            y += STEP
    all_rows = set()
    for r in rows.values():
        all_rows.update(r.keys())
    for y in all_rows:
        merged = merge_intervals([iv for r in rows.values() for iv in r.get(y, [])])
        union_area += sum(b - a for a, b in merged) * STEP
    out_area = 0.0
    if outline_poly:
        for y, iv in outline_rows.items():
            out_area += sum(b - a for a, b in iv) * STEP
        out_area = max(out_area, shoelace(outline_poly))
    cover = union_area / out_area if out_area else 1.0

    # 两两重叠（先过 bbox 过滤，再按"嵌套 / 真重叠"分级）
    pair_warn, pair_info = [], []
    ids = [it[0] for it in items]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            ri, rj = items[i], items[j]
            bi, bj = box[ri[0]], box[rj[0]]
            if bi[2] <= bj[0] or bj[2] <= bi[0] or bi[3] <= bj[1] or bj[3] <= bi[1]:
                continue
            common = rows[ri[0]].keys() & rows[rj[0]].keys()
            inter = sum(overlap_length(rows[ri[0]][y], rows[rj[0]][y]) for y in common) * STEP
            if inter <= OVERLAP_MIN_PX2:
                continue
            small = min(ri[3], rj[3])
            big = max(ri[3], rj[3])
            ratio = inter / max(1.0, small)
            if ratio < 0.15:
                continue
            rec = (ri[0], ri[1], rj[0], rj[1], inter, ratio)
            if ratio >= NEST_RATIO and small < 0.5 * big:
                pair_info.append(rec)          # 小房间整个落在某个大分区里：多半是有意嵌套
            elif ratio >= OVERLAP_RATIO:
                pair_warn.append(rec)          # 面积相当的铺装互相压盖：多半是画错了
            else:
                pair_info.append(rec)
    return pair_warn, pair_info, cover


# ---------------------------------------------------------------- 图片尺寸（读文件头，零依赖）
def _jpeg_size(path):
    with open(path, "rb") as fh:
        fh.read(2)
        while True:
            b = fh.read(1)
            if not b:
                return None
            if b != b"\xff":
                continue
            m = fh.read(1)
            while m == b"\xff":
                m = fh.read(1)
            if not m:
                return None
            code = m[0]
            if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
                continue
            seg = fh.read(2)
            if len(seg) < 2:
                return None
            ln = struct.unpack(">H", seg)[0]
            if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                data = fh.read(5)
                h, w = struct.unpack(">HH", data[1:5])
                return w, h
            fh.seek(ln - 2, 1)


def image_size(path):
    try:
        with open(path, "rb") as fh:
            head = fh.read(32)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return w, h
        if head[:6] in (b"GIF87a", b"GIF89a"):
            w, h = struct.unpack("<HH", head[6:10])
            return w, h
        if head[:2] == b"BM":
            w, h = struct.unpack("<ii", head[18:26])
            return w, abs(h)
        if head[:2] == b"\xff\xd8":
            return _jpeg_size(path)
    except Exception:   # noqa: BLE001
        return None
    return None


# ---------------------------------------------------------------- 通用多边形检查
def check_polygon(cat, tag, poly, w, h):
    if not isinstance(poly, list) or len(poly) < 3:
        E(cat, f"{tag}: 顶点数 {len(poly) if isinstance(poly, list) else '非法'} < 3")
        return False, 0.0
    if any(not (isinstance(p, (list, tuple)) and len(p) == 2) for p in poly):
        E(cat, f"{tag}: 存在非 [x,y] 顶点")
        return False, 0.0
    for x, y in poly:
        if not (-5 <= x <= w + 5 and -5 <= y <= h + 5):
            E(cat, f"{tag}: 坐标越界 ({x},{y})，画布 {w}x{h}")
            return False, 0.0
    si = self_intersections(poly)
    if si:
        pairs = "、".join(f"边{i}-{j}" for i, j in si[:4])
        E("自交", f"{tag}: 多边形自交（{pairs}）→ 浏览器会渲染成蝴蝶结，必须重画")
    dg = degenerate_edges(poly)
    if dg:
        W("退化边", f"{tag}: 存在 {len(dg)} 条零长度边（顶点重复）")
    area = shoelace(poly)
    if area < 1:
        W("退化面", f"{tag}: 面积≈0（{area:.1f} px²）")
    return True, area


def resolve_source(f, b):
    """返回楼层底图的本地路径（可能不存在）。"""
    src = f.get("sourceImageFull")
    if src:
        p = ROOT / src
        if p.exists():
            return p
    sd = f.get("sourceDir") or (b.get("meta") or {}).get("sourceDir")
    si = f.get("sourceImage")
    if sd and si:
        p = ROOT / sd / si
        if p.exists():
            return p
    return None


# ---------------------------------------------------------------- 楼栋检查
def check_building(fp):
    b = json.load(open(fp, encoding="utf-8"))
    bname = fp.stem
    bid = b.get("building") or bname
    if bid != bname:
        W("命名", f"{fp.name}: building='{bid}' 与文件名不一致")
    if (b.get("coordinateSystem") or {}).get("metersPerPixel") is None:
        W("比例", f"{bid}: metersPerPixel 为空，米制面积不可用")

    floor_ids = set()
    room_ids_all = set()

    for f in b.get("floors", []):
        fid = f.get("id", "?")
        tag = f"{bid}/{fid}"
        if fid in floor_ids:
            E("结构", f"{tag}: 楼层 id 重复")
        floor_ids.add(fid)
        for key in ("id", "levels", "sourceImage", "pdfPage", "outline", "grid",
                    "rooms", "openings", "vertical"):
            if key not in f:
                E("结构", f"{tag}: 缺字段 {key}")
        w, h = f.get("imageSize") or DEFAULT_SIZE

        # 外轮廓
        outline = f.get("outline") or {}
        op = outline.get("polygon") or []
        outline_ok, outline_area = check_polygon("几何", f"{tag} 外轮廓", op, w, h)
        if op and not outline.get("note"):
            W("规范", f"{tag}: outline 没有 note（画法/来源说明）")

        # 房间
        ids = set()
        items = []
        for r in f.get("rooms", []):
            rid = r.get("id", "")
            if not rid:
                E("结构", f"{tag}: 有房间缺 id（name={r.get('name')!r}）")
                continue
            if rid in ids:
                E("结构", f"{tag}: 房间 id 重复 {rid}")
            ids.add(rid)
            room_ids_all.add(rid)
            if r.get("type") not in TYPES:
                E("结构", f"{rid}: 非法 type {r.get('type')!r}")
            if not r.get("name"):
                W("命名", f"{rid}: 空 name")
            good, area = check_polygon("几何", rid, r.get("polygon", []), w, h)
            if good:
                items.append((rid, r.get("name", ""), r["polygon"], area))
                # 房间质心是否落在本层外轮廓内
                if outline_ok:
                    pts = r["polygon"]
                    cx = sum(p[0] for p in pts) / len(pts)
                    cy = sum(p[1] for p in pts) / len(pts)
                    if not point_in_poly((cx, cy), op):
                        rb = bbox(pts)
                        ob = bbox(op)
                        if rb[2] > ob[2] + 10 or rb[0] < ob[0] - 10:
                            W("轮廓", f"{rid}: 质心在外轮廓之外（外轮廓可能漏画该部分）")

        # 门洞 / 垂直交通
        for o in f.get("openings", []):
            between = o.get("between", [])
            for rid in between:
                if rid != "outside" and rid not in ids:
                    E("引用", f"{tag}: 门洞引用了不存在的房间 {rid}")
            if len(between) != 2:
                W("结构", f"{tag}: 门洞 between 不是 2 个元素 {between}")
            at = o.get("at")
            if at and not (-5 <= at[0] <= w + 5 and -5 <= at[1] <= h + 5):
                W("几何", f"{tag}: 门洞位置越界 {at}")
        for v in f.get("vertical", []):
            if v.get("roomId") and v["roomId"] not in ids:
                E("引用", f"{tag}: 垂直交通引用了不存在的房间 {v['roomId']}")
            if not v.get("connects"):
                W("结构", f"{tag}: 垂直交通 {v.get('name', '?')} 没有 connects")

        # 重叠 + 覆盖率
        if items and outline_ok:
            pair_warn, pair_info, cover = raster_report(items, op)
            for a_id, a_name, b_id, b_name, px2, ratio in pair_warn:
                W("重叠", f"{tag}: {a_id}({a_name}) 与 {b_id}({b_name}) 重叠 "
                          f"{px2:.0f}px²（占较小房间 {ratio * 100:.0f}%）")
            for a_id, a_name, b_id, b_name, px2, ratio in pair_info:
                I("嵌套", f"{tag}: {a_id}({a_name}) 与 {b_id}({b_name}) 交叠 "
                          f"{px2:.0f}px²（{ratio * 100:.0f}%，多半是有意嵌套）")
            if cover < COVER_LOW:
                W("覆盖", f"{tag}: 房间只覆盖外轮廓的 {cover * 100:.0f}%"
                          f"（约 {100 - cover * 100:.0f}% 面积没录房间，可能漏了）")
            elif cover > COVER_HIGH:
                W("覆盖", f"{tag}: 房间合计超出外轮廓 {cover * 100 - 100:.0f}%（墙体或凸出体块画到轮廓外？）")

        # 底图
        src = resolve_source(f, b)
        if not src:
            W("底图", f"{tag}: 找不到原图（sourceImage={f.get('sourceImage')!r}）")
        else:
            shp = image_size(src)
            if shp:
                aw, ah = shp
                if f.get("imageSize") is None and [aw, ah] != DEFAULT_SIZE:
                    E("底图", f"{tag}: 原图实际 {aw}×{ah}，但楼层没写 imageSize"
                              f"（查看器按 {DEFAULT_SIZE[0]}×{DEFAULT_SIZE[1]} 画叠加框 → 整体错位）")
                elif f.get("imageSize"):
                    iw, ih = f["imageSize"]
                    if abs(aw / ah - iw / ih) / (iw / ih) > 0.02:
                        W("底图", f"{tag}: imageSize {iw}×{ih} 与原图 {aw}×{ah} 长宽比不符（>2%）")

    return b, bid, room_ids_all


# ---------------------------------------------------------------- 总图检查
def check_campus(building_names):
    if not CAMPUS.exists():
        W("结构", "没有 model/campus.json，跳过总图检查")
        return
    c = json.load(open(CAMPUS, encoding="utf-8"))
    cs = c.get("coordinateSystem") or {}
    w, h = cs.get("imageSize") or DEFAULT_SIZE
    if cs.get("metersPerPixel") is None:
        W("比例", "校园总图: metersPerPixel 未标定（面积/距离不可用）")

    sid = set()
    items = []
    for s in c.get("sites", []):
        tag = f"总图/{s.get('id', '?')} {s.get('name', '')}".strip()
        if s.get("id") in sid:
            E("结构", f"{tag}: site id 重复")
        sid.add(s.get("id"))
        if s.get("kind") not in KINDS:
            E("结构", f"{tag}: 非法 kind {s.get('kind')!r}")
        if not s.get("name"):
            W("命名", f"{tag}: 空 name")
        good, area = check_polygon("几何", tag, s.get("polygon", []), w, h)
        if s.get("linkTo") and s["linkTo"] not in building_names:
            E("引用", f"{tag}: linkTo='{s['linkTo']}' 没有对应楼栋文件（断链）")
        if good:
            items.append((s.get("id"), s.get("name", ""), s["polygon"], area))

    op = (c.get("outline") or {}).get("polygon") or []
    check_polygon("几何", "总图/校园边界 outline", op, w, h)

    # 地块互相压盖（总图上不同地块不应大面积重叠）
    if len(items) > 1:
        y_lo = min(p[1] for _, _, poly, _ in items for p in poly)
        y_hi = max(p[1] for _, _, poly, _ in items for p in poly)
        rows, box = {}, {}
        for sid_, name_, poly, area in items:
            box[sid_] = bbox(poly)
            per = {}
            y = y_lo + STEP / 2
            while y < y_hi:
                iv = row_intervals(poly, y)
                if iv:
                    per[y] = iv
                y += STEP
            rows[sid_] = per
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                ri, rj = items[i], items[j]
                bi, bj = box[ri[0]], box[rj[0]]
                if bi[2] <= bj[0] or bj[2] <= bi[0] or bi[3] <= bj[1] or bj[3] <= bi[1]:
                    continue
                common = rows[ri[0]].keys() & rows[rj[0]].keys()
                inter = sum(overlap_length(rows[ri[0]][y], rows[rj[0]][y]) for y in common) * STEP
                small = min(ri[3], rj[3])
                if inter > 400 and inter > 0.25 * small:
                    W("重叠", f"总图: {ri[1]} 与 {rj[1]} 重叠 {inter:.0f}px²"
                              f"（占较小地块 {inter / small * 100:.0f}%）")

    # 楼栋↔总图地块对应
    linked = {s["linkTo"] for s in c.get("sites", []) if s.get("linkTo")}
    for name in sorted(building_names - linked):
        W("对应", f"楼栋 '{name}' 在总图上没有 linkTo 地块（点不到）")


# ---------------------------------------------------------------- 主流程
def main():
    files = sorted(p for p in BD.glob("*.json")
                   if ".part" not in p.name and not p.name.startswith("~"))
    if not files:
        print("没有找到 model/buildings/*.json")
        sys.exit(1)

    names = set()
    total_floors = total_rooms = total_openings = 0
    for fp in files:
        b, bid, rids = check_building(fp)
        names.add(bid)
        total_floors += len(b.get("floors", []))
        total_rooms += len(rids)
        total_openings += sum(len(f.get("openings", [])) for f in b.get("floors", []))
        ok(f"{bid}: {len(b.get('floors', []))} 层 / {len(rids)} 房间")

    check_campus(names)

    n_sites = 0
    if CAMPUS.exists():
        n_sites = len(json.load(open(CAMPUS, encoding="utf-8")).get("sites", []))

    print(f"检查 {len(files)} 个楼栋 + 总图（{n_sites} 地块）："
          f"{total_floors} 个楼层、{total_rooms} 个房间、{total_openings} 个门洞")
    if VERBOSE_FLAG:
        print("\n通过项：")
        for p in passed:
            print("  ✓", p)

    def dump(title, items):
        print(f"\n{title} {len(items)} 个：")
        cats = {}
        for cat, msg in items:
            cats.setdefault(cat, []).append(msg)
        for cat, msgs in cats.items():
            print(f"  [{cat}]")
            for m in msgs:
                print("    ", m)

    if errors:
        dump("✗ 错误", errors)
    if warns:
        dump("⚠ 警告", warns)
    if infos:
        print(f"\nℹ 提示 {len(infos)} 条（小房间嵌在大分区里等，一般无需处理，仅列前 6 条）：")
        for cat, msg in infos[:6]:
            print(f"    [{cat}] {msg}")
        if len(infos) > 6:
            print(f"    …… 另有 {len(infos) - 6} 条同级别提示")
    if not errors and not warns:
        print("\n✓ 全部通过，没有发现问题。")
    elif not errors:
        print("\n✓ 无错误（警告建议人工过一遍）。")
    sys.exit(1 if errors else 0)


VERBOSE_FLAG = "-v" in sys.argv or "--verbose" in sys.argv

if __name__ == "__main__":
    main()
