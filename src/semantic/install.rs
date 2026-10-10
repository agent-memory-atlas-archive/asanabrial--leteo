//! Getting the model onto a machine that arrived without it.
//!
//! One path, for every install that has no model beside it: `cargo install`, a
//! build from source, a distro package, a manager nobody has written yet.
//! Nothing here knows or asks which of them put the binary where it is. An install
//! that arrived with the model beside it never comes this way; this is for the rest.
//!
//! Both sources end in the same place and the same way. Every file is checked
//! against the hashes compiled into the binary *before* anything is written where
//! the model is looked for, the three go into a directory of their own, and that
//! directory is renamed into place, so a download that stops half-way, a hash that
//! does not match or a source that is not the model leaves what was there
//! untouched.

use std::path::{Path, PathBuf};
use std::time::Duration;

use anyhow::{Context, Result, bail};
use futures_util::StreamExt;

use super::{Directory, MODEL_FILES, REPOSITORY_MODEL_DIR, inspect, sha256_hex};

/// The environment variable that replaces [`release_base`], for a mirror or a
/// test.
pub const RELEASE_URL_ENV: &str = "LETEO_MODEL_URL";

/// How long the whole install may take, all three files together.
///
/// One deadline around the lot and not one per request: a per-request timeout
/// lets three slow files take three times as long, and a network that trickles
/// bytes never trips a timeout that only watches for silence. The model is 13 MB;
/// two minutes is a slow connection finishing it, and `setup` waits at most this
/// long after the agent is configured.
pub const INSTALL_DEADLINE: Duration = Duration::from_secs(120);

/// How long to wait for a server to answer at all, inside the deadline.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(15);

/// The most bytes a file may be before the download is abandoned.
///
/// Its size with a margin -- config.json is 432 bytes, the weights 12,596,056, the
/// gzipped tokenizer 320,621 -- so a server that answers with something else, or
/// never stops, is cut off at a known bound and not read into memory until the
/// deadline. The hash decides whether what came back is the model; this only
/// decides how much of a wrong answer is worth reading.
fn size_cap(name: &str) -> usize {
    match name {
        "model.safetensors" => 16 * 1024 * 1024,
        "tokenizer.json.gz" => 1024 * 1024,
        _ => 64 * 1024,
    }
}

/// The directory of the files of the tag that matches this binary.
///
/// The model is committed under [`REPOSITORY_MODEL_DIR`] at every tag, so the raw
/// files of `v<version>` exist for every release without any release step having
/// to publish them: `raw.githubusercontent.com/<owner>/<repo>/v<version>/<dir>`,
/// the owner and repository taken from the crate's own `repository` field. The
/// hashes compiled into the binary decide whether what comes back is the model, so
/// the address only has to be a place to ask.
///
/// `overridden` (`--url`) wins, then `LETEO_MODEL_URL`; both name a directory that
/// holds the three files under their own names.
pub fn release_base(overridden: Option<&str>) -> String {
    release_base_from(overridden, environment_url().as_deref())
}

/// [`release_base`] with the environment handed in, so a test depends on nothing
/// the developer who runs it has exported.
pub fn release_base_from(overridden: Option<&str>, environment: Option<&str>) -> String {
    overridden
        .or(environment)
        .filter(|value| !value.is_empty())
        .map(str::to_owned)
        .unwrap_or_else(default_base)
}

/// `LETEO_MODEL_URL`, read here and nowhere else; unit tests do not see it.
fn environment_url() -> Option<String> {
    if cfg!(test) {
        return None;
    }
    std::env::var(RELEASE_URL_ENV)
        .ok()
        .filter(|value| !value.is_empty())
}

/// `(owner, repository)` from `CARGO_PKG_REPOSITORY`, which has to be a
/// github.com address for the default download to mean anything.
fn repository() -> Option<(&'static str, &'static str)> {
    let rest = env!("CARGO_PKG_REPOSITORY")
        .strip_prefix("https://github.com/")?
        .trim_end_matches('/');
    let rest = rest.strip_suffix(".git").unwrap_or(rest);
    let (owner, name) = rest.split_once('/')?;
    (!owner.is_empty() && !name.is_empty() && !name.contains('/')).then_some((owner, name))
}

fn default_base() -> String {
    let (owner, name) = repository()
        .expect("Cargo.toml's `repository` must be a github.com/<owner>/<repo> address");
    format!(
        "https://raw.githubusercontent.com/{owner}/{name}/v{}/{}",
        env!("CARGO_PKG_VERSION"),
        REPOSITORY_MODEL_DIR
    )
}

