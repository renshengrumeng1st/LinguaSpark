# 项目文件用途核查（2026-11-10）

当前入口 `main.py` 只使用 `learning_assistant.application`；构建入口为 `tools/build_release.py`，当前测试位于 `tests_v2/`。

## 已删除的无当前引用历史文件

| 路径 | 核查结果 |
| --- | --- |
| 根目录 `ui/` | 旧 Tk 界面；现有入口、工具、测试不导入该包 |
| 根目录 `utils/` | 旧热键、托盘、缓存和语音等辅助模块，只由旧实现使用 |
| 根目录 `config.py`、`translator.py` | 旧配置与翻译实现，现有服务已由 `learning_assistant` 替代 |
| `learning_assistant/ui/pdf_view.py` | 停用的 Qt PDF 自绘选择视图，当前使用 `pdfjs_view.py` |
| `summary.md` | 历史工作记录，包含已过时的界面与发布说明；当前使用文档以 README 为准 |
| `artifacts/ui-compact.png`、`ui-preview.png`、`ui-word-expanded.png` | 早期截图，无当前文档引用 |

用户明确授权删除后，已移除以上 27 个 Git 跟踪文件，以及旧 `ui/`、`utils/` 目录内的编译缓存。删除前核对了未提交改动、当前代码引用及目录边界；这些旧实现仍可从 Git 历史恢复。

## 保留且仍有用途的内容

- `sitecustomize.py` 与 `learning_assistant/pytest_bootstrap.py`：Windows Qt/ICU 初始化，影响源码测试启动。
- `tools/migrate_legacy_secrets.py`：旧配置密钥迁移工具；读取旧 JSON 不依赖旧 `config.py`。
- `data/ecdict_core.sqlite3`：当前离线词典，构建时打包。
- `assets/pdfjs-6.2.108-legacy/`：当前 PDF 阅读运行时。字体、CMap、WASM、图标和语言资源可能动态加载，不按静态引用盲目裁剪。
- `assets/themes/`：当前主题插画及来源说明。
- `docs/`、`AGENTS.md`：架构、协作偏好与历史设计记录。
- 本地配置、历史、缓存、虚拟环境、其他工作树及旧发布包：未删除，不依据 ignored/untracked 状态判断可清理。

## 本次整理

- 当前应用和测试不再依赖 `customtkinter`、`keyboard`、`Pillow`、`pystray`，从开发依赖清单移除；未修改已安装的虚拟环境。
- `artifacts/` 加入忽略规则，新诊断日志、临时数据库和截图保留本地，不加入本次源码提交。
- PyInstaller 从现用入口追踪依赖，仅显式包含 `assets/` 和当前词典，不包含旧源码目录、配置密钥、历史或诊断目录。
