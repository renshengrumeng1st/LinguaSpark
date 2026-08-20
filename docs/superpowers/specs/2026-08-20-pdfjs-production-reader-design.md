# PDF.js 正式阅读器接入设计

日期：2026-08-20

## 背景与决策

现有 `SelectablePdfView` 依赖 `QPdfView` 的文本几何，并在 Python 中自行完成命中、坐标换算与蓝色覆盖层绘制。复杂论文中的双栏、公式、上下标和字体片段会让文字边界与最终页面像素不同步，已经反复出现漏行、空白蓝条和垂直错位。

独立 PDF.js 验证器已经通过真实文档人工验收。正式阅读器因此采用 PDF.js 6.2.108 legacy 构建与 `QWebEngineView` 的原生 DOM 文字层；页面、文字和浏览器选区由同一布局引擎生成，不再由 Python 重建当前蓝色选区。

## 目标

- 复杂文本型 PDF 中，鼠标拖选直接使用浏览器原生蓝色选区。
- 保留多 PDF 标签、连续滚动、50%–300% 缩放、适合宽度、四种背景、持久标记、专注阅读和 `Alt+W` 翻译。
- `PdfReaderTab`、`PdfTranslationController`、缓存、数据库与快捷键不依赖 PDF.js 细节。
- 每个标签的文档、端口、缩放、选区和标记相互隔离。
- 只向 LLM 发送最终选中文字；PDF 文件、路径和全文不离开本机。
- 源码验收前不打包、不推送 GitHub。

## 非目标

- OCR、扫描件识别、编辑 PDF 内容、手写批注与云同步。
- 跨页持久标记。跨页文字仍可用于翻译，但标记只在单页稳定选区中开放。
- 重写翻译协议、学习数据库或多标签容器。
- 本轮删除旧 `SelectablePdfView`。旧实现先保留为可回退代码，验收稳定后再单独清理。

## 架构

```text
PdfReaderWindow
└── PdfReaderTab
    ├── PdfJsViewAdapter (稳定 QWidget 接口)
    │   ├── QWebEngineView
    │   ├── PdfJsBridge (WebChannel)
    │   └── PdfJsAssetServer (127.0.0.1 + 随机文档路由)
    │       └── assets/pdfjs-6.2.108-legacy
    └── PdfTranslationController
```

`PdfJsViewAdapter` 保持正式 UI 已消费的契约：

- 信号：`selection_changed`、`document_loaded`、`load_failed`、`current_page_changed`、`zoomFactorChanged`。
- 方法：`load_file`、`close_document`、`current_selection`、`set_annotations`、`set_reading_theme`、`zoomFactor`、`set_zoom_factor`、`adjust_zoom`、`fit_to_width`。
- 属性：`document_key`。

`PdfReaderTab` 只切换构造的具体视图，不读取 WebChannel、HTTP 或 DOM。

## 本地资源服务

PDF.js 的 viewer、worker、字体、CMap、WASM 与当前 PDF 只通过随机端口的 `127.0.0.1` 服务。文档 URL 包含每个会话独立的随机令牌；服务拒绝资源根目录之外的路径，不列目录，不暴露任意本地文件。

文档请求支持 `HEAD`、普通 `GET` 和单段 `Range: bytes=`，以 64 KiB 块流式发送，避免打开大 PDF 时一次性读入内存。无效或多段 Range 返回 416。关闭标签时停止页面加载并关闭对应服务线程。

## 选区与标记

注入脚本只在 PDF.js viewer 主框架执行。鼠标释放或键盘扩展选区后，它读取浏览器 `Selection`：

1. 获取原生选中文字；
2. 按页面归属收集 `Range.getClientRects()`；
3. 把矩形除以 PDF.js 当前缩放，保存为 scale=1 的页面坐标；
4. 用页面文字层前缀长度计算单页 `start_index` 与 `end_index`；
5. 通过 WebChannel 一次性提交最终结果。

Python 规范化文字并生成现有 `PdfTextSelection`。单页且索引稳定时允许持久标记；跨页选区可翻译但不允许写入错误标记。持久标记由脚本在对应 `.page` 中创建无鼠标事件的绝对定位层，缩放或页面重新渲染后按当前比例重绘。

## 主题、缩放与状态

- `eye_care`、`paper`、`soft_gray`、`white` 继续使用既有稳定 ID。
- 自有 CSS 给 viewer 背景和 PDF 页面设置主题色，并对 canvas 使用 `multiply`，使默认白纸映射为主题色。
- 原生 `::selection` 使用半透明蓝色；持久标记位于页面之上、原生活动选区之下。
- 自定义缩放限制为 0.5–3.0；PDF.js `scalechanging` 将实际比例回传工具栏。
- “适合宽度”使用 PDF.js 的 `page-width` 模式；`pagechanging` 回传当前页。
- PDF.js `documentloaded` 后才发出正式 `document_loaded`，加载或密码错误映射为中文状态。

## 资源与许可

仓库只保存 Mozilla 官方 PDF.js 6.2.108 legacy 运行所需文件，不保存 source map、示例 PDF 或调试器。上游 `LICENSE` 一并纳入 `assets/pdfjs-6.2.108-legacy`，并在 `THIRD_PARTY_NOTICES.md` 记录 Apache-2.0、版本与来源。

PySide6 Addons 6.10.1 已包含 Qt WebEngine 与 WebChannel，不新增 Python 包。正式打包将在源码验收后的独立阶段验证 QtWebEngineProcess 和资源收集。

## 错误处理与生命周期

- 路径不存在、不是文件或不是 `%PDF-` 文件时，`load_file` 同步返回 `False` 并发出中文错误。
- viewer/worker/文档加载失败时保留标签并显示可理解错误；不得崩溃或静默翻译空文本。
- 空选区清空控制器状态；没有文字层的扫描 PDF 提示暂不支持 OCR。
- `close_document` 可重复调用，必须清空选区、文档身份和标记，并终止本地服务。

## 测试与验收

- 资源服务：路径隔离、HEAD、完整 GET、前缀/后缀 Range、416、流式响应。
- 桥接：合法/空/畸形 payload、坐标有限值、单页索引、跨页不可标记。
- 真实 WebEngine：三行选择、主题、缩放、适合宽度、页码、标记重绘和关闭释放。
- UI：多标签隔离、工具栏百分比、`Alt+W`、专注模式、翻译与标记控制状态。
- 完整 pytest、compileall 与 `git diff --check` 通过后启动正式应用供人工验收。

## 完成条件

- 正式 `PdfReaderTab` 使用 `PdfJsViewAdapter`，不再运行旧手工选区。
- 已验收验证器的蓝色选区行为在正式应用中保持一致。
- 所有既有功能回归通过，资源与许可完整。
- 未打包、未推送；等待用户进行正式源码验收。
