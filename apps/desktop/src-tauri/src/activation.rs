use super::Runtime;
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::collections::HashMap;
use std::path::Path;
use std::sync::{Mutex, OnceLock};
use tauri::{AppHandle, Manager, WebviewUrl, WebviewWindowBuilder};
use winreg::{enums::*, RegKey};

#[derive(Clone, Serialize)]
pub struct ActivityJob {
    id: String,
    path: String,
    status: String,
    output: Option<String>,
}
#[derive(Clone, Serialize)]
pub struct ActivityError {
    path: String,
    error: String,
}
#[derive(Clone, Serialize)]
pub struct Activity {
    id: String,
    target: String,
    enumerating: bool,
    cancelled: bool,
    errors: Vec<ActivityError>,
    jobs: Vec<ActivityJob>,
}
static ACTIVITIES: OnceLock<Mutex<HashMap<String, Activity>>> = OnceLock::new();
fn activities() -> &'static Mutex<HashMap<String, Activity>> {
    ACTIVITIES.get_or_init(|| Mutex::new(HashMap::new()))
}
fn cancelled(id: &str) -> bool {
    activities()
        .lock()
        .map(|g| g.get(id).map(|v| v.cancelled).unwrap_or(true))
        .unwrap_or(true)
}
fn update(id: &str, operation: impl FnOnce(&mut Activity)) {
    if let Ok(mut groups) = activities().lock() {
        if let Some(group) = groups.get_mut(id) {
            operation(group);
        }
    }
}
#[tauri::command]
pub fn open_main(app: AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.set_focus();
    }
}
#[tauri::command]
pub fn cancel_activity(app: AppHandle, group: String) {
    update(&group, |value| value.cancelled = true);
    std::thread::spawn(move || {
        let state = app.state::<Mutex<Runtime>>();
        let Ok(runtime) = state.lock() else {
            return;
        };
        let (client, base, token) = (
            runtime.client.clone(),
            runtime.base.clone(),
            runtime.token.clone(),
        );
        drop(runtime);
        let jobs = activities()
            .lock()
            .ok()
            .and_then(|g| g.get(&group).map(|v| v.jobs.clone()))
            .unwrap_or_default();
        for job in jobs {
            if !["succeeded", "failed", "cancelled"].contains(&job.status.as_str()) {
                let _ = client
                    .post(format!("{}/v1/jobs/{}/cancel", base, job.id))
                    .bearer_auth(&token)
                    .send();
            }
        }
    });
}
#[tauri::command]
pub async fn activity_state(app: AppHandle) -> Result<Vec<Activity>, String> {
    tauri::async_runtime::spawn_blocking(move || {
        let state = app.state::<Mutex<Runtime>>();
        let (client, base, token) = {
            let runtime = state.lock().map_err(|_| "Runtime unavailable")?;
            (
                runtime.client.clone(),
                runtime.base.clone(),
                runtime.token.clone(),
            )
        };
        let snapshot: Vec<Activity> = activities()
            .lock()
            .map_err(|_| "Activity unavailable")?
            .values()
            .cloned()
            .collect();
        for group in snapshot {
            for job in group
                .jobs
                .iter()
                .filter(|j| !["succeeded", "failed", "cancelled"].contains(&j.status.as_str()))
            {
                if group.cancelled {
                    let _ = client
                        .post(format!("{}/v1/jobs/{}/cancel", base, job.id))
                        .bearer_auth(&token)
                        .send();
                }
                if let Ok(response) = client
                    .get(format!("{}/v1/jobs/{}", base, job.id))
                    .bearer_auth(&token)
                    .send()
                {
                    if let Ok(value) = response.json::<serde_json::Value>() {
                        if let Some(status) = value["status"].as_str() {
                            update(&group.id, |g| {
                                if let Some(item) = g.jobs.iter_mut().find(|j| j.id == job.id) {
                                    item.status = status.into();
                                }
                            });
                        }
                    }
                }
            }
        }
        if let Ok(response) = client
            .get(format!("{}/v1/desktop/recent", base))
            .bearer_auth(&token)
            .send()
        {
            if let Ok(records) = response.json::<Vec<serde_json::Value>>() {
                if let Ok(mut groups) = activities().lock() {
                    for group in groups.values_mut() {
                        for job in &mut group.jobs {
                            if let Some(record) = records
                                .iter()
                                .find(|v| v["id"].as_str() == Some(job.id.as_str()))
                            {
                                job.output = record["output"].as_str().map(String::from);
                            }
                        }
                    }
                }
            }
        }
        Ok(activities()
            .lock()
            .map_err(|_| "Activity unavailable")?
            .values()
            .cloned()
            .collect())
    })
    .await
    .map_err(|_| "Activity request failed".to_string())?
}
struct GroupGuard(String);
impl Drop for GroupGuard {
    fn drop(&mut self) {
        update(&self.0, |g| g.enumerating = false);
    }
}
struct Cursor {
    client: reqwest::blocking::Client,
    base: String,
    token: String,
    cursor: String,
    group: String,
}
impl Drop for Cursor {
    fn drop(&mut self) {
        let _ = self
            .client
            .delete(format!("{}/v1/desktop/discover/{}", self.base, self.cursor))
            .bearer_auth(&self.token)
            .send();
        update(&self.group, |g| g.enumerating = false);
    }
}

