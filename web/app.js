"use strict";
// Food Insights frontend: Capture -> Result -> Library. No build step, no framework.
// Model text is always inserted with textContent; the only HTML we ever set is Elasticsearch
// highlights, escaped first and then re-enabling <mark> only.

const $ = (sel) => document.querySelector(sel);
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

const state = { file: null, health: null, current: null, raw: "output", lib: { allergens: new Set(), language: "" } };

// ---------- views ----------
function showView(name) {
  for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== `view-${name}`;
  for (const b of document.querySelectorAll("#tabs button")) b.classList.toggle("active", b.dataset.view === name);
  if (name === "library") loadLibrary();
}
$("#tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-view]");
  if (b && !b.disabled) showView(b.dataset.view);
});

// ---------- startup ----------
async function init() {
  try {
    state.health = await (await fetch("/api/health")).json();
    const sel = $("#prompt");
    for (const p of state.health.prompts) sel.append(el("option", { value: p, text: p }));
    sel.value = state.health.default_prompt;
    sel.addEventListener("change", showPromptText);
    showPromptText();
    fetch("/api/warmup", { method: "POST" }).catch(() => {}); // wake the model, ignore the outcome
  } catch {
    setStatus("The server is not answering.", true);
  }
}
function showPromptText() {
  const text = state.health?.prompt_texts?.[$("#prompt").value] || "";
  $("#prompt-text").textContent = text ? `Sent to the model: “${text}”` : "";
}

// ---------- capture ----------
function setStatus(msg, err = false, busy = false) {
  const s = $("#status");
  s.className = "status" + (err ? " err" : "");
  s.replaceChildren(busy ? el("span", { class: "spin" }) : "", msg);
}

$("#file").addEventListener("change", (e) => {
  const f = e.target.files[0];
  state.file = f || null;
  $("#read-btn").disabled = !f;
  if (f) {
    const img = $("#preview");
    img.src = URL.createObjectURL(f);
    img.hidden = false;
    $("#drop-hint").hidden = true;
  }
});

async function postCapture(prompt, index) {
  const fd = new FormData();
  fd.append("image", state.file);
  fd.append("prompt", prompt);
  fd.append("index", index ? "true" : "false");
  for (const [field, id] of [["barcode", "#barcode"], ["language", "#language"], ["product_name", "#product-name"]]) {
    const v = $(id).value.trim();
    if (v) fd.append(field, v);
  }
  const r = await fetch("/api/capture", { method: "POST", body: fd });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.detail ? `${body.error || "error"} (${body.status || r.status}): ${body.detail}` : `Server said ${r.status}`);
  return body;
}

$("#capture-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.file) return;
  $("#read-btn").disabled = true;
  setStatus("Reading the label… the first read after a quiet period can take two to three minutes.", false, true);
  try {
    const data = await postCapture($("#prompt").value, true);
    setStatus("");
    renderResult(data);
    showView("result");
  } catch (err) {
    setStatus(err.message, true);
  } finally {
    $("#read-btn").disabled = false;
  }
});

// ---------- result ----------
const ROWS = [
  ["energy_kcal", "Energy", "kcal", false, true],
  ["fat_g", "Fat", "g", false, true],
  ["saturated_fat_g", "of which saturates", "g", true, true],
  ["carbohydrates_g", "Carbohydrate", "g", false, true],
  ["sugars_g", "of which sugars", "g", true, true],
  ["added_sugars_g", "of which added sugars", "g", true, false],
  ["fiber_g", "Fibre", "g", false, false],
  ["protein_g", "Protein", "g", false, true],
  ["salt_g", "Salt", "g", false, true],
  ["sodium_mg", "Sodium", "mg", false, false],
];
const FLAG_TEXT = {
  edge_cutoff_suspected: "Text looks cut off at the edge of the frame.",
  kcal_mismatch: "Energy does not match fat, carbohydrate and protein (4·C + 4·P + 9·F).",
  sugars_gt_carbs: "Sugars are higher than carbohydrate.",
  saturates_gt_fat: "Saturates are higher than fat.",
  energy_converted: "Energy was converted from kJ (÷ 4.184).",
  aligned: "Values were re-aligned to their labels by row order.",
  looped: "The model's output looped. Do not trust this read.",
};

