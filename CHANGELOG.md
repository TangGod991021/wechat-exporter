# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- 便携版一键打包脚本 `build-portable.bat`：自动安装依赖、构建前端、执行 PyInstaller 打包
- 打包产物附带 `USAGE.md`、`LICENSE.txt`、`NOTICE.md`
- 全新程序图标（绿色底 + 聊天气泡 + 导出箭头）：exe、窗口、网页 favicon 与顶栏 Logo 统一使用
- `tools/make_icon.py`：一键生成多尺寸 ICO / PNG / favicon
- 可执行文件更名为 `WeChatExporter.exe`，产物文件夹同步为 `dist\WeChatExporter\`
- 补齐 Windows 文件属性：文件描述、产品名、版本、版权、原始文件名（`packaging/version_info.txt`）
- 导出 HTML 图片支持点击放大预览（灯箱），聊天图片与转发记录图片均生效，Esc 或点击空白处关闭

### 变更

- 界面改为五步向导：选择账号 → 提取密钥 → 选择会话 → 准备数据 → 导出
- 第 2 步只提取密钥并建立会话索引（`session.db` / `contact.db`），提取后即可离线
- 第 3 步自动加载消息库（`message_0.db` / `media_0.db`），显示消息条数并支持预览
- 第 4 步只解密所选会话实际引用的图片 / 语音 / 视频，未选中的会话不处理
- 新增 `/api/core`（加载会话数据）与 `/api/prepare`（按会话准备媒体）；`decrypt_all` 支持 `only_rels`
- 视频转码由「导出」前移到「准备所选数据」阶段；导出阶段数据已就绪

### 修复

- 重新打包时自动备份并恢复 `dist` 中的 `data/`、`media/`、`exports/` 与 `config.json`，避免升级时丢失已解密数据
- 修复 `make_store` 误用未定义变量 `c` 导致会话 / 导出接口 500（应为 `cfg`）
- 修复前端调用 `api.startCore` 方法名不匹配导致「建立会话索引」报错（`startCore is not a function`）

- 打包后 `config.json` 与 `data/`、`media/`、`exports/` 固定落在 exe 同级目录，整个文件夹可直接拷贝到其他电脑运行
- 修复双击 exe 无反应：窗口模式下 `sys.stdout/stderr` 为 `None`，uvicorn 日志初始化异常导致后台线程静默退出；启动时用 `devnull` 兜底，并在启动失败时写入 `启动错误.log` 并弹窗提示
- 修复启动/处理媒体时闪现 cmd 黑框：`powershell`、`tasklist`、`ffmpeg`、`ffprobe` 等控制台子进程统一通过 `app/core/proc.py` 附加 `CREATE_NO_WINDOW`

## [0.1.0] - 2026-11-13

首个公开版本。

### 新增

- 微信 4.x 账号与数据目录自动发现
- 密钥提取：4.0.x 明文缓存 / 4.1.11+ `Config.Cipher` 掩码两种策略
- SQLCipher 4 数据库逐页解密，支持增量跳过
- 富消息解析与渲染：
  - 引用（57）、链接（5）、文件（6/74）、小程序（33/36）
  - 音乐（3）、视频分享（4）、聊天记录（19，可展开明细）
  - 转账（2000）、红包（2001）、拍一拍（62）、接龙（53）
  - 未知类型降级为可读摘要，避免输出原始 XML
- 媒体处理：
  - 图片 V2 `.dat` 解密、WxAM（`wxgf`）转 JPG
  - 语音 SILK v3 转 WAV
  - 视频索引与 HEVC → H.264 兼容转码
- 自包含归档导出：`index.html` + `images/` + `videos/` + `audio/` + `manifest.json`
  - 媒体硬链接优先、失败回退复制
  - HTML 使用相对路径，可离线打开
- Vue 3 + Naive UI 四步向导，深色模式，实时进度
- pywebview 原生窗口 + 本地 FastAPI 服务
- PyInstaller 打包配置

### 修复

- 复杂媒体处理速度优化：增量跳过、进程池、PyAV 解码 HEVC
- 暗色模式自定义样式未生效、页面高度塌陷
- 视频 HEVC 编码导致浏览器无法播放

### 已知限制

- 微信未缓存的媒体无法离线还原，显示占位提示
- 部分转发聊天记录中微信自身写入的发送者字段异常（如时间），属于源数据问题
- 微信升级可能改变密钥格式，需要跟进适配

[0.1.0]: https://github.com/TangGod991021/wechat-exporter/releases/tag/v0.1.0
