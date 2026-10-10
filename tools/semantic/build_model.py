"""Builds the embedding model Leteo ships, from the model it is derived from.

    sentence-transformers/static-similarity-mrl-multilingual-v1   (Apache-2.0)
        -> truncated to the first DIMS columns   (Matryoshka: replaces PCA)
        -> quantised to int8 with model2vec's own routine
        -> its WordPiece vocabulary pruned to the pieces Leteo's languages use

and writes the three files the binary reads to <out-dir>:
config.json, model.safetensors, tokenizer.json.gz.

The tokenizer is 843 KB of one-line JSON that nobody reviews, so it is stored as
deterministic gzip (`pack_gz.py`) and the build checks both what is stored and
what it decompresses to. The second is the one that matters: another zlib may
write other valid bytes for the same vocabulary.

Every input is pinned: the source model at a revision, the corpus by
`fetch_corpus.py` at a dataset revision, and the technical English text at a
commit of this repository rather than at whatever the working tree holds today.
That last one matters. The text counted for the vocabulary includes Leteo's own
source and documents, and a build that read the working tree would produce
different weights after every edit to a document.

usage: build_model.py <corpus-dir> <out-dir> [--check]

`--check` compares the SHA-256 of what was built with `checksums.json` and exits
non-zero on a difference, so a reviewer can tell "these are the weights this
pipeline makes" from "these are bytes somebody put here".
"""

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections import Counter

import numpy as np
from huggingface_hub import snapshot_download
from model2vec.model import StaticModel
from model2vec.quantization import DType, quantize_embeddings
from safetensors.numpy import load_file, save_file
from tokenizers import Tokenizer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pack_gz import pack  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

SOURCE = "sentence-transformers/static-similarity-mrl-multilingual-v1"
SOURCE_REVISION = "b68f4122911bcffcd6e1f695f2d99cd6788972d8"
DIMS = 256
DTYPE = "int8"
# The commit whose files are the technical text counted into the vocabulary.
TECH_COMMIT = "058b2e3"
# A piece is kept when it occurs this many times in at least one language's
# text, so a small language is not out-voted by a large one.
MIN_COUNT = 5
SHIPPED = ("config.json", "model.safetensors", "tokenizer.json.gz")


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def convert(directory: str) -> None:
    """The source's float32 table, truncated, quantised, in model2vec's layout."""
    snapshot = snapshot_download(
        SOURCE,
        revision=SOURCE_REVISION,
        allow_patterns=["0_StaticEmbedding/*", "modules.json", "config_sentence_transformers.json"],
    )
    weights = load_file(os.path.join(snapshot, "0_StaticEmbedding", "model.safetensors"))
    table = next(iter(weights.values()))
    tokenizer = Tokenizer.from_file(os.path.join(snapshot, "0_StaticEmbedding", "tokenizer.json"))
    vectors = quantize_embeddings(table[:, :DIMS].copy(), DType(DTYPE))
    config = {
        "model_type": "model2vec",
        "architectures": ["StaticModel"],
        "tokenizer_name": SOURCE,
        "apply_pca": None,
        "hidden_dim": DIMS,
        "seq_length": 1000000,
        "normalize": True,
        "pooling": "mean",
        "m124_source": SOURCE,
        "m124_truncated_to": DIMS,
    }
    StaticModel(
        vectors=vectors,
        weights=None,
        token_mapping=None,
        tokenizer=tokenizer,
        config=config,
        base_model_name=SOURCE,
        language=None,
        normalize=True,
    ).save_pretrained(directory)