function renderResult(data) {
  const doc = data.doc;
  state.current = data;
  state.raw = "output";
  $("#view-result").dataset.id = doc.id;
  $('#tabs button[data-view="result"]').disabled = false;
  $("#shot").src = data.image_url || (doc.image_path?.startsWith("captures/") ? "/" + doc.image_path : doc.image_path?.startsWith("http") ? doc.image_path : "");

  const n = doc.nutrients || {};
  const verified = !!doc.nutrients_verified;
  const badge = $("#verified-badge");
  badge.textContent = verified ? "Verified" : "Not verified";
  badge.className = "badge " + (verified ? "ok" : "no");
  badge.title = verified
    ? "Parsed from the panel, nothing cut off, numbers consistent. It does not mean the numbers are right."
    : "A panel was not parsed, text looks cut off, or the numbers contradict each other.";

  $("#basis-line").textContent = {
    "100g": "Values per 100 g",
    "100ml": "Values per 100 ml",
    serving: `Values per serving${n.serving_text ? ` (${n.serving_text})` : ""}`,
  }[n.basis] || "Basis not stated on the label. Check the pack.";

  const hero = $("#carb-hero");
  hero.replaceChildren(
    ...(n.carbohydrates_g === undefined
      ? [el("span", { class: "what", text: "Carbohydrate not read from this photo." })]
      : [el("span", { class: "num", text: fmt(n.carbohydrates_g) }), el("span", { class: "unit", text: "g" }), el("span", { class: "what", text: "carbohydrate" })]),
  );

  const body = $("#nutrients tbody");
  body.replaceChildren(
    ...ROWS.filter(([k, , , , core]) => (core && !(k === "salt_g" && n.sodium_mg !== undefined)) || n[k] !== undefined).map(([k, label, unit, child]) =>
      el("tr", { class: child ? "child" : "" },
        el("td", { text: label }),
        n[k] === undefined ? el("td", { class: "miss", text: "not read" }) : el("td", { text: `${fmt(n[k])} ${unit}` })),
    ),
  );
  if (n.energy_kj !== undefined) {
    body.append(el("tr", { class: "child" }, el("td", { text: "energy as printed" }), el("td", { text: `${fmt(n.energy_kj)} kJ` })));
  }

  $("#flags").replaceChildren(
    ...(doc.parse_flags || []).filter((f) => FLAG_TEXT[f]).map((f) => el("li", { text: FLAG_TEXT[f] })),
  );
  renderOff(doc);

  $("#unverified-text").textContent = doc.unverified_text || "No ingredients or allergens text in the frame.";
  const names = state.health?.allergen_names || {};
  const mentions = doc.allergen_mentions || [];
  const kindRow = (kind, label) => {
    const those = mentions.filter((a) => a.kind === kind);
    return those.length
      ? el("div", { class: "kind-row" }, el("span", { class: "kind-label", text: label }),
          ...those.map((a) => el("span", { class: `chip ${kind === "contains" ? "contains" : "may"}`, text: names[a.name] || a.name })))
      : null;
  };
  $("#allergen-chips").replaceChildren(
    ...(mentions.length
      ? [kindRow("contains", "Contains"), kindRow("may_contain", "May contain")].filter(Boolean)
      : [el("span", { class: "fine", text: "None named in the text as read." })]),
  );

  const t = doc.telemetry || {};
  $("#telemetry").textContent = [
    state.health?.endpoint?.replace(/^\./, "").replace("-chat_completion", "") || "jina-ocr-v1",
    `${t.prompt_variant || "official"} prompt`,
    t.prompt_tokens !== undefined ? `${t.prompt_tokens} in / ${t.completion_tokens} out tokens` : null,
    t.ocr_ms !== undefined ? `${(t.ocr_ms / 1000).toFixed(1)} s` : null,
    t.cost_est !== undefined ? `~$${t.cost_est.toFixed(4)}` : null,
  ].filter(Boolean).join(" · ");

  const ix = data.indexed;
  $("#stored").textContent = !ix ? "" : ix.skipped ? "Comparison run, not stored." : ix.ok ? `Stored in “${ix.index}”. Find it in the Library.` : `Not stored: ${ix.error}`;
  renderRaw();
}

