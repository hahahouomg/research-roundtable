# Research Roundtable

**English** · [简体中文](README.zh-CN.md)

Run a research discussion with Codex and Gemini from a local browser. Give the agents a question and a working folder. They propose independently, compare evidence, and vote on the same plan. Gemini writes the final draft after unanimous approval.

- **Research together.** Agents can read project material, search for sources, and run small experiments in separate working copies. Cross-review gives each agent a distinct focus and records the evidence, open objections, and checks that could resolve them.
- **Keep the reasoning.** View original replies and votes alongside the result. Resume an interrupted round with the same inputs, or start a linked follow-up with updated files. If agreement remains out of reach, close the discussion and ask Gemini to summarize the differences.
- **Review before applying changes.** Approved plans can be implemented in an isolated workspace. Inspect or download the actual Git patch, alongside the agents’ handoffs and verification reports.
- **Work locally.** Switch between English and Simplified Chinese in the header. Keep discussions in separate folders and export plans and transcripts as Markdown. PDF export is optional.

## Quick start

Requires Python 3.10+ and locally installed, signed-in [Codex](https://developers.openai.com/codex/cli/) and [Antigravity CLI](https://antigravity.google/docs/cli/tutorial). Git is required for implementation previews. Roundtable has no Python packages or frontend build step.

```sh
git clone https://github.com/hahahouomg/research-roundtable.git
cd research-roundtable
```

| Platform | Start |
| --- | --- |
| Windows | Open `start-roundtable.cmd` or run `python -X utf8 -B roundtable.py web`. |
| macOS | Open `启动圆桌.command` or run `python3 -B roundtable.py web`. |
| Linux | Run `python3 -B roundtable.py web`. |

Open [the local workspace](http://127.0.0.1:8765/) and start a discussion. To set up another computer, give its coding agent the [installation and verification guide](INSTALL-AGENT.md).

## Where records live

Each discussion has a **Record folder** under `data/projects/<project>/discussions/<id>/`. It contains its Markdown exports and any generated PDF or implementation patch. Move a finished discussion folder out of that directory to remove it from the local history. Your project files live in the separately selected working folder.

Use **Usage** to query the installed CLIs without starting a discussion. Provider availability and returned quota details depend on the CLI, account, and operating system.

## Development

Run the offline checks with `python -X utf8 -B -m unittest discover -v` (use `python3` on macOS or Linux). GitHub Actions also starts the browser server on native Windows.
