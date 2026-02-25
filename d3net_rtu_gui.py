#!/usr/bin/env python3
"""Tkinter UI for d3net_rtu_tool (Daikin DTA116A51 Modbus RTU)."""

from __future__ import annotations

import json
import queue
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import d3net_rtu_tool as rtu


class D3netGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Daikin D3Net RTU Tool")
        self.geometry("1100x760")

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.stop_watch = threading.Event()

        self._make_top_config()
        self._make_tabs()
        self._make_output()
        self.after(100, self._drain_logs)

    def _make_top_config(self) -> None:
        frame = ttk.LabelFrame(self, text="Serial Settings")
        frame.pack(fill="x", padx=8, pady=8)

        self.port_var = tk.StringVar(value="/dev/ttyUSB0")
        self.baud_var = tk.IntVar(value=9600)
        self.byte_var = tk.IntVar(value=8)
        self.parity_var = tk.StringVar(value="E")
        self.stop_var = tk.IntVar(value=1)
        self.timeout_var = tk.DoubleVar(value=1.0)
        self.slave_var = tk.IntVar(value=1)

        fields = [
            ("Port", ttk.Entry(frame, textvariable=self.port_var, width=22)),
            ("Baud", ttk.Entry(frame, textvariable=self.baud_var, width=8)),
            ("Bytes", ttk.Combobox(frame, textvariable=self.byte_var, values=[7, 8], width=5, state="readonly")),
            ("Parity", ttk.Combobox(frame, textvariable=self.parity_var, values=["N", "E", "O"], width=5, state="readonly")),
            ("Stop", ttk.Combobox(frame, textvariable=self.stop_var, values=[1, 2], width=5, state="readonly")),
            ("Timeout", ttk.Entry(frame, textvariable=self.timeout_var, width=8)),
            ("Slave", ttk.Entry(frame, textvariable=self.slave_var, width=8)),
        ]

        for idx, (label, widget) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=0, column=idx * 2, padx=(6, 2), pady=6, sticky="w")
            widget.grid(row=0, column=idx * 2 + 1, padx=(0, 6), pady=6, sticky="w")

        ttk.Button(frame, text="List Ports", command=self.on_ports).grid(row=0, column=len(fields) * 2, padx=8)

    def _make_tabs(self) -> None:
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.tab_scan = ttk.Frame(self.tabs)
        self.tab_status = ttk.Frame(self.tabs)
        self.tab_errors = ttk.Frame(self.tabs)
        self.tab_control = ttk.Frame(self.tabs)
        self.tab_watch = ttk.Frame(self.tabs)

        self.tabs.add(self.tab_scan, text="Scan")
        self.tabs.add(self.tab_status, text="Status")
        self.tabs.add(self.tab_errors, text="Errors")
        self.tabs.add(self.tab_control, text="Control")
        self.tabs.add(self.tab_watch, text="Watch/Logs")

        self._build_scan_tab()
        self._build_status_tab()
        self._build_errors_tab()
        self._build_control_tab()
        self._build_watch_tab()

    def _make_output(self) -> None:
        out = ttk.LabelFrame(self, text="Output")
        out.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.output = tk.Text(out, wrap="word", height=14)
        self.output.pack(fill="both", expand=True, padx=4, pady=4)

    def _build_scan_tab(self) -> None:
        self.scan_verbose = tk.BooleanVar(value=True)
        ttk.Checkbutton(self.tab_scan, text="Verbose", variable=self.scan_verbose).pack(anchor="w", padx=6, pady=6)
        ttk.Button(self.tab_scan, text="Scan Units", command=self.on_scan).pack(anchor="w", padx=6, pady=6)

    def _build_status_tab(self) -> None:
        frm = ttk.Frame(self.tab_status)
        frm.pack(fill="x", padx=6, pady=6)
        self.status_units = tk.StringVar(value="")
        ttk.Label(frm, text="Units (e.g. 0,1,3)").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.status_units, width=30).grid(row=0, column=1, padx=6)
        self.status_all = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="All discovered", variable=self.status_all).grid(row=0, column=2, padx=6)
        ttk.Button(frm, text="Read Status", command=self.on_status).grid(row=0, column=3, padx=6)

    def _build_errors_tab(self) -> None:
        frm = ttk.Frame(self.tab_errors)
        frm.pack(fill="x", padx=6, pady=6)
        self.error_units = tk.StringVar(value="")
        self.error_all = tk.BooleanVar(value=True)
        self.error_show_clear = tk.BooleanVar(value=False)
        ttk.Label(frm, text="Units (e.g. 0,1,3)").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.error_units, width=30).grid(row=0, column=1, padx=6)
        ttk.Checkbutton(frm, text="All discovered", variable=self.error_all).grid(row=0, column=2, padx=6)
        ttk.Checkbutton(frm, text="Show clear", variable=self.error_show_clear).grid(row=0, column=3, padx=6)
        ttk.Button(frm, text="Read Errors", command=self.on_errors).grid(row=0, column=4, padx=6)

    def _build_control_tab(self) -> None:
        frm = ttk.Frame(self.tab_control)
        frm.pack(fill="x", padx=6, pady=6)

        self.ctrl_unit = tk.IntVar(value=0)
        self.ctrl_power = tk.StringVar(value="")
        self.ctrl_mode = tk.StringVar(value="")
        self.ctrl_setpoint = tk.StringVar(value="")
        self.ctrl_fan_speed = tk.StringVar(value="")
        self.ctrl_fan_dir = tk.StringVar(value="")
        self.ctrl_filter_reset = tk.BooleanVar(value=False)

        row = 0
        ttk.Label(frm, text="Unit").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.ctrl_unit, width=8).grid(row=row, column=1, padx=6)
        ttk.Label(frm, text="Power").grid(row=row, column=2, sticky="w")
        ttk.Combobox(frm, textvariable=self.ctrl_power, values=["", "on", "off"], state="readonly", width=8).grid(row=row, column=3, padx=6)
        ttk.Label(frm, text="Mode").grid(row=row, column=4, sticky="w")
        ttk.Combobox(
            frm,
            textvariable=self.ctrl_mode,
            values=[""] + [m.name.lower() for m in rtu.D3netOperationMode],
            state="readonly",
            width=12,
        ).grid(row=row, column=5, padx=6)

        row += 1
        ttk.Label(frm, text="Setpoint (°C)").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.ctrl_setpoint, width=8).grid(row=row, column=1, padx=6)
        ttk.Label(frm, text="Fan Speed").grid(row=row, column=2, sticky="w")
        ttk.Combobox(
            frm,
            textvariable=self.ctrl_fan_speed,
            values=[""] + [m.name.lower() for m in rtu.D3netFanSpeed],
            state="readonly",
            width=12,
        ).grid(row=row, column=3, padx=6)
        ttk.Label(frm, text="Fan Direction").grid(row=row, column=4, sticky="w")
        ttk.Combobox(
            frm,
            textvariable=self.ctrl_fan_dir,
            values=[""] + [m.name.lower() for m in rtu.D3netFanDirection],
            state="readonly",
            width=12,
        ).grid(row=row, column=5, padx=6)

        row += 1
        ttk.Checkbutton(frm, text="Filter reset", variable=self.ctrl_filter_reset).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Button(frm, text="Apply Control", command=self.on_control).grid(row=row, column=1, padx=6)

    def _build_watch_tab(self) -> None:
        frm = ttk.Frame(self.tab_watch)
        frm.pack(fill="x", padx=6, pady=6)

        self.watch_unit = tk.IntVar(value=0)
        self.watch_interval = tk.DoubleVar(value=5.0)
        self.watch_duration = tk.DoubleVar(value=60.0)
        self.watch_out = tk.StringVar(value="")

        ttk.Label(frm, text="Unit").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.watch_unit, width=8).grid(row=0, column=1, padx=6)
        ttk.Label(frm, text="Interval (s)").grid(row=0, column=2, sticky="w")
        ttk.Entry(frm, textvariable=self.watch_interval, width=8).grid(row=0, column=3, padx=6)
        ttk.Label(frm, text="Duration (s)").grid(row=0, column=4, sticky="w")
        ttk.Entry(frm, textvariable=self.watch_duration, width=8).grid(row=0, column=5, padx=6)

        ttk.Label(frm, text="Output JSONL").grid(row=1, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.watch_out, width=50).grid(row=1, column=1, columnspan=4, padx=6, sticky="we")
        ttk.Button(frm, text="Browse", command=self.on_browse_watch).grid(row=1, column=5, padx=6)

        ttk.Button(frm, text="Start Watch", command=self.on_watch_start).grid(row=2, column=0, pady=8)
        ttk.Button(frm, text="Stop Watch", command=self.on_watch_stop).grid(row=2, column=1, pady=8)

    def _drain_logs(self) -> None:
        while True:
            try:
                line = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.output.insert("end", line + "\n")
            self.output.see("end")
        self.after(100, self._drain_logs)

    def _log(self, text: str) -> None:
        self.log_queue.put(text)

    def _parse_units(self, text: str) -> list[int] | None:
        stripped = text.strip()
        if not stripped:
            return None
        return [int(part.strip()) for part in stripped.split(",") if part.strip()]

    def _cfg(self) -> rtu.RtuConfig:
        return rtu.RtuConfig(
            port=self.port_var.get().strip(),
            baudrate=self.baud_var.get(),
            bytesize=self.byte_var.get(),
            parity=self.parity_var.get().strip(),
            stopbits=self.stop_var.get(),
            timeout=self.timeout_var.get(),
            slave=self.slave_var.get(),
        )

    def _run(self, worker) -> None:
        def wrapped() -> None:
            try:
                worker()
            except Exception as exc:  # noqa: BLE001
                self._log(f"ERROR: {exc}")
                self.after(0, lambda: messagebox.showerror("Error", str(exc)))

        threading.Thread(target=wrapped, daemon=True).start()

    def _with_client(self, fn) -> None:
        cfg = self._cfg()
        client = rtu._build_client(cfg)
        try:
            rtu._connect_or_fail(client, cfg.port)
            fn(client, cfg)
        finally:
            client.close()

    def on_ports(self) -> None:
        ports = rtu._list_candidate_ports()
        if ports:
            self._log("Detected serial ports:")
            for port in ports:
                self._log(f"- {port}")
        else:
            self._log("No serial ports detected. Try entering COMx or /dev/ttyUSBx manually.")

    def on_scan(self) -> None:
        def worker() -> None:
            def action(client, cfg):
                found = rtu._scan_units(client, cfg, verbose=self.scan_verbose.get())
                self._log(f"Scan complete: {len(found)} units")

            self._with_client(action)

        self._run(worker)

    def on_status(self) -> None:
        def worker() -> None:
            def action(client, cfg):
                targets = rtu._scan_units(client, cfg, verbose=False) if self.status_all.get() else self._parse_units(self.status_units.get())
                if not targets:
                    raise RuntimeError("No units selected for status")
                self._log("Status:")
                for idx in targets:
                    status = rtu.UnitStatus(rtu._read_input(client, rtu.UnitStatus.ADDRESS + idx * rtu.UnitStatus.COUNT, rtu.UnitStatus.COUNT, cfg.slave))
                    self._log(
                        f"idx={idx:02d} id={rtu._unit_id(idx)} power={status.power} mode={status.operating_mode.name} "
                        f"setpoint={status.temp_setpoint:.1f} room={status.temp_current:.1f} fan={status.fan_speed.name}/{status.fan_direct.name}"
                    )

            self._with_client(action)

        self._run(worker)

    def on_errors(self) -> None:
        def worker() -> None:
            def action(client, cfg):
                targets = rtu._scan_units(client, cfg, verbose=False) if self.error_all.get() else self._parse_units(self.error_units.get())
                if not targets:
                    raise RuntimeError("No units selected for errors")
                self._log("Errors:")
                for idx in targets:
                    err = rtu.UnitError(rtu._read_input(client, rtu.UnitError.ADDRESS + idx * rtu.UnitError.COUNT, rtu.UnitError.COUNT, cfg.slave))
                    if (not self.error_show_clear.get()) and not (err.error or err.alarm or err.warning):
                        continue
                    self._log(
                        f"idx={idx:02d} id={rtu._unit_id(idx)} error={bool(err.error)} alarm={bool(err.alarm)} "
                        f"warning={bool(err.warning)} code={err.error_code} sub={err.error_sub_code}"
                    )

            self._with_client(action)

        self._run(worker)

    def on_control(self) -> None:
        def worker() -> None:
            def action(client, cfg):
                unit = self.ctrl_unit.get()
                holding = rtu.UnitHolding(
                    rtu._read_holding(
                        client,
                        rtu.UnitHolding.ADDRESS + unit * rtu.UnitHolding.COUNT,
                        rtu.UnitHolding.COUNT,
                        cfg.slave,
                    )
                )
                changes: list[str] = []

                power = self.ctrl_power.get().strip()
                if power:
                    holding.power = power == "on"
                    changes.append(f"power={power}")
                mode = self.ctrl_mode.get().strip()
                if mode:
                    holding.operating_mode = rtu._parse_enum(rtu.D3netOperationMode, mode)
                    changes.append(f"mode={mode}")
                setpoint = self.ctrl_setpoint.get().strip()
                if setpoint:
                    holding.temp_setpoint = float(setpoint)
                    changes.append(f"setpoint={setpoint}")
                fan_speed = self.ctrl_fan_speed.get().strip()
                if fan_speed:
                    holding.fan_speed = rtu._parse_enum(rtu.D3netFanSpeed, fan_speed)
                    changes.append(f"fan_speed={fan_speed}")
                fan_dir = self.ctrl_fan_dir.get().strip()
                if fan_dir:
                    holding.fan_direct = rtu._parse_enum(rtu.D3netFanDirection, fan_dir)
                    changes.append(f"fan_direction={fan_dir}")
                if self.ctrl_filter_reset.get():
                    holding.filter_reset = True
                    changes.append("filter_reset=true")

                if not holding.dirty:
                    raise RuntimeError("No control values were set")

                rtu._write_holding(client, rtu.UnitHolding.ADDRESS + unit * rtu.UnitHolding.COUNT, holding.registers, cfg.slave)
                if self.ctrl_filter_reset.get():
                    holding.filter_reset = False
                    if holding.dirty:
                        rtu._write_holding(client, rtu.UnitHolding.ADDRESS + unit * rtu.UnitHolding.COUNT, holding.registers, cfg.slave)

                self._log(f"Control applied to idx={unit:02d}: {', '.join(changes)}")

            self._with_client(action)

        self._run(worker)

    def on_browse_watch(self) -> None:
        file_path = filedialog.asksaveasfilename(title="JSONL output", defaultextension=".jsonl")
        if file_path:
            self.watch_out.set(file_path)

    def on_watch_start(self) -> None:
        self.stop_watch.clear()

        def worker() -> None:
            def action(client, cfg):
                unit = self.watch_unit.get()
                interval = self.watch_interval.get()
                duration = self.watch_duration.get()
                output = Path(self.watch_out.get()) if self.watch_out.get().strip() else None
                started = time.time()
                self._log("Watch started")
                while not self.stop_watch.is_set() and (duration <= 0 or time.time() - started <= duration):
                    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    status = rtu.UnitStatus(
                        rtu._read_input(client, rtu.UnitStatus.ADDRESS + unit * rtu.UnitStatus.COUNT, rtu.UnitStatus.COUNT, cfg.slave)
                    )
                    err = rtu.UnitError(
                        rtu._read_input(client, rtu.UnitError.ADDRESS + unit * rtu.UnitError.COUNT, rtu.UnitError.COUNT, cfg.slave)
                    )
                    row = {
                        "ts": now,
                        "unit_index": unit,
                        "unit_id": rtu._unit_id(unit),
                        "power": status.power,
                        "mode": status.operating_mode.name,
                        "setpoint": status.temp_setpoint,
                        "room_temp": status.temp_current,
                        "fan_speed": status.fan_speed.name,
                        "fan_direction": status.fan_direct.name,
                        "error": bool(err.error),
                        "alarm": bool(err.alarm),
                        "warning": bool(err.warning),
                        "error_code": err.error_code,
                        "error_sub_code": err.error_sub_code,
                    }
                    line = json.dumps(row, separators=(",", ":"))
                    self._log(line)
                    if output:
                        output.parent.mkdir(parents=True, exist_ok=True)
                        with output.open("a", encoding="utf-8") as file_handle:
                            file_handle.write(json.dumps(row) + "\n")
                    self.stop_watch.wait(interval)
                self._log("Watch stopped")

            self._with_client(action)

        self._run(worker)

    def on_watch_stop(self) -> None:
        self.stop_watch.set()


def main() -> int:
    app = D3netGui()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
