"""Self-checks for the LLM tier's pure logic: skipping, containers, mapping, spread.

    python3 -m unittest discover -s tools/memory-bench -p 'test_*.py'

None of these starts Ollama, Docker or an engine.
"""
import os
import tempfile
import unittest

os.environ.setdefault("BENCH_STATE", os.path.join(tempfile.gettempdir(), "leteo-adapters-selfcheck"))

import bench_engines  # noqa: E402
import llm_report  # noqa: E402
import llm_tier  # noqa: E402
from adapters import Skipped  # noqa: E402

TAGS = [
    {"name": "qwen2.5:7b", "digest": "845dbda0ea48" + "0" * 52, "details": {"parameter_size": "7.6B", "quantization_level": "Q4_K_M"}},
    {"name": "nomic-embed-text:latest", "digest": "0a109f422b47" + "0" * 52, "details": {"parameter_size": "137M", "quantization_level": "F16"}},
]


class WithoutPath(unittest.TestCase):
    def setUp(self):
        self.old = os.environ["PATH"]
        os.environ["PATH"] = ""

    def tearDown(self):
        os.environ["PATH"] = self.old


class Models(unittest.TestCase):
    def test_a_tag_and_a_bare_name_are_both_found_with_their_digests(self):
        found = llm_tier.resolve_models(TAGS, ["qwen2.5:7b", "nomic-embed-text"])
        self.assertEqual(found["qwen2.5:7b"]["digest"], "845dbda0ea48")
        self.assertEqual(found["nomic-embed-text"]["name"], "nomic-embed-text:latest")

    def test_a_model_that_is_not_pulled_skips_the_engine_and_names_it(self):
        with self.assertRaises(Skipped) as caught:
            llm_tier.resolve_models(TAGS, ["qwen2.5:7b", "llama3.1:8b"])
        self.assertIn("llama3.1:8b", str(caught.exception))
        self.assertNotIn("qwen2.5:7b", str(caught.exception))

    def test_a_different_tag_of_the_same_model_is_not_the_model(self):
        with self.assertRaises(Skipped):
            llm_tier.resolve_models(TAGS, ["qwen2.5:14b"])

    def test_ollama_that_is_not_running_skips_rather_than_failing(self):
        with self.assertRaises(Skipped) as caught:
            llm_tier.ollama_state(["qwen2.5:7b"], url="http://127.0.0.1:1")
        self.assertIn("not reachable", str(caught.exception))


class LocalOnly(unittest.TestCase):
    def test_a_remote_host_is_refused_because_the_corpus_would_leave_the_machine(self):
        with self.assertRaises(Skipped) as caught:
            llm_tier.require_local("https://ollama.example.com")
        self.assertIn("local-only", str(caught.exception))

    def test_this_machine_is_accepted_under_each_of_its_names(self):
        for url in ("http://localhost:11434", "http://127.0.0.1:11434", "http://host.docker.internal:11434"):
            llm_tier.require_local(url)

    def test_a_host_that_only_starts_like_localhost_is_remote(self):
        with self.assertRaises(Skipped):
            llm_tier.require_local("http://localhost.evil.example:11434")


class Containers(unittest.TestCase):
    def test_a_container_is_named_for_this_process_so_only_its_own_is_ever_removed(self):
        cmd = llm_tier.run_command("img:1", "falkor", [6379])
        name = cmd[cmd.index("--name") + 1]
        self.assertEqual(name, f"leteo-bench-{os.getpid()}-falkor")

    def test_ports_bind_loopback_with_a_random_host_port_and_no_volume_is_mounted(self):
        cmd = llm_tier.run_command("img:1", "falkor", [6379, 8283], env={"A": "b"})
        self.assertEqual([c for c in cmd if c.startswith("127.0.0.1::")], ["127.0.0.1::6379", "127.0.0.1::8283"])
        for flag in ("-v", "--volume", "--mount", "--network", "--privileged", "-P"):
            self.assertNotIn(flag, cmd)
        self.assertEqual(cmd[-1], "img:1")

    def test_removal_takes_the_anonymous_volumes_with_it(self):
        self.assertEqual(llm_tier.remove_command("n")[:4], ["docker", "rm", "-f", "-v"])


