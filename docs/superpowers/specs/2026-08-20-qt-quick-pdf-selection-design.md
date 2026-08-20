# Qt Quick PDF 原生选区重构设计

日期：2026-08-20

## 1. 背景与决策

当前 `SelectablePdfView` 继承 QWidget 版本的 `QPdfView`。该控件负责 PDF 页面渲染、滚动、缩放和搜索，但不提供完整的鼠标文字选择交互。项目因此自行维护页面布局、鼠标命中、PDF 点坐标与视口坐标转换、字符范围稳定化以及蓝色覆盖层。

真实论文中的双栏排版、公式、上下标、字体切换和异步页面重绘已经多次暴露以下问题：

- Qt 返回的字符边界可能由大量字体片段组成；
- 页面渲染比例、逻辑 DPI、滚动位置和手工布局之间可能产生小数误差；
- 选区数据正确时，独立绘制的覆盖层仍可能因局部重绘而出现缺行；
- 修复一个文档后，另一种 PDF 内容流顺序或字符几何仍可能产生新错位。

继续修补手工坐标算法不能给出复杂 PDF 下的稳定保证。本次决定把左侧 PDF 显示层替换为 Qt Quick 官方 PDF 组件体系：页面使用 `PdfPageImage` 渲染，文字选择使用 `PdfSelection`，蓝色选区与页面共享同一 QML 场景、`renderScale` 和 `pageScale`。Python 不再绘制当前文字选区。

## 2. 目标与非目标

### 目标

- 普通段落、双栏、公式和混合字体中，蓝色选区与文字保持一致，不缺行、不出现空白碎片带。
- 在 50% 至 300% 缩放、滚动和 Windows 125%/150% 显示缩放下保持对齐。
- 保留现有多 PDF 标签、右侧翻译、词组分析、`Alt+W`、专注模式、背景主题和本地标记。
- 选区释放后尽快把文字送入现有 `PdfTranslationController`；本次重构不改变网络请求和缓存协议。
- 继续只发送当前选中文字，不上传 PDF 文件、路径或全文。
- 复用当前 PySide6 6.10.1 已安装的 Qt Quick PDF 模块，不引入 WebEngine、PDF.js 或第二套 PDF 解析引擎。

### 非目标

- OCR、扫描 PDF 文字识别、跨页选择、手写批注和修改原 PDF。
- 重写多标签与翻译控制器。
- 在源码验收前打包或推送 GitHub。
- 为无法正确编码文字层的 PDF 猜测阅读顺序；此类文档应明确提示，而不是生成错误译文。

## 3. 方案比较

### 方案 A：Qt Quick PDF 原生选区（采用）

使用 `QQuickWidget` 嵌入定制版 `PdfMultiPageView`。`PdfSelection.geometry` 直接在页面图像所在的 QML 场景中通过 `PathMultiline` 绘制，避免 Python 侧重复计算坐标。

优点：当前运行时已包含所需模块；无 Chromium 依赖；连续滚动、缩放、链接和选择由 Qt 官方组件实现；与现有 PySide6 UI 的集成范围可控。

代价：需要维护一份从 Qt 6.10.1 官方组件派生的 QML 文件；打包时必须显式收集 Qt Quick PDF、Shapes 和相应 QML 插件；首次创建 Qt Quick 场景会增加少量启动成本。

### 方案 B：PDF.js + QWebEngineView（不采用）

PDF.js 的 canvas 与文本层适合浏览器式选择，但需要引入 WebEngine、JavaScript 桥接和额外资源，显著增加打包体积与冷启动成本，并形成 Python、Chromium、JavaScript 三层调试边界。

### 方案 C：PyMuPDF 自绘页面与文本层（不采用）

该方案控制力最大，但必须自行实现虚拟化、多页缓存、文字层、链接、选择、缩放和高 DPI 处理，工作量与长期维护风险最高，仍可能重新制造坐标同步问题。

## 4. 总体架构

```text
PdfReaderWindow
└── PdfReaderTab
    ├── QuickPdfViewAdapter (Python QWidget API)
    │   └── QQuickWidget
    │       └── LinguaPdfMultiPageView.qml
    │           ├── PdfDocument
    │           ├── PdfPageImage
    │           ├── PdfSelection + PathMultiline
    │           ├── annotation paths
    │           └── theme page filter
    ├── translation panel
    └── PdfTranslationController
```

`PdfReaderTab` 继续面向一个稳定的视图接口，不直接依赖 QML：