/// The address of one model file under a directory of them.
pub fn asset_url(base: &str, name: &str) -> String {
    format!("{}/{name}", base.trim_end_matches('/'))
}

/// What an install put where.
#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct Installed {
    pub directory: PathBuf,
    pub files: Vec<String>,
}

/// Installs from a directory that holds the three files, for a machine with no
/// network: the `model/` of an archive that carries one, or a copy made elsewhere.
pub fn from_directory(source: &Path, data_dir: &Path) -> Result<Installed> {
    let bytes = match inspect(source) {
        Directory::Verified(bytes) => bytes,
        Directory::Empty => bail!("{} holds none of the model files", source.display()),
        Directory::Wrong(problems) => bail!(
            "{} is not the model this build accepts: {}",
            source.display(),
            problems.join("; ")
        ),
    };
    place(data_dir, bytes)
}

/// Downloads the three files from `base` and installs them, within
/// [`INSTALL_DEADLINE`].
pub async fn from_release(base: &str, data_dir: &Path) -> Result<Installed> {
    from_release_within(base, data_dir, INSTALL_DEADLINE).await
}

/// [`from_release`] with the deadline handed in.
pub async fn from_release_within(
    base: &str,
    data_dir: &Path,
    deadline: Duration,
) -> Result<Installed> {
    let bodies = tokio::time::timeout(deadline, fetch(base))
        .await
        .map_err(|_| {
            anyhow::anyhow!(
                "the download did not finish within {} seconds; nothing was installed",
                deadline.as_secs_f32()
            )
        })??;
    place(data_dir, bodies)
}

async fn fetch(base: &str) -> Result<[Vec<u8>; 3]> {
    let client = reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .user_agent(concat!("leteo/", env!("CARGO_PKG_VERSION")))
        .build()
        .context("could not build an HTTP client")?;
    let mut fetched = Vec::new();
    for (name, expected) in MODEL_FILES {
        let url = asset_url(base, name);
        let response = client
            .get(&url)
            .send()
            .await
            .with_context(|| format!("could not reach {url}"))?;
        if !response.status().is_success() {
            bail!("{url} answered {}", response.status());
        }
        let cap = size_cap(name);
        if response
            .content_length()
            .is_some_and(|length| length > cap as u64)
        {
            bail!("{url} is larger than the {cap} bytes {name} may be; nothing was installed");
        }
        let mut body = Vec::new();
        let mut stream = response.bytes_stream();
        while let Some(chunk) = stream.next().await {
            let chunk = chunk.with_context(|| format!("the download of {url} did not finish"))?;
            if body.len() + chunk.len() > cap {
                bail!("{url} is larger than the {cap} bytes {name} may be; nothing was installed");
            }
            body.extend_from_slice(&chunk);
        }
        if sha256_hex(&body) != expected {
            bail!(
                "{url} is not the file this build accepts ({name} does not match its pinned SHA-256); nothing was installed"
            );
        }
        fetched.push(body);
    }
    Ok(<[Vec<u8>; 3]>::try_from(fetched).expect("one body per pinned file"))
}

