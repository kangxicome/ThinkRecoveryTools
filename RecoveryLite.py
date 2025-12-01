#!/usr/bin/env python3
"""
ThinkPad Recovery Tool
======================

Interactive command-line UI tool for managing Lenovo Recovery files.
Allows moving .CRI and .IMZ/.7z files between RECOVERY and archives directories.

Author:  Michael Shen
Version: 1.1.0
Date:    2025-11-28
License: MIT

Features:
---------
- Browse RECOVERY and ARCHIVES directories
- Multi-select files with SPACE key (Linux kernel menuconfig style)
- Move files between directories with ENTER key
- Keyword highlighting in descriptions (green)
- Search keyword highlighting in red (Ctrl+F)
- Selected files shown in yellow
- Fixed status bar at bottom

Installation:
-------------
Windows:
    pip install windows-curses

Linux/macOS:
    # curses is built-in, no installation needed

Usage:
------
    python ThinkpadRecoveryTool.py [RECOVERY_DIR]

Examples:
    python ThinkpadRecoveryTool.py E:\\RECOVERY
    python ThinkpadRecoveryTool.py "C:\\OEM\\21CB-Win11PROx64-US-USB\\RECOVERY"
    python ThinkpadRecoveryTool.py /mnt/recovery

Keyboard Controls:
------------------
    TAB        - Switch between RECOVERY and ARCHIVES lists
    SPACE      - Select/deselect current file
    ENTER      - Move selected files to opposite directory
    UP/DOWN    - Navigate through files
    PAGE UP/DN - Fast scroll (10 items)
    Ctrl+F     - Search keyword and highlight in red
    Q          - Quit program

Notes:
------
- Automatically creates 'archives' subdirectory if it doesn't exist
- Moves both .CRI and corresponding payload (.IMZ/.7z) files together when present
- Script-only CRI files are supported (no payload required)
- Highlights keywords like 'Office', 'NVIDIA', 'Intel', etc. in green
"""


import argparse
import curses
import os
import re
import shutil
import sys
from typing import List, Optional, Tuple

# Default keyword list for general highlighting
DEFAULT_KEYWORDS = [
    "Office", "Power2Go", "PowerDVD", "Sunix", "Taisol", "MTK",
    "NVIDIA", "Realtek", "Optane", "Intel Discrete",
    "Lenovo Calliope", "AMD Discrete Graphics", "Intel AMT Driver",
    "AMD Radeon", "Broadcom LAN Driver", "Intel Management",
    "Intel Thunderbolt"
]


class RecoveryItem:
    """Represents a Lenovo Recovery module discovered via a .CRI file."""
    def __init__(self, cri_path: str, imz_path: Optional[str],
                 module_name: str = "", module_this: str = "",
                 description: str = "", image_file: str = "") -> None:
        self.cri_path = cri_path
        self.imz_path = imz_path
        self.module_name = module_name
        self.module_this = module_this
        self.description = description
        self.image_file = image_file  # IMZ/7z filename referenced in CRI (e.g., ImageFile=xxx.imz)
        self.selected = False

    @property
    def basename(self) -> str:
        return os.path.splitext(os.path.basename(self.cri_path))[0]

    def display_text(self) -> str:
        checkbox = "[X]" if self.selected else "[ ]"
        mt = self.module_this or self.module_name or self.basename
        desc = self.description or ""
        # Show payload hint only if present
        suffix = f" (Payload: {os.path.basename(self.imz_path)})" if self.imz_path else ""
        return f"{checkbox} {mt} - {desc}{suffix}"


