"""The text the vocabulary is pruned against: the first N articles of each of
Leteo's thirteen interface languages, from the public `wikimedia/wikipedia`
dump at a pinned revision, streamed in dataset order.

No sampling and no shuffling, so a rerun reads the same text. Writes
<out>/<lang>.txt, one article per line, cut at MAX_CHARS so a long article does
not out-weigh the rest of its language.

usage: fetch_corpus.py <out-dir>
"""

import os
import sys

from datasets import load_dataset

LANGS = "ca de en es eu fr gl it nl pl pt ro sv".split()
SNAPSHOT = "20231101"
# The dataset revision the snapshot was read at. A moving `main` would change
# the text under the same snapshot name if the dataset were ever re-uploaded.
REVISION = "b04c8d1ceb2f5cd4588862100d08de323dccfbaa"
ARTICLES = 4000
MAX_CHARS = 6000


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    for lang in LANGS:
        path = os.path.join(out, f"{lang}.txt")
        if os.path.exists(path):
            continue
        rows = load_dataset(
            "wikimedia/wikipedia",
            f"{SNAPSHOT}.{lang}",
            split="train",
            streaming=True,
            revision=REVISION,
        )
        with open(path + ".tmp", "w") as handle:
            for index, row in enumerate(rows):
                if index >= ARTICLES:
                    break
                handle.write(row["text"][:MAX_CHARS].replace("\n", " ") + "\n")
        os.rename(path + ".tmp", path)
        print(lang, os.path.getsize(path), flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
