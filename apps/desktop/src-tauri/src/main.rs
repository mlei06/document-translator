#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]
mod activation;
mod input;

use rand::RngCore;
use serde::Deserialize;
use serde_json::{json, Value};
use std::os::windows::{io::AsRawHandle, process::CommandExt};
use std::{
    io::{BufRead, BufReader, Read, Write},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::Duration,
};
use tauri::{Manager, State};
use tauri_plugin_dialog::DialogExt;
use windows_sys::Win32::{Foundation::CloseHandle, System::JobObjects::*};

struct ComApartment(bool);
impl Drop for ComApartment {
    fn drop(&mut self) {
        if self.0 {
            unsafe {
                windows_sys::Win32::System::Com::CoUninitialize();
            }
        }
    }
}
struct Job(isize);
impl Drop for Job {
    fn drop(&mut self) {
        unsafe {
            CloseHandle(self.0 as _);
        }
    }
}
struct Runtime {
    child: Child,
    base: String,
    token: String,
    client: reqwest::blocking::Client,
    _job: Job,
}
impl Drop for Runtime {
    fn drop(&mut self) {
        let _ = self
            .client
            .post(format!("{}/v1/desktop/shutdown", self.base))
            .bearer_auth(&self.token)
            .send();
        for _ in 0..50 {
            if self.child.try_wait().ok().flatten().is_some() {
                break;
            }
            std::thread::sleep(Duration::from_millis(100));
        }
    }
}
#[derive(Deserialize)]
struct Ready {
    event: String,
    protocol: u32,
    api: String,
    pid: u32,
    base_url: String,
}

fn launch(app: &tauri::App) -> Result<Runtime, Box<dyn std::error::Error>> {
    let executable = app
        .path()
        .resource_dir()?
        .join("runtime/doctranslator-server.exe");
    let mut child = Command::new(executable)
        .arg("desktop")
        .creation_flags(0x08000000)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()?;
    let handle = unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            let _ = child.kill();
            return Err(std::io::Error::last_os_error().into());
        }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as _,
            std::mem::size_of_val(&info) as u32,
        ) == 0
            || AssignProcessToJobObject(job, child.as_raw_handle() as _) == 0
        {
            CloseHandle(job);
            let _ = child.kill();
            return Err(std::io::Error::last_os_error().into());
        }
        Job(job as isize)
    };
    let mut bytes = [0u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut bytes);
    let token: String = bytes.iter().map(|b| format!("{b:02x}")).collect();
    writeln!(
        child.stdin.take().ok_or("Missing bootstrap pipe")?,
        "{}",
        json!({"protocol":1,"token":token})
    )?;
    let stdout = child.stdout.take().ok_or("Missing readiness pipe")?;
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        let mut line = String::new();
        let result = BufReader::new(stdout)
            .take(4097)
            .read_line(&mut line)
            .map(|_| line);
        let _ = tx.send(result);
    });
    let line = rx.recv_timeout(Duration::from_secs(120))??;
    if line.len() > 4096 {
        return Err("Invalid runtime readiness".into());
    }
    let ready: Ready = serde_json::from_str(&line)?;
    let url = reqwest::Url::parse(&ready.base_url)?;
    if ready.event != "ready"
        || ready.protocol != 1
        || ready.api != "v1"
        || ready.pid != child.id()
        || url.scheme() != "http"
        || url.host_str() != Some("127.0.0.1")
        || url.port().is_none()
        || url.path() != "/"
    {
        return Err("Incompatible desktop runtime".into());
    }
    let client = reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(120))
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()?;
    client
        .get(format!("{}/v1/health", ready.base_url))
        .bearer_auth(&token)
        .send()?
        .error_for_status()?;
    Ok(Runtime {
        child,
        base: ready.base_url,
        token,
        client,
        _job: handle,
    })
}

