"""mem0 behind a line protocol: one JSON object per line in, one per line out.

mem0 is a Python SDK, not a server, so the harness runs it in its own isolated
environment (`uv run --with mem0ai==...`) and talks to it through this script
rather than importing it. The first line is the configuration; every later line
is an `add` or a `search`.

stdout is the protocol, so the library's own prints are sent to stderr before
anything is imported: one stray line on stdout would be read as a reply.
"""
import json
import sys

PROTOCOL = sys.stdout
sys.stdout = sys.stderr


def reply(obj):
    PROTOCOL.write(json.dumps(obj, ensure_ascii=False) + "\n")
    PROTOCOL.flush()


def build(cfg):
    from mem0 import Memory
    from ollama import Client

    # The vector store is created with the embedder's width, which is a property
    # of the model and not something to type: a wrong number fails at the first
    # insert with an error that does not name the model.
    dims = len(Client(host=cfg["ollama_url"]).embed(model=cfg["embed_model"], input="width")["embeddings"][0])
    return Memory.from_config({
        "llm": {"provider": "ollama", "config": {"model": cfg["llm_model"], "ollama_base_url": cfg["ollama_url"],
                                                 "temperature": 0}},
        "embedder": {"provider": "ollama", "config": {"model": cfg["embed_model"], "ollama_base_url": cfg["ollama_url"],
                                                      "embedding_dims": dims}},
        "vector_store": {"provider": "qdrant", "config": {"path": cfg["dir"] + "/qdrant", "collection_name": "bench",
                                                          "embedding_model_dims": dims, "on_disk": True}},
        "history_db_path": cfg["dir"] + "/history.db",
    })


def main():
    memory = build(json.loads(sys.stdin.readline()))
    reply({"ready": True})
    for line in sys.stdin:
        req = json.loads(line)
        try:
            if req["op"] == "add":
                out = memory.add(req["text"], user_id=req["user"], metadata={"key": req["key"]}, infer=req["infer"])
                reply({"events": [e.get("event") for e in out.get("results", [])]})
            elif req["op"] == "search":
                out = memory.search(req["query"], filters={"user_id": req["user"]}, top_k=req["limit"])
                reply({"hits": [{"key": (h.get("metadata") or {}).get("key"), "text": h.get("memory", "")}
                                for h in out.get("results", [])]})
            else:
                reply({"error": f"unknown op {req['op']!r}"})
        except Exception as e:  # noqa: BLE001 - reported to the harness, which names it
            reply({"error": f"{type(e).__name__}: {e}"})


main()
