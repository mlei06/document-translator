"use strict";
const { invoke } = window.__TAURI__.core;
const $ = (id) => document.getElementById(id);
const languageNames = {
  en: "English",
  zh: "Chinese",
  ja: "Japanese",
  es: "Spanish",
};
const formats = { docx: "W", pptx: "P", xlsx: "X", pdf: "PDF", txt: "TXT" };
const activeStates = ["running", "queued", "submitting", "waiting"];
const items = new Map(),
  discoveries = new Map(),
  dismissed = new Set();
let draft = [],
  destination = null,
  defaultDestination = null,
  refreshing = false;

async function api(method, path, body = null) {
  try {
    return await invoke("api", { method, path, body });
  } catch (raw) {
    let detail;
    try {
      detail = JSON.parse(String(raw));
    } catch {
      /* Native transport failure. */
    }
    const error = new Error(
      detail?.error?.message ||
        detail?.message ||
        detail?.detail ||
        String(raw),
    );
    error.code = detail?.error?.code || detail?.code;
    throw error;
  }
}
function announce(message) {
  $("announcement").textContent = message;
}
function button(text, action, label = text) {
  const element = document.createElement("button");
  element.textContent = text;
  element.setAttribute("aria-label", label);
  element.onclick = async () => {
    element.disabled = true;
    try {
      await action();
    } catch (error) {
      announce(error.message || String(error));
    } finally {
      element.disabled = false;
    }
  };
  return element;
}
function basename(path) {
  return path.split(/[\\/]/).pop() || path;
}
function extension(path) {
  const name = basename(path);
  return name.includes(".") ? name.split(".").pop().toLowerCase() : "";
}
function fileIcon(path, kind = "file") {
  const icon = document.createElement("span"),
    ext = extension(path);
  icon.className = `file-icon ${kind === "folder" ? "folder" : formats[ext] ? ext : "generic"}`;
  icon.textContent = kind === "folder" ? "▰" : formats[ext] || "FILE";
  icon.setAttribute("aria-hidden", "true");
  return icon;
}
function pathDetails(path) {
  const details = document.createElement("details");
  details.className = "path-details";
  const summary = document.createElement("summary");
  summary.textContent = basename(path);
  summary.title = path;
  summary.setAttribute("aria-label", `${basename(path)}: show full path`);
  const full = document.createElement("p");
  full.textContent = path;
  details.append(summary, full);
  return details;
}
function updateDraft() {
  $("draft-section").hidden = !draft.length;
  const files = draft.filter((item) => item.kind === "file").length;
  const folders = draft.filter((item) => item.kind === "folder").length;
  const unknown = draft.length - files - folders;
  $("selection").textContent =
    [
      files && `${files} file${files === 1 ? "" : "s"}`,
      folders && `${folders} folder${folders === 1 ? "" : "s"}`,
      unknown && `${unknown} item${unknown === 1 ? "" : "s"} to check`,
    ]
      .filter(Boolean)
      .join(" and ") + " selected";
  const host = $("draft-list");
  const focusedPath = host.contains(document.activeElement)
    ? document.activeElement.closest("li")?.dataset.path
    : null;
  const focusedTag = document.activeElement?.tagName;
  const openPaths = new Set(
    [...host.querySelectorAll("details[open]")].map(
      (el) => el.closest("li").dataset.path,
    ),
  );
  host.replaceChildren();
  for (const entry of draft) {
    const row = document.createElement("li");
    row.dataset.path = entry.path;
    row.append(fileIcon(entry.path, entry.kind));
    const info = document.createElement("div"),
      details = pathDetails(entry.path);
    details.open = openPaths.has(entry.path);
    info.append(details);
    if (
      draft.some(
        (other) =>
          other !== entry && basename(other.path) === basename(entry.path),
      )
    ) {
      const parent = document.createElement("p");
      parent.className = "help";
      parent.textContent = entry.path.slice(0, -basename(entry.path).length);
      info.append(parent);
    }
    if (entry.error || entry.checking) {
      const message = document.createElement("p");
      message.className = entry.error ? "input-error" : "help";
      message.textContent = entry.error || "Checking selected path…";
      info.append(message);
    }
    row.append(info);
    const remove = button(
      "×",
      () => {
        const index = draft.indexOf(entry);
        draft = draft.filter((item) => item !== entry);
        updateDraft();
        const controls = host.querySelectorAll("button");
        (controls[Math.min(index, controls.length - 1)] || $("files")).focus();
      },
      `Remove ${basename(entry.path)}`,
    );
    remove.className = "icon-button quiet";
    row.append(remove);
    host.append(row);
    if (entry.path === focusedPath)
      (focusedTag === "SUMMARY"
        ? details.querySelector("summary")
        : remove
      ).focus({ preventScroll: true });
  }
  document.querySelectorAll("[data-target]").forEach((element) => {
    element.disabled =
      !destination ||
      draft.some((item) => item.checking) ||
      !draft.some((item) => !item.error);
  });
}
async function addPaths(paths) {
  const added = paths
    .filter(
      (path, index) =>
        paths.indexOf(path) === index &&
        !draft.some((item) => item.path === path),
    )
    .map((path) => ({ path, kind: "unknown", checking: true }));
  draft.push(...added);
  updateDraft();
  for (let start = 0; start < added.length; start += 256) {
    const entries = added.slice(start, start + 256);
    try {
      const checked = await invoke("inspect_paths", {
        paths: entries.map((item) => item.path),
      });
      for (const entry of entries) {
        const result = checked.find((item) => item.path === entry.path);
        Object.assign(entry, result || { error: "Could not check this path" }, {
          checking: false,
        });
        if (
          !entry.error &&
          entry.kind === "file" &&
          !formats[extension(entry.path)]
        )
          entry.error =
            "Unsupported file type. Choose DOCX, PPTX, XLSX, PDF or TXT.";
      }
    } catch (error) {
      entries.forEach((entry) =>
        Object.assign(entry, { checking: false, error: String(error) }),
      );
    }
    updateDraft();
  }
  if (added.some((entry) => draft.includes(entry)))
    announce(
      `${added.length} selected item${added.length === 1 ? "" : "s"} added. Choose a language to translate.`,
    );
}
async function pick(folders) {
  const trigger = folders ? $("folders") : $("files");
  try {
    await addPaths(await invoke("pick", { folders }));
  } catch (error) {
    announce(String(error));
  } finally {
    trigger.focus();
  }
}
$("files").onclick = () => pick(false);
$("folders").onclick = () => pick(true);
$("clear-draft").onclick = () => {
  draft = [];
  updateDraft();
  $("files").focus();
};
function updateDestination() {
  $("destination-path").textContent = destination || "Choose an export folder";
  $("reset-destination").hidden =
    !defaultDestination || destination === defaultDestination;
  updateDraft();
}
$("destination").onclick = async () => {
  try {
    const paths = await invoke("pick", { folders: true });
    if (paths.length) {
      destination = paths[0];
      updateDestination();
    }
  } catch (error) {
    announce(String(error));
  } finally {
    $("destination").focus();
  }
};
$("reset-destination").onclick = () => {
  destination = defaultDestination;
  updateDestination();
  $("destination").focus();
};
invoke("default_export_directory")
  .then((path) => {
    defaultDestination = path;
    if (!destination) destination = path;
    updateDestination();
  })
  .catch((error) => {
    updateDestination();
    announce(String(error));
  });

