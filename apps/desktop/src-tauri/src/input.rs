//! Read only the selected roots, never enumerate folders during draft selection.
use serde::Serialize;

#[tauri::command]
pub fn default_export_directory() -> Result<String, String> {
    dirs::download_dir()
        .map(|path| path.to_string_lossy().into_owned())
        .ok_or_else(|| "Downloads is unavailable. Choose an export folder.".into())
}

#[derive(Serialize)]
pub struct InputPath {
    path: String,
    kind: &'static str,
    error: Option<String>,
}

fn inspect(path: String) -> InputPath {
    let (kind, error) = match std::fs::metadata(&path) {
        Ok(meta) if meta.is_dir() => ("folder", None),
        Ok(meta) if meta.is_file() => ("file", None),
        Ok(_) => ("unknown", Some("Choose a regular file or folder".into())),
        Err(_) => (
            "unknown",
            Some("Cannot access this path. Check that it exists and is available.".into()),
        ),
    };
    InputPath { path, kind, error }
}

#[tauri::command]
pub async fn inspect_paths(paths: Vec<String>) -> Result<Vec<InputPath>, String> {
    if paths.len() > 256 {
        return Err("Inspect at most 256 paths at a time".into());
    }
    tauri::async_runtime::spawn_blocking(move || paths.into_iter().map(inspect).collect())
        .await
        .map_err(|_| "Could not check selected paths".into())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn dotted_folder_and_extensionless_file_are_not_guessed_from_names() {
        let root = std::env::temp_dir().join(format!("lenny-input-{}", std::process::id()));
        std::fs::create_dir_all(root.join("Folder.v2")).unwrap();
        std::fs::write(root.join("README"), "text").unwrap();
        assert_eq!(
            inspect(root.join("Folder.v2").to_string_lossy().into()).kind,
            "folder"
        );
        assert_eq!(
            inspect(root.join("README").to_string_lossy().into()).kind,
            "file"
        );
        assert!(inspect(root.join("missing").to_string_lossy().into())
            .error
            .is_some());
        std::fs::remove_file(root.join("README")).unwrap();
        std::fs::remove_dir(root.join("Folder.v2")).unwrap();
        std::fs::remove_dir(root).unwrap();
    }
}
