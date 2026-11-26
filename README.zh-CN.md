# 科研圆桌

[English](README.md) · **简体中文**

在本机浏览器里让 Codex 和 Gemini 一起讨论科研问题或开发方案。给它们一个问题和工作目录，各席独立提案、交叉核对证据，再对同一份方案表决。全票赞成后，由 Gemini 执笔定稿。

- **一起查证。** 各席可以阅读项目材料、搜索来源、在独立副本里做小实验。交叉评议有互补的审查重点，记录依据、未解异议及可以改变判断的检查。
- **沿着发言读讨论。** 在「经纬」视图里，每根线代表一位参与者，每一行是一个讨论阶段。点线轴可沿时间读这一席的原话，点表决可查看理由。讨论进行中也能回看早先的阶段，再点「回到现场」跟上最新进展。中断后可用相同输入续跑，文件变了可以开始关联讨论。仍有分歧时，也可以结束本轮，让 Gemini 整理已对齐和未解决的部分。
- **先审改动再应用。** 已通过的方案可在隔离工作区实施。实际 Git 补丁可查看或下载，讨论中保留分工交接和验证报告。
- **在本机工作。** 右上角可切换中文和英文。每场讨论分开存放，可下载 Markdown 方案和记录，也可按需导出 PDF。

## 快速启动

需要 Python 3.10+ 以及已安装并登录的 [Codex CLI](https://developers.openai.com/codex/cli/) 和 [Antigravity CLI](https://antigravity.google/docs/cli/tutorial)。生成实施预览需要 Git。圆桌无需安装 Python 包或构建前端。

```sh
git clone https://github.com/hahahouomg/research-roundtable.git
cd research-roundtable
```

| 平台 | 启动 |
| --- | --- |
| Windows | 双击 `start-roundtable.cmd`，或运行 `python -X utf8 -B roundtable.py web`。 |
| macOS | 双击 `启动圆桌.command`，或运行 `python3 -B roundtable.py web`。 |
| Linux | 运行 `python3 -B roundtable.py web`。 |

打开[本机工作台](http://127.0.0.1:8765/)即可开始讨论。要在另一台电脑上配置，可以把[安装与验收指南](INSTALL-AGENT.zh-CN.md)交给那台电脑上的编程代理。

## 记录在哪里

每场讨论的**记录文件夹**位于 `data/projects/<项目>/discussions/<编号>/`，存放 Markdown 记录及已生成的 PDF 或实施补丁。结束后，把该文件夹移出这个位置即可从本机历史中移除这场讨论。项目文件保存在单独选择的工作目录。

在右上角点**订阅额度**可向已安装的 CLI 查询额度，无需发起讨论。模型可用性和额度详情取决于 CLI、账号及操作系统。

## 开发

离线检查用 `python -X utf8 -B -m unittest discover -v`，macOS 或 Linux 上可用 `python3`。GitHub Actions 还会验证原生 Windows 上能够启动网页服务。
