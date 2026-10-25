# 曹杨二中校园地图

把上海市曹杨二中 2010 改扩建方案图纸数字化后的交互式校园地图与楼层平面模型。

## 在线查看

GitHub Pages 部署后直接打开 **viewer.html** 即可（无需安装任何东西，双击本地文件也能用）。

- `viewer.html` — 单文件查看器（数据已内嵌，双击即用）
  - 滚轮缩放 · 拖拽平移 · 点击房间/地块看信息
  - 勾选「原图叠加」可对照原始图纸核验
  - 总图上点击蓝色虚线楼栋可跳转到对应楼层平面

## 目录结构

```
viewer.html            查看器（构建产物；由 tools/build_viewer.py 生成）
model/
  campus.json          校园总图（23 个地块：楼栋/广场/球场/出入口等）
  buildings/*.json     7 栋楼 34 个楼层、639 个房间的平面模型
  schema.md            数据格式定义
  README.md            数据说明
tools/
  build_viewer.py      数据注入模板生成 viewer.html
  validate.py          结构/引用/坐标越界校验
  calibrate.py         米/像素比例标定
  viewer_template.html 查看器模板
交接文档.md            项目工作记录（数据约定、实况修正史、遗留问题）
```

## 数据约定

- 所有坐标 = 原图纸像素（图像坐标系，x 向右 y 向下），米制用各楼 `metersPerPixel` 换算。
- 楼栋与房间名带有 `confidence`（可信度）与 `note`（依据）字段——大量房间名是图纸小字的推断值，引用时请先看 note。

## 重新构建查看器

改了 `model/` 下的数据后：

```bash
python tools/validate.py
python tools/build_viewer.py
```

---
图源：曹杨二中 2010 改扩建方案（方案三）楼层平面与总平面，辅以实地信息修正。
