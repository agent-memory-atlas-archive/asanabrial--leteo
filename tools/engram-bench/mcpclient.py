import json, os, subprocess, tempfile, time

# Every store lives under BENCH_STATE and each engine is started with HOME and
# its data directory pointed there, so a run cannot reach the user's database.
BENCH = os.environ.get("BENCH_STATE") or os.path.join(tempfile.gettempdir(), "leteo-engram-bench")
ENGRAM = os.environ.get("ENGRAM_BIN", "engram")
LETEO = os.environ.get("LETEO_BIN", "leteo")
# The server is started from a directory under BENCH_STATE, so a relative path
# to the binary stops resolving the moment it is spawned. A bare name is left
# alone: that is a lookup on PATH, not a path. Windows accepts `/` as well as the
# native separator, so `target/release/leteo.exe` is a path there too.
if os.sep in LETEO or (os.altsep and os.altsep in LETEO):
    LETEO = os.path.abspath(LETEO)
os.makedirs(BENCH, exist_ok=True)

# The bench starts Engram dozens of times, and its startup update check is a
# network call that changes nothing measured here. One mapping so every place
# that builds an Engram environment turns it off the same way rather than
# carrying its own copy of the variable name and value.
ENGRAM_QUIET_ENV = {"ENGRAM_NO_UPDATE_CHECK": "1"}

def engine_cmd(engine, project, home=None):
    cwd = os.path.join(BENCH, "work", project)
    os.makedirs(cwd, exist_ok=True)
    if engine == "engram":
        home = os.path.join(BENCH, "ehome")
        return [ENGRAM, "mcp"], cwd, dict(os.environ, HOME=home, ENGRAM_DATA_DIR=os.path.join(home, "data"), **ENGRAM_QUIET_ENV)
    home = home or os.path.join(BENCH, "lhome")
    os.makedirs(home, exist_ok=True)
    env = dict(os.environ, HOME=home, LETEO_DATA_DIR=home)
    # The server runs from `cwd` above, so a relative model directory would be
    # looked for under the bench state and not where the person who typed it
    # meant. The stage then stays off without a word, which is how a documented
    # `LETEO_MODEL_DIR=assets/model` made a run measure the lexical search alone.
    if env.get("LETEO_MODEL_DIR"):
        env["LETEO_MODEL_DIR"] = os.path.abspath(env["LETEO_MODEL_DIR"])
    return [LETEO, "mcp", "--database", os.path.join(home, "leteo.db")], cwd, env

class MCP:
    def __init__(self, engine, project, home=None):
        cmd, cwd, env = engine_cmd(engine, project, home)
        self.p = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.n = 0
        self.req("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                "clientInfo": {"name": "bench", "version": "0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
    def req(self, method, params):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params}) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line: raise RuntimeError("server closed")
            msg = json.loads(line)
            if msg.get("id") == self.n: return msg
    def call(self, tool, args):
        t0 = time.perf_counter()
        r = self.req("tools/call", {"name": tool, "arguments": args})
        dt = time.perf_counter() - t0
        res = r.get("result") or {}
        text = "".join(c.get("text", "") for c in res.get("content", []))
        return text, dt, r
    def close(self):
        self.p.stdin.close(); self.p.wait(timeout=5)
