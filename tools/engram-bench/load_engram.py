# Saved through `engram save` rather than SQL so its own save path builds the index.
import json, os, subprocess, sqlite3, shutil, sys
from comparison_corpus import corpus
from mcpclient import BENCH, ENGRAM, ENGRAM_QUIET_ENV
EHOME = os.path.join(BENCH, "ehome"); shutil.rmtree(EHOME, ignore_errors=True); os.makedirs(EHOME)
env = dict(os.environ, HOME=EHOME, ENGRAM_DATA_DIR=os.path.join(EHOME, "data"), **ENGRAM_QUIET_ENV)
for p in ("alpha-api", "beta-web"): os.makedirs(os.path.join(BENCH, "work", p), exist_ok=True)
for m in corpus():
    cmd = [ENGRAM, "save", m["title"], m["content"], "--type", m["type"], "--project", m["project"]]
    if m["topic"]: cmd += ["--topic", m["topic"]]
    r = subprocess.run(cmd, env=env, cwd=os.path.join(BENCH, "work", m["project"]), capture_output=True, text=True)
    if r.returncode: sys.exit(f"save failed: {m['key']}: {r.stderr}")
db = os.path.join(EHOME, "data", "engram.db")
con = sqlite3.connect(db)
rows = con.execute("select id, title, project from observations where deleted_at is null").fetchall()
by = {(t, p): i for i, t, p in rows}
keymap = {m["key"]: by[(m["title"], m["project"])] for m in corpus()}
json.dump(keymap, open(os.path.join(BENCH, "keymap_engram.json"), "w"))
print(len(rows), "observations in", db)
