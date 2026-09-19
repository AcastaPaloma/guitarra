"""Quick arm controller GUI on the Waveshare bus servo adapter.

Talks raw Feetech STS protocol over serial (no lerobot dependency).

Defaults target the ONLY working arm (the tapping/fretting arm, IDs 7-12).
The old pluck arm (5, 6, 1, 2, 7, 3) is out of service — use --port/--ids to
override if it ever comes back. Gripper 12 is deliberately absent from the
defaults: it permanently holds the fingertip tool and is never commanded.

Run:  uv run --with pyserial python app.py
"""
import json
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, simpledialog, ttk

import serial

PORT = "/dev/cu.wchusbserial5B8E1128501"
BAUD = 1_000_000
MOTOR_IDS = [7, 8, 9, 10, 11]  # bottom of the arm to top; gripper 12 never commanded
JOINT_NAMES = {7: "base", 8: "shoulder", 9: "elbow", 10: "wrist_flex", 11: "wrist_roll"}
KEYFRAMES_PATH = Path(__file__).parent / "keyframes_arm2.json"

# STS3215 register addresses
REG_TORQUE_ENABLE = 40
REG_GOAL_BLOCK = 41  # acc(1) goal_pos(2) goal_time(2) goal_speed(2)
REG_TORQUE_LIMIT = 48  # runtime limit, re-clamped to EEPROM max on every torque enable
REG_PRESENT_POS = 56

# Arm-1 quirks (elbow 1's weak EEPROM torque, elbow range cap) no longer apply —
# that arm is out of service. Kept as empty maps so per-motor overrides are easy
# to add back for THIS arm if a joint needs one.
TORQUE_LIMIT_OVERRIDE = {}

MOTOR_RANGE = {}
DEFAULT_RANGE = (0, 4095)

GOTO_ACC = 30
GOTO_SPEED = 600  # conservative speed for slider moves and keyframe playback


class FeetechBus:
    def __init__(self, port, baud):
        self.ser = serial.Serial(port, baud, timeout=0.005)
        self.lock = threading.Lock()

    def close(self):
        self.ser.close()

    def _txrx(self, sid, instr, params, resp_extra=0):
        pkt = bytearray([0xFF, 0xFF, sid, len(params) + 2, instr, *params])
        pkt.append((~sum(pkt[2:])) & 0xFF)
        with self.lock:
            self.ser.reset_input_buffer()
            self.ser.write(pkt)
            self.ser.flush()
            deadline = time.time() + 0.05
            buf = b""
            need = 6 + resp_extra
            while time.time() < deadline:
                buf += self.ser.read(64)
                i = buf.find(b"\xff\xff")
                if i != -1 and len(buf) >= i + need:
                    resp = buf[i:]
                    if resp[2] == sid:
                        return resp[5 : 5 + resp_extra] if resp_extra else b""
        return None

    def ping(self, sid):
        return self._txrx(sid, 0x01, []) is not None

    def read_pos(self, sid):
        data = self._txrx(sid, 0x02, [REG_PRESENT_POS, 2], resp_extra=2)
        if data is None:
            return None
        return data[0] | (data[1] << 8)

    def set_torque(self, sid, on):
        self._txrx(sid, 0x03, [REG_TORQUE_ENABLE, 1 if on else 0])

    def set_torque_limit(self, sid, limit):
        self._txrx(sid, 0x03, [REG_TORQUE_LIMIT, limit & 0xFF, (limit >> 8) & 0xFF])

    def read_torque(self, sid):
        data = self._txrx(sid, 0x02, [REG_TORQUE_ENABLE, 1], resp_extra=1)
        return None if data is None else bool(data[0])

    def goto(self, sid, pos, speed=GOTO_SPEED, acc=GOTO_ACC):
        pos = max(0, min(4095, int(pos)))
        params = [
            REG_GOAL_BLOCK,
            acc,
            pos & 0xFF, (pos >> 8) & 0xFF,
            0, 0,  # goal time unused when speed is set
            speed & 0xFF, (speed >> 8) & 0xFF,
        ]
        self._txrx(sid, 0x03, params)


