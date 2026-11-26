"""Typeset a voted plan using Gemini and print its static HTML to PDF locally."""
import asyncio
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from record_store import discussion_folder
import roundtable as rt


def pdf_path(sid, project):
    return discussion_folder(project, sid) / "方案.pdf"


def chrome():
    candidates = [os.environ.get("ROUNDTABLE_CHROME_BIN"), "google-chrome", "chromium", "chromium-browser",
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    if os.name == "nt":
        for env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if base := os.environ.get(env):
                candidates += [str(Path(base) / name) for name in (
                    "Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe")]
    return next((found for candidate in candidates if candidate and (found := shutil.which(candidate))), None)


def print_source(html):
    # Disallow active content and resource loads in the print document.
    head = re.match(r"\s*(?:<!doctype\s+html\s*>\s*)?<html\b[^>]*>\s*<head\s*>", html, re.I)
    if not head or not re.search(r"</html\s*>\s*$", html, re.I):
        raise ValueError("Gemini 未返回完整 HTML 文稿")
    if re.search(r"<(?:script|iframe|frame|object|embed|base)\b|<meta\b[^>]*http-equiv", html, re.I):
        raise ValueError("图文稿只能包含静态排版内容")
    csp = """<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; form-action 'none'">"""
    return html[:head.end()] + csp + html[head.end():]


async def export_pdf(db, sid, project, evidence=None):
    row = rt.session(db, sid, project)
    if row["state"] not in ("consensus", "returned", "implementing", "inspect"):
        raise ValueError("图文 PDF 需要先取得全席共识")
    writer = db.execute("""SELECT reply FROM calls WHERE session=? AND stage='最终方案撰写'
                           AND agent='gemini' AND ended IS NOT NULL AND error IS NULL ORDER BY id DESC LIMIT 1""", (sid,)).fetchone()
    if not writer:
        raise ValueError("请先完成 Gemini 最终方案撰写")
    pdf = pdf_path(sid, project)
    with (pdf.parent / ".print.lock").open("a+b") as lock:
        try:
            if os.name == "nt":
                import msvcrt
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise ValueError("本轮图文 PDF 正在生成") from exc
        if pdf.is_file():
            return pdf
        exe = chrome()
        if not exe:
            raise ValueError("本机需要 Chrome 或 Chromium，可用 ROUNDTABLE_CHROME_BIN 指定路径")
        with tempfile.TemporaryDirectory(dir=pdf.parent) as tmp:
            lab = Path(tmp)
            layout = pdf.parent / "排版源稿.html.txt"
            if not layout.exists():
                prompt = (
                    "你是本项目最终方案的作者和科学图表编辑。请亲自完成中文图文 PDF 的内容、图形和版式。"
                    "定稿、被表决的原文和现有数值均随请求附上。发布端使用本机 Chrome 直接打印。中文字体可用 Noto Sans CJK SC、PingFang SC、sans-serif 回退。"
                    "忠实保留共识的主次终点、数值、对照、阶段、停止条件、分工与限制。只用提供的真实数据；"
                    "把文献实测、项目预测、拟议阈值清楚标注。用清晰易懂的中文给会审阅方案的读者讲解。"
                    "至少包含与问题相关的数据图（有数值来源时，画坐标、单位、直接标签、误差含义、出处）、"
                    "标明输入输出和连接关系的装置或测量架构示意图、带验收条件的计划时间线。"
                    "如项目没有观测数据，可视化已通过的设计参数并说明性质。给图配一条能解释结论或局限的图注。"
                    "使用内联 SVG 或 CSS 亲自设计图形，字体在 Linux 与 Mac 上可读。图形、图注、文字不得重叠。"
                    "用 4–6 页 A4 纵向排印，封面也承载实质信息；正文至少 11pt，图例至少 9pt。"
                    "按内容分配空间，保留清晰层级。使用 @page 定义 A4 和边距，每个页面段落可在本地浏览器打印。"
                    "输出带 <head>、UTF-8 和内联 CSS 的完整独立静态 HTML，不使用 JavaScript、远程资源、外部字体或图片。"
                    "正式论文引用可使用 https 链接。优先直接回复从 <!doctype html> 到 </html> 的完整源码；"
                    "也可在工作目录中写出 report.html 并返回文件名。请勿用 Bash 输出或转存回复。"
                    "\nGemini 已完成的定稿：\n" + writer["reply"] + "\n全席表决通过的原文：\n" + row["plan"]
                )
                if evidence:
                    prompt += "\n可用于绘图的来源与数据：\n" + Path(evidence).read_text(encoding="utf-8")
                model = json.loads(row["settings"])["models"]["gemini"]
                answer = await rt.call(db, sid, "图文 PDF 排版", "gemini", prompt, model, workspace=lab)
                rt.save_finished_record(db, sid, project)
                if not answer:
                    raise ValueError("Gemini 未完成图文排版，调用记录已保存")
                manuscript = lab / "report.html"
                if manuscript.is_file() and not manuscript.is_symlink():
                    html = manuscript.read_text(encoding="utf-8")
                else:
                    start, end = re.search(r"<(?:!doctype html|html)\b", answer, re.I), re.search(r"</html\s*>", answer, re.I)
                    if not start or not end:
                        raise ValueError("Gemini 未交付可打印的 HTML 文稿")
                    html = answer[start.start():end.end()]
                print_source(html)
                manuscript = lab / "validated.html"
                manuscript.write_text(html, encoding="utf-8")
                manuscript.replace(layout)
            html = print_source(layout.read_text(encoding="utf-8"))
            source = lab / "print.html"
            source.write_text(html, encoding="utf-8")
            out = lab / "out.pdf"
            proc = await asyncio.create_subprocess_exec(exe, "--headless", "--disable-gpu", "--disable-extensions",
                    "--disable-background-networking", "--no-first-run",
                    "--host-resolver-rules=MAP * ~NOTFOUND", "--no-pdf-header-footer",
                    f"--user-data-dir={lab / 'profile'}", f"--print-to-pdf={out}", source.as_uri(),
                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
            try:
                await asyncio.wait_for(proc.wait(), 90)
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()
            if proc.returncode or not out.is_file() or not out.read_bytes().startswith(b"%PDF-"):
                raise ValueError("浏览器未生成 PDF，已保留 Gemini 的排版稿供重新打印")
            out.replace(pdf)
    return pdf
