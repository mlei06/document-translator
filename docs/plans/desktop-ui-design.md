# Desktop translation UI design specification

Status: Owner-requested implementation in desktop source, 2026-09-30. Automated verification is recorded in [desktop evidence](unified-desktop-evidence.md); updated installed-shell drag/drop acceptance remains outstanding. This is not a release certification.

## 1. Purpose and authority

Make the existing desktop application easy to use for dropping documents, starting translation and opening saved results. Preserve its simple workplace-tool identity.

The owner's latest direction is explicit: no Lenny character or floating orbs on desktop; users need a clear way to drag files into the app. Follow the [unified product contract](unified-translator-design.md), [architecture](../Architecture.md), ADR-014 storage ownership and ADR-030 desktop delivery. This proposal refines presentation and interactions without changing routing, storage or native runtime architecture.

The unified contract says dropping files followed by clicking a target starts the batch. The current desktop implementation does this. Preserve that behavior, with no additional Translate button or automatic submission on drop. Earlier conversational suggestions about applying a saved language automatically concerned a possible design, not an implemented desktop feature. The website's saved-language preference does not apply here.

## 2. Reviewed baseline

Reviewed `apps/desktop/ui/index.html`, `style.css`, `app.js` and the Tauri window configuration. A browser rendering of these assets at 980 x 720 used simulated native responses; it was not verification of the installed executable.

Current behavior and deficiencies:

- Native `tauri://drag-drop` already adds files and folder roots to a draft. There is no drag-enter/leave visual feedback.
- The draft displays only a count, with no filenames or per-item removal.
- English, Chinese, Japanese and Spanish are red action buttons. Clicking one submits the draft.
- The button labeled Save beside originals actually opens a destination folder chooser. There is no reset after choosing a custom folder.
- Activity renders per-file text and action buttons. Although CSS styles a progress element, the renderer does not create one.
- Offline support and Explorer shortcuts are under collapsed Settings.

Retain the existing Tauri shell, plain HTML/CSS/JavaScript, native pickers, local service and shared desktop/Explorer queue. Do not replace the frontend framework or introduce a separate queue.

## 3. Screen structure

Default content size: 980 x 720. Minimum supported window: 375 x 500. Account for native title-bar space when validating the installed app.

```text
 [existing red icon] Lenny Translator                         Quit
 Translate documents and keep their formatting.

 +--------------------------------------------------------------+
 |                  Drop files or folders here                  |
 |                   Choose files  Choose folders               |
 |                 DOCX, PPTX, XLSX, PDF and TXT                 |
 +--------------------------------------------------------------+

 Selected (2)                                          Clear all
 [Word icon] Quarterly report.docx                              x
 [folder]    Product documents                                  x

 Save translations to: Downloads             Change folder

 Translate to
 [English]       [Chinese]       [Japanese]       [Spanish]
 Clicking a language starts translation.

 Activity                          2 translating / 1 saved
 Document                     Language   Status          Actions
 [Word] Quarterly report.docx  Chinese    Translating     Cancel
 [PPT]  Product overview.pptx  Chinese    Saved           Open ...

 Settings
 Closing this window keeps translations running.
```

The wireframe defines hierarchy, not exact dimensions. Selected files appear only when the draft is nonempty. Activity fills remaining space; avoid large empty cards. Settings expands inline and remains reachable when content overflows.

## 4. Drop and selection workflow

### Drop target

- Use a clearly bounded drop area, approximately 136 px tall when empty, with a neutral dashed border, upload/document icon and centered instruction. It remains available while translations run.
- Keep native whole-window file drops supported. On native drag enter/over, highlight the drop area and display a window-level inset border so users know the current window will accept the drop. Avoid a blocking overlay.
- Use a pale red tint and deep red border during drag. Clear feedback on leave, cancel, successful drop and window blur. The highlight must not flicker when the cursor crosses child elements.
- Native paths, not browser File objects, remain the input to the existing desktop flow. Test real Windows Explorer files and folders in the installed shell.
- Choose files and Choose folders invoke their existing native dialogs and feed the same draft.

### Selected items

- Display each selected file or folder root with an appropriate file-type/folder icon, name and small remove button. Show the full path through an accessible details control; do not depend on hover alone.
- Distinguish identical basenames using their parent folders. Do not claim a selected folder is a single document or show a document total before discovery.
- Use accurate counts: for example, "2 files and 1 folder selected". Offer Clear all for the draft only.
- Rows are approximately 44 px tall. Show up to four rows before a bounded, normally visible scroll area is needed. Keep language actions visible at the default size.
- Deduplicate exact selected paths using the existing draft behavior. Do not enumerate whole folders merely to draw the draft list.
- Remove and Clear all do not cancel accepted jobs or delete source files.
- Unsupported direct files receive an inline explanation and cannot enter the submitted batch. Folder discovery retains its per-file validation and error reporting; corrupt, inaccessible or encrypted documents must not fail silently.

