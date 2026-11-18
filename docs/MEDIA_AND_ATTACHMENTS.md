# 表情、附件、转账、链接与语音

本文说明微信 4.x 聊天记录中各类富内容的解析与获取方式，以及界面/导出中的交互。

## 功能说明

| 内容 | 解析来源 | 获取方式 | 界面/导出行为 |
|---|---|---|---|
| 表情 | base 47 `<emoji>`；appmsg type 8 `appattach/emojiinfo` | 读取消息里的腾讯 CDN 地址，下载到 `media/<账号>/stickers/` | 显示图片，点击放大；导出复制到 `images/` |
| 内置表情 | 正文中的 `[微笑]`、`[破涕为笑]` 等代码 | `app/core/emoji.py` 映射为 Unicode 表情 | 正文、引用、转发记录、转账备注等直接显示为 😊😂🙏 |
| 文件附件 | appmsg type 6/74 的 `title`、`totallen`、`fileext` | 在 `msg/file`、`msg/attach/**/F` 中按名称/大小/月份定位 | 预览可「打开/下载」；归档导出复制到 `files/`；找不到时标注 |
| 转账 | appmsg subtype 2000 `wcpayinfo` | 解析 `feedesc`、`paymememo`、`receivertitle` 等 | 卡片显示金额、备注、状态 |
| 红包 | appmsg subtype 2001 `wcpayinfo` | 同上 | 卡片显示祝福语、状态 |
| 链接 | appmsg subtype 5；正文 URL；引用/转发记录中的 `<link>` | 直接使用 URL | 可点击跳转（新窗口） |
| 语音 | base 34 + `media_0.db` VoiceInfo | SILK → WAV | 播放器 + 「下载语音」 |
| 转发/笔记 | appmsg subtype 19/24 `<recorditem>` | 逐条解析文本、图片、视频、文件、链接、表情 | 点击展开明细，支持打开/下载/放大 |

## 涉及文件

- `app/core/message_parser.py`：各类消息 XML 解析
- `app/core/emoji.py`：微信内置表情代码 → Unicode 映射
- `app/core/attachments.py`：本地附件索引与匹配
- `app/core/stickers.py`：表情 CDN 下载、扩展名探测、缓存
- `app/core/export.py`：`ChatStore` 消息富化、导出复制、HTML 渲染
- `app/core/prepare.py`：准备阶段批量下载表情
- `app/api/routes.py`：`/api/sticker`、附件目录访问权限、附件打开
- `webui/src/components/MessageContent.vue`：聊天预览交互
- `webui/src/App.vue`：图片放大、转发记录明细交互
- `tests/test_attachments.py`、`tests/test_stickers.py`、`tests/test_emoji.py`、`tests/test_parser.py`、`tests/test_export_errors.py`

## 核心逻辑

### 表情

- base 47 的 XML：`<emoji ... md5="..." cdnurl="..." />`；
  appmsg type 8 的 `emojiinfo` 是 base64 protobuf，里面包含数据地址和缩略图地址。
- 优先选择 `m=<md5>` 的地址。
- 本地 `cache/YYYY-MM/Emoticon/<md5>` 是加密格式，当前无法离线解密，因此按 CDN 下载。
- 下载只允许 `*.qq.com`、`*.qpic.cn`、`*.gtimg.cn`，单文件上限 32 MB，按文件头识别扩展名。
- 缓存文件名 `<md5>.<ext>`；重复导出直接命中缓存。
- 预览时 `<img src="/api/sticker?...">` 会在首次访问时下载并缓存。

### 内置表情代码

- 微信正文把内置表情保存为 `[微笑]`、`[抱拳]`、`[破涕为笑]` 等代码；
  `app/core/emoji.py` 提供代码到 Unicode 的映射（约 120 个常用表情）。
- 转换发生在解析阶段：正文、引用、转发记录、转账/红包备注、群公告、名片昵称等；
  已知代码替换，未知 `[xxx]` 原样保留。
- **文件名不转换**：文件消息的 `title` / `file_name` 保持原始名称，避免破坏本地附件匹配；
  发件人昵称、会话名称会转换后显示。
- 界面、HTML、TXT、CSV、JSON 输出均为转换后的 Unicode 表情。

### 图片选择与 WXAM 白帧

微信 4.x 同一个图片通常有 3 份本地缓存：

- `<md5>.dat`：中间图，可能是 WXAM/HEVC（部分文件的第 0 帧是白帧）
- `<md5>_h.dat`：高清原图（PNG/JPEG/MPO）
- `<md5>_t.dat`：缩略图

导出优先级为 **`_h` > 中间图 > `_t`**，优先保证清晰度与颜色。

若只有中间图：
- PyAV 解码时按灰度方差选择内容最丰富的一帧，跳过白帧；
- FFmpeg 回退使用 `thumbnail=24` 滤镜；
- 准备阶段如果发现旧版本生成的全白 JPG，会自动重新转换。

### 缺失媒体提示

本地找不到原图时，不能只显示 `[图片]`，否则用户会误以为导出失败。当前规则：

| 情况 | 消息文本 |
|---|---|
| 图片无本地文件 | `[图片]（图片已过期或已被清理）` |
| 只有 `_t` 缩略图 | `[图片]（原图已过期或已被清理，显示缩略图）` |
| 语音无本地文件 | `[语音 Ns]（语音已过期或已被清理）` |
| 视频无本地文件 | `[视频 X MB]（视频已过期或已被清理）` |
| 转发记录内图片/视频/语音 | 同上，写入对应记录项的 `text` |