class RecoveryManager:
    """Handles discovery, parsing, and moving of recovery modules between directories."""
    def __init__(self, recovery_dir: str) -> None:
        self.recovery_dir = os.path.abspath(recovery_dir)
        self.archives_dir = os.path.join(self.recovery_dir, "archives")
        self.errors: List[str] = []
        self._ensure_archives_dir()
        self.recovery_items: List[RecoveryItem] = []
        self.archive_items: List[RecoveryItem] = []

    def _ensure_archives_dir(self) -> None:
        try:
            os.makedirs(self.archives_dir, exist_ok=True)
        except Exception as e:
            self.errors.append(f"Failed to create archives directory: {e}")

    def scan(self) -> None:
        self.recovery_items = self._scan_dir(self.recovery_dir)
        self.archive_items = self._scan_dir(self.archives_dir)

    def _scan_dir(self, d: str) -> List[RecoveryItem]:
        items: List[RecoveryItem] = []
        try:
            for entry in sorted(os.listdir(d)):
                if entry.lower().endswith(".cri"):
                    cri_path = os.path.join(d, entry)
                    module_name, module_this, description, image_file = self._parse_cri(cri_path)

                    # Resolve payload path (IMZ or 7z) using CRI-declared image_file if present
                    payload_path = None
                    if image_file:
                        imz_name = image_file.strip().strip('"').strip("'")
                        candidate = os.path.join(d, imz_name)
                        if os.path.exists(candidate):
                            payload_path = candidate
                        else:
                            # fallback: try common extensions matching the CRI basename
                            base = os.path.splitext(entry)[0]
                            for ext in (".imz", ".7z"):
                                alt = os.path.join(d, base + ext)
                                if os.path.exists(alt):
                                    payload_path = alt
                                    break
                            # No payload found: this can be a script-only CRI; no error
                    else:
                        # no ImageFile declared: try basename with common payload extensions
                        base = os.path.splitext(entry)[0]
                        for ext in (".imz", ".7z"):
                            candidate = os.path.join(d, base + ext)
                            if os.path.exists(candidate):
                                payload_path = candidate
                                break
                        # No payload found: script-only is OK; no error

                    items.append(RecoveryItem(
                        cri_path=cri_path,
                        imz_path=payload_path,
                        module_name=module_name,
                        module_this=module_this,
                        description=description,
                        image_file=image_file
                    ))
        except Exception as e:
            self.errors.append(f"Scan error in {d}: {e}")
        return items

    def _parse_cri(self, path: str) -> Tuple[str, str, str, str]:
        """
        Parse .CRI as simple key=value pairs using regex.
        Returns (ModuleName, ModuleThis, Description, ImageFile). Missing keys -> "".
        """
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except Exception as e:
            self.errors.append(f"Error reading {os.path.basename(path)}: {e}")
            return "", "", "", ""

        # Raw string to avoid invalid escape warnings
        kv_pattern = re.compile(r'^\s*([A-Za-z0-9_]+)\s*=\s*(.*)\s*$', re.MULTILINE)
        data = {}
        for m in kv_pattern.finditer(content):
            key = m.group(1)
            val = m.group(2).strip()
            data[key] = val

        module_name = data.get("ModuleName", "") or ""
        module_this = data.get("ModuleThis", "") or ""
        description = data.get("Description", "") or ""

        # Try typical payload pointer keys (priority order)
        image_file = (
            data.get("ImageFile")
            or data.get("IMZ")
            or data.get("Target")
            or data.get("FileName")
            or data.get("Payload")
            or ""
        )

        return module_name, module_this, description, image_file

    def move_selected(self, from_archives: bool) -> None:
        """
        Move all selected items from one pane to the other.
        Moves the .CRI file and the corresponding payload (IMZ/7z) if present.
        """
        src_items = self.archive_items if from_archives else self.recovery_items
        dst_dir = self.recovery_dir if from_archives else self.archives_dir

        remaining: List[RecoveryItem] = []
        for item in src_items:
            if not item.selected:
                remaining.append(item)
                continue

            try:
                shutil.move(item.cri_path, os.path.join(dst_dir, os.path.basename(item.cri_path)))
            except Exception as e:
                self.errors.append(f"Failed to move CRI {os.path.basename(item.cri_path)}: {e}")
                item.selected = False
                remaining.append(item)
                continue

            # Move payload if present (IMZ or 7z); no alarm if missing (script-only CRI)
            if item.imz_path and os.path.exists(item.imz_path):
                try:
                    shutil.move(item.imz_path, os.path.join(dst_dir, os.path.basename(item.imz_path)))
                except Exception as e:
                    self.errors.append(f"Moved CRI but failed payload {os.path.basename(item.imz_path)}: {e}")

        if from_archives:
            self.archive_items = remaining
        else:
            self.recovery_items = remaining

        self.scan()
        for it in self.recovery_items + self.archive_items:
            it.selected = False


