# Lenny Windows application

The Windows shell is Tauri2, the Explorer extension is an in-process IExplorerCommand DLL, and the translation host is the existing server frozen with PyInstaller. Translation remains in the shared JobService, Worker and core; the WebView only calls native commands and never receives the loopback bearer or Davy credentials.

## Build

From the repository root on Windows11 x64, install Rust, Visual Studio2022 Build Tools with the C++ desktop workload/Windows SDK10.0.26100, and NSIS3.12. The build uses Cargo.lock and two compiler jobs.

```powershell
uv sync --all-packages
./apps/desktop/build-package.ps1
```

This builds an unsigned release-profile shell plus frozen runtime, Explorer DLL, sparse identity and two private installers under `data/desktop-build`. `-DevelopmentBuild` uses the debug shell; `-SkipRuntimeBuild` is only appropriate when the frozen runtime already matches current source. `-Release` rejects development builds and requires `-CertificateThumbprint` for a trusted certificate in the Windows certificate store. `-Publisher` must match that certificate subject. Signing material is never stored in the repository.

`prepare_desktop_resources.py` consumes the already configured Davy endpoint/key without printing them. It creates a current-user-only private resource directory and validates the configuration. Both setup executables are credential-bearing internal artifacts and must remain in restricted distribution. The offline installer includes the approved existing Q8 GGUF; the online installer downloads the same immutable bytes when offline support is selected. Both offer online-only installation, with online+offline recommended by default. `/ONLINE /S` is the silent online-only development lifecycle path.

The fixed approved model is Tencent HY-MT1.5-1.8B Q8_0, upstream revision265b2e615a7dc9b06c435dc878829ad99a512ba2, SHA2566789b06d0902f2f5312c0e1703d56ccbddfcfb6c653d22519b7c720f7db9a98e. The resource preparation verifies the local file, pins all runtime DLLs and signs them before hashing when a certificate is supplied. The approved runtime uses Vulkan, four generation/prompt threads, four slots and context16384. Startup must observe Vulkan and full GPU offload; there is no silent CPU substitute.

The sparse MSIX deliberately contains identity/visual assets and references external installed binaries. Microsoft's sparse-package workflow requires MakeAppx `/nv` because normal semantic validation expects those binaries inside the archive. This does not replace installed-package validation. See https://blogs.windows.com/windowsdeveloper/2019/10/29/identity-registration-and-activation-of-non-packaged-win32-apps/ . Windows registration still requires a trusted signature matching Publisher.

## Verification

The main-window design is specified in `docs/plans/desktop-ui-design.md`. It uses native drop events and the read-only `inspect_paths` bridge to display selected files/folders before the language action submits them. Browser interaction tests use the existing web project's Playwright installation and mock native responses; they do not certify Windows drag/drop:

```powershell
node --test apps/desktop/tests/ui.test.cjs
cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml --locked -j 2
```

UI screenshots from that suite are written under `data/desktop-ui-verification`.

New translations export directly to the Windows Downloads known folder unless the main window supplies another folder. The native shell pins that explicit destination for each batch. Source paths are used only for ingestion/retry, and successful export clears them from the export journal. This change updates both the shell and Python desktop API; rebuild the runtime as well as the shell before installing it (`-SkipRuntimeBuild` is not appropriate with an older runtime).

```powershell
uv run pytest apps/server/tests/test_desktop.py apps/server/tests/test_desktop_assets.py apps/server/tests/test_desktop_lifecycle.py
cmd /c apps\desktop\explorer\smoke.cmd
uv run python scripts/desktop_host_smoke.py data/desktop-build/payload/runtime/doctranslator-server.exe
```

The native COM smoke calls the real compiled DLL factory, enumerates configured shortcuts and verifies unload/reference ownership. The host smoke is a real Davy translation and rejects missing bearer and browser Origin. Optional real HY inference uses `DOCTRANSLATOR_TEST_LLAMA_EXE` and `DOCTRANSLATOR_TEST_GGUF` with `pytest -m integration apps/server/tests/test_desktop_runtime_integration.py`.

The application data root is the Windows known LocalAppData folder plus `Lenny/Translator`, ACL restricted to the current SID. The app retains bounded journal/job metadata, runs shared retention every five minutes, and disables daily backups for transient desktop work. Successful export releases managed source/result/report bytes after durable verified publication; exports and originals remain user-owned. Uninstall preserves these files and shortcut preferences, refuses unexpected/reparse installation paths, and checks owned processes have exited before recursive application deletion.

Current acceptance evidence and remaining signing/clean-machine gates are recorded in `docs/plans/unified-desktop-evidence.md`. Unsigned development execution, mocks and developer-machine local inference are not substitutes for signed modern Explorer menu and network-disabled clean-machine installer tests.
