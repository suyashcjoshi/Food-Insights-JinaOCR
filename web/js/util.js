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

  // Capture screen: two photos, the front (optional, for the name) and the back (the nutrition panel)
  photos: { front: null, back: null }, // each { file, url } once chosen
  slot: "front", // which one the next photo goes to
  reading: false,

  // Result sheet
  current: null, // the last /api/capture (or /api/doc) response being shown
  rawView: "markdown", // which "Extracted text" tab is open: markdown | json

  // Library screen
  lib: { language: "all", allergens: new Set(), kind: "", languages: [] },
};

// ---------- the person's own daily limits (kept in this browser only) ----------

export const DEFAULT_LIMITS = { netCarbsG: 100, calories: 1800 };
const LIMITS_KEY = "fi.limits";

export function getLimits() {
  try {
    const saved = JSON.parse(localStorage.getItem(LIMITS_KEY) || "{}");
    return {
      netCarbsG: Number(saved.netCarbsG) > 0 ? Number(saved.netCarbsG) : DEFAULT_LIMITS.netCarbsG,
      calories: Number(saved.calories) > 0 ? Number(saved.calories) : DEFAULT_LIMITS.calories,
    };
  } catch {
    return { ...DEFAULT_LIMITS }; // private mode: the defaults still work
  }
}

export function saveLimits(limits) {
  try {
    localStorage.setItem(LIMITS_KEY, JSON.stringify(limits));
  } catch { /* private mode: the limits just will not stick */ }
}

// ---------- net carbs and the day ----------

// How net carbs were worked out. Same rules as app/diary.py, which does the real adding up.
export const NET = {
  MINUS_FIBRE: "minus_fibre", // US-style panel: total carbohydrate includes fibre, so subtract it
  ALREADY_NET: "already_excludes_fibre", // EU / UK panel: carbohydrate already excludes fibre
  FIBRE_NOT_READ: "fibre_not_read", // US-style, no fibre figure: the full carbohydrate counts
  FORMAT_UNKNOWN: "format_unknown", // cannot tell the format: the full carbohydrate counts
};

const round1 = (n) => Math.round(n * 10) / 10;

/** { value, method }. Subtract fibre only when the printed carbohydrate includes it (US / Canada). */
export function netCarbs(nutrients) {
  const carbs = nutrients.carbohydrates_g;
  if (carbs === undefined || carbs === null) return { value: null, method: null };
  const includesFibre = nutrients.carb_includes_fibre;
  if (includesFibre === false) return { value: round1(carbs), method: NET.ALREADY_NET };
  if (includesFibre === undefined || includesFibre === null) return { value: round1(carbs), method: NET.FORMAT_UNKNOWN };
  const fiber = nutrients.fiber_g;
  if (fiber === undefined || fiber === null) return { value: round1(carbs), method: NET.FIBRE_NOT_READ };
  return { value: round1(Math.max(carbs - fiber, 0)), method: NET.MINUS_FIBRE };
}

/** The line under the big net carbs figure: what was done, in plain words. */
export function netCarbsNote(nutrients, method) {
  const carbs = fmt(nutrients.carbohydrates_g);
  return {
    [NET.MINUS_FIBRE]: `${carbs} carbs − ${fmt(nutrients.fiber_g)} fibre (US-style label)`,
    [NET.ALREADY_NET]: `${carbs} carbs. This label already leaves fibre out`,
    [NET.FIBRE_NOT_READ]: `${carbs} carbs, fibre not read`,
    [NET.FORMAT_UNKNOWN]: `${carbs} carbs. Label format unclear, so fibre is not subtracted`,
  }[method] || "Carbohydrate not read from this photo.";
}

/** What one portion is: the panel as printed. { text, size } where size is the g / ml when per 100. */
export function portionUnit(nutrients) {
  if (nutrients.basis === "100g") return { text: "100 g", size: 100 };
  if (nutrients.basis === "100ml") return { text: "100 ml", size: 100 };
  if (nutrients.basis === "serving") {
    return { text: nutrients.serving_text ? `serving (${nutrients.serving_text})` : "serving", size: null };
  }
  return { text: "the panel as printed", size: null };
}

/** "1.5 × 100 g = 150 g", or "1.5 × serving (6 oz (170g))" when the size is not a plain weight. */
export function amountLine(portions, nutrients) {
  const unit = portionUnit(nutrients);
  const times = `${fmt(portions)} × ${unit.text}`;
  return unit.size === null ? times : `${times} = ${fmt(portions * unit.size)} ${unit.text.split(" ").pop()}`;
}

/** The person's local date as 2026-11-06: what "today" means for the daily log. */
export function todayKey(now = new Date()) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`;
}

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
