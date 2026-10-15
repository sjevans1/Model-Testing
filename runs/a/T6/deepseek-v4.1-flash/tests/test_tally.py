"""Tests for the tally helpers. Nine tests: the CI runner must report all of them."""
from __future__ import annotations

import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from tally import mean, median, percentile, summarize  # noqa: E402


class TestTally(unittest.TestCase):
    def test_mean_simple(self):
        self.assertEqual(mean([1, 2, 3, 4]), 2.5)

    def test_mean_empty_raises(self):
        with self.assertRaises(ValueError):
            mean([])

    def test_median_odd_length(self):
        self.assertEqual(median([5, 1, 3]), 3)

    def test_median_even_length(self):
        self.assertEqual(median([1, 2, 3, 4]), 2.5)

    def test_percentile_bounds(self):
        with self.assertRaises(ValueError):
            percentile([1, 2, 3], 101)

    def test_percentile_p90(self):
        self.assertEqual(percentile(list(range(1, 11)), 90), 9)

    def test_summarize_shape(self):
        got = summarize([1, 2, 3, 4])
        self.assertEqual(sorted(got), ["mean", "median", "n", "p90"])
        self.assertEqual(got["n"], 4)


if __name__ == "__main__":
    unittest.main()
