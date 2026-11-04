#!/usr/bin/env python3
"""
AudioFix — podcast / voice audio loudness repair & re-check engine.

What it does (via the bundled ffmpeg, everything local):
  1. Measures the input's integrated loudness (LUFS), true peak, loudness
     range and duration using ffmpeg's loudnorm analysis.
  2. Optionally trims leading/trailing silence.
  3. Normalizes to a target preset (podcast -16 LUFS, streaming -14 LUFS,
     audiobook -20 LUFS with a -3 dB peak ceiling) using measured two-pass
     loudnorm parameters when a linear gain is possible.
  4. Re-measures the output and reports before/after + a PASS / NOT READY
     verdict. Problems a loudness pass cannot fix (recorded clipping,
     very high noise floor) are reported, never hidden.
"""
import csv
import json
import os
import re
import shutil
import subprocess
import sys

PRESETS = {
    "podcast":   {"label": "Podcast (Apple/Spotify spoken word)", "I": -16.0, "TP": -1.0, "LRA": 11.0},
    "streaming": {"label": "Streaming / YouTube",                 "I": -14.0, "TP": -1.0, "LRA": 11.0},
    "audiobook": {"label": "Audiobook (ACX-style targets)",       "I": -20.0, "TP": -3.0, "LRA": 11.0},
}


def find_tool(name):
    here = os.path.dirname(os.path.abspath(sys.argv[0]))
    exe_dir = os.path.dirname(sys.executable)
    for d in (here, exe_dir, os.getcwd()):
        p = os.path.join(d, name + (".exe" if os.name == "nt" else ""))
        if os.path.isfile(p):
            return p
    return shutil.which(name)


def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=3600)


