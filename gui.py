#!/usr/bin/env python3
"""AudioFix desktop shell (tkinter).

Single mode: pick one audio file -> measure, fix & re-check.
Batch mode: pick multiple files or a whole folder -> every episode is
fixed with the same preset and one batch summary report is written.
"""
import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_fix import run_audiofix, run_batch, PRESETS

AUDIO_FT = [("Audio/video", "*.mp3 *.wav *.m4a *.flac *.ogg *.mp4 *.mov *.mkv"),
            ("All files", "*.*")]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AudioFix — Loudness Fix & Re-Check")
        self.geometry("720x640")
        self.mode = tk.StringVar(value="single")
        self.src = tk.StringVar()
        self.batch_src = tk.StringVar()
        self.batch_files = []       # explicit multi-file selection
        self.batch_folder = ""      # folder selection
        self.preset = tk.StringVar(value="podcast")
        self.trim = tk.BooleanVar(value=True)

        tk.Label(self, text="Mode:").pack(anchor="w", padx=12, pady=(12, 0))
        mrow = tk.Frame(self)
        mrow.pack(anchor="w", padx=12)
        tk.Radiobutton(mrow, text="Single episode", variable=self.mode,
                       value="single").pack(side="left")
        tk.Radiobutton(mrow, text="Batch — a whole season (multiple files or a folder)",
                       variable=self.mode, value="batch").pack(side="left", padx=10)

        tk.Label(self, text="Single: audio or video file (mp3 / wav / m4a / mp4 …):").pack(
            anchor="w", padx=12, pady=(10, 2))
        row = tk.Frame(self)
        row.pack(fill="x", padx=12)
        tk.Entry(row, textvariable=self.src).pack(side="left", fill="x", expand=True)
        tk.Button(row, text="Browse…", command=self.pick).pack(side="left", padx=6)

        tk.Label(self, text="Batch: choose several episode files, or one folder of episodes:").pack(
            anchor="w", padx=12, pady=(10, 2))
        brow = tk.Frame(self)
        brow.pack(fill="x", padx=12)
        tk.Entry(brow, textvariable=self.batch_src).pack(side="left", fill="x", expand=True)
        tk.Button(brow, text="Files…", command=self.pick_files).pack(side="left", padx=(6, 0))
        tk.Button(brow, text="Folder…", command=self.pick_folder).pack(side="left", padx=6)

        tk.Label(self, text="Target preset (applies to every episode in batch mode):").pack(
            anchor="w", padx=12, pady=(10, 0))
        for key, p in PRESETS.items():
            tk.Radiobutton(self, text=f"{p['label']} — {p['I']:.0f} LUFS, peak ≤ {p['TP']:.0f} dB",
                           variable=self.preset, value=key).pack(anchor="w", padx=20)
        tk.Checkbutton(self, text="Trim leading / trailing silence",
                       variable=self.trim).pack(anchor="w", padx=12, pady=(6, 0))
        self.btn = tk.Button(self, text="Measure, Fix & Re-Check", command=self.run, height=2)
        self.btn.pack(pady=12)
        self.log = scrolledtext.ScrolledText(self, wrap="word")
        self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.write("AudioFix measures your episodes' loudness, normalizes them to the\n"
                   "platform target, then re-measures the outputs to prove it.\n"
                   "Batch mode fixes a whole season in one run and writes a single\n"
                   "batch_summary.md with one line per episode plus totals.\n"
                   "Everything runs locally — your audio never leaves this computer.\n")

    def write(self, s):
        self.log.insert("end", s)
        self.log.see("end")

    def pick(self):
        p = filedialog.askopenfilename(filetypes=AUDIO_FT)
        if p:
            self.src.set(p)
            self.mode.set("single")

    def pick_files(self):
        ps = filedialog.askopenfilenames(filetypes=AUDIO_FT)
        if ps:
            self.batch_files = list(ps)
            self.batch_folder = ""
            self.batch_src.set(f"{len(ps)} files selected")
            self.mode.set("batch")

    def pick_folder(self):
        p = filedialog.askdirectory()
        if p:
            self.batch_folder = p
            self.batch_files = []
            self.batch_src.set(p)
            self.mode.set("batch")

    def _batch_inputs(self):
        """Resolve the batch selection to (inputs, default_outdir)."""
        typed = self.batch_src.get().strip()
        if self.batch_files:
            return list(self.batch_files), os.path.join(
                os.path.dirname(self.batch_files[0]), "audiofix_batch_output")
        folder = self.batch_folder or (typed if os.path.isdir(typed) else "")
        if folder:
            return [folder], os.path.join(folder, "audiofix_batch_output")
        if typed and os.path.isfile(typed):
            return [typed], os.path.join(os.path.dirname(typed), "audiofix_batch_output")
        return None, None

    def run(self):
        if self.mode.get() == "batch":
            inputs, _ = self._batch_inputs()
            if not inputs:
                messagebox.showerror(
                    "AudioFix", "Choose episode files or a folder for batch mode first.")
                return
            self.btn.config(state="disabled")
            threading.Thread(target=self._work_batch, args=(inputs,), daemon=True).start()
            return
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

    def _work_batch(self, inputs):
        try:
            _, outdir = self._batch_inputs()
            self.write(f"\nBatch started — {len(inputs)} input(s), "
                       f"preset: {self.preset.get()}\n")
            b = run_batch(inputs, outdir, self.preset.get(), self.trim.get(),
                          progress=lambda s: self.write(s + "\n"))
            for r in b["results"]:
                bi = f"{r['before_I']:.1f}" if r["before_I"] is not None else "—"
                ai = f"{r['after_I']:.1f}" if r["after_I"] is not None else "—"
                self.write(f"{r['file']}: {bi} → {ai} LUFS — {r['status']}\n")
            self.write(f"\nBatch done. Total: {b['total']} episodes — "
                       f"{b['passed']} PASS, {b['failed']} FAIL\n"
                       f"Summary: {b['summary_md']}\nSummary CSV: {b['summary_csv']}\n"
                       f"Output folder: {outdir}\n")
        except Exception as e:
            self.write(f"\nError: {e}\n")
        finally:
            self.btn.config(state="normal")


if __name__ == "__main__":
    App().mainloop()
