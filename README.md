# PDF Studio

> **WPS 免费版 PDF 工具箱补位** · 本地离线 · 无广告 · 跨平台桌面应用

在 WPS 免费版中阅读与编辑文档；当需要 **WPS 会员才提供的 PDF 处理能力**（拆分、合并、压缩、加密、水印、OCR 等）时，使用 PDF Studio 在本地免费完成。

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![PyQt6](https://img.shields.io/badge/PyQt6-6.6+-green.svg)](https://pypi.org/project/PyQt6/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)]()

---

## ✨ 功能特性

| 模块 | 功能 | 说明 |
|------|------|------|
| **PDF 拆分** | 自定义范围 · 按页数 · 按书签 · 按大小 · 空白页 | 对应 WPS 会员「PDF 拆分」 |
| **PDF 合并** | 拖拽排序 · 自动书签 · 重复检测 · 列表校验 | 对应 WPS 会员「PDF 合并」 |
| **页面管理** | 提取 / 删除 / 旋转 · 奇偶页 · 插入/复制页 | 对应 WPS 会员「提取/删页」 |
| **PDF 对比** | 页数 / 体积 / 文本抽样对比 | 轻量版本差异检查 |
| **PDF 压缩** | 高质量/均衡/极限/智能压缩 | 对应 WPS 会员「PDF 压缩」 |
| **加密解密** | AES-256 加密 · 权限控制 | 对应 WPS 会员「加密」 |
| **水印页码** | 文字/图片水印 · 灵活页码 | 对应 WPS 会员「水印/页码」 |
| **PDF 工具** | 去水印 · 表单 · 签名 · 涂黑 · 元数据 | 会员高级 PDF 工具本地替代 |
| **图片工具** | PDF↔图片 · 长图/网格合并 · **图片压缩** · 扫描增强 | 对应 WPS 会员「PDF 转图片」及日常图片处理 |
| **OCR 识别** | 中/英/日/韩 · 离线 · 可配模型/GPU | 对应 WPS 会员「OCR」 |
| **网页转 PDF** | Chromium · 懒加载 · 网页长截图 | 本地网页采集 |
| **批处理中心** | 多步骤工作流 · 失败自动重试 | 批量自动化 |
| **阅读批注** | 按需渲染 · 搜索 · 全套批注工具 | 可配合 WPS 免费阅读 |
| **任务队列** | 首页后台任务 · 排队 · 满队提示 | 多任务并行管理 |

> PDF 核心处理完全离线；OCR 首次使用会下载模型；网页功能需 Playwright 或本机 Chrome/Edge。

---

## 🚀 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 自动检查/补装核心依赖（含 PDF 加密所需的 cryptography）
python scripts/ensure_deps.py --install

# 安装 Playwright Chromium（网页转 PDF，可选）
playwright install chromium

# 启动（首次启动会显示依赖向导）
python main.py
```

---

## 📁 项目结构

```
pdf_studio/
├── main.py              # 应用入口
├── app/                 # UI 层（PyQt6）
│   ├── pages/           # 功能页面
│   ├── widgets/         # 共用控件（拖放区、合并列表、样式）
│   ├── workers/         # 后台 Worker
│   ├── config/          # 配置系统
│   └── ui/              # 主窗口、向导、全局样式
├── core/                # 业务逻辑层（无 UI 依赖）
│   ├── pdf/             # PDF 处理引擎
│   ├── image/           # 转图 / 合并 / 压缩 / 增强
│   ├── ocr/             # OCR 识别
│   └── web/             # 网页转 PDF
├── scripts/             # ensure_deps、pack_smoke 等
├── tests/               # 单元 / 集成 / UI smoke
```

---

## 🧪 运行测试

```bash
# 开发依赖（含 pytest-qt，用于 UI smoke）
pip install -r requirements-dev.txt

pytest tests/ -v
# 当前基线：116 passed，1 skipped（无 pytest-qt 时 UI smoke 跳过）
```

Windows 可双击 `scripts\run_tests.bat`（Conda 环境 `pdf-Assist`）。

**CI**：`.github/workflows/ci.yml` 在 push/PR 时对 Ubuntu + Windows、Python 3.12 运行上述测试（Linux 需 offscreen Qt）。

可选环境变量：`PDF_STUDIO_TEST_ROOT` 指向含 `pdf/`、`图片/` 子目录的样本根路径。

---

## 📦 打包

```bash
pip install pyinstaller
python scripts/ensure_deps.py --install   # 确保 cryptography 等完整
# 打包前将图标置于 app/resources/icons/app.ico（运行 python scripts/generate_app_icon.py 生成）
pyinstaller pdf_studio.spec
# 输出在 dist/PDFStudio/
```

发布前验收请参考 [发布冒烟清单.md](发布冒烟清单.md)。

自动化打包冒烟（Conda 环境 `pdf-Assist`）：

```bash
python scripts/pack_smoke.py
# 仅验收已有 dist：python scripts/pack_smoke.py --skip-build --skip-pytest
```

打包输出在 `dist/PDFStudio/`；冻结包核心链路自检：`PDFStudio.exe --pack-smoke`（结果写入同目录 `pack_smoke_result.txt`）。

---

## 📖 文档

- [使用说明](使用说明.md)
- [技术说明](技术说明.md)
- [发布冒烟清单](发布冒烟清单.md)

---

## 🔧 技术栈

- **GUI**：PyQt6 + PyQt6-Fluent-Widgets（Fluent Design，含全局补充样式）
- **PDF**：PyMuPDF · pypdf · cryptography
- **图像**：Pillow · OpenCV
- **OCR**：RapidOCR (ONNX)
- **网页**：Playwright + Chromium / 系统浏览器
- **配置**：Pydantic v2
- **日志**：loguru

---

## ⚠️ 许可证注意

- PyMuPDF 使用 **AGPL** 许可，商业分发请购买商业版
- PyQt6 商业分发需要 Qt 商业许可证