function renderDiscoveries() {
  const host = $("discoveries");
  host.replaceChildren();
  for (const group of discoveries.values()) {
    const row = document.createElement("div");
    row.className = "discovery";
    const text = document.createElement("span");
    text.textContent = `${group.cancelled ? "Stopping discovery" : "Finding documents"}: ${group.count} found for ${languageNames[group.target]}`;
    row.append(text);
    if (!group.cancelled)
      row.append(
        button(
          "Stop adding files",
          async () => {
            group.cancelled = true;
            // Stop discovery, but do not cancel already accepted translations.
            if (group.waiting && !group.waiting.accepted)
              group.waiting.cancelled = true;
            renderDiscoveries();
            if (group.cursor)
              await api("DELETE", `/v1/desktop/discover/${group.cursor}`);
            announce(
              "Folder discovery stopped. Accepted translations continue.",
            );
          },
          `Stop adding files to ${languageNames[group.target]} batch`,
        ),
      );
    host.append(row);
  }
}

function renderItem(item) {
  const row = document.createElement("div");
  row.className = "item";
  row.dataset.id = item.id;
  row.setAttribute("role", "listitem");
  const info = document.createElement("div");
  info.className = "document-cell";
  const name = document.createElement("div");
  name.className = "filename";
  name.textContent = item.name;
  name.title = item.path || item.name;
  info.append(fileIcon(item.name), name);
  const language = document.createElement("div");
  language.className = "language-cell";
  language.textContent = languageNames[item.target] || item.target || "";
  language.setAttribute("aria-label", `Translate to ${language.textContent}`);
  const state = document.createElement("div");
  state.className = "state-cell";
  const status = document.createElement("p");
  status.className = "status";
  const error =
    item.error || (item.status === "failed" ? item.error_message : null);
  const saving = item.status === "succeeded" && !item.output;
  status.textContent = item.output
    ? "✓ Saved"
    : error
      ? saving
        ? "Couldn't save"
        : "Needs attention"
      : item.cancel_requested
        ? "Cancelling"
        : {
            running: "Translating",
            queued: "Queued",
            submitting: "Adding to queue",
            waiting: "Waiting for queue space",
            cancelled: "Cancelled",
            failed: "Failed",
            succeeded: "Saving",
          }[item.status] || item.status;
  if (item.output) status.classList.add("ready");
  if (error) status.classList.add("input-error");
  state.append(status);
  if ((item.status === "running" || saving) && !error) {
    const progress = document.createElement("progress");
    progress.setAttribute(
      "aria-label",
      `${saving ? "Saving" : "Translating"} ${item.name}`,
    );
    // These counts measure translation units, not overall document completion.
    const snapshot = item.progress;
    if (
      !saving &&
      snapshot?.phase === "translate" &&
      Number.isFinite(snapshot.done) &&
      Number.isFinite(snapshot.total) &&
      snapshot.total > 0 &&
      snapshot.done >= 0
    ) {
      progress.max = snapshot.total;
      progress.value = Math.min(snapshot.done, snapshot.total);
      const count = document.createElement("small");
      count.textContent = `${progress.value} of ${snapshot.total} text units`;
      state.append(count);
    }
    state.append(progress);
  }
  row.append(info, language, state);
  const actions = document.createElement("div");
  actions.className = "item-actions";
  const control = (text, action, host = actions) =>
    host.append(button(text, action, `${text} ${item.name}`));
  if (activeStates.includes(item.status)) {
    control("Cancel", async () => {
      item.cancelled = true;
      if (item.accepted) {
        await api("POST", `/v1/jobs/${item.id}/cancel`);
        item.cancel_requested = true;
      } else item.status = "cancelled";
      render();
      await refresh();
    });
  }
  const more = document.createElement("details");
  more.className = "more-actions";
  const toggle = document.createElement("summary");
  toggle.textContent = "···";
  toggle.setAttribute("role", "button");
  toggle.setAttribute("aria-label", `More actions for ${item.name}`);
  const menu = document.createElement("div");
  menu.className = "action-menu";
  more.append(toggle, menu);
  if (item.output) {
    control("Open file", () =>
      invoke("open_export", { path: item.output, folder: false }),
    );
    control(
      "Show in folder",
      () => invoke("open_export", { path: item.output, folder: true }),
      menu,
    );
  }
  if (saving && error) {
    control("Retry save", () => save(item));
    control(
      "Choose folder",
      async () => {
        const paths = await invoke("pick", { folders: true });
        if (paths.length) await save(item, paths[0]);
      },
      menu,
    );
  }
  if (
    ["failed", "cancelled"].includes(item.status) &&
    !item.admitting &&
    item.path &&
    item.target
  )
    control("Retry", () => retry(item));
  if (
    !item.admitting &&
    (item.output || error || ["failed", "cancelled"].includes(item.status)) &&
    !activeStates.includes(item.status)
  ) {
    control(
      "Dismiss",
      async () => {
        if (item.accepted) await api("POST", `/v1/jobs/${item.id}/dismiss`);
        dismissed.add(item.id);
        items.delete(item.id);
        render();
        $("queue-title").focus();
      },
      menu,
    );
  }
  if (menu.childElementCount) actions.append(more);
  row.append(actions);
  if (error || (item.fallback && item.status === "running")) {
    const detail = document.createElement("p");
    detail.className = `item-detail ${error ? "input-error" : "help"}`;
    detail.textContent = error || item.fallback;
    row.append(detail);
  }
  return row;
}
function render() {
  const queue = $("queue");
  const active = queue.contains(document.activeElement)
    ? document.activeElement
    : null;
  const focusedId = active?.closest(".item")?.dataset.id;
  const focusedLabel = active?.getAttribute("aria-label");
  const values = [...items.values()];
  $("queue-columns").hidden = !values.length;
  const running = values.filter(
    (item) =>
      activeStates.includes(item.status) ||
      (item.status === "succeeded" && !item.output && !item.error),
  ).length;
  const saved = values.filter((item) => item.output).length;
  const failed = values.filter(
    (item) => item.error || item.status === "failed",
  ).length;
  $("activity-summary").textContent = [
    running && `${running} active`,
    saved && `${saved} saved`,
    failed && `${failed} need attention`,
  ]
    .filter(Boolean)
    .join(" · ");
  queue.querySelector(".empty")?.remove();
  for (const row of queue.querySelectorAll(":scope > *"))
    if (!items.has(row.dataset.id)) row.remove();
  for (const item of values) {
    const existing = [...queue.children].find(
      (row) => row.dataset.id === item.id,
    );
    const signature = JSON.stringify(item);
    if (existing?.dataset.signature === signature) continue;
    const replacement = renderItem(item);
    replacement.dataset.signature = signature;
    if (existing) {
      const open = existing.querySelector(".more-actions")?.open;
      const details = replacement.querySelector(".more-actions");
      if (details) details.open = !!open;
      existing.replaceWith(replacement);
    } else queue.append(replacement);
  }
  if (!items.size) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Your translations will appear here.";
    queue.append(empty);
  }
  if (focusedId && focusedLabel && !document.activeElement?.closest(".item")) {
    const row = [...queue.children].find((el) => el.dataset.id === focusedId);
    const next =
      row?.querySelector(`[aria-label="${CSS.escape(focusedLabel)}"]`) ||
      row?.querySelector("button, summary");
    (next || $("queue-title")).focus({ preventScroll: true });
  }
}
async function save(item, output = null) {
  try {
    const result = await api("POST", `/v1/desktop/jobs/${item.id}/export`, {
      destination: output,
    });
    item.output = result.path;
    item.error = null;
    announce(`Saved ${item.name}`);
  } catch (error) {
    item.error = error.message;
    announce(`Couldn't save ${item.name}: ${error.message}`);
  }
  render();
}
async function admit(item, group = null) {
  item.admitting = true;
  try {
    await performAdmission(item, group);
  } finally {
    item.admitting = false;
    render();
  }
}
async function performAdmission(item, group = null) {
  const previous = item.id;
  // Backpressure retries keep this identity. An explicit Retry creates a new one.
  while (!item.cancelled && !group?.cancelled) {
    try {
      const job = await api("POST", "/v1/desktop/submit", {
        path: item.path,
        target: item.target,
        submission_id: item.submissionId,
        destination: item.destination,
      });
      items.delete(previous);
      Object.assign(item, job, { accepted: true, error: null });
      items.set(item.id, item);
      if (item.cancelled) await api("POST", `/v1/jobs/${item.id}/cancel`);
      render();
      return;
    } catch (error) {
      if (error.code === "queue_full") {
        item.status = "waiting";
        render();
        await new Promise((resolve) => setTimeout(resolve, 2000));
        continue;
      }
      item.error = error.message;
      item.status = "failed";
      announce(`${item.name}: ${error.message}`);
      render();
      return;
    }
  }
  item.status = "cancelled";
  item.error = null;
  render();
}
function newItem(file, target, output) {
  const id = crypto.randomUUID();
  const item = {
    id,
    submissionId: id,
    path: file.path,
    name: file.name || basename(file.path),
    target,
    destination: output,
    status: file.error ? "failed" : "submitting",
    error: file.error,
    accepted: false,
  };
  items.set(id, item);
  return item;
}
async function retry(previous) {
  if (previous.retrying) return;
  previous.retrying = true;
  try {
    if (previous.accepted) await api("POST", `/v1/jobs/${previous.id}/dismiss`);
  } catch (error) {
    previous.retrying = false;
    throw error;
  }
  dismissed.add(previous.id);
  items.delete(previous.id);
  const item = newItem(
    { path: previous.path, name: previous.name },
    previous.target,
    previous.destination,
  );
  render();
  await admit(item);
}
async function submit(target) {
  if (!destination) {
    announce("Choose an export folder before translating.");
    return;
  }
  if (draft.some((item) => item.checking)) return;
  const selected = draft.filter((item) => !item.error && !item.checking);
  if (!selected.length) return;
  const paths = selected.map((item) => item.path),
    output = destination;
  draft = draft.filter((item) => !selected.includes(item));
  updateDraft();
  $("files").focus();
  announce(
    `Starting ${selected.length} selected item${selected.length === 1 ? "" : "s"} in ${languageNames[target]}.`,
  );
  const id = crypto.randomUUID(),
    group = { target, count: 0, cancelled: false };
  discoveries.set(id, group);
  renderDiscoveries();
  try {
    ({ cursor: group.cursor } = await api("POST", "/v1/desktop/discover", {
      paths,
      destination: output,
    }));
    while (!group.cancelled) {
      const file = await api("GET", `/v1/desktop/discover/${group.cursor}`);
      if (file.done || group.cancelled) break;
      group.count++;
      renderDiscoveries();
      const item = newItem(file, target, output);
      group.waiting = item;
      render();
      if (!file.error) await admit(item, group);
      group.waiting = null;
    }
    if (!group.cancelled && !group.count)
      announce("No supported documents were found in this selection.");
  } catch (error) {
    if (!group.cancelled) {
      if (!group.count) {
        draft.push(
          ...selected.filter(
            (entry) => !draft.some((current) => current.path === entry.path),
          ),
        );
        updateDraft();
      }
      // Preserve an actionable failure if discovery itself cannot start or continue.
      const item = newItem(
        { path: paths[0], name: "Selected documents", error: error.message },
        target,
        output,
      );
      item.path = null;
      render();
      announce(error.message);
    }
  } finally {
    if (group.cursor)
      await api("DELETE", `/v1/desktop/discover/${group.cursor}`).catch(
        () => {},
      );
    discoveries.delete(id);
    renderDiscoveries();
  }
}
document.querySelectorAll("[data-target]").forEach((element) => {
  element.onclick = () => submit(element.dataset.target);
});
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const recent = await api("GET", "/v1/desktop/recent");
    const notices = [];
    for (const row of recent) {
      if (dismissed.has(row.id)) continue;
      const previous = items.get(row.id);
      if (previous && row.output && !previous.output)
        notices.push(`Saved ${row.name}`);
      if (previous && row.error && row.error !== previous.error)
        notices.push(`${row.name}: ${row.error}`);
      if (previous && row.status === "failed" && previous.status !== "failed")
        notices.push(
          `${row.name}: ${row.error_message || "Translation failed"}`,
        );
      if (row.fallback && row.fallback !== previous?.fallback)
        notices.push(`${row.name}: ${row.fallback}`);
      if (previous) Object.assign(previous, row, { accepted: true });
      else items.set(row.id, { ...row, accepted: true });
    }
    if (notices.length) announce(notices.join(". "));
    render();
  } catch (error) {
    announce(error.message);
  } finally {
    refreshing = false;
  }
}
setInterval(refresh, 2000);
$("quit").onclick = () => $("quit-dialog").showModal();
$("keep").onclick = () => $("quit-dialog").close();
$("confirm-quit").onclick = async () => {
  try {
    await invoke("quit");
  } catch (error) {
    announce(String(error));
  }
};
function setDragging(value) {
  document.body.classList.toggle("dragging", value);
}
for (const name of ["tauri://drag-enter", "tauri://drag-over"])
  window.__TAURI__.event.listen(name, () => setDragging(true));
