"""One adapter per engine behind one interface.

The comparison used to know exactly two engines, and each was wired into the
loader, the search script and the page by hand. An adapter is the whole of what
the harness needs from an engine: start it isolated, write the corpus through the
engine's own write path, search through its own search path, and say which corpus
memory each returned hit is. Adding an engine is one class and one registry
entry; nothing downstream names it.

Isolation is the first rule and the one that is easy to break by accident: no
run may read or write a real store. `isolated_env` is the only place an
environment for an engine is built, and it removes every variable that could name
a real store before it sets the throwaway ones.
"""

import json
import os
import re
import shutil
import subprocess
import unicodedata

from mcpclient import BENCH, ENGRAM, LETEO, MCP, call_json, engine_cmd

# Variables an engine reads to find its data. They are removed from the inherited
# environment first, so a developer who exports one for daily use does not point
# a benchmark run at their own memory.
STORE_VARIABLES = (
    "ENGRAM_DATA_DIR", "LETEO_DATA_DIR",
    "BASIC_MEMORY_CONFIG_DIR", "BASIC_MEMORY_HOME", "BASIC_MEMORY_DEFAULT_PROJECT",
    "MEMORY_FILE_PATH",
)

# A content match shorter than this proves nothing: a ten-character snippet is
# contained in half the distractors, which share their vocabulary on purpose.
MIN_CONTENT_MATCH = 40


class Skipped(Exception):
    """The engine cannot be measured here, and the message says why.

    Raised for a missing binary, package manager or service. It is never turned
    into a row of zeros: a zero is a measurement, and nothing was measured.
    """


class Hit:
    """One search result, reduced to what mapping needs.

    `ref` is the engine's own identifier for it when the engine keeps one that we
    set; `text` is whatever content the reply carried, for the fallback rule.
    """

    __slots__ = ("ref", "text")

    def __init__(self, ref=None, text=""):
        self.ref = None if ref is None else str(ref)
        self.text = text or ""


def isolated_env(state, name, **extra):
    """The environment an engine runs in: a home under `state`, no real store.

    `name` keeps each engine's home apart from the others', so one engine's
    leftovers cannot answer for another.
    """
    home = os.path.join(state, "homes", name)
    os.makedirs(home, exist_ok=True)
    env = {k: v for k, v in os.environ.items() if k not in STORE_VARIABLES}
    env.update(HOME=home, USERPROFILE=home, XDG_CONFIG_HOME=os.path.join(home, ".config"),
               XDG_DATA_HOME=os.path.join(home, ".local", "share"),
               XDG_CACHE_HOME=os.path.join(home, ".cache"))
    env.update(extra)
    return env


def normalise(text):
    """Case, accents, punctuation and spacing folded away, so a snippet that an
    engine re-wrapped or re-cased still contains the text that was saved."""
    text = unicodedata.normalize("NFKD", text).casefold()
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[\W_]+", " ", text).strip()


def content_key(text, members):
    """The corpus memory a hit's text is, or None.

    Engine-independent: the text must contain the saved content or be a stretch of
    it of at least `MIN_CONTENT_MATCH` characters. A hit that fits more than one
    memory, or none, is unmappable; guessing between two would hand one engine a
    rank the other was denied.
    """
    seen = normalise(text)
    if len(seen) < MIN_CONTENT_MATCH:
        return None
    found = {m["key"] for m in members if normalise(m["content"]) in seen or seen in normalise(m["content"])}
    return found.pop() if len(found) == 1 else None