function renderOff(doc) {
  const m = doc.off_match || { status: "not_found" };
  const chip = (cls, text) => el("span", { class: `chip ${cls}`, text });
  let node;
  const label = doc.nutrients?.carbohydrates_g;
  if (m.status === "match") node = chip("ok", `Matches Open Food Facts · carbohydrate ${fmt(m.carbohydrates_100g)} g per 100 g`);
  else if (m.status === "mismatch") node = chip("bad", `Differs from Open Food Facts · label ${fmt(label)} g, OFF ${fmt(m.carbohydrates_100g)} g per 100 g`);
  else if (m.status === "not_comparable") node = chip("muted", `Open Food Facts lists ${fmt(m.carbohydrates_100g)} g per 100 g; this panel is not per 100 g`);
  else if (m.status === "error") node = chip("muted", "Open Food Facts could not be reached");
  else node = chip("muted", doc.barcode ? `Barcode ${doc.barcode} not found on Open Food Facts` : "No barcode · not cross-checked");
  $("#off-chip").replaceChildren(node, m.url ? el("a", { href: m.url, target: "_blank", rel: "noopener", text: " View on Open Food Facts", class: "fine" }) : "");
}

function renderRaw() {
  const data = state.current;
  const raw = data.raw || { markdown: data.doc.raw_markdown };
  const shown = { output: raw.markdown, prompt: raw.prompt ? `${raw.prompt_variant}: ${raw.prompt}` : "Not kept for this capture.", request: raw.request ? JSON.stringify(raw.request, null, 2) : "Not kept for this capture." }[state.raw];
  $("#raw-body").textContent = shown || "";
  for (const b of document.querySelectorAll(".raw-tabs button")) b.classList.toggle("active", b.dataset.raw === state.raw);
  const other = (state.health?.prompts || []).find((p) => p !== (raw.prompt_variant || data.doc.telemetry?.prompt_variant));
  const btn = $("#reread");
  $("#reread-row").hidden = !state.file || !other;
  btn.textContent = other ? `Re-read with the “${other}” prompt` : "";
  btn.dataset.prompt = other || "";
}
document.querySelector(".raw-tabs").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-raw]");
  if (b) { state.raw = b.dataset.raw; renderRaw(); }
});
$("#reread").addEventListener("click", async (e) => {
  const btn = e.currentTarget;
  btn.disabled = true;
  btn.textContent = "Reading…";
  try {
    renderResult(await postCapture(btn.dataset.prompt, false));
    $("#raw").open = true;
  } catch (err) {
    btn.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});
$("#again").addEventListener("click", () => showView("capture"));
$("#to-library").addEventListener("click", () => showView("library"));

// ---------- library ----------
const params = () => {
  const p = new URLSearchParams();
  if ($("#q").value.trim()) p.set("q", $("#q").value.trim());
  for (const a of state.lib.allergens) p.append("allergen", a);
  if (state.lib.language) p.set("language", state.lib.language);
  if ($("#f-kind").value) p.set("allergen_kind", $("#f-kind").value);
  if ($("#f-verified").checked) p.set("verified", "true");
  return p;
};
const safeMark = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/&lt;mark&gt;/g, "<mark>").replace(/&lt;\/mark&gt;/g, "</mark>");

let libSeq = 0; // a slow earlier request must not overwrite a newer one
async function loadLibrary() {
  const p = params().toString();
  const mine = ++libSeq;
  try {
    const [s, a] = await Promise.all([fetch(`/api/search?${p}`), fetch(`/api/aggs?${p}`)]);
    if (!s.ok || !a.ok) throw new Error((await (s.ok ? a : s).json()).detail || "search failed");
    const [search, aggs] = [await s.json(), await a.json()];
    if (mine === libSeq) renderLibrary(search, aggs);
  } catch (err) {
    if (mine !== libSeq) return;
    $("#cards").replaceChildren(el("p", { class: "empty", text: err.message }));
    $("#lib-summary").textContent = "";
  }
}

