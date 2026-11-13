# 更新日志

本项目遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 新增

- 便携版一键打包脚本 `build-portable.bat`：自动安装依赖、构建前端、执行 PyInstaller 打包
- 打包产物附带 `USAGE.md`、`LICENSE.txt`、`NOTICE.md`

### 修复

- 打包后 `config.json` 与 `data/`、`media/`、`exports/` 固定落在 exe 同级目录，整个文件夹可直接拷贝到其他电脑运行

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
