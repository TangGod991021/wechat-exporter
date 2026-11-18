# 架构说明

本文档说明项目的分层、核心算法与关键实现，供二次开发参考。

## 1. 总体结构

```
app.exe（pywebview 原生窗口）
  └─ 本地 FastAPI（127.0.0.1，随机端口，API 需访问令牌）
       ├─ /api/bootstrap        账号与运行环境
       ├─ /api/config           配置读写
       ├─ /api/pick-folder      选择数据目录
       ├─ /api/locate-wechat    Everything 自动定位数据目录
       ├─ /api/keys             提取密钥（后台任务）
       ├─ /api/core             建立会话索引（后台任务）
       ├─ /api/prepare          按所选会话准备媒体（后台任务）
       ├─ /api/decrypt          解密数据库（后台任务）
       ├─ /api/media            图片 / 语音 / 视频（后台任务）
       ├─ /api/sessions         会话列表（读取缓存，快速返回）
       ├─ /api/sessions/refresh 解析会话列表（后台任务，带进度）
       ├─ /api/chat             消息预览
       ├─ /api/export           导出（后台任务）
       ├─ /api/jobs/{id}        任务进度
       ├─ /api/jobs/{id}/cancel 请求取消任务
       ├─ /api/open-path        用系统程序打开白名单目录/附件
       ├─ /api/file             本地媒体/附件文件（白名单）
       └─ /api/sticker          按需下载并缓存表情
```

前端（Vue 3 + Naive UI）通过 HTTP 调用本地服务，长任务通过轮询 `/api/jobs/{id}` 获取进度。

## 2. 目录与模块

| 模块 | 职责 |
|---|---|
| `app/main.py` | 单实例互斥、端口重试与 `/api/bootstrap` 身份校验、pywebview 窗口 |
| `app/config.py` | 配置原子读写、只读目录回退 `%LOCALAPPDATA%`、账号目录推导 |
| `app/api/routes.py` | 路由、任务编排、静态资源挂载 |
| `app/core/discovery.py` | 数据目录 / 账号 / 微信版本 / kvcomm code 发现；集成 Everything（`es.exe` / HTTP JSON）快速定位 `xwechat_files`，不可用时回退本地递归扫描 |
| `app/core/keys.py` | 密钥提取（两种策略） |
| `app/core/decrypt.py` | SQLCipher 4 页面解密 |
| `app/core/media.py` | 图片 / 语音 / 视频索引与转码 |
| `app/core/message_parser.py` | 富消息 XML 解析（含表情、文件、转账、链接） |
| `app/core/emoji.py` | 微信内置表情代码（`[微笑]` 等）→ Unicode 映射 |
| `app/core/textutil.py` | 多轮 HTML 反转义与 URL 清洗（处理 `&amp;amp;`、`&lt;/url&gt;`） |
| `app/core/links.py` | B 站短链检测/解析、搜索链接与状态缓存 |
| `app/core/attachments.py` | 本地附件索引与按名称/大小/时间匹配 |
| `app/core/stickers.py` | 表情 CDN 下载、缓存与域名白名单 |
| `app/core/export.py` | 会话解析、HTML 渲染、归档导出 |
| `app/core/jobs.py` | 后台任务与进度；同类型任务互斥、进度回调处检查取消 |
| `app/core/tools.py` | 内置 FFmpeg/ffprobe 定位；启动时把工具目录前置到 `PATH` |

启动流程要点：

- Windows 命名互斥量防止双实例；重复启动时提示并尝试打开 `.runtime_url` 中记录的地址
- 端口随机探测后绑定，被占用时重试（最多 3 个候选端口）
- `wait_server` 除探测端口外还会请求 `/api/bootstrap` 并校验 `version`，避免误连其他本地服务
- 启动等待上限 60 秒；成功后在 `.runtime_url` 写入带令牌的地址，退出时删除
- 配置写入使用临时文件 + `os.replace`；损坏的 `config.json` 会改名为 `.json.bad`
- 程序目录不可写（如 Program Files）时，配置与数据目录回退到 `%LOCALAPPDATA%\WeChatExporter`
- 后台任务失败会追加到 `运行日志.log`（当前配置目录）

进度与状态约定：