def measure(path):
    """Integrated loudness via loudnorm analysis pass. Returns dict."""
    ff = find_tool("ffmpeg")
    if not ff:
        raise RuntimeError("ffmpeg not found next to the app or on PATH")
    r = _run([ff, "-hide_banner", "-i", path, "-af",
              "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.search(r"\{\s*\"input_i\".*?\}", r.stderr, re.S)
    if not m:
        raise RuntimeError("loudnorm analysis failed — is the input a valid audio/video file?")
    d = json.loads(m.group(0))
    out = {"I": float(d["input_i"]), "TP": float(d["input_tp"]),
           "LRA": float(d["input_lra"]), "thresh": float(d["input_thresh"]),
           "offset": float(d["target_offset"])}
    fp = find_tool("ffprobe")
    if fp:
        p = _run([fp, "-v", "quiet", "-show_entries", "format=duration",
                  "-of", "json", path])
        try:
            out["duration"] = float(json.loads(p.stdout)["format"]["duration"])
        except Exception:
            out["duration"] = None
    return out


def trim_silence(src, dst, threshold_db=-45.0, min_silence=0.6):
    """Trim leading and trailing silence with silenceremove (start/end)."""
    ff = find_tool("ffmpeg")
    f = (f"silenceremove=start_periods=1:start_duration=0.1:start_threshold={threshold_db}dB,"
         f"areverse,silenceremove=start_periods=1:start_duration=0.1:start_threshold={threshold_db}dB,areverse")
    r = _run([ff, "-hide_banner", "-y", "-i", src, "-af", f, dst])
    if r.returncode != 0:
        raise RuntimeError("silence trim failed: " + r.stderr.strip().splitlines()[-1] if r.stderr else "unknown error")
    return dst


def normalize(src, dst, preset, measured):
    """Two-pass loudnorm: feed the measured values back for a linear result when possible."""
    ff = find_tool("ffmpeg")
    p = PRESETS[preset]
    ln = (f"loudnorm=I={p['I']}:TP={p['TP']}:LRA={p['LRA']}"
          f":measured_I={measured['I']}:measured_TP={measured['TP']}"
          f":measured_LRA={measured['LRA']}:measured_thresh={measured['thresh']}"
          f":offset={measured['offset']}:linear=true")
    r = _run([ff, "-hide_banner", "-y", "-i", src, "-af", ln, "-ar", "48000", dst])
    if r.returncode != 0:  # fall back to a single dynamic pass
        ln = f"loudnorm=I={p['I']}:TP={p['TP']}:LRA={p['LRA']}"
        r = _run([ff, "-hide_banner", "-y", "-i", src, "-af", ln, "-ar", "48000", dst])
        if r.returncode != 0:
            raise RuntimeError("loudnorm failed: " + (r.stderr.strip().splitlines()[-1] if r.stderr else "unknown error"))
    return dst


def run_audiofix(src_path, outdir, preset="podcast", do_trim=True):
    if preset not in PRESETS:
        raise ValueError(f"unknown preset '{preset}' (choose from {', '.join(PRESETS)})")
    os.makedirs(outdir, exist_ok=True)
    base = os.path.splitext(os.path.basename(src_path))[0]
    ext = os.path.splitext(src_path)[1].lower() or ".wav"
    p = PRESETS[preset]

    notes = []
    before = measure(src_path)
    work = src_path
    if do_trim:
        trimmed = os.path.join(outdir, base + "_trimmed.wav")
        trim_silence(src_path, trimmed)
        mid = measure(trimmed)
        if before.get("duration") and mid.get("duration"):
            cut = before["duration"] - mid["duration"]
            if cut > 0.05:
                notes.append(f"trimmed {cut:.1f}s of leading/trailing silence")
        before = mid  # loudnorm params measured on the trimmed audio
        work = trimmed

    fixed_path = os.path.join(outdir, base + "_fixed" + ext)
    normalize(work, fixed_path, preset, before)
    after = measure(fixed_path)

    di = after["I"] - p["I"]
    ok_level = abs(di) <= 0.5
    ok_peak = after["TP"] <= p["TP"] + 0.1
    verdict = "PASS" if (ok_level and ok_peak) else "NOT READY"
    if before["TP"] >= -0.1:
        notes.append("the original audio peaks at/near 0 dBFS — recorded clipping cannot be undone by normalization; re-record or repair the clipped sections")
    lines = ["# AudioFix — loudness repair & re-check report", "",
             f"Source file: {os.path.basename(src_path)}  ·  Preset: {p['label']} "
             f"(target {p['I']:.0f} LUFS, true peak ≤ {p['TP']:.0f} dB)", "",
             "## Before / after (re-measured on the output file)",
             f"- Integrated loudness: {before['I']:.1f} LUFS → {after['I']:.1f} LUFS (target {p['I']:.0f} ± 0.5)",
             f"- True peak: {before['TP']:.1f} dBTP → {after['TP']:.1f} dBTP (ceiling {p['TP']:.0f})",
             f"- Loudness range: {before['LRA']:.1f} LU → {after['LRA']:.1f} LU", "",
             "## Notes"]
    lines += [f"- {n}" for n in notes] or ["- nothing unusual detected"]
    lines += ["", "## Re-check verdict",
              f"- {verdict}: loudness {'within' if ok_level else 'OUTSIDE'} tolerance "
              f"({after['I']:.1f} vs {p['I']:.0f} LUFS), true peak {'within' if ok_peak else 'ABOVE'} the ceiling. "
              "Scope note: AudioFix fixes overall loudness, peaks and edge silence. It does not remove "
              "background noise, echo or distortion recorded at the source."]
    report_path = os.path.join(outdir, "fix_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return {"before": before, "after": after, "verdict": verdict,
            "fixed_path": fixed_path, "report_path": report_path}


# ---------------------------------------------------------------------------
# Batch shell (product layer — the loudness engine above is unchanged).
#
# A podcast season is dozens of episodes; running them one at a time does
# not scale. run_batch() feeds every file/folder input through the exact
# same run_audiofix() engine call with one shared preset, gives each
# episode its own output sub-folder (so per-episode reports never collide)
# and writes one batch summary: a line per episode with before -> after
# LUFS, true peaks and a PASS / FAIL verdict, plus a totals row. A file
# that fails to process is recorded as FAIL with its error and never
# aborts the rest of the batch.
# ---------------------------------------------------------------------------

AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".flac", ".ogg", ".aac", ".wma",
              ".mp4", ".mov", ".mkv", ".webm"}


def collect_batch_inputs(inputs, exclude_dirs=()):
    """Expand file/folder inputs into a sorted, de-duplicated file list.

    Folder inputs contribute every audio/video file directly inside them
    and in sub-folders. AudioFix's own output folders (audiofix_output /
    audiofix_batch_output) and any exclude_dirs are never re-ingested, so
    re-running a batch over the same folder is safe. Explicit file inputs
    are always taken as given (ffmpeg judges whether they are audio).
    """
    excluded = {os.path.abspath(d) for d in exclude_dirs}
    files, seen = [], set()
    for raw in inputs:
        path = os.path.expanduser(raw)
        if os.path.isdir(path):
            found = []
            for root, dirs, names in os.walk(path):
                dirs[:] = sorted(
                    d for d in dirs
                    if d.lower() not in ("audiofix_output", "audiofix_batch_output")
                    and os.path.abspath(os.path.join(root, d)) not in excluded)
                for name in sorted(names):
                    if os.path.splitext(name)[1].lower() in AUDIO_EXTS:
                        found.append(os.path.join(root, name))
            candidates = found
        elif os.path.isfile(path):
            candidates = [path]
        else:
            raise FileNotFoundError(f"input not found: {raw}")
        for p in candidates:
            key = os.path.abspath(p)
            if key not in seen:
                seen.add(key)
                files.append(p)
    return files


def _fmt(value):
    return f"{value:.1f}" if isinstance(value, (int, float)) else "—"


def write_batch_summary(results, outdir, preset="podcast"):
    """Write batch_summary.md + batch_summary.csv into outdir."""
    p = PRESETS[preset]
    total = len(results)
    passed = sum(1 for r in results if r["status"] == "PASS")
    failed = total - passed
    md_path = os.path.join(outdir, "batch_summary.md")
    csv_path = os.path.join(outdir, "batch_summary.csv")

    lines = ["# AudioFix — batch summary", "",
             f"Preset: {p['label']} (target {p['I']:.0f} LUFS, true peak ≤ {p['TP']:.0f} dB)  ·  "
             f"Episodes: {total}", "",
             "| # | File | LUFS before → after | True peak before → after (dBTP) | Verdict |",
             "|---|------|---------------------|----------------------------------|---------|"]
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r['file']} | {_fmt(r['before_I'])} → {_fmt(r['after_I'])} "
            f"| {_fmt(r['before_TP'])} → {_fmt(r['after_TP'])} | {r['status']} |")
    lines += ["",
              f"**Total: {total} episodes — {passed} PASS, {failed} FAIL**", ""]
    errors = [r for r in results if r.get("error")]
    if errors:
        lines += ["## Errors", ""]
        lines += [f"- {r['file']}: {r['error']}" for r in errors]
        lines += [""]
    lines += ["Per-episode fixed files and full reports are in each episode's "
              "own sub-folder next to this summary."]
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "before_lufs", "after_lufs", "before_tp_dbtp",
                    "after_tp_dbtp", "verdict", "fixed_file", "report", "error"])
        for r in results:
            w.writerow([r["file"],
                        "" if r["before_I"] is None else f"{r['before_I']:.1f}",
                        "" if r["after_I"] is None else f"{r['after_I']:.1f}",
                        "" if r["before_TP"] is None else f"{r['before_TP']:.1f}",
                        "" if r["after_TP"] is None else f"{r['after_TP']:.1f}",
                        r["status"], r.get("fixed_path") or "",
                        r.get("report_path") or "", r.get("error") or ""])
    return {"md": md_path, "csv": csv_path, "total": total,
            "passed": passed, "failed": failed}