#[tauri::command]
async fn api(
    runtime: State<'_, Mutex<Runtime>>,
    method: String,
    path: String,
    body: Option<Value>,
) -> Result<Value, String> {
    if !path.starts_with("/v1/") || path.contains("..") || path.contains('?') || path.contains('#')
    {
        return Err("Invalid local route".into());
    }
    let mut request = {
        let runtime = runtime.lock().map_err(|_| "Runtime unavailable")?;
        let method =
            reqwest::Method::from_bytes(method.as_bytes()).map_err(|_| "Invalid method")?;
        runtime
            .client
            .request(method, format!("{}{}", runtime.base, path))
            .bearer_auth(&runtime.token)
    };
    if let Some(body) = body {
        request = request.json(&body);
    }
    tauri::async_runtime::spawn_blocking(move || {
        let response = request
            .send()
            .map_err(|_| "Local runtime connection failed")?;
        let status = response.status();
        let value: Value = response
            .json()
            .map_err(|_| "Invalid local runtime response")?;
        if !status.is_success() {
            return Err(value.to_string());
        }
        Ok(value)
    })
    .await
    .map_err(|_| "Local request task failed".to_string())?
}

#[tauri::command]
fn pick(app: tauri::AppHandle, folders: bool) -> Vec<String> {
    let picker = app.dialog().file();
    let paths = if folders {
        picker.blocking_pick_folders()
    } else {
        picker
            .add_filter("Documents", &["docx", "pptx", "xlsx", "pdf", "txt"])
            .blocking_pick_files()
    };
    paths
        .unwrap_or_default()
        .into_iter()
        .filter_map(|p| p.into_path().ok())
        .map(|p| p.to_string_lossy().into_owned())
        .collect()
}

#[tauri::command]
fn quit(app: tauri::AppHandle, runtime: State<Mutex<Runtime>>) -> Result<(), String> {
    let mut runtime = runtime.lock().map_err(|_| "Runtime unavailable")?;
    let _ = runtime
        .client
        .post(format!("{}/v1/desktop/shutdown", runtime.base))
        .bearer_auth(&runtime.token)
        .send();
    for _ in 0..150 {
        if runtime
            .child
            .try_wait()
            .map_err(|_| "Cannot wait for runtime")?
            .is_some()
        {
            break;
        }
        std::thread::sleep(Duration::from_millis(100));
    }
    app.exit(0);
    Ok(())
}

