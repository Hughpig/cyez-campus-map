# 楼层平面数据格式（schema v1）

目标：把楼层平面图纸转成**方便 AI 处理/编辑、也方便程序渲染**的结构化数据。

## 设计原则

1. **几何用原图像素坐标**。所有 `polygon` / `at` 坐标都是对应楼层平面图 PNG 上的像素位置
   （图像坐标系：原点在图左上角，x 向右，y 向下，图片统一为 1164×873）。
   这样改数据时可以直接对照原图量取，零转换误差。
2. **真实尺寸用比例尺换算**。原图上尺寸数字太小无法读出，因此每栋楼给出
   `metersPerPixel`（由设计说明中的各楼总面积反推，见 `标定` 字段），程序需要米制时
   乘上该系数即可。它是估计值，误差大约 ±10%。
3. **房间是一等公民**。墙不做逐段建模；用"房间多边形 + 门洞位置"表达空间结构和连通关系，
   足够做导航/渲染/统计。

## 文件组织

```
model/
  schema.md            本文件
  README.md            使用说明
  campus.json          校园总图（手绘地形图数字化；site 可带 linkTo 跳转到楼栋）
  buildings/
    <楼名>.json        一栋楼一个文件
```

## 校园总图文件（campus.json）

```jsonc
{
  "type": "campus",
  "name": "校园总图",
  "meta": { "source": "...", "sourceDir": "...", "sourceImageFull": "资料/.../图.jpg", "sourceImageName": "图.jpg" },
  "coordinateSystem": { "unit": "px", "imageSize": [1280, 1823], "metersPerPixel": null, "metersPerPixelBasis": "..." },
  "outline": { "polygon": [[x,y],...], "note": "校园用地边界" },
  "sites": [
    {
      "id": "cam-001",
      "name": "6号楼（文杰楼）",
      "kind": "building",              // building / sport / garden / plaza / gate / other
      "polygon": [[x,y],...],           // 原图像素坐标
      "linkTo": "文杰楼",               // 可选：点击跳转到的楼栋名（必须与 buildings/*.json 的 building 一致）
      "confidence": "high",
      "note": ""
    }
  ],
  "notes": []
}
```

## 楼栋文件结构

```jsonc
{
  "building": "综合楼",              // 楼栋名，与文件名一致
  "aliases": [],                     // 别名，如 ["宿舍楼"]
  "meta": {
    "source": "2010-11《曹杨二中改扩建工程建筑设计方案》（设计方案，非竣工图）",
    "sourceDir": "资料/01_本部校区_改扩建方案/楼层平面",
    "note": ""                       // 需要特别说明的事项
  },
  "coordinateSystem": {
    "unit": "px",
    "x": "向右", "y": "向下（图像坐标系）",
    "imageSize": [1164, 873],
    "metersPerPixel": 0.05,          // 整栋统一的比例尺（估计值）
    "metersPerPixelBasis": "由投资估算表：综合楼总面积12209㎡ 反推"  // 标定依据
  },
  "floors": [ /* FloorData 数组，按楼层从低到高 */ ]
}
```

## FloorData（每层）

```jsonc
{
  "id": "1F",                        // 层标识，如 "-2F","1F","2F","7F","标准层(2-5F)"
                                     // 同一层可有多个版本：如 "-2F"(实测) 与 "-2F(2010方案)"(存档) 并存
  "levels": [1],                     // 该图对应的真实楼层号数组；"标准层"图写 [2,3,4,5]
  "sourceImage": "03_综合楼_一层_1F.png",   // 相对 sourceDir 的文件名
  "sourceImageFull": null,           // 可选：相对项目根目录的图片路径（手绘等非标准来源用），优先于 sourceImage
  "sourceDir": null,                 // 可选：该层图片来源目录（覆盖楼栋级 sourceDir 的记录用途）
  "pdfPage": 26,                     // 在119页PDF中的页码（1-based）；非PDF来源为 null
  "imageSize": [1164, 873],          // 可选：该层底图像素尺寸（默认 1164×873；不同尺寸来源必须写）
  "outline": {                       // 建筑外轮廓（外墙面近似，含凸出体块）
    "polygon": [[x,y], ...],
    "note": ""
  },
  "grid": {                          // 轴网（图纸上的轴线圆圈），用于对齐/量距
    "vertical":   [{"label": "1", "x": 110}, ...],   // 竖向轴线（编号通常为数字）
    "horizontal": [{"label": "A", "y": 160}, ...]    // 横向轴线（编号通常为字母）
  },
  "rooms": [ /* RoomData 数组 */ ],
  "openings": [ /* OpeningData 数组 */ ],
  "vertical": [ /* VerticalData 数组 */ ],
  "notes": []                        // 字符串数组，整层备注
}
```

