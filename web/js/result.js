// The Result sheet: one label's numbers, the unverified text, allergen chips, the pipeline strip,
// the extracted text, and the raw request/response. It opens over whichever tab is showing.
import { $, $$, closeLow, cleanText, el, fmt, imageUrl, netCarbs, openLow, seconds, state, todayKey } from "./util.js";
import { fetchToday, renderTotals } from "./today.js";

// ---------- nutrient rows ----------

const VISIBLE_ROWS = 6; // the rest sit behind "More"

/** `core` rows are shown even when not read; the others only when the label had them. */
const NUTRIENT_ROWS = [
  { key: "energy_kcal", label: "Energy", unit: "kcal", core: true },
  { key: "fat_g", label: "Fat", unit: "g", core: true },
  { key: "saturated_fat_g", label: "of which saturates", unit: "g", core: true, child: true },
  { key: "carbohydrates_g", label: "Carbohydrate", unit: "g", core: true },
  { key: "sugars_g", label: "of which sugars", unit: "g", core: true, child: true },
  { key: "protein_g", label: "Protein", unit: "g", core: true },
  { key: "salt_g", label: "Salt", unit: "g", core: true },
  { key: "fiber_g", label: "Fibre", unit: "g" },
  { key: "added_sugars_g", label: "of which added sugars", unit: "g", child: true },
  { key: "sodium_mg", label: "Sodium", unit: "mg" },
  { key: "trans_fat_g", label: "Trans fat", unit: "g" },
  { key: "cholesterol_mg", label: "Cholesterol", unit: "mg" },
  { key: "potassium_mg", label: "Potassium", unit: "mg" },
  { key: "calcium_mg", label: "Calcium", unit: "mg" },
  { key: "iron_mg", label: "Iron", unit: "mg" },
  { key: "vitamin_d_mcg", label: "Vitamin D", unit: "mcg" },
  { key: "vitamin_a_mcg", label: "Vitamin A", unit: "mcg" },
];

const BASIS_TEXT = {
  "100g": "Per 100 g",
  "100ml": "Per 100 ml",
};

function basisText(nutrients) {
  if (nutrients.basis === "serving") {
    return `Per serving${nutrients.serving_text ? `, ${nutrients.serving_text}` : ""}`;
  }
  return BASIS_TEXT[nutrients.basis] || "Basis not stated on the label. Check the pack.";
}

function rowIsShown(row, nutrients) {
  if (nutrients[row.key] !== undefined) return true;
  // salt is not "missing" when the label gave sodium instead
  const saltGivenAsSodium = row.key === "salt_g" && nutrients.sodium_mg !== undefined;
  return row.core && !saltGivenAsSodium;
}

function nutrientRow(row, nutrients) {
  const value = nutrients[row.key];
  const missing = value === undefined;
  return el("div", { class: "r" + (row.child ? " child" : "") },
    el("span", { text: row.label }),
    el("span", { class: "v" + (missing ? " miss" : ""), text: missing ? "not read" : `${fmt(value)} ${row.unit}` }));
}

// ---------- render: one function per block of the sheet ----------

function hasNutritionPanel(nutrients) {
  return nutrients.carbohydrates_g !== undefined || nutrients.energy_kcal !== undefined;
}

function renderHeader(doc, imageSrc) {
  $("#r-thumb").src = imageSrc;
  const front = $("#r-thumb-front");
  front.hidden = !doc.front_image_path;
  if (doc.front_image_path) front.src = "/" + doc.front_image_path;
  $("#r-name").value = doc.product_name || "";
  const readMs = doc.telemetry?.ocr_ms;
  $("#r-read").textContent = readMs !== undefined ? `Read in ${seconds(readMs)}` : "";

  const select = $("#r-lang");
  const known = doc.language && select.querySelector(`option[value="${CSS.escape(doc.language)}"]`);
  if (doc.language && !known) select.append(el("option", { value: doc.language, text: doc.language })); // a tag outside our seven
  select.value = doc.language || "";
  $("#r-msg").hidden = true;
}