- 长任务统一通过 `Job.update(pct, message)` 上报；密钥扫描按已读内存 MB、数据库解密按源库字节加权与页数上报，避免大库/大内存时进度长时间不动
- `/api/sessions/refresh` 是后台任务：读取消息库、逐表 `count(*)` 时上报进度，前端显示进度条；结果写入 `data/<账号>/session_counts.json` 缓存
- `data/<账号>/prepared.json` 记录第 4 步已准备的会话列表；`/api/bootstrap` 以 `prepared_targets` 返回，前端据此恢复「已准备」状态（刷新/重启后仍可导出）
- `data/<账号>/session_counts.json` 按消息库 mtime/size 缓存各会话消息数（v2 起跨分库累加），避免每次进入会话页都全量 `count(*)`
- 消息分库：同一会话的 `Msg_<md5>` 表可能同时出现在 `message_0.db`、`message_1.db` … 中（微信滚动分片），`ChatStore` 保存「表名 → 分库列表」，读取时逐库查询并按 `(create_time, sort_seq, local_id)` 合并、去重；公众号消息在 `biz_message_*.db`

## 3. 微信 4.x 数据结构要点

### 3.1 复合 local_type

`Msg_<md5(用户名)>` 表中的 `local_type` 是复合编码：

```
local_type = (sub_type << 32) | base_type
```

例如：

- `244813135921 = (57 << 32) | 49`：应用消息，子类型 57（引用）
- `25769803825  = (6  << 32) | 49`：文件
- `25769803825` 之外的常见 base：1 文本、3 图片、34 语音、43 视频、47 表情、10000 系统

解析入口为 `message_parser.split_local_type()`。

### 3.2 消息内容压缩

`message_content` / `source` 以 zstd 压缩，魔数 `28 b5 2f fd`。`export.dec()` 负责判断并解压。

### 3.3 发送者

`real_sender_id` → `Name2Id.rowid` → `user_name`。

> 注意：`select user_name from Name2Id` 可能走索引按字母序返回，必须显式 `select rowid, user_name`，否则映射错位。

## 4. 密钥提取

### 4.1 4.0.x：内存明文

WCDB 在内存中以 ASCII `x'<64hex enc_key><32hex salt>'` 缓存密钥。扫描进程可读内存，用页面 1 的 HMAC 校验候选。

### 4.2 4.1.11+：Config.Cipher 掩码

- 在内存中定位字符串 `com.Tencent.WCDB.Config.Cipher`
- 找到引用它的 `(指针, 长度)` 节点：`node + 0x28` → config 对象
- `config + 0x88` 为缓冲描述：`+0x08` 数据指针、`+0x10` 长度
- 读出 blob，按固定 32 字节掩码 XOR，得到 `x'<enc_key><salt>'`
- 用 salt 匹配数据库并用 HMAC 校验

掩码随版本可能变化，见 `docs/COMPATIBILITY.md`。

## 5. 数据库解密

SQLCipher 4 页面格式（4096 字节，reserve 80）：

```
page 1 ：[salt 16][ciphertext 4000][IV 16][HMAC 64]
page >1：[ciphertext 4016][IV 16][HMAC 64]
```

- AES-256-CBC，无 padding
- `mac_key = PBKDF2-SHA512(enc_key, salt ^ 0x3a, 2, 32)`
- 解密后写入标准 SQLite 页面（reserve 区域补零）
- 源库必须整页对齐（否则视为正在写入/被截断而失败）
- 先写 `*.tmp` 并校验输出 SQLite 头，成功后 `os.replace` 原子替换；跳过已有文件时同时校验大小
- 消息库按实际存在的 `message/message_*.db`、`media_*.db` 动态解密，兼容多分片账号

实现：`app/core/decrypt.py`。

## 6. 媒体处理

### 6.1 图片

- V2 `.dat`：头 15 字节 + AES-128-ECB 密文 + 原始段 + XOR 尾部
- 图片 AES key 离线推导（来自 ChatTrace 思路）：
  - `code` 取自 `%APPDATA%\Tencent\xwechat\*\kvcomm\key_<code>_*.statistic`
  - `xor_key = code & 0xFF`
  - `aes_key = md5(f"{code}{wxid}")[:16]`
  - 用账号自己的图片验证候选 key
- PKCS7 补齐：密文长度 = `(aes_size // 16 + 1) * 16`
- WxAM（`wxgf`）：`wxgf` 头 + ICC/Exif + HEVC 裸流；优先 PyAV 解码首帧，失败回退 ffmpeg
- 转发聊天记录中的图片使用消息 md5，需经 `hardlink/hardlink.db` 的
  `image_hardlink_info_v4` 映射到本地 `.dat` 文件名后再定位

