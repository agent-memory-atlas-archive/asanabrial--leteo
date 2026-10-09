//! What this binary is, not only what version it claims.
//!
//! `--version` printed `CARGO_PKG_VERSION` and nothing else, so every build
//! between releases printed the last release's number. A binary built from
//! `main` on 2026-10-06 reported `leteo 0.2.1` while it already understood
//! schema 22, which no released 0.2.1 does: an agent pointed at a real 0.2.1
//! then failed with "this database is at schema version 22, but this build of
//! Leteo understands 18", and nothing told the two binaries apart. The commit
//! and the schema are what tell them apart.
//!
//! The commit and the dirty flag are established by `build.rs` at compile time;
//! the schema version is the constant the migrations are numbered by.

use std::sync::LazyLock;

use crate::store::SCHEMA_VERSION;

/// The build identity, as `leteo --version` prints it after the name.
///
/// The commit is absent when the build had no git to read — a crates.io tarball,
/// or a source copy without `.git` — and is the one fact that can be missing.
/// The version and the schema it supports are always known, so those are always
/// printed.
pub fn version() -> &'static str {
    static VERSION: LazyLock<String> = LazyLock::new(|| {
        compose(
            option_env!("LETEO_GIT_COMMIT"),
            option_env!("LETEO_GIT_DIRTY").is_some(),
        )
    });
    &VERSION
}

/// The identity, from the two facts the build script could establish.
///
/// Split out from [`version`] so its shape is testable without a git checkout:
/// a commit, a dirty tree, and neither are the three cases, and this is where
/// their format is held.
fn compose(commit: Option<&str>, dirty: bool) -> String {
    let version = env!("CARGO_PKG_VERSION");
    let suffix = match (commit, dirty) {
        (Some(commit), true) => format!(" ({commit}-dirty, schema {SCHEMA_VERSION})"),
        (Some(commit), false) => format!(" ({commit}, schema {SCHEMA_VERSION})"),
        (None, _) => format!(" (schema {SCHEMA_VERSION})"),
    };
    format!("{version}{suffix}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_identity_names_the_schema_and_the_commit_when_it_has_one() {
        let version = env!("CARGO_PKG_VERSION");
        assert_eq!(
            compose(Some("f712df8"), false),
            format!("{version} (f712df8, schema {SCHEMA_VERSION})")
        );
        assert_eq!(
            compose(Some("f712df8"), true),
            format!("{version} (f712df8-dirty, schema {SCHEMA_VERSION})")
        );
        // The build without git: the version and the schema are still there.
        assert_eq!(
            compose(None, false),
            format!("{version} (schema {SCHEMA_VERSION})")
        );
    }
}
