// Shared helpers for every screen: DOM building, formatting, the one state object, and the
// small bottom sheets. Model text is only ever inserted with textContent, never as HTML.

// ---------- DOM ----------

export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => [...document.querySelectorAll(selector)];

/**
 * Build an element. `attrs` understands: class, text, onclick-style handlers (`on...`),
 * and plain attributes (null/undefined/false are skipped, true becomes an empty attribute).
 * Children may be nodes, strings, arrays of either, or null.
 */
export function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (name === "class") node.className = value;
    else if (name === "text") node.textContent = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else if (value !== null && value !== undefined && value !== false) {
      node.setAttribute(name, value === true ? "" : value);
    }
  }
  for (const child of children.flat()) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

// ---------- formatting ----------

const LANGUAGE_NAMES = {
  en: "English", fr: "French", es: "Spanish", pt: "Portuguese",
  de: "German", it: "Italian", ja: "Japanese",
};
export const langName = (code) => LANGUAGE_NAMES[code] || code;

// Short names for the Library bars; the Result uses the full names from /api/health.
export const ALLERGEN_SHORT_NAMES = {
  gluten: "Gluten", crustaceans: "Crustaceans", eggs: "Eggs", fish: "Fish",
  peanuts: "Peanuts", soybeans: "Soy", milk: "Milk", tree_nuts: "Tree nuts",
  celery: "Celery", mustard: "Mustard", sesame: "Sesame", sulphites: "Sulphites",
  lupin: "Lupin", molluscs: "Molluscs",
};

/** 27 -> "27", 0.12345 -> "0.123", missing -> "–". */
export const fmt = (n) => (n === null || n === undefined ? "–" : String(Math.round(n * 1000) / 1000));

export const seconds = (ms) => `${(ms / 1000).toFixed(1)} s`;

/** The reader answers in Markdown. Show it as plain text: same words, same case. */
export function cleanText(markdown) {
  return markdown
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/(\*\*|__|`)/g, "")
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

/** Where to load a label photo from: an explicit URL, our own captures, or an absolute URL. */
export function imageUrl(doc, explicit) {
  if (explicit) return explicit;
  const path = doc.image_path || "";
  if (path.startsWith("captures/")) return "/" + path;
  if (path.startsWith("http")) return path;
  return "";
}

// ---------- state ----------

export const state = {
  tab: "capture",
  health: null, // /api/health: endpoint and allergen display names

  // Capture screen
  file: null, // the photo chosen but not yet read
  reading: false,

  // Result sheet
  current: null, // the last /api/capture (or /api/doc) response being shown
  rawView: "markdown", // which "Extracted text" tab is open: markdown | json

  // Library screen
  lib: { language: "all", allergens: new Set(), kind: "", languages: [] },
};

// ---------- small bottom sheets ("low" sheets): framing tips, the raw request/response ----------
// At most one is open at a time, over a dimmed backdrop.

let openSheet = null;

export const isLowSheetOpen = () => openSheet !== null;

export function openLow(selector) {
  closeLow();
  openSheet = $(selector);
  $("#backdrop").hidden = false;
  openSheet.hidden = false;
  openSheet.querySelector("input:not([hidden]), button, select")?.focus();
}

export function closeLow() {
  if (!openSheet) return;
  openSheet.hidden = true;
  $("#backdrop").hidden = true;
  openSheet = null;
}

export function wireSheets() {
  $("#backdrop").addEventListener("click", closeLow);
  $$(".sheet.low .close").forEach((button) => button.addEventListener("click", closeLow));
}
