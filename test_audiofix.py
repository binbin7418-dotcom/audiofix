#!/usr/bin/env python3
"""AudioFix acceptance tests (stdlib only; requires ffmpeg/ffprobe on PATH).

Covers the product's standing acceptance criteria:
  1. Single-file regression on the seeded sample — the README's verified
     behaviour: seeded.wav (integrated ≈ -29.9 LUFS, 4 s of edge silence)
     must come out within ±0.5 LUFS of the -16 podcast target, verdict
     PASS, with edge silence trimmed.
  2. Batch mode: >= 3 files in one run (seeded + synthetic variants at
     different loudness) -> every episode PASS, one batch summary with a
     line per episode and a totals row (md + csv).
  3. Batch resilience: a corrupt file becomes a FAIL row with an error
     and does not abort the other episodes.

Run:  python test_audiofix.py
"""
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from audio_fix import run_audiofix, run_batch, collect_batch_inputs  # noqa: E402

SEEDED = os.path.join(HERE, "seeded.wav")


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *args],
                   check=True)


def _sine(path, freq, gain, seconds=5):
    _ffmpeg("-f", "lavfi", "-i", f"sine=frequency={freq}:duration={seconds}",
            "-af", f"volume={gain}", "-ar", "48000", path)


@unittest.skipUnless(shutil.which("ffmpeg") and os.path.isfile(SEEDED),
                     "ffmpeg or seeded.wav missing")
class TestSingleRegression(unittest.TestCase):
    def test_seeded_sample_passes(self):
        with tempfile.TemporaryDirectory() as td:
            s = run_audiofix(SEEDED, os.path.join(td, "out"), "podcast", True)
            self.assertEqual(s["verdict"], "PASS")
            self.assertLessEqual(abs(s["after"]["I"] - (-16.0)), 0.5)
            self.assertLessEqual(s["after"]["TP"], -1.0 + 0.1)
            self.assertTrue(os.path.isfile(s["fixed_path"]))
            self.assertTrue(os.path.isfile(s["report_path"]))


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg missing")
class TestBatch(unittest.TestCase):
    def _make_inputs(self, folder):
        os.makedirs(folder)
        shutil.copy(SEEDED, os.path.join(folder, "ep01_seeded.wav"))
        # sine source peaks at ≈ -18 dBFS before the volume gain; keep the
        # "quiet" variant above the engine's -45 dB silence-trim threshold
        _sine(os.path.join(folder, "ep02_quiet.wav"), 440, 0.2)
        _sine(os.path.join(folder, "ep03_loud.wav"), 880, 3.0)

    def test_batch_three_files_one_summary(self):
        with tempfile.TemporaryDirectory() as td:
            src_dir, out_dir = os.path.join(td, "in"), os.path.join(td, "out")
            self._make_inputs(src_dir)
            b = run_batch([src_dir], out_dir, "podcast", True)
            self.assertEqual(b["total"], 3)
            self.assertEqual(b["passed"], 3, b["results"])
            self.assertEqual(b["failed"], 0)
            for r in b["results"]:
                self.assertEqual(r["status"], "PASS")
                self.assertLessEqual(abs(r["after_I"] - (-16.0)), 0.5)
                self.assertTrue(os.path.isfile(r["fixed_path"]))
                self.assertTrue(os.path.isfile(r["report_path"]))
            self.assertTrue(os.path.isfile(b["summary_md"]))
            self.assertTrue(os.path.isfile(b["summary_csv"]))
            with open(b["summary_md"], encoding="utf-8") as fh:
                md = fh.read()
            for name in ("ep01_seeded.wav", "ep02_quiet.wav", "ep03_loud.wav"):
                self.assertIn(name, md)
            self.assertIn("Total: 3 episodes — 3 PASS, 0 FAIL", md)
            with open(b["summary_csv"], newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r["verdict"] == "PASS" for r in rows))

    def test_batch_multi_file_inputs_and_collect(self):
        with tempfile.TemporaryDirectory() as td:
            src_dir = os.path.join(td, "in")
            self._make_inputs(src_dir)
            files = collect_batch_inputs(
                [os.path.join(src_dir, "ep02_quiet.wav"),
                 os.path.join(src_dir, "ep03_loud.wav")])
            self.assertEqual(len(files), 2)
            b = run_batch(files, os.path.join(td, "out"), "podcast", True)
            self.assertEqual((b["total"], b["passed"]), (2, 2))

    def test_batch_rerun_over_same_folder_is_stable(self):
        # GUI folder mode writes its output inside the source folder;
        # a second run must not re-ingest its own fixed/trimmed outputs.
        with tempfile.TemporaryDirectory() as td:
            src_dir = os.path.join(td, "in")
            self._make_inputs(src_dir)
            out_dir = os.path.join(src_dir, "audiofix_batch_output")
            b1 = run_batch([src_dir], out_dir, "podcast", True)
            b2 = run_batch([src_dir], out_dir, "podcast", True)
            self.assertEqual(b1["total"], 3)
            self.assertEqual(b2["total"], 3)

    def test_batch_corrupt_file_fails_without_aborting(self):
        with tempfile.TemporaryDirectory() as td:
            src_dir, out_dir = os.path.join(td, "in"), os.path.join(td, "out")
            os.makedirs(src_dir)
            _sine(os.path.join(src_dir, "good.wav"), 440, 1.0)
            with open(os.path.join(src_dir, "broken.wav"), "wb") as fh:
                fh.write(b"this is not audio at all")
            b = run_batch([src_dir], out_dir, "podcast", True)
            self.assertEqual(b["total"], 2)
            by_name = {r["file"]: r for r in b["results"]}
            self.assertEqual(by_name["good.wav"]["status"], "PASS")
            self.assertEqual(by_name["broken.wav"]["status"], "FAIL")
            self.assertTrue(by_name["broken.wav"]["error"])
            self.assertTrue(os.path.isfile(b["summary_md"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
