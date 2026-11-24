# 科研圆桌

在浏览器或终端输入一个科研想法或开发任务，Codex 和 Gemini 各自提案、互相评议，并对同一份候选方案分别投票。你可以在讨论后继续追问，也可以指定项目目录，让 Codex 实施。Claude 席位预留。

## 开始使用

在 Mac 上双击 **启动圆桌.command**，浏览器会打开本机工作台。也可以在项目目录运行：

```sh
python3 roundtable.py
```

在输入框写下问题，点 **开始讨论**。默认由 Codex 和 Gemini 共同参与；输入框左下角可切到单聊。讨论期间保持启动服务的终端开着。刷新页面可以找回当前进度。

| 想做的事 | 在窗口中操作 |
| --- | --- |
| 新建或切换项目 | 在左栏点项目旁边的 **＋**，或直接点项目名 |
| 更换型号 | 点讨论席上的 **Codex** 或 **Gemini**，可搜索并点选型号。Gemini 的推理档位排列在同一行 |
| 看进度或用量 | 打开讨论的 **逐轮发言**，或点右上角 **订阅额度** |
| 查看或停止进行中的讨论 | 从左栏 **进行中** 打开讨论，点 **停止本轮** 可保留现场并结束调用 |
| 移除和恢复项目 | 在 **项目设置** 里点 **移除项目**，可在左栏 **回收站** 恢复 |
| 接续讨论 | 点左栏的历史记录，在下方输入框追问 |
| 实施方案 | 双方通过后点 **交给 Codex 实施**，核对目录并开始 |

每个项目保存自己的目录、模型选择和历史。界面仅监听本机回环地址，数据与终端版共用。应用需要 Python 3.9+ 和本机已登录的 CLI，无需安装前端依赖。在没有图形桌面的机器上也可以运行 `python3 roundtable.py chat --terminal`。

## 一场讨论会发生什么

1. **独立提案。** 两个 CLI 同时收到同样的用户原话和必要的历史背景。双方此时都看不到对方本轮的草稿。
2. **交叉评议。** 双方看到两份提案，各自指出值得保留的想法、漏洞和可区分两种观点的检验。终端显示发言全文。
3. **形成候选方案。** Codex 综合提案与评议。科研任务会要求写清待验证的假设、可以否定它的结果、最小实验和验收条件。讨论阶段使用临时空目录，适合对所给材料做推理。需要查文献或读项目代码时，可以将该项列入下一阶段并指定材料。
4. **独立表决。** 两方都对同一个版本投赞成票并给出理由，才记录为共识。有异议则交回明确修订。默认最多两版，之后保留异议供你判断。两人同意先做一个实验，只表示认可实验方案，科研结论仍须用实验数据验证。
5. **执行。** 明确运行 `implement` 或 `/run` 后，Codex 才取得指定目录的 workspace-write 沙箱。它收到用户要求和已投票的方案，并被要求实际验收、列出遗留工作。状态「执行已返回」表示收到了执行者的报告；测试结果和完成范围见报告。每份方案只派发一次。中途失败可能已留下文件，可检查目标目录后，带着实际进度接续讨论。

一版双人共识通常涉及 7 次 CLI 请求；每修订一版，增加 3 次。单聊只需一次。每个请求都会带入相应 CLI 自身的上下文。用量取自 CLI 回执。Codex 的总数为输入加输出，Gemini 采用自身报告的总数。缓存字段单列，避免重复相加。仪表显示本工具记录的调用量，各方订阅额度可在浏览器右上角查看。「—」表示缺少用量信息。打开第二个终端运行 `status` 或 `show 编号`，可查看进行中的阶段。

<details>
<summary>终端命令与项目管理</summary>

| 交互输入 | 作用 |
| --- | --- |
| 直接输入一段话 | 新开一轮双模型讨论。已有记录时，带上对话背景 |
| `/ask gemini 有没有更便宜的验证方法？` | 只向 Gemini 追问一次。可换成 `codex` |
| `/project` | 查看项目目录和讨论条数，输入编号切换 |
| `/project add 科研想法` | 新建并切换项目。可追加一个目录路径，有空格时用双引号 |
| `/model codex`、`/model gemini` | 从相应 CLI 的型号清单中输入编号选择；输入 0 恢复默认 |
| `/model` | 查看当前项目两个席位的型号 |
| `/run` | 把当前批准的方案交给 Codex，在绑定的项目目录实施 |
| `/new` | 清空当前对话上下文，开始另一个议题 |
| `/list`、`/open 编号`、`/show` | 找回记录、接着聊、查看每轮原文与用量 |
| `/status`、`/probe` | 查看最近连接记录，或各发一次真实短请求检查当前连接 |
| `/run /绝对路径/项目目录` | 将当前已达成共识的方案交给 Codex，在该目录实施。路径可包含空格，交互输入无需引号 |
| `/quit` | 退出 |

## 项目和模型

每个项目保存自己的讨论记录、绑定目录和两个席位的型号。再次启动时进入上次选择的项目。已经打开的其他终端继续使用各自当前的项目。切换项目后可用 `/list` 和 `/open 编号` 接上那个项目的讨论。历史版本的讨论归入「默认」，原编号继续可用。

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
| `model set codex default` | 清除项目的 Codex 型号选择，恢复环境变量或 CLI 默认配置 |
| `implement ID` | 在当前项目绑定的目录实施；`--workspace` 可为本次指定其他目录 |

