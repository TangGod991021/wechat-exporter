# 开发指南

## 环境

- Windows 10/11 x64
- Python 3.11+
- Node.js 18+
- 可选：FFmpeg（图片 WxAM、视频转码）

## 安装

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

cd webui
npm install --registry=https://registry.npmmirror.com
```

## 开发运行

后端：

```bash
.venv\Scripts\python -m uvicorn app.api.routes:create_app --factory --host 127.0.0.1 --port 8765
```

前端热更新：

```bash
cd webui
npm run dev
```

访问 http://localhost:5173 ，`/api` 会代理到 8765。

原生窗口：

```bash
.venv\Scripts\python run.py
```

## 构建前端

```bash
cd webui
npm run build
```

产物在 `webui/dist`，由 FastAPI 直接提供。

## 打包

```bash
.venv\Scripts\pip install pyinstaller
.venv\Scripts\pyinstaller packaging\app.spec
```

## 测试

```bash
# 富消息解析（离线合成数据）
.venv\Scripts\python tests\test_parser.py

# 真实数据库抽样（可选）
set WECHAT_EXPORTER_DB=D:\path\to\message_0.db
.venv\Scripts\python tests\test_parser.py
```

## 更新界面截图

`docs/screenshots/` 中的截图用于 README 与文档展示，由脚本自动生成（接口全部使用虚构演示数据，不读取本机微信数据）：

```bash
# 仅首次：安装 Playwright
pip install playwright
playwright install chromium

# 需先构建 webui/dist
cd webui && npm run build && cd ..
python tools/capture_screenshots.py
```

修改界面布局或配色后，请重新运行脚本并提交更新后的截图。说明见 `docs/SCREENSHOTS.md`。

## 新增消息类型

1. 在 `app/core/message_parser.py` 的 `_parse_appmsg()` 中增加分支
2. 返回统一结构（`kind/title/des/url/...`），未知类型必须降级为可读文本
3. 在 `tests/test_parser.py` 增加合成 XML 测试
4. 如需卡片样式，在 `app/core/export.py` 的 `_rich_body()` 与
   `webui/src/components/MessageContent.vue` 中同步实现

## 适配新的微信版本

1. 确认密钥提取失败的具体策略（4.0 明文 / 4.1.11+ 掩码）
2. 若为掩码策略，重新定位 `Config.Cipher` 对象布局与 XOR 掩码
3. 更新 `app/core/keys.py` 中的常量
4. 在 `docs/COMPATIBILITY.md` 记录测试结果

## 代码风格

- Python：PEP 8，4 空格
- Vue / TypeScript：`<script setup>`，2 空格，scoped CSS
- 提交信息：`feat:` / `fix:` / `docs:` / `refactor:` 前缀

## 隐私要求

提交前确认不包含任何真实聊天记录、密钥、wxid、手机号等个人数据。
