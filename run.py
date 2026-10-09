#!/usr/bin/env python3
"""
Scrcpy Webcam GUI
Minimal Tkinter wrapper to start/stop an Android phone as a v4l2 webcam
via scrcpy, on Fedora with v4l2loopback already configured to load at boot.
"""

import subprocess
import threading
import tkinter as tk
from tkinter import scrolledtext

# ────────────────────────────────────────────────────────| Config |──
V4L2_DEVICE = "/dev/video0"
CAMERA_SIZE = "1920x1080"
CARD_LABEL = "Android Webcam"
SCRCPY_ARGS = [
    "scrcpy",
    f"--v4l2-sink={V4L2_DEVICE}",
    "--no-video-playback",
    "--video-source=camera",
    f"--camera-size={CAMERA_SIZE}",
    "--no-audio",
]


# ────────────────────────────────────────────────| Module check |──
def is_module_loaded():
    result = subprocess.run(["lsmod"], capture_output=True, text=True)
    return "v4l2loopback" in result.stdout


def load_module():
    """Load v4l2loopback via pkexec, prompting the user for auth."""
    return subprocess.run(
        [
            "pkexec",
            "modprobe",
            "v4l2loopback",
            "exclusive_caps=1",
            f"card_label={CARD_LABEL}",
        ],
        capture_output=True,
        text=True,
    )


# ────────────────────────────────────────────────────────| App |──
class ScrcpyWebcamApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Scrcpy Webcam")
        self.root.geometry("480x320")
        self.process = None

        self.status_var = tk.StringVar(value="Stopped")

        status_label = tk.Label(
            root, textvariable=self.status_var, font=("Sans", 12, "bold")
        )
        status_label.pack(pady=(10, 0))

        button_frame = tk.Frame(root)
        button_frame.pack(pady=10)

        self.start_button = tk.Button(
            button_frame, text="Start", width=12, command=self.start
        )
        self.start_button.grid(row=0, column=0, padx=5)

        self.stop_button = tk.Button(
            button_frame,
            text="Stop",
            width=12,
            command=self.stop,
            state=tk.DISABLED,
        )
        self.stop_button.grid(row=0, column=1, padx=5)

        self.log_box = scrolledtext.ScrolledText(
            root, height=12, state=tk.DISABLED, wrap=tk.WORD
        )
        self.log_box.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ────────────────────────────────────────────────| Logging |──
    def log(self, message):
        self.log_box.configure(state=tk.NORMAL)
        self.log_box.insert(tk.END, message + "\n")
        self.log_box.see(tk.END)
        self.log_box.configure(state=tk.DISABLED)

    # ────────────────────────────────────────────| Start / Stop |──
    def start(self):
        if self.process is not None:
            return

        self.start_button.configure(state=tk.DISABLED)

        if not is_module_loaded():
            self.log("v4l2loopback not loaded, requesting authentication...")
            self.status_var.set("Loading module...")
            result = load_module()
            if result.returncode != 0:
                self.log(
                    f"Failed to load v4l2loopback: {result.stderr.strip()}"
                )
                self.status_var.set("Stopped")
                self.start_button.configure(state=tk.NORMAL)
                return
            self.log("v4l2loopback loaded.")
        else:
            self.log("v4l2loopback already loaded.")

        self.log("Starting scrcpy...")
        self.status_var.set("Starting...")

        try:
            self.process = subprocess.Popen(
                SCRCPY_ARGS,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError:
            self.log("scrcpy not found. Is it installed and on PATH?")
            self.status_var.set("Stopped")
            self.start_button.configure(state=tk.NORMAL)
            self.process = None
            return

        self.stop_button.configure(state=tk.NORMAL)
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self):
        for line in self.process.stdout:
            self.log(line.rstrip())
            if "v4l2 sink started" in line:
                self.status_var.set("Running")

        # Process ended, either stopped manually or crashed
        return_code = self.process.wait()
        if return_code != 0:
            self.log(f"scrcpy exited with code {return_code}")
        self.status_var.set("Stopped")
        self.start_button.configure(state=tk.NORMAL)
        self.stop_button.configure(state=tk.DISABLED)
        self.process = None

    def stop(self):
        if self.process is None:
            return
        self.log("Stopping scrcpy...")
        self.process.terminate()
        self.stop_button.configure(state=tk.DISABLED)

    def on_close(self):
        self.stop()
        self.root.destroy()


# ────────────────────────────────────────────────────────| Main |──
def main():
    root = tk.Tk()
    ScrcpyWebcamApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
