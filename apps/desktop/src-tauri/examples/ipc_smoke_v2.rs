use std::fs::{File, OpenOptions};
use std::io::{Read, Write};
use std::thread;
use std::time::{Duration, Instant};

const PIPE_PATH: &str = r"\\.\pipe\zcode-sidecar-spike";

fn open_pipe(timeout: Duration) -> Result<File, Box<dyn std::error::Error>> {
    let deadline = Instant::now() + timeout;
    loop {
        match OpenOptions::new().read(true).write(true).open(PIPE_PATH) {
            Ok(pipe) => return Ok(pipe),
            Err(error)
                if matches!(error.raw_os_error(), Some(2 | 231)) && Instant::now() < deadline =>
            {
                thread::sleep(Duration::from_millis(2));
            }
            Err(error) => return Err(error.into()),
        }
    }
}

fn round_trip(message: &str, nonce: &str) -> Result<f64, Box<dyn std::error::Error>> {
    let start = Instant::now();
    let mut pipe = open_pipe(Duration::from_secs(2))?;
    let request = serde_json::json!({ "msg": message, "nonce": nonce }).to_string();
    pipe.write_all(request.as_bytes())?;
    pipe.flush()?;
    let mut buffer = vec![0_u8; 65536];
    let size = pipe.read(&mut buffer)?;
    let response: serde_json::Value = serde_json::from_slice(&buffer[..size])?;
    if response.get("echoed").and_then(|value| value.as_str()) != Some(message) {
        return Err("unexpected echo response".into());
    }
    if response.get("nonce").and_then(|value| value.as_str()) != Some(nonce) {
        return Err("unexpected sidecar nonce".into());
    }
    Ok(start.elapsed().as_secs_f64() * 1000.0)
}

fn percentile(sorted: &[f64], quantile: f64) -> f64 {
    let index = ((quantile * sorted.len() as f64).ceil() as usize).saturating_sub(1);
    sorted[index]
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let nonce = std::env::var("ZCODE_RUN_NONCE").unwrap_or_else(|_| "development".to_string());
    for _ in 0..10 {
        round_trip("warmup", &nonce)?;
    }
    let mut samples = Vec::with_capacity(100);
    for _ in 0..100 {
        samples.push(round_trip("ping", &nonce)?);
    }
    samples.sort_by(|left, right| left.total_cmp(right));
    println!(
        "{}",
        serde_json::json!({
            "samples": samples.len(),
            "p50_ms": (percentile(&samples, 0.50) * 1000.0).round() / 1000.0,
            "p95_ms": (percentile(&samples, 0.95) * 1000.0).round() / 1000.0,
            "max_ms": (samples[samples.len() - 1] * 1000.0).round() / 1000.0,
            "passed": percentile(&samples, 0.95) <= 100.0,
        })
    );
    Ok(())
}
