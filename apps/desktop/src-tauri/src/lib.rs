use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use std::collections::BTreeMap;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU32, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use tauri::{Manager, State};

const PIPE_PATH: &str = r"\\.\pipe\zcode-control-core-v1";
const PROTOCOL_VERSION: u32 = 1;
const MAX_FRAME_SIZE: usize = 1 << 20;
const MAX_RESTARTS: u32 = 3;

#[derive(Debug, Serialize)]
struct SidecarStatus {
    healthy: bool,
    running: bool,
    restart_count: u32,
    restart_limit_reached: bool,
}

#[derive(Debug, Deserialize)]
struct HelloAck {
    version: u32,
    http_port: u16,
    http_token: String,
    sidecar_pid: u32,
    schema_version: String,
}

#[derive(Debug, Deserialize)]
struct IpcError {
    code: String,
    message: Option<String>,
}

#[derive(Debug, Deserialize)]
struct IpcResponse {
    ok: bool,
    data: Option<Value>,
    error: Option<IpcError>,
}

struct SidecarSession {
    stream: File,
    next_id: u64,
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
    session: Mutex<Option<SidecarSession>>,
    stopping: AtomicBool,
    restart_count: AtomicU32,
    restart_limit_reached: AtomicBool,
    python: String,
    sidecar: PathBuf,
    pipe_path: String,
    run_nonce: String,
    data_dir: PathBuf,
    #[cfg(windows)]
    job: Mutex<Option<JobHandle>>,
}

