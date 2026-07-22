use serde::{Deserialize, Serialize};
use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::net::{Shutdown, TcpStream, ToSocketAddrs};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{Manager, State};

const HTTP_ADDR: &str = "127.0.0.1:9876";
const PIPE_PATH: &str = r"\\.\pipe\zcode-sidecar-spike";
const MAX_RESTARTS: u32 = 3;

#[derive(Debug, Serialize)]
struct SidecarStatus {
    healthy: bool,
    running: bool,
    restart_count: u32,
    restart_limit_reached: bool,
}

#[derive(Debug, Deserialize)]
struct HealthResponse {
    status: String,
    nonce: String,
    pid: u32,
}

#[derive(Debug, Deserialize)]
struct PipeResponse {
    echoed: Option<String>,
    nonce: Option<String>,
    error: Option<String>,
}

#[cfg(windows)]
struct JobHandle(isize);

#[cfg(windows)]
impl Drop for JobHandle {
    fn drop(&mut self) {
        unsafe {
            windows_sys::Win32::Foundation::CloseHandle(self.0 as _);
        }
    }
}

struct SidecarController {
    child: Mutex<Option<Child>>,
    stopping: AtomicBool,
    restart_count: AtomicU32,
    python: String,
    sidecar: PathBuf,
    run_nonce: String,
    #[cfg(windows)]
    job: Mutex<Option<JobHandle>>,
}

impl SidecarController {
    fn new(python: String, sidecar: PathBuf) -> Self {
        let run_nonce = format!(
            "{}-{}",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap_or_default()
                .as_nanos()
        );
        Self {
            child: Mutex::new(None),
            stopping: AtomicBool::new(false),
            restart_count: AtomicU32::new(0),
            python,
            sidecar,
            run_nonce,
            #[cfg(windows)]
            job: Mutex::new(None),
        }
    }

    fn spawn_child(&self) -> std::io::Result<Child> {
        let is_executable = self
            .sidecar
            .extension()
            .and_then(|extension| extension.to_str())
            .is_some_and(|extension| extension.eq_ignore_ascii_case("exe"));
        let mut command = if is_executable {
            Command::new(&self.sidecar)
        } else {
            let mut python = Command::new(&self.python);
            python.arg(&self.sidecar);
            python
        };
        command
            .current_dir(self.sidecar.parent().unwrap_or_else(|| Path::new(".")))
            .env("PYTHONUNBUFFERED", "1")
            .env("ZCODE_RUN_NONCE", &self.run_nonce)
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            command.creation_flags(0x08000000);
        }
        let mut child = command.spawn()?;
        #[cfg(windows)]
        if let Err(error) = self.assign_to_job(&child) {
            let _ = child.kill();
            let _ = child.wait();
            return Err(error);
        }
        Ok(child)
    }

    #[cfg(windows)]
    fn assign_to_job(&self, child: &Child) -> std::io::Result<()> {
        use std::mem::{size_of, zeroed};
        use std::os::windows::io::AsRawHandle;
        use windows_sys::Win32::System::JobObjects::{
            AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation,
            SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
        };

        let mut guard = self.job.lock().unwrap();
        if guard.is_none() {
            let handle = unsafe { CreateJobObjectW(std::ptr::null(), std::ptr::null()) };
            if handle.is_null() {
                return Err(std::io::Error::last_os_error());
            }
            let mut limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = unsafe { zeroed() };
            limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            let configured = unsafe {
                SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    &mut limits as *mut _ as *mut _,
                    size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
                )
            };
            if configured == 0 {
                unsafe { windows_sys::Win32::Foundation::CloseHandle(handle) };
                return Err(std::io::Error::last_os_error());
            }
            *guard = Some(JobHandle(handle as isize));
        }
        let job = guard.as_ref().unwrap().0 as _;
        if unsafe { AssignProcessToJobObject(job, child.as_raw_handle() as _) } == 0 {
            return Err(std::io::Error::last_os_error());
        }
        Ok(())
    }

    fn start(&self) -> std::io::Result<()> {
        let child = self.spawn_child()?;
        self.child.lock().unwrap().replace(child);
        Ok(())
    }

    fn stop(&self) {
        self.stopping.store(true, Ordering::SeqCst);
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    fn monitor(self: Arc<Self>) {
        while !self.stopping.load(Ordering::SeqCst) {
            thread::sleep(Duration::from_millis(100));
            let exited = {
                let mut guard = self.child.lock().unwrap();
                match guard.as_mut() {
                    Some(child) => child
                        .try_wait()
                        .map(|status| status.is_some())
                        .unwrap_or(true),
                    None => true,
                }
            };
            if !exited || self.stopping.load(Ordering::SeqCst) {
                continue;
            }
            self.child.lock().unwrap().take();
            let attempt = self.restart_count.fetch_add(1, Ordering::SeqCst) + 1;
            if attempt > MAX_RESTARTS {
                break;
            }
            thread::sleep(Duration::from_millis(100 * u64::from(attempt)));
            if self.stopping.load(Ordering::SeqCst) {
                break;
            }
            match self.spawn_child() {
                Ok(mut child) => {
                    if self.stopping.load(Ordering::SeqCst) {
                        let _ = child.kill();
                        let _ = child.wait();
                        break;
                    }
                    self.child.lock().unwrap().replace(child);
                    if !wait_for_health(Duration::from_secs(5), &self.run_nonce) {
                        if let Some(mut unhealthy) = self.child.lock().unwrap().take() {
                            let _ = unhealthy.kill();
                            let _ = unhealthy.wait();
                        }
                    }
                }
                Err(_) => thread::sleep(Duration::from_secs(1)),
            }
        }
    }

    fn status(&self) -> SidecarStatus {
        let restart_count = self.restart_count.load(Ordering::SeqCst);
        SidecarStatus {
            healthy: wait_for_health(Duration::from_millis(250), &self.run_nonce),
            running: self.child.lock().unwrap().is_some(),
            restart_count,
            restart_limit_reached: restart_count > MAX_RESTARTS,
        }
    }
}

