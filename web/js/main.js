// Food Insights, phone-first. Two tabs (Capture, Library) and a Result sheet that opens over
// whichever is showing. No build step, no framework: plain ES modules.
//
//   util.js     helpers, the shared state object, bottom sheets
//   result.js   the Result sheet          library.js   the Library screen
//   main.js     this file: tabs, the Capture screen, and the wiring
//
import { $, $$, state, closeLow, isLowSheetOpen, openLow, wireSheets } from "./util.js";
import { closeResult, isResultOpen, openResult, wireResult } from "./result.js";
import { loadLibrary, wireLibrary } from "./library.js";

// ---------- tabs ----------

function setTab(name) {
  state.tab = name;
  $("#screen-capture").hidden = name !== "capture";
  $("#screen-library").hidden = name !== "library";
  for (const button of $$(".tabs button")) {
    if (button.dataset.tab === name) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
  if (name === "library") loadLibrary();
}

// ---------- Capture screen: pick or take a photo, send it to /api/capture, open the Result ----------

const MESSAGES = {
  unreachable: "Couldn't reach the app. Check your connection and try again.",
  modelDown: "Couldn't reach the model. Try again in a minute; the first read after idle can take two to three minutes.",
  notAnImage: "That file isn't an image we can read. Choose a JPEG or PNG photo.",
  other: "Something went wrong on our side. Try again in a minute.",
  reading: "Reading the label. The first read after idle can take two to three minutes.",
};

function setStatus(message, isError = false) {
  const status = $("#status");
  status.className = "status" + (isError ? " err" : "");
  status.textContent = message;
}

function renderCapture() {
  const hasPhoto = !!state.file;
  $("#preview").hidden = !hasPhoto;
  $("#finder-hint").hidden = hasPhoto;
  const button = $("#primary");
  button.textContent = state.reading ? "Reading…" : hasPhoto ? "Read label" : "Take photo";
  button.disabled = state.reading;
}

function showPhoto(file) {
  if (!file) return;
  state.file = file;
  const preview = $("#preview");
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.src = URL.createObjectURL(file);
  setStatus("");
  renderCapture();
}

function resetCapture() {
  state.file = null;
  const preview = $("#preview");
  if (preview.src) URL.revokeObjectURL(preview.src);
  preview.removeAttribute("src");
  $("#cam").value = "";
  $("#pick").value = "";
  setStatus("");
  renderCapture();
}

/** POST the photo; turn every failure into a sentence a person can act on. */
async function postCapture() {
  const form = new FormData();
  form.append("image", state.file);
  let response;
  try {
    response = await fetch("/api/capture", { method: "POST", body: form });
  } catch {
    throw new Error(MESSAGES.unreachable);
  }
  const body = await response.json().catch(() => ({}));
  if (response.ok) return body;
  if (body.error === "ocr_failed") throw new Error(MESSAGES.modelDown);
  if (response.status === 400) throw new Error(MESSAGES.notAnImage);
  throw new Error(MESSAGES.other);
}

async function readLabel() {
  if (!state.file || state.reading) return;
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

function wireCapture() {
  $("#cam").addEventListener("change", (e) => showPhoto(e.target.files[0]));
  $("#pick").addEventListener("change", (e) => showPhoto(e.target.files[0]));
  $("#choose").addEventListener("click", () => $("#pick").click());
  $("#finder")?.addEventListener("click", () => {
    if (state.file) $("#cam").click(); // tap the viewfinder to retake
  });
  $("#primary").addEventListener("click", () => (state.file ? readLabel() : $("#cam").click()));
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
  wireLibrary({ onGoToCapture: () => setTab("capture") });
  await loadHealth();
  renderCapture();
  fetch("/api/warmup", { method: "POST" }).catch(() => {}); // wake the model; ignore the outcome
}

start();