/** Extract -> Ingest -> Search, with what happened to this read at each step. */
function renderPipeline(doc, indexed) {
  const readMs = doc.telemetry?.ocr_ms;
  const ingest = !indexed || indexed.skipped ? "not saved" : indexed.ok ? "saved" : "failed";
  const steps = [
    ["Extract", readMs !== undefined ? seconds(readMs) : ""],
    ["Ingest", ingest],
    ["Search", "Library"],
  ];
  const nodes = steps.flatMap(([name, detail], i) => [
    ...(i ? [el("span", { class: "arrow", text: "→", "aria-hidden": "true" })] : []),
    el("span", { class: "step" }, el("b", { text: name }), ` ${detail}`.trimEnd()),
  ]);
  $("#r-pipe").replaceChildren(...nodes);
}

/** The two figures that matter, big enough to read on a recording: net carbs and calories. */
function bigFigure(label, value, unit, sub) {
  const missing = value === null || value === undefined;
  return el("div", { class: "big" },
    el("span", { class: "big-label", text: label }),
    el("span", { class: "big-value" },
      el("span", { class: "num" + (missing ? " none" : ""), text: missing ? "not read" : fmt(value) }),
      missing ? null : el("span", { class: "unit", text: ` ${unit}` })),
    el("span", { class: "big-sub", text: sub }));
}

function renderHero(nutrients) {
  const net = netCarbs(nutrients);
  const carbsSub = net.value === null ? "Carbohydrate not read from this photo."
    : net.fiberRead ? `${fmt(nutrients.carbohydrates_g)} carbs − ${fmt(nutrients.fiber_g)} fibre`
    : `${fmt(nutrients.carbohydrates_g)} carbs, fibre not read`;
  $("#r-hero").replaceChildren(
    bigFigure("Net carbs", net.value, "g", carbsSub),
    bigFigure("Calories", nutrients.energy_kcal, "kcal", "per portion shown"));
}

function renderPanel(nutrients) {
  const hasPanel = hasNutritionPanel(nutrients);
  // a photo with no panel in it gets an explanation instead of an empty table of "not read"
  $("#r-nopanel").hidden = hasPanel;
  for (const id of ["#r-hero", "#r-basis", "#r-panel"]) $(id).hidden = !hasPanel;

  renderHero(nutrients);

  $("#r-basis").textContent = basisText(nutrients);

  const rows = NUTRIENT_ROWS.filter((row) => rowIsShown(row, nutrients)).map((row) => nutrientRow(row, nutrients));
  if (nutrients.energy_kj !== undefined) {
    rows.push(el("div", { class: "r child" }, el("span", { text: "energy as printed" }), el("span", { class: "v", text: `${fmt(nutrients.energy_kj)} kJ` })));
  }
  rows.forEach((row, i) => {
    row.hidden = i >= VISIBLE_ROWS;
    row.dataset.extra = i >= VISIBLE_ROWS ? "1" : "";
  });
  $("#r-rows").replaceChildren(...rows);

  const more = $("#r-more");
  more.hidden = rows.length <= VISIBLE_ROWS;
  more.textContent = "More";
  more.dataset.open = "0";
}

function renderUnverifiedText(doc) {
  const text = $("#r-unv");
  text.textContent = doc.unverified_text ? cleanText(doc.unverified_text) : "No ingredients or allergens text in the frame.";
  text.classList.add("clamp");
  const showAll = $("#r-unv-more");
  showAll.textContent = "Show all";
  showAll.hidden = true;
  // only offer "Show all" when the clamp actually cut something off (needs layout first)
  requestAnimationFrame(() => { showAll.hidden = text.scrollHeight <= text.clientHeight + 1; });
}

function allergenChips(mentions, kind, displayNames) {
  const those = mentions.filter((mention) => mention.kind === kind);
  if (!those.length) return [el("span", { class: "none", text: "None named" })];
  return those.map((mention) => el("span", {
    class: "chip" + (kind === "contains" ? " c" : ""),
    text: displayNames[mention.name] || mention.name,
  }));
}

function renderAllergens(doc) {
  const names = state.health?.allergen_names || {};
  const mentions = doc.allergen_mentions || [];
  $("#r-contains").replaceChildren(...allergenChips(mentions, "contains", names));
  $("#r-may").replaceChildren(...allergenChips(mentions, "may_contain", names));
}

function renderFooter(doc, indexed) {
  const model = (doc.telemetry?.endpoint || state.health?.endpoint || "").replace(/^\./, "") || "jina-reader";
  $("#r-telemetry").textContent = [model, doc.telemetry?.task || "document_extraction"].join(", ");

  const stored = !indexed ? ""
    : indexed.skipped ? "Comparison read. Not saved."
    : indexed.ok ? "Saved to your library."
    : "Couldn't save this read to the library. Your edits stay on this screen only.";
  $("#r-stored").textContent = stored;
}

