/* UI thread. All scheduling runs in worker.js (Pyodide); files are read locally. */
"use strict";

const $ = (id) => document.getElementById(id);
const el = (tag, props = {}, ...kids) => {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") e.className = v; else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v);
  }
  for (const kid of kids.flat(Infinity)) if (kid != null) e.append(kid.nodeType ? kid : document.createTextNode(kid));
  return e;
};

/* ------------------------------------------------------------ worker RPC */
const worker = new Worker("worker.js");
let nextId = 1, engineReady = false;
const pending = new Map();
worker.onmessage = (ev) => {
  const m = ev.data;
  if (m.type === "progress") { if (m.msg) $("engine-msg").textContent = m.msg; }
  else if (m.type === "ready") {
    engineReady = true; $("engine").classList.add("ready");
    $("engine-msg").textContent = "Solver ready.";
    $("btn-load").disabled = false; $("btn-example").disabled = false; $("btn-example-files").disabled = false;
  } else if (m.type === "fatal") {
    $("engine").classList.add("fatal");
    $("engine-msg").textContent = "Could not start the solver: " + m.msg +
      " (an internet connection is needed on first load to fetch Python and SciPy).";
  } else if (m.type === "result") {
    const p = pending.get(m.id); pending.delete(m.id); p && p(m.result);
  }
};
const call = (method, payload) => new Promise((resolve) => {
  const id = nextId++; pending.set(id, resolve); worker.postMessage({ id, method, payload });
});

/* ------------------------------------------------------------------ state */
let info = null;            // candidates, staff, slots, dates, leads
let hasSchedule = false;
let staged = [];            // [{label, key, value}]
let busy = false;
let lastLoad = null;        // last load payload, to reload with another setting

function setBusy(on, label) {
  busy = on;
  for (const id of ["btn-load", "btn-example", "btn-solve", "btn-resched", "btn-stage"]) $(id).disabled = on || !engineReady;
  if (!on) $("btn-resched").disabled = staged.length === 0;
  if (label) $("engine-msg").textContent = label;
  $("engine").classList.toggle("ready", !on);
}

const readText = (input) => input.files && input.files[0] ? input.files[0].text() : Promise.resolve("");
const msg = (cls, ...kids) => el("div", { class: "msg " + cls }, kids);

/* ------------------------------------------------------------------ step 1 */
async function afterLoad(out) {
  const box = $("load-msg"); box.replaceChildren();
  if (!out.ok) { box.append(msg("err", out.error)); return; }
  info = out.data.info; hasSchedule = false; staged = [];
  $("results").hidden = true; $("results").replaceChildren(); $("step-change").hidden = true;
  const leads = info.leads.length ? info.leads.join(", ") : "none";
  box.append(msg("", `Loaded ${info.candidates.length} applicants, ${info.staff.length} staff `,
    `(leads: ${leads}), ${info.slots.length} time slots over ${info.dates.length} days, ${info.n_forbidden} forbidden pairs.`));
  if (out.data.warnings.length)
    box.append(msg("warn", "Please check:", el("ul", {}, out.data.warnings.map((w) => el("li", { text: w })))));
  $("step-solve").hidden = false;
  box.append(leadPicker());
  fillChangeForm();
}

function leadPicker() {
  const boxes = info.staff.map((s) => el("label", { class: "check" },
    el("input", { type: "checkbox", value: s.id, ...(s.lead ? { checked: "checked" } : {}) }), s.id));
  const apply = el("button", { text: "Apply leads", onclick: async () => {
    const ids = boxes.map((b) => b.firstChild).filter((i) => i.checked).map((i) => i.value);
    setBusy(true, "Updating leads…");
    const out = await call("set_leads", { lead_ids: ids });
    setBusy(false, "Solver ready.");
    if (!out.ok) { alert(out.error); return; }
    info = out.data.info; hasSchedule = false; staged = [];
    $("results").hidden = true; $("results").replaceChildren(); $("step-change").hidden = true;
    summary.textContent = leadSummary();
    fillChangeForm();
  } });
  const leadSummary = () => `Leads: ${info.leads.length ? info.leads.join(", ") : "none — no lead rule; tick the leads below"}`;
  const summary = el("summary", { text: leadSummary() });
  return el("details", { class: "msg", ...(info.leads.length ? {} : { open: "open" }) }, summary,
    el("p", { class: "note", text: "Every panel includes at least one lead. Tick the lead staff, then apply (this resets any schedule)." }),
    el("div", { class: "grid4" }, boxes), el("div", { class: "row" }, apply));
}

