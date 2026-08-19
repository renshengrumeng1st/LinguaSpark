# LinguaSpark

LinguaSpark 是一个面向 Windows 的 AI 辅助英语学习助手。它把“查事实”和“做解释”拆成两条链路：单词先从本地 SQLite 词典即时返回音标、词性、释义和词形；AI 再渐进补充通俗解释、近义词、搭配、例句与记忆提示。句子和图片直接交给多模态模型翻译。

## 主要能力

- 单词输入停顿约 160 ms 后自动查词；本地结果不等待网络。
- 句子按 `Ctrl+Enter` 翻译；剪贴板图片可直接粘贴识别。
- AI 返回结构化数据，不再依赖 Markdown 正则解析。
- `Alt+W` 使用 Windows UI Automation 优先读取选区，失败时回退到剪贴板并完整恢复原内容。
- 发音支持持久化 Windows SAPI，以及可选的 Azure Neural TTS 和本地音频缓存。
- API 密钥使用当前 Windows 用户的 DPAPI 加密，公开配置与凭据分离。
- “收藏”与“加入学习”相互独立；到期单词进入今日复习，并按“不记得 / 模糊 / 记得”排期。
- 复习卡在释义回忆与例句挖空间渐进切换，托盘每天至多提醒一次且可在设置中关闭。
- 收藏、学习队列、复习日志、历史、AI 缓存和性能指标统一存入用户目录下的 SQLite。
- 语言、词典、AI、语音和界面均通过接口解耦，后续可扩展为多语言学习助手。

## 快速运行

```bat
setup.bat
run.bat
```

首次运行会自动迁移旧 `config.json` 中的模型配置。新配置位于 Windows AppData，不会被打包进可执行文件。

## 安装本地词典

项目使用 MIT 许可的 [ECDICT](https://github.com/skywind3000/ECDICT)。下载其 `ecdict.csv` 后，把文件拖到 `install_dictionary.bat` 上；脚本会筛出适合学习的高频词并生成 `data/ecdict_core.sqlite3`。

也可从终端执行：

```bat
install_dictionary.bat C:\path\to\ecdict.csv
```

没有本地词典时句子、图片和 AI 助学仍可用，但单词不会显示离线基础事实。

## 快捷键

- `Alt+Q`：显示或隐藏主窗口
- `Alt+W`：翻译当前选中文字
- `Ctrl+Enter`：提交句子或图片
- `Ctrl+L`：清空当前内容

`Alt+Q` 和 `Alt+W` 是默认值，可在“设置 → 快捷键”中录制并立即更换。

## 测试与构建

```bat
test.bat
build.bat
```

`build.bat` 只打包代码、图标和已生成的本地词典，不包含 `config.json`、API 密钥、历史或缓存。

详细的边界与扩展方式见 [架构说明](docs/ARCHITECTURE.md)。
