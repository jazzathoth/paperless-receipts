use std::os::unix::net::{UnixListener, UnixStream};
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::Command;


const SOCKET_PATH: &str = "/tmp/paperless_worker.sock";

fn up(dir: &str) -> bool {
    Command::new("docker")
        .args(["compose", "up", "-d"])
        .current_dir(dir)
        .status()
        .map(|s| s.success()).unwrap_or(false)
}

fn down(dir: &str) -> bool {
    Command::new("docker")
        .args(["compose", "down"])
        .current_dir(dir)
        .status()
        .map(|s| s.success()).unwrap_or(false)
}

fn is_up(dir: &str) -> bool {
    let status = Command::new("docker")
        .args(["compose", "ps", "--status", "running", "--services"])
        .current_dir(dir)
        .output();

    match status {
        Ok(s) => !String::from_utf8_lossy(&s.stdout).trim().is_empty(),
        Err(_) => false,
    }
}

enum CmdResult {
    Continue,
    Quit,
}

fn process_cmd(
    stream: UnixStream,
    running: &mut bool,
    app_dir: &str,
) -> Result<CmdResult, String> {
    let mut reader = BufReader::new(stream);
    let mut line = String::new();

    let l = reader.read_line(&mut line).map_err(|e| e.to_string())?;
    if l == 0 {
        return Ok(CmdResult::Continue)
    }

    let cmd = line.trim();
    let writer = reader.get_mut();

    match cmd {
        "status" => {
            *running = is_up(app_dir);
        }

        "start" => {
            if !*running {
                if up(app_dir) {
                    *running = true;
                }
            } else {
                *running = is_up(app_dir);
            }
        }

        "toggle" => {
            if *running {
                if down(app_dir) {
                    *running = false;
                } else {
                    *running = is_up(app_dir);
                }
            } else {
                if up(app_dir) {
                    *running = true;
                } else {
                    *running = is_up(app_dir);
                }
            }
        }

        "quit" => {
            *running = is_up(app_dir);
            if *running {
                let _ = down(app_dir);
                *running = false;
            }
            writer.write_all(b"stopped\n").map_err(|e| e.to_string())?;
            return Ok(CmdResult::Quit)
        }
        _ => {
            writer.write_all(b"error\n").map_err(|e| e.to_string())?;
            return Ok(CmdResult::Continue);
        }
    }
    let state = if *running {"running\n"} else {"stopped\n"};
    writer.write_all(state.as_bytes()).map_err(|e| e.to_string())?;
    Ok(CmdResult::Continue)
}


pub fn spawn_server(app_dir: String) -> Result<(), String> {

    if Path::new(SOCKET_PATH).exists() {
        std::fs::remove_file(SOCKET_PATH).map_err(|e| e.to_string())?;
    }

    let listener = UnixListener::bind(SOCKET_PATH).map_err(|e| e.to_string())?;

    std::thread::spawn(move || {
        let mut running = is_up(&app_dir);
        for conn in listener.incoming() {
            match conn {
                Ok(stream) => {
                    match process_cmd(stream, &mut running, &app_dir) {
                        Ok(CmdResult::Continue) => {},
                        Ok(CmdResult::Quit) => break,
                        Err(e) => eprintln!("Error processing cmd: {e}"),
                    }
                },
                Err(e) => {
                    eprintln!("Accept error: {e}");
                    break;
                }
            }
        }
        let _ = std::fs::remove_file(SOCKET_PATH);
    });
    Ok(())
}