class Prerequisites(WithoutPath):
    def test_no_docker_skips_with_its_name(self):
        with self.assertRaises(Skipped) as caught:
            llm_tier.docker_ready()
        self.assertIn("`docker` was not found", str(caught.exception))

    def test_each_runner_an_engine_needs_is_named_when_missing(self):
        for cls, tool in ((llm_tier.Mem0VerbatimAdapter, "uv"), (llm_tier.ClaudeMemAdapter, "npm"),
                          (llm_tier.GraphitiAdapter, "docker")):
            with self.assertRaises(Skipped) as caught:
                cls(tempfile.gettempdir()).check_tools()
            self.assertIn(f"`{tool}` was not found", str(caught.exception))


class ClaudeMemReplies(unittest.TestCase):
    TABLE = """Found 2 result(s) matching "backoff" (2 obs, 0 sessions, 0 prompts)

### Oct 11, 2026

**General**
| ID | Time | T | Title | Read |
|----|------|---|-------|------|
| #31 | 3:43 PM | ○ | Retries use exponential backoff | ~27 |
| #4 | 3:42 PM | ○ | Keyset pagination | ~32 |
"""

    def test_hits_come_back_in_rank_order_with_their_ids(self):
        self.assertEqual(llm_tier.parse_search_table(self.TABLE),
                         [("31", "Retries use exponential backoff"), ("4", "Keyset pagination")])

    def test_a_reply_with_no_table_has_no_hits(self):
        self.assertEqual(llm_tier.parse_search_table("No results found matching \"x\""), [])

    def test_the_id_of_a_saved_memory(self):
        self.assertEqual(llm_tier.parse_saved_id("Saved memory #12: Keyset. Project: alpha."), "12")
        self.assertIsNone(llm_tier.parse_saved_id("The worker could not complete this request."))


class GraphitiProvenance(unittest.TestCase):
    KEYMAP = {"e1": "retry", "e2": "retry", "e3": "keyset"}

    def test_a_fact_is_the_memory_its_source_episode_is(self):
        self.assertEqual(llm_tier.episode_key(["e1"], self.KEYMAP), "retry")

    def test_episodes_of_one_memory_agree(self):
        self.assertEqual(llm_tier.episode_key(["e1", "e2"], self.KEYMAP), "retry")

    def test_a_fact_drawn_from_two_memories_is_not_guessed(self):
        self.assertIsNone(llm_tier.episode_key(["e1", "e3"], self.KEYMAP))

    def test_an_episode_we_never_wrote_is_unmappable(self):
        self.assertIsNone(llm_tier.episode_key(["elsewhere"], self.KEYMAP))
        self.assertIsNone(llm_tier.episode_key([], self.KEYMAP))

    def test_the_adapter_maps_a_hit_through_its_episode_list(self):
        a = llm_tier.GraphitiAdapter(tempfile.gettempdir())
        a.keymap = dict(self.KEYMAP)
        self.assertEqual(a.map_hit(llm_tier.Hit("e3,e3", "a fact"), []), "keyset")
        self.assertIsNone(a.map_hit(llm_tier.Hit("e1,e3", "a fact"), []))
        self.assertIsNone(a.map_hit(llm_tier.Hit("-", "a fact"), []))


class FakeWorker:
    def __init__(self, events):
        self.events = events

    def send(self, req, timeout):
        return {"events": self.events.get(req["key"], [])}

    def close(self):
        pass


