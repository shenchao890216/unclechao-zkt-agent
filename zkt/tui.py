"""tui.py —— zkt 的 Textual 全屏界面。zkt 直接进入。

布局:中间滚动对话区(Markdown 实时渲染),底部输入行。
agent 循环跑在 worker 线程,流式增量通过 call_from_thread 推回 UI。
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import time
from pathlib import Path

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from agent import box_state, compact_history, run_agent

SESSIONS_DIR = Path.home() / ".zkt" / "sessions"  # 会话是对话,不随盒子走

SLASH_COMMANDS = (
    "help", "exit", "inbox", "graph", "check", "clusters",
    "audit", "drafts", "home", "new", "compact", "resume",
)

HELP = """\
## 命令

| 命令 | 作用 |
|---|---|
| /inbox | 过目待审卡片 |
| /graph | 生成星图并打开 |
| /check | 全盒体检 |
| /clusters | 看卡片簇 |
| /audit | 看审计日志 |
| /drafts | 看文章草稿 |
| /home | 查看/设置盒子路径 |
| /compact | 压缩对话历史 |
| /resume | 恢复上次会话 |
| /exit | 退出(Ctrl+Q 亦可) |

其余任何话都交给 agent 处理。
"""

WELCOME = f"""\
直接说人话,我来操作卡片盒。`/help` 看命令,`Ctrl+Q` 退出。

