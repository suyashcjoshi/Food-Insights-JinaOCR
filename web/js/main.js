// Food Insights, phone-first. Three tabs (Capture, Today, Library) and a Result sheet that opens over
// whichever is showing. No build step, no framework: plain ES modules.
//
//   util.js     helpers, the shared state object, bottom sheets
//   result.js   the Result sheet          library.js   the Library screen
//   today.js    the Today screen (totals against your limits)
//   main.js     this file: tabs, the Capture screen, and the wiring
//
import { $, $$, state, closeLow, isLowSheetOpen, openLow, wireSheets } from "./util.js";
import { loadToday, wireToday } from "./today.js";
import { closeResult, isResultOpen, openResult, wireResult } from "./result.js";
import { loadLibrary, wireLibrary } from "./library.js";

// ---------- tabs: Capture, Today, Library ----------

function setTab(name) {
  state.tab = name;
  $("#screen-capture").hidden = name !== "capture";
  $("#screen-today").hidden = name !== "today";
  $("#screen-library").hidden = name !== "library";
  for (const button of $$(".tabs button")) {
    if (button.dataset.tab === name) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (name === "today") loadToday();
  if (name === "library") loadLibrary();
}

// ---------- Capture screen: a front photo (optional, for the name) and a back photo (the panel) ----------

const MESSAGES = {
  unreachable: "Couldn't reach the app. Check your connection and try again.",
  modelDown: "Couldn't reach the model. Try again in a minute; the first read after idle can take two to three minutes.",
  notAnImage: "That file isn't an image we can read. Choose a JPEG or PNG photo.",
  other: "Something went wrong on our side. Try again in a minute.",
  reading: "Reading the label. The first read after idle can take two to three minutes.",
};
const SLOT_HINTS = {
  front: "The front of the pack, so we can read the name",
  back: "Fit the whole nutrition panel in the frame",
};

function setStatus(message, isError = false) {
  const status = $("#status");
  status.className = "status" + (isError ? " err" : "");
  status.textContent = message;
}

function primaryLabel() {
  if (state.reading) return "Reading…";
  if (state.photos.back) return "Read label";
  return state.slot === "front" && !state.photos.front ? "Take front photo" : "Take back photo";
}

function renderCapture() {
  for (const slot of ["front", "back"]) {
    const photo = state.photos[slot];
    $(`#slot-${slot}`).setAttribute("aria-pressed", String(state.slot === slot));
    const thumb = $(`#${slot}-thumb`);
    thumb.hidden = !photo;
    if (photo) thumb.src = photo.url;
  }
  const shown = state.photos[state.slot];
  $("#preview").hidden = !shown;
  if (shown) $("#preview").src = shown.url;
  $("#finder-hint").hidden = !!shown;
  $("#finder-hint").textContent = SLOT_HINTS[state.slot];
  $("#skip-front").hidden = !(state.slot === "front" && !state.photos.front);
  const button = $("#primary");
  button.textContent = primaryLabel();
  button.disabled = state.reading;
}

function forget(slot) {
  const photo = state.photos[slot];
  if (photo) URL.revokeObjectURL(photo.url);
  state.photos[slot] = null;
}

function takePhoto(file) {
  if (!file) return;
  forget(state.slot);
  state.photos[state.slot] = { file, url: URL.createObjectURL(file) };
  if (state.slot === "front") state.slot = "back"; // front done: now the nutrition panel
  setStatus("");
  renderCapture();
}

function resetCapture() {
  forget("front");
  forget("back");
  state.slot = "front";
  $("#cam").value = "";
  $("#pick").value = "";
  setStatus("");
  renderCapture();
}

/** POST the photos; turn every failure into a sentence a person can act on. */
async function postCapture() {
  const form = new FormData();
  form.append("image", state.photos.back.file);
  if (state.photos.front) form.append("front", state.photos.front.file);
  let response;
  try {
    response = await fetch("/api/capture", { method: "POST", body: form });
  } catch {
    throw new Error(MESSAGES.unreachable);
  }
  const body = await response.json().catch(() => ({}));
  if (response.ok) return body;
  if (body.error === "ocr_failed" || response.status === 502) throw new Error(MESSAGES.modelDown);
  if (response.status === 400) throw new Error(MESSAGES.notAnImage);
  throw new Error(MESSAGES.other);
}

async function readLabel() {
  if (!state.photos.back || state.reading) return;
  state.reading = true;
  renderCapture();
  setStatus(MESSAGES.reading);
  try {
    const data = await postCapture();
    setStatus("");
    openResult(data);
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    state.reading = false;
    renderCapture();
  }
}

function chooseSlot(slot) {
  state.slot = slot;
  renderCapture();
  if (!state.photos[slot]) $("#cam").click();
}

function wireCapture() {
  for (const input of [$("#cam"), $("#pick")]) {
    input.addEventListener("change", () => {
      takePhoto(input.files[0]);
      input.value = ""; // so choosing the same file again (a retake) still fires a change
    });
  }
  $("#choose").addEventListener("click", () => $("#pick").click());
  $("#slot-front").addEventListener("click", () => chooseSlot("front"));
  $("#slot-back").addEventListener("click", () => chooseSlot("back"));
  $("#skip-front").addEventListener("click", () => {
    state.slot = "back";
    renderCapture();
  });
  $("#finder")?.addEventListener("click", () => {
    if (state.photos[state.slot]) $("#cam").click(); // tap the viewfinder to retake
  });
  $("#primary").addEventListener("click", () => (state.photos.back ? readLabel() : $("#cam").click()));
  $("#why-open").addEventListener("click", () => openLow("#sheet-why"));
}

// ---------- startup ----------

async function loadHealth() {
  try {
    state.health = await (await fetch("/api/health")).json();
  } catch {
    setStatus("Couldn't reach the app. Check your connection and reload.", true);
    state.health = { allergen_names: {}, endpoint: "" };
  }
}

function wireChrome() {
  wireSheets();
  for (const button of $$(".tabs button")) {
    button.addEventListener("click", () => {
      closeResult();
      setTab(button.dataset.tab);
    });
  }
  $("#r-again").addEventListener("click", () => {
    closeResult();
    resetCapture();
    setTab("capture");
  });
  $("#log-see").addEventListener("click", () => {
    closeResult();
    setTab("today");
  });
  $("#r-library").addEventListener("click", () => {
    closeResult();
    setTab("library");
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    if (isLowSheetOpen()) closeLow();
    else if (isResultOpen()) closeResult();
  });
}

async function start() {
  wireChrome();
  wireCapture();
  wireResult();
  wireToday();
  wireLibrary({ onGoToCapture: () => setTab("capture") });
  await loadHealth();
  renderCapture();
  fetch("/api/warmup", { method: "POST" }).catch(() => {}); // wake the model; ignore the outcome
}

start();
