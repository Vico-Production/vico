//! Starts, watches and stops the Python engine.
//!
//! The engine gets a random per-launch token through its environment, binds to
//! 127.0.0.1 on a free port and prints `VICO_READY port=<n>`. Its stdin is a pipe held
//! by this process, so if Vico dies the engine sees EOF and exits too.

use serde_json::{json, Value};
use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::mpsc;
use std::sync::Mutex;
use std::time::Duration;

const READY_TIMEOUT: Duration = Duration::from_secs(60);
const MAX_RESTARTS: u32 = 3;

#[derive(Default)]
struct Inner {
    child: Option<Child>,
    port: Option<u16>,
    status: &'static str,
    error: Option<String>,
    restarts: u32,
    resource_dir: Option<PathBuf>,
}

pub struct Sidecar {
    token: String,
    inner: Mutex<Inner>,
}

fn random_token() -> String {
    let mut bytes = [0u8; 32];
    getrandom::getrandom(&mut bytes).expect("system random source");
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

impl Sidecar {
    pub fn new() -> Self {
        Sidecar {
            token: random_token(),
            inner: Mutex::new(Inner { status: "starting", ..Default::default() }),
        }
    }

    pub fn token(&self) -> &str {
        &self.token
    }

    pub fn set_resource_dir(&self, dir: Option<PathBuf>) {
        self.inner.lock().unwrap().resource_dir = dir;
    }

    pub fn status(&self) -> Value {
        let inner = self.inner.lock().unwrap();
        json!({ "status": inner.status, "error": inner.error, "restarts": inner.restarts })
    }

    pub fn mark_unreachable(&self) {
        let mut inner = self.inner.lock().unwrap();
        inner.port = None;
    }

    /// Return the engine's port, starting or restarting it if needed.
    pub fn ensure_ready(&self) -> Result<u16, String> {
        let mut inner = self.inner.lock().unwrap();
        if let (Some(port), Some(child)) = (inner.port, inner.child.as_mut()) {
            if matches!(child.try_wait(), Ok(None)) {
                return Ok(port);
            }
        }
        if let Some(mut old) = inner.child.take() {
            let _ = old.kill();
            let _ = old.wait();
            inner.restarts += 1;
        }
        inner.port = None;
        if inner.restarts > MAX_RESTARTS {
            inner.status = "failed";
            let message = "The Vico engine keeps stopping. Restart Vico; if it continues, see the log in Vico's data folder.";
            inner.error = Some(message.into());
            return Err(message.into());
        }
        inner.status = "starting";
        match self.spawn(inner.resource_dir.clone()) {
            Ok((child, port)) => {
                inner.child = Some(child);
                inner.port = Some(port);
                inner.status = "ready";
                inner.error = None;
                Ok(port)
            }
            Err(message) => {
                inner.status = "failed";
                inner.error = Some(message.clone());
                inner.restarts += 1;
                Err(message)
            }
        }
    }

    fn command(&self, resource_dir: Option<PathBuf>) -> Result<Command, String> {
        if let Ok(python) = std::env::var("VICO_PYTHON") {
            return Ok(dev_command(PathBuf::from(python)));
        }
        if cfg!(debug_assertions) {
            let agent = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../services/agent");
            let python = if cfg!(windows) {
                agent.join(".venv/Scripts/python.exe")
            } else {
                agent.join(".venv/bin/python")
            };
            if python.exists() {
                return Ok(dev_command(python));
            }
        }
        let name = if cfg!(windows) { "vico-agent.exe" } else { "vico-agent" };
        let mut candidates = Vec::new();
        if let Ok(exe) = std::env::current_exe() {
            if let Some(dir) = exe.parent() {
                candidates.push(dir.join(name));
            }
        }
        if let Some(dir) = resource_dir {
            candidates.push(dir.join(name));
        }
        candidates
            .into_iter()
            .find(|p| p.exists())
            .map(Command::new)
            .ok_or_else(|| "The Vico engine (vico-agent) is missing from this installation.".to_string())
    }

    fn spawn(&self, resource_dir: Option<PathBuf>) -> Result<(Child, u16), String> {
        let mut cmd = self.command(resource_dir)?;
        cmd.env("VICO_TOKEN", &self.token)
            .env("PYTHONUTF8", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            cmd.creation_flags(CREATE_NO_WINDOW);
        }
        let mut child = cmd.spawn().map_err(|e| format!("Could not start the Vico engine: {e}"))?;
        let stdout = child.stdout.take().ok_or("engine has no stdout")?;
        let (tx, rx) = mpsc::channel::<u16>();
        std::thread::spawn(move || {
            let mut tx = Some(tx);
            for line in BufReader::new(stdout).lines().map_while(Result::ok) {
                if let Some(rest) = line.trim().strip_prefix("VICO_READY port=") {
                    if let (Ok(port), Some(sender)) = (rest.parse::<u16>(), tx.take()) {
                        let _ = sender.send(port);
                    }
                }
            }
        });
        match rx.recv_timeout(READY_TIMEOUT) {
            Ok(port) => Ok((child, port)),
            Err(_) => {
                let _ = child.kill();
                let _ = child.wait();
                Err("The Vico engine did not start in time.".into())
            }
        }
    }

    pub fn shutdown(&self) {
        let mut inner = self.inner.lock().unwrap();
        if let Some(mut child) = inner.child.take() {
            drop(child.stdin.take()); // EOF asks the engine to exit cleanly
            for _ in 0..20 {
                if matches!(child.try_wait(), Ok(Some(_))) {
                    break;
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            let _ = child.kill();
            let _ = child.wait();
        }
        inner.port = None;
        inner.status = "stopped";
    }
}

fn dev_command(python: PathBuf) -> Command {
    let agent = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../../services/agent");
    let mut cmd = Command::new(python);
    cmd.args(["-m", "app.main"]).current_dir(agent);
    cmd
}

#[cfg(test)]
mod tests {
    use super::random_token;

    #[test]
    fn tokens_are_random_and_long() {
        let a = random_token();
        let b = random_token();
        assert_eq!(a.len(), 64);
        assert_ne!(a, b);
    }
}
