#!/usr/bin/env python3
"""AudioFix desktop shell (tkinter). Pick an audio file -> measure, fix & re-check."""
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_fix import run_audiofix, PRESETS


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AudioFix — Loudness Fix & Re-Check")
        self.geometry("680x540")
        self.src = tk.StringVar()
        self.preset = tk.StringVar(value="podcast")
        self.trim = tk.BooleanVar(value=True)
        tk.Label(self, text="Audio or video file (mp3 / wav / m4a / mp4 …):").pack(anchor="w", padx=12, pady=(12, 2))
        row = tk.Frame(self)
        row.pack(fill="x", padx=12)
        tk.Entry(row, textvariable=self.src).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Browse…", command=self.pick).pack(side="left", padx=6)
        tk.Label(self, text="Target preset:").pack(anchor="w", padx=12, pady=(10, 0))
        for key, p in PRESETS.items():
            tk.Radiobutton(self, text=f"{p['label']} — {p['I']:.0f} LUFS, peak ≤ {p['TP']:.0f} dB",
                           variable=self.preset, value=key).pack(anchor="w", padx=20)
        tk.Checkbutton(self, text="Trim leading / trailing silence",
                       variable=self.trim).pack(anchor="w", padx=12, pady=(6, 0))
        self.btn = tk.Button(self, text="Measure, Fix & Re-Check", command=self.run, height=2)
        self.btn.pack(pady=12)
        self.log = scrolledtext.ScrolledText(self, wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.write("AudioFix measures your episode's loudness, normalizes it to the\n"
                   "platform target, then re-measures the output to prove it.\n"
                   "Everything runs locally — your audio never leaves this computer.\n")

    def write(self, s):
        self.log.insert("end", s)
        self.log.see("end")

    def pick(self):
        p = filedialog.askopenfilename(
            filetypes=[("Audio/video", "*.mp3 *.wav *.m4a *.flac *.ogg *.mp4 *.mov *.mkv"), ("All files", "*.*")])
        if p:
            self.src.set(p)

    def run(self):
        src = self.src.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showerror("AudioFix", "Choose an audio file first.")
            return
        self.btn.config(state="disabled")
        threading.Thread(target=self._work, args=(src,), daemon=True).start()

    def _work(self, src):
        try:
            outdir = os.path.join(os.path.dirname(src), "audiofix_output")
            s = run_audiofix(src, outdir, self.preset.get(), self.trim.get())
            b, a = s["before"], s["after"]
            self.write(f"\nDone. Loudness: {b['I']:.1f} LUFS → {a['I']:.1f} LUFS · "
                       f"true peak: {b['TP']:.1f} → {a['TP']:.1f} dBTP\n"
                       f"Fixed file: {s['fixed_path']}\nReport: {s['report_path']}\n"
                       f"Verdict: {s['verdict']}\n")
        except Exception as e:
            self.write(f"\nError: {e}\n")
        finally:
            self.btn.config(state="normal")


if __name__ == "__main__":
    App().mainloop()
