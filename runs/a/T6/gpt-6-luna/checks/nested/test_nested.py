"""Nested suite: the outer acceptance check shells out to this file and scrapes its lines.

This file stands in for the nightly export check: it is slow, it is the check the pipeline
actually cares about, and it must not be allowed to look green when it did not finish.
The outer check's time budget is `NESTED_TIMEOUT_S` (default 3).
"""
from __future__ import annotations

import pathlib
import sys
import time
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "src"))

from tally import percentile  # noqa: E402


class TestNested(unittest.TestCase):
    def test_first(self):
        self.assertEqual(percentile([1, 2, 3, 4], 25), 1)

    def test_second(self):
        self.assertEqual(percentile([1, 2, 3, 4], 50), 2)

    def test_slow_export(self):
        time.sleep(8)
        self.assertEqual(percentile([1, 2, 3, 4], 75), 3)


if __name__ == "__main__":
    unittest.main()