class App:
    def __init__(self, root):
        self.root = root
        root.title("Arm Controller")
        self.bus = None
        self.torque_on = False
        self.sliders = {}
        self.pos_labels = {}
        self._syncing = False  # True while poll() updates sliders programmatically

        top = ttk.Frame(root, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text=f"Port: {PORT} @ {BAUD}").pack(side="left")
        self.status = ttk.Label(top, text="disconnected", foreground="red")
        self.status.pack(side="right")

        ctrl = ttk.Frame(root, padding=8)
        ctrl.pack(fill="x")
        self.torque_btn = ttk.Button(ctrl, text="Torque ON", command=self.toggle_torque, state="disabled")
        self.torque_btn.pack(side="left")
        self.key_btn = ttk.Button(ctrl, text="★ Keyframe current pose", command=self.save_keyframe, state="disabled")
        self.key_btn.pack(side="left", padx=8)

        joints = ttk.LabelFrame(root, text="Joints (bottom → top)", padding=8)
        joints.pack(fill="x", padx=8)
        for row, sid in enumerate(MOTOR_IDS):
            lo, hi = MOTOR_RANGE.get(sid, DEFAULT_RANGE)
            ttk.Label(joints, text=f"ID {sid} ({JOINT_NAMES[sid]})", width=16).grid(row=row, column=0, sticky="w")
            s = tk.Scale(joints, from_=lo, to=hi, orient="horizontal", length=320, showvalue=False,
                         command=lambda v, sid=sid: self.on_slider(sid, v))
            s.grid(row=row, column=1, padx=6)
            self.sliders[sid] = s
            lbl = ttk.Label(joints, text="----", width=6, cursor="hand2")
            lbl.grid(row=row, column=2)
            lbl.bind("<Button-1>", lambda e, sid=sid, row=row: self.open_jog(sid, row))
            self.pos_labels[sid] = lbl
        self.jog_entry = None
        self.jog_sid = None
        self.joints_frame = joints

        kf = ttk.LabelFrame(root, text="Keyframes", padding=8)
        kf.pack(fill="both", expand=True, padx=8, pady=8)
        self.kf_list = tk.Listbox(kf, height=6, exportselection=False)
        self.kf_list.pack(fill="both", expand=True, side="left")
        btns = ttk.Frame(kf)
        btns.pack(side="left", fill="y", padx=6)
        ttk.Button(btns, text="Go to", command=self.goto_keyframe).pack(fill="x")
        ttk.Button(btns, text="Edit", command=self.edit_keyframe).pack(fill="x", pady=4)
        ttk.Button(btns, text="Delete", command=self.delete_keyframe).pack(fill="x")

        self.keyframes = self.load_keyframes()
        self.refresh_kf_list()
        self.connect()
        self.poll()
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    def connect(self):
        try:
            self.bus = FeetechBus(PORT, BAUD)
        except serial.SerialException as e:
            messagebox.showerror("Serial", f"Could not open {PORT}:\n{e}")
            return
        alive = [sid for sid in MOTOR_IDS if self.bus.ping(sid)]
        if len(alive) == len(MOTOR_IDS):
            self.status.config(text=f"connected, all {len(alive)} motors OK", foreground="green")
        else:
            missing = [sid for sid in MOTOR_IDS if sid not in alive]
            self.status.config(text=f"connected, MISSING {missing}", foreground="orange")
        self.torque_btn.config(state="normal")
        self.key_btn.config(state="normal")
        # reflect the servos' actual torque state (may be ON if a previous run was killed)
        self.torque_on = all(self.bus.read_torque(sid) for sid in alive) if alive else False
        self.torque_btn.config(text="Torque OFF" if self.torque_on else "Torque ON")
        if self.torque_on:
            for sid, limit in TORQUE_LIMIT_OVERRIDE.items():
                self.bus.set_torque_limit(sid, limit)
        # seed sliders with real positions so the first slider touch can't command a jump
        self._syncing = True
        for sid in alive:
            pos = self.bus.read_pos(sid)
            if pos is not None:
                self.sliders[sid].set(pos)
        self._syncing = False

    def toggle_torque(self):
        self.torque_on = not self.torque_on
        for sid in MOTOR_IDS:
            self.bus.set_torque(sid, self.torque_on)
        if self.torque_on:
            for sid, limit in TORQUE_LIMIT_OVERRIDE.items():
                self.bus.set_torque_limit(sid, limit)
        self.torque_btn.config(text="Torque OFF" if self.torque_on else "Torque ON")

    def on_slider(self, sid, value):
        if self._syncing or not self.bus:
            return
        if not self.torque_on:
            # RC mode: touching a slider takes control of the arm
            self.toggle_torque()
        self.bus.goto(sid, int(float(value)))

    def poll(self):
        if self.bus:
            for sid in MOTOR_IDS:
                pos = self.bus.read_pos(sid)
                if pos is not None:
                    self.pos_labels[sid].config(text=str(pos))
                    if not self.torque_on:
                        # hand-posing mode: sliders follow the arm
                        self._syncing = True
                        self.sliders[sid].set(pos)
                        self._syncing = False
        self.root.after(100, self.poll)

    JOG_FINE = 1
    JOG_COARSE = 25

    def open_jog(self, sid, row):
        """Click a joint's value -> entry box; arrows jog the motor live."""
        self.close_jog()
        pos = self.bus.read_pos(sid) if self.bus else None
        if pos is None:
            return
        e = ttk.Entry(self.joints_frame, width=6)
        e.grid(row=row, column=3, padx=4)
        e.insert(0, str(pos))
        e.select_range(0, "end")
        e.focus_set()
        self.jog_entry, self.jog_sid = e, sid
        for keys, delta in (
            (("<Left>",), -self.JOG_FINE),
            (("<Right>",), self.JOG_FINE),
            (("<Shift-Left>", "<Down>"), -self.JOG_COARSE),
            (("<Shift-Right>", "<Up>"), self.JOG_COARSE),
        ):
            for k in keys:
                e.bind(k, lambda ev, d=delta: self.jog(d))
        e.bind("<Return>", lambda ev: self.jog(0))
        e.bind("<Escape>", lambda ev: self.close_jog())

    def jog(self, delta):
        e, sid = self.jog_entry, self.jog_sid
        if e is None or not self.bus:
            return "break"
        try:
            target = int(e.get())
        except ValueError:
            target = self.bus.read_pos(sid) or 0
        lo, hi = MOTOR_RANGE.get(sid, DEFAULT_RANGE)
        target = max(lo, min(hi, target + delta))
        e.delete(0, "end")
        e.insert(0, str(target))
        if not self.torque_on:
            self.toggle_torque()
        self.bus.goto(sid, target)
        self._syncing = True
        self.sliders[sid].set(target)
        self._syncing = False
        return "break"

    def close_jog(self):
        if self.jog_entry is not None:
            self.jog_entry.destroy()
            self.jog_entry, self.jog_sid = None, None

    def current_pose(self):
        pose = {}
        for sid in MOTOR_IDS:
            pos = self.bus.read_pos(sid)
            if pos is None:
                raise RuntimeError(f"Motor {sid} did not answer a position read")
            pose[str(sid)] = pos
        return pose

    def save_keyframe(self):
        try:
            pose = self.current_pose()
        except RuntimeError as e:
            messagebox.showerror("Keyframe", str(e))
            return
        name = simpledialog.askstring("Keyframe", "Name for this pose:",
                                      initialvalue=f"pose_{len(self.keyframes) + 1}")
        if not name:
            return
        self.keyframes.append({"name": name, "time": datetime.now().isoformat(timespec="seconds"),
                               "positions": pose})
        KEYFRAMES_PATH.write_text(json.dumps(self.keyframes, indent=2))
        self.refresh_kf_list()

    def goto_keyframe(self):
        if not self.bus:
            return
        sel = self.kf_list.curselection()
        if not sel:
            messagebox.showinfo("Keyframe", "Select a keyframe in the list first.")
            return
        if not self.torque_on:
            messagebox.showinfo("Keyframe", "Turn torque ON first.")
            return
        kf = self.keyframes[sel[0]]
        clamped = []
        targets = {}
        for sid_str, pos in kf["positions"].items():
            sid = int(sid_str)
            lo, hi = MOTOR_RANGE.get(sid, DEFAULT_RANGE)
            safe = max(lo, min(hi, pos))
            if safe != pos:
                clamped.append(f"ID {sid}: {pos} -> {safe}")
            targets[sid] = safe
        # shoulder (6) goes LAST so it lands into an already-positioned arm —
        # except for "neutral" keyframes, where the shoulder leads instead
        shoulder = {6: targets.pop(6)} if 6 in targets else {}
        if "neutral" in kf["name"].lower():
            first, second = shoulder, targets
        else:
            first, second = targets, shoulder
        self._send_targets(first)
        if second:
            self._await_settle(dict(first), second, time.time() + 4.0)
        if clamped:
            messagebox.showwarning("Keyframe", "Clamped to safe range:\n" + "\n".join(clamped))
        self.status.config(text=f"moving to '{self.keyframes[sel[0]]['name']}'", foreground="blue")

    def edit_keyframe(self):
        sel = self.kf_list.curselection()
        if not sel:
            messagebox.showinfo("Keyframe", "Select a keyframe in the list first.")
            return
        idx = sel[0]
        kf = self.keyframes[idx]

        win = tk.Toplevel(self.root)
        win.title(f"Edit: {kf['name']}")
        win.transient(self.root)
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="Name").grid(row=0, column=0, sticky="w")
        name_e = ttk.Entry(frm, width=18)
        name_e.grid(row=0, column=1, pady=(0, 8))
        name_e.insert(0, kf["name"])

        entries = {}
        for row, sid in enumerate(MOTOR_IDS, start=1):
            lo, hi = MOTOR_RANGE.get(sid, DEFAULT_RANGE)
            ttk.Label(frm, text=f"ID {sid} ({JOINT_NAMES[sid]})  [{lo}-{hi}]").grid(row=row, column=0, sticky="w")
            e = ttk.Entry(frm, width=8)
            e.grid(row=row, column=1, pady=1)
            e.insert(0, str(kf["positions"].get(str(sid), "")))
            entries[sid] = e

        def save():
            new_pos = {}
            for sid, e in entries.items():
                raw = e.get().strip()
                if raw == "":
                    continue  # joint absent from this keyframe stays absent
                try:
                    val = int(raw)
                except ValueError:
                    messagebox.showerror("Edit", f"ID {sid}: '{raw}' is not a number", parent=win)
                    return
                lo, hi = MOTOR_RANGE.get(sid, DEFAULT_RANGE)
                new_pos[str(sid)] = max(lo, min(hi, val))
            kf["name"] = name_e.get().strip() or kf["name"]
            kf["positions"] = new_pos
            KEYFRAMES_PATH.write_text(json.dumps(self.keyframes, indent=2))
            self.refresh_kf_list()
            self.kf_list.selection_set(idx)
            win.destroy()

        bar = ttk.Frame(frm)
        bar.grid(row=len(MOTOR_IDS) + 1, column=0, columnspan=2, pady=(10, 0))
        ttk.Button(bar, text="Save", command=save).pack(side="left", padx=4)
        ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="left")
        win.bind("<Return>", lambda ev: save())
        win.bind("<Escape>", lambda ev: win.destroy())
        name_e.focus_set()

    def _send_targets(self, targets):
        self._syncing = True
        for sid, pos in targets.items():
            self.bus.goto(sid, pos)
            self.sliders[sid].set(pos)
        self._syncing = False

    def _await_settle(self, watch, next_targets, deadline):
        """Poll until watched joints are near target (or timeout), then send the next group."""
        settled = all(
            (pos := self.bus.read_pos(sid)) is not None and abs(pos - tgt) <= 25
            for sid, tgt in watch.items()
        )
        if settled or time.time() > deadline:
            self._send_targets(next_targets)
            note = "" if settled else " (timeout — continued anyway)"
            self.status.config(text=f"final stage moving{note}", foreground="blue")
        else:
            self.root.after(120, lambda: self._await_settle(watch, next_targets, deadline))

    def delete_keyframe(self):
        sel = self.kf_list.curselection()
        if not sel:
            return
        del self.keyframes[sel[0]]
        KEYFRAMES_PATH.write_text(json.dumps(self.keyframes, indent=2))
        self.refresh_kf_list()

    def load_keyframes(self):
        if KEYFRAMES_PATH.exists():
            return json.loads(KEYFRAMES_PATH.read_text())
        return []

    def refresh_kf_list(self):
        self.kf_list.delete(0, "end")
        for k in self.keyframes:
            self.kf_list.insert("end", f"{k['name']}  ({k['time']})")

    def on_close(self):
        if self.bus:
            if self.torque_on:
                for sid in MOTOR_IDS:
                    self.bus.set_torque(sid, False)
            self.bus.close()
        self.root.destroy()


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Feetech bus arm controller")
    ap.add_argument("--port", default=PORT)
    ap.add_argument("--ids", default=",".join(map(str, MOTOR_IDS)), help="motor IDs, bottom to top")
    ap.add_argument("--names", default=None, help="joint names matching --ids order")
    ap.add_argument("--keyframes", default=None, help="keyframes json path")
    ap.add_argument("--title", default="Arm Controller")
    a = ap.parse_args()

    PORT = a.port
    MOTOR_IDS = [int(x) for x in a.ids.split(",")]
    if a.names:
        JOINT_NAMES = dict(zip(MOTOR_IDS, a.names.split(",")))
    else:
        JOINT_NAMES = {sid: JOINT_NAMES.get(sid, f"joint{sid}") for sid in MOTOR_IDS}
    if a.keyframes:
        p = Path(a.keyframes)
        KEYFRAMES_PATH = p if p.is_absolute() else Path(__file__).parent / p

    root = tk.Tk()
    App(root)
    root.title(a.title)
    root.mainloop()
