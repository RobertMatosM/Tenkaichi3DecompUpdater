#!/usr/bin/env python3
"""Cross-platform graphical interface for Tenkaichi3DecompUpdater."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from common import (
    APP_DATA_DIR,
    LabeledProgressCallback,
    read_install_paths,
    read_installed_version,
)
from install import install
from remove import remove_registered_install
from update import update_installations


class UpdaterWindow:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Tenkaichi3Decomp Updater")
        self.root.minsize(700, 500)
        self.events: queue.Queue[tuple] = queue.Queue()
        self.running = False
        self.operation_failed = False

        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._build_widgets()
        self.refresh_installations()
        self.root.after(100, self._poll_events)

    def _build_widgets(self) -> None:
        container = ttk.Frame(self.root, padding=12)
        container.pack(fill=tk.BOTH, expand=True)

        actions = ttk.Frame(container)
        actions.pack(fill=tk.X, pady=(0, 10))
        self.install_button = ttk.Button(
            actions, text="Install", command=self._install
        )
        self.install_button.pack(side=tk.LEFT, padx=(0, 6))
        self.update_button = ttk.Button(
            actions, text="Update all", command=self._update
        )
        self.update_button.pack(side=tk.LEFT, padx=6)
        self.check_button = ttk.Button(
            actions, text="Check updates", command=self._check_updates
        )
        self.check_button.pack(side=tk.LEFT, padx=6)
        self.refresh_button = ttk.Button(
            actions, text="Refresh list", command=self.refresh_installations
        )
        self.refresh_button.pack(side=tk.RIGHT)

        listing = ttk.LabelFrame(container, text="Registered installations", padding=8)
        listing.pack(fill=tk.BOTH, expand=True)
        columns = ("version", "status")
        self.install_tree = ttk.Treeview(
            listing,
            columns=columns,
            show="tree headings",
            selectmode="browse",
            height=7,
        )
        self.install_tree.heading("#0", text="Installation path")
        self.install_tree.heading("version", text="Version")
        self.install_tree.heading("status", text="Status")
        self.install_tree.column("#0", width=440, minwidth=200)
        self.install_tree.column("version", width=100, anchor=tk.CENTER)
        self.install_tree.column("status", width=110, anchor=tk.CENTER)
        scrollbar = ttk.Scrollbar(
            listing, orient=tk.VERTICAL, command=self.install_tree.yview
        )
        self.install_tree.configure(yscrollcommand=scrollbar.set)
        self.install_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.remove_button = ttk.Button(
            container,
            text="Remove selected installation…",
            command=self._remove_selected,
        )
        self.remove_button.pack(anchor=tk.W, pady=(8, 10))

        progress_row = ttk.Frame(container)
        progress_row.pack(fill=tk.X, pady=(0, 8))
        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(progress_row, textvariable=self.status_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        self.progress = ttk.Progressbar(progress_row, maximum=100, length=220)
        self.progress.pack(side=tk.RIGHT)

        activity = ttk.LabelFrame(container, text="Activity", padding=6)
        activity.pack(fill=tk.BOTH, expand=True)
        self.activity = tk.Text(activity, height=8, wrap=tk.WORD, state=tk.DISABLED)
        activity_scrollbar = ttk.Scrollbar(
            activity, orient=tk.VERTICAL, command=self.activity.yview
        )
        self.activity.configure(yscrollcommand=activity_scrollbar.set)
        self.activity.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        activity_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.action_buttons = (
            self.install_button,
            self.update_button,
            self.check_button,
            self.refresh_button,
            self.remove_button,
        )

    def _append_activity(self, message: str) -> None:
        self.activity.configure(state=tk.NORMAL)
        self.activity.insert(tk.END, message.rstrip() + "\n")
        self.activity.see(tk.END)
        self.activity.configure(state=tk.DISABLED)

    def _close(self) -> None:
        if self.running:
            messagebox.showinfo(
                "Operation in progress",
                "Wait for the current operation to finish before closing the updater.",
                parent=self.root,
            )
            return
        self.root.destroy()

    def refresh_installations(self) -> None:
        for item in self.install_tree.get_children():
            self.install_tree.delete(item)

        for install_dir in read_install_paths():
            exists = install_dir.is_dir()
            version = read_installed_version(install_dir) if exists else None
            self.install_tree.insert(
                "",
                tk.END,
                iid=str(install_dir),
                text=str(install_dir),
                values=(version or "Unknown", "Installed" if exists else "Missing"),
            )

    def _start_task(self, label: str, operation) -> None:
        if self.running:
            return
        self.running = True
        self.operation_failed = False
        for button in self.action_buttons:
            button.configure(state=tk.DISABLED)
        self.progress.configure(mode="determinate", value=0)
        self.status_var.set(label)
        self._append_activity(label)

        def report_message(message: str) -> None:
            self.events.put(("message", message))

        def report_progress(
            phase: str,
            completed: int,
            total: int | None,
        ) -> None:
            self.events.put(("progress", phase, completed, total))

        def worker() -> None:
            try:
                result = operation(report_message, report_progress)
                self.events.put(("result", result))
            except Exception as exc:
                self.events.put(("error", str(exc)))
            finally:
                self.events.put(("done",))

        threading.Thread(target=worker, daemon=True).start()

    def _install(self) -> None:
        default_dir = Path.home() / "Games"
        initial_dir = default_dir if default_dir.is_dir() else Path.home()
        selected = filedialog.askdirectory(
            title="Choose the parent folder for the game installation",
            initialdir=initial_dir,
            mustexist=True,
        )
        if not selected:
            return
        parent = Path(selected)
        self._start_task(
            "Installing latest release…",
            lambda message, progress: install(
                parent,
                on_message=message,
                on_progress=progress,
            ),
        )

    def _update(self) -> None:
        self._start_task(
            "Updating registered installations…",
            lambda message, progress: update_installations(
                on_message=message,
                on_progress=progress,
            ),
        )

    def _check_updates(self) -> None:
        self._start_task(
            "Checking for updates…",
            lambda message, progress: update_installations(
                check_only=True,
                on_message=message,
                on_progress=progress,
            ),
        )

    def _remove_selected(self) -> None:
        selection = self.install_tree.selection()
        if not selection:
            messagebox.showinfo(
                "Choose an installation",
                "Select an installation from the list first.",
                parent=self.root,
            )
            return

        install_dir = Path(selection[0])
        question = (
            f"Permanently remove {install_dir} and all its files?"
            if install_dir.is_dir()
            else f"Remove the missing installation record for {install_dir}?"
        )
        if not messagebox.askyesno("Remove installation", question, parent=self.root):
            return

        self._start_task(
            "Removing installation…",
            lambda message, progress: remove_registered_install(install_dir),
        )

    def _poll_events(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "message":
                    self._append_activity(event[1])
                    self.status_var.set(event[1])
                elif kind == "progress":
                    _, phase, completed, total = event
                    if total:
                        percentage = min(100, int(completed * 100 / total))
                        if str(self.progress.cget("mode")) == "indeterminate":
                            self.progress.stop()
                        self.progress.configure(mode="determinate", value=percentage)
                        self.status_var.set(f"{phase}: {percentage}%")
                    else:
                        if str(self.progress.cget("mode")) != "indeterminate":
                            self.progress.configure(mode="indeterminate")
                            self.progress.start(12)
                        self.status_var.set(f"{phase}: {completed:,} bytes")
                elif kind == "result":
                    result = event[1]
                    if isinstance(result, list):
                        for message in result:
                            self._append_activity(message)
                    if isinstance(result, int) and result != 0:
                        self._append_activity("Operation finished with errors.")
                        self.operation_failed = True
                elif kind == "error":
                    self._append_activity(f"Error: {event[1]}")
                    self.operation_failed = True
                elif kind == "done":
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.running = False
                    for button in self.action_buttons:
                        button.configure(state=tk.NORMAL)
                    self.refresh_installations()
                    self.status_var.set(
                        "Operation finished with errors" if self.operation_failed else "Ready"
                    )
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)


def main() -> int:
    root: tk.Tk | None = None
    try:
        root = tk.Tk()
        UpdaterWindow(root)
        root.mainloop()
        return 0
    except Exception as exc:
        details = traceback.format_exc()
        log_path = APP_DATA_DIR / "logs" / "gui-startup.log"
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(details, encoding="utf-8")
        except OSError:
            log_path = None

        try:
            if root is None:
                root = tk.Tk()
            root.withdraw()
            message = f"The updater could not start: {exc}"
            if log_path is not None:
                message += f"\n\nDetails were saved to:\n{log_path}"
            messagebox.showerror("Tenkaichi3Decomp Updater", message, parent=root)
            root.destroy()
        except tk.TclError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
