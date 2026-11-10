// Today screen: what you have eaten today against your own limits. Totals come from one
// Elasticsearch aggregation (/api/today); the limits live in this browser. Numbers over a limit turn red.
// The app only compares numbers. It never says what to eat.

import { $, el, fmt, getLimits, imageUrl, openLow, closeLow, saveLimits, state, todayKey } from "./util.js";

// ---------- totals against limits ----------

function totalCard({ key, label, value, limit, unit }) {
  const over = value > limit;
  const fill = Math.min(100, limit > 0 ? (value / limit) * 100 : 0);
  return el("div", { class: "total" + (over ? " over" : ""), "data-total": key },
    el("span", { class: "t-label", text: label }),
    el("span", { class: "t-value" },
      el("span", { class: "num", text: fmt(value) }),
      el("span", { class: "t-unit", text: ` ${unit}` })),
    el("span", { class: "t-limit", text: `of ${limit} ${unit}` }),
    el("span", { class: "meter" }, el("i", { style: `width:${fill}%` })),
    el("span", { class: "t-remain", text: over ? `${fmt(value - limit)} ${unit} over` : `${fmt(limit - value)} ${unit} left` }),
    el("span", { class: "t-flag", text: over ? "Over your limit" : "" }));
}

export function renderTotals(summary, target = $("#today-totals")) {
  const limits = getLimits();
  target.replaceChildren(
    totalCard({ key: "carbs", label: "Net carbs", value: summary.totals.net_carbs_g, limit: limits.netCarbsG, unit: "g" }),
    totalCard({ key: "calories", label: "Calories", value: summary.totals.calories_kcal, limit: limits.calories, unit: "kcal" }));
}

// ---------- the entries ----------

/** "1.5 × 100 g = 150 g": what was eaten, in the unit the panel uses. */
function portionsText(entry) {
  const unit = entry.unit_text || "portion";
  return `${fmt(entry.portions)} × ${unit}${entry.amount_text ? ` = ${entry.amount_text}` : ""}`;
}

// Only the cases worth a note: the others are the normal, expected ones.
const NET_NOTES = {
  fibre_not_read: "Fibre not read, so the full carbohydrate is counted",
  format_unknown: "Label format unclear, so fibre is not subtracted",
};

function entryRow(entry) {
  const image = imageUrl(entry);
  const nutrition = [
    entry.net_carbs_g !== undefined ? `${fmt(entry.net_carbs_g)} g net carbs` : "carbs not read",
    entry.calories_kcal !== undefined ? `${fmt(entry.calories_kcal)} kcal` : "calories not read",
  ].join(" · ");
  return el("div", { class: "entry" },
    el("span", { class: "sq small", style: image ? `background-image:url('${encodeURI(image)}')` : null }),
    el("span", { class: "e-text" },
      el("span", { class: "e-name", text: entry.product_name || "Unnamed label" }),
      el("span", { class: "e-sub", text: `${portionsText(entry)} · ${nutrition}` }),
      NET_NOTES[entry.net_method] ? el("span", { class: "e-note", text: NET_NOTES[entry.net_method] }) : null,
      entry.edited ? el("span", { class: "e-note", text: "Numbers edited by hand" }) : null),
    el("button", { type: "button", class: "icon remove", "aria-label": `Remove ${entry.product_name || "entry"}`, text: "×", onclick: () => removeEntry(entry.id) }));
}

async function removeEntry(id) {
  try {
    const response = await fetch(`/api/log/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error();
  } catch {
    $("#today-note").textContent = "Couldn't remove that. Try again.";
    return;
  }
  loadToday();
}

// ---------- load and render ----------

export async function fetchToday() {
  const response = await fetch(`/api/today?day=${todayKey()}`);
  if (!response.ok) throw new Error("today failed");
  return response.json();
}

export async function loadToday() {
  $("#today-date").textContent = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
  try {
    const summary = await fetchToday();
    renderTotals(summary);
    $("#today-entries").replaceChildren(...summary.entries.map(entryRow));
    const count = summary.totals.entries;
    $("#today-count").textContent = count ? `· ${count} ${count === 1 ? "entry" : "entries"}` : "";
    $("#today-empty").hidden = summary.entries.length > 0;
    $("#today-note").textContent = "";
  } catch {
    $("#today-note").textContent = "Couldn't load today. Check your connection and try again.";
  }
}

// ---------- your limits (behind the gear) ----------

function openLimits() {
  const limits = getLimits();
  $("#lim-carbs").value = limits.netCarbsG;
  $("#lim-kcal").value = limits.calories;
  openLow("#sheet-limits");
}

export function wireToday() {
  $("#limits-open").addEventListener("click", openLimits);
  $("#limits-save").addEventListener("click", () => {
    saveLimits({ netCarbsG: Number($("#lim-carbs").value), calories: Number($("#lim-kcal").value) });
    closeLow();
    if (state.tab === "today") loadToday();
  });
}
