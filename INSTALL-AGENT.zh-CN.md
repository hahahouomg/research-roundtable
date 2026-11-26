# 安装和验收科研圆桌

[English](INSTALL-AGENT.md) · **简体中文** · [项目介绍](README.zh-CN.md)

把本文件交给目标电脑上的编程代理，让它完成安装并核对模型接入。

1. 克隆仓库或解压 GitHub 源码 ZIP。复用已有的 Python 3.10+ 环境，需要创建环境时使用 Miniforge/Mamba。需要实施预览时安装 Git。圆桌不需要构建前端或安装 Python 包。
2. 检查 `codex --version` 和 `agy --version`。缺少时按 [Codex CLI](https://developers.openai.com/codex/cli/) 和 [Antigravity CLI](https://antigravity.google/docs/cli/tutorial) 官方指南安装。让用户在目标电脑用自己的账号登录。Windows 修改 PATH 后，重新打开终端。确需指定执行文件时用 `ROUNDTABLE_CODEX_BIN` 或 `ROUNDTABLE_AGY_BIN`。
3. Windows 双击 `start-roundtable.cmd`，或运行 `python -X utf8 -B roundtable.py web`。macOS 可双击 `启动圆桌.command`。macOS 或 Linux 终端运行 `python3 -B roundtable.py web`。保持进程运行并打开[圆桌](http://127.0.0.1:8765/)。
4. 核对网页能打开、能切换中英文、能选择已有项目目录。PDF 导出是可选项，由 Gemini 排版后用本机 Chrome、Chromium 或 Microsoft Edge 生成。
5. 更新前结束运行中的任务并备份本机数据，再更新代码。默认数据目录是 `data/`，也可以通过 `ROUNDTABLE_HOME` 指定。分享源码和迁移个人数据分别操作。

## 验收模型接入

Windows 在仓库目录运行以下命令。macOS 和 Linux 终端用 `python3`。

```powershell
python -X utf8 -B roundtable.py status
python -X utf8 -B roundtable.py model list codex
python -X utf8 -B roundtable.py model list gemini
```

- **找到 CLI。** `status` 显示执行文件，以及有记录时最近一次调用的结果。
- **列出型号。** 两条 `model list` 读取本机 CLI 提供的选项。网页可点开对应席位选型号。
- **实测调用。** 经用户同意后，在网页分别选**只问 Codex**和**只问 Gemini**，各发一个无敏感内容的短问题。根据实际回复报告哪些选定型号可用。实测使用账号额度，也会留下正常讨论记录。
- **查询额度。** 点击**订阅额度**可单独验收额度查询。Windows 原生环境可在 agy 终端运行 `/usage` 查看 Gemini 的额度。

离线检查运行 `python -X utf8 -B -m unittest discover -v`。
