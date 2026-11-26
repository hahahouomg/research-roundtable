# 科研圆桌

在浏览器或终端输入一个科研想法或开发任务，Codex 和 Gemini 各自提案、互相评议，并对同一份候选方案分别投票。你可以在讨论后继续追问，也可以指定项目目录，按共识分工实施。Claude 是可选的第三席。

## 开始使用

在 Mac 上双击 **启动圆桌.command**，浏览器会打开本机工作台。Windows 下双击 **start-roundtable.cmd**。也可以在项目目录运行下面的命令。安装步骤见[给安装代理的轻量指南](INSTALL-AGENT.md)。

```sh
python3 roundtable.py
```

在输入框写下问题，点 **开始讨论**。默认由 Codex 和 Gemini 共同参与；输入框左下角可切到单聊。讨论期间保持启动服务的终端开着。刷新页面可以找回当前进度。

| 想做的事 | 在窗口中操作 |
| --- | --- |
| 新建或切换项目 | 在左栏点项目旁边的 **＋**，或直接点项目名 |
| 选择主持人 | 在「共同讨论」旁选择「主持」。默认自动分配，开始后本轮固定。 |
| 更换型号 | 点讨论席上的 **Codex** 或 **Gemini**，可搜索并点选型号。每个 Codex 型号显示 CLI 支持的思考强度，Gemini 显示账号可用的推理档位 |
| 看进度或用量 | 打开讨论的 **逐轮发言** 查看调用记录。右上角 **订阅额度 → 刷新额度** 只读取已启用席位的账号额度，不发送推理提示或创建讨论。面板打开时可复用 60 秒内的结果 |
| 查看或停止进行中的讨论 | 从左栏 **进行中** 打开讨论，点 **停止本轮** 可保留现场并结束调用 |
| 确认 Gemini 工具操作 | 打开当前讨论，核对工作目录、命令或文件变更，点 **仅允许这一次** 或 **拒绝并停止本席**。刷新后仍能处理待确认请求 |
| 选择本机目录 | 新建项目、项目设置和实施窗口均可打开运行圆桌那台电脑的系统文件夹选择器。远程访问时可直接在网页浏览服务器目录；无图形桌面时自动使用网页选择器 |
| 接续讨论 | 点左栏的历史记录，在下方输入框追问 |
| 实施方案 | 全体通过后点 **按分工实施**，核对目录并开始 |

每个项目保存自己的目录、模型选择和历史。界面仅监听本机回环地址，数据与终端版共用。应用需要 Python 3.10+ 和本机已登录的 CLI，无需安装前端依赖。在没有图形桌面的机器上也可以运行 `python3 roundtable.py chat --terminal`。

## Gemini 的自动工具权限