function renderResult() {
  const { doc, raw, indexed, image_url: imageSrc } = state.current;
  const nutrients = doc.nutrients || {};

  renderHeader(doc, imageUrl(doc, imageSrc));
  renderPipeline(doc, indexed);
  renderPanel(nutrients);
  renderEdited(doc);
  closeEditor();
  renderLog(nutrients);
  renderUnverifiedText(doc);
  renderAllergens(doc);
  renderFooter(doc, indexed);

  state.rawView = "markdown";
  $("#r-raw").open = false;
  renderExtractedText();
  $("#r-api").hidden = !raw?.request; // saved labels don't keep the HTTP exchange
}

// ---------- extracted text (Markdown / JSON) and the raw API call ----------

const NOT_SHOWN_IN_JSON = ["raw_markdown", "plain_text"]; // already shown as Markdown / too long

function renderExtractedText() {
  const { doc, raw } = state.current;
  const fields = Object.fromEntries(Object.entries(doc).filter(([key]) => !NOT_SHOWN_IN_JSON.includes(key)));
  const views = {
    markdown: raw?.markdown ?? doc.raw_markdown ?? "",
    json: JSON.stringify(fields, null, 2),
  };
  $("#r-raw-body").textContent = views[state.rawView];
  for (const tab of $$(".tabs2 button")) tab.setAttribute("aria-selected", String(tab.dataset.raw === state.rawView));
}

function openRawExchange() {
  const raw = state.current?.raw;
  if (!raw?.request) return;
  const pretty = (value) => JSON.stringify(value, null, 2);
  $("#raw-line").textContent = `${raw.request.method} ${raw.request.path}`;
  $("#raw-req").textContent = pretty(raw.request.body);
  $("#raw-res").textContent = raw.response ? pretty(raw.response) : "";
  openLow("#sheet-raw");
}

// ---------- open / close, with the browser's back button closing the sheet ----------

let historyEntryPushed = false;

export const isResultOpen = () => !$("#sheet-result").hidden;

export function openResult(data) {
  state.current = data;
  renderResult();
  $("#sheet-result").hidden = false;
  $("#r-scroll").scrollTop = 0;
  $("#r-back").focus();
  if (!historyEntryPushed) {
    history.pushState({ sheet: "result" }, "");
    historyEntryPushed = true;
  }
}

export function closeResult() {
  if (!isResultOpen()) return;
  $("#sheet-result").hidden = true;
  closeLow();
  if (historyEntryPushed && history.state?.sheet === "result") history.back();
  historyEntryPushed = false;
}

// ---------- editing name and language ----------

