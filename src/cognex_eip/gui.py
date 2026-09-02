"""Tk application for monitoring and controlling Cognex Class 1 I/O."""

import json
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .binary import format_display_value, get_bit, get_bits, hex_dump, uint16_le
from .connection import CognexConnection
from .constants import DEFAULT_CAMERA_IP, DEFAULT_RPI_MS, GUI_REFRESH_MS, HEX_REFRESH_MS, INPUT_BITS, INPUT_RESULTS_OFFSET, INPUT_RESULTS_SIZE, IO_TIMEOUT_SECONDS, NUMERIC_FIELDS, OUTPUT_BITS, OUTPUT_USER_SIZE
from .layout import DataLayout
from .widgets import BitIndicator, LayoutEditor, ScrollableFrame

# Main GUI
# ============================================================

class CognexGUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title(
            "Cognex EtherNet/IP Monitor & Control"
        )

        self.geometry(
            "1350x850"
        )

        self.minsize(
            1000,
            650,
        )

        self.connection = (
            CognexConnection()
        )

        self.input_layout = (
            DataLayout(
                INPUT_RESULTS_SIZE
            )
        )

        self.output_layout = (
            DataLayout(
                OUTPUT_USER_SIZE
            )
        )

        self.input_indicators = {}
        self.output_vars = {}
        self.numeric_labels = {}

        self.input_value_labels = {}
        self.output_value_vars = {}

        self.last_hex_update = 0
        self.last_error = None

        self._build_gui()

        self.after(
            GUI_REFRESH_MS,
            self._refresh,
        )

        self.protocol(
            "WM_DELETE_WINDOW",
            self._close,
        )

    # ========================================================
    # Build GUI
    # ========================================================

    def _build_gui(self):
        self._build_connection_bar()

        self.notebook = ttk.Notebook(
            self
        )

        self.notebook.pack(
            fill=tk.BOTH,
            expand=True,
            padx=10,
            pady=5,
        )

        self.live_tab = ttk.Frame(
            self.notebook
        )

        self.layout_tab = ttk.Frame(
            self.notebook
        )

        self.raw_tab = ttk.Frame(
            self.notebook
        )

        self.notebook.add(
            self.live_tab,
            text="Live I/O",
        )

        self.notebook.add(
            self.layout_tab,
            text="Data Layout",
        )

        self.notebook.add(
            self.raw_tab,
            text="Raw I/O",
        )

        self._build_live_tab()
        self._build_layout_tab()
        self._build_raw_tab()
        self._build_bottom_bar()

    # ========================================================
    # Connection Bar
    # ========================================================

    def _build_connection_bar(self):
        frame = ttk.Frame(
            self,
            padding=10,
        )

        frame.pack(
            fill=tk.X
        )

        ttk.Label(
            frame,
            text="Camera IP:",
        ).pack(
            side=tk.LEFT
        )

        self.ip_var = (
            tk.StringVar(
                value=DEFAULT_CAMERA_IP
            )
        )

        self.ip_entry = ttk.Entry(
            frame,
            textvariable=self.ip_var,
            width=18,
        )

        self.ip_entry.pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Label(
            frame,
            text="RPI:",
        ).pack(
            side=tk.LEFT,
            padx=(15, 0),
        )

        self.rpi_var = (
            tk.StringVar(
                value=str(
                    DEFAULT_RPI_MS
                )
            )
        )

        self.rpi_entry = ttk.Entry(
            frame,
            textvariable=self.rpi_var,
            width=7,
        )

        self.rpi_entry.pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Label(
            frame,
            text="ms",
        ).pack(
            side=tk.LEFT
        )

        self.connect_button = (
            ttk.Button(
                frame,
                text="Connect",
                command=self._connect,
            )
        )

        self.connect_button.pack(
            side=tk.LEFT,
            padx=(20, 5),
        )

        self.disconnect_button = (
            ttk.Button(
                frame,
                text="Disconnect",
                command=self._disconnect,
                state=tk.DISABLED,
            )
        )

        self.disconnect_button.pack(
            side=tk.LEFT
        )

        self.connection_label = (
            ttk.Label(
                frame,
                text="Disconnected",
                font=(
                    "Segoe UI",
                    10,
                    "bold",
                ),
            )
        )

        self.connection_label.pack(
            side=tk.LEFT,
            padx=20,
        )

    # ========================================================
    # Live I/O
    # ========================================================

    def _build_live_tab(self):
        scroll = ScrollableFrame(
            self.live_tab
        )

        scroll.pack(
            fill=tk.BOTH,
            expand=True,
        )

        self.live_container = (
            scroll.content
        )

        self.live_container.columnconfigure(
            0,
            weight=1,
        )

        self.live_container.columnconfigure(
            1,
            weight=1,
        )

        # ----------------------------------------------------
        # Input status
        # ----------------------------------------------------

        input_frame = ttk.LabelFrame(
            self.live_container,
            text=(
                "Camera → PC | "
                "Input Assembly 13"
            ),
            padding=10,
        )

        input_frame.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(10, 5),
            pady=(10, 5),
        )

        row = 0

        for (
            byte,
            bit,
            name,
        ) in INPUT_BITS:
            indicator = BitIndicator(
                input_frame,
                name,
            )

            indicator.grid(
                row=row,
                column=0,
                sticky="w",
                pady=2,
            )

            ttk.Label(
                input_frame,
                text=f"B{byte}.{bit}",
                foreground="#707070",
            ).grid(
                row=row,
                column=1,
                sticky="e",
                padx=(15, 0),
            )

            self.input_indicators[
                (byte, bit)
            ] = indicator

            row += 1

        ttk.Separator(
            input_frame
        ).grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=8,
        )

        row += 1

        ttk.Label(
            input_frame,
            text="Offline Reason",
        ).grid(
            row=row,
            column=0,
            sticky="w",
        )

        self.offline_label = (
            ttk.Label(
                input_frame,
                text="0 (0b000)",
                font=(
                    "Consolas",
                    10,
                    "bold",
                ),
            )
        )

        self.offline_label.grid(
            row=row,
            column=1,
            sticky="e",
        )

        row += 1

        ttk.Separator(
            input_frame
        ).grid(
            row=row,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=8,
        )

        row += 1

        for (
            name,
            offset,
        ) in NUMERIC_FIELDS:
            ttk.Label(
                input_frame,
                text=name,
            ).grid(
                row=row,
                column=0,
                sticky="w",
                pady=2,
            )

            label = ttk.Label(
                input_frame,
                text="0",
                font=("Consolas", 10),
            )

            label.grid(
                row=row,
                column=1,
                sticky="e",
            )

            self.numeric_labels[
                offset
            ] = label

            row += 1

        # ----------------------------------------------------
        # Output controls
        # ----------------------------------------------------

        output_frame = ttk.LabelFrame(
            self.live_container,
            text=(
                "PC → Camera | "
                "Output Assembly 22"
            ),
            padding=10,
        )

        output_frame.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(5, 10),
            pady=(10, 5),
        )

        ttk.Label(
            output_frame,
            text="Signal",
            font=(
                "Segoe UI",
                9,
                "bold",
            ),
        ).grid(
            row=0,
            column=0,
            sticky="w",
        )

        ttk.Label(
            output_frame,
            text="Level",
            font=(
                "Segoe UI",
                9,
                "bold",
            ),
        ).grid(
            row=0,
            column=1,
        )

        ttk.Label(
            output_frame,
            text="Pulse",
            font=(
                "Segoe UI",
                9,
                "bold",
            ),
        ).grid(
            row=0,
            column=2,
        )

        for row, (
            byte,
            bit,
            name,
        ) in enumerate(
            OUTPUT_BITS,
            start=1,
        ):
            ttk.Label(
                output_frame,
                text=name,
            ).grid(
                row=row,
                column=0,
                sticky="w",
                pady=2,
            )

            var = tk.BooleanVar(
                value=False
            )

            ttk.Checkbutton(
                output_frame,
                variable=var,
                command=(
                    lambda b=byte,
                    n=bit,
                    v=var:
                    self.connection
                    .set_output_bit(
                        b,
                        n,
                        v.get(),
                    )
                ),
            ).grid(
                row=row,
                column=1,
                padx=12,
            )

            ttk.Button(
                output_frame,
                text="100 ms",
                command=(
                    lambda b=byte,
                    n=bit:
                    self.connection
                    .pulse_output_bit(
                        b,
                        n,
                        0.1,
                    )
                ),
            ).grid(
                row=row,
                column=2,
                padx=5,
            )

            self.output_vars[
                (byte, bit)
            ] = var

        row = (
            len(OUTPUT_BITS)
            + 2
        )

        ttk.Separator(
            output_frame
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=8,
        )

        row += 1

        ttk.Label(
            output_frame,
            text="Command ID",
        ).grid(
            row=row,
            column=0,
            sticky="w",
        )

        self.command_id_var = (
            tk.StringVar(
                value="0"
            )
        )

        ttk.Entry(
            output_frame,
            textvariable=
                self.command_id_var,
            width=12,
        ).grid(
            row=row,
            column=1,
            padx=5,
        )

        ttk.Button(
            output_frame,
            text="Apply",
            command=
                self._apply_command_id,
        ).grid(
            row=row,
            column=2,
            padx=5,
        )

        row += 1

        ttk.Button(
            output_frame,
            text="CLEAR ALL OUTPUTS",
            command=
                self._clear_outputs,
        ).grid(
            row=row,
            column=0,
            columnspan=3,
            sticky="ew",
            pady=(10, 0),
        )

        # ----------------------------------------------------
        # Formatted inspection results
        # ----------------------------------------------------

        self.formatted_input_frame = (
            ttk.LabelFrame(
                self.live_container,
                text=(
                    "Formatted Inspection Results "
                    "(Input byte 16+)"
                ),
                padding=10,
            )
        )

        self.formatted_input_frame.grid(
            row=1,
            column=0,
            sticky="nsew",
            padx=(10, 5),
            pady=(5, 10),
        )

        # ----------------------------------------------------
        # Formatted output User Data
        # ----------------------------------------------------

        self.formatted_output_frame = (
            ttk.LabelFrame(
                self.live_container,
                text=(
                    "Formatted User Data "
                    "(Output byte 8+)"
                ),
                padding=10,
            )
        )

        self.formatted_output_frame.grid(
            row=1,
            column=1,
            sticky="nsew",
            padx=(5, 10),
            pady=(5, 10),
        )

        self._rebuild_formatted_panels()

    # ========================================================
    # Data Layout
    # ========================================================

    def _build_layout_tab(self):
        container = ttk.Frame(
            self.layout_tab,
            padding=10,
        )

        container.pack(
            fill=tk.BOTH,
            expand=True,
        )

        container.columnconfigure(
            0,
            weight=1,
        )

        container.columnconfigure(
            1,
            weight=1,
        )

        container.rowconfigure(
            0,
            weight=1,
        )

        self.input_editor = (
            LayoutEditor(
                container,
                (
                    "Inspection Results Layout "
                    f"({INPUT_RESULTS_SIZE} "
                    "bytes available)"
                ),
                self.input_layout,
                self._layout_changed,
            )
        )

        self.input_editor.grid(
            row=0,
            column=0,
            sticky="nsew",
            padx=(0, 5),
        )

        self.output_editor = (
            LayoutEditor(
                container,
                (
                    "User Data Layout "
                    f"({OUTPUT_USER_SIZE} "
                    "bytes available)"
                ),
                self.output_layout,
                self._layout_changed,
            )
        )

        self.output_editor.grid(
            row=0,
            column=1,
            sticky="nsew",
            padx=(5, 0),
        )

        bottom = ttk.Frame(
            container
        )

        bottom.grid(
            row=1,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(10, 0),
        )

        ttk.Button(
            bottom,
            text="Save Layout...",
            command=self._save_layout,
        ).pack(
            side=tk.LEFT
        )

        ttk.Button(
            bottom,
            text="Load Layout...",
            command=self._load_layout,
        ).pack(
            side=tk.LEFT,
            padx=5,
        )

        ttk.Label(
            bottom,
            text=(
                "Fields are packed sequentially; "
                "moving a field recalculates every "
                "following byte offset."
            ),
        ).pack(
            side=tk.LEFT,
            padx=15,
        )

    # ========================================================
    # Raw I/O
    # ========================================================

    def _make_text_with_scrollbars(
        self,
        parent,
    ):
        frame = ttk.Frame(
            parent
        )

        frame.pack(
            fill=tk.BOTH,
            expand=True,
        )

        text = tk.Text(
            frame,
            font=("Consolas", 10),
            wrap="none",
        )

        ybar = ttk.Scrollbar(
            frame,
            orient="vertical",
            command=text.yview,
        )

        xbar = ttk.Scrollbar(
            frame,
            orient="horizontal",
            command=text.xview,
        )

        text.configure(
            yscrollcommand=ybar.set,
            xscrollcommand=xbar.set,
        )

        text.grid(
            row=0,
            column=0,
            sticky="nsew",
        )

        ybar.grid(
            row=0,
            column=1,
            sticky="ns",
        )

        xbar.grid(
            row=1,
            column=0,
            sticky="ew",
        )

        frame.rowconfigure(
            0,
            weight=1,
        )

        frame.columnconfigure(
            0,
            weight=1,
        )

        return text

    def _build_raw_tab(self):
        pane = ttk.Panedwindow(
            self.raw_tab,
            orient=tk.VERTICAL,
        )

        pane.pack(
            fill=tk.BOTH,
            expand=True,
            padx=10,
            pady=10,
        )

        input_frame = ttk.LabelFrame(
            pane,
            text="Input Assembly 13",
        )

        output_frame = ttk.LabelFrame(
            pane,
            text="Output Assembly 22",
        )

        pane.add(
            input_frame,
            weight=1,
        )

        pane.add(
            output_frame,
            weight=1,
        )

        self.raw_input_text = (
            self._make_text_with_scrollbars(
                input_frame
            )
        )

        self.raw_output_text = (
            self._make_text_with_scrollbars(
                output_frame
            )
        )

    # ========================================================
    # Bottom Bar
    # ========================================================

    def _build_bottom_bar(self):
        frame = ttk.Frame(
            self,
            padding=8,
        )

        frame.pack(
            fill=tk.X
        )

        self.packet_label = ttk.Label(
            frame,
            text="Packets: 0",
        )

        self.rate_label = ttk.Label(
            frame,
            text="Rate: 0 Hz",
        )

        self.age_label = ttk.Label(
            frame,
            text="Last Packet: --",
        )

        self.packet_label.pack(
            side=tk.LEFT
        )

        self.rate_label.pack(
            side=tk.LEFT,
            padx=20,
        )

        self.age_label.pack(
            side=tk.LEFT
        )

    # ========================================================
    # Dynamic Formatted Panels
    # ========================================================

    def _clear_children(
        self,
        widget,
    ):
        for child in (
            widget.winfo_children()
        ):
            child.destroy()

    def _rebuild_formatted_panels(self):
        old_output_values = {
            name: var.get()
            for (
                name,
                var,
            ) in self.output_value_vars.items()
        }

        # ----------------------------------------------------
        # Input inspection results
        # ----------------------------------------------------

        self._clear_children(
            self.formatted_input_frame
        )

        self.input_value_labels = {}

        input_fields = (
            self.input_layout.offsets()
        )

        if not input_fields:
            ttk.Label(
                self.formatted_input_frame,
                text=(
                    "No fields configured. "
                    "Add fields on the Data Layout tab."
                ),
            ).grid(
                row=0,
                column=0,
                sticky="w",
            )

        else:
            for column, heading in enumerate(
                (
                    "Name",
                    "Type",
                    "Offset",
                    "Value",
                )
            ):
                ttk.Label(
                    self.formatted_input_frame,
                    text=heading,
                    font=(
                        "Segoe UI",
                        9,
                        "bold",
                    ),
                ).grid(
                    row=0,
                    column=column,
                    sticky="w",
                    padx=(0, 12),
                )

            for row, field in enumerate(
                input_fields,
                start=1,
            ):
                ttk.Label(
                    self.formatted_input_frame,
                    text=field["name"],
                ).grid(
                    row=row,
                    column=0,
                    sticky="w",
                    pady=2,
                )

                ttk.Label(
                    self.formatted_input_frame,
                    text=field["type"],
                ).grid(
                    row=row,
                    column=1,
                    sticky="w",
                    padx=(0, 12),
                )

                ttk.Label(
                    self.formatted_input_frame,
                    text=str(
                        field["offset"]
                    ),
                ).grid(
                    row=row,
                    column=2,
                    sticky="w",
                    padx=(0, 12),
                )

                label = ttk.Label(
                    self.formatted_input_frame,
                    text="--",
                    font=(
                        "Consolas",
                        10,
                    ),
                )

                label.grid(
                    row=row,
                    column=3,
                    sticky="e",
                )

                self.input_value_labels[
                    field["name"]
                ] = label

        # ----------------------------------------------------
        # Output User Data
        # ----------------------------------------------------

        self._clear_children(
            self.formatted_output_frame
        )

        self.output_value_vars = {}

        output_fields = (
            self.output_layout.offsets()
        )

        if not output_fields:
            ttk.Label(
                self.formatted_output_frame,
                text=(
                    "No fields configured. "
                    "Add fields on the Data Layout tab."
                ),
            ).grid(
                row=0,
                column=0,
                sticky="w",
            )

        else:
            for column, heading in enumerate(
                (
                    "Name",
                    "Type",
                    "Offset",
                    "Value",
                )
            ):
                ttk.Label(
                    self.formatted_output_frame,
                    text=heading,
                    font=(
                        "Segoe UI",
                        9,
                        "bold",
                    ),
                ).grid(
                    row=0,
                    column=column,
                    sticky="w",
                    padx=(0, 12),
                )

            for row, field in enumerate(
                output_fields,
                start=1,
            ):
                ttk.Label(
                    self.formatted_output_frame,
                    text=field["name"],
                ).grid(
                    row=row,
                    column=0,
                    sticky="w",
                    pady=2,
                )

                ttk.Label(
                    self.formatted_output_frame,
                    text=field["type"],
                ).grid(
                    row=row,
                    column=1,
                    sticky="w",
                    padx=(0, 12),
                )

                ttk.Label(
                    self.formatted_output_frame,
                    text=str(
                        field["offset"]
                    ),
                ).grid(
                    row=row,
                    column=2,
                    sticky="w",
                    padx=(0, 12),
                )

                var = tk.StringVar(
                    value=old_output_values.get(
                        field["name"],
                        "0",
                    )
                )

                ttk.Entry(
                    self.formatted_output_frame,
                    textvariable=var,
                    width=16,
                ).grid(
                    row=row,
                    column=3,
                    sticky="ew",
                )

                self.output_value_vars[
                    field["name"]
                ] = var

            last_row = (
                len(output_fields)
                + 1
            )

            ttk.Button(
                self.formatted_output_frame,
                text="Apply User Data",
                command=
                    self._apply_formatted_user_data,
            ).grid(
                row=last_row,
                column=0,
                columnspan=2,
                sticky="ew",
                pady=(10, 0),
            )

            ttk.Button(
                self.formatted_output_frame,
                text=(
                    "Apply + Pulse "
                    "Set User Data"
                ),
                command=
                    self._apply_formatted_user_data_and_pulse,
            ).grid(
                row=last_row,
                column=2,
                columnspan=2,
                sticky="ew",
                padx=(5, 0),
                pady=(10, 0),
            )

    # ========================================================
    # Layout Handling
    # ========================================================

    def _layout_changed(self):
        self._rebuild_formatted_panels()

    def _save_layout(self):
        path = (
            filedialog.asksaveasfilename(
                title="Save Data Layout",
                defaultextension=".json",
                filetypes=[
                    (
                        "JSON files",
                        "*.json",
                    ),
                    (
                        "All files",
                        "*.*",
                    ),
                ],
            )
        )

        if not path:
            return

        data = {
            "inspection_results":
                self.input_layout
                .copy_fields(),

            "user_data":
                self.output_layout
                .copy_fields(),
        }

        with open(
            path,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                indent=2,
            )

    def _load_layout(self):
        path = (
            filedialog.askopenfilename(
                title="Load Data Layout",
                filetypes=[
                    (
                        "JSON files",
                        "*.json",
                    ),
                    (
                        "All files",
                        "*.*",
                    ),
                ],
            )
        )

        if not path:
            return

        try:
            with open(
                path,
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(
                    file
                )

            new_input = DataLayout(
                INPUT_RESULTS_SIZE,
                data.get(
                    "inspection_results",
                    [],
                ),
            )

            new_output = DataLayout(
                OUTPUT_USER_SIZE,
                data.get(
                    "user_data",
                    [],
                ),
            )

            self.input_layout = (
                new_input
            )

            self.output_layout = (
                new_output
            )

            self.input_editor.layout = (
                self.input_layout
            )

            self.output_editor.layout = (
                self.output_layout
            )

            self.input_editor.refresh()
            self.output_editor.refresh()

            self._rebuild_formatted_panels()

        except Exception as exc:
            messagebox.showerror(
                "Load Layout",
                str(exc),
            )

    # ========================================================
    # Commands
    # ========================================================

    def _connect(self):
        try:
            rpi = float(
                self.rpi_var.get()
            )

            if rpi <= 0:
                raise ValueError

        except ValueError:
            messagebox.showerror(
                "RPI",
                "RPI must be a positive number.",
            )
            return

        camera_ip = (
            self.ip_var
            .get()
            .strip()
        )

        if not camera_ip:
            messagebox.showerror(
                "Camera IP",
                "Enter the camera IP address.",
            )
            return

        self.connection.start(
            camera_ip,
            rpi,
        )

        self.connect_button.configure(
            state=tk.DISABLED
        )

        self.disconnect_button.configure(
            state=tk.NORMAL
        )

    def _disconnect(self):
        self.connection.stop()

    def _apply_command_id(self):
        try:
            value = int(
                self.command_id_var.get(),
                0,
            )

            self.connection.set_command_id(
                value
            )

        except Exception as exc:
            messagebox.showerror(
                "Command ID",
                str(exc),
            )

    def _clear_outputs(self):
        self.connection.clear_outputs()

        for var in (
            self.output_vars.values()
        ):
            var.set(
                False
            )

        self.command_id_var.set(
            "0"
        )

        for var in (
            self.output_value_vars.values()
        ):
            var.set(
                "0"
            )

    def _apply_formatted_user_data(self):
        try:
            values = {
                name: var.get()
                for (
                    name,
                    var,
                ) in self.output_value_vars.items()
            }

            encoded = (
                self.output_layout
                .encode(
                    values
                )
            )

            self.connection.set_user_data(
                encoded[
                    :self.output_layout
                    .total_size()
                ]
            )

        except Exception as exc:
            messagebox.showerror(
                "User Data",
                str(exc),
            )
            return False

        return True

    def _apply_formatted_user_data_and_pulse(self):
        if (
            self._apply_formatted_user_data()
        ):
            self.connection.pulse_output_bit(
                2,
                0,
                0.1,
            )

    # ========================================================
    # Refresh
    # ========================================================

    def _refresh(self):
        snap = (
            self.connection.snapshot()
        )

        state = snap["state"]
        age = snap["packet_age"]

        if (
            state == "I/O Running"
            and age is not None
            and age
            > IO_TIMEOUT_SECONDS
        ):
            state_text = (
                "I/O TIMEOUT"
            )

        else:
            state_text = state

        self.connection_label.configure(
            text=state_text
        )

        self.packet_label.configure(
            text=(
                f"Packets: "
                f"{snap['packet_count']:,}"
            )
        )

        self.rate_label.configure(
            text=(
                f"Rate: "
                f"{snap['packet_rate']} Hz"
            )
        )

        if age is None:
            self.age_label.configure(
                text=(
                    "Last Packet: --"
                )
            )

        else:
            self.age_label.configure(
                text=(
                    f"Last Packet: "
                    f"{age * 1000:.1f} ms"
                )
            )

        data = snap["input"]

        # ----------------------------------------------------
        # Input status + standard fields
        # ----------------------------------------------------

        if data:
            for (
                byte,
                bit,
                _name,
            ) in INPUT_BITS:
                self.input_indicators[
                    (byte, bit)
                ].set(
                    get_bit(
                        data,
                        byte,
                        bit,
                    )
                )

            offline = get_bits(
                data,
                0,
                4,
                3,
            )

            self.offline_label.configure(
                text=(
                    f"{offline} "
                    f"(0b{offline:03b})"
                )
            )

            for (
                _name,
                offset,
            ) in NUMERIC_FIELDS:
                self.numeric_labels[
                    offset
                ].configure(
                    text=str(
                        uint16_le(
                            data,
                            offset,
                        )
                    )
                )

            # -----------------------------------------------
            # Configured Inspection Results
            # -----------------------------------------------

            result_buffer = data[
                INPUT_RESULTS_OFFSET:
                INPUT_RESULTS_OFFSET
                + INPUT_RESULTS_SIZE
            ]

            for (
                field,
                value,
            ) in self.input_layout.decode(
                result_buffer
            ):
                label = (
                    self.input_value_labels
                    .get(
                        field["name"]
                    )
                )

                if label is not None:
                    label.configure(
                        text=(
                            "--"
                            if value is None
                            else
                            format_display_value(
                                value,
                                field["type"],
                            )
                        )
                    )

        # ----------------------------------------------------
        # Output level controls
        # ----------------------------------------------------

        output = snap["output"]

        for (
            byte,
            bit,
            _name,
        ) in OUTPUT_BITS:
            self.output_vars[
                (byte, bit)
            ].set(
                get_bit(
                    output,
                    byte,
                    bit,
                )
            )

        # ----------------------------------------------------
        # Raw I/O at slower rate
        # ----------------------------------------------------

        now = (
            time.monotonic()
        )

        if (
            now
            - self.last_hex_update
            >= HEX_REFRESH_MS / 1000
        ):
            self.last_hex_update = (
                now
            )

            if data:
                self.raw_input_text.delete(
                    "1.0",
                    tk.END,
                )

                self.raw_input_text.insert(
                    tk.END,
                    hex_dump(
                        data
                    ),
                )

            self.raw_output_text.delete(
                "1.0",
                tk.END,
            )

            self.raw_output_text.insert(
                tk.END,
                hex_dump(
                    output
                ),
            )

        # ----------------------------------------------------
        # Errors / connection buttons
        # ----------------------------------------------------

        if (
            state == "Error"
            and snap["error"]
            and snap["error"]
            != self.last_error
        ):
            self.last_error = (
                snap["error"]
            )

            messagebox.showerror(
                "EtherNet/IP",
                snap["error"],
            )

        if state in (
            "Disconnected",
            "Error",
        ):
            self.connect_button.configure(
                state=tk.NORMAL
            )

            self.disconnect_button.configure(
                state=tk.DISABLED
            )

        self.after(
            GUI_REFRESH_MS,
            self._refresh,
        )

    # ========================================================
    # Close
    # ========================================================

    def _close(self):
        self.connection.stop()

        self.after(
            100,
            self.destroy,
        )


# ============================================================
