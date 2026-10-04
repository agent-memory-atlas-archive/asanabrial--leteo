-- Version history: the title and body a content-changing write replaced.
--
-- A topic-key upsert and a content-changing `mem_update` overwrite the row in
-- place and only bump `revision_count`, so the previous text was gone the
-- moment it was replaced. This table keeps it, one row per superseded
-- revision, so a read can hand the old text back byte for byte.
--
-- Keyed by the observation's `sync_id` and never by its local `id`: the same
-- memory has a different `id` on every machine, and versions replicate.
--
-- The unique index is the whole of the idempotency. A version arriving twice
-- over the wire — a retried pull, or the same payload applied on both the
-- local path and the replicated one — is `INSERT OR IGNORE`d against
-- `(observation_sync_id, revision)` and lands once.
--
-- `replaced_at` carries a default for a row written by hand during repairs;
-- every write from the store supplies it, because the value has to be the same
-- string on both machines or the two stores' versions disagree by a second.
--
-- Retention is the newest `OBSERVATION_VERSION_RETENTION` per observation,
-- applied by `snapshot_observation_version_tx` after every insert on both
-- write paths. The bound lives in the code rather than in a trigger so one
-- number governs the local path, the replicated path, and the tests.
--
-- No full-text index carries a column of this table, so the migration needs no
-- rebuild, and neither index is partial because every query over it names an
-- observation.

CREATE TABLE IF NOT EXISTS observation_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    observation_sync_id TEXT NOT NULL,
    revision INTEGER NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    replaced_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_observation_versions_identity
    ON observation_versions (observation_sync_id, revision);

CREATE INDEX IF NOT EXISTS idx_observation_versions_read
    ON observation_versions (observation_sync_id, revision DESC);
