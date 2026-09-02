"""Reusable Tk widgets for the Cognex application."""

import tkinter as tk
from tkinter import messagebox, ttk

from .constants import DATA_TYPES

# GUI Widgets
# ============================================================

class BitIndicator(ttk.Frame):
    def __init__(
        self,
        parent,
        text,
    ):
        super().__init__(
            parent
        )

        self.canvas = tk.Canvas(
            self,
            width=20,
            height=20,
            highlightthickness=0,
        )

        self.canvas.pack(
            side=tk.LEFT,
            padx=(0, 7),
        )

        self.led = (
            self.canvas.create_oval(
                3,
                3,
                17,
                17,
                fill="#707070",
            )
        )

        ttk.Label(
            self,
            text=text,
        ).pack(
            side=tk.LEFT
        )

    def set(
        self,
        value,
    ):
        self.canvas.itemconfigure(
            self.led,
            fill=(
                "#22C55E"
                if value
                else "#707070"
            ),
        )


class ScrollableFrame(ttk.Frame):
    def __init__(
        self,
        parent,
    ):
        super().__init__(
            parent
        )

        self.canvas = tk.Canvas(
            self,
            highlightthickness=0,
        )

        scrollbar = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
        )

        self.content = ttk.Frame(
            self.canvas
        )

        self.window_id = (
            self.canvas.create_window(
                (0, 0),
                window=self.content,
                anchor="nw",
            )
        )

        self.canvas.configure(
            yscrollcommand=(
                scrollbar.set
            )
        )

        self.canvas.pack(
            side=tk.LEFT,
            fill=tk.BOTH,
            expand=True,
        )

        scrollbar.pack(
            side=tk.RIGHT,
            fill=tk.Y,
        )

        self.content.bind(
            "<Configure>",
            lambda _e:
                self.canvas.configure(
                    scrollregion=
                    self.canvas.bbox(
                        "all"
                    )
                ),
        )

        self.canvas.bind(
            "<Configure>",
            lambda e:
                self.canvas.itemconfigure(
                    self.window_id,
                    width=e.width,
                ),
        )

        self.canvas.bind(
            "<MouseWheel>",
            lambda e:
                self.canvas.yview_scroll(
                    int(
                        -e.delta / 120
                    ),
                    "units",
                ),
        )


# ============================================================
# Data Layout Editor
# ============================================================

class LayoutEditor(ttk.LabelFrame):
    def __init__(
        self,
        parent,
        title,
        layout,
        on_change,
    ):
        super().__init__(
            parent,
            text=title,
            padding=10,
        )

        self.layout = layout
        self.on_change = on_change

        self.tree = ttk.Treeview(
            self,
            columns=(
                "type",
                "offset",
                "size",
            ),
            show="tree headings",
            height=12,
        )

        self.tree.heading(
            "#0",
            text="Name",
        )

        self.tree.heading(
            "type",
            text="Type",
        )

        self.tree.heading(
            "offset",
            text="Offset",
        )

        self.tree.heading(
            "size",
            text="Bytes",
        )

        self.tree.column(
            "#0",
            width=190,
            stretch=True,
        )

        self.tree.column(
            "type",
            width=70,
            anchor="center",
        )

        self.tree.column(
            "offset",
            width=70,
            anchor="center",
        )

        self.tree.column(
            "size",
            width=60,
            anchor="center",
        )

        self.tree.pack(
            fill=tk.BOTH,
            expand=True,
        )

        controls = ttk.Frame(
            self
        )

        controls.pack(
            fill=tk.X,
            pady=(8, 0),
        )

        self.name_var = (
            tk.StringVar(
                value="Value1"
            )
        )

        self.type_var = (
            tk.StringVar(
                value="REAL"
            )
        )

        ttk.Entry(
            controls,
            textvariable=self.name_var,
            width=18,
        ).pack(
            side=tk.LEFT,
            padx=(0, 5),
        )

        ttk.Combobox(
            controls,
            textvariable=self.type_var,
            values=list(
                DATA_TYPES
            ),
            state="readonly",
            width=7,
        ).pack(
            side=tk.LEFT,
            padx=(0, 5),
        )

        ttk.Button(
            controls,
            text="Add",
            command=self._add,
        ).pack(
            side=tk.LEFT,
            padx=2,
        )

        ttk.Button(
            controls,
            text="Remove",
            command=self._remove,
        ).pack(
            side=tk.LEFT,
            padx=2,
        )

        ttk.Button(
            controls,
            text="↑",
            width=3,
            command=lambda:
                self._move(-1),
        ).pack(
            side=tk.LEFT,
            padx=2,
        )

        ttk.Button(
            controls,
            text="↓",
            width=3,
            command=lambda:
                self._move(1),
        ).pack(
            side=tk.LEFT,
            padx=2,
        )

        self.usage_label = ttk.Label(
            self,
            text="",
        )

        self.usage_label.pack(
            anchor="w",
            pady=(8, 0),
        )

        self.refresh()

    def selected_index(self):
        selected = (
            self.tree.selection()
        )

        if not selected:
            return None

        children = list(
            self.tree.get_children()
        )

        return children.index(
            selected[0]
        )

    def refresh(
        self,
        select_index=None,
    ):
        for item in (
            self.tree.get_children()
        ):
            self.tree.delete(
                item
            )

        inserted = []

        for field in (
            self.layout.offsets()
        ):
            item = self.tree.insert(
                "",
                tk.END,
                text=field["name"],
                values=(
                    field["type"],
                    field["offset"],
                    field["size"],
                ),
            )

            inserted.append(
                item
            )

        if (
            select_index is not None
            and 0 <= select_index
            < len(inserted)
        ):
            self.tree.selection_set(
                inserted[
                    select_index
                ]
            )

            self.tree.focus(
                inserted[
                    select_index
                ]
            )

        self.usage_label.configure(
            text=(
                f"Used: "
                f"{self.layout.total_size()} / "
                f"{self.layout.max_size} bytes"
            )
        )

    def _add(self):
        try:
            self.layout.add(
                self.name_var.get(),
                self.type_var.get(),
            )

        except Exception as exc:
            messagebox.showerror(
                "Layout",
                str(exc),
            )
            return

        self.name_var.set(
            f"Value"
            f"{len(self.layout.fields) + 1}"
        )

        self.refresh(
            len(self.layout.fields) - 1
        )

        self.on_change()

    def _remove(self):
        index = (
            self.selected_index()
        )

        if index is None:
            return

        self.layout.remove(
            index
        )

        self.refresh()
        self.on_change()

    def _move(
        self,
        delta,
    ):
        index = (
            self.selected_index()
        )

        if index is None:
            return

        new_index = (
            self.layout.move(
                index,
                delta,
            )
        )

        self.refresh(
            new_index
        )

        self.on_change()


# ============================================================