提示写入消息 `text`，因此 HTML、JSON、TXT、CSV 与界面预览保持一致。

### 附件

- 文件消息 XML 只有 `title` / `totallen`，没有 md5，因此需要本地匹配：
  1. 精确文件名；
  2. 去掉 ` (1)`、` (2)` 后缀的同名文件；
  3. 依次按大小、消息月份、mtime 距离排序。
- 索引范围：`msg/file/**`（普通文件）和 `msg/attach/**/F/**`（收到的文件），
  跳过 `.dat` 等媒体缓存与 `Img/V` 目录。
- 转发聊天记录中的文件带 `fullmd5`，通过 `hardlink.db` 的
  `file_hardlink_info_v4(md5, file_name)` 映射到本地文件名；文件名不存在说明已被清理，
  不会误用同名不同版本。
- 导出：复制到 `<会话>/files/`，命名为 `YYYY-MM-DD_HH-MM-SS_原文件名`，HTML 使用相对路径。

### 链接跳转

| 来源 | 导出 HTML | 界面预览 |
|---|---|---|
| 链接卡片（type 5） | 整张卡片是 `<a target="_blank">` | 整卡可点击，显示「点击打开」 |
| 视频分享（type 4，B 站/抖音等） | 整卡可点击 | 整卡可点击 |
| 小程序（33/36）、音乐（3） | 有 `url` 时整卡可点击 | 有 `url` 时整卡可点击 |
| 正文/引用/转发记录中的 URL | `linkify` 生成 `<a>` | 点击时交给系统浏览器 |
| 本地文件/语音下载 | 相对链接 | `/api/file` |

界面预览运行在内嵌 WebView 中，`target="_blank"` 对 B 站/小红书等外部地址不可靠，
因此前端统一拦截 `http/https/mailto` 链接，调用 `POST /api/open-url` 用系统默认
浏览器打开。该接口拒绝 `file:`、`javascript:`、`data:` 等协议。

链接打开前会经过 `app/core/textutil.py` 清洗：

- `&amp;amp;` → `&`（多轮反转义）
- `&lt;/url&gt;`、空白、引号等 XML/HTML 残留直接截断
- 避免把 `https://b23.tv/x?...&amp;amp;...&lt;/url&gt;` 这类畸形地址交给浏览器

如果清洗后的短链接仍返回平台 404（例如 B 站 `啥都木有`），说明视频已删除或
短链已过期，属于链接源失效，无法由导出程序恢复。

### B 站短链检测与兜底

准备/导出时对 `b23.tv` 短链做一次检测（结果缓存 `media/<账号>/link_status.json`，7 天）：

| 检测结果 | 卡片行为 |
|---|---|
| 302 → 视频地址 | 卡片使用解析后的 `https://www.bilibili.com/video/BV...` 直链 |
| 200 + `啥都木有` | 卡片点击改为按标题搜索；显示「原短链已失效 · 点击按标题搜索」 |
| 网络失败 | 保留原短链，同时提供搜索入口 |

视频卡片下方提供：

- **📋 复制标题**：写入剪贴板（HTML 使用 Clipboard API，失败回退 `execCommand`）
- **搜索标题**：`https://search.bilibili.com/all?keyword=<标题>`
- **原短链**：仅在判定失效时显示

只对 `b23.tv` / B 站域名发起检测，不会探测消息中的其他任意地址。

### 转账 / 红包

`wcpayinfo` 常见字段：

- `feedesc`：金额（如 `￥88.00`）
- `paymememo` / `paymemo`：转账备注
- `sendertitle` / `receivertitle`：状态或祝福语
- `transferid` / `paymsgid`：单据号（仅展示/保留，不联网校验）

## 使用方式

1. 正常执行五步流程；第 4 步「准备数据」会同时下载所选会话引用的表情、解密图片、转换语音。
2. 预览聊天时，文件卡片提供「打开」（系统默认程序）与「下载」；表情和图片点击放大。
3. 导出归档模式会把可用附件复制到 `files/`，表情复制到 `images/`，语音复制到 `audio/`。

## 限制

- 本地表情缓存为加密格式，必须联网获取；CDN 链接失效或断网时显示「表情未下载」。
- 部分附件已被微信清理，只能标注「附件未缓存到本地」。
- 转账/红包的领取详情、对方信息依赖消息 XML 实际字段，部分版本字段缺失时只显示已有内容。

## 变更记录

| 日期 | 变更 |
|---|---|
| 2026-11-18 | 新增表情下载、附件定位与复制、转账/红包字段、链接跳转、语音下载；对应测试与文档 |
| 2026-11-18 | 新增微信内置表情代码（`[微笑]` 等）到 Unicode 的转换，文件名保持原样 |
| 2026-11-18 | 修复 WXAM/HEVC 首帧白图导致导出全白；图片优先使用 `_h` 高清原图，旧白图自动重转 |
| 2026-11-18 | 图片/语音/视频缺失时在消息文本中标注“已过期或已被清理”，仅缩略图也明确提示 |
| 2026-11-18 | 视频分享/小程序/音乐卡片整卡可点击；界面外链改由系统浏览器打开 |
| 2026-11-18 | 新增多轮反转义与 URL 清洗，修复双重转义导致的畸形链接 |
| 2026-11-18 | B 站短链检测/直链解析/失效改搜索；卡片增加复制标题按钮 |
