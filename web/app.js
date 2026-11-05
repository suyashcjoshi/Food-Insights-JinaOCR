"use strict";
// Food Insights, phone-first. Two tabs (Capture, Library) and a Result sheet that opens over
// whichever is showing. No build step, no framework. Model text is only ever inserted with
// textContent; the one place HTML is set is Elasticsearch highlights, escaped first.

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];
const el = (tag, attrs = {}, ...kids) => {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k === "text") n.textContent = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k !== null && k !== undefined) n.append(k);
  return n;
};
const fmt = (n) => (n === null || n === undefined ? "–" : String(Math.round(n * 1000) / 1000));
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode: the setting just won't stick */ } },
};
const LANGS = { en: "English", fr: "French", es: "Spanish", pt: "Portuguese", de: "German", it: "Italian", ja: "Japanese" };
const langName = (c) => LANGS[c] || c;
// short names for the library list; the result card uses the full names from the API
const SHORT = { gluten: "Gluten", crustaceans: "Crustaceans", eggs: "Eggs", fish: "Fish", peanuts: "Peanuts", soybeans: "Soy", milk: "Milk", tree_nuts: "Tree nuts", celery: "Celery", mustard: "Mustard", sesame: "Sesame", sulphites: "Sulphites", lupin: "Lupin", molluscs: "Molluscs" };
// the table prompt answers in markdown: show it as plain text, same words, same case
const cleanText = (s) => s.replace(/<br\s*\/?>/gi, "\n").replace(/<[^>]+>/g, " ").replace(/(\*\*|__|`)/g, "").replace(/^\s{0,3}#{1,6}\s+/gm, "").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();

const state = {
  file: null, barcode: "", reading: false, health: null,
  dev: false, prompt: "",
  tab: "capture", current: null, raw: "output", barcodeMode: "capture",
  lib: { chip: "all", allergens: new Set(), kind: "", languages: [] },
};
const imageUrl = (doc, given) => given || (doc.image_path?.startsWith("captures/") ? "/" + doc.image_path : doc.image_path?.startsWith("http") ? doc.image_path : "");

// ---------- startup ----------
async function init() {
  state.dev = store.get("fi.dev") === "1";
  try {
    state.health = await (await fetch("/api/health")).json();
  } catch {
    setStatus("Couldn't reach the app. Check your connection and reload.", true);
    state.health = { prompts: ["table"], prompt_texts: {}, default_prompt: "table", allergen_names: {}, endpoint: "" };
  }
  const saved = store.get("fi.prompt");
  state.prompt = state.health.prompts.includes(saved) ? saved : state.health.default_prompt;
  const sel = $("#prompt");
  for (const p of state.health.prompts) sel.append(el("option", { value: p, text: p }));
  sel.value = state.prompt;
  applyDev();
  renderCapture();
  fetch("/api/warmup", { method: "POST" }).catch(() => {}); // wake the model, ignore the outcome
}

// ---------- tabs ----------
function setTab(name) {
  state.tab = name;
  $("#screen-capture").hidden = name !== "capture";
  $("#screen-library").hidden = name !== "library";
  for (const b of $$(".tabs button")) {
    if (b.dataset.tab === name) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  if (name === "library") loadLibrary();
}
$$(".tabs button").forEach((b) => b.addEventListener("click", () => { closeResult(); setTab(b.dataset.tab); }));

// ---------- small sheets ----------
let lowOpen = null;
function openLow(id) {
  closeLow();
  lowOpen = $(id);
  $("#backdrop").hidden = false;
  lowOpen.hidden = false;
  lowOpen.querySelector("input:not([hidden]), button, select")?.focus();
}
function closeLow() {
  if (!lowOpen) return;
  lowOpen.hidden = true;
  $("#backdrop").hidden = true;
  lowOpen = null;
}
$("#backdrop").addEventListener("click", closeLow);
$$(".sheet.low .close").forEach((b) => b.addEventListener("click", closeLow));
document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  if (lowOpen) closeLow();
  else if (!$("#sheet-result").hidden) closeResult();
});

// ---------- developer ----------
function applyDev() {
  document.body.dataset.dev = state.dev ? "1" : "0";
  $("#dev-toggle").checked = state.dev;
  $("#dev-prompt-wrap").hidden = !state.dev;
  $("#r-dev").hidden = !state.dev || !state.current;
  const t = state.health?.prompt_texts?.[state.prompt];
  $("#prompt-text").textContent = t ? `Sent to the model: “${t}”` : "";
}
$("#dev-open").addEventListener("click", () => openLow("#sheet-dev"));
$("#dev-toggle").addEventListener("change", (e) => {
  state.dev = e.target.checked;
  store.set("fi.dev", state.dev ? "1" : "0");
  applyDev();
  if (state.current) renderRaw();
});
$("#prompt").addEventListener("change", (e) => {
  state.prompt = e.target.value;
  store.set("fi.prompt", state.prompt);
  applyDev();
});
const promptToUse = () => (state.dev ? state.prompt : state.health.default_prompt);

// ---------- capture ----------
function setStatus(msg, err = false) {
  const s = $("#status");
  s.className = "status" + (err ? " err" : "");
  s.textContent = msg;
}
function renderCapture() {
  const has = !!state.file;
  $("#preview").hidden = !has;
  $("#finder-hint").hidden = has;
  const primary = $("#primary");
  primary.textContent = state.reading ? "Reading…" : has ? "Read label" : "Take photo";
  primary.disabled = state.reading;
  $("#scan").textContent = state.barcode ? `Barcode ${state.barcode}` : "Scan barcode (optional)";
}
function setFile(f) {
  if (!f) return;
  state.file = f;
  const img = $("#preview");
  if (img.src) URL.revokeObjectURL(img.src);
  img.src = URL.createObjectURL(f);
  setStatus("");
  renderCapture();
}
$("#cam").addEventListener("change", (e) => setFile(e.target.files[0]));
$("#pick").addEventListener("change", (e) => setFile(e.target.files[0]));
$("#choose").addEventListener("click", () => $("#pick").click());
$("#finder")?.addEventListener("click", () => { if (state.file) $("#cam").click(); });
$("#primary").addEventListener("click", () => (state.file ? readLabel() : $("#cam").click()));
$("#why-open").addEventListener("click", () => openLow("#sheet-why"));
$("#dev-open").setAttribute("aria-haspopup", "dialog");

async function postCapture(prompt, index) {
  const fd = new FormData();
  fd.append("image", state.file);
  fd.append("prompt", prompt);
  fd.append("index", index ? "true" : "false");
  if (state.barcode) fd.append("barcode", state.barcode);
  let r;
  try {
    r = await fetch("/api/capture", { method: "POST", body: fd });
  } catch {
    throw new Error("Couldn't reach the app. Check your connection and try again.");
  }
  const body = await r.json().catch(() => ({}));
  if (r.ok) return body;
  if (body.error === "ocr_failed") throw new Error("Couldn't reach the model. Try again in a minute; the first read after idle can take two to three minutes.");
  if (r.status === 400) throw new Error("That file isn't an image we can read. Choose a JPEG or PNG photo.");
  throw new Error("Something went wrong on our side. Try again in a minute.");
}

async function readLabel() {
  if (!state.file || state.reading) return;
  state.reading = true;
  renderCapture();
  setStatus("Reading the label. The first read after idle can take two to three minutes.");
  try {
    const data = await postCapture(promptToUse(), true);
    setStatus("");
    openResult(data);
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    state.reading = false;
    renderCapture();
  }
}
function resetCapture() {
  state.file = null;
  state.barcode = "";
  const img = $("#preview");
  if (img.src) URL.revokeObjectURL(img.src);
  img.removeAttribute("src");
  $("#cam").value = "";
  $("#pick").value = "";
  setStatus("");
  renderCapture();
}

// ---------- barcode sheet ----------
const validBarcode = (c) => {
  if (!/^(\d{8}|\d{12,14})$/.test(c)) return false;
  const d = [...c].map(Number), check = d.pop();
  const sum = d.reverse().reduce((a, v, i) => a + v * (i % 2 === 0 ? 3 : 1), 0);
  return (10 - (sum % 10)) % 10 === check;
};
function openBarcode(mode) {
  state.barcodeMode = mode;
  $("#bc-input").value = mode === "result" ? state.current?.doc.barcode || "" : state.barcode;
  $("#bc-error").hidden = true;
  $("#bc-scan").hidden = !("BarcodeDetector" in window);
  $("#bc-clear").hidden = !$("#bc-input").value;
  openLow("#sheet-barcode");
}
$("#scan").addEventListener("click", () => openBarcode("capture"));
$("#bc-clear").addEventListener("click", () => { $("#bc-input").value = ""; $("#bc-save").click(); });
$("#bc-save").addEventListener("click", async () => {
  const code = $("#bc-input").value.replace(/\D/g, "");
  const err = $("#bc-error");
  if (code && !validBarcode(code)) {
    err.textContent = "That barcode doesn't pass its check digit. Check the digits.";
    err.hidden = false;
    return;
  }
  if (state.barcodeMode === "capture") {
    state.barcode = code;
    renderCapture();
    closeLow();
    return;
  }
  const res = await saveEdit({ barcode: code });
  if (res.ok) closeLow();
  else { err.textContent = res.error; err.hidden = false; }
});
$("#bc-input").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#bc-save").click(); });
$("#bc-scan").addEventListener("click", () => $("#bc-photo").click());
$("#bc-photo").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f || !("BarcodeDetector" in window)) return;
  try {
    const found = await new BarcodeDetector().detect(await createImageBitmap(f));
    if (found[0]?.rawValue) $("#bc-input").value = found[0].rawValue;
    else { $("#bc-error").textContent = "No barcode found in that photo. Type the digits instead."; $("#bc-error").hidden = false; }
  } catch {
    $("#bc-error").textContent = "Couldn't scan that photo. Type the digits instead.";
    $("#bc-error").hidden = false;
  }
});

// ---------- result sheet ----------
const ROWS = [
  ["energy_kcal", "Energy", "kcal", false, true],
  ["fat_g", "Fat", "g", false, true],
  ["saturated_fat_g", "of which saturates", "g", true, true],
  ["carbohydrates_g", "Carbohydrate", "g", false, true],
  ["sugars_g", "of which sugars", "g", true, true],
  ["protein_g", "Protein", "g", false, true],
  ["salt_g", "Salt", "g", false, true],
  ["fiber_g", "Fibre", "g", false, false],
  ["added_sugars_g", "of which added sugars", "g", true, false],
  ["sodium_mg", "Sodium", "mg", false, false],
  ["trans_fat_g", "Trans fat", "g", false, false],
  ["cholesterol_mg", "Cholesterol", "mg", false, false],
  ["potassium_mg", "Potassium", "mg", false, false],
  ["calcium_mg", "Calcium", "mg", false, false],
  ["iron_mg", "Iron", "mg", false, false],
  ["vitamin_d_mcg", "Vitamin D", "mcg", false, false],
  ["vitamin_a_mcg", "Vitamin A", "mcg", false, false],
];
const FLAG_TEXT = {
  edge_cutoff_suspected: "Text looks cut off at the edge of the frame.",
  saturates_gt_fat: "Saturates are higher than fat.",
  sugars_gt_carbs: "Sugars are higher than carbohydrate.",
  energy_converted: "Energy was converted from kJ (divided by 4.184).",
  aligned: "Values were matched to their labels by row order.",
  column_swapped: "The column headers looked swapped, so the other column was read.",
  looped: "The model's output looped. Don't trust this read.",
};
let historyPushed = false;

function openResult(data) {
  state.current = data;
  renderResult();
  $("#sheet-result").hidden = false;
  $("#r-scroll").scrollTop = 0;
  $("#r-back").focus();
  if (!historyPushed) {
    history.pushState({ sheet: "result" }, "");
    historyPushed = true;
  }
}
function closeResult() {
  if ($("#sheet-result").hidden) return;
  $("#sheet-result").hidden = true;
  closeLow();
  if (historyPushed && history.state?.sheet === "result") {
    historyPushed = false;
    history.back();
  }
  historyPushed = false;
}
window.addEventListener("popstate", () => {
  if (!$("#sheet-result").hidden) { historyPushed = false; $("#sheet-result").hidden = true; closeLow(); }
});
$("#r-back").addEventListener("click", closeResult);
$("#r-again").addEventListener("click", () => { closeResult(); resetCapture(); setTab("capture"); });
$("#r-library").addEventListener("click", () => { closeResult(); setTab("library"); });

function renderResult() {
  const { doc, raw } = state.current;
  const n = doc.nutrients || {};
  $("#r-thumb").src = imageUrl(doc, state.current.image_url);
  $("#r-name").value = doc.product_name || "";
  const t = doc.telemetry || {};
  $("#r-read").textContent = t.ocr_ms !== undefined ? `Read in ${(t.ocr_ms / 1000).toFixed(1)} s` : "";
  const langSel = $("#r-lang");
  if (doc.language && !langSel.querySelector(`option[value="${CSS.escape(doc.language)}"]`)) {
    langSel.append(el("option", { value: doc.language, text: doc.language })); // a tag outside our seven
  }
  langSel.value = doc.language || "";
  $("#r-msg").hidden = true;
  renderXchip();

  // hero + basis
  const hero = $("#r-hero");
  hero.replaceChildren(
    ...(n.carbohydrates_g === undefined
      ? [el("span", { class: "none", text: "Carbohydrate not read from this photo." })]
      : [el("span", { class: "num", text: fmt(n.carbohydrates_g) }), el("span", { class: "unit", text: "g carbohydrate" })]),
  );
  $("#r-basis").textContent = {
    "100g": "Per 100 g",
    "100ml": "Per 100 ml",
    serving: `Per serving${n.serving_text ? `, ${n.serving_text}` : ""}`,
  }[n.basis] || "Basis not stated on the label. Check the pack.";

  // nutrient rows, six visible, the rest behind "More"
  const rows = ROWS.filter(([k, , , , core]) => (core && !(k === "salt_g" && n.sodium_mg !== undefined && n.salt_g === undefined)) || n[k] !== undefined)
    .map(([k, label, unit, child]) =>
      el("div", { class: "r" + (child ? " child" : "") },
        el("span", { text: label }),
        el("span", { class: "v" + (n[k] === undefined ? " miss" : ""), text: n[k] === undefined ? "not read" : `${fmt(n[k])} ${unit}` })));
  if (n.energy_kj !== undefined) rows.push(el("div", { class: "r child" }, el("span", { text: "energy as printed" }), el("span", { class: "v", text: `${fmt(n.energy_kj)} kJ` })));
  rows.forEach((r, i) => { r.hidden = i >= 6; r.dataset.extra = i >= 6 ? "1" : ""; });
  $("#r-rows").replaceChildren(...rows);
  const more = $("#r-more");
  more.hidden = rows.length <= 6;
  more.textContent = "More";
  more.dataset.open = "0";

  const verified = !!doc.nutrients_verified;
  const v = $("#r-verified");
  v.textContent = verified ? "Verified" : "Not verified";
  v.className = "verified" + (verified ? "" : " no");
  v.title = verified ? "Read from the panel, nothing cut off, and the numbers add up. It does not mean they are right." : "A panel was not read, text looks cut off, or the numbers contradict each other.";

  // does it add up?
  const adds = $("#r-adds");
  if (n.carbohydrates_g !== undefined && n.protein_g !== undefined && n.fat_g !== undefined) {
    const est = Math.round(4 * n.carbohydrates_g + 4 * n.protein_g + 9 * n.fat_g);
    const off = (doc.parse_flags || []).includes("kcal_mismatch");
    adds.className = "adds" + (off ? " warn" : "");
    adds.textContent = off
      ? `Doesn't add up: 4×carbs + 4×protein + 9×fat ≈ ${est} kcal${n.energy_kcal !== undefined ? `, the label says ${fmt(n.energy_kcal)} kcal` : ""}.`
      : `Adds up: 4×carbs + 4×protein + 9×fat ≈ ${est} kcal`;
    adds.hidden = false;
  } else adds.hidden = true;
  $("#r-flags").replaceChildren(...(doc.parse_flags || []).filter((f) => FLAG_TEXT[f]).map((f) => el("li", { text: FLAG_TEXT[f] })));

  // unverified text and allergens
  const unv = $("#r-unv");
  unv.textContent = doc.unverified_text ? cleanText(doc.unverified_text) : "No ingredients or allergens text in the frame.";
  unv.classList.add("clamp");
  const unvMore = $("#r-unv-more");
  unvMore.textContent = "Show all";
  unvMore.hidden = true;
  requestAnimationFrame(() => { unvMore.hidden = unv.scrollHeight <= unv.clientHeight + 1; });
  const names = state.health?.allergen_names || {};
  const chips = (kind) => {
    const those = (doc.allergen_mentions || []).filter((a) => a.kind === kind);
    return those.length ? those.map((a) => el("span", { class: "chip" + (kind === "contains" ? " c" : ""), text: names[a.name] || a.name })) : [el("span", { class: "none", text: "None named" })];
  };
  $("#r-contains").replaceChildren(...chips("contains"));
  $("#r-may").replaceChildren(...chips("may_contain"));

  // telemetry, stored, raw, developer
  const model = (state.health?.endpoint || "").replace(/^\./, "").replace("-chat_completion", "") || "jina-ocr-v1";
  $("#r-telemetry").textContent = [
    model,
    `${t.prompt_variant || "official"} prompt`,
    t.prompt_tokens !== undefined ? `${t.prompt_tokens} in / ${t.completion_tokens} out tokens` : null,
    t.cost_est !== undefined ? `$${t.cost_est.toFixed(4)}` : null,
  ].filter(Boolean).join(", ");
  const ix = state.current.indexed;
  $("#r-stored").textContent = !ix ? "" : ix.skipped ? "Comparison read. Not saved." : ix.ok ? "Saved to your library." : "Couldn't save this read to the library. Your edits stay on this screen only.";
  state.raw = state.dev && raw?.request ? "request" : "output";
  $("#r-raw").open = false;
  renderRaw();
  const other = (state.health?.prompts || []).find((p) => p !== (raw?.prompt_variant || t.prompt_variant));
  const reread = $("#r-reread");
  reread.hidden = !state.file || !other;
  reread.textContent = other ? `Re-read with the ${other} prompt` : "";
  reread.dataset.prompt = other || "";
  $("#r-dev-prompt").textContent = `Prompt used: ${t.prompt_variant || raw?.prompt_variant || "unknown"}.`;
  applyDev();
}

