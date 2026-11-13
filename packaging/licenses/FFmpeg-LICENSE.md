# FFmpeg / PyAV 许可说明

本程序通过 PyAV（BSD-3-Clause）间接分发 FFmpeg 运行库。PyInstaller 产物中的
`_internal/av.libs/` 包含 FFmpeg 的以下组件及其编码器：

- `avcodec` / `avformat` / `avutil` / `avfilter` / `avdevice` / `swscale` / `swresample`
- 第三方编码器/解码器：`libx264`、`libx265`、`libmp3lame`、`libopus`、`libvpx`、
  `libdav1d`、`libSvtAv1Enc`、`libwebp` 等

其中 `libx264`、`libx265` 采用 GPL 许可，因此随包分发的 FFmpeg 组合按
**GPL v2 或更高版本**分发；其余组件分别适用 LGPL v2.1 或各自兼容的许可。

## 对应源码

- FFmpeg 源码：https://ffmpeg.org/download.html
- PyAV 源码：https://github.com/PyAV-Org/PyAV
- 具体构建配置由 PyAV 官方 wheel 提供，可在 wheel 的 `av.libs` 目录与
  https://pypi.org/project/av/ 查询对应版本

如需本程序所捆绑 FFmpeg 组件的完整源码，请通过项目仓库提交 Issue 获取，
或按上述地址下载相同版本的 FFmpeg 源码。

## 许可证全文

- GNU General Public License v2：同目录 `GPLv2.txt`
- GNU Lesser General Public License v2.1：同目录 `LGPLv2.1.txt`

再分发本程序的二进制包时，请同时保留本文件及上述许可证文本。