impl SidecarController {
    fn new(python: String, sidecar: PathBuf) -> std::io::Result<Self> {
        let data_dir = zcode_data_dir();
        fs::create_dir_all(data_dir.join("logs"))?;
        let mut random = [0_u8; 32];
        getrandom::fill(&mut random).map_err(|error| std::io::Error::other(error.to_string()))?;
        Ok(Self {
            child: Mutex::new(None),
            session: Mutex::new(None),
            stopping: AtomicBool::new(false),
            restart_count: AtomicU32::new(0),
            restart_limit_reached: AtomicBool::new(false),
            python,
            sidecar,
            pipe_path: env::var("ZCODE_PIPE").unwrap_or_else(|_| PIPE_PATH.to_string()),
            run_nonce: hex::encode(random),
            data_dir,
            #[cfg(windows)]
            job: Mutex::new(None),
        })
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
        let sidecar_dir = self.sidecar.parent().unwrap_or_else(|| Path::new("."));
        let log_path = self.data_dir.join("logs").join("sidecar.log");
        let stdout = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&log_path)?;
        let stderr = stdout.try_clone()?;
        let database_path = self.data_dir.join("agent_platform.db");
        let workspace_root = self.data_dir.join("workspace");
        command
            .current_dir(sidecar_dir)
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONDONTWRITEBYTECODE", "1")
            .env("ZCODE_RUN_NONCE", &self.run_nonce)
            .env("ZCODE_LAUNCHER_PID", std::process::id().to_string())
            .env("ZCODE_PIPE", &self.pipe_path)
            .env("ZCODE_DATA_DIR", &self.data_dir)
            .env("ZCODE_RESOURCE_ROOT", sidecar_dir)
            .env("DATABASE_URL", sqlite_url(&database_path))
            .env("APP_WORKSPACE_ROOT", workspace_root)
            .stdout(Stdio::from(stdout))
            .stderr(Stdio::from(stderr));
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
        if let Err(error) = self.establish_session(Duration::from_secs(10)) {
            self.kill_current_child();
            return Err(std::io::Error::other(error));
        }
        Ok(())
    }

    fn establish_session(&self, timeout: Duration) -> Result<(), String> {
        let mut stream = open_pipe_with_timeout(&self.pipe_path, timeout)?;
        let hello_request = json!({
            "v": PROTOCOL_VERSION,
            "id": 1,
            "method": "hello",
            "params": {
                "nonce": self.run_nonce,
                "client_versions": [PROTOCOL_VERSION],
                "pid": std::process::id(),
            }
        });
        write_frame(&mut stream, &hello_request)?;
        let hello_response = read_frame(&mut stream)?;
        let hello_data = response_data(hello_response)?;
        let hello: HelloAck =
            serde_json::from_value(hello_data).map_err(|error| error.to_string())?;
        if hello.version != PROTOCOL_VERSION
            || hello.http_port == 0
            || hello.http_token.len() != 64
            || hello.sidecar_pid == 0
            || hello.schema_version != "1.0.0"
        {
            return Err("sidecar hello acknowledgement failed validation".to_string());
        }
        let ping_request = json!({
            "v": PROTOCOL_VERSION,
            "id": 2,
            "method": "ipc.ping",
            "params": {},
        });
        write_frame(&mut stream, &ping_request)?;
        let ping = response_data(read_frame(&mut stream)?)?;
        if ping.get("pong").and_then(Value::as_bool) != Some(true) {
            return Err("sidecar did not return a valid ping response".to_string());
        }
        self.session
            .lock()
            .unwrap()
            .replace(SidecarSession { stream, next_id: 3 });
        Ok(())
    }

    fn ipc_request(&self, method: &str, params: Value) -> Result<Value, String> {
        let mut guard = self
            .session
            .lock()
            .map_err(|_| "sidecar session lock poisoned".to_string())?;
        let result = (|| {
            let session = guard
                .as_mut()
                .ok_or_else(|| "sidecar IPC session is unavailable".to_string())?;
            let id = session.next_id;
            session.next_id = session.next_id.saturating_add(1);
            let request = json!({
                "v": PROTOCOL_VERSION,
                "id": id,
                "method": method,
                "params": params,
            });
            write_frame(&mut session.stream, &request)?;
            response_data(read_frame(&mut session.stream)?)
        })();
        if result.is_err() {
            guard.take();
        }
        result
    }

    fn kill_current_child(&self) {
        self.session.lock().unwrap().take();
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    fn stop(&self) {
        self.stopping.store(true, Ordering::SeqCst);
        let _ = self.ipc_request("ipc.shutdown", json!({}));
        self.session.lock().unwrap().take();
        if let Some(mut child) = self.child.lock().unwrap().take() {
            let deadline = Instant::now() + Duration::from_secs(5);
            while Instant::now() < deadline {
                match child.try_wait() {
                    Ok(Some(_)) => return,
                    Ok(None) => thread::sleep(Duration::from_millis(50)),
                    Err(_) => break,
                }
            }
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
            self.session.lock().unwrap().take();
            let attempt = self.restart_count.fetch_add(1, Ordering::SeqCst) + 1;
            if attempt > MAX_RESTARTS {
                self.restart_limit_reached.store(true, Ordering::SeqCst);
                break;
            }
            thread::sleep(Duration::from_millis(100 * u64::from(attempt)));
            if self.stopping.load(Ordering::SeqCst) {
                break;
            }
            match self.spawn_child() {
                Ok(child) => {
                    self.child.lock().unwrap().replace(child);
                    if self.establish_session(Duration::from_secs(10)).is_err() {
                        self.kill_current_child();
                    }
                }
                Err(_) => thread::sleep(Duration::from_secs(1)),
            }
        }
    }

    fn status(&self) -> SidecarStatus {
        let running = {
            let mut guard = self.child.lock().unwrap();
            match guard.as_mut() {
                Some(child) => child
                    .try_wait()
                    .map(|status| status.is_none())
                    .unwrap_or(false),
                None => false,
            }
        };
        let healthy = running && self.ipc_request("ipc.ping", json!({})).is_ok();
        SidecarStatus {
            healthy,
            running,
            restart_count: self.restart_count.load(Ordering::SeqCst),
            restart_limit_reached: self.restart_limit_reached.load(Ordering::SeqCst),
        }
    }
}

fn zcode_data_dir() -> PathBuf {
    env::var_os("ZCODE_DATA_DIR")
        .map(PathBuf::from)
        .or_else(|| env::var_os("LOCALAPPDATA").map(|path| PathBuf::from(path).join("zcode")))
        .or_else(|| {
            env::var_os("USERPROFILE").map(|path| {
                PathBuf::from(path)
                    .join("AppData")
                    .join("Local")
                    .join("zcode")
            })
        })
        .unwrap_or_else(|| env::temp_dir().join("zcode"))
}

fn sqlite_url(path: &Path) -> String {
    format!("sqlite:///{}", path.to_string_lossy().replace('\\', "/"))
}

fn response_data(response: Value) -> Result<Value, String> {
    let response: IpcResponse =
        serde_json::from_value(response).map_err(|error| error.to_string())?;
    if response.ok {
        return response
            .data
            .ok_or_else(|| "sidecar response is missing data".to_string());
    }
    let error = response.error.unwrap_or(IpcError {
        code: "E_INTERNAL".to_string(),
        message: None,
    });
    Err(match error.message {
        Some(message) => format!("sidecar {}: {}", error.code, message),
        None => format!("sidecar {}", error.code),
    })
}