class Adapter:
    """The interface. A subclass sets `name` and `label` and implements the rest."""

    name = ""
    label = ""
    # The engine the page is about: if it cannot be measured the run has failed,
    # rather than quietly producing a page without it.
    required = False

    def __init__(self, state):
        self.state = state
        self.keymap = {}
        self._servers = {}

    def check(self):
        """Raise `Skipped` when the engine's prerequisites are absent."""

    def version(self):
        raise NotImplementedError

    def load(self, members):
        """Write every member through the engine's own write path and fill
        `self.keymap` with `hit.ref -> corpus key` for what was written."""
        raise NotImplementedError

    def search(self, project, query, limit):
        raise NotImplementedError

    def map_hit(self, hit, members):
        """Provenance first; the content rule only for a hit carrying none."""
        if hit.ref is not None:
            return self.keymap.get(hit.ref)
        return content_key(hit.text, members)

    def close(self):
        for server in self._servers.values():
            server.close()
        self._servers = {}

    def _server(self, project, launch, warmup):
        if project not in self._servers:
            server = MCP(self.name, project, launch=launch())
            # The first search pays for model loads and cold caches, which is not
            # what the ranking numbers are about.
            warmup(server)
            self._servers[project] = server
        return self._servers[project]


class _SearchTool(Adapter):
    """Engram and Leteo: `mem_search` over MCP, replying `{"results": [{"id": ..}]}`."""

    def search(self, project, query, limit):
        m = self._server(project, lambda: engine_cmd(self.name, project),
                         lambda s: s.call("mem_search", {"query": "warmup"}))
        reply, _, _ = call_json(m, "mem_search", {"query": query, "limit": limit})
        return [Hit(r["id"], r.get("content")) for r in reply.get("results") or []]

    def version(self):
        r = subprocess.run([self.binary, "--version"], capture_output=True, text=True, env=dict(os.environ))
        text = (r.stdout or "") + (r.stderr or "")
        m = re.search(self.version_pattern, text)
        return m.group(1) if m else "unknown"


class EngramAdapter(_SearchTool):
    name, label, binary = "engram", "Engram", ENGRAM
    version_pattern = r"engram\s+v?(\d+\.\d+\.\d+)"

    def check(self):
        if not shutil.which(self.binary):
            raise Skipped(f"`{self.binary}` was not found on PATH; set ENGRAM_BIN to the binary")

    def load(self, members):
        # Engram's own `engram save`, as before the adapters existed: its numbers
        # are comparable with every earlier run only if it is loaded the same way.
        import load_engram
        self.keymap = {str(i): k for k, i in load_engram.load().items()}


class LeteoAdapter(_SearchTool):
    name, label, binary = "leteo", "Leteo", LETEO
    version_pattern = r"(\d+\.\d+\.\d+)"
    required = True

    def check(self):
        if not shutil.which(self.binary):
            raise Skipped(f"`{self.binary}` was not found; set LETEO_BIN to the build under test")

    def load(self, members):
        # Leteo adopts a copy of the Engram store, so ids survive and one answer
        # key serves both. It cannot be loaded without that store.
        if not os.path.exists(os.path.join(BENCH, "keymap_engram.json")):
            raise Skipped("its corpus is adopted from the Engram store, and Engram was not loaded")
        env = dict(os.environ, BENCH_STATE=BENCH, LETEO_BIN=self.binary)
        here = os.path.dirname(os.path.abspath(__file__))
        r = subprocess.run(["sh", "load_leteo.sh"], cwd=here, env=env, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(f"load_leteo.sh failed: {r.stderr.strip()}")
        engram_ids = json.load(open(os.path.join(BENCH, "keymap_engram.json")))
        self.keymap = {str(i): k for k, i in engram_ids.items()}


# The deterministic tier: no model, no network at query time beyond fetching the
# engine itself, so a re-run on the same versions gives the same ranking.
DETERMINISTIC = (EngramAdapter, LeteoAdapter)

# The opt-in tier is for engines that need a local LLM (mem0, claude-mem, Letta,
# Graphiti on Ollama). It is selected with `--tier llm`, which compare.py refuses
# until adapters are registered here; an engine that is not measured has no row,
# which is different from a row of zeros.
LLM: tuple = ()

TIERS = {"deterministic": DETERMINISTIC, "llm": LLM}