### Starting a batch

- Label the action group "Translate to" with the helper "Clicking a language starts translation."
- Keep the four existing supported targets. Use neutral outlined buttons with a red hover/focus treatment. All four are equivalent actions, so do not fill all four with red or imply a persistent selected target.
- Accessible names explicitly include the action, for example "Translate to Chinese".
- With an empty draft, disable the target buttons. Once a valid file or folder root is selected, permit immediate target selection without waiting for folder discovery or language detection.
- Clicking a language atomically snapshots the draft roots, target and destination, clears that draft and starts the existing discovery/admission flow. Prevent duplicate submission from repeated clicks.
- Files dropped afterward form a new draft. Destination changes and later target clicks must never retarget accepted work.
- Keep target-only language behavior. Unknown, mixed or same-as-target detection must not result in a silent no-op.

## 5. Output destination

Replace the current Save beside originals button with a separate secondary row:

**Save translations to:** Downloads · **Change folder**

- Downloads is resolved through the Windows known-folder API, including redirected Downloads folders. The actual destination path is shown. If unavailable, require an explicit folder choice; never fall back to the source folder.
- Change folder opens the native folder picker. Cancel leaves the current destination unchanged.
- After choosing a folder, show the path, Change folder and Use Downloads. Reset restores the resolved Downloads path. Picker cancellation preserves the existing choice.
- Wrap long paths without pushing actions outside the window. Provide the full path accessibly.
- Destination applies to future batches and is pinned when the user clicks a language. Keep the current session-only behavior; do not introduce preference persistence in this UI change.
- Export into the chosen folder directly, without recreating the source folder tree. Preserve collision-safe naming and automatic export. Example: `report.docx` translated to Chinese becomes `report.zh.docx`; existing files are never overwritten.
- Optional short help: "Translated copies save automatically. Originals stay unchanged."

The source path is used for local ingestion and failed-job retry only, not destination selection. Accepted input is a temporary snapshot, so exporting does not require the original to remain at its old path. Successful export removes the source path from the export journal. Explorer submissions use Downloads; main-window custom folders apply to that window's future batches.

There is no ordinary Save step after translation. Save retry and alternate-folder controls appear only when automatic export fails.

## 6. Activity and progress

Use one compact list for jobs received from both the window and Explorer. No floating bubbles, duplicate history panel or separate permanent document library.

- Desktop columns: Document (flexible), Language (88 px), Status (160 px), Actions (content width). Rows are approximately 64 px tall, expanding for errors or long names.
- Use existing-style Office/PDF/text icons with accessible textual filenames. Do not encode file type or status by color alone.
- Preserve stable row ordering while statuses update. Append newly received jobs, retain keyboard focus and do not recreate focused controls unnecessarily during polling.
- Summary counts derive from actual items. Folder discovery has its own compact line: "Finding documents: 12 found", with Stop adding files. Explain that accepted translations continue when discovery alone is stopped.
- Keep active progress separate from folder-discovery counts. A count of discovered files is not a completion percentage.

| State | Visible treatment | Actions |
| --- | --- | --- |
| Admitting / waiting for capacity | Adding to queue / Waiting for queue space | Cancel |
| Queued | Queued, neutral indicator | Cancel |
| Running | Translating, deep red activity indicator | Cancel |
| Translation succeeded, export pending | Saving, indeterminate indicator only while export is actually pending | No redundant Save action |
| Exported | Saved, green check | Open file; Show in folder and Dismiss in overflow |
| Translation failed | Needs attention, concise explanation | Retry when supported; Dismiss |
| Export failed | Couldn't save, destination/error explanation | Retry save; Choose folder; Dismiss |
| Cancelled | Cancelled, neutral indicator | Retry when supported; Dismiss |

Implementation inspection verified that desktop recent status includes `JobOut.progress` with phase, done and total. Display a determinate bar during the translate phase when valid counts exist, labeled "7 of 20 text units", not a whole-document percentage. Use honest indeterminate activity during other running phases or when counts are unavailable. No new progress API or simulated completion timers are required.

An export failure must retain the translated result for retry through the existing lifecycle, without rerunning inference. Dismiss removes activity according to the existing service contract; it does not delete originals or exported files.

## 7. Visual system

