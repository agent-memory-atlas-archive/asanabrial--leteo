"""Fails when the release binary is larger than its budget.

A limit that is only written down is not a limit (`AGENTS.md`, rule 4). The
binary is 17,206,608 bytes on the machine it was measured on, and the model is a
file beside it and no part of that: the budget bounds the code, and does not move
when the model does. 20,000,000 bytes, decimal, is that size and a margin of
2.8 MB (16%) for what differs between platforms and toolchains -- the CI build is
Linux, the measurement was arm64 macOS -- and for the dependencies that will be
added. It is about the room a new tokenizer or HTTP stack takes; a dependency of
that size should have to say so here. `openspec/specs/search.md` §15 states the
measurement.

usage: check_binary_size.py <path-to-leteo>
"""

import os
import sys

# One place. The spec states the measurement, and says this is the bound.
LIMIT_BYTES = 20_000_000


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