### 6.2 语音

`media_0.db` 的 `VoiceInfo.voice_data` 为 SILK v3，用 `pilk` 解码为 PCM 后封装 WAV。
语音目录按 `Name2Id.user_name`（wxid/@chatroom）命名，导出时同样按 username 查找，不能使用备注名。

### 6.3 视频

- 源文件：`msg/video/<月份>/<随机哈希>.mp4`、`msg/attach/**/Rec/**/V/*.mp4`
- 文件名不可直接对应消息；视频消息 XML 的 `md5` = 明文文件 MD5，因此需要计算本地文件哈希建立索引
- 索引持久化到 `media/<账号>/video_index.json`，按 mtime/size 增量
- 编码兼容：准备所选数据时，将涉及的 HEVC 按需转码为 H.264（强制 `-pix_fmt yuv420p`），缓存到 `media/<账号>/videos_h264/<md5>.mp4`
- FFmpeg/ffprobe 可用性通过 `media.ffmpeg_status()` 汇总到 `/api/bootstrap`；WxAM 回退同样使用配置的 ffmpeg 路径
- 无法探测编码的视频计入 `probe_failed`，准备任务会提示，而非静默跳过

### 6.4 增量与并发

- 图片 / 语音 / WxAM：产物存在且 mtime 不早于源文件则跳过
- 图片、语音使用分块 `ProcessPoolExecutor`；WxAM 使用 PyAV 进程内解码
- 图片与语音并发执行；视频只建立索引，HEVC 在导出阶段按所选会话转码

## 7. 富消息解析

`message_parser.parse_content(local_type, raw)` 返回统一结构：

```json
{
  "kind": "quote|link|file|miniprogram|...",
  "text": "TXT/CSV 使用的可读摘要",
  "title": "...", "des": "...", "url": "...",
  "quote": {"sender": "...", "text": "..."},
  "records": [...]
}
```

- 引用（57）会递归解析被引用的内容
- 聊天记录（19）与笔记（24）解析 `<recorditem>` 的 `datalist`（含 HTML 转义形式）
- 表情/动图（8）输出 `[表情]` / `[动图]`；群公告（87）解析 `announcement` 的 `datalist`
- 名片（42）保留昵称/username；位置（48）保留 label/poiname/城市并生成高德地图链接
- 群聊消息前缀 `发送者:\n` 在解析前按真实 sender 精确剥离，兼容自定义微信号
- 未知类型只输出标题或 `[应用消息]`，绝不泄漏 XML

## 8. 导出设计

`export.export_chats()` 支持两种模式：

1. **归档模式（默认）**
   - 每个会话一个文件夹：`index.html`、可选 `txt/json/csv`、`images/`、`videos/`、`audio/`、`manifest.json`
   - 只复制会话实际引用的媒体，按源路径去重
   - 硬链接优先（`os.link`），失败回退 `shutil.copy2`
   - HTML 使用相对路径
2. **引用模式**：与旧版一致，HTML 使用 `file:///` 绝对路径，不复制媒体；
   文件名附加 username 摘要，避免同名会话互相覆盖

单个会话导出失败不会中断整批：错误写入返回值 `errors` 与批次 `manifest.json`。
归档模式下媒体复制失败会记入 `missing_media`，HTML 中标记 `[媒体缺失]`，不再回退绝对
`file:///` 路径；气泡使用 `white-space: pre-wrap` 保留换行。Windows 非法字符、保留设备名
（CON/NUL 等）会在文件名中处理。

媒体命名：`YYYY-MM-DD_HH-MM-SS_哈希前8位.ext`（音频为 local_id）。

## 9. 安全边界

- 只监听 `127.0.0.1`；启动时生成随机访问令牌，页面通过 `?token=` 获取，API 请求需携带
  `X-Auth-Token` 或 `token` 查询参数（媒体直链用后者）；非本机 Host 一律 403，防 DNS rebinding
- 不启用 CORS：跨源页面无法读取接口响应
- `/api/file` 仅允许媒体缓存与导出目录，按目录边界校验（不接受前缀绕过）
- `/api/open-path` 仅允许打开媒体缓存/导出目录内的路径
- 消息中的链接只允许 `http/https/mailto`，前端与导出 HTML 双端过滤
- 无任何外网请求
- 原始微信数据只读
