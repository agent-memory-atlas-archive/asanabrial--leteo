"""Self-checks for the deterministic page's pass handling.

    python3 -m unittest discover -s tools/memory-bench -p 'test_*.py'

None of these starts an engine: they are the arithmetic of a row measured once
and a row measured over passes, which is the difference the page has to keep, and
the load loop that produces the passes.
"""
import os
import shutil
import tempfile
import unittest

os.environ.setdefault("BENCH_STATE", os.path.join(tempfile.gettempdir(), "leteo-compare-selfcheck"))

import bench_engines  # noqa: E402
import compare  # noqa: E402
from adapters import Adapter, Skipped  # noqa: E402
from comparison_corpus import corpus  # noqa: E402


def rows(ranks):
    return [dict(kind="short", q=f"q{i}", rank=r, n=5, unmappable=0) for i, r in enumerate(ranks)]


def one(ranks):
    return dict(rows=rows(ranks), no_answer=[])


def engine(name, passes):
    return dict(name=name, label=name, version="0", date="2026-01-01", status="measured",
                required=False, reason="", rows=passes[0]["rows"], no_answer=passes[0]["no_answer"],
                passes=passes)


class Figure(unittest.TestCase):
    def test_one_pass_is_its_own_number(self):
        self.assertEqual(compare.figure([0.750], 3), "0.750")

    def test_several_passes_are_a_mean_with_the_range(self):
        self.assertEqual(compare.figure([0.750, 0.500], 3), "0.625 (0.500–0.750)")

    def test_passes_that_agree_say_every_pass(self):
        self.assertEqual(compare.figure([0.750, 0.750], 3), "0.750 (every pass)")

    def test_a_run_that_planned_five_and_kept_one_says_so(self):
        self.assertEqual(compare.figure([0.750], 3, planned=5), "0.750 (1 of 5 passes)")


class OverallTable(unittest.TestCase):
    def test_a_row_measured_once_is_written_as_before(self):
        line = compare.overall_table([engine("leteo", [one([1, 2])])])
        self.assertIn("| leteo | 0 | 2026-01-01 | 0.50 | 1.00 | 0.750 | 0 of 2 | 10 | 0 | 0 of 0 |", line)

    def test_a_row_measured_over_passes_reports_the_spread(self):
        line = compare.overall_table([engine("basic-memory", [one([1, 2]), one([1, None])])])
        self.assertIn("| 0.625 (0.500–0.750) |", line)


class EnginesTable(unittest.TestCase):
    def test_a_row_measured_once_still_just_says_measured(self):
        self.assertIn("| leteo | 0 | 2026-01-01 | measured |",
                      compare.engines_table([engine("leteo", [one([1])])]))

    def test_a_row_measured_over_passes_names_the_count(self):
        self.assertIn("| basic-memory | 0 | 2026-01-01 | measured, mean of 5 passes |",
                      compare.engines_table([engine("basic-memory", [one([1]) for _ in range(5)])]))

    def test_a_truncated_run_names_the_passes_it_kept_and_the_fault(self):
        e = engine("basic-memory", [one([1])])
        e["planned"], e["failed"] = 5, "pass 2: no engine"
        self.assertIn("| basic-memory | 0 | 2026-01-01 | measured, mean of 1 of 5 passes; "
                      "**stopped:** pass 2: no engine |", compare.engines_table([e]))


class LeadsTable(unittest.TestCase):
    def test_the_leader_uses_the_mean_of_the_passes(self):
        leteo = engine("leteo", [one([1, 1])])
        basic = engine("basic-memory", [one([1, 1]), one([1, None])])
        self.assertIn("leteo 1.000", compare.leads_table([leteo, basic], {}))


class FakeAdapter(Adapter):
    """The smallest engine `run_repeated` can drive: it loads, answers nothing."""

    name, label = "fake", "fake"
    calls = 0
    fail_on = 0

    def check(self):
        pass

    def version(self):
        return "0"

    def load(self, members):
        FakeAdapter.calls += 1
        if FakeAdapter.calls == FakeAdapter.fail_on:
            raise Skipped("no engine")

    def search(self, project, query, limit):
        return []


class RunRepeated(unittest.TestCase):
    def setUp(self):
        FakeAdapter.calls = 0
        FakeAdapter.fail_on = 0
        self.state = tempfile.mkdtemp(prefix="leteo-run-repeated-")
        self.addCleanup(shutil.rmtree, self.state, ignore_errors=True)

    def test_a_complete_run_keeps_every_pass_and_names_none_failed(self):
        entry = bench_engines.run_repeated(FakeAdapter, self.state, corpus(), "2026-01-01", 3)
        self.assertEqual(len(entry["passes"]), 3)
        self.assertEqual(entry["planned"], 3)
        self.assertEqual(entry["failed"], "")
        self.assertEqual(entry["status"], "measured")
        self.assertIn("mean of 3 passes", compare.engines_table([entry]))

    def test_a_fault_keeps_the_passes_that_ran_and_stops(self):
        FakeAdapter.fail_on = 2
        entry = bench_engines.run_repeated(FakeAdapter, self.state, corpus(), "2026-01-01", 3)
        self.assertEqual(len(entry["passes"]), 1)
        self.assertEqual(entry["failed"], "pass 2: no engine")
        self.assertEqual(entry["status"], "measured")
        table = compare.engines_table([entry])
        self.assertIn("mean of 1 of 3 passes", table)
        self.assertIn("**stopped:** pass 2: no engine", table)

    def test_no_pass_at_all_is_not_measured(self):
        FakeAdapter.fail_on = 1
        entry = bench_engines.run_repeated(FakeAdapter, self.state, corpus(), "2026-01-01", 3)
        self.assertEqual(entry["passes"], [])
        self.assertEqual(entry["status"], "skipped")


if __name__ == "__main__":
    unittest.main()
