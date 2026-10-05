-- Stems: a second stemmed index, for the language memories are written in.
--
-- `observations_fts` stems with `porter`, which is an English algorithm. It
-- folds `memoria`/`memorias` by accident of stripping a final `s` and nothing
-- else Spanish: `migración` and `migraciones` stay two terms, and so do
-- `ejecuta` and `ejecutó`. FTS5 takes its tokenizer from a fixed list, so a
-- Snowball stemmer written in Rust cannot be named in `tokenize =`. The text is
-- stemmed before it reaches an index instead, by `leteo_stem`, a SQL function
-- the connection registers (`src/stemming.rs`), and indexed with plain
-- `unicode61`.
--
-- Every memory keeps `porter` in `observations_fts` — agents write English
-- terms into memories in any language — and gains one row here recording which
-- language it was stemmed in and what that stemmer made of it. The language is
-- the memory-writing setting at the moment the row is written, so the choice is
-- fixed per row and a later change of setting re-stems only the rows it touches.
-- A language with no stemmer yet has a row whose stems are empty: the language is
-- still recorded, which is what lets a later algorithm find the rows it owes.
--
-- A table of its own rather than columns on `observations`, for the reason
-- `0020_observation_vectors.sql` gives: `obs_fts_update` and `obs_exact_update`
-- are bare `AFTER UPDATE ON observations`, so a column written there re-indexes
-- the memory twice. This one is derived data, and nothing replicates or exports
-- it: each machine stems with its own setting.
--
-- The triggers are what make every write path stem, structurally. Nothing in
-- Rust has to remember: an insert, a revision, a project rename and a
-- replicated write all reach `observations`, and these fire on it. An import
-- is the exception, because it drops the triggers to build the indexes once at
-- the end; it stems the rows it wrote with `restem_observations` before the
-- rebuild. The cost is that a connection which has not registered both
-- functions cannot insert a memory or edit its text, and fails saying so rather
-- than leaving a row its index cannot find.
--
-- `ON DELETE CASCADE` for the three hard-delete paths, as the vectors table
-- does. Foreign keys are on for every connection, and the cascade fires the
-- index's delete trigger like any other delete.
--
-- Existing rows are stemmed here, in the language the setting names when this
-- runs. That is not what the writer of an old memory necessarily had, and it is
-- the only answer there is: nothing recorded one. A store whose setting is
-- `auto` gets English, which stems nothing, and its rows stay English: a row
-- keeps the language it was written in, and a rule that handed old rows to a new
-- setting could not tell a memory written in English from one written before the
-- setting was named. The rows a later write that changes the text touches take the language it names.

DROP TRIGGER IF EXISTS obs_stems_insert;
DROP TRIGGER IF EXISTS obs_stems_update;
DROP TRIGGER IF EXISTS stems_fts_insert;
DROP TRIGGER IF EXISTS stems_fts_delete;
DROP TRIGGER IF EXISTS stems_fts_update;
DROP TABLE IF EXISTS observations_stemmed;

CREATE TABLE IF NOT EXISTS observation_stems (
    observation_id INTEGER PRIMARY KEY REFERENCES observations(id) ON DELETE CASCADE,
    language TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    tool_name TEXT,
    type TEXT,
    project TEXT,
    topic_key TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_observation_stems_language ON observation_stems(language);

-- Only rows whose `id` is an integer: a database that predates the baseline can
-- carry a TEXT primary key, with a NULL among the values, and neither is a
-- parent a row here can reference. Such a row has no stems and no way to be
-- found by them; it is found by the other two indexes as before.
--
-- `tool_name`, `type` and `project` are copied as written, not stemmed. They are
-- identifiers, and `project` is what the search narrows on inside the index
-- (`normalize::fts_within_project`), which compares it with the name as typed.
-- The columns exist at all so that this index has the shape of the other two and
-- the one query builder serves all three.
INSERT OR REPLACE INTO observation_stems(
    observation_id, language, title, content, tool_name, type, project, topic_key
)
SELECT id, leteo_stem_language(),
       leteo_stem(title, leteo_stem_language()),
       leteo_stem(content, leteo_stem_language()),
       tool_name, type, project,
       leteo_stem(topic_key, leteo_stem_language())
FROM observations
WHERE typeof(id) = 'integer';

CREATE VIRTUAL TABLE observations_stemmed USING fts5(
    title, content, tool_name, type, project, topic_key,
    content='observation_stems', content_rowid='observation_id',
    tokenize = 'unicode61'
);


CREATE TRIGGER obs_stems_insert AFTER INSERT ON observations BEGIN
    INSERT INTO observation_stems(observation_id, language, title, content, tool_name, type, project, topic_key)
    VALUES (new.id, leteo_stem_language(), leteo_stem(new.title, leteo_stem_language()), leteo_stem(new.content, leteo_stem_language()), new.tool_name, new.type, new.project, leteo_stem(new.topic_key, leteo_stem_language()))
    ON CONFLICT(observation_id) DO UPDATE SET language = excluded.language, title = excluded.title, content = excluded.content, tool_name = excluded.tool_name, type = excluded.type, project = excluded.project, topic_key = excluded.topic_key;
END;
CREATE TRIGGER obs_stems_update AFTER UPDATE OF title, content, tool_name, type, project, topic_key ON observations BEGIN
    INSERT INTO observation_stems(observation_id, language, title, content, tool_name, type, project, topic_key)
    VALUES (new.id, leteo_stem_language(), leteo_stem(new.title, leteo_stem_language()), leteo_stem(new.content, leteo_stem_language()), new.tool_name, new.type, new.project, leteo_stem(new.topic_key, leteo_stem_language()))
    ON CONFLICT(observation_id) DO UPDATE SET language = excluded.language, title = excluded.title, content = excluded.content, tool_name = excluded.tool_name, type = excluded.type, project = excluded.project, topic_key = excluded.topic_key;
END;

CREATE TRIGGER stems_fts_insert AFTER INSERT ON observation_stems BEGIN
    INSERT INTO observations_stemmed(rowid, title, content, tool_name, type, project, topic_key)
    VALUES (new.observation_id, new.title, new.content, new.tool_name, new.type, new.project, new.topic_key);
END;
CREATE TRIGGER stems_fts_delete AFTER DELETE ON observation_stems BEGIN
    INSERT INTO observations_stemmed(observations_stemmed, rowid, title, content, tool_name, type, project, topic_key)
    VALUES ('delete', old.observation_id, old.title, old.content, old.tool_name, old.type, old.project, old.topic_key);
END;
CREATE TRIGGER stems_fts_update AFTER UPDATE ON observation_stems BEGIN
    INSERT INTO observations_stemmed(observations_stemmed, rowid, title, content, tool_name, type, project, topic_key)
    VALUES ('delete', old.observation_id, old.title, old.content, old.tool_name, old.type, old.project, old.topic_key);
    INSERT INTO observations_stemmed(rowid, title, content, tool_name, type, project, topic_key)
    VALUES (new.observation_id, new.title, new.content, new.tool_name, new.type, new.project, new.topic_key);
END;

-- Last, and after the triggers, as `observations_exact` is built: the rows above
-- were written before the index existed, and this is what indexes them.
INSERT INTO observations_stemmed(observations_stemmed) VALUES('rebuild');