/// Writes already-verified bytes into `<data dir>/model/`, all or nothing.
///
/// Written beside the destination under a name of its own and renamed over it, so
/// a reader never sees a model with some files new and some old. The previous
/// directory is moved aside first and put back if the rename fails; between the
/// two renames there is a moment with no model, and a search in it is a lexical
/// search, which is what it was before.
fn place(data_dir: &Path, bytes: [Vec<u8>; 3]) -> Result<Installed> {
    std::fs::create_dir_all(data_dir)
        .with_context(|| format!("could not create {}", data_dir.display()))?;
    let staging = data_dir.join(format!("model.new-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&staging);
    std::fs::create_dir(&staging)
        .with_context(|| format!("could not create {}", staging.display()))?;
    let outcome = (|| -> Result<()> {
        for ((name, _), body) in MODEL_FILES.iter().zip(&bytes) {
            std::fs::write(staging.join(name), body)
                .with_context(|| format!("could not write {name}"))?;
        }
        // The files on disk, not the bytes in memory: what was written is what
        // is checked, so a full disk or a bad write is caught here.
        match inspect(&staging) {
            Directory::Verified(_) => Ok(()),
            _ => bail!("the files written to {} do not verify", staging.display()),
        }
    })();
    if let Err(error) = outcome {
        let _ = std::fs::remove_dir_all(&staging);
        return Err(error);
    }

    let target = data_dir.join("model");
    let aside = data_dir.join(format!("model.old-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&aside);
    let had_one = target.exists();
    if had_one {
        std::fs::rename(&target, &aside)
            .with_context(|| format!("could not move {} aside", target.display()))?;
    }
    if let Err(error) = std::fs::rename(&staging, &target) {
        if had_one {
            let _ = std::fs::rename(&aside, &target);
        }
        let _ = std::fs::remove_dir_all(&staging);
        return Err(error)
            .with_context(|| format!("could not move the model into {}", target.display()));
    }
    let _ = std::fs::remove_dir_all(&aside);
    Ok(Installed {
        directory: target,
        files: MODEL_FILES
            .iter()
            .map(|(name, _)| (*name).to_owned())
            .collect(),
    })
}

#[cfg(test)]
mod tests {
    use super::super::tests::{needs_model, repository_model};
    use super::super::{Status, status};
    use super::*;
    use std::io::{Read, Write};
    use std::net::TcpListener;

    fn copy_model(into: &Path) {
        std::fs::create_dir_all(into).unwrap();
        for (name, _) in MODEL_FILES {
            std::fs::copy(repository_model().unwrap().join(name), into.join(name)).unwrap();
        }
    }

    /// A server on a port of its own that answers `GET /<path>` from a map, for
    /// as many requests as the test makes. Never the network.
    fn serve(files: Vec<(String, Vec<u8>)>) -> String {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            for stream in listener.incoming().flatten() {
                let mut stream = stream;
                let mut request = [0u8; 2048];
                let read = stream.read(&mut request).unwrap_or(0);
                let head = String::from_utf8_lossy(&request[..read]).into_owned();
                let path = head.split_whitespace().nth(1).unwrap_or("").to_owned();
                let reply = match files.iter().find(|(name, _)| *name == path) {
                    Some((_, body)) => {
                        let mut out = format!(
                            "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                            body.len()
                        )
                        .into_bytes();
                        out.extend_from_slice(body);
                        out
                    }
                    None => {
                        b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                            .to_vec()
                    }
                };
                let _ = stream.write_all(&reply);
            }
        });
        format!("http://{address}/v")
    }

    fn assets(corrupt: Option<&str>) -> Vec<(String, Vec<u8>)> {
        MODEL_FILES
            .iter()
            .map(|(name, _)| {
                let mut body = std::fs::read(repository_model().unwrap().join(name)).unwrap();
                if corrupt == Some(*name) {
                    body[10] ^= 0xff;
                }
                (format!("/v/{name}"), body)
            })
            .collect()
    }

    /// The address is shaped by this crate's own `repository` field and version,
    /// and by the directory the repository keeps the model in: the raw files of
    /// the tag. Unit-tested and never fetched.
    #[test]
    fn the_default_address_is_the_raw_files_of_the_tag_of_this_binary() {
        let (owner, name) = repository().expect("Cargo.toml's repository is a github.com address");
        assert_eq!(
            release_base_from(None, None),
            format!(
                "https://raw.githubusercontent.com/{owner}/{name}/v{}/assets/model",
                env!("CARGO_PKG_VERSION")
            )
        );
        assert_eq!(
            asset_url(&release_base_from(None, None), "config.json"),
            format!(
                "https://raw.githubusercontent.com/{owner}/{name}/v{}/assets/model/config.json",
                env!("CARGO_PKG_VERSION")
            ),
            "the files keep their own names"
        );
        assert_eq!(
            asset_url("http://h/v/", "config.json"),
            "http://h/v/config.json"
        );
        assert_eq!(
            release_base_from(Some("http://flag/x"), Some("http://env/y")),
            "http://flag/x"
        );
        assert_eq!(
            release_base_from(None, Some("http://env/y")),
            "http://env/y"
        );
        assert_eq!(
            release_base_from(None, Some("")),
            release_base_from(None, None)
        );
    }

    /// The path the address assumes is the path the tests read the model from, and
    /// the three files are there under the names the address will ask for.
    #[test]
    fn the_directory_the_address_names_is_the_one_the_repository_keeps_the_model_in() {
        assert!(release_base_from(None, None).ends_with(&format!("/{REPOSITORY_MODEL_DIR}")));
        let Some(directory) = repository_model() else {
            eprintln!("skipped: this tree has no assets/model");
            return;
        };
        assert_eq!(
            directory,
            Path::new(env!("CARGO_MANIFEST_DIR")).join(REPOSITORY_MODEL_DIR)
        );
        for (name, _) in MODEL_FILES {
            assert!(directory.join(name).is_file(), "{name}");
        }
    }

    /// A body larger than the file may be is abandoned, not read to the end.
    #[tokio::test]
    async fn a_body_larger_than_the_file_may_be_is_cut_off() {
        let data = tempfile::TempDir::new().unwrap();
        let base = serve(vec![("/v/config.json".to_owned(), vec![b'x'; 200 * 1024])]);
        let error = from_release(&base, data.path())
            .await
            .unwrap_err()
            .to_string();
        assert!(error.contains("larger than"), "{error}");
        assert_eq!(std::fs::read_dir(data.path()).unwrap().count(), 0);
    }

    /// One deadline for the whole install: a server that takes the connection and
    /// says nothing is given up on, whatever each request would have waited.
    #[tokio::test]
    async fn a_server_that_never_answers_is_given_up_on_at_the_deadline() {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        std::thread::spawn(move || {
            let held: Vec<_> = listener.incoming().flatten().collect();
            std::thread::sleep(Duration::from_secs(5));
            drop(held);
        });
        let data = tempfile::TempDir::new().unwrap();
        let started = std::time::Instant::now();
        let error = from_release_within(
            &format!("http://{address}/v"),
            data.path(),
            Duration::from_millis(300),
        )
        .await
        .unwrap_err()
        .to_string();
        assert!(error.contains("did not finish within"), "{error}");
        assert!(started.elapsed() < Duration::from_secs(3));
        assert_eq!(std::fs::read_dir(data.path()).unwrap().count(), 0);
    }

    #[test]
    fn a_local_copy_installs_and_verifies() {
        let Some(_) = needs_model!() else { return };
        let scratch = tempfile::TempDir::new().unwrap();
        let (copy, data) = (scratch.path().join("copy"), scratch.path().join("data"));
        copy_model(&copy);
        let done = from_directory(&copy, &data).unwrap();
        assert_eq!(done.directory, data.join("model"));
        assert_eq!(
            status(&data, Some(Path::new("/nonexistent"))),
            Status::Verified(data.join("model"))
        );
        assert_eq!(
            std::fs::read_dir(&data).unwrap().count(),
            1,
            "no staging directory is left behind"
        );
    }

    /// The refusals, each leaving what was already installed exactly as it was.
    #[test]
    fn a_missing_file_or_a_flipped_byte_installs_nothing_and_changes_nothing() {
        let Some(_) = needs_model!() else { return };
        let scratch = tempfile::TempDir::new().unwrap();
        let (copy, data) = (scratch.path().join("copy"), scratch.path().join("data"));
        copy_model(&copy);
        from_directory(&copy, &data).unwrap();
        let before = std::fs::read(data.join("model/model.safetensors")).unwrap();

        std::fs::remove_file(copy.join("config.json")).unwrap();
        let error = from_directory(&copy, &data).unwrap_err().to_string();
        assert!(error.contains("config.json is missing"), "{error}");

        copy_model(&copy);
        let mut bytes = std::fs::read(copy.join("model.safetensors")).unwrap();
        bytes[100] ^= 0x01;
        std::fs::write(copy.join("model.safetensors"), bytes).unwrap();
        let error = from_directory(&copy, &data).unwrap_err().to_string();
        assert!(
            error.contains("model.safetensors does not match"),
            "{error}"
        );

        assert_eq!(
            std::fs::read(data.join("model/model.safetensors")).unwrap(),
            before
        );
        assert!(matches!(
            status(&data, Some(Path::new("/nonexistent"))),
            Status::Verified(_)
        ));
        assert!(from_directory(&scratch.path().join("empty"), &data).is_err());
    }

    #[tokio::test]
    async fn a_release_is_downloaded_verified_and_placed() {
        let Some(_) = needs_model!() else { return };
        let data = tempfile::TempDir::new().unwrap();
        let base = serve(assets(None));
        let done = from_release(&base, data.path()).await.unwrap();
        assert_eq!(done.files.len(), 3);
        assert!(matches!(
            status(data.path(), Some(Path::new("/nonexistent"))),
            Status::Verified(_)
        ));
    }

    #[tokio::test]
    async fn a_download_that_is_not_the_model_or_not_there_installs_nothing() {
        let Some(_) = needs_model!() else { return };
        let data = tempfile::TempDir::new().unwrap();
        let base = serve(assets(Some("model.safetensors")));
        let error = from_release(&base, data.path())
            .await
            .unwrap_err()
            .to_string();
        assert!(
            error.contains("does not match its pinned SHA-256"),
            "{error}"
        );
        assert!(!data.path().join("model").exists());
        assert_eq!(
            std::fs::read_dir(data.path()).unwrap().count(),
            0,
            "nothing was left behind"
        );

        let base = serve(Vec::new());
        let error = from_release(&base, data.path())
            .await
            .unwrap_err()
            .to_string();
        assert!(error.contains("404"), "{error}");
        assert!(!data.path().join("model").exists());
    }
}