/** Save a correction. Unsaved reads are edited in memory; saved ones go through PATCH. */
async function saveEdit(fields) {
  const current = state.current;
  if (!current) return;
  const isStored = current.indexed?.ok || current.fromLibrary;
  if (!isStored) {
    const { nutrients, ...rest } = fields;
    Object.assign(current.doc, rest);
    if (nutrients) {
      current.doc.nutrients = { ...current.doc.nutrients, ...nutrients };
      current.doc.edited_fields = [...new Set([...(current.doc.edited_fields || []), ...Object.keys(nutrients)])];
    }
    return true;
  }
  const message = $("#r-msg");
  try {
    const response = await fetch(`/api/doc/${current.doc.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(fields),
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't save that. Try again.");
    Object.assign(current.doc, body);
    message.hidden = true;
    return true;
  } catch (error) {
    message.textContent = error instanceof TypeError ? "Couldn't reach the app. Try again." : error.message;
    message.hidden = false;
    return false;
  }
}

// ---------- correcting the numbers by hand ----------

const EDIT_INPUTS = { carbohydrates_g: "#e-carbs", fiber_g: "#e-fiber", energy_kcal: "#e-kcal" };
const EDIT_LABELS = { carbohydrates_g: "carbohydrate", fiber_g: "fibre", energy_kcal: "calories" };

function renderEdited(doc) {
  const edited = doc.edited_fields || [];
  $("#r-edited").hidden = edited.length === 0;
  $("#r-edited").textContent = `Edited by hand: ${edited.map((key) => EDIT_LABELS[key] || key).join(", ")}`;
}

function openEditor() {
  const nutrients = state.current.doc.nutrients || {};
  for (const [key, selector] of Object.entries(EDIT_INPUTS)) $(selector).value = nutrients[key] ?? "";
  $("#r-editor").hidden = false;
  $("#r-edit").hidden = true;
  $("#e-carbs").focus();
}

function closeEditor() {
  $("#r-editor").hidden = true;
  $("#r-edit").hidden = false;
}

/** Send only the numbers the person actually changed (or filled in). */
async function saveNumbers(event) {
  event.preventDefault();
  const nutrients = state.current.doc.nutrients || {};
  const changes = {};
  for (const [key, selector] of Object.entries(EDIT_INPUTS)) {
    const text = $(selector).value.trim();
    if (text !== "" && Number(text) !== nutrients[key]) changes[key] = Number(text);
  }
  if (Object.keys(changes).length && (await saveEdit({ nutrients: changes }))) renderResult();
  else closeEditor();
}

// ---------- add to today ----------

const MIN_PORTIONS = 0.5;
const MAX_PORTIONS = 20;
const PORTION_STEP = 0.5;
let portions = 1;

function renderLog(nutrients) {
  const canLog = netCarbs(nutrients).value !== null || nutrients.energy_kcal !== undefined;
  $("#r-log").hidden = !canLog;
  portions = 1;
  showPortions(nutrients);
  $("#log-done").hidden = true;
  $("#log-add").disabled = false;
  $("#log-add").textContent = "Add to today";
}

function showPortions(nutrients = state.current.doc.nutrients || {}) {
  $("#log-portions").textContent = fmt(portions);
  const unit = portions === 1 ? "portion" : "portions";
  $("#log-basis").textContent = `${unit} · ${basisText(nutrients)}`;
}

function stepPortions(delta) {
  portions = Math.min(MAX_PORTIONS, Math.max(MIN_PORTIONS, portions + delta));
  showPortions();
}

async function addToToday() {
  const doc = state.current.doc;
  const message = $("#log-msg");
  const button = $("#log-add");
  button.disabled = true;
  button.textContent = "Adding…";
  try {
    const response = await fetch("/api/log", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label_id: doc.id, portions, day: todayKey() }),
    });
    if (!response.ok) throw new Error();
    renderTotals(await fetchToday(), $("#log-totals"));
    message.textContent = `Added ${fmt(portions)} ${portions === 1 ? "portion" : "portions"} to today.`;
    $("#log-done").hidden = false;
  } catch {
    message.textContent = "Couldn't add that. Try again.";
    $("#log-done").hidden = false;
    button.disabled = false;
    button.textContent = "Add to today";
    return;
  }
  button.textContent = "Added"; // stays disabled so one tap cannot add the same thing twice
}

// ---------- wiring ----------

export function wireResult() {
  $("#r-back").addEventListener("click", closeResult);
  window.addEventListener("popstate", () => {
    if (!isResultOpen()) return;
    historyEntryPushed = false; // the browser already went back
    $("#sheet-result").hidden = true;
    closeLow();
  });

  $("#r-name").addEventListener("change", (e) => saveEdit({ product_name: e.target.value }));
  $("#r-name").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
  $("#r-lang").addEventListener("change", (e) => saveEdit({ language: e.target.value }));

  $$(".tabs2 button").forEach((tab) => tab.addEventListener("click", () => {
    state.rawView = tab.dataset.raw;
    renderExtractedText();
  }));
  $("#r-api").addEventListener("click", openRawExchange);

  $("#r-edit").addEventListener("click", openEditor);
  $("#e-cancel").addEventListener("click", closeEditor);
  $("#r-editor").addEventListener("submit", saveNumbers);

  $("#log-minus").addEventListener("click", () => stepPortions(-PORTION_STEP));
  $("#log-plus").addEventListener("click", () => stepPortions(PORTION_STEP));
  $("#log-add").addEventListener("click", addToToday);

  $("#r-more").addEventListener("click", (e) => {
    const button = e.currentTarget;
    const opening = button.dataset.open !== "1";
    button.dataset.open = opening ? "1" : "0";
    button.textContent = opening ? "Fewer" : "More";
    for (const row of $$("#r-rows .r")) if (row.dataset.extra) row.hidden = !opening;
  });
  $("#r-unv-more").addEventListener("click", (e) => {
    const clamped = $("#r-unv").classList.toggle("clamp");
    e.currentTarget.textContent = clamped ? "Show all" : "Show fewer";
  });
}
