//! The Snowball index: every memory stemmed in the language it was written in.

use super::*;
use crate::settings::Interface;

fn store_in(language: Interface) -> (TempDir, Store) {
    let temp = TempDir::new().unwrap();
    let mut config = StoreConfig::new(temp.path().join("leteo.db"));
    config.memory_language = Some(language);
    let mut store = Store::open(config).unwrap();
    store.create_session("s1", "leteo", "C:/repo").unwrap();
    (temp, store)
}

fn reopen_in(temp: &TempDir, language: Interface) -> Store {
    let mut config = StoreConfig::new(temp.path().join("leteo.db"));
    config.memory_language = Some(language);
    Store::open(config).unwrap()
}

/// What a question finds by the strict pass alone, so that neither a widened or
/// nearest rescue nor a corrected term can stand in for the stemmer being asked
/// about.
fn strict(store: &Store, query: &str) -> Vec<String> {
    let (found, _, corrections) = store
        .search_with_more_and_corrections(query, SearchOptions::default())
        .unwrap();
    if !corrections.is_empty() {
        return Vec::new();
    }
    found
        .into_iter()
        .filter(|result| !result.partial)
        .map(|result| result.observation.title)
        .collect()
}

fn languages(store: &Store) -> Vec<(String, String)> {
    let mut statement = store
        .connection
        .prepare(
            "SELECT o.title, s.language FROM observation_stems s
             JOIN observations o ON o.id = s.observation_id ORDER BY o.id",
        )
        .unwrap();
    statement
        .query_map([], |row| Ok((row.get(0)?, row.get(1)?)))
        .unwrap()
        .collect::<Result<_, _>>()
        .unwrap()
}

/// One memory and one question per language, the question reaching the memory
/// only through another inflection of a word it holds, at least three edits from
/// it so neither `porter` nor the typo stage can answer. The English store is the
/// control, as in the Spanish test below.
#[test]
fn every_language_with_a_stemmer_finds_a_memory_by_another_inflection() {
    let cases = [
        (
            Interface::Spanish,
            "Cuánto tarda la reindexación completa",
            "reindexar",
        ),
        (
            Interface::Portuguese,
            "A reindexação completa leva quatro minutos",
            "reindexar",
        ),
        (
            Interface::French,
            "Meilisearch tolère les fautes de frappe",
            "tolérait",
        ),
        (
            Interface::German,
            "Wir müssen jeden Aufruf verarbeiten",
            "Verarbeitungen",
        ),
        (
            Interface::Italian,
            "La reindicizzazione completa dura quattro minuti",
            "reindicizzare",
        ),
        (
            Interface::Romanian,
            "Meilisearch tolerează greșeli de scriere",
            "greșelilor",
        ),
        (
            Interface::Dutch,
            "We willen alle teksten vertalen",
            "vertalingen",
        ),
        (
            Interface::Swedish,
            "Migrering av sökningen",
            "migreringarna",
        ),
    ];
    for (language, title, question) in cases {
        let (_temp, mut store) = store_in(language);
        store
            .add_observation(observation("s1", title, "Anteckning."))
            .unwrap();
        assert_eq!(strict(&store, question), [title], "{language:?}");

        let (_other, mut english) = store_in(Interface::English);
        english
            .add_observation(observation("s1", title, "Anteckning."))
            .unwrap();
        assert!(strict(&english, question).is_empty(), "{language:?}");
    }
}

/// `porter` is an English algorithm, and `ejecuta` and `ejecutaron` are two words
/// to it — three edits apart, which is past what the typo stage reads as the
/// same word, so a pass here is the stemmer and not a correction. The control is the same memory in a store that writes English: the
/// question finds nothing there, which is what makes the first half of this a
/// measurement of the Spanish stemmer and not of anything `porter` already did.
#[test]
fn a_spanish_store_finds_a_memory_by_another_inflection_of_its_word() {
    let (_temp, mut spanish) = store_in(Interface::Spanish);
    spanish
        .add_observation(observation(
            "s1",
            "El cron ejecuta la conciliación bancaria",
            "Cada noche.",
        ))
        .unwrap();
    assert_eq!(
        strict(&spanish, "ejecutaron"),
        ["El cron ejecuta la conciliación bancaria"]
    );
    assert_eq!(
        strict(&spanish, "conciliaciones"),
        ["El cron ejecuta la conciliación bancaria"]
    );

    let (_other, mut english) = store_in(Interface::English);
    english
        .add_observation(observation(
            "s1",
            "El cron ejecuta la conciliación bancaria",
            "Cada noche.",
        ))
        .unwrap();
    assert!(strict(&english, "ejecutaron").is_empty());
}

#[test]
fn a_spanish_inflection_in_the_body_is_found_as_well_as_one_in_the_title() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    store
        .add_observation(observation(
            "s1",
            "Una nota",
            "La migración de los datos terminó sin errores.",
        ))
        .unwrap();
    assert_eq!(strict(&store, "migraciones"), ["Una nota"]);
}

