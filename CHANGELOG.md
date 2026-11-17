# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.2.1] - 2026-11-17

### 修复

- 修复导出缺失大量历史消息：微信 4.x 会把同一会话的消息表滚动写入
  `message_0.db`、`message_1.db` 等多个分库，旧实现只读取了其中一个分库。
  现在遍历该会话所在的全部分库并合并，按 `(create_time, sort_seq, local_id)` 排序
- 会话消息数与消息预览分页同步按分库累加/合并，新增 `before_sort` 游标避免同秒消息丢失
- 公众号会话支持读取 `biz_message_*.db`，并在解密列表中包含该分库
- 第 2 步给出「消息库缺少密钥 / 解密失败」的明确提示，并新增「重新提取密钥」按钮
  （微信新增分库后需要重新提取密钥才能看到其中的历史消息）
- 会话数量缓存升级为 v2，升级后自动重算，避免沿用旧版本偏小的统计值
- 新增 `tests/test_multishard.py` 回归测试（跨分库合并、计数、分页、公众号分库）

## [0.2.0] - 2026-11-17

### 新增

- 会话列表改为后台任务解析（`/api/sessions/refresh`），界面显示进度条、百分比、当前统计进度，并支持取消与失败重试
- 内置 FFmpeg：`build-portable.bat` 自动把 `ffmpeg.exe` / `ffprobe.exe` 放入打包产物，启动时自动加入 `PATH`，目标电脑无需另行安装
- 导出目录可移植：位于程序目录内时以相对路径 `exports` 保存，默认写入启动器（exe）同级目录；配置中的绝对路径失效时自动回退

### 修复

- 密钥提取扫描微信内存时按 MB 持续上报进度与阶段提示，不再长时间停在 5% 无反馈
- 数据库解密按页上报进度并按库大小加权，大库解密期间进度条持续更新
- 会话列表改为每库一次连接统计并落盘缓存，第 2 → 3 步加载更快且显示加载提示
- 准备完成状态落盘（`prepared.json`）并在 bootstrap 返回；刷新/重启后仍可进入导出，修复「准备完成后无法点击导出」
- 「下一步 / 开始导出」被禁用时显示具体原因；步骤条支持点击前进，条件不足时弹出提示
- 准备失败/取消显示持久错误卡片与重试；准备成功提供「进入导出」按钮
- 修正准备阶段图片/WxAM/语音子进度按比例换算错误（0–1 与 0–100 混用导致进度条停在阶段起点）
- 移除 bootstrap 中未被界面使用的媒体文件全目录递归计数，减少媒体量大时的响应延迟
- 发布包不再携带 `config.json`；打包重跑时保留已有 runtime 备份，避免数据丢失
- `app.spec` 打包 Everything 与第三方许可证，手动构建不再缺文件
- 修正 NOTICE：FFmpeg 经 PyAV 随包分发，补充 GPL/LGPL 与 Everything 许可文本
- 导出语音按 username 目录查找，修复有备注的联系人语音全部丢失
- 转发聊天记录图片通过 `hardlink.db` 映射消息 md5 到本地文件
- 解密改为临时文件 + 原子替换，校验源库整页对齐与输出 SQLite 头；跳过时校验大小
- 消息库按实际存在的 `message_*.db` / `media_*.db` 动态解密，兼容多分片账号
- 任务按类型互斥并支持取消；导出失败保留错误信息与日志，可重试
- 切换账号/数据目录时重置导出、预览与任务状态
- 聊天预览改用 `(create_time, local_id)` 复合游标，修复同秒消息丢失
- 导出格式、日期范围、分页 limit 增加参数校验
- 新增 `tests/run_all.py` 与 GitHub Actions（后端离线测试 + 前端构建）
- 消息类型补全：笔记（24）、表情/动图（8）、群公告（87）、名片（42）、位置（48）
- 群聊消息前缀按真实 sender 剥离，XML 类型不再因 `wxid:\n` 前缀丢失内容
- HEVC 转码强制 `-pix_fmt yuv420p`，修复 10-bit 视频仍无法播放
- 导出单个会话失败不中断整批；引用模式同名会话不再互相覆盖
- 增加单实例保护；启动时校验 `/api/bootstrap` 身份并支持端口重试，避免误连其他服务
- Everything 退出改为按 PID 只关闭本程序启动的进程
- 数据目录自动探测支持 OneDrive 重定向与注册表 Documents 路径
- 增加 FFmpeg 可用性检测与准备阶段失败提示；WxAM 使用配置的 ffmpeg 路径
- 导出 HTML 保留消息换行；归档缺失媒体在 HTML 与 manifest 中明确标记，不再引用绝对路径
- 配置原子写入、损坏自动备份；程序目录只读时回退 `%LOCALAPPDATA%`
- 任务失败写入 `运行日志.log`；大视频索引改为分块计算 MD5
- 自动定位结果按账号去重，降低非微信 `db_storage` 误判；密钥权限失败提示管理员运行

### 安全

- 本地 API 启用随机访问令牌鉴权，移除通配 CORS，校验 Host 防 DNS rebinding
- `/api/file`、`/api/open-path` 改为严格目录白名单，不再允许读取解密库或任意文件
- 链接消息只允许 http/https/mailto，避免预览与导出 HTML 执行 `javascript:`

### 新增

- 便携版一键打包脚本 `build-portable.bat`：自动安装依赖、构建前端、执行 PyInstaller 打包
- 打包产物附带 `USAGE.md`、`LICENSE.txt`、`NOTICE.md`
- 全新程序图标（绿色底 + 聊天气泡 + 导出箭头）：exe、窗口、网页 favicon 与顶栏 Logo 统一使用
- `tools/make_icon.py`：一键生成多尺寸 ICO / PNG / favicon
- 可执行文件更名为 `WeChatExporter.exe`，产物文件夹同步为 `dist\WeChatExporter\`
- 补齐 Windows 文件属性：文件描述、产品名、版本、版权、原始文件名（`packaging/version_info.txt`）
- 导出 HTML 图片支持点击放大预览（灯箱），聊天图片与转发记录图片均生效，Esc 或点击空白处关闭
- 第一步新增「Everything 查找」：内置 Everything 便携版（`everything\`），未运行会静默启动（无窗口、不占任务栏、不弹 UAC），通过 `es.exe` 搜索 `db_storage` / `xwechat_files`，自动定位微信数据目录；退出程序时关闭由它启动的实例
- 选中数据目录后支持递归查找账号，兼容微信更改存储路径、选中上层目录的情况

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
