// Library screen: a grid of every label read, a search box, language chips, and the allergen bars.
// Two Elasticsearch-backed calls draw it (/api/search and /api/aggs) with the same filters,
// so the grid and the bars always agree. Tapping a tile adds a third call (/api/doc/<id>).
import { $, ALLERGEN_SHORT_NAMES, el, imageUrl, langName, state } from "./util.js";
import { openResult } from "./result.js";

const PAGE_SIZE = "60";
const SEARCH_DEBOUNCE_MS = 300;
const MIN_BAR_PERCENT = 8; // the smallest allergen bar still has to be tappable

const searchText = () => $("#q").value.trim();

const filtersActive = () =>
  state.lib.language !== "all" || state.lib.allergens.size > 0 || searchText() !== "";

/** The query string shared by /api/search and /api/aggs. */
function filterParams() {
  const params = new URLSearchParams({ size: PAGE_SIZE });
  if (searchText()) params.set("q", searchText());
  for (const allergen of state.lib.allergens) params.append("allergen", allergen);
  if (state.lib.kind) params.set("allergen_kind", state.lib.kind);
  if (state.lib.language !== "all") params.set("language", state.lib.language);
  return params.toString();
}

function clearFilters() {
  state.lib.language = "all";
  state.lib.allergens.clear();
  state.lib.kind = "";
  $("#q").value = "";
}

// ---------- loading ----------

let latestRequest = 0; // a slow earlier request must not overwrite a newer one

export async function loadLibrary() {
  const thisRequest = ++latestRequest;
  const query = filterParams();
  try {
    const [searchResponse, aggsResponse] = await Promise.all([
      fetch(`/api/search?${query}`),
      fetch(`/api/aggs?${query}`),
    ]);
    if (!searchResponse.ok || !aggsResponse.ok) throw new Error("search failed");
    const search = await searchResponse.json();
    const aggs = await aggsResponse.json();
    if (thisRequest === latestRequest) renderLibrary(search, aggs);
  } catch {
    if (thisRequest !== latestRequest) return;
    $("#grid").replaceChildren();
    $("#allergens").hidden = true;
    showEmpty("Couldn't load the library. Check your connection and try again.", "Try again", loadLibrary);
  }
}

async function openLabel(id) {
  try {
    const response = await fetch(`/api/doc/${id}`);
    if (!response.ok) throw new Error();
    const doc = await response.json();
    openResult({ doc, raw: { markdown: doc.raw_markdown }, image_url: imageUrl(doc), fromLibrary: true });
  } catch {
    $("#lib-note").textContent = "Couldn't open that label. Try again.";
  }
}

// ---------- render ----------

function showEmpty(text, buttonLabel, onClick) {
  $("#empty").hidden = false;
  $("#empty-text").textContent = text;
  const button = $("#empty-go");
  button.hidden = !buttonLabel;
  button.textContent = buttonLabel || "";
  button.onclick = onClick;
}

function renderLibrary(search, aggs) {
  // the language chips come from the unfiltered library, so picking one does not shrink the row
  if (!state.lib.languages.length || !filtersActive()) {
    state.lib.languages = aggs.languages.map((bucket) => bucket.key);
  }
  renderLanguageChips();
  renderCount(search);
  const tiles = search.hits.map(renderTile);
  $("#grid").classList.toggle("list", tiles.some((tile) => tile.classList.contains("result")));
  $("#grid").replaceChildren(...tiles);
  renderEmptyState(search.total);
  renderAllergenBars(aggs);
}

function renderCount(search) {
  const labels = `${search.total} label${search.total === 1 ? "" : "s"}`;
  const clipped = search.hits.length < search.total ? `, showing the first ${search.hits.length}` : "";
  $("#lib-note").textContent = labels + clipped;
}

function renderEmptyState(total) {
  if (total > 0) {
    $("#empty").hidden = true;
  } else if (filtersActive()) {
    showEmpty("Nothing matches. Try other words, or clear the filters.", "Clear filters", () => {
      clearFilters();
      loadLibrary();
    });
  } else {
    showEmpty("No labels yet. Photograph one to start.", "Photograph a label", goToCapture);
  }
}

function renderLanguageChips() {
  const options = [["all", "All"], ...state.lib.languages.map((code) => [code, langName(code)])];
  $("#chips").replaceChildren(...options.map(([language, label]) => el("button", {
    type: "button",
    class: "chip",
    role: "radio",
    "aria-checked": String(state.lib.language === language),
    text: label,
    onclick: () => { state.lib.language = language; loadLibrary(); },
  })));
}

