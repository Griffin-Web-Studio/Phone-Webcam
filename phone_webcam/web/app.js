// @ts-check
"use strict";

/** @typedef {import("./types").WebcamEvent} WebcamEvent */
/** @typedef {import("./types").Orientation} Orientation */
/** @typedef {import("./types").PreviewEvent} PreviewEvent */
/** @typedef {import("./types").CameraInfo} CameraInfo */
/** @typedef {import("./types").PhoneState} PhoneState */
/** @typedef {import("./types").StreamSettings} StreamSettings */

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
const previewPanel = byId("preview-panel", HTMLElement);
const previewImg = byId("preview-img", HTMLImageElement);
const cameraSelect = byId("camera", HTMLSelectElement);
const camerasRefresh = byId("cameras-refresh", HTMLButtonElement);
const setResolution = byId("set-resolution", HTMLSelectElement);
const setFps = byId("set-fps", HTMLSelectElement);
const setBitrate = byId("set-bitrate", HTMLSelectElement);
const setPreviewFps = byId("set-preview-fps", HTMLSelectElement);
const appMain = byId("app", HTMLElement);
const phoneOverlay = byId("phone", HTMLElement);
const phoneTitle = byId("phone-title", HTMLElement);
const phoneText = byId("phone-text", HTMLElement);
const busy = byId("busy", HTMLElement);
const busyText = byId("busy-text", HTMLElement);
const busyDismiss = byId("busy-dismiss", HTMLButtonElement);
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
  switching: "Switching camera...",
  applying: "Applying settings...",
};

/**
 * @param {string} state
 */
function setState(state) {
  statusEl.textContent = LABELS[state] ?? state;
  statusEl.dataset.state = state;
  startBtn.disabled = state !== "stopped";
  stopBtn.disabled = state === "stopped" || state === "stopping";
  cameraSelect.disabled = ["switching", "applying", "stopping"].includes(state);
  // The resolution is the output's format, so it only changes while stopped.
  // The frame rate and bitrate restart the phone side and so can change live,
  // but not in the middle of another change.
  const settled = state === "stopped" || state === "running";
  setResolution.disabled = state !== "stopped";
  setFps.disabled = !settled;
  setBitrate.disabled = !settled;
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
 * @param {StreamSettings} settings
 */
function showSettings(settings) {
  setResolution.value = settings.resolution;
  setFps.value = String(settings.fps);
  setBitrate.value = String(settings.bitrate);
  setPreviewFps.value = String(settings.preview_fps);
}

function saveSettings() {
  window.pywebview.api.set_settings({
    resolution: setResolution.value,
    fps: Number(setFps.value),
    bitrate: Number(setBitrate.value),
    preview_fps: Number(setPreviewFps.value),
  });
}

/** @type {Record<Exclude<PhoneState, "ready">, [string, string]>} */
const PHONE_NOTICES = {
  missing: [
    "No phone connected",
    "Connect your phone with a USB cable and turn on USB debugging.",
  ],
  unauthorised: [
    "Approve USB debugging",
    "Look at your phone and tap Allow on the USB debugging request.",
  ],
  offline: [
    "The phone is not responding",
    "Unplug the phone and plug it in again.",
  ],
  unavailable: [
    "adb could not be run",
    "Check that Android platform tools (adb) are installed.",
  ],
};

/** @type {PhoneState | null} */
let phoneState = null;

/**
 * Cover the app until a phone is ready, and load its cameras once it is.
 * There is no way to dismiss this, it goes when the phone is usable.
 * @param {PhoneState} state
 */
function showPhone(state) {
  const wasReady = phoneState === "ready";
  phoneState = state;
  const ready = state === "ready";
  phoneOverlay.hidden = ready;
  appMain.inert = !ready;
  if (!ready) {
    [phoneTitle.textContent, phoneText.textContent] = PHONE_NOTICES[state];
  } else if (!wasReady) {
    loadCameras();
  }
}

/**
 * Fill the camera list, keeping the default first and the choice selected.
 * @param {CameraInfo[]} cameras
 * @param {string} chosen
 */
function showCameras(cameras, chosen) {
  const options = cameras.map((camera) => {
    const option = document.createElement("option");
    option.value = camera.id;
    option.textContent = camera.label;
    return option;
  });
  const fallback = cameraSelect.options[0];
  cameraSelect.replaceChildren(fallback, ...options);
  cameraSelect.value = chosen;
}

async function loadCameras() {
  camerasRefresh.disabled = true;
  try {
    const cameras = await window.pywebview.api.list_cameras();
    showCameras(cameras, await window.pywebview.api.get_camera());
    if (cameras.length === 0) addLog("No cameras found, is the phone connected?");
  } finally {
    camerasRefresh.disabled = false;
  }
}

/**
 * Follow the preview through its states, with a notice while it changes.
 * @param {PreviewEvent["state"]} state
 * @param {string | null} url
 */
function showPreview(state, url) {
  const changing = state === "starting" || state === "stopping";
  busy.hidden = !changing;
  busyText.textContent =
    state === "starting"
      ? "Starting preview, please wait..."
      : "Stopping preview, please wait...";
  previewBtn.disabled = changing;

  if (state === "open" && url !== null) {
    previewImg.src = url;
    previewPanel.hidden = false;
    previewBtn.textContent = "Close preview";
  } else if (state === "closed") {
    previewImg.removeAttribute("src");
    previewPanel.hidden = true;
    previewBtn.textContent = "Preview";
  }
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
      showPreview(event.state, event.url);
      break;
    case "phone":
      showPhone(event.state);
      break;
    case "camera":
      cameraSelect.value = event.id;
      break;
    case "settings":
      showSettings(event);
      break;
    case "confirm":
      confirmMessage.textContent = event.message;
      confirmDialog.showModal();
      break;
  }
};

startBtn.addEventListener("click", () => window.pywebview.api.start());
stopBtn.addEventListener("click", () => window.pywebview.api.stop());
cameraSelect.addEventListener("change", () =>
  window.pywebview.api.set_camera(cameraSelect.value),
);
camerasRefresh.addEventListener("click", loadCameras);
for (const select of [setResolution, setFps, setBitrate, setPreviewFps]) {
  select.addEventListener("change", saveSettings);
}
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
// Dismissing is an escape hatch, so it also frees the button in case a state
// change never arrives.
function dismissBusy() {
  busy.hidden = true;
  previewBtn.disabled = false;
}
busyDismiss.addEventListener("click", dismissBusy);
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") dismissBusy();
});
confirmYes.addEventListener("click", () => answer(true));
confirmNo.addEventListener("click", () => answer(false));
confirmDialog.addEventListener("cancel", () => answer(false));
window.addEventListener("pywebviewready", async () => {
  setState(await window.pywebview.api.get_state());
  showOrientation(await window.pywebview.api.get_orientation());
  showSettings(await window.pywebview.api.get_settings());
  showPhone(await window.pywebview.api.get_phone());
});
