//! The uninstall scripts decide that the binary started by looking for the line
//! `leteo uninstall --yes` prints first, and a shell script cannot read the
//! constant that holds it. This keeps their copies from drifting: a script
//! looking for stale text would count every binary as one that never started and
//! delete a model file the binary had chosen to keep.

use std::path::Path;

fn marker_lines_in(script: &str) -> Vec<String> {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("scripts")
        .join(script);
    let text = std::fs::read_to_string(&path).expect("read the script");
    text.lines()
        .filter(|line| !line.trim_start().starts_with('#'))
        .filter(|line| line.contains("uninstall: started"))
        .map(str::to_owned)
        .collect()
}

#[test]
fn the_uninstallers_look_for_exactly_the_line_the_binary_prints() {
    for script in ["uninstall.sh", "uninstall.ps1"] {
        let lines = marker_lines_in(script);
        assert_eq!(
            lines.len(),
            1,
            "{script} has to name the marker on exactly one line: {lines:?}"
        );
        assert!(
            lines[0].contains(&format!("'{}'", leteo::setup::UNINSTALL_STARTED))
                || lines[0].contains(&format!("\"{}\"", leteo::setup::UNINSTALL_STARTED)),
            "{script} looks for a different line than the binary prints: {}",
            lines[0]
        );
    }
}

/// A binary built before the marker existed is recognised by its report, and the
/// scripts match one line of it. The report is what `print_json` makes of a
/// `Removal`, so the line is taken from the real serialisation.
#[test]
fn the_uninstallers_recognise_a_line_of_the_report_the_binary_prints() {
    let removal = leteo::setup::Removal {
        dry_run: false,
        agents: Vec::new(),
        data_dir: std::path::PathBuf::new(),
        data_dir_removed: false,
        data_removed: false,
        data_kept: false,
        memories: None,
        binary: None,
        binary_removed: false,
        model_files: Vec::new(),
        model_removed: true,
        remaining: Vec::new(),
    };
    let report = serde_json::to_string_pretty(&removal).expect("serialise the report");
    assert!(
        report
            .lines()
            .any(|line| line == "  \"model_removed\": true,"),
        "the report no longer has the line the scripts look for:\n{report}"
    );
    for script in ["uninstall.sh", "uninstall.ps1"] {
        let path = Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("scripts")
            .join(script);
        let text = std::fs::read_to_string(&path).expect("read the script");
        let named = text
            .lines()
            .filter(|line| !line.trim_start().starts_with('#'))
            .any(|line| line.contains("model_removed") && line.contains("(true|false),?"));
        assert!(
            named,
            "{script} does not match the report's model_removed line"
        );
    }
}