$("btn-load").addEventListener("click", async () => {
  if (!$("f-app").files.length || !$("f-staff").files.length) {
    $("load-msg").replaceChildren(msg("err", "Choose the applicants and the staff CSV files first.")); return;
  }
  setBusy(true, "Reading files…");
  const payload = {
    applicants: await readText($("f-app")), staff: await readText($("f-staff")),
    forbidden: await readText($("f-forb")), forbidden_inline: $("forb-inline").value,
    lead_ids: $("lead-ids").value, if_needed: $("opt-ifneeded").value, duplicates: $("opt-dups").value,
  };
  lastLoad = payload;
  await afterLoad(await call("load", payload));
  setBusy(false, "Solver ready.");
});

$("btn-example").addEventListener("click", async () => {
  setBusy(true, "Generating example data…");
  lastLoad = null;
  await afterLoad(await call("load_example", {}));
  setBusy(false, "Solver ready.");
});

$("btn-example-files").addEventListener("click", async () => {
  const out = await call("example_files", {});
  if (!out.ok) { alert(out.error); return; }
  const bytes = Uint8Array.from(atob(out.data.zip_base64), (c) => c.charCodeAt(0));
  const a = el("a", { href: URL.createObjectURL(new Blob([bytes], { type: "application/zip" })), download: "example_csv_files.zip" });
  document.body.append(a); a.click(); a.remove();
});

/* ------------------------------------------------------------------ step 2 */
function params() {
  return {
    min_staff: +$("p-min").value, max_staff: +$("p-max").value, fairness: $("p-fair").value,
    time_limit: +$("p-time").value, allow_parallel: $("p-par").checked, max_parallel: +$("p-rooms").value,
  };
}

$("btn-solve").addEventListener("click", async () => {
  setBusy(true, "Solving… (up to the time limit)");
  const out = await call("solve", { params: params() });
  setBusy(false, "Solver ready.");
  showResult(out, "Schedule");
});

