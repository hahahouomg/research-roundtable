# 让安装代理配置科研圆桌

把本文件交给安装代理，并让它在目标电脑的仓库副本里逐项检查。圆桌在本机浏览器运行，用本机登录的 Codex 和 Antigravity CLI。Claude 与 PDF 都是可选项。

1. 查询操作系统、Python、Git 和现有环境。复用 Python 3.10 或更新版本及现有环境。需要创建环境时用 Miniforge/Mamba。圆桌本身无需 Python 包或前端构建。Windows 使用同一个环境里的 Python 和供应商 CLI。
2. 找到 `codex` 和 `agy`，并运行各自的 `--version`。若缺少，按本机系统从官方渠道安装。[Codex CLI](https://developers.openai.com/codex/cli/) · [Antigravity CLI](https://antigravity.google/docs/cli/tutorial)
3. 在本电脑终端分别运行 `codex` 和 `agy`，请用户完成登录或设备确认。Windows 重新打开终端以刷新 PATH。需指定二进制时设置 `ROUNDTABLE_CODEX_BIN` 和 `ROUNDTABLE_AGY_BIN`。
4. 只有用户要求加第三席时才安装并登录 Claude Code。让用户在网页打开 Claude 开关并填写这台安装机允许的公网 IPv4，或者运行 `python roundtable.py model claude ip <IPv4>`，再运行 `python roundtable.py model claude on`。配置存于部署机的 `ROUNDTABLE_HOME/claude-ip`（默认 `data/claude-ip`），由安装机用户管理。[Claude Code 安装指南](https://code.claude.com/docs/en/setup)
5. 启动圆桌。在 Windows 双击 `start-roundtable.cmd` 或进入项目目录运行下面的第一条命令。在 macOS 双击 `启动圆桌.command`，在 Linux 或 macOS 终端用第二条。启动时打印本机入口，默认 `http://127.0.0.1:8765/`。终端保持打开。

   ```text
   python -X utf8 -B roundtable.py web
   python3 -B roundtable.py web
   ```

6. 验收。本机网页能建项目、浏览文件夹和选择主持人。离线检查运行 `python -X utf8 -B -m unittest -v`。需要验证真实模型时，用一个无敏感内容的短议题跑完整流程，再检查交叉评议、投票和 Gemini 定稿。PDF 需要 Chrome、Chromium 或 Windows 上的 Edge，也可指定 `ROUNDTABLE_CHROME_BIN`。
7. 日常使用。右上「订阅额度」查看额度。Windows 原生 Gemini 额度在 agy 终端用 `/usage`。Windows 原生实施由 Codex 或 Gemini 承担。项目设置中的「工具与运行」控制 Auto 和单次超时，具体可用模式由当前 CLI 与账号决定。更新 CLI 后，重新打开型号选择读取新清单。若有调用失败，检查逐轮发言里的实际 CLI 回执。
8. 更新或迁移。停掉正在运行的任务，备份本地数据目录，再更新代码。若要迁移讨论，用本机备份与目标机的 `ROUNDTABLE_HOME`。分享安装包时只交付 Git 中的源码，目标机自己设置数据路径和可选的 Claude IP。

网页登录权限只接受本机回环连接。用作个人桌面工具时，保持这一部署方式。