function renderXchip() {
  const doc = state.current.doc;
  const m = doc.off_match || { status: "not_found" };
  const chip = $("#r-xchip");
  const act = (label) => el("button", { type: "button", text: label, onclick: () => openBarcode("result") });
  let cls = "xchip", text, action;
  if (!doc.barcode) { text = "No barcode"; action = act("Add barcode"); }
  else if (m.status === "match") { cls += " ok"; text = `Open Food Facts agrees: carbs ${fmt(m.carbohydrates_100g)} g`; action = act("Edit barcode"); }
  else if (m.status === "mismatch") { cls += " warn"; text = `Open Food Facts says carbs ${fmt(m.carbohydrates_100g)} g, the label says ${fmt(doc.nutrients?.carbohydrates_g)} g`; action = act("Edit barcode"); }
  else if (m.status === "not_comparable") { text = `Open Food Facts lists carbs ${fmt(m.carbohydrates_100g)} g per 100 g. This panel isn't per 100 g.`; action = act("Edit barcode"); }
  else if (m.status === "error") { text = "Couldn't reach Open Food Facts."; action = el("button", { type: "button", text: "Try again", onclick: () => saveEdit({ barcode: doc.barcode }) }); }
  else { text = "Barcode not found on Open Food Facts"; action = act("Edit barcode"); }
  chip.className = cls;
  chip.replaceChildren(el("span", { text }), action);
}