fn wait_for_health(timeout: Duration, expected_nonce: &str) -> bool {
    let deadline = Instant::now() + timeout;
    let address = HTTP_ADDR.to_socket_addrs().unwrap().next().unwrap();
    while Instant::now() < deadline {
        if let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_millis(100)) {
            let _ = stream.set_read_timeout(Some(Duration::from_millis(250)));
            let _ = stream.set_write_timeout(Some(Duration::from_millis(250)));
            if stream
                .write_all(b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
                .is_err()
            {
                continue;
            }
            let mut response = String::new();
            if stream.read_to_string(&mut response).is_err() {
                continue;
            }
            let _ = stream.shutdown(Shutdown::Both);
            let valid_health = response
                .split("\r\n\r\n")
                .nth(1)
                .and_then(|body| serde_json::from_str::<HealthResponse>(body).ok())
                .is_some_and(|health| {
                    health.status == "ready" && health.nonce == expected_nonce && health.pid > 0
                });
            if (response.starts_with("HTTP/1.0 200") || response.starts_with("HTTP/1.1 200"))
                && valid_health
            {
                return true;
            }
        }
        thread::sleep(Duration::from_millis(50));
    }
    false
}

#[cfg(windows)]
fn open_pipe_with_timeout(timeout: Duration) -> Result<File, String> {
    let deadline = Instant::now() + timeout;
    loop {
        match OpenOptions::new().read(true).write(true).open(PIPE_PATH) {
            Ok(pipe) => return Ok(pipe),
            Err(error)
                if matches!(error.raw_os_error(), Some(2 | 231)) && Instant::now() < deadline =>
            {
                thread::sleep(Duration::from_millis(2));
            }
            Err(error) => return Err(error.to_string()),
        }
    }
}

#[cfg(windows)]
fn pipe_echo(message: &str, expected_nonce: &str) -> Result<String, String> {
    let mut stream = open_pipe_with_timeout(Duration::from_secs(2))?;
    let payload = serde_json::json!({ "msg": message, "nonce": expected_nonce }).to_string();
    stream
        .write_all(payload.as_bytes())
        .map_err(|error| error.to_string())?;
    stream.flush().map_err(|error| error.to_string())?;
    let mut response = vec![0_u8; 65536];
    let size = stream
        .read(&mut response)
        .map_err(|error| error.to_string())?;
    let raw = String::from_utf8(response[..size].to_vec()).map_err(|error| error.to_string())?;
    let parsed: PipeResponse = serde_json::from_str(&raw).map_err(|error| error.to_string())?;
    if let Some(error) = parsed.error {
        return Err(error);
    }
    if parsed.nonce.as_deref() != Some(expected_nonce) || parsed.echoed.as_deref() != Some(message)
    {
        return Err("sidecar response identity mismatch".to_string());
    }
    Ok(raw)
}

#[tauri::command]
fn greet(name: &str) -> String {
    format!("Hello, {}! You've been greeted from Rust!", name)
}

#[tauri::command]
fn sidecar_status(state: State<'_, Arc<SidecarController>>) -> SidecarStatus {
    state.inner().as_ref().status()
}

#[tauri::command]
fn sidecar_echo(
    message: String,
    state: State<'_, Arc<SidecarController>>,
) -> Result<String, String> {
    #[cfg(windows)]
    return pipe_echo(&message, &state.run_nonce);
    #[cfg(not(windows))]
    Err("Named Pipe spike is Windows-only".to_string())
}

fn resolve_sidecar() -> (String, PathBuf) {
    let python = std::env::var("ZCODE_PYTHON").unwrap_or_else(|_| "python".to_string());
    let sidecar = std::env::var_os("ZCODE_SIDECAR")
        .map(PathBuf::from)
        .or_else(|| {
            std::env::current_exe().ok().and_then(|exe| {
                exe.parent().and_then(|directory| {
                    [
                        directory.join("sidecar").join("sidecar.exe"),
                        directory.join("sidecar.exe"),
                    ]
                    .into_iter()
                    .find(|candidate| candidate.exists())
                })
            })
        })
        .unwrap_or_else(|| PathBuf::from("sidecar.py"));
    (python, sidecar)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let (python, sidecar) = resolve_sidecar();
    let controller = Arc::new(SidecarController::new(python, sidecar));
    let monitor = controller.clone();

    controller.start().expect("failed to start sidecar");
    if !wait_for_health(Duration::from_secs(10), &controller.run_nonce) {
        controller.stop();
        panic!("sidecar did not become healthy in 10s");
    }
    thread::spawn(move || monitor.monitor());

    tauri::Builder::default()
        .manage(controller)
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![
            greet,
            sidecar_status,
            sidecar_echo
        ])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window.app_handle().state::<Arc<SidecarController>>();
                state.inner().as_ref().stop();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
