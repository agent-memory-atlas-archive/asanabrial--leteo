//! The second stemmer: a Snowball stemmer for the language memories are written in.
//!
//! FTS5 takes its tokenizer from a fixed list, so a stemmer written in Rust
//! cannot be named in `tokenize =`. The words are stemmed *before* they reach an
//! index instead, by the two SQL functions registered here, and the index that
//! holds them (`observations_stemmed`) tokenises plain `unicode61`. The query side
//! applies the same function, so a word and the stem it was indexed under meet.
//!
//! Which languages have a stemmer is the one table in [`algorithm`]; every other
//! place asks it.

use std::borrow::Cow;

use rusqlite::Connection;
use rusqlite::functions::FunctionFlags;

use crate::settings::Interface;

/// The Snowball algorithm for a language, where this build has one.
///
/// Two sources are behind it, and the split is measured rather than tidy; the
/// table in [`algorithm`] says which language comes from which and why.
pub enum Algorithm {
    /// One of the eight `rust-stemmers` carries.
    Rust(rust_stemmers::Algorithm),
    /// One of the three only `snowball_stemmers_rs` carries.
    Snowball(snowball_stemmers_rs::Algorithm),
}

/// A stemmer over either source, so `stem_text` does not branch per word.
enum Stemmer {
    Rust(rust_stemmers::Stemmer),
    Snowball(snowball_stemmers_rs::Stemmer),
}

impl Stemmer {
    fn create(algorithm: Algorithm) -> Self {
        match algorithm {
            Algorithm::Rust(algorithm) => Self::Rust(rust_stemmers::Stemmer::create(algorithm)),
            Algorithm::Snowball(algorithm) => {
                Self::Snowball(snowball_stemmers_rs::Stemmer::create(algorithm))
            }
        }
    }

    fn stem<'a>(&self, word: &'a str) -> Cow<'a, str> {
        match self {
            Self::Rust(stemmer) => stemmer.stem(word),
            Self::Snowball(stemmer) => stemmer.stem(word),
        }
    }
}

/// The Snowball algorithm for a language, where this build has one.
///
/// English is absent on purpose: `porter` already indexes every memory, and a
/// row's English stems are those. Galician is absent because it has no Snowball
/// algorithm at all, and borrowing one was measured and declined; the set that
/// measured it and `search.md` §16 record why. The other eleven languages the
/// setting offers each have an arm: Spanish, Portuguese, French, German,
/// Italian, Romanian, Dutch and Swedish come from `rust-stemmers`, and Catalan,
/// Basque and Polish, which it does not carry, come from
/// `snowball_stemmers_rs`. A row in a language with no arm here is recorded
/// under it and gets `porter` alone.
///
/// The two sources are not interchangeable. `snowball_stemmers_rs` also carries
/// the eight, but it disagrees with `rust-stemmers` on words they already index
/// — Dutch alone differs on 102,728 words of this repository's own vocabulary —
/// so the eight keep the source their floors were measured against.
///
/// A language added here needs a set in `tools/engram-bench/inflection_sets.py`
/// and a floor for it: a stemmer that no query can tell from `porter` is not
/// shipping anything.
pub fn algorithm(language: Interface) -> Option<Algorithm> {
    Some(match language {
        Interface::Spanish => Algorithm::Rust(rust_stemmers::Algorithm::Spanish),
        Interface::Portuguese => Algorithm::Rust(rust_stemmers::Algorithm::Portuguese),
        Interface::French => Algorithm::Rust(rust_stemmers::Algorithm::French),
        Interface::German => Algorithm::Rust(rust_stemmers::Algorithm::German),
        Interface::Italian => Algorithm::Rust(rust_stemmers::Algorithm::Italian),
        Interface::Romanian => Algorithm::Rust(rust_stemmers::Algorithm::Romanian),
        Interface::Dutch => Algorithm::Rust(rust_stemmers::Algorithm::Dutch),
        Interface::Swedish => Algorithm::Rust(rust_stemmers::Algorithm::Swedish),
        Interface::Catalan => Algorithm::Snowball(snowball_stemmers_rs::Algorithm::Catalan),
        Interface::Basque => Algorithm::Snowball(snowball_stemmers_rs::Algorithm::Basque),
        Interface::Polish => Algorithm::Snowball(snowball_stemmers_rs::Algorithm::Polish),
        _ => return None,
    })
}

/// The language a settings value names, or English when it names none.
///
/// `None` is the setting's "the language of the conversation", which says
/// nothing about what was written, so it indexes as English and gets `porter`
/// alone rather than a guess.
pub fn memory_language(setting: Option<&str>) -> Interface {
    setting.and_then(Interface::parse).unwrap_or_default()
}

/// The code a row is recorded under.
pub fn code(language: Interface) -> &'static str {
    language.code()
}