## RoomData（房间）

```jsonc
{
  "id": "zhl-1F-001",               // 全楼唯一：<楼名拼音缩写>-<层>-<序号>
  "name": "门厅",                    // 图纸上标注的房间名；读不清写 "未识别房间" 并在 note 说明
  "type": "hall",                    // 类型，取值见下方词表
  "polygon": [[x,y], ...],           // 顶点序列（原图像素）。矩形房间4个点；弧形房间8~16个点
  "confidence": "high",              // high=名字和边界都清楚; medium=其中之一不确定; low=两者都不确定
  "note": ""                         // 例如 "与2F连通上空"、"椅子不计入"
}
```

- **走廊（corridor）、门厅、楼梯间、电梯厅、卫生间**都要作为房间录入，不能省略。
- 相邻同功能房间即使图中没画隔墙（如开放阅览）也可以合并为一个房间。
- 不要把家具、座位排布录入；大空间（礼堂/体育馆）整间一个多边形即可。
- **type 词表**（渲染配色按组）：
  - 教学：`classroom` 普通教室 / `lab` 实验室 / `lecture` 阶梯教室 / `music` 音乐 / `art` 美术艺术 / `library` 图书 / `reading` 阅览 / `auditorium` 礼堂会堂
  - 办公：`office` 办公 / `meeting` 会议 / `admin` 行政接待档案广播
  - 生活：`dorm` 宿舍 / `dorm-utility` 宿舍配套(盥洗洗衣活动) / `dining` 餐厅 / `kitchen` 厨房
  - 体育：`gym` 体育馆/操场层
  - 交通：`hall` 门厅中庭 / `corridor` 走廊过道 / `stairs` 楼梯间 / `elevator` 电梯井/厅 / `entrance` 入口门斗
  - 辅助：`toilet` 卫生间 / `storage` 储藏库房 / `equipment` 设备用房(配电水泵机房风井) / `parking` 车位区 / `circulation-helper` 车道坡道
  - 其他：`courtyard` 下沉庭院/内院 / `other` 无法归类

## OpeningData（门洞/开口）

```jsonc
{
  "between": ["zhl-1F-001", "zhl-1F-010"],  // 两个房间的 id
  "kind": "door",                            // door=普通门 / passage=无门连通(开放) / external=对外出入口
  "at": [x, y],                              // 门洞在图上的大致位置（像素）
  "confidence": "high"
}
```

- 记录**房间之间的连通**即可，位置取门洞图形的大致中点。
- 重复排列的房间（如宿舍标准间一排 10 间）也要逐间记录，这是导航数据的价值所在。
- 对外出入口（进入建筑的门）用 `external`，`between` 里第二个元素写 `"outside"`。

## VerticalData（垂直交通）

```jsonc
{
  "kind": "stairs",                  // stairs / elevator / escalator / ramp
  "name": "1#楼梯",                  // 若图上没有编号，用位置描述，如 "西北角楼梯"
  "roomId": "zhl-1F-012",            // 对应本层的楼梯间/电梯井房间 id
  "connects": ["1F", "2F"],          // 连通的楼层 id（按图判断；标准层写 ["2F","5F"] 表示 2~5 层间）
  "note": ""
}
```

## 注意事项

- 这是 2010 年**设计方案**：局部与现状可能不同；图上"曹阳"为"曹杨"的错别字。
- 部分小房间名字在原图上偏糊：先用整图看布局，再对局部裁切放大 2~4 倍读名字；实在读不出
  用 `"name": "未识别房间"`，`confidence: "low"`，并在 note 写你看到的线索。
- 坐标宁可略粗也不要臆造精细数字；顶点误差 5~10px 可接受。
- JSON 里不要写注释（上面 jsonc 仅为说明）。
