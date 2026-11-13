# 界面截图

本页集中展示程序界面，方便前端与文档维护者快速了解布局、配色和交互。所有截图均使用**虚构演示数据**生成，不包含任何真实微信账号、会话或聊天内容。

界面基于 Vue 3 + Naive UI，主色 `#07c160`（微信绿），支持浅色 / 深色两种主题。

---

## 1. 选择账号（浅色）

四步向导的第一步。自动扫描本机微信 4.x 数据目录，展示账号昵称、wxid、数据体积、数据库数量与最近活跃时间；已完成解密的账号带有状态标签。

![选择账号](screenshots/01-accounts-light.png)

## 2. 准备数据（浅色）

密钥、数据库、图片/视频、语音四个处理卡片的统一入口。顶部提供「一键完成」，卡片内展示各自状态与实时进度；底部控制台输出任务日志。

![准备数据](screenshots/02-prepare-light.png)

## 3. 选择会话（浅色）

支持搜索、按「全部 / 群聊 / 私聊」过滤、全选当前列表。每行展示头像首字、会话名、最近一条消息摘要、消息总数与时间。

![选择会话](screenshots/03-sessions-light.png)

## 4. 消息预览（浅色）

点击会话行打开预览。聊天气泡区分「我」与对方；支持引用、链接、文件、图片、转账、转发聊天记录等富消息类型。

![消息预览](screenshots/04-chat-preview-light.png)

## 5. 转发聊天记录明细（浅色）

在预览中点击「聊天记录」卡片，可展开转发内容的消息明细。

![转发聊天记录明细](screenshots/05-record-detail-light.png)

## 6. 导出设置（浅色）

选择导出格式（HTML / TXT / JSON / CSV）、时间范围、输出目录与导出方式（归档文件夹 / 仅引用本机文件）。

![导出设置](screenshots/06-export-light.png)

## 7. 导出进度（浅色）

导出过程中展示进度条与当前处理信息。

![导出进度](screenshots/07-export-progress-light.png)

## 8. 导出完成（浅色）

完成后列出生成的文件，可逐个打开或直接打开导出目录。

![导出完成](screenshots/08-export-done-light.png)

## 9. 导出完成（深色）

深色模式下的导出页，配色随主题切换。

![导出完成（深色）](screenshots/09-export-done-dark.png)

## 10. 选择会话（深色）

![选择会话（深色）](screenshots/10-sessions-dark.png)

## 11. 消息预览（深色）

![消息预览（深色）](screenshots/11-chat-preview-dark.png)

---

## 重新生成截图

截图由脚本自动生成，接口数据全部在脚本内模拟：

```bash
# 1. 构建前端（webui/dist）
cd webui && npm run build && cd ..

# 2. 安装 Playwright（仅首次）
pip install playwright
playwright install chromium

# 3. 生成到 docs/screenshots/
python tools/capture_screenshots.py
```

脚本说明见 [`tools/capture_screenshots.py`](../tools/capture_screenshots.py)。修改界面后请重新运行，保持截图与代码一致。