- `load_file(path) -> bool`
- `close_document()`
- `current_selection() -> PdfTextSelection | None`
- `set_annotations(annotations)`
- `set_reading_theme(theme_id)`
- `set_zoom_factor(value)`、`adjust_zoom(steps)`、`fit_to_width()`
- `selection_changed`、`document_loaded`、`load_failed`、`current_page_changed`、`zoomFactorChanged`

新 `QuickPdfViewAdapter` 对外保持上述语义。这样多标签容器、快捷键路由、翻译控制器和右侧 UI 无需理解 QML。

## 5. QML 阅读层

### 5.1 官方组件派生

项目复制 Qt 6.10.1 随附的 `PdfMultiPageView.qml` 作为受控基线，保留原始 Qt 版权和许可证头，并记录上游版本。派生文件只做与产品需求直接相关的修改：

- 暴露选区提交、当前页、缩放和加载状态信号；
- 把选区的页码、文本、PDF 点坐标起止点和 `geometry` 传给 Python；
- 接收每页本地标记几何并在同一页面场景绘制；
- 应用四种阅读主题；
- 保留官方连续滚动、按需页面委托和渲染缓存。

不修改 Qt 安装目录中的文件。派生 QML 存放在项目资源目录，并随源码提交。

### 5.2 选区数据流

1. 页面委托中的 `DragHandler` 记录同一页内的鼠标起止位置。
2. `PdfSelection` 使用与 `PdfPageImage` 相同的 `renderScale` 解析文字并产生 `text` 与 `geometry`。
3. `PathMultiline` 使用页面的 `pageScale` 直接绘制半透明蓝色选区。
4. 鼠标释放时，QML 把 `geometry` 展平为由 `{x, y}` 构成的 `QVariantList`，并发出一次 `selectionCommitted(page, text, fromPoints, toPoints, geometry)`；拖动中只更新视觉反馈，不触发翻译控制器。
5. Python 适配器规范化文本，转换几何为 PDF 点坐标，生成 `PdfTextSelection` 并发出 `selection_changed`。
6. `Alt+W` 继续读取当前标签的最终选区并调用现有控制器。

蓝色选区始终使用 QML 原始 `geometry` 渲染。Python 保存的矩形仅用于持久化标记和测试，不再反向驱动当前选区绘制，因此数值舍入不会影响用户看到的选区。

### 5.3 字符范围与标记身份

`PdfSelection` 不直接暴露字符索引。QML 在提交前使用当前 `renderScale` 把鼠标像素坐标换算成 PDF 点坐标。为了兼容现有 `PdfTextSelection` 和数据库，Python 使用返回的页码和 PDF 点坐标起止点调用同一 `QPdfDocument.getSelection()` 获取 `start_index` 与 `end_index`。该索引只用于标记身份和数据库兼容，不用于蓝色选区绘制。

若索引提取失败但 QML 已返回有效文字与几何：

- 翻译仍可正常进行；
- 该选区暂不允许新增持久化标记，并显示明确提示；
- 不使用猜测索引或页面全文模糊匹配，以免删除错误标记。

持久化标记仍保存 PDF 点坐标。重新打开文档后，QML 在对应页面通过与页面图像相同的 `pageScale` 绘制标记。现有数据库结构不迁移，已有标记继续可读。

## 6. Python/QML 边界

新增一个只负责视图通信的 `PdfViewBridge(QObject)`：

- QML → Python：选区提交、清空选区、当前页变化、缩放变化、文档加载状态和错误。
- Python → QML：打开/关闭文件、设置主题、设置缩放、适合宽度、更新标记和清空当前选区。

桥接只传递可序列化值：字符串、整数、浮点数、点列表和字典列表；不得传递控制器、数据库连接或网络客户端。QML 不访问 SQLite、设置文件或 LLM。

文档路径通过本地 `QUrl` 传入 QML。错误信息在适配器中转换为现有中文状态文本。密码只在当前会话中设置，不持久化。

## 7. 主题、缩放和滚动

- 页面空白和窗口背景继续使用 `eye_care`、`paper`、`soft_gray`、`white` 四个稳定主题 ID。
- PDF 页面颜色处理放在页面图像层，使用一个由项目资源携带的 Qt Quick `ShaderEffect` 执行乘色：黑色文字保持深色，白色纸张映射到主题色；蓝色选区和本地标记绘制在颜色处理层之上。片段着色器使用当前 PySide6 随附的 `pyside6-qsb` 预编译并纳入资源测试，不依赖用户机器现场编译。
- 缩放统一修改 `PdfMultiPageView.renderScale`，限制为 0.5 至 3.0；工具栏百分比由 QML 的实际值回传。
- “适合宽度”调用官方 `scaleToWidth()`，不在 Python 侧重新计算页面宽度。
- 连续滚动由官方 `TableView` 和按需页面委托负责。滚动不提取页面全文、不访问数据库、不发起网络请求。
- 每个 `PdfReaderTab` 各自拥有一个 QML 阅读实例，因此切换标签时滚动、缩放和选区自然隔离。

