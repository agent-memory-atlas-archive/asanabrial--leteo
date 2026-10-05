"""Fails when the release binary is larger than its budget.

A limit that is only written down is not a limit (`AGENTS.md`, rule 4). The
model is a file beside the binary and no part of its size: the budget bounds the
code, and does not move when the model does.

The bound follows the platform that runs this check, which is CI, and not the one
the code was written on. The same source is 21,052,600 bytes on ubuntu-latest and
17,206,608 on arm64 macOS; the first version of this check took the macOS number,
set 20,000,000, and failed on Linux. 24,000,000 bytes, decimal, is the Linux size
and a margin of 2.9 MB (14%) for toolchain drift and for the dependencies that
will be added. It is about the room a new tokenizer or HTTP stack takes; a
dependency of that size should have to say so here. `openspec/specs/search.md`
§15 states the measurement.

usage: check_binary_size.py <path-to-leteo>
"""

import os
import sys

LIMIT_BYTES = 24_000_000


def main() -> int:
    path = sys.argv[1]
    if not os.path.isfile(path):
        print(f"binary size check could not run: {path} is not a file")
        return 2
    size = os.path.getsize(path)
    verdict = "ok" if size <= LIMIT_BYTES else "OVER THE BUDGET"
    print(f"{path}: {size:,} bytes ({size / 1e6:.2f} MB), budget {LIMIT_BYTES:,} bytes: {verdict}")
    return 0 if size <= LIMIT_BYTES else 1


if __name__ == "__main__":
    sys.exit(main())