def technical_text() -> list[str]:
    """Leteo's own English text at TECH_COMMIT: source, specs, docs, tools."""

    def wanted(path: str) -> bool:
        parts = path.split("/")
        if any(part.startswith(".") for part in parts):
            return False
        if "/target/" in "/" + path or "/i18n/" in "/" + path:
            return False
        return (
            (path.startswith("src/") and path.endswith(".rs"))
            or (path.startswith("openspec/") and path.endswith(".md"))
            or (path.startswith("docs/") and path.endswith(".md"))
            or (path.startswith("tools/") and path.endswith((".py", ".rs")))
            or ("/" not in path and path.endswith(".md"))
        )

    listing = subprocess.run(
        ["git", "-C", REPO_ROOT, "ls-tree", "-r", "--name-only", TECH_COMMIT],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()
    lines: list[str] = []
    for path in sorted(p for p in listing if wanted(p)):
        blob = subprocess.run(
            ["git", "-C", REPO_ROOT, "show", f"{TECH_COMMIT}:{path}"],
            capture_output=True, check=True,
        ).stdout.decode("utf-8", errors="ignore")
        lines += [line for line in blob.splitlines() if line.strip()]
    return lines


def prune(source: str, destination: str, corpus: str) -> None:
    """Keeps the pieces Leteo's languages use, plus every way to spell a word.

    Every special token and every single-character piece (with or without
    `##`) in the Latin and punctuation ranges is kept, so a word can always be
    spelled and never falls to [UNK] for want of a piece.
    """
    specification = json.load(open(os.path.join(source, "tokenizer.json")))
    tokenizer = Tokenizer.from_file(os.path.join(source, "tokenizer.json"))
    vocabulary = specification["model"]["vocab"]
    inverse = {index: piece for piece, index in vocabulary.items()}

    counts: dict[str, Counter] = {}
    for name in sorted(os.listdir(corpus)):
        if not name.endswith(".txt"):
            continue
        counter: Counter = Counter()
        lines = open(os.path.join(corpus, name)).read().splitlines()
        for start in range(0, len(lines), 2000):
            for encoding in tokenizer.encode_batch(lines[start:start + 2000], add_special_tokens=False):
                counter.update(encoding.ids)
        counts[name[:-4]] = counter
    technical: Counter = Counter()
    for encoding in tokenizer.encode_batch(technical_text(), add_special_tokens=False):
        technical.update(encoding.ids)
    counts["tech"] = technical

    keep: set[int] = set()
    for counter in counts.values():
        keep |= {index for index, seen in counter.items() if seen >= MIN_COUNT}

    def single(piece: str) -> bool:
        bare = piece[2:] if piece.startswith("##") else piece
        return len(bare) == 1 and (ord(bare) < 0x0250 or 0x2000 <= ord(bare) < 0x2C00)

    keep |= {
        index for piece, index in vocabulary.items()
        if single(piece) or (piece.startswith("[") and piece.endswith("]"))
    }
    old = sorted(keep)
    specification["model"]["vocab"] = {inverse[o]: new for new, o in enumerate(old)}
    for added in specification.get("added_tokens", []):
        added["id"] = specification["model"]["vocab"].get(added["content"], added["id"])
    processor = specification.get("post_processor")
    if processor and "special_tokens" in processor:
        for special in processor["special_tokens"].values():
            special["ids"] = [specification["model"]["vocab"][t] for t in special["tokens"]]

    os.makedirs(destination, exist_ok=True)
    json.dump(specification, open(os.path.join(destination, "tokenizer.json"), "w"), ensure_ascii=False)
    weights = load_file(os.path.join(source, "model.safetensors"))
    save_file(
        {k: (v[old] if v.shape[0] == len(vocabulary) else v) for k, v in weights.items()},
        os.path.join(destination, "model.safetensors"),
    )
    open(os.path.join(destination, "config.json"), "w").write(
        open(os.path.join(source, "config.json")).read()
    )
    coverage = {
        lang: round(sum(n for i, n in c.items() if i in keep) / sum(c.values()), 5)
        for lang, c in counts.items()
    }
    print(f"kept {len(old)} of {len(vocabulary)} pieces; occurrence coverage {coverage}")


def main() -> int:
    corpus, out = sys.argv[1], sys.argv[2]
    with tempfile.TemporaryDirectory() as scratch:
        convert(scratch)
        prune(scratch, out, corpus)
    plain = os.path.join(out, "tokenizer.json")
    raw = open(plain, "rb").read()
    with open(plain + ".gz", "wb") as handle:
        handle.write(pack(raw))
    os.remove(plain)
    built = {name: sha256(os.path.join(out, name)) for name in SHIPPED}
    decompressed = {"tokenizer.json": hashlib.sha256(raw).hexdigest()}
    for name, digest in {**built, **decompressed}.items():
        print(f"{digest}  {name}")
    if "--check" in sys.argv:
        recorded = json.load(open(os.path.join(HERE, "checksums.json")))
        text = {
            name[:-4]: sha256(os.path.join(corpus, name))
            for name in sorted(os.listdir(corpus)) if name.endswith(".txt")
        }
        if text != recorded["corpus"]:
            print("the corpus is not the one checksums.json records", file=sys.stderr)
            return 1
        if built != recorded["files"] or decompressed != recorded["decompressed"]:
            print("DIFFERENT from checksums.json", file=sys.stderr)
            return 1
        print("identical to checksums.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