#[tauri::command]
fn open_export(path: String, folder: bool) -> Result<(), String> {
    let path = std::path::Path::new(&path)
        .canonicalize()
        .map_err(|_| "The exported file is no longer available")?;
    let suffix = path
        .extension()
        .and_then(|s| s.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    if !["txt", "docx", "pptx", "xlsx", "pdf"].contains(&suffix.as_str()) {
        return Err("Unsupported document".into());
    }
    let normalized = path.to_string_lossy();
    let shell_path = if let Some(unc) = normalized.strip_prefix(r"\\?\UNC\") {
        format!(r"\\{}", unc)
    } else {
        normalized
            .strip_prefix(r"\\?\")
            .unwrap_or(&normalized)
            .to_string()
    };
    let filename: Vec<u16> = shell_path.encode_utf16().chain(Some(0)).collect();
    // File associations can invoke COM shell extensions too, including packaged apps.
    let initialized =
        unsafe { windows_sys::Win32::System::Com::CoInitializeEx(std::ptr::null(), 2 | 4) };
    if initialized < 0 && initialized != 0x80010106u32 as i32 {
        return Err("Could not initialize Windows file actions".into());
    }
    let _apartment = ComApartment(initialized >= 0);
    if folder {
        unsafe {
            let mut pidl = std::ptr::null_mut();
            let parsed = windows_sys::Win32::UI::Shell::SHParseDisplayName(
                filename.as_ptr(),
                std::ptr::null_mut(),
                &mut pidl,
                0,
                std::ptr::null_mut(),
            );
            if parsed < 0 {
                return Err("Could not locate the exported file".into());
            }
            let opened = windows_sys::Win32::UI::Shell::SHOpenFolderAndSelectItems(
                pidl,
                0,
                std::ptr::null(),
                0,
            );
            windows_sys::Win32::System::Com::CoTaskMemFree(pidl as _);
            if opened < 0 {
                return Err("Could not open the exported file location".into());
            }
        }
    } else {
        let verb: Vec<u16> = "open".encode_utf16().chain(Some(0)).collect();
        let result = unsafe {
            windows_sys::Win32::UI::Shell::ShellExecuteW(
                std::ptr::null_mut(),
                verb.as_ptr(),
                filename.as_ptr(),
                std::ptr::null(),
                std::ptr::null(),
                1,
            )
        };
        if result as isize <= 32 {
            return Err("Could not open the exported document".into());
        }
    }
    Ok(())
}

fn install_offline(handle: tauri::AppHandle) {
    std::thread::spawn(move || {
        let state = handle.state::<Mutex<Runtime>>();
        let Ok(runtime) = state.lock() else {
            return;
        };
        let (client, base, token) = (
            runtime.client.clone(),
            runtime.base.clone(),
            runtime.token.clone(),
        );
        drop(runtime);
        let result = client
            .post(format!("{}/v1/desktop/offline/install", base))
            .bearer_auth(&token)
            .send()
            .and_then(|r| r.error_for_status());
        if result.is_err() {
            handle.dialog().message("Offline installation could not start. Open Settings to repair or try again when translations finish.").title("Offline support").show(|_|{});
        }
    });
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, arguments, _| {
            if arguments.iter().any(|arg| arg == "--shutdown") {
                let handle = app.clone();
                std::thread::spawn(move || {
                    let _ = quit(handle.clone(), handle.state::<Mutex<Runtime>>());
                });
                return;
            }
            if arguments.iter().any(|arg| arg == "--install-offline") {
                install_offline(app.clone());
                return;
            }
            if arguments.iter().any(|arg| arg == "--activation") {
                let handle = app.clone();
                std::thread::spawn(move || {
                    if let Err(message) = activation::receive(&handle, &arguments) {
                        handle
                            .dialog()
                            .message(message)
                            .title("Translation selection needs attention")
                            .show(|_| {});
                    }
                });
                return;
            }
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.set_focus();
            }
        }))
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            if std::env::args().any(|argument| argument == "--shutdown") {
                app.handle().exit(0);
                return Ok(());
            }
            let runtime = match launch(app) {
                Ok(runtime) => runtime,
                Err(error) => {
                    let message: Vec<u16> = "Lenny could not start its local translation runtime. Repair or reinstall the application, then try again.".encode_utf16().chain(Some(0)).collect();
                    let title: Vec<u16> = "Lenny Translator".encode_utf16().chain(Some(0)).collect();
                    unsafe { windows_sys::Win32::UI::WindowsAndMessaging::MessageBoxW(std::ptr::null_mut(), message.as_ptr(), title.as_ptr(), 0x10); }
                    return Err(error);
                }
            };
            app.manage(Mutex::new(runtime));
            if std::env::args().any(|argument| argument == "--install-offline") {
                install_offline(app.handle().clone());
            }
            let arguments: Vec<String> = std::env::args().collect();
            if arguments.iter().any(|arg| arg == "--activation") {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
                let handle = app.handle().clone();
                std::thread::spawn(move || {
                    if let Err(message) = activation::receive(&handle, &arguments) {
                        handle
                            .dialog()
                            .message(message)
                            .title("Translation selection needs attention")
                            .show(|_| {});
                    }
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                api.prevent_close();
                let _ = window.hide();
            }
        })
        .invoke_handler(tauri::generate_handler![
            api,
            pick,
            input::inspect_paths,
            input::default_export_directory,
            quit,
            open_export,
            activation::activity_state,
            activation::cancel_activity,
            activation::open_main,
            activation::get_shortcuts,
            activation::set_shortcuts
        ])
        .run(tauri::generate_context!())
        .expect("Desktop application could not start");
}
