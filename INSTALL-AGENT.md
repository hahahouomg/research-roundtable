# 让安装代理配置科研圆桌

把本文件交给安装代理，让它在目标电脑上克隆仓库或解压 GitHub 的源码 ZIP，再逐项安装和验收。圆桌在本机浏览器运行，使用本机登录的 Codex 和 Antigravity CLI。Claude 是可选的第三席。

1. 查询操作系统、Python、Git 和现有环境。复用 Python 3.10 或更新版本及现有环境。需要创建环境时用 Miniforge/Mamba。圆桌本身无需 Python 包或前端构建。Windows 使用同一个环境里的 Python 和供应商 CLI。
2. 找到 `codex` 和 `agy`，并运行各自的 `--version`。若缺少，按本机系统从官方渠道安装。[Codex CLI](https://developers.openai.com/codex/cli/) · [Antigravity CLI](https://antigravity.google/docs/cli/tutorial)
3. 在本电脑终端分别运行 `codex` 和 `agy`，让用户用自己的账号完成登录或设备确认。Windows 重新打开终端以刷新 PATH。需指定二进制时设置 `ROUNDTABLE_CODEX_BIN` 和 `ROUNDTABLE_AGY_BIN`。从将来启动圆桌的同一个 Python 环境完成验收。
4. 只有用户要求加第三席时才安装并登录 Claude Code。让用户在网页打开 Claude 开关并填写这台安装机允许的公网 IPv4，或者运行 `python roundtable.py model claude ip <IPv4>`，再运行 `python roundtable.py model claude on`。配置存于部署机的 `ROUNDTABLE_HOME/claude-ip`（默认 `data/claude-ip`），由安装机用户管理。[Claude Code 安装指南](https://code.claude.com/docs/en/setup)
5. 启动圆桌。在 Windows 双击 `start-roundtable.cmd` 或进入项目目录运行下面的第一条命令。在 macOS 双击 `启动圆桌.command`，在 Linux 或 macOS 终端用第二条。启动时打印本机入口，默认 `http://127.0.0.1:8765/`。终端保持打开。

   ```text
   python -X utf8 -B roundtable.py web
   python3 -B roundtable.py web
   ```

6. 按下方清单验收接入情况。本机网页应能建项目、浏览文件夹和选择主持人。讨论记录和方案均可下载为 Markdown。用户选择「请 Gemini 排版 PDF」时，圆桌另行排版并用本机 Chrome、Chromium 或 Windows 上的 Edge 输出 PDF。若浏览器装在非标准位置，可设置 `ROUNDTABLE_CHROME_BIN`。
7. 日常使用。右上「订阅额度」查看额度。Windows 原生 Gemini 额度在 agy 终端用 `/usage`。Windows 原生实施由 Codex 或 Gemini 承担。项目设置中的「运行设置」控制表决上限、三席的单次超时和共用的 CLI / Auto 工具策略。更新 CLI 后，重新打开型号选择读取新清单。若有调用失败，展开讨论页上的调用问题查看 CLI 回执。
8. 更新或迁移。停掉正在运行的任务，备份本地数据目录，再更新代码。若要迁移讨论，用本机备份与目标机的 `ROUNDTABLE_HOME`。分享安装包时只交付 Git 中的源码，目标机自己设置数据路径和可选的 Claude IP。

网页登录权限只接受本机回环连接。用作个人桌面工具时，保持这一部署方式。

## 验收模型接入

在 Windows 的圆桌目录中运行以下命令。macOS 和 Linux 可用 `python3`。

```powershell
python -X utf8 -B roundtable.py status
python -X utf8 -B roundtable.py model list codex
python -X utf8 -B roundtable.py model list gemini
```

1. **CLI 已找到。** `status` 给出实际可执行文件路径，以及最近一次调用结果。「CLI 就绪，尚未实测」表示可找到本机程序。此命令本身不会发起推理。
2. **型号已列出。** 两条 `model list` 分别读取当前 Codex 和 Antigravity CLI 的型号清单。网页也可以点对应席位打开清单。请从这些型号中选择。Claude 的型号选项为圆桌预设，启用后仍需实测。
3. **账号和选定型号能调用。** 得到用户同意后，在网页选「只问 Codex」或「只问 Gemini」，给每个待验收的席位发一个无敏感内容的短问题。收到有效回复后，再报告该席实测通过。两席通过后可用一个简短议题验收共同讨论。单聊和共同讨论都会产生正常记录并使用模型额度。

「订阅额度」可以单独确认账号额度查询是否可用。Windows 上 Gemini 的额度在 `agy` 终端输入 `/usage` 查看。

离线回归可运行 `python -X utf8 -B -m unittest discover -v`，使用模拟回执。
