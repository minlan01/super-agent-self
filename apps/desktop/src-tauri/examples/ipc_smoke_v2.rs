use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::thread;
use std::time::{Duration, Instant};

const PIPE_PATH: &str = r"\\.\pipe\zcode-control-core-v1";
const MAX_FRAME_SIZE: usize = 1 << 20;

fn open_pipe(timeout: Duration) -> Result<File, Box<dyn std::error::Error>> {
    let deadline = Instant::now() + timeout;
    loop {
        match OpenOptions::new().read(true).write(true).open(PIPE_PATH) {
            Ok(pipe) => return Ok(pipe),
            Err(error)
                if matches!(error.raw_os_error(), Some(2 | 231)) && Instant::now() < deadline =>
            {
                thread::sleep(Duration::from_millis(25));
            }
            Err(error) => return Err(error.into()),
        }
    }
}

fn request(pipe: &mut File, value: serde_json::Value) -> Result<serde_json::Value, Box<dyn std::error::Error>> {
    let payload = serde_json::to_vec(&value)?;
    if payload.len() > MAX_FRAME_SIZE {
        return Err("request exceeds 1 MiB".into());
    }
    pipe.write_all(&(payload.len() as u32).to_le_bytes())?;
    pipe.write_all(&payload)?;
    pipe.flush()?;
    let mut header = [0_u8; 4];
    pipe.read_exact(&mut header)?;
    let size = u32::from_le_bytes(header) as usize;
    if size > MAX_FRAME_SIZE {
        return Err("response exceeds 1 MiB".into());
    }
    let mut response = vec![0_u8; size];
    pipe.read_exact(&mut response)?;
    Ok(serde_json::from_slice(&response)?)
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let nonce = std::env::var("ZCODE_RUN_NONCE")?;
    let mut pipe = open_pipe(Duration::from_secs(10))?;
    let hello = request(
        &mut pipe,
        serde_json::json!({
            "v": 1,
            "id": 1,
            "method": "hello",
            "params": {
                "nonce": nonce,
                "client_versions": [1],
                "pid": std::process::id(),
            }
        }),
    )?;
    let ping = request(
        &mut pipe,
        serde_json::json!({"v": 1, "id": 2, "method": "ipc.ping", "params": {}}),
    )?;
    println!("{}", serde_json::json!({"hello": hello, "ping": ping}));
    Ok(())
}
