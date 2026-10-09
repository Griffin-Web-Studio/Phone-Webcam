// @ts-check
"use strict";

/** @typedef {import("./types").WebcamEvent} WebcamEvent */

const statusEl = byId("status", HTMLElement);
const startBtn = byId("start", HTMLButtonElement);
const stopBtn = byId("stop", HTMLButtonElement);
const logEl = byId("log", HTMLElement);

/** @type {Record<string, string>} */
const LABELS = {
  stopped: "Stopped",
  starting: "Starting...",
  running: "Running",
  stopping: "Stopping...",
};

/**
 * @param {string} state
 */
function setState(state) {
  statusEl.textContent = LABELS[state] ?? state;
  statusEl.dataset.state = state;
  startBtn.disabled = state !== "stopped";
  stopBtn.disabled = state === "stopped" || state === "stopping";
}

/**
 * @param {string} line
 */
function addLog(line) {
  // Only follow the output while the reader is already at the bottom.
  const gap = logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight;
  const atBottom = gap < 8;
  logEl.append(`${line}\n`);
  if (atBottom) logEl.scrollTop = logEl.scrollHeight;
}

/**
 * Called from Python through evaluate_js.
 * @param {WebcamEvent} event
 */
window.onWebcamEvent = (event) => {
  if (event.type === "state") setState(event.state);
  else addLog(event.line);
};

startBtn.addEventListener("click", () => window.pywebview.api.start());
stopBtn.addEventListener("click", () => window.pywebview.api.stop());
window.addEventListener("pywebviewready", async () => {
  setState(await window.pywebview.api.get_state());
});
