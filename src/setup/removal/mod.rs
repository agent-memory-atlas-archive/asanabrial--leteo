use std::path::{Path, PathBuf};

use serde::Serialize;

use super::{SetupOptions, agents};

#[derive(Debug, Clone, Serialize)]
pub struct AgentRemoval {
    pub agent: &'static str,
    pub was_configured: bool,
    pub files_changed: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Removal {
    pub dry_run: bool,
    pub agents: Vec<AgentRemoval>,
    pub data_dir: PathBuf,
    pub data_dir_removed: bool,
    pub data_removed: bool,
    pub memories: Option<i64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub binary: Option<PathBuf>,
    pub binary_removed: bool,
    /// The model files taken out of the places the binary looks for them.
    pub model_files: Vec<PathBuf>,
    /// False when a model file was found and could not be deleted; a model that
    /// was never installed is not a failure.
    pub model_removed: bool,
    pub remaining: Vec<String>,
}

impl Removal {
    pub fn complete(&self) -> bool {
        self.agents.iter().all(|agent| agent.error.is_none())
            && (self.data_removed || self.dry_run)
            && (self.model_removed || self.dry_run)
    }
}

pub fn uninstall_everything(options: &SetupOptions, data_dir: &Path) -> Removal {
    uninstall_everything_for(options, data_dir, std::env::current_exe().ok())
}

/// [`uninstall_everything`] for a given executable, so the removal of what sits
/// beside it can be tested without being run against the test binary's own
/// directory.
fn uninstall_everything_for(
    options: &SetupOptions,
    data_dir: &Path,
    exe: Option<PathBuf>,
) -> Removal {
    let memories = count_memories(data_dir);
    let mut removed = Removal {
        dry_run: options.dry_run,
        agents: Vec::new(),
        data_dir: data_dir.to_path_buf(),
        data_dir_removed: false,
        data_removed: false,
        memories,
        binary: exe,
        binary_removed: false,
        model_files: Vec::new(),
        model_removed: false,
        remaining: Vec::new(),
    };

    for adapter in agents::REGISTRY {
        let was_configured = super::is_configured(adapter.slug, options);
        // Run even where nothing is configured. `is_configured` answers about
        // the MCP entry, and an agent can still be carrying a protocol block or
        // a stale hook from an older install — which is exactly the leftover
        // somebody uninstalling wants gone.
        let outcome = super::uninstall(adapter.slug, options);
        removed.agents.push(match outcome {
            Ok(result) => AgentRemoval {
                agent: adapter.slug,
                was_configured,
                files_changed: result.changed_files(),
                error: None,
            },
            Err(error) => AgentRemoval {
                agent: adapter.slug,
                was_configured,
                files_changed: 0,
                error: Some(error.to_string()),
            },
        });
    }

    // Before the data directory, because `<data dir>/model` is one of the places
    // and would otherwise keep the directory as something foreign.
    if !options.dry_run {
        remove_model(&mut removed, data_dir);
    }

    if !options.dry_run && data_dir.exists() {
        remove_data_directory(&mut removed, data_dir);
    }

    remove_binary(&mut removed, options.dry_run);
    removed
}

/// Everything Leteo creates in its data directory, by name.
///
/// Named rather than globbed, and the directory is emptied rather than deleted,
/// because `LETEO_DATA_DIR` points wherever somebody told it to. `remove_dir_all`
/// on that path is a program that deletes a directory it does not own — which
/// is exactly how other tools have taken people's own files with them on the way
/// out. Nothing here removes a thing it did not put there.
///
/// The suffixes cover SQLite's sidecars and the copies a migration leaves
/// behind; the prefixes cover the dated backups.
const DATA_DIR_FILES: &[&str] = &["leteo.db", "settings.json", "cloud.json", "store.db"];
const DATA_DIR_PREFIXES: &[&str] = &["leteo.db", "store.db", "backup-"];
const DATA_DIR_SUBDIRECTORIES: &[&str] = &["hooks"];

fn remove_data_directory(removed: &mut Removal, data_dir: &Path) {
    let Ok(entries) = std::fs::read_dir(data_dir) else {
        removed
            .remaining
            .push(format!("{}: could not be read", data_dir.display()));
        return;
    };
    let mut foreign = Vec::new();
    let failures_before = removed.remaining.len();
    for entry in entries.flatten() {
        let name = entry.file_name().to_string_lossy().into_owned();
        let is_ours = DATA_DIR_FILES.contains(&name.as_str())
            || DATA_DIR_SUBDIRECTORIES.contains(&name.as_str())
            || DATA_DIR_PREFIXES
                .iter()
                .any(|prefix| name.starts_with(prefix));
        if !is_ours {
            foreign.push(name);
            continue;
        }
        let outcome = if entry.path().is_dir() {
            std::fs::remove_dir_all(entry.path())
        } else {
            std::fs::remove_file(entry.path())
        };
        if let Err(error) = outcome {
            removed
                .remaining
                .push(format!("{}: {error}", entry.path().display()));
        }
    }
    removed.data_removed = removed.remaining.len() == failures_before;
    if foreign.is_empty() {
        match std::fs::remove_dir(data_dir) {
            Ok(()) => removed.data_dir_removed = true,
            Err(error) => removed
                .remaining
                .push(format!("{}: {error}", data_dir.display())),
        }
    } else {
        removed.remaining.push(format!(
            "{} was kept: it holds {} that Leteo did not put there ({})",
            data_dir.display(),
            if foreign.len() == 1 {
                "a file"
            } else {
                "files"
            },
            foreign.join(", ")
        ));
    }
}

/// The model, from every place the binary looks for it except `LETEO_MODEL_DIR`.
///
/// The places are [`crate::semantic::locations_for`] -- the list the lookup
/// itself reads -- and the files are [`crate::semantic::MODEL_FILES`], so an
/// installer that puts the model somewhere the binary finds it is also somewhere
/// this takes it from. The variable is left out because it names a directory
/// somebody else chose and may share with other things. Files are removed by
/// name, then a directory only if that left it empty: `model/`, and
/// `share/leteo` above it, never `share/`.
fn remove_model(removed: &mut Removal, data_dir: &Path) {
    let mut failed = false;
    for directory in crate::semantic::locations_for(removed.binary.as_deref(), data_dir, None) {
        let mut took_any = false;
        for (name, _) in crate::semantic::MODEL_FILES {
            let file = directory.join(name);
            if std::fs::symlink_metadata(&file).is_err() {
                continue;
            }
            match std::fs::remove_file(&file) {
                Ok(()) => {
                    took_any = true;
                    removed.model_files.push(file);
                }
                Err(error) => {
                    failed = true;
                    removed
                        .remaining
                        .push(format!("{}: {error}", file.display()));
                }
            }
        }
        if !took_any {
            continue;
        }
        if std::fs::remove_dir(&directory).is_err() && directory.exists() {
            removed.remaining.push(format!(
                "{} was kept: it holds files that Leteo did not put there",
                directory.display()
            ));
            continue;
        }
        if let Some(parent) = directory.parent()
            && parent.file_name().is_some_and(|name| name == "leteo")
            && parent
                .parent()
                .and_then(Path::file_name)
                .is_some_and(|name| name == "share")
        {
            // A share/leteo that holds something else is somebody else's.
            let _ = std::fs::remove_dir(parent);
        }
    }
    removed.model_removed = !failed;
}

#[cfg(not(windows))]
fn remove_binary(removed: &mut Removal, dry_run: bool) {
    let Some(binary) = removed.binary.clone() else {
        return;
    };
    if dry_run {
        return;
    }
    match std::fs::remove_file(&binary) {
        Ok(()) => removed.binary_removed = true,
        Err(error) => removed
            .remaining
            .push(format!("{}: {error}", binary.display())),
    }
}

#[cfg(windows)]
fn remove_binary(removed: &mut Removal, _dry_run: bool) {
    let Some(binary) = removed.binary.clone() else {
        return;
    };
    // Not an error and not a failure to report as one: Windows holds a running
    // image open, and the only thing that can finish this is the script that is
    // not the binary.
    removed.remaining.push(format!(
        "{} is still here: Windows cannot delete a running program. \
         Remove Leteo from Settings > Installed apps, or run uninstall.ps1 \
         beside it, which also takes the PATH entry and the registry key.",
        binary.display()
    ));
}

fn count_memories(data_dir: &Path) -> Option<i64> {
    let database = data_dir.join("leteo.db");
    if !database.exists() {
        return None;
    }
    let connection = rusqlite::Connection::open_with_flags(
        &database,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    )
    .ok()?;
    connection
        .query_row(
            "SELECT COUNT(*) FROM observations WHERE deleted_at IS NULL",
            [],
            |row| row.get(0),
        )
        .ok()
}

#[cfg(test)]
mod tests;
