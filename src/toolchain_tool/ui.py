"""Curses drawing primitives: theme, box drawing, text fitting and dialogs.

Adapted from the docker-tool project (../tools).
"""

from __future__ import annotations

import curses
import locale
import textwrap
from dataclasses import dataclass
from typing import Callable, Sequence

ELLIPSIS = "..."

KEY_ENTER = (curses.KEY_ENTER, 10, 13)
KEY_ESC = 27
KEY_BACKSPACE = (curses.KEY_BACKSPACE, 127, 8)


# --------------------------------------------------------------------------
# Pure text helpers (unit tested)
# --------------------------------------------------------------------------


def truncate(text: str, width: int) -> str:
    """Shorten text to width, marking the cut with '...'."""
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width <= len(ELLIPSIS):
        return text[:width]
    return text[: width - len(ELLIPSIS)] + ELLIPSIS


def fit(text: str, width: int, align: str = "left") -> str:
    """Truncate and pad text to exactly width characters."""
    text = truncate(text, width)
    return text.rjust(width) if align == "right" else text.ljust(width)


def wrap(text: str, width: int) -> list[str]:
    """Wrap text, keeping explicit newlines as paragraph breaks."""
    width = max(1, width)
    out: list[str] = []
    for para in text.split("\n"):
        out.extend(textwrap.wrap(para, width, break_on_hyphens=False, break_long_words=True) or [""])
    return out


class LineEditor:
    """State for a single-line text field (pure, unit tested)."""

    def __init__(self, text: str = "") -> None:
        self.text = text
        self.pos = len(text)

    def insert(self, ch: str) -> None:
        self.text = self.text[: self.pos] + ch + self.text[self.pos :]
        self.pos += len(ch)

    def backspace(self) -> None:
        if self.pos > 0:
            self.text = self.text[: self.pos - 1] + self.text[self.pos :]
            self.pos -= 1

    def delete(self) -> None:
        self.text = self.text[: self.pos] + self.text[self.pos + 1 :]

    def move(self, delta: int) -> None:
        self.pos = max(0, min(len(self.text), self.pos + delta))

    def home(self) -> None:
        self.pos = 0

    def end(self) -> None:
        self.pos = len(self.text)

    def kill_to_end(self) -> None:
        self.text = self.text[: self.pos]

    def clear(self) -> None:
        self.text, self.pos = "", 0

    def window(self, width: int) -> tuple[str, int]:
        """The visible slice for a field of this width and the cursor column in it."""
        width = max(1, width)
        start = max(0, self.pos - width + 1)
        return self.text[start : start + width], self.pos - start


# --------------------------------------------------------------------------
# Theme
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Glyphs:
    tl: str
    tr: str
    bl: str
    br: str
    h: str
    v: str
    lt: str
    rt: str
    up: str
    down: str
    crumb: str
    bullet: str
    dot: str
    check_on: str
    check_off: str
    radio_on: str
    radio_off: str
    arrow: str
    pointer: str


UNICODE_GLYPHS = Glyphs("╭", "╮", "╰", "╯", "─", "│", "├", "┤", "▲", "▼", " › ", "◆", "●",
                        "[✔]", "[ ]", "◉", "○", "→", "▸")
ASCII_GLYPHS = Glyphs("+", "+", "+", "+", "-", "|", "+", "+", "^", "v", " > ", "*", "o",
                      "[x]", "[ ]", "(*)", "( )", "->", ">")