class RecoveryUI:
    """Curses-based UI with two vertical panes and a fixed status bar."""
    def __init__(self, manager: RecoveryManager) -> None:
        self.m = manager
        self.focus_archives = False
        self.cursor_idx_left = 0
        self.cursor_idx_right = 0
        self.scroll_left = 0
        self.scroll_right = 0
        self.search_keyword: str = ""

    def run(self) -> None:
        curses.wrapper(self._main)

    def _init_colors(self) -> None:
        curses.start_color()
        try:
            curses.use_default_colors()
        except Exception:
            pass
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)   # cursor line
        curses.init_pair(2, curses.COLOR_YELLOW, -1)                  # selected
        curses.init_pair(3, curses.COLOR_CYAN, -1)                    # headers
        curses.init_pair(4, curses.COLOR_GREEN, -1)                   # default keywords (green)
        curses.init_pair(5, curses.COLOR_RED, -1)                     # errors
        curses.init_pair(6, curses.COLOR_RED, -1)                     # search keyword (red)
        curses.init_pair(7, curses.COLOR_YELLOW, curses.COLOR_WHITE)  # selected + cursor
        curses.init_pair(8, curses.COLOR_GREEN, curses.COLOR_WHITE)   # default keywords on cursor line

    def _main(self, stdscr) -> None:
        curses.curs_set(0)
        self._init_colors()
        self.m.scan()

        while True:
            stdscr.clear()
            h, w = stdscr.getmaxyx()
            status_h = 4
            content_h = max(0, h - status_h)
            left_w = w // 2
            right_w = w - left_w

            left_win = stdscr.derwin(content_h, left_w, 0, 0)
            right_win = stdscr.derwin(content_h, right_w, 0, left_w)

            self.cursor_idx_left = self._clamp_index(self.cursor_idx_left, len(self.m.recovery_items))
            self.cursor_idx_right = self._clamp_index(self.cursor_idx_right, len(self.m.archive_items))

            self._draw_pane(left_win, "RECOVERY", self.m.recovery_items,
                            focused=not self.focus_archives,
                            cursor_idx=self.cursor_idx_left,
                            scroll=self.scroll_left)

            self._draw_pane(right_win, "archives", self.m.archive_items,
                            focused=self.focus_archives,
                            cursor_idx=self.cursor_idx_right,
                            scroll=self.scroll_right)

            status_win = stdscr.derwin(status_h, w, h - status_h, 0)
            self._draw_status(status_win)

            stdscr.refresh()
            ch = stdscr.getch()

            if ch in (ord('q'), ord('Q')):
                break
            elif ch in (9, getattr(curses, "KEY_TAB", None)):
                self.focus_archives = not self.focus_archives
            elif ch == curses.KEY_UP:
                self._move_cursor(-1, content_h)
            elif ch == curses.KEY_DOWN:
                self._move_cursor(1, content_h)
            elif ch == curses.KEY_PPAGE:
                self._move_cursor(-10, content_h)
            elif ch == curses.KEY_NPAGE:
                self._move_cursor(10, content_h)
            elif ch == ord(' '):
                self._toggle_selection()
            elif ch in (curses.KEY_ENTER, 10, 13):
                self.m.move_selected(from_archives=self.focus_archives)
                self._clamp_cursors()
            elif ch == 6:  # Ctrl+F
                keyword = self._prompt_search(stdscr)
                self.search_keyword = keyword.strip()
            else:
                pass

    def _prompt_search(self, stdscr) -> str:
        h, w = stdscr.getmaxyx()
        prompt = "Search keyword (empty to clear): "
        try:
            stdscr.addnstr(h - 1, 0, prompt, w, curses.A_BOLD)
        except curses.error:
            pass
        curses.echo()
        stdscr.refresh()
        try:
            raw = stdscr.getstr(h - 1, len(prompt), max(1, w - len(prompt) - 1))
            keyword = raw.decode("utf-8", errors="ignore").strip()
        except Exception:
            keyword = ""
        curses.noecho()
        return keyword

    def _clamp_index(self, idx: int, n: int) -> int:
        if n <= 0:
            return 0
        return max(0, min(idx, n - 1))

    def _clamp_cursors(self) -> None:
        self.cursor_idx_left = self._clamp_index(self.cursor_idx_left, len(self.m.recovery_items))
        self.cursor_idx_right = self._clamp_index(self.cursor_idx_right, len(self.m.archive_items))
        self.scroll_left = max(0, min(self.scroll_left, max(0, len(self.m.recovery_items) - 1)))
        self.scroll_right = max(0, min(self.scroll_right, max(0, len(self.m.archive_items) - 1)))

    def _current_list(self) -> Tuple[List[RecoveryItem], int, int]:
        if self.focus_archives:
            return self.m.archive_items, self.cursor_idx_right, self.scroll_right
        else:
            return self.m.recovery_items, self.cursor_idx_left, self.scroll_left

    def _set_current_cursor_scroll(self, cursor_idx: int, scroll: int) -> None:
        if self.focus_archives:
            self.cursor_idx_right = cursor_idx
            self.scroll_right = scroll
        else:
            self.cursor_idx_left = cursor_idx
            self.scroll_left = scroll

    def _move_cursor(self, delta: int, content_h: int) -> None:
        items, cursor_idx, scroll = self._current_list()
        if not items:
            return
        cursor_idx = max(0, min(cursor_idx + delta, len(items) - 1))
        viewport_h = max(1, content_h - 1)
        if cursor_idx < scroll:
            scroll = cursor_idx
        elif cursor_idx >= scroll + viewport_h:
            scroll = cursor_idx - viewport_h + 1
        max_scroll = max(0, len(items) - viewport_h)
        scroll = max(0, min(scroll, max_scroll))
        self._set_current_cursor_scroll(cursor_idx, scroll)

    def _toggle_selection(self) -> None:
        items, cursor_idx, _ = self._current_list()
        if not items:
            return
        if 0 <= cursor_idx < len(items):
            items[cursor_idx].selected = not items[cursor_idx].selected

    def _draw_pane(self, win, title: str, items: List[RecoveryItem],
                   focused: bool, cursor_idx: int, scroll: int) -> None:
        win.erase()
        h, w = win.getmaxyx()
        header = f" {title} "
        header_attr = curses.color_pair(3) | curses.A_BOLD
        try:
            win.addnstr(0, 0, header.ljust(w), w, header_attr)
        except curses.error:
            pass

        viewport_h = max(0, h - 1)
        cursor_idx = self._clamp_index(cursor_idx, len(items))
        max_scroll = max(0, len(items) - viewport_h) if viewport_h > 0 else 0
        scroll = max(0, min(scroll, max_scroll))
        if focused:
            self._set_current_cursor_scroll(cursor_idx, scroll)

        for i in range(viewport_h):
            idx = scroll + i
            if idx >= len(items):
                break
            item = items[idx]
            is_cursor = (focused and idx == cursor_idx)
            if is_cursor and item.selected:
                base_attr = curses.color_pair(7)
            elif is_cursor:
                base_attr = curses.color_pair(1)
            elif item.selected:
                base_attr = curses.color_pair(2)
            else:
                base_attr = curses.A_NORMAL

            row_text = item.display_text()
            prefix, desc = self._split_prefix_desc(row_text)

            # Draw prefix with search highlighting if active
            try:
                self._add_text_with_search(win, i + 1, 0, prefix, base_attr, self.search_keyword, w)
            except curses.error:
                pass

            desc_x = min(len(prefix), max(0, w - 1))

            # Default keyword highlight color (green or green-on-white)
            default_kw_attr = curses.color_pair(8) if is_cursor else curses.color_pair(4)

            # Combine highlights: search keyword (red) and default keywords (green)
            self._add_desc_with_combined_keywords(
                win, i + 1, desc_x, desc, base_attr,
                search_kw=self.search_keyword,
                default_kw_attr=default_kw_attr,
                max_w=w
            )

        win.noutrefresh()

    def _split_prefix_desc(self, row_text: str) -> Tuple[str, str]:
        parts = row_text.split(" - ", 1)
        if len(parts) == 2:
            return parts[0] + " - ", parts[1]
        else:
            return row_text, ""

    def _add_text_with_search(self, win, y: int, x: int, text: str,
                              base_attr: int, search_kw: str, max_w: int) -> None:
        if max_w <= 0 or x >= max_w or not text:
            return
        available = max_w - x
        if available <= 0:
            return

        if not search_kw:
            try:
                win.addnstr(y, x, text, available, base_attr)
            except curses.error:
                pass
            return

        pattern = re.compile(re.escape(search_kw), re.IGNORECASE)
        pos = 0
        for m in pattern.finditer(text):
            start, end = m.span()
            before = text[pos:start]
            if before:
                try:
                    win.addnstr(y, x, before, available, base_attr)
                except curses.error:
                    pass
                x += len(before)
                available -= len(before)
                if available <= 0:
                    return
            kw = text[start:end]
            try:
                win.addnstr(y, x, kw, available, curses.color_pair(6))
            except curses.error:
                pass
            x += len(kw)
            available -= len(kw)
            if available <= 0:
                return
            pos = end
        tail = text[pos:]
        if tail and available > 0:
            try:
                win.addnstr(y, x, tail, available, base_attr)
            except curses.error:
                pass

    def _add_desc_with_combined_keywords(self, win, y: int, x: int, text: str,
                                         base_attr: int, search_kw: str,
                                         default_kw_attr: int, max_w: int) -> None:
        """
        Render description with combined highlights:
        - Search keyword in RED (if present).
        - Default keywords in GREEN (or green-on-white on cursor line).
        """
        if max_w <= 0 or x >= max_w or not text:
            return
        available = max_w - x
        if available <= 0:
            return

        # Build combined pattern: search keyword first (if any), then default keywords
        parts = []
        if search_kw:
            parts.append(re.escape(search_kw))
        if DEFAULT_KEYWORDS:
            parts.extend(re.escape(k) for k in DEFAULT_KEYWORDS)
        if not parts:
            try:
                win.addnstr(y, x, text, available, base_attr)
            except curses.error:
                pass
            return

        pattern = re.compile("(" + "|".join(parts) + ")", re.IGNORECASE)
        pos = 0
        while True:
            m = pattern.search(text, pos)
            if not m:
                break
            start, end = m.span()
            before = text[pos:start]
            if before:
                try:
                    win.addnstr(y, x, before, available, base_attr)
                except curses.error:
                    pass
                x += len(before)
                available -= len(before)
                if available <= 0:
                    return

            kw = text[start:end]
            # If kw matches search_keyword exactly (case-insensitive), color red; else default keyword color
            if search_kw and re.fullmatch(re.escape(search_kw), kw, re.IGNORECASE):
                attr = curses.color_pair(6)
            else:
                attr = default_kw_attr
            try:
                win.addnstr(y, x, kw, available, attr)
            except curses.error:
                pass
            x += len(kw)
            available -= len(kw)
            if available <= 0:
                return
            pos = end

        tail = text[pos:]
        if tail and available > 0:
            try:
                win.addnstr(y, x, tail, available, base_attr)
            except curses.error:
                pass

    def _draw_status(self, win) -> None:
        win.erase()
        h, w = win.getmaxyx()
        focus = "archives" if self.focus_archives else "RECOVERY"
        line1 = f" Lenovo Recovery Manager  |  Focus: {focus} "
        try:
            win.addnstr(0, 0, line1.ljust(w), w, curses.A_BOLD)
        except curses.error:
            pass

        help_text = " TAB: switch  SPACE: select  ENTER: move  ↑/↓: navigate  PgUp/PgDn: fast scroll  Ctrl+F: search  Q: quit "
        try:
            win.addnstr(1, 0, help_text.ljust(w), w, curses.A_DIM)
        except curses.error:
            pass

        search_info = f" | Search: '{self.search_keyword}'" if self.search_keyword else ""
        counts = f" RECOVERY: {len(self.m.recovery_items)}  |  archives: {len(self.m.archive_items)}{search_info} "
        try:
            win.addnstr(2, 0, counts.ljust(w), w, curses.A_NORMAL)
        except curses.error:
            pass

        err_attr = curses.color_pair(5)
        if self.m.errors:
            last_errors = self.m.errors[-2:]
            msg = "  ".join(last_errors)
            try:
                win.addnstr(3, 0, msg[:w], w, err_attr)
            except curses.error:
                pass
        else:
            try:
                win.addnstr(3, 0, " ".ljust(w), w, curses.A_NORMAL)
            except curses.error:
                pass

        win.noutrefresh()


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Curses UI for managing Lenovo Recovery files (.CRI/.IMZ/.7z).")
    p.add_argument("recovery_dir", help="Path to the main RECOVERY directory.")
    return p.parse_args(argv)


def main() -> None:
    args = parse_args(sys.argv[1:])
    recovery_dir = args.recovery_dir

    if not os.path.isdir(recovery_dir):
        print(f"Error: '{recovery_dir}' is not a directory or does not exist.", file=sys.stderr)
        sys.exit(1)

    manager = RecoveryManager(recovery_dir)
    ui = RecoveryUI(manager)
    try:
        ui.run()
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