window.__TAURI__.event.listen("tauri://drag-leave", () => setDragging(false));
window.__TAURI__.event.listen("tauri://drag-drop", async (event) => {
  setDragging(false);
  await addPaths(event.payload.paths);
});
window.addEventListener("blur", () => setDragging(false));
window.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    setDragging(false);
    const open = document.querySelector(".more-actions[open]");
    if (open) {
      open.open = false;
      open.querySelector("summary").focus();
    }
  }
});
document.addEventListener("click", (event) => {
  document.querySelectorAll(".more-actions[open]").forEach((el) => {
    if (!el.contains(event.target)) el.open = false;
  });
});
updateDraft();
refresh();

let shortcuts = [];
async function saveShortcuts() {
  await invoke("set_shortcuts", { codes: shortcuts });
  renderShortcuts();
}
function renderShortcuts() {
  const host = $("shortcuts");
  host.replaceChildren();
  shortcuts.forEach((code, index) => {
    const row = document.createElement("div");
    row.className = "actions";
    const name = document.createElement("span");
    name.textContent = languageNames[code];
    row.append(name);
    if (index > 0)
      row.append(
        button(
          "Move up",
          async () => {
            [shortcuts[index - 1], shortcuts[index]] = [
              shortcuts[index],
              shortcuts[index - 1],
            ];
            await saveShortcuts();
          },
          `Move ${languageNames[code]} up`,
        ),
      );
    row.append(
      button(
        "Remove",
        async () => {
          shortcuts.splice(index, 1);
          await saveShortcuts();
        },
        `Remove ${languageNames[code]} shortcut`,
      ),
    );
    host.append(row);
  });
}
$("shortcut-add").onclick = async () => {
  const code = $("shortcut-language").value;
  if (!shortcuts.includes(code)) {
    shortcuts.push(code);
    try {
      await saveShortcuts();
    } catch (error) {
      announce(String(error));
    }
  }
};
invoke("get_shortcuts")
  .then((codes) => {
    shortcuts = codes;
    renderShortcuts();
  })
  .catch((error) => announce(String(error)));