**项目设置 → 运行设置** 的「三席工具策略」可选「跟随 CLI」或「优先 Auto」。新项目默认跟随 CLI。Auto 会使用当前安装支持的自动方式，保留圆桌的工作目录边界。Gemini 通过 `agy acp --sandbox` 获取可用模式，需要许可的操作显示在讨论页。Codex 用适用于非交互执行的工作目录沙箱。Claude 在原生 Auto 可用且工具范围为只读时采用原生模式，使用受限命令启动器时采用允许清单。供应商的模式和可用性会随版本、账号和系统变化。[Antigravity 权限](https://antigravity.google/docs/permissions/) · [Claude 权限模式](https://code.claude.com/docs/en/permission-modes)

**运行设置** 的「单次调用超时」供三席在讨论、定稿、排版、实施和复核时共同使用。默认 20 分钟，也可用 `ROUNDTABLE_TIMEOUT` 设定安装级默认秒数。计时单位是一个席位的一次调用，等待网页授权的时间另计。额度或频率限制、内容安全限制、工具权限、超时和中断采用统一分类。续跑优先复用已完成的发言和有效表决。

## 一场讨论会发生什么

1. **独立提案与实验。** 每席获得同一份用户原话和历史，以及各自可写的临时实验目录。绑定了项目时，复制当前工作文件，包含未提交修改。Git 项目使用已跟踪及未被忽略的文件，跳过符号链接、凭据目录和依赖缓存。各席可搜索资料、执行命令、运行测试，记录来源和复现步骤。Gemini 使用本机 `agy acp --sandbox`。CLI 提供 Auto 时自动选用，否则选择默认模式。需要额外确认时，命令或变更会显示在当前讨论，等候时间不计入调用超时。CLI 的明确禁止仍有效。Claude 的本地启动器在指定工作目录调用 `codex sandbox`。实验目录在本轮结束时清理。
2. **交叉评议。** 参与者阅读所有提案，核验依据，指出实质异议。
3. **形成候选方案。** 默认双席由 Codex 主持，三席由 Claude 主持。开始前可改选任一已启用席位。在 Git 项目和 Windows 上也沿用同一流程。方案列出有顺序的任务，每项指定一位负责人和验收条件。后端、算法优先交给 Codex，前端、交互优先交给 Gemini。小任务可以只派一席。
4. **独立表决。** 全部参与者对同一版方案及分工投赞成票才进入共识。异议交给主持者修订，默认最多两版，可在运行设置选择 1–3 版。表决用完仍有分歧时，可 **带着分歧继续讨论**，或 **结束并请 Gemini 总结**。继续会创建链接到前一场的新讨论。结束会保留原始发言、异议和投票，另外保存可下载的 Markdown 总结。未获全票赞成的方案不会进入实施。
5. **Gemini 撰写最终方案。** 全体通过后，Gemini 根据表决原稿、任务清单和三席的审阅意见（双席时为两席）写成便于阅读的方案。页面可下载定稿，也可展开原表决稿。已通过的原稿与分工用于实施。点击 **请 Gemini 排版 PDF** 可按需生成含图表、装置示意和计划步骤的 PDF。已生成文件可直接下载。命令行可用 `python3 roundtable.py pdf ID --evidence 文献数据.txt`，省略 `--evidence` 时使用讨论定稿。排版使用本机 Chrome、Chromium 或 Windows Edge，文件保存在该轮的记录文件夹。
6. **按分工实施。** 点击实施或运行 `implement` 后，各负责人在选定目录依次工作，并收到前序报告。未完成或无有效回执时停止后续派发。同一数据库中的运行会互斥占用相同或互相包含的实施目录。文件归属和共享接口在计划中约定，负责人共用目录。跨席实施结束后由 Claude 或 Codex 在目标目录只读复核产物和验收证据。Gemini 主持时由 Codex 复核，复核未通过则标记需核对。讨论记录保留已完成部分。旧版已批准且无分工清单的方案仍由 Codex 承接。

**Claude 的网络条件。** 讨论席旁有独立的 Claude 开关，按项目保存，默认关闭。启用时先核验公网 IPv4，通过后才加入。首次开启时填写本机允许的公网 IPv4。关闭时无需联网，当前项目运行中的 Claude 调用会在下一次检查时终止，以后新开的共同讨论使用双席。终端可用 `model claude ip 你的IPv4` 配置本机地址，再用 `model claude on` 或 `model claude off` 控制当前项目。

启动 Claude 或向它查询额度前，圆桌先通过 HTTPS 向 api.ipify.org 核验出口（服务无响应时再查 checkip.amazonaws.com），仅允许当前安装配置的 IPv4。运行中约每五秒复查，采纳回复前再次核验。开始共同讨论前若核验失败，本轮使用双席并记录原因。三席讨论中途若出口改变或无法核实，圆桌终止 Claude 进程，保留已完成的发言和投票。需要 Claude 的阶段会显示未完成，可在恢复指定出口并启用席位后续跑。IP 查询与 Claude 须走同一出口；要覆盖两次抽查之间的时间窗口，可在 VPS 客户端启用断线阻断。

两席首版共 7 次模型调用，三席首版共 10 次；形成共识后，Gemini 执笔另用 1 次。修订一版分别增加 3 或 4 次。单聊只需一次。每个请求都会带入相应 CLI 自身的上下文。用量取自 CLI 回执。Codex 的总数为输入加输出，Gemini 采用自身报告的总数。缓存字段单列，避免重复相加。仪表显示本工具记录的调用量，各方订阅额度可在浏览器右上角查看。「—」表示缺少用量信息。打开第二个终端运行 `status` 或 `show 编号`，可查看进行中的阶段。

<details>
<summary>终端命令与项目管理</summary>

| 交互输入 | 作用 |
| --- | --- |
| 直接输入一段话 | 新开一轮讨论。已有记录时，带上对话背景 |
| `/ask gemini 有没有更便宜的验证方法？` | 只向 Gemini 追问一次。可换成 `codex` |
| `/project` | 查看项目目录和讨论条数，输入编号切换 |
| `/project add 科研想法` | 新建并切换项目。可追加一个目录路径，有空格时用双引号 |
| `/model codex`、`/model gemini` | 从相应 CLI 的型号清单中输入编号选择；输入 0 恢复默认 |
| `/model` | 查看当前项目席位的型号和思考强度 |
| `/run` | 在绑定目录按已批准的分工实施 |
| `/new` | 清空当前对话上下文，开始另一个议题 |
| `/list`、`/open 编号`、`/show` | 找回记录、接着聊、查看每轮原文与用量 |
| `/status`、`/probe` | 查看最近连接记录，或各发一次真实短请求检查当前连接 |
| `/run /绝对路径/项目目录` | 在指定目录按已批准的分工实施。路径可包含空格，交互输入无需引号 |
| `/quit` | 退出 |

## 项目和模型

每个项目保存自己的讨论记录、绑定目录和各席位的型号。再次启动时进入上次选择的项目。已经打开的其他终端继续使用各自当前的项目。切换项目后可用 `/list` 和 `/open 编号` 接上那个项目的讨论。历史版本的讨论归入「默认」，原编号继续可用。

在终端创建项目时可指定现有或新目录。

```sh
python3 roundtable.py project add 文献检索 "$HOME/Documents/Projects/文献检索"
python3 roundtable.py chat
```

只输入 `project add 文献检索` 时，圆桌会在数据目录的 `workspaces/文献检索` 新建工作目录，并打印完整路径。圆桌的讨论数据库仍保存在数据目录。迁移到另一台电脑后，若项目原来绑定了外部绝对路径，可以用 `project path 现有目录` 重新绑定。

| 终端命令（前面加 `python3 roundtable.py`） | 用途 |
| --- | --- |
| `project list`、`project use 文献检索` | 列出项目，或按名称切换 |
| `--project 文献检索 list` | 只在本次命令中查看该项目的历史 |
| `model list codex`、`model list gemini` | 列出对应 CLI 报告的型号 ID |
| `model set codex 型号ID`、`model set gemini 型号ID` | 为当前项目保存指定型号；也可在交互菜单按编号选择 |
| `close ID` | 保留分歧并请 Gemini 写讨论总结 |
| `model set codex default` | 清除项目的 Codex 型号选择，恢复环境变量或 CLI 默认配置 |
| `implement ID` | 在当前项目绑定的目录实施；`--workspace` 可为本次指定其他目录 |

模型偏好按项目保存。可用 `model set codex 型号ID high` 同时设置型号和思考强度，实际选项见 `model list codex`。新讨论在发起时固定参与者、型号和思考强度，实施沿用该次记录。逐轮发言中可核对实际传入的配置。

## 一次性命令与接续

下列 `ID` 均替换为终端打印的记录编号。多行题目或材料也可用标准输入传入，每位参与者会收到提供的内容。

```sh
python3 roundtable.py status --probe
python3 roundtable.py discuss '比较两种实验设计，优先考虑最小可行的验证。'
python3 roundtable.py discuss --rounds 1 - < brief.txt
python3 roundtable.py ask codex '上一次方案里最大的混杂因素是什么？' --after ID
python3 roundtable.py discuss '把预算缩减为一天，请双方重审。' --after ID
python3 roundtable.py list
python3 roundtable.py show ID
python3 roundtable.py implement ID --workspace "/path/to/existing project"
```

每次追问有自己的编号，链接到上一轮。后续提问携带先前议题、候选方案、表决和单聊结果，历史背景上限为最近 16,000 个字符；逐轮原文保存在本地数据库。中断的常规讨论可点 **从中断阶段续跑** 或运行 `python3 roundtable.py resume ID`，沿用同一讨论已完成的阶段和有效选票，恢复时保持原来的参与席位、型号和强度。临时实验副本会从绑定目录重建。命令行讨论的退出码为 0（共识）、2（仍有分歧）或 1（调用失败或未完成）。

</details>

## 移到 Linux

在可以通过 SSH 访问此私有仓库的 Linux 电脑上，使用现有的 Python 3.10+ 环境即可启动。两席讨论使用这台电脑已登录的 `codex` 和 Google Antigravity CLI `agy`。以后在同一目录运行 `git pull --ff-only` 即可更新代码。

```sh
git clone git@github.com:hahahouomg/research-roundtable.git
cd research-roundtable
python3 roundtable.py
```

没有桌面时运行 `python3 roundtable.py chat --terminal`。运行 `python3 roundtable.py status` 可检查本机找到的 CLI 路径，附加 `--probe` 会向两家各发一次请求。Claude 可继续留空。若还没有 `agy`，可按 Google 的说明安装 Linux 版本并登录，然后用 `agy models` 查询账号可用的模型。[Google 安装说明](https://antigravity.google/docs/getting-started?tab=cli) · [登录说明](https://antigravity.google/docs/install)

Git 保存程序、测试和示例。Mac 工作目录里的 `.tools/` 存放本机 CLI，`data/` 存放个人讨论、模型选择及自动创建的工作目录，各自留在本机。要在新克隆中接续 Mac 的历史，可在两端圆桌退出后，将 Mac 的整个 `data/` 私下复制到新克隆根目录，再启动圆桌。已绑定的外部项目需单独迁移文件，并在 **项目设置** 中改为 Linux 路径。

| 可选环境变量 | 用途 |
| --- | --- |
| `ROUNDTABLE_CODEX_BIN`、`ROUNDTABLE_AGY_BIN`、`ROUNDTABLE_CLAUDE_BIN` | 指定 CLI 可执行文件；默认查本机安装及项目内 .tools；Mac 的 Codex 另比较桌面版 CLI |
| `ROUNDTABLE_CODEX_MODEL` | 项目未单独指定型号时使用；缺省由 CLI 选择。程序显式设置沙箱、非交互审批及工具选项，使用 `--ignore-user-config`，沿用本机认证 |
| `ROUNDTABLE_GEMINI_MODEL` | 项目未单独指定型号时使用，缺省为 `gemini-4-neon-medium`。若账号的可用模型不同，填写 `agy models` 输出的 Gemini 型号 |
| `ROUNDTABLE_HOME` | 记录目录，默认是程序旁的 `data/` |
| `ROUNDTABLE_TIMEOUT` | 单次 CLI 等待秒数，默认讨论 300、实施 1200 |

离线测试命令为 `python3 -B -m unittest -v`。测试使用固定回执与模拟调用，不消耗模型额度。

这台 Mac 录下了两场实际讨论。一场评审圆桌自己的界面，另一场讨论文献检索指标并生成可运行的 Python 程序。[圆桌界面评审](examples/圆桌界面评审.md) · [文献检索指标讨论实录](examples/recall/讨论实录.md) · [生成的程序](examples/recall/main.py)

## 订阅额度与记录保存

- 点右上角 **订阅额度** 查看当前项目已启用的席位各自回报的剩余比例或数量、重置时间和查询时间。用 **刷新额度** 可重新查询。Codex 使用本机 app-server 的 `account/rateLimits/read`；Gemini 使用临时状态栏读取 Google 提供的额度桶。已启用的 Claude 通过本地 CLI 的 get_usage 控制请求读取 5 小时和 7 天窗口，沿用出口 IP 检查。额度查询不发送模型消息。达到 10% 会标记低额度，耗尽时显示供应商提供的重置时间。项目 token 统计仍在逐轮发言中。Windows 原生环境的 Gemini 额度通过 agy 的 `/usage` 查看。
- 在 Mac 上，圆桌会比较 PATH 中的 Codex 与 ChatGPT / Codex 桌面版附带的 CLI，优先使用版本较新的一份。模型菜单和执行共用同一可执行文件；`ROUNDTABLE_CODEX_BIN` 仍可显式指定。实际型号以当前账号的清单为准。
- 左栏 **进行中** 可返回任务现场。讨论页显示当前阶段、等待中的席位以及 CLI 已经交付的可见正文；个别 CLI 只在整段生成后交付。点 **停止本轮** 会取消本轮的 CLI 调用。已收文字保留，可继续追问。停止实施时可能已有文件落盘，请核对项目目录。
- 每场讨论在 `data/projects/<项目>/discussions/<编号>/` 有独立文件夹，保存讨论 Markdown、方案及其 PDF。圆桌同时用本机 SQLite 索引查看历史与接续。`ROUNDTABLE_HOME` 可指定整个数据根。升级会把旧讨论和 PDF 归档到对应文件夹。
- 额度弹窗按需调用 CLI，每席成功结果在服务内存缓存 60 秒。Gemini 复用同一个空工作目录（`data/quota-workspace/`），状态栏回执和本次 CLI 主日志放在自动清理的临时目录。讨论、实施和额度查询的 agy 主日志都进入各次调用的临时目录，调用结束即回收。圆桌不保存额度快照历史。供应商 CLI 自己维护的日志、缓存和状态文件有独立的生命周期。
- 终端可用 `python3 roundtable.py quota codex`、`python3 roundtable.py quota gemini`、`python3 roundtable.py quota claude` 和 `python3 roundtable.py stop ID`。

Google 额度字段说明见[官方状态栏文档](https://antigravity.google/docs/cli/statusline)。

可在 Claude 席位的 **型号和思考强度** 中设置 Opus 5.5，或运行 `python3 roundtable.py model set claude claude-opus-5-5 max`。新讨论固定当时的配置。

**文件查看与清理**

| 内容 | 在哪里查看 | 怎样管理 |
| --- | --- | --- |
| 讨论、定稿和实施报告 | 讨论页的「记录文件夹」，或「项目设置 → 项目记录文件夹」 | 结束后，用系统文件管理器移走该轮文件夹。圆桌下一次刷新会清除该轮索引，后续各轮可独立查看，接续链在缺失的那一轮停止。项目工作目录独立保存。要留备份，先复制文件夹到另一个位置。 |
| 实施产物 | 讨论页显示这次实际选择的实施目录 | 用 Finder 或文件管理器核对改动，按文件处理。在 Git 项目可先看 `git status --short` 和 `git diff`。 |
| 讨论实验副本 | 系统临时目录下的 `roundtable-lab-*` | 正常退出自动回收。异常退出留下的目录，可在确认对应任务结束后手工移除。 |
| agy 常规与崩溃日志 | `~/.gemini/antigravity-cli/log/` 和 `~/.gemini/antigravity-cli/crashes/` | macOS Finder 按 ⌘⇧G 输入目录，按日期选择旧的 `cli-*.log` 或 `crash_*.log` 移到废纸篓。 |
| agy 自己的会话与产物 | `~/.gemini/antigravity-cli/conversations/` 和 `brain/` | 可能包含其他项目。清理诊断日志时保留这两个目录。 |
