# 兼容性说明

## 支持的微信版本

| 微信版本 | 密钥方式 | 数据库 | 图片 | 语音 | 视频 | 状态 |
|---|---|---|---|---|---|---|
| 4.0.x | 内存明文 `x'<key><salt>'` | ✅ | ✅ | ✅ | ✅ | 理论支持，未广泛实测 |
| 4.1.11+ | `Config.Cipher` XOR 掩码 | ✅ | ✅ | ✅ | ✅ | 支持 |
| 4.2.0.13 | `Config.Cipher` XOR 掩码 | ✅ | ✅ | ✅ | ✅ | 已实测 |

> 微信 3.x 数据结构不同，不在支持范围内。

## 各版本的关键差异

### 密钥存储

- **4.0.x**：WCDB 在进程内存中以 ASCII 明文缓存 `x'<64hex enc_key><32hex salt>'`
- **4.1.11+**：明文不再出现，改为 `Config.Cipher` 对象中以 32 字节固定掩码 XOR 后的 blob

### 图片密钥

与数据库密钥不同，V2 图片密钥可以**完全离线推导**：

```
code     = kvcomm 文件名 key_<code>_*.statistic 中的 code
xor_key  = code & 0xFF
aes_key  = md5(f"{code}{wxid}")[:16]
```

程序会用账号自己的图片验证候选密钥，验证通过才使用。

### 视频编码

微信视频混用 H.264 与 HEVC（H.265）。浏览器默认不解码 HEVC，
程序会在准备数据时把 HEVC 转码为 H.264 缓存，以保证播放。

## 升级微信后可能失效的点

| 变化 | 表现 | 需要修改 |
|---|---|---|
| `local_type` 编码方式 | 消息类型解析错误 | `message_parser.split_local_type()` |
| `Config.Cipher` 对象布局 | 提取不到密钥 | `keys.config_cipher_scan()` |
| XOR 掩码 | 解出的密钥无效 | `keys.CONFIG_MASK` |
| 数据库页面参数 | 解密后 SQLite 校验失败 | `decrypt.py` 常量 |
| appmsg 子类型 | 富消息显示异常 | `message_parser` 对应分支 |
| 媒体目录结构 | 图片/视频找不到 | `media.py` / `export.py` 路径规则 |

## 已知限制

- 微信未缓存的媒体（图片、视频、文件）无法离线还原
- 部分转发聊天记录中 `sourcename` 被微信自身写为时间，无法恢复真实发送者
- 语音仅支持 `VoiceInfo` 中保存的 SILK v3 数据
- 视频转码会增加磁盘占用（H.264 缓存位于 `media/<账号>/videos_h264`）
