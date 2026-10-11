# Saved through `engram save` rather than SQL so its own save path builds the index.
import json, os, subprocess, sqlite3, shutil, sys
from comparison_corpus import corpus
from mcpclient import BENCH, ENGRAM, ENGRAM_QUIET_ENV


def load():
    # Removed first: the keymap is written last, so one left by an earlier run
    # would make a failed or partial load here look complete.
    try: os.remove(os.path.join(BENCH, "keymap_engram.json"))
    except FileNotFoundError: pass
    ehome = os.path.join(BENCH, "ehome"); shutil.rmtree(ehome, ignore_errors=True); os.makedirs(ehome)
    env = dict(os.environ, HOME=ehome, ENGRAM_DATA_DIR=os.path.join(ehome, "data"), **ENGRAM_QUIET_ENV)
    for p in ("alpha-api", "beta-web"): os.makedirs(os.path.join(BENCH, "work", p), exist_ok=True)
    for m in corpus():
        cmd = [ENGRAM, "save", m["title"], m["content"], "--type", m["type"], "--project", m["project"]]
        if m["topic"]: cmd += ["--topic", m["topic"]]
        r = subprocess.run(cmd, env=env, cwd=os.path.join(BENCH, "work", m["project"]), capture_output=True, text=True)
        if r.returncode: raise RuntimeError(f"save failed: {m['key']}: {r.stderr}")
    db = os.path.join(ehome, "data", "engram.db")
    con = sqlite3.connect(db)
    rows = con.execute("select id, title, project from observations where deleted_at is null").fetchall()
    by = {(t, p): i for i, t, p in rows}
    keymap = {m["key"]: by[(m["title"], m["project"])] for m in corpus()}
    json.dump(keymap, open(os.path.join(BENCH, "keymap_engram.json"), "w"))
    print(len(rows), "observations in", db)
    return keymap


if __name__ == "__main__":
    try:
        load()
    except RuntimeError as e:
        sys.exit(str(e))
