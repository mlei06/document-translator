"use strict";
const { invoke } = window.__TAURI__.core;
const languages = {
  en: "English",
  zh: "Chinese",
  ja: "Japanese",
  es: "Spanish",
};
const activeStates = new Set(["queued", "running"]);
let refreshing = false;
let lastSummary = "";
const cancelling = new Set();
function announce(message) {
  document.getElementById("announcement").textContent = message;
}
function displayError(error) {
  const host = document.getElementById("connection");
  host.textContent = String(error);
  host.hidden = false;
}
function render(groups) {
  const host = document.getElementById("groups");
  const focusedGroup = host.contains(document.activeElement)
    ? document.activeElement?.dataset.group
    : null;
  host.replaceChildren();
  const summary = [];
  if (!groups.length) {
    const empty = document.createElement("p");
    empty.textContent =
      "No active selections. Open Lenny to see recent translations.";
    host.append(empty);
  }
  for (const group of groups) {
    const jobs = group.jobs || [],
      errors = group.errors || [];
    const active = jobs.filter((job) => activeStates.has(job.status)).length;
    const ready = jobs.filter((job) => job.status === "succeeded").length;
    const failed =
      jobs.filter((job) => job.status === "failed").length + errors.length;
    const cancelled = jobs.filter((job) => job.status === "cancelled").length;
    const language = languages[group.target] || group.target;
    const state = group.cancelled
      ? active || group.enumerating
        ? "Stopping batch"
        : "Cancelled"
      : group.enumerating
        ? "Finding files"
        : active
          ? "Translating"
          : "Finished";
    const counts = `${jobs.length} accepted, ${ready} translated, ${active} active, ${failed} need attention${cancelled ? `, ${cancelled} cancelled` : ""}`;
    summary.push(`${language}: ${state}. ${counts}.`);
    const section = document.createElement("section");
    const heading = document.createElement("div");
    heading.className = "heading";
    const title = document.createElement("h2");
    title.textContent = `To ${language}`;
    heading.append(title);
    if (!group.cancelled && (group.enumerating || active)) {
      const cancel = document.createElement("button");
      cancel.textContent = "Cancel batch";
      cancel.dataset.group = group.id;
      cancel.setAttribute("aria-label", `Cancel ${language} batch`);
      cancel.disabled = cancelling.has(group.id);
      cancel.onclick = async () => {
        cancelling.add(group.id);
        cancel.disabled = true;
        try {
          await invoke("cancel_activity", { group: group.id });
          announce(`Cancelling ${language} batch.`);
        } catch (error) {
          displayError(error);
        } finally {
          cancelling.delete(group.id);
          await refresh();
        }
      };
      heading.append(cancel);
    }
    const status = document.createElement("p");
    status.textContent = `${state}. ${counts}.`;
    section.append(heading, status);
    const list = document.createElement("ul");
    for (const job of jobs) {
      const row = document.createElement("li");
      const path = document.createElement("span");
      path.className = "path";
      path.textContent = job.path;
      const state = document.createElement("p");
      state.className = "status";
      state.textContent =
        job.status === "succeeded"
          ? job.output
            ? "Saved successfully"
            : "Translated. Saving the output file."
          : job.status === "running"
            ? "Translating"
            : job.status === "queued"
              ? "Waiting to translate"
              : job.status === "cancelled"
                ? "Cancelled"
                : "Translation failed. Open Lenny for details.";
      if (job.status === "succeeded") state.classList.add("ready");
      if (activeStates.has(job.status)) state.classList.add("active");
      row.append(path, state);
      if (job.output) {
        for (const [label, folder] of [
          ["Open file", false],
          ["Show in folder", true],
        ]) {
          const action = document.createElement("button");
          action.textContent = label;
          action.dataset.group = `${group.id}:${job.id}:${folder}`;
          action.onclick = async () => {
            try {
              await invoke("open_export", { path: job.output, folder });
            } catch (error) {
              displayError(error);
            }
          };
          row.append(action);
        }
      }
      list.append(row);
    }
    for (const error of errors) {
      const row = document.createElement("li");
      const path = document.createElement("span");
      path.className = "path";
      path.textContent = error.path;
      const message = document.createElement("p");
      message.className = "status error";
      message.textContent = `Needs attention: ${error.error}`;
      row.append(path, message);
      list.append(row);
    }
    section.append(list);
    host.append(section);
  }
  if (focusedGroup)
    host
      .querySelector(`[data-group="${CSS.escape(focusedGroup)}"]`)
      ?.focus({ preventScroll: true });
  const next = summary.join(" ");
  if (next !== lastSummary) {
    announce(next);
    lastSummary = next;
  }
}
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const groups = await invoke("activity_state");
    document.getElementById("connection").hidden = true;
    render(groups);
  } catch (error) {
    displayError(error);
  } finally {
    refreshing = false;
  }
}
document.getElementById("open-main").onclick = async () => {
  try {
    await invoke("open_main");
  } catch (error) {
    displayError(error);
  }
};
refresh();
setInterval(refresh, 1000);
