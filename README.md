# AudioFix — Podcast & Voice Loudness Fix & Re-Check

AudioFix measures your episode's loudness with ffmpeg's loudnorm analysis,
normalizes it to the platform target, then **re-measures the output file**
and reports before/after numbers with a plain verdict. 100% local — your
audio never leaves your computer.

## Presets
- **Podcast** — −16 LUFS integrated, true peak ≤ −1 dB (Apple/Spotify spoken-word)
- **Streaming / YouTube** — −14 LUFS, true peak ≤ −1 dB
- **Audiobook (ACX-style)** — −20 LUFS, true peak ≤ −3 dB

## What it does
- Two-pass loudnorm normalization using the measured values of *your* file
- Optional leading/trailing silence trim
- Re-check on the finished file: loudness within ±0.5 LUFS and peak under the
  ceiling, or a NOT READY verdict saying exactly which one failed
- Honest reporting: recorded clipping (peaks already at 0 dBFS) is flagged —
  normalization cannot undo it and AudioFix will not pretend otherwise

## Verified behaviour
On a seeded test recording (8 s: 2 s silence + quiet tone + 2 s silence,
integrated loudness −29.9 LUFS), AudioFix trimmed 4.2 s of edge silence and
normalized the output to −15.9 LUFS against the −16 LUFS podcast target —
re-measured on the output file, verdict PASS.

## Batch mode — fix a whole season in one run
One episode at a time does not scale to a season. Batch mode runs every
episode through the same engine with **one shared preset**:

- **GUI:** choose "Batch" mode, then pick several episode files
  (`Files…`) or a whole folder (`Folder…`) and run once.
- **CLI (folder):** `python batch.py episodes_folder --out fixed_season`
- **CLI (files):** `python batch.py ep01.mp3 ep02.mp3 --out fixed_season --preset podcast`
- **CLI (engine entry):** `python audio_fix.py --batch episodes_folder --out fixed_season`
  or simply `python audio_fix.py episodes_folder fixed_season podcast`

Each episode lands in its own sub-folder of the output folder (fixed file
+ its full before/after report, exactly as in single mode). The output
folder also gets one **batch summary** — `batch_summary.md` (and a
`batch_summary.csv` twin) with one line per episode: file name, LUFS
before → after, true peak before → after, PASS / FAIL — plus a totals
row (`Total: N episodes — X PASS, Y FAIL`). An episode that cannot be
processed is listed as FAIL with its error and never stops the rest of
the batch. Batch CLI exit code: 0 = every episode PASS, 1 = any FAIL,
2 = usage/setup error.

## Run from source
```
python audio_fix.py episode.mp3 output_folder podcast
python batch.py episodes_folder --out fixed_season --preset podcast
```
Requires ffmpeg/ffprobe (the Windows package bundles them next to the app).

## Scope
Overall loudness, true peak and edge silence. Background noise, echo and
source distortion are recording problems, not loudness problems — out of scope.