/// The language is the one the row was written in, and it survives a change of
/// setting: a store that wrote Spanish and now writes English still holds Spanish
/// memories, and the question is stemmed for them because the *rows* say so.
#[test]
fn each_row_keeps_the_language_it_was_stemmed_in_through_a_change_of_setting() {
    let (temp, mut store) = store_in(Interface::Spanish);
    store
        .add_observation(observation("s1", "Ejecuta el cron", "Cada noche."))
        .unwrap();
    drop(store);

    let mut store = reopen_in(&temp, Interface::English);
    store
        .add_observation(observation("s1", "Runs the nightly job", "Every night."))
        .unwrap();

    assert_eq!(
        languages(&store),
        [
            ("Ejecuta el cron".to_owned(), "es".to_owned()),
            ("Runs the nightly job".to_owned(), "en".to_owned()),
        ]
    );
    assert_eq!(strict(&store, "ejecutaron"), ["Ejecuta el cron"]);
    assert_eq!(strict(&store, "running"), ["Runs the nightly job"]);
}

/// Both languages in one store, each found by its own morphology and neither
/// answering for the other.
#[test]
fn a_store_holding_both_languages_answers_each() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    store
        .add_observation(observation("s1", "Ejecuta el cron", "Cada noche."))
        .unwrap();
    store
        .add_observation(observation("s1", "The cron runs nightly", "Reconciles."))
        .unwrap();
    assert_eq!(strict(&store, "ejecutaron"), ["Ejecuta el cron"]);
    assert_eq!(strict(&store, "running"), ["The cron runs nightly"]);
}

/// A revision re-stems: the words the memory used to hold stop finding it and the
/// words it holds now start to.
#[test]
fn a_revision_by_topic_key_is_stemmed_again() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    let mut first = observation("s1", "Tarea", "El cron ejecuta la conciliación.");
    first.topic_key = Some("architecture/cron".to_owned());
    store.add_observation(first).unwrap();
    let mut second = observation("s1", "Tarea", "El cron sincroniza los saldos.");
    second.topic_key = Some("architecture/cron".to_owned());
    store.add_observation(second).unwrap();

    assert_eq!(strict(&store, "sincronizaron"), ["Tarea"]);
    assert!(strict(&store, "ejecutaron").is_empty());
}

#[test]
fn an_edit_through_update_is_stemmed_again() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    let saved = store
        .add_observation(observation(
            "s1",
            "Tarea",
            "El cron ejecuta la conciliación.",
        ))
        .unwrap()
        .observation;
    store
        .update_observation(
            saved.id,
            None,
            UpdateObservation {
                content: Some("El cron sincroniza los saldos.".to_owned()),
                ..Default::default()
            },
        )
        .unwrap();
    assert_eq!(strict(&store, "sincronizaron"), ["Tarea"]);
    assert!(strict(&store, "ejecutaron").is_empty());
}

/// A pulled mutation writes through its own `INSERT` and `UPDATE`, which no
/// other write path shares.
#[test]
fn a_memory_pulled_from_a_peer_is_stemmed() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    let payload = |content: &str| {
        serde_json::json!({
            "sync_id": "obs-remote-1",
            "session_id": "s1",
            "type": "discovery",
            "title": "Nota remota",
            "content": content,
            "project": "leteo",
            "scope": "project",
            "created_at": "2026-01-01 00:00:00",
            "updated_at": "2026-01-01 00:00:00",
        })
        .to_string()
    };
    let mutation = |seq: i64, content: &str| SyncMutation {
        seq,
        target_key: "cloud".to_owned(),
        entity: "observation".to_owned(),
        entity_key: "obs-remote-1".to_owned(),
        op: crate::sync::OP_UPSERT.to_owned(),
        payload: payload(content),
        source: "remote".to_owned(),
        project: "leteo".to_owned(),
        occurred_at: "2026-01-01 00:00:00".to_owned(),
        acked_at: None,
    };
    store
        .apply_pulled_sync_mutation("cloud", &mutation(1, "El cron ejecuta la conciliación."))
        .unwrap();
    assert_eq!(strict(&store, "ejecutaron"), ["Nota remota"]);

    store
        .apply_pulled_sync_mutation("cloud", &mutation(2, "El cron sincroniza los saldos."))
        .unwrap();
    assert_eq!(strict(&store, "sincronizaron"), ["Nota remota"]);
    assert!(strict(&store, "ejecutaron").is_empty());
}

#[test]
fn an_import_stems_what_it_brings() {
    let (_source_temp, mut source) = store_in(Interface::Spanish);
    source
        .add_observation(observation("s1", "El cron ejecuta", "Cada noche."))
        .unwrap();
    let exported = source.export().unwrap();

    let (_target_temp, mut target) = store_in(Interface::Spanish);
    target.import(&exported).unwrap();
    assert_eq!(strict(&target, "ejecutaron"), ["El cron ejecuta"]);
    assert!(
        crate::store::schema::missing_full_text_triggers(target.connection()).is_empty(),
        "the import put every trigger back"
    );
}