class Mem0Provenance(unittest.TestCase):
    MEMBERS = [dict(key=k, project="p", title=k, content=f"content of {k}", type="decision") for k in ("a", "b", "c")]

    def adapter(self, events):
        a = llm_tier.Mem0InferAdapter(tempfile.gettempdir())
        a._servers["w"] = FakeWorker(events)
        a.load(self.MEMBERS)
        return a

    def verbatim(self, events):
        a = llm_tier.Mem0VerbatimAdapter(tempfile.gettempdir())
        a._servers["w"] = FakeWorker(events)
        a.load(self.MEMBERS)
        return a

    def test_a_memory_the_model_extracted_nothing_from_has_no_provenance(self):
        a = self.adapter({"a": ["ADD"], "b": [], "c": ["ADD", "ADD"]})
        self.assertEqual(a.map_hit(llm_tier.Hit("a", "x"), self.MEMBERS), "a")
        self.assertIsNone(a.map_hit(llm_tier.Hit("b", "x"), self.MEMBERS))

    def test_the_count_of_memories_that_were_not_stored_is_on_the_row(self):
        a = self.adapter({"a": ["ADD"], "b": [], "c": ["UPDATE"]})
        self.assertTrue(any("2 of 3 memories" in n and "1 extraction events updated" in n for n in a.notes), a.notes)

    def test_a_row_without_extraction_still_names_the_writes_that_were_dropped(self):
        a = self.verbatim({"a": ["ADD"], "b": [], "c": ["ADD"]})
        self.assertTrue(any("2 of 3 memories were stored" in n and "1 write returned no events" in n for n in a.notes), a.notes)

    def test_a_row_that_stored_everything_names_no_drop(self):
        a = self.verbatim({"a": ["ADD"], "b": ["ADD"], "c": ["ADD"]})
        self.assertTrue(any("3 of 3 memories were stored" in n and "returned no events" not in n for n in a.notes), a.notes)

    def test_a_store_that_kept_nothing_is_a_fault_not_a_row(self):
        with self.assertRaises(RuntimeError):
            self.adapter({})


def rows(ranks):
    return [dict(kind="k", rank=r, n=20 if r else 0, unmappable=0) for r in ranks]


def engine(label, rank_sets, planned=None):
    return dict(label=label, name=label, status="measured", version="1", date="2026-01-01", failed="", reason="",
                models={}, planned=planned or len(rank_sets), ollama="0.1",
                passes=[dict(rows=rows(r), no_answer=[dict(n=0)] * 4, load_seconds=10, notes=[]) for r in rank_sets])


class Spread(unittest.TestCase):
    def test_the_lowest_and_highest_pass_sit_beside_the_mean(self):
        self.assertEqual(llm_report.cell([0.5, 0.6, 0.7]), "0.600 (0.500–0.700)")

    def test_passes_that_agree_say_so_instead_of_printing_a_range_of_one(self):
        self.assertEqual(llm_report.cell([0.5, 0.5]), "0.500 (every pass)")

    def test_the_table_reports_each_pass_not_only_the_mean(self):
        # MRR of the three passes: 1.0, 0.5, 0.25
        table = llm_report.results_table([engine("e", [[1, 1], [2, 2], [4, 4]])])
        self.assertIn("0.583 (0.250–1.000)", table)

    def test_the_pass_count_is_a_column_and_a_short_run_shows_how_short(self):
        self.assertIn("| e | 2 of 3 |", llm_report.results_table([engine("e", [[1], [1]], planned=3)]))
        self.assertIn("| e | 3 |", llm_report.results_table([engine("e", [[1], [1], [1]])]))


class Page(unittest.TestCase):
    def test_an_engine_that_was_not_measured_is_listed_with_its_reason_and_has_no_numbers(self):
        skipped = dict(label="Graphiti", status="skipped", reason="the Docker daemon is not reachable", version="",
                       date="2026-01-01", passes=[], models={}, planned=3, failed="")
        text = llm_report.engines_table([engine("mem0", [[1]]), skipped])
        self.assertIn("**not measured:** the Docker daemon is not reachable", text)
        self.assertNotIn("Graphiti | ", llm_report.results_table([engine("mem0", [[1]])]))

    def test_a_run_that_stopped_part_way_keeps_its_passes_and_says_why(self):
        e = engine("mem0", [[1]], planned=3)
        e["failed"] = "pass 2: RuntimeError: worker exited"
        self.assertIn("**stopped:** pass 2: RuntimeError: worker exited", llm_report.engines_table([e]))

    def test_a_row_that_called_no_model_does_not_claim_one(self):
        self.assertEqual(llm_report.models_cell(engine("x", [[1]])), "none called")

    def test_the_vendor_default_caveat_is_on_the_page(self):
        self.assertIn("lower here than in their vendor-default", llm_report.CAVEAT)


class Letta(unittest.TestCase):
    def test_letta_is_a_skip_that_says_what_the_named_version_is(self):
        e = bench_engines.run_llm(llm_tier.LettaAdapter, tempfile.gettempdir(), [], "2026-01-01", 3)
        self.assertEqual((e["status"], e["passes"]), ("skipped", []))
        self.assertIn("Letta Code", e["reason"])
        self.assertIn("0.16.8", e["reason"])