/* ----------------------------------------------------------------- results */
function showResult(out, title, host = $("results")) {
  host.hidden = false; host.replaceChildren();
  const card = el("section", { class: host === $("results") ? "card" : "" });
  host.append(card);
  if (!out.ok) { card.append(el("h2", { text: title }), msg("err", out.error)); return; }
  const r = out.data.result; info = out.data.info;
  card.append(el("h2", { text: title }));

  const statusCls = r.ok ? (r.status === "OPTIMAL" ? "ok" : "warn") : "bad";
  const statusTxt = r.status === "OPTIMAL" ? "Optimal" : r.status === "FEASIBLE" ? "Feasible (time limit reached, may not be optimal)"
    : r.status === "INFEASIBLE" ? "Infeasible — no schedule satisfies every rule"
    : r.status === "UNKNOWN" ? "No schedule found within the time limit (not proven infeasible)" : r.status;
  const chips = [el("span", { class: "chip " + statusCls, text: statusTxt }),
    el("span", { class: "chip", text: `solved in ${r.solve_seconds}s` })];
  if (r.ok) {
    chips.push(el("span", { class: "chip", text: `${r.rows.length} interviews` }));
    if (r.rooms_used > 1) chips.push(el("span", { class: "chip", text: `${r.rooms_used} parallel rooms needed` }));
    chips.push(el("span", { class: "chip", text: `workload per person: ${r.load_stats.min}–${r.load_stats.max} (mean ${r.load_stats.mean})` }));
    if (r.changes) chips.push(el("span", { class: "chip warn", text:
      `${r.changes.moved} moved · ${r.changes.panel} panel change${r.changes.panel === 1 ? "" : "s"} · ${r.changes.new} new · ${r.changes.removed} removed` }));
  }
  card.append(el("div", { class: "stats" }, chips));

  if (!r.ok) { card.append(diagnostics(r.diagnostics)); return; }

  hasSchedule = true;
  $("step-change").hidden = false;
  const showRooms = r.rows.some((x) => x.room > 1);
  const filter = el("input", { type: "text", placeholder: "Filter by name or date…", "aria-label": "Filter" });
  const tbody = el("tbody");
  const head = el("tr", {}, ["Date", "Time", showRooms ? "Room" : null, "Applicant", "Panel", r.changes ? "Change" : null]
    .filter(Boolean).map((h) => el("th", { text: h })));
  const leadSet = new Set(info.leads);
  const draw = () => {
    const q = filter.value.trim().toLowerCase();
    tbody.replaceChildren(...r.rows.filter((x) => !q || (x.candidate + x.date + x.time + x.panel.join(" ")).toLowerCase().includes(q))
      .map((x) => {
        const panel = el("td", {}, x.panel.map((s, i) => [i ? " + " : "", el("span", { class: leadSet.has(s) ? "lead" : "", text: s })]));
        const note = x.change === "moved" ? `moved from ${x.was}` : x.change === "panel" ? "new panel" : x.change === "new" ? "new" : "";
        return el("tr", { class: x.change || "" }, [el("td", { text: x.date }), el("td", { text: x.time }),
          showRooms ? el("td", { text: String(x.room) }) : null, el("td", { text: x.candidate }), panel,
          r.changes ? el("td", { text: note }) : null].filter(Boolean));
      }));
  };
  filter.addEventListener("input", draw); draw();
  const dl = (label, kind, name) => el("button", { onclick: async () => {
    const o = await call("export", { kind });
    if (!o.ok) { alert(o.error); return; }
    const a = el("a", { href: URL.createObjectURL(new Blob([o.data.csv], { type: "text/csv" })), download: name });
    document.body.append(a); a.click(); a.remove();
  }, text: label });
  card.append(el("div", { class: "tools" }, filter,
    dl("Download schedule (CSV)", "table", "schedule.csv"),
    dl("Download for re-import (CSV)", "prev", "prev_schedule.csv")));
  card.append(el("div", { class: "tablewrap", style: "max-height:480px;overflow:auto" }, el("table", {}, el("thead", {}, head), tbody)));

  const maxLoad = Math.max(1, ...r.staff_load.map((x) => x.interviews));
  card.append(el("h3", { text: "Workload per staff member" }),
    el("div", { class: "tablewrap" }, el("table", {}, el("tbody", {}, r.staff_load.map((x) =>
      el("tr", {}, el("td", { class: x.lead ? "lead" : "", text: x.staff + (x.lead ? " (lead)" : "") }),
        el("td", { text: String(x.interviews) }),
        el("td", {}, el("span", { class: "bar", style: `width:${Math.round(160 * x.interviews / maxLoad)}px` }))))))));
  card.scrollIntoView({ behavior: "smooth", block: "start" });
}