/// The language a recorded code names, if it is one Leteo speaks.
pub fn from_code(code: &str) -> Option<Interface> {
    Interface::ALL
        .into_iter()
        .find(|language| language.code() == code)
}

/// The text as the language's stemmer reads it: lowercased words, stemmed,
/// separated by single spaces.
///
/// Words are cut where `unicode61` would cut them — at anything that is not a
/// letter or a digit — so a query term and an indexed word that the index would
/// have treated as one token are one token here too. A language with no
/// stemmer yields nothing, which is what leaves a row's stems empty.
pub fn stem_text(text: &str, language: Interface) -> String {
    let Some(algorithm) = algorithm(language) else {
        return String::new();
    };
    let stemmer = Stemmer::create(algorithm);
    let mut stemmed = String::with_capacity(text.len());
    for word in text.split(|c: char| !c.is_alphanumeric()) {
        if word.is_empty() {
            continue;
        }
        if !stemmed.is_empty() {
            stemmed.push(' ');
        }
        stemmed.push_str(&stemmer.stem(&word.to_lowercase()));
    }
    stemmed
}

/// Makes the two functions the stem triggers call available on a connection.
///
/// Both are needed by an insert or an edit of a memory's text, because the
/// triggers call them; a delete or an edit of `tool_name`, `type` or `project`
/// calls neither. `leteo_stem_language()` is what a row written on this
/// connection is recorded under. It is fixed for the life of the connection: a long-running server
/// keeps stemming in the language it opened with until it is restarted.
///
/// Every connection that writes `observations` has to have registered these,
/// because the triggers call them. A foreign connection that does not fails the
/// write with "no such function" rather than leaving a row its index cannot find.
pub fn register(connection: &Connection, language: Interface) -> rusqlite::Result<()> {
    let flags = FunctionFlags::SQLITE_UTF8
        | FunctionFlags::SQLITE_DETERMINISTIC
        | FunctionFlags::SQLITE_INNOCUOUS;
    connection
        .create_scalar_function("leteo_stem_language", 0, flags, move |_| Ok(code(language)))?;
    connection.create_scalar_function("leteo_stem", 2, flags, |context| {
        let text: Option<String> = context.get(0)?;
        let code: Option<String> = context.get(1)?;
        Ok(match (text, code.as_deref().and_then(from_code)) {
            (Some(text), Some(language)) => stem_text(&text, language),
            _ => String::new(),
        })
    })?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn spanish_inflections_share_a_stem() {
        let stems = |text| stem_text(text, Interface::Spanish);
        assert_eq!(stems("migración"), stems("migraciones"));
        assert_eq!(stems("ejecuta"), stems("ejecutó"));
        assert_eq!(stems("Migraciones, de datos"), "migracion de dat");
    }

    #[test]
    fn the_registered_function_stems_by_the_code_a_row_records() {
        let connection = Connection::open_in_memory().unwrap();
        register(&connection, Interface::Spanish).unwrap();
        let (language, stems, unknown): (String, String, String) = connection
            .query_row(
                "SELECT leteo_stem_language(), leteo_stem('ejecutó', 'es'), leteo_stem('ejecutó', 'zz')",
                [],
                |row| Ok((row.get(0)?, row.get(1)?, row.get(2)?)),
            )
            .unwrap();
        assert_eq!(language, "es");
        assert_eq!(stems, "ejecut");
        assert_eq!(unknown, "");
    }

    #[test]
    fn a_language_without_a_stemmer_yields_nothing() {
        assert_eq!(stem_text("migrations", Interface::English), "");
        assert_eq!(stem_text("migracións", Interface::Galician), "");
    }

    /// The three languages `rust-stemmers` does not carry are stemmed by the
    /// other source. Each pair is an inflection the memory index has to fold
    /// together, and the exact stem is pinned so a swap between the two
    /// implementations is a failing test rather than a silent re-index.
    #[test]
    fn catalan_basque_and_polish_inflections_share_a_stem() {
        assert_eq!(
            stem_text("configuració", Interface::Catalan),
            stem_text("configuracions", Interface::Catalan)
        );
        assert_eq!(stem_text("configuracions", Interface::Catalan), "configur");
        assert_eq!(
            stem_text("bilaketa", Interface::Basque),
            stem_text("bilaketak", Interface::Basque)
        );
        assert_eq!(stem_text("bilaketak", Interface::Basque), "bila");
        assert_eq!(
            stem_text("migracja", Interface::Polish),
            stem_text("migracje", Interface::Polish)
        );
        assert_eq!(stem_text("migracje", Interface::Polish), "migracj");
    }

    #[test]
    fn every_language_is_recorded_under_a_code_that_reads_back() {
        for language in Interface::ALL {
            assert_eq!(from_code(code(language)), Some(language));
        }
    }
}