function renderLibrary(search, aggs) {
  const names = state.health?.allergen_names || {};
  $("#lib-summary").textContent =
    `${search.total} capture${search.total === 1 ? "" : "s"}` +
    (search.hits.length < search.total ? ` · showing the first ${search.hits.length}` : "") +
    (aggs.verified?.true !== undefined ? ` · ${aggs.verified.true} with a verified panel` : "");

  const facet = (label, counts, on, onclick) =>
    el("button", { type: "button", class: "facet" + (on ? " on" : ""), onclick }, el("span", { text: label }), counts);
  const num = (n) => el("b", { text: String(n) });
  const all = new Map(aggs.allergens.map((b) => [b.key, b]));
  for (const k of state.lib.allergens) if (!all.has(k)) all.set(k, { key: k, count: 0, contains: 0, may_contain: 0 }); // keep a selected filter visible
  $("#facet-allergens").replaceChildren(
    ...(all.size ? [...all.values()].map((b) => facet(
      names[b.key] || b.key,
      el("span", { class: "counts" },
        el("span", { class: "n contains" + (b.contains ? "" : " zero"), title: "contains", text: String(b.contains) }),
        el("span", { class: "n may" + (b.may_contain ? "" : " zero"), title: "may contain", text: String(b.may_contain) })),
      state.lib.allergens.has(b.key),
      () => { state.lib.allergens.has(b.key) ? state.lib.allergens.delete(b.key) : state.lib.allergens.add(b.key); loadLibrary(); },
    )) : [el("p", { class: "fine", text: "No allergen words in these captures." })]),
  );
  $("#facet-languages").replaceChildren(
    ...(aggs.languages.length ? aggs.languages.map((b) => facet(b.key, num(b.count), state.lib.language === b.key, () => {
      state.lib.language = state.lib.language === b.key ? "" : b.key;
      $("#f-language").value = state.lib.language;
      loadLibrary();
    })) : [el("p", { class: "fine", text: "No language set on these captures." })]),
  );
  const sel = $("#f-language");
  const have = new Set([...sel.options].map((o) => o.value));
  for (const b of aggs.languages) if (!have.has(b.key)) sel.append(el("option", { value: b.key, text: b.key }));
  sel.value = state.lib.language;

  $("#cards").replaceChildren(
    ...(search.hits.length ? search.hits.map(card) : [el("p", { class: "empty", text: "Nothing here yet. Read a label first, or loosen the filters." })]),
  );
}

function card(doc) {
  const names = state.health?.allergen_names || {};
  const n = doc.nutrients || {};
  const img = doc.image_path?.startsWith("captures/") ? "/" + doc.image_path : doc.image_path?.startsWith("http") ? doc.image_path : "";
  const snip = doc.highlight?.plain_text?.[0] || doc.highlight?.unverified_text?.[0];
  const snipNode = el("div", { class: "snip" });
  if (snip) snipNode.innerHTML = safeMark(snip);
  return el("button", { type: "button", class: "lib-card", onclick: () => openDoc(doc.id) },
    el("div", { class: "thumb", style: img ? `background-image:url('${encodeURI(img)}')` : null, text: img ? "" : "no photo" }),
    el("div", { class: "body" },
      el("h3", { text: doc.product_name || doc.barcode || doc.id.slice(0, 8) }),
      el("div", { class: "chips" },
        el("span", { class: "chip " + (doc.nutrients_verified ? "ok" : "muted"), text: doc.nutrients_verified ? "Verified" : "Not verified" }),
        n.carbohydrates_g !== undefined ? el("span", { class: "chip", text: `${fmt(n.carbohydrates_g)} g carbs${n.basis === "100g" ? " / 100 g" : n.basis === "100ml" ? " / 100 ml" : ""}` }) : null,
        doc.language ? el("span", { class: "chip", text: doc.language }) : null),
      doc.allergen_mentions?.length ? el("div", { class: "chips" }, ...doc.allergen_mentions.map((a) =>
        el("span", { class: `chip ${a.kind === "contains" ? "contains" : "may"}`, title: a.kind === "contains" ? "contains (as read)" : "may contain (as read)", text: (a.kind === "contains" ? "" : "may: ") + (names[a.name] || a.name) }))) : null,
      snip ? snipNode : null),
  );
}

async function openDoc(id) {
  const r = await fetch(`/api/doc/${id}`);
  if (!r.ok) return;
  const doc = await r.json();
  state.file = null; // no original file to re-read
  renderResult({ doc, raw: { markdown: doc.raw_markdown }, image_url: doc.image_path?.startsWith("captures/") ? "/" + doc.image_path : doc.image_path });
  showView("result");
}

let timer;
$("#q").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(loadLibrary, 300); });
$("#search-form").addEventListener("submit", (e) => { e.preventDefault(); loadLibrary(); });
$("#f-verified").addEventListener("change", loadLibrary);
$("#f-kind").addEventListener("change", loadLibrary);
$("#f-language").addEventListener("change", (e) => { state.lib.language = e.target.value; loadLibrary(); });

init();
