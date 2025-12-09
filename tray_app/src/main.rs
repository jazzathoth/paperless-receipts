mod server;
use std::os::unix::net::UnixStream;
use std::io::{BufReader, BufRead, Write};
use std::path::PathBuf;
use std::process::Command;
use tray_icon::{menu::{Menu, MenuEvent, MenuItem}, Icon, TrayIconBuilder};
use std::env;
use image::{self, GenericImageView};

use server::spawn_server;

const SOCKET_PATH: &str = "/tmp/paperless_worker.sock";


fn start_app() {
    let url = "http://127.0.0.1:8000";
    let chrome_like = [
        "google-chrome",
        "chromium",
        "chromium-browser",
        "chrome",
    ];

    for bin in chrome_like {
        if Command::new(bin)
            .args([ "--app", url ])
            .spawn()
            .is_ok()
    {
            return;
        }
    }

    if Command::new("firefox").arg(url).spawn().is_ok() {
        return;
    }

    let _ = Command::new("xdg-open").arg(url).spawn();
}

fn send_cmd(cmd: &str) -> Option<String> {
    let stream = UnixStream::connect(SOCKET_PATH).ok()?;
    let mut reader = BufReader::new(stream);
    let writer = reader.get_mut();

    writer.write_all(cmd.as_bytes()).ok()?;
    writer.write_all(b"\n").ok()?;
    writer.flush().ok()?;

    let mut response = String::new();
    reader.read_line(&mut response).ok()?;
    Some(response.trim().to_string())
}

fn make_icon(img_file: &str) -> Result<Icon, String> {
    let mut path = PathBuf::from(get_dir());
    path.push(img_file);

    let img = image::open(path)
        .map_err(|e| e.to_string())?;

    let (width, height) = img.dimensions();
    let rgba = img.to_rgba8();
    let icon = Icon::from_rgba(rgba.into_raw(), width, height)
        .map_err(|e| e.to_string())?;
    Ok(icon)
}


fn get_dir() -> String {
    let exe_path = env::current_exe().unwrap();
    exe_path.parent().unwrap().to_string_lossy().into_owned()
}




fn main() {
    #[cfg(target_os = "linux")]
    gtk::init().expect("Failed to initialize GTK");


    let app_dir = get_dir();

    let running_icon = make_icon("paperless_on.png").unwrap();
    let stopped_icon = make_icon("paperless_off.png").unwrap();
    
    if !UnixStream::connect(SOCKET_PATH).is_ok() {
        spawn_server(app_dir.clone()).expect("Failed to start worker");
    } else {
        let _ = send_cmd("start");
        start_app();
        return ();
    }


    let init_status = send_cmd("start").unwrap_or_else(|| "stopped".into());

    let mut running = init_status == "running";

    start_app();

    let menu = Menu::new();

    let toggle_start = MenuItem::new(
        if running {"Stop server"} else {"Start server"},
        true,
        None,
    );

    let quit_item = MenuItem::new("Quit", true, None);

    menu.append(&toggle_start).unwrap();
    menu.append(&quit_item).unwrap();

    let tray_icon = TrayIconBuilder::new()
        .with_menu(Box::new(menu))
        .with_icon(if running {running_icon.clone()} else {stopped_icon.clone()})
        .with_tooltip("Paperless Receipts")
        .build()
        .expect("failed to build tray icon");

    let toggle_id = toggle_start.id().clone();
    let quit_id = quit_item.id().clone();

    loop {
        if let Ok(event) = MenuEvent::receiver().recv() {
            let id = event.id();

            if id == &toggle_id {
                if let Some(status) = send_cmd("toggle") {
                    running = status == "running";
                    if !running {
                        let _ = tray_icon.set_icon(Some(stopped_icon.clone()));
                        toggle_start.set_text("Start server");
                    } else {
                        let _ = tray_icon.set_icon(Some(running_icon.clone()));
                        toggle_start.set_text("Stop server");
                    }
                } else {
                    eprintln!("Failed to send message to worker")
                }
            } else if id == &quit_id {
                let _ = send_cmd("quit");
                break;
            }
        }
    }
}