#[derive(Deserialize)]
struct Activation {
    version: u32,
    target: String,
    paths: Vec<String>,
}

pub fn receive(app: &AppHandle, arguments: &[String]) -> Result<(), String> {
    let Some(index) = arguments.iter().position(|arg| arg == "--activation") else {
        return Ok(());
    };
    let filename = arguments.get(index + 1).ok_or("Missing activation file")?;
    let path = Path::new(filename)
        .canonicalize()
        .map_err(|_| "Activation file unavailable")?;
    let root = dirs::data_local_dir()
        .ok_or("Local data directory unavailable")?
        .join("Lenny/Translator/activations")
        .canonicalize()
        .map_err(|_| "Activation directory unavailable")?;
    if !path.starts_with(root) || path.extension().and_then(|e| e.to_str()) != Some("json") {
        return Err("Invalid activation path".into());
    }
    let content = std::fs::read(&path).map_err(|_| "Cannot read activation")?;
    let activation: Activation =
        serde_json::from_slice(&content).map_err(|_| "Invalid activation content")?;
    if activation.version != 1 || !["en", "zh", "ja", "es"].contains(&activation.target.as_str()) {
        return Err("Unsupported activation".into());
    }
    let group = path.to_string_lossy().into_owned();
    {
        let mut groups = activities().lock().map_err(|_| "Activity unavailable")?;
        if groups.contains_key(&group) {
            if let Some(window) = app.get_webview_window("activity") {
                let _ = window.show();
                let _ = window.set_focus();
            }
            return Ok(());
        }
        groups.insert(
            group.clone(),
            Activity {
                id: group.clone(),
                target: activation.target.clone(),
                enumerating: true,
                cancelled: false,
                errors: vec![],
                jobs: vec![],
            },
        );
    }
    let _group_guard = GroupGuard(group.clone());
    if let Some(window) = app.get_webview_window("activity") {
        let _ = window.show();
        let _ = window.set_focus();
    } else {
        WebviewWindowBuilder::new(app, "activity", WebviewUrl::App("activity.html".into()))
            .title("Translating documents")
            .inner_size(560.0, 420.0)
            .min_inner_size(375.0, 280.0)
            .build()
            .map_err(|_| "Cannot open translation activity")?;
    }
    let state = app.state::<Mutex<Runtime>>();
    let (client, base, token) = {
        let runtime = state.lock().map_err(|_| "Runtime unavailable")?;
        (
            runtime.client.clone(),
            runtime.base.clone(),
            runtime.token.clone(),
        )
    };
    let destination = super::input::default_export_directory()?;
    let response = client
        .post(format!("{}/v1/desktop/discover", base))
        .bearer_auth(&token)
        .json(&json!({"paths":activation.paths,"destination":destination}))
        .send()
        .map_err(|_| "Folder admission failed")?;
    let response: serde_json::Value = response
        .error_for_status()
        .map_err(|_| "Folder admission rejected")?
        .json()
        .map_err(|_| "Invalid discovery response")?;
    let cursor = response["cursor"]
        .as_str()
        .ok_or("Missing discovery cursor")?;
    let _cursor_guard = Cursor {
        client: client.clone(),
        base: base.clone(),
        token: token.clone(),
        cursor: cursor.to_string(),
        group: group.clone(),
    };
    let mut rejected = 0usize;
    loop {
        if cancelled(&group) {
            break;
        }
        let response: serde_json::Value = client
            .get(format!("{}/v1/desktop/discover/{}", base, cursor))
            .bearer_auth(&token)
            .send()
            .map_err(|_| "Folder enumeration failed")?
            .error_for_status()
            .map_err(|_| "Folder enumeration rejected")?
            .json()
            .map_err(|_| "Invalid file response")?;
        if response["done"] == true {
            break;
        }
        if !response["error"].is_null() {
            rejected += 1;
            update(&group, |g| {
                g.errors.push(ActivityError {
                    path: response["path"].as_str().unwrap_or("").into(),
                    error: response["error"]
                        .as_str()
                        .unwrap_or("Cannot read file")
                        .into(),
                })
            });
            continue;
        }
        let source = response["path"].as_str().ok_or("Missing file path")?;
        // Same activation replay uses the same per-file admission identity.
        let identity = uuid::Uuid::new_v5(
            &uuid::Uuid::NAMESPACE_URL,
            format!("{}:{}", path.display(), source).as_bytes(),
        );
        loop {
            if cancelled(&group) {
                break;
            }
            let admitted = client.post(format!("{}/v1/desktop/submit",base)).bearer_auth(&token)
                .json(&json!({"path":source,"target":activation.target,"submission_id":identity.to_string(),"destination":destination}))
                .send().map_err(|_|"File admission interrupted; reopen the same selection to retry")?;
            if admitted.status().as_u16() == 429 {
                std::thread::sleep(std::time::Duration::from_secs(2));
                continue;
            }
            if !admitted.status().is_success() {
                rejected += 1;
                update(&group, |g| {
                    g.errors.push(ActivityError {
                        path: source.into(),
                        error: "File could not be accepted".into(),
                    })
                });
            } else {
                let value: serde_json::Value =
                    admitted.json().map_err(|_| "Invalid admission response")?;
                let id = value["id"]
                    .as_str()
                    .ok_or("Missing accepted job identity")?
                    .to_string();
                if cancelled(&group) {
                    let _ = client
                        .post(format!("{}/v1/jobs/{}/cancel", base, id))
                        .bearer_auth(&token)
                        .send();
                }
                update(&group, |g| {
                    g.jobs.push(ActivityJob {
                        id,
                        path: source.into(),
                        output: None,
                        status: value["status"].as_str().unwrap_or("queued").into(),
                    })
                });
            }
            break;
        }
    }
    if rejected > 0 {
        return Err(format!("{} files could not be accepted. Supported files continue translating. Open Lenny to review completed translations and retry the remaining originals.", rejected));
    }
    std::fs::remove_file(path).map_err(|_| "Cannot clear accepted activation")?;
    Ok(())
}