function renderRaw() {
  const { doc, raw } = state.current;
  const body = {
    output: raw?.markdown ?? doc.raw_markdown ?? "",
    request: raw?.request ? JSON.stringify(raw.request, null, 2) : "The request isn't kept for saved labels.",
  }[state.raw];
  $("#r-raw-body").textContent = body;
  for (const b of $$(".tabs2 button")) b.setAttribute("aria-selected", String(b.dataset.raw === state.raw));
}
$$(".tabs2 button").forEach((b) => b.addEventListener("click", () => { state.raw = b.dataset.raw; renderRaw(); }));
$("#r-more").addEventListener("click", (e) => {
  const open = e.currentTarget.dataset.open !== "1";
  e.currentTarget.dataset.open = open ? "1" : "0";
  e.currentTarget.textContent = open ? "Fewer" : "More";
  for (const r of $$("#r-rows .r")) if (r.dataset.extra) r.hidden = !open;
});
$("#r-unv-more").addEventListener("click", (e) => {
  const clamped = $("#r-unv").classList.toggle("clamp");
  e.currentTarget.textContent = clamped ? "Show all" : "Show fewer";
});

async function saveEdit(fields) {
  const cur = state.current;
  if (!cur) return { ok: false, error: "Nothing to edit." };
  const stored = cur.indexed?.ok || cur.fromLibrary;
  if (!stored) {
    Object.assign(cur.doc, fields.barcode !== undefined ? { barcode: fields.barcode || undefined } : fields);
    renderXchip();
    return { ok: true };
  }
  try {
    const r = await fetch(`/api/doc/${cur.doc.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(fields) });
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Couldn't save that. Try again.");
    Object.assign(cur.doc, body);
    renderXchip();
    $("#r-msg").hidden = true;
    return { ok: true };
  } catch (err) {
    const m = $("#r-msg");
    m.textContent = err instanceof TypeError ? "Couldn't reach the app. Try again." : err.message;
    m.hidden = false;
    return { ok: false, error: m.textContent };
  }
}
$("#r-name").addEventListener("change", (e) => saveEdit({ product_name: e.target.value }));
$("#r-name").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
$("#r-lang").addEventListener("change", (e) => saveEdit({ language: e.target.value }));
$("#r-reread").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Reading…";
  try {
    const data = await postCapture(btn.dataset.prompt, false);
    state.current = data;
    renderResult();
    $("#r-raw").open = true;
  } catch (err) {
    $("#r-msg").textContent = err.message;
    $("#r-msg").hidden = false;
    btn.textContent = `Re-read with the ${btn.dataset.prompt} prompt`;
  } finally {
    btn.disabled = false;
  }
});

// ---------- library ----------
let libSeq = 0; // a slow earlier request must not overwrite a newer one
const filtersActive = () => state.lib.chip !== "all" || state.lib.allergens.size > 0 || !!$("#q").value.trim();
const libParams = () => {
  const p = new URLSearchParams({ size: "60" });
  if ($("#q").value.trim()) p.set("q", $("#q").value.trim());
  for (const a of state.lib.allergens) p.append("allergen", a);
  if (state.lib.kind) p.set("allergen_kind", state.lib.kind);
  if (state.lib.chip === "unverified") p.set("verified", "false");
  else if (state.lib.chip !== "all") p.set("language", state.lib.chip);
  return p.toString();
};

async function loadLibrary() {
  const mine = ++libSeq;
  const qs = libParams();
  try {
    const [s, a] = await Promise.all([fetch(`/api/search?${qs}`), fetch(`/api/aggs?${qs}`)]);
    if (!s.ok || !a.ok) throw new Error("search failed");
    const [search, aggs] = [await s.json(), await a.json()];
    if (mine === libSeq) renderLibrary(search, aggs);
  } catch {
    if (mine !== libSeq) return;
    $("#grid").replaceChildren();
    $("#allergens").hidden = true;
    showEmpty("Couldn't load the library. Check your connection and try again.", "Try again", loadLibrary);
  }
}
function showEmpty(text, label, handler) {
  $("#empty").hidden = false;
  $("#empty-text").textContent = text;
  const b = $("#empty-go");
  b.hidden = !label;
  b.textContent = label || "";
  b.onclick = handler;
}

function renderChips() {
  const chips = [["all", "All"], ...state.lib.languages.map((c) => [c, langName(c)]), ["unverified", "Unverified"]];
  $("#chips").replaceChildren(...chips.map(([key, label]) =>
    el("button", { type: "button", class: "chip", role: "radio", "aria-checked": String(state.lib.chip === key), text: label, onclick: () => { state.lib.chip = key; loadLibrary(); } })));
}

function renderLibrary(search, aggs) {
  // the language chips come from the unfiltered library, so picking one does not shrink the row
  if (!state.lib.languages.length || !filtersActive()) state.lib.languages = aggs.languages.map((b) => b.key);
  renderChips();
  $("#lib-note").textContent = `${search.total} label${search.total === 1 ? "" : "s"}` + (search.hits.length < search.total ? `, showing the first ${search.hits.length}` : "");
  $("#grid").replaceChildren(...search.hits.map(tile));
  if (search.total === 0) {
    if (filtersActive()) showEmpty("Nothing matches. Try other words, or clear the filters.", "Clear filters", () => { state.lib.chip = "all"; state.lib.allergens.clear(); state.lib.kind = ""; $("#q").value = ""; loadLibrary(); });
    else showEmpty("No labels yet. Photograph one to start.", "Photograph a label", () => setTab("capture"));
  } else $("#empty").hidden = true;
  renderAllergens(aggs);
}

function tile(doc) {
  const img = imageUrl(doc);
  return el("button", { type: "button", class: "tile", onclick: () => openDoc(doc.id), "aria-label": `${doc.product_name || doc.barcode || "Label"}${doc.nutrients_verified ? "" : ", unverified"}` },
    el("span", { class: "sq", style: img ? `background-image:url('${encodeURI(img)}')` : null },
      doc.nutrients_verified ? null : el("span", { class: "dot", title: "Unverified" })),
    el("span", { class: "nm", text: doc.product_name || doc.barcode || "Unnamed label" }),
    el("span", { class: "lg", text: doc.language ? langName(doc.language) : "Language not set" }));
}

function renderAllergens(aggs) {
  const full = state.health?.allergen_names || {};
  const rows = new Map(aggs.allergens.map((b) => [b.key, b]));
  for (const k of state.lib.allergens) if (!rows.has(k)) rows.set(k, { key: k, count: 0, contains: 0, may_contain: 0 });
  const box = $("#allergens");
  box.hidden = rows.size === 0;
  const max = Math.max(1, ...[...rows.values()].map((b) => b.count));
  const pick = (name, kind) => { state.lib.allergens.add(name); state.lib.kind = kind; loadLibrary(); };
  $("#alg-list").replaceChildren(...[...rows.values()].map((b) => {
    const on = state.lib.allergens.has(b.key);
    const seg = (cls, n, kind, label) => n ? el("button", { type: "button", class: cls, style: `flex:${n}`, title: `${n} ${label}`, "aria-label": `${full[b.key] || b.key}: ${n} ${label}`, onclick: () => pick(b.key, kind) }) : null;
    return el("div", { class: "alg-row" + (on ? " on" : "") },
      el("button", { type: "button", class: "nm", text: SHORT[b.key] || full[b.key] || b.key, "aria-label": full[b.key] || b.key, "aria-pressed": String(on), onclick: () => { on ? state.lib.allergens.delete(b.key) : state.lib.allergens.add(b.key); loadLibrary(); } }),
      el("div", { class: "bar", style: `width:${Math.max(8, (b.count / max) * 100)}%` }, seg("c", b.contains, "contains", "contain it"), seg("m", b.may_contain, "may_contain", "may contain it")),
      el("span", { class: "ct", text: String(b.count) }));
  }));
  $("#alg-clear").hidden = !(state.lib.allergens.size || state.lib.kind);
}
$("#alg-clear").addEventListener("click", () => { state.lib.allergens.clear(); state.lib.kind = ""; loadLibrary(); });

async function openDoc(id) {
  try {
    const r = await fetch(`/api/doc/${id}`);
    if (!r.ok) throw new Error();
    const doc = await r.json();
    openResult({ doc, raw: { markdown: doc.raw_markdown }, image_url: imageUrl(doc), fromLibrary: true });
  } catch {
    $("#lib-note").textContent = "Couldn't open that label. Try again.";
  }
}

let timer;
$("#q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(loadLibrary, 300); });

init();