模型偏好按项目保存。一次讨论开始时固定双方的型号，下一次讨论或执行采用届时选择的型号。`show` 会显示各次调用指定的型号；早期记录标注为「型号未记录」。Claude 席位继续预留。讨论使用临时空目录，仅实施阶段会写入项目的工作目录。

## 一次性命令与接续

下列 `ID` 均替换为终端打印的记录编号。多行题目或材料也可用标准输入传入，两位参与者会收到提供的内容。

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

每次追问有自己的编号，链接到上一轮。后续提问携带先前议题、候选方案、表决和单聊结果，历史背景上限为最近 16,000 个字符；逐轮原文保存在本地数据库。命令行讨论的退出码为 0（共识）、2（仍有分歧）或 1（调用失败或未完成）。

</details>

## 移到 Linux

在可以通过 SSH 访问此私有仓库的 Linux 电脑上，使用现有的 Python 3.9+ 环境即可启动。两席讨论使用这台电脑已登录的 `codex` 和 Google Antigravity CLI `agy`。以后在同一目录运行 `git pull --ff-only` 即可更新代码。

```sh
git clone git@github.com:hahahouomg/research-roundtable.git
cd research-roundtable
python3 roundtable.py
```

没有桌面时运行 `python3 roundtable.py chat --terminal`。运行 `python3 roundtable.py status` 可检查本机找到的 CLI 路径，附加 `--probe` 会向两家各发一次请求。Claude 可继续留空。若还没有 `agy`，可按 Google 的说明安装 Linux 版本并登录，然后用 `agy models` 查询账号可用的模型。[Google 安装说明](https://antigravity.google/docs/getting-started?tab=cli) · [登录说明](https://antigravity.google/docs/install)

Git 保存程序、测试和示例。Mac 工作目录里的 `.tools/` 存放本机 CLI，`data/` 存放个人讨论、模型选择及自动创建的工作目录，各自留在本机。要在新克隆中接续 Mac 的历史，可在两端圆桌退出后，将 Mac 的整个 `data/` 私下复制到新克隆根目录，再启动圆桌。已绑定的外部项目需单独迁移文件，并在 **项目设置** 中改为 Linux 路径。

| 可选环境变量 | 用途 |
| --- | --- |
| `ROUNDTABLE_CODEX_BIN`、`ROUNDTABLE_AGY_BIN` | 指定 CLI 可执行文件；默认查本机安装及项目内 .tools；Mac 的 Codex 另比较桌面版 CLI |
| `ROUNDTABLE_CODEX_MODEL` | 项目未单独指定型号时使用；缺省由 CLI 选择。程序显式设置沙箱、非交互审批及工具选项，使用 `--ignore-user-config`，沿用本机认证 |
| `ROUNDTABLE_GEMINI_MODEL` | 项目未单独指定型号时使用，缺省为 `gemini-4-neon-medium`。若账号的可用模型不同，填写 `agy models` 输出的 Gemini 型号 |
| `ROUNDTABLE_HOME` | 记录目录，默认是程序旁的 `data/` |
| `ROUNDTABLE_TIMEOUT` | 单次 CLI 等待秒数，默认讨论 300、实施 1200 |

离线测试命令为 `python3 -B -m unittest -v`。测试使用固定回执与模拟调用，不消耗模型额度。

这台 Mac 录下了两场实际讨论。一场评审圆桌自己的界面，另一场讨论文献检索指标并生成可运行的 Python 程序。[圆桌界面评审](examples/圆桌界面评审.md) · [文献检索指标讨论实录](examples/recall/讨论实录.md) · [生成的程序](examples/recall/main.py)

## 订阅额度、讨论实况和回收站

- 点右上角 **订阅额度** 查看两个账号各自回报的剩余比例或数量、重置时间和查询时间。用 **刷新额度** 可重新查询。Codex 使用本机 app-server 的 `account/rateLimits/read`；Gemini 使用临时状态栏读取 Google 提供的额度桶。查询不发送模型消息。项目 token 统计仍在逐轮发言中。
- 在 Mac 上，圆桌会比较 PATH 中的 Codex 与 ChatGPT / Codex 桌面版附带的 CLI，优先使用版本较新的一份。模型菜单和执行共用同一可执行文件；`ROUNDTABLE_CODEX_BIN` 仍可显式指定。实际型号以当前账号的清单为准。
- 左栏 **进行中** 可返回任务现场。讨论页显示当前阶段、等待中的席位以及 CLI 已经交付的可见正文；个别 CLI 只在整段生成后交付。点 **停止本轮** 会取消本轮的 CLI 调用。已收文字保留，可继续追问。停止实施时可能已有文件落盘，请核对项目目录。
- **项目设置 → 移除项目** 或讨论页 **移除讨论** 会移入回收站。在左栏 **回收站** 中可恢复。移除讨论会同时收起它的后续追问，绑定目录和文件继续保留。默认项目作为常驻入口，其讨论可以单独移除。正在运行的任务应先停止或完成。
- 终端可用 `python3 roundtable.py quota codex`、`python3 roundtable.py quota gemini` 和 `python3 roundtable.py stop ID`。

Google 额度字段说明见[官方状态栏文档](https://antigravity.google/docs/cli/statusline)。