#[tauri::command]
pub fn get_shortcuts() -> Result<Vec<String>, String> {
    let hkcu = RegKey::predef(HKEY_CURRENT_USER);
    match hkcu.open_subkey("Software\\Lenny\\Translator") {
        Ok(key) => Ok(key
            .get_value("Shortcuts")
            .unwrap_or_else(|_| vec!["en".into()])),
        Err(_) => Ok(vec!["en".into()]),
    }
}

#[tauri::command]
pub fn set_shortcuts(codes: Vec<String>) -> Result<(), String> {
    if codes.len() > 4
        || codes
            .iter()
            .any(|code| !["en", "zh", "ja", "es"].contains(&code.as_str()))
        || codes.iter().collect::<std::collections::HashSet<_>>().len() != codes.len()
    {
        return Err("Invalid shortcuts".into());
    }
    let (key, _) = RegKey::predef(HKEY_CURRENT_USER)
        .create_subkey("Software\\Lenny\\Translator")
        .map_err(|_| "Cannot save shortcuts")?;
    key.set_value("Shortcuts", &codes)
        .map_err(|_| "Cannot save shortcuts")?;
    unsafe {
        windows_sys::Win32::UI::Shell::SHChangeNotify(
            0x08000000,
            0,
            std::ptr::null(),
            std::ptr::null(),
        );
    }
    Ok(())
}