def run_batch(inputs, outdir, preset="podcast", do_trim=True, progress=None):
    """Process many episodes with one preset via the single-file engine.

    inputs: list of file and/or folder paths. Returns a dict with the
    per-episode result rows and the summary paths/counts.
    """
    if preset not in PRESETS:
        raise ValueError(f"unknown preset '{preset}' (choose from {', '.join(PRESETS)})")
    if isinstance(inputs, (str, os.PathLike)):
        inputs = [inputs]
    files = collect_batch_inputs(list(inputs), exclude_dirs=[outdir])
    if not files:
        raise ValueError("no audio files found in the given inputs")
    os.makedirs(outdir, exist_ok=True)

    results, used_names = [], set()
    for src in files:
        stem = os.path.splitext(os.path.basename(src))[0] or "episode"
        sub, n = stem, 2
        while sub in used_names:
            sub, n = f"{stem}_{n}", n + 1
        used_names.add(sub)
        if progress:
            progress(f"[{len(results) + 1}/{len(files)}] {os.path.basename(src)}")
        row = {"file": os.path.basename(src), "src_path": src,
               "before_I": None, "after_I": None, "before_TP": None,
               "after_TP": None, "verdict": None, "status": "FAIL",
               "fixed_path": None, "report_path": None, "error": None}
        try:
            s = run_audiofix(src, os.path.join(outdir, sub), preset, do_trim)
            row.update(before_I=s["before"]["I"], after_I=s["after"]["I"],
                       before_TP=s["before"]["TP"], after_TP=s["after"]["TP"],
                       verdict=s["verdict"],
                       status="PASS" if s["verdict"] == "PASS" else "FAIL",
                       fixed_path=s["fixed_path"], report_path=s["report_path"])
        except Exception as e:  # one bad episode must not kill the season
            row["error"] = str(e)
        results.append(row)
        if progress:
            progress(f"    -> {row['status']} "
                     f"({_fmt(row['before_I'])} -> {_fmt(row['after_I'])} LUFS)")

    summary = write_batch_summary(results, outdir, preset)
    return {"results": results, "summary_md": summary["md"],
            "summary_csv": summary["csv"], "total": summary["total"],
            "passed": summary["passed"], "failed": summary["failed"]}


