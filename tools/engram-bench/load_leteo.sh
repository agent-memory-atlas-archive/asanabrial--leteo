#!/bin/sh
# Adopts a copy, so the Engram store the benchmark reads is left as it was.
set -e
B=${BENCH_STATE:-${TMPDIR:-/tmp}/leteo-engram-bench}
L=${LETEO_BIN:-leteo}
rm -rf "$B/lhome" "$B/ecopy"; mkdir -p "$B/lhome" "$B/ecopy"
sqlite3 "$B/ehome/data/engram.db" ".backup '$B/ecopy/engram.db'"
HOME=$B/lhome "$L" import --from-engram --source "$B/ecopy/engram.db" --database "$B/lhome/leteo.db"
sqlite3 "$B/lhome/leteo.db" "select project, count(*) from observations group by 1"
