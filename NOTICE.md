# NOTICE / 第三方说明

本项目在算法实现上参考了以下 MIT 许可的开源项目，特此致谢：

## 1. wechat-local-reader

- 项目：https://github.com/SmileGrassSky620/wechat-local-reader
- 许可：MIT License
- 参考内容：微信 4.1.11+ `Config.Cipher` 对象的内存布局与 XOR 掩码密钥提取思路
- 对应文件：`app/core/keys.py`

```
MIT License

Copyright (c) 2026 Leilong

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```

## 2. ChatTrace

- 项目：https://github.com/qiaodogbear/ChatTrace
- 许可：MIT License
- 参考内容：V2 图片（`.dat`）密钥的离线推导思路
  （`code` 取自 kvcomm 文件名，`aes_key = md5(code + wxid)[:16]`）
- 对应文件：`app/core/media.py`

```
MIT License

Copyright (c) 2026 ChatTrace contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
```

## 3. 运行时依赖

本项目依赖以下第三方库，其许可由各自项目规定：

| 依赖 | 许可 |
|---|---|
| FastAPI / Uvicorn | MIT / BSD-3-Clause |
| pywebview | BSD-3-Clause |
| PyCryptodome | BSD-2-Clause |
| python-zstandard | BSD-3-Clause |
| Pillow | HPND |
| pilk | MIT |
| PyAV | BSD-3-Clause |
| Vue 3 / Naive UI | MIT |
| FFmpeg（外部程序，未打包） | LGPL-2.1+ / GPL（取决于构建选项） |

如需再分发本项目，请同时保留上述声明，并确认 FFmpeg 的分发方式符合其许可要求。
