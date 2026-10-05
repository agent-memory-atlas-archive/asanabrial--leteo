"""Deterministic gzip: the same input, level and zlib give the same bytes.

Several things this repository ships are generated text that nobody reads line by
line: the hard-set questions and the model's tokenizer vocabulary. Stored as plain
JSON they are hundreds of kilobytes of diff; stored compressed they are a binary
blob the review leaves out, and what stands in for the review is a pair of
SHA-256s beside them -- of the compressed bytes and of what they decompress to.

The header carries no file name and a zero modification time, so nothing but the
content and the compression level reaches the output. Level 9 on the zlib this was
made with. A different zlib build may choose different but equally valid bytes, which
is why the decompressed hash is recorded as well; it is the one the checks fail on, and
a changed stored hash with an unchanged decompressed one is only reported.

usage: pack_gz.py <file> [<file> ...]     writes <file>.gz beside each
"""

import gzip
import sys


def pack(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=9, mtime=0)


if __name__ == "__main__":
    for path in sys.argv[1:]:
        with open(path, "rb") as source, open(path + ".gz", "wb") as target:
            target.write(pack(source.read()))
