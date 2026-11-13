# 架构说明

本文档说明项目的分层、核心算法与关键实现，供二次开发参考。

## 1. 总体结构

```
app.exe（pywebview 原生窗口）
  └─ 本地 FastAPI（127.0.0.1，随机端口）
       ├─ /api/bootstrap        账号与运行环境
       ├─ /api/keys             提取密钥（后台任务）
       ├─ /api/decrypt          解密数据库（后台任务）
       ├─ /api/media            图片 / 语音 / 视频（后台任务）
       ├─ /api/sessions         会话列表
       ├─ /api/chat             消息预览
       ├─ /api/export           导出（后台任务）
       ├─ /api/jobs/{id}        任务进度
       └─ /api/file             本地媒体文件（白名单）
```

前端（Vue 3 + Naive UI）通过 HTTP 调用本地服务，长任务通过轮询 `/api/jobs/{id}` 获取进度。

## 2. 目录与模块

| 模块 | 职责 |
|---|---|
| `app/main.py` | 启动 FastAPI 线程 + pywebview 窗口 |
| `app/config.py` | 配置读写、账号目录推导 |
| `app/api/routes.py` | 路由、任务编排、静态资源挂载 |
| `app/core/discovery.py` | 数据目录 / 账号 / 微信版本 / kvcomm code 发现 |
| `app/core/keys.py` | 密钥提取（两种策略） |
| `app/core/decrypt.py` | SQLCipher 4 页面解密 |
| `app/core/media.py` | 图片 / 语音 / 视频索引与转码 |
| `app/core/message_parser.py` | 富消息 XML 解析 |
| `app/core/export.py` | 会话解析、HTML 渲染、归档导出 |
| `app/core/jobs.py` | 后台任务与进度 |

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

### 6.2 语音

`media_0.db` 的 `VoiceInfo.voice_data` 为 SILK v3，用 `pilk` 解码为 PCM 后封装 WAV。

### 6.3 视频

- 源文件：`msg/video/<月份>/<随机哈希>.mp4`、`msg/attach/**/Rec/**/V/*.mp4`
- 文件名不可直接对应消息；视频消息 XML 的 `md5` = 明文文件 MD5，因此需要计算本地文件哈希建立索引
- 索引持久化到 `media/<账号>/video_index.json`，按 mtime/size 增量
- 编码兼容：导出所选会话时，将涉及的 HEVC 按需转码为 H.264，缓存到 `media/<账号>/videos_h264/<md5>.mp4`

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
- 聊天记录（19）解析 `<recorditem>` 的 `datalist`，支持展开明细
- 未知类型只输出标题或 `[应用消息]`，绝不泄漏 XML

## 8. 导出设计

`export.export_chats()` 支持两种模式：

1. **归档模式（默认）**
   - 每个会话一个文件夹：`index.html`、可选 `txt/json/csv`、`images/`、`videos/`、`audio/`、`manifest.json`
   - 只复制会话实际引用的媒体，按源路径去重
   - 硬链接优先（`os.link`），失败回退 `shutil.copy2`
   - HTML 使用相对路径
2. **引用模式**：与旧版一致，HTML 使用 `file:///` 绝对路径，不复制媒体

媒体命名：`YYYY-MM-DD_HH-MM-SS_哈希前8位.ext`（音频为 local_id）。

## 9. 安全边界

- 只监听 `127.0.0.1`
- 无任何外网请求
- `/api/file` 白名单限制：微信数据目录、解密数据、媒体缓存、导出目录
- 原始微信数据只读
