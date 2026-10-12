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


class OverallTable(unittest.TestCase):
    def test_every_engine_gets_a_row_of_its_own_numbers(self):
        a = engine("A", [row(rank=1), row(rank=2, n=5, unmappable=1)], no_answer=[dict(n=0), dict(n=3)])
        b = engine("B", [row(rank=None, n=0)])
        text = compare.overall_table([a, b])
        self.assertIn("| A | 1.0 | 2026-01-01 | 0.50 | 1.00 | 0.750 | 0 of 2 | 25 | 1 | 1 of 2 |", text)
        self.assertIn("| B | 1.0 | 2026-01-01 | 0.00 | 0.00 | 0.000 | 1 of 1 | 0 | 0 | 0 of 0 |", text)


class KindTable(unittest.TestCase):
    def test_each_engine_is_a_column_and_the_count_comes_from_the_first(self):
        a = engine("A", [row("k1", 1), row("k2", 2)])
        b = engine("B", [row("k1", 1), row("k2", 1)])
        text = compare.kind_table([a, b])
        self.assertIn("| query kind | n | A h@1 / h@5 / MRR | B h@1 / h@5 / MRR |", text)
        self.assertIn("| k1 | 1 | 1.00 / 1.00 / 1.000 | 1.00 / 1.00 / 1.000 |", text)
        self.assertIn("| **overall** | 2 | 0.50 / 1.00 / 0.750 | 1.00 / 1.00 / 1.000 |", text)


class LeadsTable(unittest.TestCase):
    def test_a_tie_names_every_engine_that_holds_the_top(self):
        text = compare.leads_table([engine("A", [row(rank=1)]), engine("B", [row(rank=1)])], {})
        self.assertIn("tie A, B 1.000", text)

    def test_a_lone_leader_is_named_with_its_number(self):
        text = compare.leads_table([engine("A", [row(rank=1)]), engine("B", [row(rank=2)])], {})
        self.assertIn("| A 1.000 |", text)
        self.assertNotIn("tie", text)


class NothingMeasured(unittest.TestCase):
    def test_the_kind_table_does_not_read_an_engine_that_is_not_there(self):
        self.assertIn("query kind", compare.kind_table([]))

    def test_the_leads_table_does_not_rank_an_empty_field(self):
        self.assertIn("query kind", compare.leads_table([], {}))


if __name__ == "__main__":
    unittest.main()
