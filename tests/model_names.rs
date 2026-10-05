//! The uninstall scripts name the model's files, and a shell script cannot read
//! `MODEL_FILES`. This is what keeps their copies from drifting: a file added to
//! the list that the scripts never learn about would survive an uninstall.
//!
//! It reads code lines only; a comment is skipped, as it is everywhere here.

use std::collections::BTreeSet;
use std::path::Path;

fn names_in(script: &str) -> BTreeSet<String> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("scripts")
        .join(script);
    let text = std::fs::read_to_string(&path).expect("read the script");
    let lines: Vec<&str> = text
        .lines()
        .filter(|line| !line.trim_start().starts_with('#'))
        .filter(|line| line.contains("safetensors"))
        .collect();
    assert_eq!(
        lines.len(),
        1,
        "{script} has to name the model's files on exactly one line: {lines:?}"
    );
    lines[0]
        .split(|c: char| !(c.is_ascii_alphanumeric() || c == '.' || c == '_'))
        .filter(|word| word.contains('.'))
        .map(str::to_owned)
        .collect()
}

#[test]
fn the_uninstallers_name_exactly_the_files_the_binary_checks() {
    let expected: BTreeSet<String> = leteo::semantic::MODEL_FILES
        .iter()
        .map(|(name, _)| (*name).to_owned())
        .collect();
    for script in ["uninstall.sh", "uninstall.ps1"] {
        assert_eq!(names_in(script), expected, "{script}");
    }
}