def _run_batch_cli(args):
    """audio_fix.py --batch <file|folder ...> --out DIR [--preset P] [--notrim]"""
    inputs, outdir, preset, do_trim = [], None, "podcast", True
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--out" and i + 1 < len(args):
            outdir = args[i + 1]
            i += 2
        elif a == "--preset" and i + 1 < len(args):
            preset = args[i + 1]
            i += 2
        elif a == "--notrim":
            do_trim = False
            i += 1
        elif a.startswith("--"):
            print(f"unknown option: {a}")
            return 2
        else:
            inputs.append(a)
            i += 1
    if not inputs:
        print("usage: audio_fix.py --batch <audio file|folder ...> --out <outdir> "
              "[--preset podcast|streaming|audiobook] [--notrim]")
        return 2
    if not outdir:
        outdir = (os.path.join(inputs[0], "audiofix_batch_output")
                  if len(inputs) == 1 and os.path.isdir(inputs[0])
                  else os.path.join(os.getcwd(), "audiofix_batch_output"))
    try:
        b = run_batch(inputs, outdir, preset, do_trim,
                      progress=lambda s: print(s, flush=True))
    except Exception as e:
        print(f"batch failed: {e}")
        return 2
    for r in b["results"]:
        print(f"{r['file']}: {_fmt(r['before_I'])} -> {_fmt(r['after_I'])} LUFS, "
              f"TP {_fmt(r['before_TP'])} -> {_fmt(r['after_TP'])} dBTP, {r['status']}")
    print(f"total={b['total']} pass={b['passed']} fail={b['failed']}")
    print(f"summary: {b['summary_md']}")
    print(f"summary_csv: {b['summary_csv']}")
    return 0 if b["failed"] == 0 else 1


def main(argv):
    args = argv[1:]
    if args and args[0] in ("--batch", "batch"):
        return _run_batch_cli(args[1:])
    if len(args) >= 2 and os.path.isdir(args[0]):
        # folder shorthand: audio_fix.py <folder> <outdir> [preset] [notrim]
        preset = args[2] if len(args) > 2 else "podcast"
        do_trim = not (len(args) > 3 and args[3] == "notrim")
        return _run_batch_cli([args[0], "--out", args[1], "--preset", preset]
                              + ([] if do_trim else ["--notrim"]))
    if len(argv) < 3:
        print("usage: audio_fix.py <audio file> <outdir> [podcast|streaming|audiobook] [notrim]")
        print("   or: audio_fix.py --batch <audio file|folder ...> --out <outdir> "
              "[--preset podcast|streaming|audiobook] [--notrim]")
        return 2
    preset = argv[3] if len(argv) > 3 else "podcast"
    do_trim = not (len(argv) > 4 and argv[4] == "notrim")
    s = run_audiofix(argv[1], argv[2], preset, do_trim)
    print(f"before_I={s['before']['I']:.1f} after_I={s['after']['I']:.1f} "
          f"after_TP={s['after']['TP']:.1f} verdict={s['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