function diagnostics(d) {
  const box = el("div");
  if (d.timeout) {
    box.append(msg("warn", `The solver found no schedule within ${d.time_limit} s. This does not mean there is none: the problem was just not solved in time.`,
      el("ul", {}, [
        el("li", { text: "Raise the time limit (step 2), especially on a phone or a slow computer." }),
        el("li", { text: "Turn off parallel rooms, or lower their number: each extra room multiplies the size of the problem." }),
        el("li", { text: "Count “If needed” answers as available (step 1) to give the solver more room." }),
      ])));
    return box;
  }
  box.append(msg("", `${d.n_candidates} applicants, ${d.slots_with_valid_panel} slots where a valid panel exists` +
    ` (capacity ${d.capacity} interviews with the current room setting).`));
  if (d.no_slot.length) box.append(msg("err", "These applicants cannot be scheduled at all:",
    el("ul", {}, d.no_slot.map((x) => el("li", { text: `${x.candidate} — ${x.reason}` }))),
    el("p", { class: "note", text: "Ask them for more availability, add staff, or relax the panel size." })));
  if (d.tight.length) box.append(msg("warn", "Applicants with very few usable slots (they compete for them): " +
    d.tight.map((x) => `${x.candidate} (${x.usable_slots})`).join(", ")));
  if (d.hint_if_needed && lastLoad) box.append(msg("warn",
    `${d.hint_if_needed} “If needed” answers are currently counted as unavailable. `,
    el("button", { class: "link", text: "Reload counting “If needed” as available", onclick: async () => {
      $("opt-ifneeded").value = "available";
      setBusy(true, "Reloading…");
      await afterLoad(await call("load", { ...lastLoad, if_needed: "available" }));
      setBusy(false, "Solver ready.");
      lastLoad = { ...lastLoad, if_needed: "available" };
    } })));
  if (!d.no_slot.length) box.append(msg("warn",
    "No single applicant is blocked, so the conflict comes from several rules combining (too many applicants for the same slots, " +
    "forbidden pairs, lead availability). Try allowing parallel rooms, adding availability, or fewer constraints."));
  return box;
}

/* ------------------------------------------------------------------ step 3 */
const slotLabel = (t) => t.replace(/\.\d+$/, "");
const CHANGES = {
  staff_day: { label: "Staff unavailable — whole day", fields: ["staff", "date"], key: "staff_unavailable_dates",
    value: (v) => [v.staff, v.date], text: (v) => `${v.staff} unavailable on ${v.date}` },
  staff_slot: { label: "Staff unavailable — one slot", fields: ["staff", "slot"], key: "staff_unavailable",
    value: (v) => [v.staff, v.slot], text: (v) => `${v.staff} unavailable at ${v.slotLabel}` },
  cand_day: { label: "Applicant unavailable — whole day", fields: ["cand", "date"], key: "candidate_unavailable_dates",
    value: (v) => [v.cand, v.date], text: (v) => `${v.cand} unavailable on ${v.date}` },
  cand_slot: { label: "Applicant unavailable — one slot", fields: ["cand", "slot"], key: "candidate_unavailable",
    value: (v) => [v.cand, v.slot], text: (v) => `${v.cand} unavailable at ${v.slotLabel}` },
  rm_cand: { label: "Applicant withdraws", fields: ["cand"], key: "remove_candidate",
    value: (v) => v.cand, text: (v) => `${v.cand} withdraws` },
  add_cand: { label: "New applicant", fields: ["name", "dates"], key: "add_candidate",
    value: (v) => ({ id: v.name, slots: v.slots }), text: (v) => `new applicant ${v.name}` },
  rm_staff: { label: "Staff member leaves", fields: ["staff"], key: "staff_removed",
    value: (v) => v.staff, text: (v) => `${v.staff} leaves` },
  add_staff: { label: "New staff member", fields: ["name", "dates"], key: "staff_added",
    value: (v) => ({ id: v.name, slots: v.slots }), text: (v) => `new staff ${v.name}` },
};

function select(id, options) {
  return el("select", { id }, options.map(([v, t]) => el("option", { value: v, text: t })));
}

function fillChangeForm() {
  const t = $("ch-type");
  if (!t.options.length) {
    for (const [k, c] of Object.entries(CHANGES)) t.append(el("option", { value: k, text: c.label }));
    t.addEventListener("change", drawFields);
  }
  const fz = $("r-freeze");
  fz.replaceChildren(el("option", { value: "", text: "— nothing frozen —" }),
    ...info.dates.map((d) => el("option", { value: d, text: d })));
  drawFields(); drawStaged();
}