/** The text that matched the search, with the matching words marked. Built from text nodes only:
 *  Elasticsearch wraps matches in <mark>, and everything else is shown literally, never as HTML. */
function snippetNode(doc) {
  const hit = doc.highlight?.unverified_text?.[0] || doc.highlight?.plain_text?.[0];
  if (!hit) return null;
  const parts = hit.split(/<\/?mark>/); // even positions are plain text, odd positions are matches
  // the reader's own HTML tags and Markdown marks are not shown, and line breaks become spaces
  const plain = (text) => text.replace(/<[^>]+>/g, " ").replace(/(\*\*|__|`)/g, "").replace(/^#{1,6}\s+/gm, "").replace(/\s+/g, " ");
  return el("span", { class: "snip" }, parts.map((text, i) => (i % 2 ? el("mark", { text: plain(text) }) : plain(text))));
}

function renderTile(doc) {
  const image = imageUrl(doc);
  const snippet = searchText() ? snippetNode(doc) : null; // with a search active, results show why they matched
  return el("button", { type: "button", class: "tile" + (snippet ? " result" : ""), "aria-label": doc.product_name || "Label", onclick: () => openLabel(doc.id) },
    el("span", { class: "sq", style: image ? `background-image:url('${encodeURI(image)}')` : null }),
    el("span", { class: "meta" },
      el("span", { class: "nm", text: doc.product_name || "Unnamed label" }),
      el("span", { class: "lg", text: doc.language ? langName(doc.language) : "Language not set" }),
      snippet));
}

// ---------- allergen bars ----------

function pickAllergen(name, kind) {
  state.lib.allergens.add(name);
  state.lib.kind = kind;
  loadLibrary();
}

function toggleAllergen(name) {
  if (state.lib.allergens.has(name)) state.lib.allergens.delete(name);
  else state.lib.allergens.add(name);
  loadLibrary();
}

/** One coloured piece of a bar: solid = "contains", dashed = "may contain". Tapping filters to it. */
function barSegment(bucket, cssClass, count, kind, phrase, fullName) {
  if (!count) return null;
  return el("button", {
    type: "button",
    class: cssClass,
    style: `flex:${count}`,
    title: `${count} ${phrase}`,
    "aria-label": `${fullName}: ${count} ${phrase}`,
    onclick: () => pickAllergen(bucket.key, kind),
  });
}

function allergenRow(bucket, maxCount, fullNames) {
  const fullName = fullNames[bucket.key] || bucket.key;
  const selected = state.lib.allergens.has(bucket.key);
  const width = Math.max(MIN_BAR_PERCENT, (bucket.count / maxCount) * 100);
  return el("div", { class: "alg-row" + (selected ? " on" : "") },
    el("button", {
      type: "button",
      class: "nm",
      text: ALLERGEN_SHORT_NAMES[bucket.key] || fullName,
      "aria-label": fullName,
      "aria-pressed": String(selected),
      onclick: () => toggleAllergen(bucket.key),
    }),
    el("div", { class: "bar", style: `width:${width}%` },
      barSegment(bucket, "c", bucket.contains, "contains", "contain it", fullName),
      barSegment(bucket, "m", bucket.may_contain, "may_contain", "may contain it", fullName)),
    el("span", { class: "ct", text: String(bucket.count) }));
}

function renderAllergenBars(aggs) {
  const fullNames = state.health?.allergen_names || {};
  const buckets = new Map(aggs.allergens.map((bucket) => [bucket.key, bucket]));
  // a selected allergen stays on screen (with 0) even when the other filters leave it no matches
  for (const name of state.lib.allergens) {
    if (!buckets.has(name)) buckets.set(name, { key: name, count: 0, contains: 0, may_contain: 0 });
  }
  const rows = [...buckets.values()];
  const maxCount = Math.max(1, ...rows.map((bucket) => bucket.count));
  $("#allergens").hidden = rows.length === 0;
  $("#alg-list").replaceChildren(...rows.map((bucket) => allergenRow(bucket, maxCount, fullNames)));
  $("#alg-clear").hidden = !(state.lib.allergens.size || state.lib.kind);
}

// ---------- wiring ----------

let goToCapture = () => {};

export function wireLibrary({ onGoToCapture }) {
  goToCapture = onGoToCapture;
  $("#alg-clear").addEventListener("click", () => {
    state.lib.allergens.clear();
    state.lib.kind = "";
    loadLibrary();
  });
  let debounce;
  $("#q").addEventListener("input", () => {
    clearTimeout(debounce);
    debounce = setTimeout(loadLibrary, SEARCH_DEBOUNCE_MS);
  });
}
