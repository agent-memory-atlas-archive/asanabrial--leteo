//! Every command the README shows has to be one the binary accepts.
//!
//! Documentation drifts in silence. A flag renamed, a subcommand moved, and the
//! README keeps promising the old spelling — the code compiles, the tests pass,
//! and the first person to hit it is somebody following the instructions.
//!
//! This ran once by hand and found nothing wrong, which is exactly when a check
//! is worth keeping: it is cheap now and it is what notices the next rename.

use std::path::Path;

mod support;

use support::spelled;

use assert_cmd::Command;

/// Splits a shell-ish line, honouring the double quotes the README uses around
/// titles with spaces. Nothing here needs escapes or single quotes.
fn arguments(line: &str) -> Vec<String> {
    let mut parts = Vec::new();
    let mut current = String::new();
    let mut quoted = false;
    for character in line.chars() {
        match character {
            '"' => quoted = !quoted,
            c if c.is_whitespace() && !quoted => {
                if !current.is_empty() {
                    parts.push(std::mem::take(&mut current));
                }
            }
            c => current.push(c),
        }
    }
    if !current.is_empty() {
        parts.push(current);
    }
    parts
}

/// Every `leteo …` line inside a fenced code block, with trailing comments cut.
fn documented_commands(markdown: &str) -> Vec<Vec<String>> {
    let mut commands = Vec::new();
    let mut inside = false;
    for line in markdown.lines() {
        if line.trim_start().starts_with("```") {
            inside = !inside;
            continue;
        }
        let line = line.trim();
        if !inside || !line.starts_with("leteo ") {
            continue;
        }
        let line = line.split('#').next().unwrap_or(line).trim();
        let mut parts = arguments(line);
        if parts.is_empty() {
            continue;
        }
        parts.remove(0);
        if !parts.is_empty() {
            commands.push(parts);
        }
    }
    commands
}

#[test]
fn every_command_the_readme_shows_is_one_the_binary_accepts() {
    let readme = std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("README.md"))
        .expect("read README.md");
    let commands = documented_commands(&readme);
    assert!(
        commands.len() > 20,
        "the extractor found only {} commands, so it has stopped matching the README",
        commands.len()
    );

    let mut rejected = Vec::new();
    for parts in &commands {
        // `--help` makes clap walk the subcommand path and validate every flag,
        // then stop before any argument is required and before a database is
        // opened. So this checks the spelling without doing anything.
        let output = Command::cargo_bin("leteo")
            .expect("find leteo test binary")
            .args(parts)
            .arg("--help")
            .output()
            .expect("run leteo");
        if !output.status.success() {
            let reason = String::from_utf8_lossy(&output.stderr);
            let reason = reason.lines().next().unwrap_or("").to_owned();
            rejected.push(format!("leteo {} -> {reason}", parts.join(" ")));
        }
    }

    assert!(
        rejected.is_empty(),
        "the README documents commands this binary refuses:\n  {}",
        rejected.join("\n  ")
    );
}

#[test]
fn the_extractor_reads_a_fenced_block_the_way_the_readme_writes_one() {
    // The guard above is only as good as this, so it is worth its own test:
    // an extractor that quietly matched nothing would pass every time.
    let markdown = "text\n\n```powershell\nleteo save \"A title with spaces\" body --type decision\n\
                    leteo stats   # a trailing comment\n```\n\nprose mentioning leteo stats\n";

    let commands = documented_commands(markdown);

    assert_eq!(
        commands,
        vec![
            vec![
                "save".to_owned(),
                "A title with spaces".to_owned(),
                "body".to_owned(),
                "--type".to_owned(),
                "decision".to_owned()
            ],
            vec!["stats".to_owned()],
        ],
        "prose outside a fence is not a command, and a comment is not an argument"
    );
}

