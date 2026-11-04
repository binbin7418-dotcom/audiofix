#!/usr/bin/env python3
"""AudioFix batch CLI — fix a whole season in one run.

Usage:
    python batch.py EPISODES_FOLDER --out OUTPUT_FOLDER [--preset podcast]
    python batch.py ep01.mp3 ep02.mp3 ep03.wav --out OUTPUT_FOLDER

Every input goes through the same loudness engine as the single-file
tool, with one shared preset. Each episode lands in its own sub-folder
under the output folder, and OUTPUT_FOLDER/batch_summary.md (plus a
.csv twin) lists one line per episode — file, LUFS before -> after,
true peak before -> after, PASS / FAIL — with a totals row.

Exit code: 0 when every episode PASSes, 1 when any episode FAILs,
2 on usage / setup errors.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audio_fix import _run_batch_cli


def main(argv):
    return _run_batch_cli(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv))