async function offlineStatus() {
  try {
    const state = await api("GET", "/v1/desktop/offline");
    $("offline-state").textContent =
      `${state.state}${state.bytes ? ` - ${(state.bytes / 1024 ** 3).toFixed(2)} GB` : ""}${state.detail ? ` - ${state.detail}` : ""}`;
    for (const id of ["offline-install", "offline-repair", "offline-remove"])
      $(id).disabled = state.state === "Installing";
    $("offline-cancel").disabled = state.state !== "Installing";
  } catch (error) {
    $("offline-state").textContent = error.message;
  }
}
for (const [id, action] of [
  [
    "offline-install",
    async () => {
      await api("POST", "/v1/desktop/offline/install");
      announce(
        "Offline setup started. It will be ready when installation finishes.",
      );
    },
  ],
  [
    "offline-repair",
    async () => {
      await api("DELETE", "/v1/desktop/offline");
      await api("POST", "/v1/desktop/offline/install");
    },
  ],
  ["offline-remove", () => api("DELETE", "/v1/desktop/offline")],
  [
    "offline-cancel",
    async () => {
      await api("POST", "/v1/desktop/offline/cancel");
      announce("Cancelling offline setup");
    },
  ],
])
  $(id).onclick = async () => {
    try {
      await action();
    } catch (error) {
      announce(error.message);
    }
    await offlineStatus();
  };
offlineStatus();
setInterval(offlineStatus, 5000);