function drawFields() {
  const c = CHANGES[$("ch-type").value]; const box = $("ch-fields"); box.replaceChildren();
  for (const f of c.fields) {
    if (f === "staff") box.append(labelled("Staff member", select("f-staff-sel", info.staff.map((s) => [s.id, s.id + (s.lead ? " (lead)" : "")]))));
    if (f === "cand") box.append(labelled("Applicant", select("f-cand-sel", info.candidates.map((x) => [x, x]))));
    if (f === "date") box.append(labelled("Date", select("f-date-sel", info.dates.map((d) => [d, d]))));
    if (f === "slot") box.append(labelled("Time slot", select("f-slot-sel", info.slots.map((s, i) => [s, info.slot_labels[i]]))));
    if (f === "name") box.append(labelled("Name", el("input", { type: "text", id: "f-name", placeholder: "Full name" })));
    if (f === "dates") {
      const sel = el("select", { id: "f-dates", multiple: "multiple", size: "4" },
        info.dates.map((d) => el("option", { value: d, text: d, selected: "selected" })));
      box.append(labelled("Available on (default: all days)", sel));
    }
  }
}
const labelled = (text, input) => el("label", {}, text, input);

$("btn-stage").addEventListener("click", () => {
  const k = $("ch-type").value, c = CHANGES[k];
  const v = {
    staff: $("f-staff-sel") && $("f-staff-sel").value, cand: $("f-cand-sel") && $("f-cand-sel").value,
    date: $("f-date-sel") && $("f-date-sel").value, slot: $("f-slot-sel") && $("f-slot-sel").value,
    name: $("f-name") && $("f-name").value.trim(),
    slotLabel: $("f-slot-sel") && $("f-slot-sel").selectedOptions[0].text,
  };
  if (c.fields.includes("name") && !v.name) { alert("Enter a name."); return; }
  if (c.fields.includes("dates")) {
    const chosen = [...$("f-dates").selectedOptions].map((o) => o.value);
    if (!chosen.length) { alert("Select at least one day."); return; }
    v.slots = chosen.length === info.dates.length ? null : info.slots.filter((s) => chosen.includes(s.split(" ")[0]));
  }
  staged.push({ key: c.key, value: c.value(v), text: c.text(v) });
  drawStaged();
});

function drawStaged() {
  const box = $("staged"); box.replaceChildren();
  if (staged.length) {
    box.append(el("ul", { class: "staged" }, staged.map((s, i) =>
      el("li", {}, s.text, el("button", { class: "link", "aria-label": "Remove", text: "✕",
        onclick: () => { staged.splice(i, 1); drawStaged(); } }))),
      el("li", {}, el("button", { class: "link", text: "clear all", onclick: () => { staged = []; drawStaged(); } }))));
  }
  $("btn-resched").disabled = busy || staged.length === 0;
}

$("btn-resched").addEventListener("click", async () => {
  const changes = {};
  for (const s of staged) (changes[s.key] = changes[s.key] || []).push(s.value);
  setBusy(true, "Rescheduling… (up to the time limit)");
  const out = await call("reschedule", { changes, params: params(), strategy: $("r-strat").value, freeze_date: $("r-freeze").value || null });
  setBusy(false, "Solver ready.");
  const fail = $("resched-fail"); fail.replaceChildren();
  if (out.ok && out.data.result.ok) {
    showResult(out, "Rescheduled");
    staged = []; fillChangeForm();
  } else {
    // keep the previous schedule on screen; explain why the changes could not be absorbed
    showResult(out, "Could not reschedule", fail);
    fail.append(msg("warn", "The staged changes were not applied: the previous schedule is still the reference. " +
      "Adjust the staged changes (or the settings) and try again."));
  }
});