fn write_frame(stream: &mut File, value: &Value) -> Result<(), String> {
    let payload = serde_json::to_vec(value).map_err(|error| error.to_string())?;
    if payload.len() > MAX_FRAME_SIZE {
        return Err("IPC request exceeds 1 MiB".to_string());
    }
    let size = u32::try_from(payload.len()).map_err(|_| "IPC request is too large".to_string())?;
    stream
        .write_all(&size.to_le_bytes())
        .map_err(|error| error.to_string())?;
    stream
        .write_all(&payload)
        .map_err(|error| error.to_string())?;
    stream.flush().map_err(|error| error.to_string())
}

fn read_frame(stream: &mut File) -> Result<Value, String> {
    let mut header = [0_u8; 4];
    stream
        .read_exact(&mut header)
        .map_err(|error| error.to_string())?;
    let size = u32::from_le_bytes(header) as usize;
    if size > MAX_FRAME_SIZE {
        return Err("IPC response exceeds 1 MiB".to_string());
    }
    let mut payload = vec![0_u8; size];
    stream
        .read_exact(&mut payload)
        .map_err(|error| error.to_string())?;
    serde_json::from_slice(&payload).map_err(|error| error.to_string())
}

#[cfg(windows)]
fn set_pipe_byte_read_mode(pipe: &File) -> Result<(), String> {
    use std::os::windows::io::AsRawHandle;
    use windows_sys::Win32::System::Pipes::SetNamedPipeHandleState;

    let mut mode = 0_u32;
    let result = unsafe {
        SetNamedPipeHandleState(
            pipe.as_raw_handle() as _,
            &mut mode,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
        )
    };
    if result == 0 {
        return Err(std::io::Error::last_os_error().to_string());
    }
    Ok(())
}

#[cfg(windows)]
fn open_pipe_with_timeout(pipe_path: &str, timeout: Duration) -> Result<File, String> {
    let deadline = Instant::now() + timeout;
    loop {
        match OpenOptions::new().read(true).write(true).open(pipe_path) {
            Ok(pipe) => {
                set_pipe_byte_read_mode(&pipe)?;
                return Ok(pipe);
            }
            Err(error)
                if matches!(error.raw_os_error(), Some(2 | 231)) && Instant::now() < deadline =>
            {
                thread::sleep(Duration::from_millis(25));
            }
            Err(error) => return Err(error.to_string()),
        }
    }
}

#[cfg(not(windows))]
fn open_pipe_with_timeout(_pipe_path: &str, _timeout: Duration) -> Result<File, String> {
    Err("Named Pipe sidecar is Windows-only".to_string())
}

#[tauri::command]
fn sidecar_status(state: State<'_, Arc<SidecarController>>) -> SidecarStatus {
    state.inner().as_ref().status()
}

#[tauri::command]
fn http_via_sidecar(
    method: String,
    path: String,
    body: Option<Value>,
    headers: Option<BTreeMap<String, String>>,
    state: State<'_, Arc<SidecarController>>,
) -> Result<Value, String> {
    let mut params = Map::new();
    params.insert("method".to_string(), Value::String(method));
    params.insert("path".to_string(), Value::String(path));
    if let Some(body) = body {
        params.insert("body".to_string(), body);
    }
    if let Some(headers) = headers {
        params.insert(
            "headers".to_string(),
            serde_json::to_value(headers).map_err(|error| error.to_string())?,
        );
    }
    state
        .inner()
        .as_ref()
        .ipc_request("http.request", Value::Object(params))
}

fn resolve_sidecar() -> (String, PathBuf) {
    let python = env::var("ZCODE_PYTHON").unwrap_or_else(|_| "python".to_string());
    let source_sidecar = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../../services/control-core/scripts/nuitka-build/control_core_sidecar.py");
    let sidecar = env::var_os("ZCODE_SIDECAR")
        .map(PathBuf::from)
        .or_else(|| {
            env::current_exe().ok().and_then(|exe| {
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
        .unwrap_or(source_sidecar);
    (python, sidecar)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let (python, sidecar) = resolve_sidecar();
    let controller = Arc::new(
        SidecarController::new(python, sidecar)
            .expect("could not initialize the sidecar controller"),
    );
    controller
        .start()
        .expect("failed to start and handshake with control-core sidecar");
    let monitor = controller.clone();
    thread::spawn(move || monitor.monitor());

    let app_controller = controller.clone();
    tauri::Builder::default()
        .manage(controller)
        .plugin(tauri_plugin_opener::init())
        .invoke_handler(tauri::generate_handler![sidecar_status, http_via_sidecar])
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                let state = window.app_handle().state::<Arc<SidecarController>>();
                state.inner().as_ref().stop();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running the Tauri application");
    app_controller.stop();
}