class OptIn(unittest.TestCase):
    def run_with(self, cls, var, value):
        old = os.environ.pop(var, None)
        if value is not None:
            os.environ[var] = value
        try:
            return bench_engines.run_llm(cls, tempfile.gettempdir(), [], "2026-01-01", 3)
        finally:
            os.environ.pop(var, None)
            if old is not None:
                os.environ[var] = old

    CASES = ((llm_tier.GraphitiAdapter, "BENCH_GRAPHITI", "16 of the first 18 episodes"),
             (llm_tier.Mem0InferAdapter, "BENCH_MEM0_INFER", "filled the disk before three passes"))

    def test_by_default_each_is_not_measured_with_its_measured_reason_and_its_opt_in(self):
        for cls, var, why in self.CASES:
            e = self.run_with(cls, var, None)
            self.assertEqual((e["status"], e["passes"]), ("skipped", []), var)
            self.assertIn(why, e["reason"])
            self.assertIn(f"set {var}=1", e["reason"])

    def test_any_value_but_one_leaves_it_gated(self):
        for cls, var, why in self.CASES:
            self.assertIn(why, self.run_with(cls, var, "true")["reason"])

    def test_opting_in_gets_past_the_gate_to_the_real_prerequisites(self):
        old = os.environ["PATH"]
        os.environ["PATH"] = ""
        try:
            for cls, var, why in self.CASES:
                self.assertNotIn(why, self.run_with(cls, var, "1")["reason"])
        finally:
            os.environ["PATH"] = old

    def test_the_gated_engines_and_their_variables_are_one_table(self):
        self.assertEqual({n: v for n, (v, _) in llm_tier.OPT_IN.items()},
                         {"mem0-infer": "BENCH_MEM0_INFER", "graphiti": "BENCH_GRAPHITI"})


class DiskWatchdog(unittest.TestCase):
    def test_no_pass_starts_when_the_disk_is_nearly_full(self):
        saved = bench_engines.shutil.disk_usage
        bench_engines.shutil.disk_usage = lambda p: type("U", (), {"free": 1024 ** 3})()
        try:
            e = bench_engines.run_llm(Passes().cls("ok"), tempfile.gettempdir(), [], "2026-01-01", 3)
        finally:
            bench_engines.shutil.disk_usage = saved
        self.assertEqual((e["status"], e["passes"]), ("skipped", []))
        self.assertIn("stopped before pass 1", e["reason"])


class Passes(unittest.TestCase):
    def cls(self, behaviour):
        class A(llm_tier.LLMAdapter):
            name, label = "fake", "Fake"
            calls = 0

            def check(self):
                if behaviour == "skip":
                    raise Skipped("Ollama is not reachable at http://localhost:11434")

            def version(self):
                return "9"

            def load(self, members):
                A.calls += 1
                if behaviour == "second-fails" and A.calls == 2:
                    raise RuntimeError("store unreadable")

            def search(self, project, query, limit):
                return []

        return A

    def run_it(self, behaviour, passes=3):
        saved = (bench_engines.queries, bench_engines.no_answer)
        bench_engines.queries = lambda: [dict(project="p", q="x", target="a", kind="k")]
        bench_engines.no_answer = lambda: [dict(project="p", q="y")]
        try:
            return bench_engines.run_llm(self.cls(behaviour), tempfile.gettempdir(), [], "2026-01-01", passes)
        finally:
            bench_engines.queries, bench_engines.no_answer = saved

    def test_a_missing_dependency_is_a_skip_with_its_reason_and_no_passes(self):
        e = self.run_it("skip")
        self.assertEqual((e["status"], e["passes"]), ("skipped", []))
        self.assertIn("Ollama is not reachable", e["reason"])

    def test_every_requested_pass_runs_and_is_kept(self):
        e = self.run_it("ok")
        self.assertEqual((e["status"], len(e["passes"]), e["planned"]), ("measured", 3, 3))
        self.assertEqual([(len(p["rows"]), len(p["no_answer"])) for p in e["passes"]], [(1, 1)] * 3)

    def test_a_fault_in_a_later_pass_keeps_the_earlier_ones_and_stops(self):
        e = self.run_it("second-fails")
        self.assertEqual((e["status"], len(e["passes"])), ("measured", 1))
        self.assertIn("pass 2: RuntimeError: store unreadable", e["failed"])


if __name__ == "__main__":
    unittest.main()