class Theme:
    def __init__(self) -> None:
        encoding = locale.getpreferredencoding(False).lower().replace("-", "")
        self.glyphs = UNICODE_GLYPHS if encoding == "utf8" else ASCII_GLYPHS
        self._colors = False
        self._next_pair = 1
        bg = -1
        if curses.has_colors():
            try:
                curses.start_color()
                try:
                    curses.use_default_colors()
                except curses.error:
                    bg = curses.COLOR_BLACK
                self._colors = True
            except curses.error:
                pass

        C, B, R = curses, curses.A_BOLD, curses.A_REVERSE
        self.border = self._pair(C.COLOR_CYAN, bg)
        self.title = self._pair(C.COLOR_BLACK, C.COLOR_CYAN, B, fallback=R | B)
        self.header = self._pair(C.COLOR_YELLOW, bg, B, fallback=B | C.A_UNDERLINE)
        self.cursor = self._pair(C.COLOR_BLACK, C.COLOR_CYAN, fallback=R)
        self.mark = self._pair(C.COLOR_MAGENTA, bg, B, fallback=B)
        self.key = self._pair(C.COLOR_CYAN, bg, B, fallback=B)
        self.info = self._pair(C.COLOR_CYAN, bg)
        self.ok = self._pair(C.COLOR_GREEN, bg, B, fallback=B)
        self.warn = self._pair(C.COLOR_YELLOW, bg, B, fallback=B)
        self.error = self._pair(C.COLOR_RED, bg, B, fallback=B | R)
        self.danger_title = self._pair(C.COLOR_WHITE, C.COLOR_RED, B, fallback=R | B)
        self.section = self._pair(C.COLOR_MAGENTA, bg, B, fallback=B | C.A_UNDERLINE)
        self.label = self._pair(C.COLOR_CYAN, bg)
        self.value = self._pair(C.COLOR_GREEN, bg)
        self.changed = self._pair(C.COLOR_YELLOW, bg, B, fallback=B)
        self.input = self._pair(C.COLOR_WHITE, C.COLOR_BLUE, fallback=R)
        self.dim = curses.A_DIM
        self.bold = curses.A_BOLD
        self.normal = curses.A_NORMAL

    def _pair(self, fg: int, bg: int, extra: int = 0, fallback: int = 0) -> int:
        if not self._colors:
            return fallback
        n = self._next_pair
        self._next_pair += 1
        curses.init_pair(n, fg, bg)
        return curses.color_pair(n) | extra

    def level(self, level: str) -> int:
        return {"ok": self.ok, "warn": self.warn, "error": self.error}.get(level, self.info)


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------


def put(win, y: int, x: int, text: str, attr: int = 0) -> None:
    """addstr that clips to the window and never raises."""
    h, w = win.getmaxyx()
    if not (0 <= y < h and 0 <= x < w):
        return
    text = text[: w - x]
    if not text:
        return
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass  # writing the bottom-right cell raises even though it succeeds


def draw_box(win, y: int, x: int, h: int, w: int, attr: int, g: Glyphs) -> None:
    put(win, y, x, g.tl + g.h * (w - 2) + g.tr, attr)
    for row in range(y + 1, y + h - 1):
        put(win, row, x, g.v, attr)
        put(win, row, x + w - 1, g.v, attr)
    put(win, y + h - 1, x, g.bl + g.h * (w - 2) + g.br, attr)


def draw_divider(win, y: int, x: int, w: int, attr: int, g: Glyphs) -> None:
    put(win, y, x, g.lt + g.h * (w - 2) + g.rt, attr)


def draw_help(win, y: int, x: int, width: int, items: Sequence[tuple[str, str]], theme: Theme) -> None:
    pos, end = x, x + width
    for key, desc in items:
        if pos + len(key) + 1 + len(desc) > end:
            break
        put(win, y, pos, key, theme.key)
        put(win, y, pos + len(key) + 1, desc, theme.normal)
        pos += len(key) + len(desc) + 3


