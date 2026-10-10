// @ts-check
"use strict";

/** @typedef {import("./types").CheckItem} CheckItem */
/** @typedef {import("./types").Report} Report */

const title = byId("title", HTMLElement);
const summary = byId("summary", HTMLElement);
const list = byId("checks", HTMLUListElement);
const fix = byId("fix", HTMLElement);
const fixIntro = byId("fix-intro", HTMLElement);
const commandRow = byId("command-row", HTMLElement);
const command = byId("command", HTMLElement);
const copy = byId("copy", HTMLButtonElement);
const recheck = byId("recheck", HTMLButtonElement);
const proceed = byId("continue", HTMLButtonElement);

/**
 * Build one row of the checklist.
 * @param {CheckItem} item
 * @returns {HTMLLIElement}
 */
function renderItem(item) {
  const li = document.createElement("li");
  const state = item.ok ? "ok" : item.required ? "missing" : "optional";
  li.className = state;

  const mark = document.createElement("span");
  mark.className = "mark";
  mark.textContent = item.ok ? "✓" : item.required ? "✕" : "–";

  const label = document.createElement("span");
  label.textContent = item.label;
  li.append(mark, label);

  if (item.detail) {
    const detail = document.createElement("span");
    detail.className = "detail";
    detail.textContent = item.detail;
    li.append(detail);
  }
  return li;
}

/**
 * Leave the gate for the main page.
 */
function proceedToApp() {
  window.location.href = "app.html";
}

/**
 * Show a report. When every check passes, go straight to the app, otherwise
 * offer to continue once nothing blocks.
 * @param {Report} report
 */
function render(report) {
  title.textContent = report.app_name;
  document.title = report.app_name;
  list.replaceChildren(...report.checks.map(renderItem));

  const missing = report.checks.filter((c) => !c.ok);
  fix.hidden = missing.length === 0;
  commandRow.hidden = report.command === null;
  command.textContent = report.command ?? "";
  fixIntro.textContent = report.command
    ? "Install the missing packages with:"
    : "Install the missing items with your distribution's package manager.";

  proceed.hidden = !report.ready;
  summary.textContent = report.ready
    ? "Everything required is in place."
    : "Some required items are missing.";

  if (report.checks.every((c) => c.ok)) proceedToApp();
}

async function refresh() {
  recheck.disabled = true;
  summary.textContent = "Checking your system...";
  try {
    render(await window.pywebview.api.get_report());
  } catch (err) {
    summary.textContent = `The check failed: ${err}`;
  } finally {
    recheck.disabled = false;
  }
}

copy.addEventListener("click", async () => {
  try {
    await window.pywebview.api.copy_text(command.textContent ?? "");
    copy.textContent = "Copied";
  } catch {
    // Copying through Python failed, so select the text for Ctrl+C.
    const range = document.createRange();
    range.selectNodeContents(command);
    const selection = window.getSelection();
    selection?.removeAllRanges();
    selection?.addRange(range);
    copy.textContent = "Press Ctrl+C";
  }
  setTimeout(() => (copy.textContent = "Copy"), 1500);
});

recheck.addEventListener("click", refresh);
proceed.addEventListener("click", proceedToApp);
window.addEventListener("pywebviewready", refresh);