- Preserve the existing red square app icon and white characters exactly. No mascot, meadow, pointer parallax, eating animation or Lenovo endorsement text.
- Keep Geist with Segoe UI fallback. Heading 24 px/600; section heading 16 px/600; body 14 px; secondary labels 13 px. Avoid pale text for critical states.
- Use a neutral canvas (`#F5F5F5`), white panels, near-black text (`#202020`), secondary text (`#595959`) and neutral borders (`#D4D4D4`). Remove the current green cast from neutral surfaces.
- Use red sparingly: brand icon `#E2231A`, action/active progress `#B51F24`, hover `#991B20`, pale selection/drag tint `#FAE9E9`. Success stays green (`#237143`). Error states combine text and an icon with their color.
- Dark mode uses neutral charcoal surfaces, light text, light red active indicators and lighter green success. Validate contrast independently; do not invert the light palette mechanically.
- Buttons use a 6 px radius, panels 8 px. Spacing scale: 4, 8, 12, 16, 24 px. Main padding 24 px, reduced to 16 px in narrow windows.
- Use visible keyboard focus rings, minimum 44 px control hit areas and 4.5:1 contrast for normal text. Small remove/overflow glyphs retain generous hit targets.

## 8. Responsive behavior and accessibility

- At widths below 700 px, activity metadata wraps beneath filenames and actions occupy a second line as needed. Do not force a horizontally scrolling table.
- At 375 px, language actions form a two-column grid; destination controls wrap beneath the path. Header retains icon, title and reachable Quit action.
- At short heights or 200% scaling, allow normal vertical page scrolling. Do not trap controls under fixed panels. Limit nested scroll containers to the long draft list and, only when sufficient height exists, Activity.
- All drop operations have keyboard-accessible picker alternatives. Native picker cancel returns focus to its trigger.
- Announce files added, batch submitted, completion and errors through the existing polite live region. Do not announce every polling refresh.
- Removing a draft item focuses the next remove control, the preceding item if last, or Choose files when empty. Menus support keyboard operation and Escape.
- Respect reduced motion: active state remains clear using static text and icons without requiring animated stripes or spinners.

## 9. Settings and application lifecycle

Keep Settings collapsed initially, containing offline support management and Explorer language shortcuts. Their existing install/repair/remove/cancel and shortcut ordering semantics remain intact. Do not add model or online/offline routing selectors.

Keep Quit distinct from closing the window. Preserve the existing interruption confirmation and background-work behavior. Short footer copy: "Closing this window keeps translations running." The quit dialog explains that active work stops and originals and saved copies remain.

## 10. Implementation scope and acceptance

Implementation is concentrated in `apps/desktop/ui/`, retaining existing service endpoints. A small read-only `inspect_paths` native bridge command is necessary because drop events contain paths without file/folder metadata. It checks at most 256 roots per off-thread call and never enumerates folders. This resolves dotted folders and extensionless files correctly; no queue expansion is involved. The owner's Downloads amendment adds a native `default_export_directory` command; desktop submission now requires an explicit absolute destination, ignores source-relative folder layout, and export retry needs no source-path argument. Path checking is explicitly shown before enabling submission; folder enumeration and language detection do not delay target submission. The architecture documents this bridge refinement. Semantic draft rows, native drag feedback, destination reset, compact activity and honest progress all use the existing lifecycle.

Acceptance scenarios:

1. Drop two files from Explorer: highlight appears, filenames are visible, one can be removed, and clicking Chinese submits the remaining file once.
2. Drop a folder: submit before enumeration finishes; discovered files retain the selected target and destination. Stop discovery without cancelling already accepted files.
3. Drop another file during a running batch: it becomes a new draft and does not change the first batch.
4. Confirm default Downloads, then choose, cancel and reset a destination. Drop a file already in Downloads. Move/remove an original after acceptance and confirm export still works. Verify output placement, original preservation and collision-safe export with real files.
5. Verify queued, running, saved, cancelled, unsupported input, translation failure and export failure layouts. Save retry must not start translation again.
6. Verify same-language translation gives visible work/result or a genuine actionable error, never a silent no-op.
7. Open and reveal a saved result. Dismiss its activity without deleting the exported file.
8. Confirm Explorer submissions appear in the same list and reopening the window reconnects to accepted work.
9. Review empty, four-item draft and 20-job layouts at 980 x 720, 700 x 600 and 375 x 500; light/dark modes; 200% scaling; keyboard-only and reduced-motion settings. No horizontal overflow, clipped controls or lost focus during refresh.
10. Validate native drag enter/leave/drop and picker behavior in the actual Windows shell, not just mocked browser events. Browser previews cover visual states but are not native acceptance evidence.

For implementation, run relevant desktop tests, meaningful UI interaction checks and all six repository checks listed in AGENTS.md. Record native verification and screenshots separately from simulated preview evidence. Current automated results and outstanding installed-shell verification are recorded in the desktop evidence document.

Deferred: additional languages, saved desktop target preferences, progress API expansion, new batch actions and installer/release changes. These require their own product or service scope; this design must not invent them while refining the existing workflow.
