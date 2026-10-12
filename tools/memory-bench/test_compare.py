"""Self-checks for compare.py's tables and its not-measured engine path.

    python3 -m unittest discover -s tools/memory-bench -p 'test_*.py'

No engine is started here: every table is built from a fixed list of rows.
"""
import os
import tempfile
import unittest

os.environ.setdefault("BENCH_STATE", os.path.join(tempfile.gettempdir(), "leteo-adapters-selfcheck"))

import compare  # noqa: E402


def row(kind="k", rank=None, n=20, unmappable=0):
    return dict(kind=kind, rank=rank, n=n, unmappable=unmappable)


def engine(label, rows, no_answer=(), status="measured", version="1.0", date="2026-01-01", reason=""):
    return dict(name=label.lower(), label=label, version=version, date=date, status=status,
                reason=reason, rows=list(rows), no_answer=list(no_answer))


class EnginesTable(unittest.TestCase):
    def test_a_measured_engine_is_a_row_with_its_version_and_date(self):
        text = compare.engines_table([engine("Leteo", [row(rank=1)])])
        self.assertIn("| Leteo | 1.0 | 2026-01-01 | measured |", text)

    def test_a_skipped_engine_names_the_prerequisite_that_was_absent(self):
        e = engine("basic-memory", [], status="skipped", version="", reason="`uvx` was not found on PATH")
        text = compare.engines_table([e])
        self.assertIn("| basic-memory | — | 2026-01-01 | **not measured:** `uvx` was not found on PATH |", text)

    def test_a_crashed_engine_is_failed_and_not_read_as_a_missing_prerequisite(self):
        e = engine("basic-memory", [], status="failed", version="",
                   reason="could not run: RuntimeError: store unreadable")
        text = compare.engines_table([e])
        self.assertIn("| basic-memory | — | 2026-01-01 | **failed:** could not run: RuntimeError: store unreadable |", text)


if __name__ == "__main__":
    unittest.main()
