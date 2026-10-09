//! The build identity the binary prints: the commit it was built from, and
//! whether the tree was dirty when it was.
//!
//! `cargo` runs this before the crate compiles, so the two facts are fixed into
//! the binary as environment variables the code reads with `option_env!`.
//! Nothing here fails the build. A crates.io tarball has no `.git` and a source
//! copy may have no `git` binary; either is a build that simply does not know
//! its commit, which is the one fact that can be missing.

use std::process::Command;

/// The trimmed stdout of one `git` invocation, or `None` when git is absent,
/// the command failed, or it printed nothing.
fn git(args: &[&str]) -> Option<String> {
    let output = Command::new("git").args(args).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let text = String::from_utf8_lossy(&output.stdout).trim().to_owned();
    (!text.is_empty()).then_some(text)
}

fn main() {
    println!("cargo:rerun-if-changed=build.rs");

    // The git directory rather than the checkout: in a worktree `.git` is a file
    // pointing elsewhere, and HEAD and the index live wherever it points. Asking
    // git is what makes a checkout that moved rebuild the identity it prints.
    if let Some(git_dir) = git(&["rev-parse", "--absolute-git-dir"]) {
        println!("cargo:rerun-if-changed={git_dir}/HEAD");
        println!("cargo:rerun-if-changed={git_dir}/index");
    }

    let Some(commit) = git(&["rev-parse", "--short", "HEAD"]) else {
        return;
    };
    println!("cargo:rustc-env=LETEO_GIT_COMMIT={commit}");

    // `--porcelain` lists tracked changes and untracked files that are not
    // ignored, so `target/` and the like never make a clean build look dirty.
    if git(&["status", "--porcelain"]).is_some() {
        println!("cargo:rustc-env=LETEO_GIT_DIRTY=1");
    }
}