def _panel(win, theme: Theme, title: str, dh: int, dw: int, border: int, title_attr: int) -> tuple[int, int]:
    """Clear and frame a centred panel. Returns its top-left corner."""
    h, w = win.getmaxyx()
    y0, x0 = max(0, (h - dh) // 2), max(0, (w - dw) // 2)
    for row in range(dh):
        put(win, y0 + row, x0, " " * dw)
    draw_box(win, y0, x0, dh, dw, border, theme.glyphs)
    put(win, y0, x0 + 2, truncate(f" {title} ", dw - 4), title_attr)
    return y0, x0


def dialog(
    win,
    theme: Theme,
    title: str,
    body: Sequence[str | tuple[str, int]],
    buttons: Sequence[tuple[str, str]],
    focus: int = 0,
    danger: bool = False,
    redraw: Callable[[], None] | None = None,
) -> int | None:
    """Modal dialog. buttons are (label, hotkey) pairs.

    Returns the chosen button index, or None if cancelled with Esc/q.
    """
    border = theme.error if danger else theme.border
    title_attr = theme.danger_title if danger else theme.title
    hotkeys = {ord(k.lower()): i for i, (_, k) in enumerate(buttons)}
    hotkeys.update({ord(k.upper()): i for i, (_, k) in enumerate(buttons)})

    while True:
        if redraw:
            redraw()
        h, w = win.getmaxyx()
        dw = min(max(w - 4, 10), 84)
        text_w = dw - 6
        rows: list[tuple[str, int]] = []
        for item in body:
            text, attr = (item, theme.normal) if isinstance(item, str) else item
            rows.extend((part, attr) for part in wrap(text, text_w))
        rows = rows[: max(1, h - 8)]
        dh = len(rows) + 5  # border, gap, body, gap, buttons, border
        y0, x0 = _panel(win, theme, title, dh, dw, border, title_attr)
        for i, (text, attr) in enumerate(rows):
            put(win, y0 + 2 + i, x0 + 3, text, attr)

        labels = [f"[ {label} ]" for label, _ in buttons]
        total = sum(len(lbl) for lbl in labels) + 3 * (len(labels) - 1)
        bx = x0 + max(1, (dw - total) // 2)
        for i, lbl in enumerate(labels):
            attr = (theme.danger_title if danger else theme.cursor) if i == focus else theme.normal
            put(win, y0 + dh - 2, bx, lbl, attr)
            bx += len(lbl) + 3
        win.refresh()

        key = win.getch()
        if key in (curses.KEY_LEFT, curses.KEY_BTAB, ord("h")):
            focus = (focus - 1) % len(buttons)
        elif key in (curses.KEY_RIGHT, ord("\t"), ord("l")):
            focus = (focus + 1) % len(buttons)
        elif key in KEY_ENTER:
            return focus
        elif key in hotkeys:
            return hotkeys[key]
        elif key in (KEY_ESC, ord("q")):
            return None


def message_box(win, theme: Theme, title: str, body, danger: bool = False, redraw=None) -> None:
    dialog(win, theme, title, body, [("OK", "o")], danger=danger, redraw=redraw)


def confirm(win, theme: Theme, title: str, body, yes: str = "Yes", no: str = "No", redraw=None) -> bool:
    return dialog(win, theme, title, body, [(yes, yes[0]), (no, no[0])], focus=0, redraw=redraw) == 0


@dataclass
class PickItem:
    label: str
    hint: str = ""          # right-aligned, dim
    description: str = ""   # shown under the list for the highlighted item
    disabled: str | None = None  # reason, or None if selectable
    heading: bool = False   # a non-selectable group heading


def pick(
    win,
    theme: Theme,
    title: str,
    items: Sequence[PickItem],
    current: int | None = None,
    intro: str = "",
    redraw: Callable[[], None] | None = None,
) -> int | None:
    """Choose one item from a list (radio buttons). Returns its index or None."""
    g = theme.glyphs
    selectable = [i for i, it in enumerate(items) if not it.heading and it.disabled is None]
    if not selectable:
        return None
    cursor = current if current in selectable else selectable[0]
    top = 0
    while True:
        if redraw:
            redraw()
        h, w = win.getmaxyx()
        dw = min(max(w - 4, 20), 78)
        inner = dw - 4
        intro_rows = wrap(intro, inner) if intro else []
        desc_rows = 3
        list_h = max(3, min(len(items), h - 8 - len(intro_rows) - desc_rows))
        dh = list_h + len(intro_rows) + desc_rows + 4 + (1 if intro_rows else 0)
        y0, x0 = _panel(win, theme, title, dh, dw, theme.border, theme.title)
        y = y0 + 1
        for line in intro_rows:
            put(win, y, x0 + 2, line, theme.dim)
            y += 1
        if intro_rows:
            y += 1

        if cursor < top:
            top = cursor
        elif cursor >= top + list_h:
            top = cursor - list_h + 1
        top = max(0, min(top, max(0, len(items) - list_h)))
        for row in range(list_h):
            idx = top + row
            if idx >= len(items):
                break
            it = items[idx]
            yy = y + row
            if it.heading:
                put(win, yy, x0 + 2, truncate(f"{g.bullet} {it.label}", inner), theme.section)
                continue
            is_cur = idx == cursor
            radio = g.radio_on if idx == current else g.radio_off
            hint = it.disabled if it.disabled else it.hint
            label_w = inner - 3 - (len(hint) + 1 if hint else 0)
            text = f" {radio} " + fit(it.label, max(4, label_w))
            base = theme.cursor if is_cur else (theme.dim if it.disabled else theme.normal)
            put(win, yy, x0 + 2, fit(text + (" " + hint if hint else ""), inner), base)
            if hint and not is_cur:
                put(win, yy, x0 + 2 + inner - len(hint), hint[:inner], theme.dim)
            if idx == current and not is_cur:
                put(win, yy, x0 + 3, radio, theme.ok)
        if top > 0:
            put(win, y, x0 + dw - 1, g.up, theme.warn)
        if top + list_h < len(items):
            put(win, y + list_h - 1, x0 + dw - 1, g.down, theme.warn)

        draw_divider(win, y + list_h, x0, dw, theme.border, g)
        desc = items[cursor].description
        for i, line in enumerate(wrap(desc, inner)[:desc_rows]):
            put(win, y + list_h + 1 + i, x0 + 2, line, theme.info)
        win.refresh()

        key = win.getch()
        pos = selectable.index(cursor)
        if key in (curses.KEY_UP, ord("k")):
            cursor = selectable[max(0, pos - 1)]
        elif key in (curses.KEY_DOWN, ord("j")):
            cursor = selectable[min(len(selectable) - 1, pos + 1)]
        elif key == curses.KEY_PPAGE:
            cursor = selectable[max(0, pos - list_h)]
        elif key == curses.KEY_NPAGE:
            cursor = selectable[min(len(selectable) - 1, pos + list_h)]
        elif key in (curses.KEY_HOME, ord("g")):
            cursor = selectable[0]
        elif key in (curses.KEY_END, ord("G")):
            cursor = selectable[-1]
        elif key in KEY_ENTER or key == ord(" "):
            return cursor
        elif key in (KEY_ESC, ord("q"), curses.KEY_LEFT):
            return None


def prompt_text(
    win,
    theme: Theme,
    title: str,
    value: str = "",
    description: str = "",
    redraw: Callable[[], None] | None = None,
) -> str | None:
    """Edit a single line of text. Returns the new text, or None if cancelled."""
    ed = LineEditor(value)
    try:
        curses.curs_set(1)
    except curses.error:
        pass
    try:
        while True:
            if redraw:
                redraw()
            h, w = win.getmaxyx()
            dw = min(max(w - 4, 20), 84)
            inner = dw - 4
            rows = wrap(description, inner)[: max(0, h - 10)] if description else []
            gap = 1 if rows else 0
            dh = len(rows) + gap + 5  # border, description, gap, field, gap, help, border
            y0, x0 = _panel(win, theme, title, dh, dw, theme.border, theme.title)
            for i, line in enumerate(rows):
                put(win, y0 + 1 + i, x0 + 2, line, theme.dim)
            fy = y0 + 1 + len(rows) + gap
            text, col = ed.window(inner - 1)
            put(win, fy, x0 + 2, fit(text, inner), theme.input)
            draw_help(win, y0 + dh - 2, x0 + 2, inner, [("Enter", "OK"), ("Esc", "Cancel"), ("^U", "Clear")], theme)
            try:
                win.move(fy, x0 + 2 + col)
            except curses.error:
                pass
            win.refresh()

            key = win.get_wch()
            if isinstance(key, str):
                if key in ("\n", "\r"):
                    return ed.text
                if key == "\x1b":
                    return None
                if key in ("\x7f", "\b"):
                    ed.backspace()
                elif key == "\x15":  # ^U
                    ed.clear()
                elif key == "\x0b":  # ^K
                    ed.kill_to_end()
                elif key == "\x01":  # ^A
                    ed.home()
                elif key == "\x05":  # ^E
                    ed.end()
                elif key.isprintable():
                    ed.insert(key)
            elif key == curses.KEY_ENTER:
                return ed.text
            elif key == curses.KEY_BACKSPACE:
                ed.backspace()
            elif key == curses.KEY_DC:
                ed.delete()
            elif key == curses.KEY_LEFT:
                ed.move(-1)
            elif key == curses.KEY_RIGHT:
                ed.move(1)
            elif key == curses.KEY_HOME:
                ed.home()
            elif key == curses.KEY_END:
                ed.end()
    finally:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
