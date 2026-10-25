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

## Run from source
```
python audio_fix.py episode.mp3 output_folder podcast
```
Requires ffmpeg/ffprobe (the Windows package bundles them next to the app).

## Scope
Overall loudness, true peak and edge silence. Background noise, echo and
source distortion are recording problems, not loudness problems — out of scope.