**盒子现状:** {box_state().replace(chr(10), ' · ')}
"""


# ---------------------------------------------------------------------------
# 会话存档
# ---------------------------------------------------------------------------

def _save_session(history: list[dict]) -> Path | None:
    if not history:
        return None
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    with path.open("w", encoding="utf-8") as f:
        for msg in history:
            f.write(json.dumps(msg, ensure_ascii=False) + "\n")
    return path


def _list_sessions() -> list[Path]:
    if not SESSIONS_DIR.exists():
        return []
    return sorted(SESSIONS_DIR.glob("*.jsonl"), reverse=True)


def _load_session(path: Path) -> list[dict]:
    msgs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            msgs.append(json.loads(line))
    return msgs


# ---------------------------------------------------------------------------
# 签字弹窗
# ---------------------------------------------------------------------------

class ConfirmScreen(ModalScreen[bool]):
    """agent 提议转正/删除时的签字弹窗。y 键签字,n/Esc 拒绝。"""

    AUTO_FOCUS = None  # 不聚焦任何控件,避免光标闪现

    BINDINGS = [
        ("y", "confirm", "签字"),
        ("n", "reject", "拒绝"),
        ("escape", "reject", "拒绝"),
    ]

    def __init__(self, action: str, detail: dict) -> None:
        super().__init__()
        self.action = action
        self.detail = detail

    def compose(self) -> ComposeResult:
        verb = "转正" if self.action == "promote" else "删除"
        lines = [
            f"# ✋ 请求签字:{verb}",
            f"**{self.detail['id']}** {self.detail['title']}",
        ]
        if self.action == "promote":
            lines.append(f"> {self.detail['body'][:200]}…")
        if self.detail.get("backlinks"):
            lines.append(f"⚠ 有 {len(self.detail['backlinks'])} 张卡链到它,删除后会成死链")
        lines.append(f"**理由:** {self.detail['reason']}")
        lines.append("---")
        lines.append("**y** 签字 · **n** 拒绝")
        md = Markdown("\n\n".join(lines), classes="confirm-box")
        md.can_focus = False
        yield md

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_reject(self) -> None:
        self.dismiss(False)


class CommandInput(Input):
    """输入框:候选列表可见时,方向键/回车先交给列表,而不是自己消费。"""

    def _on_key(self, event: events.Key) -> None:
        handler = getattr(self.app, "on_command_key", None)
        if handler and handler(event):
            event.stop()
            event.prevent_default()


# ---------------------------------------------------------------------------
# 主应用
# ---------------------------------------------------------------------------

class ZktApp(App):
    BINDINGS = [("ctrl+q", "quit", "退出")]

    CSS = """
    #chat { height: 1fr; padding: 1 2; }
    #chat > * { margin-bottom: 1; }
    Markdown { background: transparent; }
    .user-msg { color: $text-muted; }
    .tool-line { color: $accent; text-style: italic; background: $surface; }
    .err { color: $error; background: $surface; }
    .sys-hint { color: $success; }
    Input {
        dock: bottom;
        background: $surface;
        border: round $primary;
        margin: 0 2 2 2;
    }
    #suggest {
        dock: bottom;
        display: none;
        height: auto;
        max-height: 10;
        margin: 0 2 0 2;
        background: $surface;
        border: round $primary;
    }
    #confirm-wrap { align: center middle; height: 1fr; }
    ConfirmScreen { align: center middle; }
    .confirm-box {
        background: $surface; border: round $accent;
        padding: 1 2; width: 70;
    }
    """

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="chat")
        yield OptionList(id="suggest")
        yield CommandInput(placeholder="说点什么,/ 开头是命令")

    def on_mount(self) -> None:
        self.history: list[dict] = []
        self._stream_md: Markdown | None = None
        self._stream_buf = ""
        self._add_markdown(WELCOME, "sys-hint")
        if sessions := _list_sessions():
            self._add_static(f"(检测到 {len(sessions)} 份历史会话,/resume 恢复最近一次)")
        self.query_one(CommandInput).focus()

    # ---- 命令补全 ------------------------------------------------------

    def on_input_changed(self, event: Input.Changed) -> None:
        value = event.value
        suggest = self.query_one("#suggest", OptionList)
        if value.startswith("/") and " " not in value:
            prefix = value[1:].lower()
            matches = [c for c in SLASH_COMMANDS if c.startswith(prefix)]
            suggest.clear_options()
            for cmd in matches:
                suggest.add_option(Option(f"/{cmd}", id=cmd))
            suggest.display = bool(matches)
            if matches:
                suggest.highlighted = 0
        else:
            suggest.display = False

    def on_command_key(self, event: events.Key) -> bool:
        """候选列表可见时接管方向键/回车/Esc。返回 True 表示已消费。"""
        suggest = self.query_one("#suggest", OptionList)
        if not suggest.display:
            return False
        if event.key == "down":
            suggest.action_cursor_down()
        elif event.key == "up":
            suggest.action_cursor_up()
        elif event.key == "escape":
            self._hide_suggest()
        elif event.key == "enter":
            if (idx := suggest.highlighted) is not None:
                self._pick_command(idx)
        else:
            return False
        return True

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option.id:
            self._pick_command_by_id(event.option.id)

    def _pick_command(self, index: int) -> None:
        suggest = self.query_one("#suggest", OptionList)
        if (opt := suggest.get_option_at_index(index)) and opt.id:
            self._pick_command_by_id(opt.id)

    def _pick_command_by_id(self, cmd: str) -> None:
        inp = self.query_one(CommandInput)
        inp.value = f"/{cmd} "
        self._hide_suggest()
        inp.focus()
        inp.cursor_position = len(inp.value)

    def _hide_suggest(self) -> None:
        self.query_one("#suggest", OptionList).display = False
        self.query_one(CommandInput).focus()

    def on_click(self) -> None:
        # 点别处时收起候选
        if self.query_one("#suggest", OptionList).display:
            self._hide_suggest()

    # ---- 渲染工具 -----------------------------------------------------

    def _add_markdown(self, text: str, cls: str = "") -> Markdown:
        md = Markdown(text, classes=cls)
        self.query_one("#chat").mount(md)
        self.query_one("#chat").scroll_end(animate=False)
        return md

    def _add_static(self, text: str, cls: str = "tool-line") -> None:
        self.query_one("#chat").mount(Static(text, classes=cls))
        self.query_one("#chat").scroll_end(animate=False)

    # ---- 输入分发 -----------------------------------------------------

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        if text.startswith("/"):
            self._slash(text[1:].split())
        else:
            self._add_markdown(f"**你:** {text}", "user-msg")
            self._ask(text)

    def _slash(self, parts: list[str]) -> None:
        cmd = parts[0]
        if cmd in ("exit", "quit"):
            self.action_quit()
        elif cmd == "help":
            self._add_markdown(HELP)
        elif cmd == "compact":
            self._do_compact()
        elif cmd == "resume":
            self._do_resume(parts[1:])
        else:
            self._run_local(parts)

    def _run_local(self, parts: list[str]) -> None:
        """本地命令:捕获 stdout 渲染成代码块进对话区,不弄花 TUI。"""
        import cli

        buf = io.StringIO()
        old_argv = sys.argv
        sys.argv = ["zkt", *parts]
        try:
            with contextlib.redirect_stdout(buf):
                cli.main()
        except SystemExit:
            pass
        except Exception as e:
            self._add_markdown(f"**出错:** {e}", "err")
            return
        finally:
            sys.argv = old_argv
        out = buf.getvalue().strip() or "(无输出)"
        self._add_markdown(f"```\n{out}\n```")

    @work(thread=True)
    def _do_compact(self) -> None:
        before = len(self.history)
        compacted = compact_history(self.history)
        self.call_from_thread(self._apply_compact, compacted, before)

    def _apply_compact(self, compacted: list, before: int) -> None:
        self.history[:] = compacted
        self._add_static(f"已压缩: {before} 条消息 → {len(compacted)} 条(旧消息变摘要)", "sys-hint")

    def _do_resume(self, args: list[str]) -> None:
        sessions = _list_sessions()
        if not sessions:
            self._add_static("没有历史会话")
            return
        idx = int(args[0]) - 1 if args and args[0].isdigit() else 0
        if not 0 <= idx < len(sessions):
            self._add_static(f"序号超范围: 1~{len(sessions)}", "err")
            return
        self.history[:] = _load_session(sessions[idx])
        self._add_static(f"已恢复: {sessions[idx].name}(共 {len(self.history)} 条消息)", "sys-hint")
        for msg in self.history[-2:]:
            content = str(msg.get("content", ""))[:300]
            self._add_markdown(f"> [{msg['role']}] {content}")

    # ---- agent 对话 ---------------------------------------------------

    @work(thread=True)
    def _ask(self, text: str) -> None:
        def on_delta(chunk: str) -> None:
            self.call_from_thread(self._feed_stream, chunk)

        def on_event(evt: dict) -> None:
            if evt["type"] == "tool":
                args = json.dumps(evt["args"], ensure_ascii=False)
                self.call_from_thread(self._add_static, f"⚙ {evt['name']}({args[:100]})")
            elif evt["type"] == "tool_error":
                self.call_from_thread(self._add_static, f"⚠ {evt['name']}: {evt['error']}", "err")
            elif evt["type"] == "turn" and evt["n"] > 1:
                # 新一轮开始:关闭上一轮的流式块,让接下来的文字排在工具行之后
                self.call_from_thread(self._feed_done)

        try:
            run_agent(text, history=self.history, on_delta=on_delta, on_event=on_event)
        except Exception as e:  # noqa: BLE001 —— 任何异常都进对话区,不崩 TUI
            self.call_from_thread(self._add_markdown, f"**出错:** {type(e).__name__}: {e}", "err")
        finally:
            self.call_from_thread(self._feed_done)

    def _feed_stream(self, chunk: str) -> None:
        if self._stream_md is None:
            self._stream_buf = "**zkt:** "
            self._stream_md = self._add_markdown(self._stream_buf)
            self._stream_md.zkt_seq = self._msg_seq = getattr(self, "_msg_seq", 0) + 1
        self._stream_buf += chunk
        self._stream_md.update(self._stream_buf)
        self.query_one("#chat").scroll_end(animate=False)

    def _feed_done(self) -> None:
        self._stream_md = None
        self._stream_buf = ""

    # ---- 签字钩子 -----------------------------------------------------

    def _confirm_via_modal(self, action: str, detail: dict) -> bool:
        """worker 线程里发起弹窗,阻塞等人在主线程按 y/n。"""
        done = threading.Event()
        result: dict = {}

        def ask() -> None:
            self.push_screen(
                ConfirmScreen(action, detail),
                lambda approved: (result.update(v=approved), done.set()),
            )

        self.call_from_thread(ask)
        done.wait()
        return bool(result.get("v"))

    def action_quit(self) -> None:
        saved = _save_session(self.history)
        if saved:
            self.notify(f"会话已存档: {saved.name}")
        self.exit()


def main() -> int:
    import agent

    app = ZktApp()
    agent.CONFIRM_HOOK = app._confirm_via_modal  # 签字权接线:提议必须过弹窗
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