/// Every `LETEO_*` name the binary reads from its own source.
///
/// Read out of the source rather than out of a list somebody maintains: a list
/// is one more thing to forget, and this check exists because two were
/// forgotten already.
fn variables_the_binary_reads(source: &Path) -> Vec<String> {
    let mut found = Vec::new();
    let mut stack = vec![source.to_path_buf()];
    while let Some(path) = stack.pop() {
        let Ok(entries) = std::fs::read_dir(&path) else {
            continue;
        };
        for entry in entries.flatten() {
            let path = entry.path();
            if path.is_dir() {
                stack.push(path);
                continue;
            }
            if path.extension().is_none_or(|kind| kind != "rs") {
                continue;
            }
            let Ok(text) = std::fs::read_to_string(&path) else {
                continue;
            };
            // `#[arg(env = "…")]` and `env::var("…")` are the only two ways
            // this binary reaches for the environment.
            for marker in [
                "env = \"LETEO_",
                "env::var(\"LETEO_",
                "env::var_os(\"LETEO_",
            ] {
                for (index, _) in text.match_indices(marker) {
                    let rest = &text[index + marker.len() - "LETEO_".len()..];
                    let name: String = rest
                        .chars()
                        .take_while(|c| c.is_ascii_uppercase() || *c == '_')
                        .collect();
                    if !name.is_empty() && !found.contains(&name) {
                        found.push(name);
                    }
                }
            }
        }
    }
    found.sort();
    found
}

#[test]
fn every_environment_variable_the_binary_honours_is_documented() {
    // Two were not: `LETEO_CLOUD_SERVER`, which is how somebody points the
    // client at a cloud, and `LETEO_AGENT_CLI`, which chooses the model that
    // judges conflicts. Both changed behaviour and neither appeared in the
    // table anybody would read to find them.
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    let readme = std::fs::read_to_string(root.join("README.md")).expect("read README.md");
    let table: String = readme
        .lines()
        .skip_while(|line| !line.starts_with("## Environment"))
        .take_while(|line| !line.starts_with("## License"))
        .collect::<Vec<_>>()
        .join("\n");

    let read = variables_the_binary_reads(&root.join("src"));
    assert!(
        read.len() > 5,
        "the scanner found only {read:?}, so it has stopped matching the source"
    );

    let missing: Vec<&String> = read
        .iter()
        .filter(|name| !table.contains(name.as_str()))
        .collect();
    assert!(
        missing.is_empty(),
        "the binary reads these and the Environment table does not list them: {missing:?}"
    );
}

#[test]
fn every_count_the_readme_writes_out_matches_the_list_it_describes() {
    // A count in prose is a second copy of the list it counts. The skill said
    // "the three that change or count the whole store" beside an enumeration of
    // them, and a fourth would have been named in that same sentence and left
    // the word wrong; the same shape is here three times over, on the first
    // page anybody reads about this crate. None of the three was checked: the
    // README's commands and its environment table were, and its arithmetic was
    // not.
    // Read with the line wrapping collapsed, so a reflowed paragraph does not
    // read as a changed claim: every sentence below is wrapped in the file.
    let readme = std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("README.md"))
        .expect("read README.md");
    let readme = readme.split_whitespace().collect::<Vec<_>>().join(" ");

    let tools = leteo::mcp::PROFILE_AGENT.len() + leteo::mcp::PROFILE_ADMIN.len();
    assert!(
        readme.contains(&format!("A {tools}-tool MCP server")),
        "the README counts the MCP tools by hand and there are {tools}"
    );

    let clients = spelled(leteo::setup::supported_agents().len());
    assert!(
        readme.contains(&format!("setup support for {clients} MCP")),
        "the README counts the agents it can set up by hand and there are {clients}"
    );

    // The languages are not only counted but enumerated, and the count appears
    // three times over: once for the interface, once for the voice, and once to
    // say that `language` is not limited to them. All of them move together.
    let languages = leteo::settings::Interface::ALL;
    let spelled_languages = spelled(languages.len());
    for claim in [
        format!("{spelled_languages} offered for memories"),
        format!("It is the same {spelled_languages} languages"),
        format!("not limited to the {spelled_languages} above"),
    ] {
        assert!(
            readme.contains(&claim),
            "the README should say {claim:?}, because that is how many languages there are"
        );
    }
    let opening = format!(
        "{}{} languages",
        spelled_languages[..1].to_uppercase(),
        &spelled_languages[1..]
    );
    let at = readme
        .find(&opening)
        .expect("the README introduces the interface languages by counting them");
    let enumerated = &readme[at..readme.len().min(at + opening.len() + 200)];
    for language in languages {
        assert!(
            enumerated.contains(language.as_str()),
            "the README lists the interface languages and leaves out {}",
            language.as_str()
        );
    }
}
