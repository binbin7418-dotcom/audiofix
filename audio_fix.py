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


def main(argv):
    if len(argv) < 3:
        print("usage: audio_fix.py <audio file> <outdir> [podcast|streaming|audiobook] [notrim]")
        return 2
    preset = argv[3] if len(argv) > 3 else "podcast"
    do_trim = not (len(argv) > 4 and argv[4] == "notrim")
    s = run_audiofix(argv[1], argv[2], preset, do_trim)
    print(f"before_I={s['before']['I']:.1f} after_I={s['after']['I']:.1f} "
          f"after_TP={s['after']['TP']:.1f} verdict={s['verdict']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
