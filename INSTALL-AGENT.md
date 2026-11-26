# Install and verify Research Roundtable

**English** · [简体中文](INSTALL-AGENT.zh-CN.md) · [Project overview](README.md)

Give this file to the coding agent on the computer where Roundtable will run.

1. Clone the repo or extract the GitHub source ZIP. Reuse an existing Python 3.10+ environment. If you need a new environment, use Miniforge/Mamba. Install Git if you want implementation previews. There is no frontend build or Python package installation.
2. Check `codex --version` and `agy --version`. Install missing CLIs from the [Codex CLI](https://developers.openai.com/codex/cli/) and [Antigravity CLI](https://antigravity.google/docs/cli/tutorial) official guides. Have the user sign in on the target computer. On Windows, reopen the terminal if PATH just changed. Use `ROUNDTABLE_CODEX_BIN` or `ROUNDTABLE_AGY_BIN` only when an explicit executable path is needed.
3. On Windows open `start-roundtable.cmd` or run `python -X utf8 -B roundtable.py web`. On macOS open `启动圆桌.command`. From a macOS or Linux terminal, run `python3 -B roundtable.py web`. Keep the process running and open [Roundtable](http://127.0.0.1:8765/).
4. Confirm the page loads, the language switch works, and the user can select an existing project folder. PDF export is optional and uses local Chrome, Chromium, or Microsoft Edge to print a document prepared by Gemini.
5. For an update, finish active work, back up the local data directory, and update the code. The default data directory is `data/`. An installation can set `ROUNDTABLE_HOME` to a different location. Share source code and migrate personal data separately.

## Verify agent access

In the repository on Windows, run the commands below. Use `python3` in a macOS or Linux terminal.

```powershell
python -X utf8 -B roundtable.py status
python -X utf8 -B roundtable.py model list codex
python -X utf8 -B roundtable.py model list gemini
```

- **CLI found.** `status` shows the executable and its last recorded call, when available.
- **Models listed.** The two `model list` commands report what the installed CLIs offer. Open a participant’s model picker to select one.
- **Real call verified.** With the user’s go-ahead, send a short, non-sensitive question using **Ask Codex** and **Ask Gemini**. Report which selected models answered. These calls use account quota and make normal discussion records.
- **Quota read verified.** **Usage** queries account limits without starting a discussion. On native Windows, check Gemini usage with `/usage` in the agy terminal.

Run the offline checks with `python -X utf8 -B -m unittest discover -v`.
