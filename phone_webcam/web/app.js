// @ts-check
"use strict";

/** @typedef {import("./types").WebcamEvent} WebcamEvent */
/** @typedef {import("./types").Orientation} Orientation */

const statusEl = byId("status", HTMLElement);
const startBtn = byId("start", HTMLButtonElement);
const stopBtn = byId("stop", HTMLButtonElement);
const logEl = byId("log", HTMLElement);
const rotateLeft = byId("rotate-left", HTMLButtonElement);
const rotateRight = byId("rotate-right", HTMLButtonElement);
const mirrorBtn = byId("mirror", HTMLButtonElement);
const resetBtn = byId("reset", HTMLButtonElement);
const turnEl = byId("turn", HTMLElement);
const previewBtn = byId("preview", HTMLButtonElement);
const confirmDialog = byId("confirm", HTMLDialogElement);
const confirmMessage = byId("confirm-message", HTMLElement);
const confirmYes = byId("confirm-yes", HTMLButtonElement);
const confirmNo = byId("confirm-no", HTMLButtonElement);

/** @type {Orientation} */
let orientation = { rotation: 0, mirror: false };

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
 * @param {Orientation} next
 */
function showOrientation(next) {
  orientation = next;
  turnEl.textContent = `${next.rotation}°${next.mirror ? ", mirrored" : ""}`;
  mirrorBtn.setAttribute("aria-pressed", String(next.mirror));
}

/**
 * Ask Python to turn the image, which applies on the next frame.
 * @param {number} step quarter turns clockwise, negative for anticlockwise
 */
function turn(step) {
  const rotation = (orientation.rotation + step * 90 + 360) % 360;
  window.pywebview.api.set_orientation(rotation, orientation.mirror);
}

/**
 * @param {boolean} yes
 */
function answer(yes) {
  confirmDialog.close();
  window.pywebview.api.answer(yes);
}

/**
 * Called from Python through evaluate_js.
 * @param {WebcamEvent} event
 */
window.onWebcamEvent = (event) => {
  switch (event.type) {
    case "state":
      setState(event.state);
      break;
    case "log":
      addLog(event.line);
      break;
    case "orientation":
      showOrientation(event);
      break;
    case "preview":
      previewBtn.textContent = event.open ? "Close preview" : "Preview";
      break;
    case "confirm":
      confirmMessage.textContent = event.message;
      confirmDialog.showModal();
      break;
  }
};

startBtn.addEventListener("click", () => window.pywebview.api.start());
stopBtn.addEventListener("click", () => window.pywebview.api.stop());
rotateLeft.addEventListener("click", () => turn(-1));
rotateRight.addEventListener("click", () => turn(1));
mirrorBtn.addEventListener("click", () =>
  window.pywebview.api.set_orientation(
    orientation.rotation,
    !orientation.mirror,
  ),
);
resetBtn.addEventListener("click", () =>
  window.pywebview.api.set_orientation(0, false),
);
previewBtn.addEventListener("click", () =>
  window.pywebview.api.toggle_preview(),
);
confirmYes.addEventListener("click", () => answer(true));
confirmNo.addEventListener("click", () => answer(false));
confirmDialog.addEventListener("cancel", () => answer(false));
window.addEventListener("pywebviewready", async () => {
  setState(await window.pywebview.api.get_state());
  showOrientation(await window.pywebview.api.get_orientation());
});