#[test]
fn a_project_merge_moves_the_stems_with_the_memory() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    store
        .add_observation(observation("s1", "El cron ejecuta", "Cada noche."))
        .unwrap();
    store.merge_project("leteo", "otro").unwrap();

    let narrowed = |project: &str| {
        store
            .search(
                "ejecutaron",
                SearchOptions {
                    project: Some(project.to_owned()),
                    ..Default::default()
                },
            )
            .unwrap()
            .len()
    };
    assert_eq!(narrowed("otro"), 1);
    assert_eq!(narrowed("leteo"), 0);
}

#[test]
fn deleting_a_memory_removes_its_stems_and_their_index_entries() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    let saved = store
        .add_observation(observation("s1", "El cron ejecuta", "Cada noche."))
        .unwrap()
        .observation;
    store.delete_observation(saved.id, None, true).unwrap();

    assert!(languages(&store).is_empty());
    let indexed: i64 = store
        .connection
        .query_row(
            "SELECT COUNT(*) FROM observations_stemmed WHERE observations_stemmed MATCH 'ejecut'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(indexed, 0);
}

/// A repair has to put back what a lost trigger cost, and the stems are one more
/// thing a lost trigger costs: rebuilding the index over a stems table that never
/// saw the memory would leave it unfindable however often it ran.
#[test]
fn a_repair_stems_the_memories_written_while_the_triggers_were_gone() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    for name in crate::store::schema::FULL_TEXT_TRIGGERS {
        store
            .connection
            .execute_batch(&format!("DROP TRIGGER IF EXISTS {name};"))
            .unwrap();
    }
    store
        .add_observation(observation("s1", "El cron ejecuta", "Cada noche."))
        .unwrap();
    assert!(strict(&store, "ejecutaron").is_empty());

    store.restore_full_text_triggers().unwrap();
    store.rebuild_full_text_indexes().unwrap();
    assert_eq!(strict(&store, "ejecutaron"), ["El cron ejecuta"]);
}

/// The migration stems the rows that were there, in the language the setting
/// names when it runs.
#[test]
fn the_migration_stems_existing_rows_in_the_language_of_the_setting() {
    let (temp, mut store) = store_in(Interface::English);
    store
        .add_observation(observation("s1", "El cron ejecuta", "Cada noche."))
        .unwrap();
    store
        .connection
        .execute_batch(
            "DROP TRIGGER obs_stems_insert; DROP TRIGGER obs_stems_update;
             DROP TRIGGER stems_fts_insert; DROP TRIGGER stems_fts_delete;
             DROP TRIGGER stems_fts_update;
             DROP TABLE observations_stemmed; DROP TABLE observation_stems;
             PRAGMA user_version = 20;",
        )
        .unwrap();
    drop(store);

    let store = reopen_in(&temp, Interface::Spanish);
    assert_eq!(
        languages(&store),
        [("El cron ejecuta".to_owned(), "es".to_owned())]
    );
    assert_eq!(strict(&store, "ejecutaron"), ["El cron ejecuta"]);
}

#[test]
fn a_connection_that_never_registered_the_functions_cannot_write_a_memory() {
    let (temp, store) = store_in(Interface::Spanish);
    drop(store);
    let raw = Connection::open(temp.path().join("leteo.db")).unwrap();
    let refused = raw
        .execute(
            "INSERT INTO observations (session_id, type, title, content, scope)
             VALUES ('s1', 'discovery', 'x', 'y', 'project')",
            [],
        )
        .unwrap_err();
    assert!(
        refused.to_string().contains("no such function"),
        "{refused}"
    );
}

#[test]
fn doctor_names_a_store_whose_stems_went_missing_and_the_repair_puts_them_back() {
    let (_temp, mut store) = store_in(Interface::Spanish);
    store
        .add_observation(observation("s1", "El cron ejecuta", "Cada noche."))
        .unwrap();
    assert!(store.doctor().unwrap().healthy);

    store
        .connection
        .execute("DELETE FROM observation_stems", [])
        .unwrap();
    let report = store.doctor().unwrap();
    assert!(
        report
            .checks
            .iter()
            .any(|check| check.code == "observation_stems_sync" && !check.ok),
        "{:?}",
        report.issues
    );

    store.rebuild_full_text_indexes().unwrap();
    assert!(store.doctor().unwrap().healthy);
    assert_eq!(strict(&store, "ejecutaron"), ["El cron ejecuta"]);
}

/// The languages the setting offers that still have no second stemmer are four,
/// and `search.md` §16 names them and what each lacks. A fifth gaining an arm, or
/// one of the four gaining one, is a reason to edit that paragraph.
#[test]
fn the_languages_without_a_stemmer_are_the_four_the_spec_names() {
    let without: Vec<Interface> = Interface::ALL
        .into_iter()
        .filter(|language| *language != Interface::English)
        .filter(|language| crate::stemming::algorithm(*language).is_none())
        .collect();
    assert_eq!(
        without,
        [
            Interface::Catalan,
            Interface::Galician,
            Interface::Basque,
            Interface::Polish
        ]
    );
}
