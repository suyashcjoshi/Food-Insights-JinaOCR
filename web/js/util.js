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

/** Net carbs = carbohydrate - fibre (never below 0). Same rule as app/diary.py, which does the real adding up. */
export function netCarbs(nutrients) {
  const carbs = nutrients.carbohydrates_g;
  if (carbs === undefined || carbs === null) return { value: null, fiberRead: false };
  const fiber = nutrients.fiber_g;
  return { value: Math.round(Math.max(carbs - (fiber || 0), 0) * 10) / 10, fiberRead: fiber !== undefined && fiber !== null };
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
