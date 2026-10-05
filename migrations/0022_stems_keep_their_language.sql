-- A row keeps the language it was stemmed in until its text changes.
--
-- Migration 21 re-recorded a row under the connection's language on every
-- update of `tool_name`, `type` or `project`, because those are copied into the
-- stems table and a copy has to follow. The same statement also wrote `language`
-- and re-stemmed the text. So a project merge, an Engram adoption that
-- normalises project names, or a replicated update that changed only a project,
-- run after the setting changed from Spanish to English, turned a Spanish memory
-- into an English one with no stems, and nothing said so.
--
-- Two triggers now, because they answer two questions. A write that changes the
-- text — title, content or topic key — is a new memory as far as stemming goes
-- and takes the language of the connection that wrote it. A write that changes
-- only an identifier keeps the language and the stems and refreshes the copies.
--
-- The text trigger also compares the values: `UPDATE OF` fires when a column is
-- named in the `SET` clause, whether or not its value changed, and a replicated
-- update names every column of the row it carries.
--
-- Neither calls a function the other does not need: an identifier update reads
-- nothing from `leteo_stem`, so a tool that edits a project directly does not
-- have to register it.

DROP TRIGGER IF EXISTS obs_stems_update;
DROP TRIGGER IF EXISTS obs_stems_identifiers;

CREATE TRIGGER obs_stems_update AFTER UPDATE OF title, content, topic_key ON observations
WHEN new.title IS NOT old.title OR new.content IS NOT old.content OR new.topic_key IS NOT old.topic_key BEGIN
    INSERT INTO observation_stems(observation_id, language, title, content, tool_name, type, project, topic_key)
    VALUES (new.id, leteo_stem_language(), leteo_stem(new.title, leteo_stem_language()), leteo_stem(new.content, leteo_stem_language()), new.tool_name, new.type, new.project, leteo_stem(new.topic_key, leteo_stem_language()))
    ON CONFLICT(observation_id) DO UPDATE SET language = excluded.language, title = excluded.title, content = excluded.content, tool_name = excluded.tool_name, type = excluded.type, project = excluded.project, topic_key = excluded.topic_key;
END;
CREATE TRIGGER obs_stems_identifiers AFTER UPDATE OF tool_name, type, project ON observations BEGIN
    UPDATE observation_stems SET tool_name = new.tool_name, type = new.type, project = new.project WHERE observation_id = new.id;
END;
