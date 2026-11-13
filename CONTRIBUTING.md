# 贡献指南

感谢你对本项目的关注！提交代码前请阅读以下约定。

## 开发环境

1. Windows 10/11，Python 3.11+，Node.js 18+
2. 按 README「快速开始」安装依赖并构建前端
3. 后端开发服务：

```bash
.venv\Scripts\python -m uvicorn app.api.routes:create_app --factory --port 8765
```

4. 前端开发服务：

```bash
cd webui && npm run dev
```

## 代码规范

- Python：PEP 8，4 空格缩进，类型标注按现有风格使用
- 前端：TypeScript + Vue 3 `<script setup>`，组件样式使用 scoped CSS
- 提交信息使用清晰的祈使句，例如：
  - `feat: support wechat 4.2.1 key format`
  - `fix: video playback for HEVC sources`
  - `docs: update compatibility matrix`

## 提交前检查

- [ ] 不包含真实聊天记录、密钥、wxid、手机号、头像等个人数据
- [ ] 新增解析类型附带**合成数据**测试（参考 `tests/test_parser.py`）
- [ ] 不引入网络请求或数据上传
- [ ] 本地运行 `python tests/test_parser.py` 通过
- [ ] 修改了导出格式时，同步更新 `docs/ARCHITECTURE.md` 与 README

## 提交 Pull Request

1. Fork 本仓库并创建功能分支
2. 保持改动聚焦，一个 PR 解决一个问题
3. 在 PR 描述中说明动机、实现方式与验证方法
4. 涉及兼容性变化的，请注明测试过的微信版本

## 安全与隐私

- 安全漏洞请按 [SECURITY.md](SECURITY.md) 私下报告，不要公开 Issue
- 请勿在 Issue / PR 中粘贴真实聊天内容、密钥或导出的数据库

## 许可

提交的代码视为同意以 MIT License 授权。