## 8. 性能与资源

- 创建 PDF 标签时才实例化 `QQuickWidget`；便捷模式不加载 Qt Quick PDF。
- 页面继续异步、按需渲染，不预渲染整本文件。
- 拖动过程中不跨 Python/QML 边界发送高频几何；只在释放时提交最终选区。
- 选区释放到 Python 收到提交信号的目标为 30 ms 内；`Alt+W` 后 50 ms 内进入翻译状态，网络首字节指标保持现有定义。
- 关闭标签时先取消翻译，再清空 QML 文档源并销毁 QQuickWidget，避免页面纹理和文档句柄残留。
- 若 Qt Quick 场景创建失败，PDF 标签显示依赖错误；不得静默回退到已知不稳定的手工选区实现。

## 9. 分阶段迁移

### 阶段一：隔离原型

新增独立的 Qt Quick 阅读原型，不替换正式 `PdfReaderTab`。使用真实问题文件验证：

- `Cloth subspace` 多行段落；
- 含上下标、数学符号和引用的段落；
- 双栏边界附近的选择；
- 从文字行首、行尾和行间空白开始拖动；
- 50%、100%、150%、200%、300% 缩放；
- Windows 100%、125%、150% 显示缩放。

原型只证明渲染、选择、桥接和性能可行，不连接数据库或网络。原型验收不通过时停止正式迁移，并保留现有正式阅读器。

### 阶段二：正式适配器

原型通过后实现 `QuickPdfViewAdapter`，接入 `PdfReaderTab`，保持现有公开接口和信号语义。翻译、多标签、专注模式和快捷键只做兼容调整。

### 阶段三：主题与标记

接入页面乘色、四种主题和持久化标记。验证新旧标记数据库兼容以及缩放后的标记对齐。

### 阶段四：删除旧实现

所有验收通过后删除手工页面布局、文字吸附、矩形合并和 Python 覆盖层代码，以及只服务于旧算法的测试。不得长期保留两套 PDF 选择实现。

## 10. 测试与验收

### 自动化测试

- `QQuickWidget` 能加载项目 QML，状态为 Ready，缺失模块时输出可理解错误。
- 打开、关闭、缩放、适合宽度、页码和选区信号能通过适配器正确传递。
- 拖动期间不发出业务选区，释放时只提交一次。
- QML 选区文本和页面号生成正确的 `PdfTextSelection`；索引失败时翻译可用而标记被安全禁用。
- 多标签之间的文档、缩放、选区和 QML 对象完全隔离。
- 主题与标记数据能进入正确页面，缩放后仍使用同一页面变换。
- 现有翻译缓存、快捷键路由、专注模式和便捷模式测试继续通过。
- Python 编译检查、QML 加载检查和完整测试套件通过。

### 真实文档视觉验收

- 每个缩放档位中，蓝色覆盖层包含用户实际选择的每一行，不遗漏中间行。
- 蓝色区域与对应字形垂直错位不超过 1 个逻辑像素，不出现无文字的大块碎片带。
- 公式和上下标可以产生局部高度差，但不得覆盖相邻未选行。
- 滚动后选区和已保存标记不漂移；切换标签再返回时状态不串联。
- 使用至少三份不同来源的文本型 PDF 验证，其中必须包含当前问题论文。
- 首屏显示和滚动无明显卡顿；选区释放信号满足 30 ms 目标。

## 11. 打包与许可

源码验收阶段不执行打包。后续打包时显式收集 `QtQuick.Pdf`、`QtQuick.Shapes`、Qt Quick Controls、平台图形后端和项目 QML 资源，并在干净 Windows 环境进行冷启动测试。

派生自 Qt 的 QML 文件保留完整上游版权与许可证头，项目发行包继续遵守当前 PySide6/Qt LGPL 要求并包含相应许可文本。项目自有桥接代码沿用仓库现有许可。

## 12. 完成条件

只有同时满足以下条件才视为重构完成：

- 隔离原型通过真实问题 PDF 的全部视觉矩阵；
- 正式适配器替换旧视图且现有功能无回退；
- 自动化与完整回归测试通过；
- 用户完成源码验收；
- 旧手工选区实现被删除；
- 未经用户明确同意，不打包、不推送 GitHub。
