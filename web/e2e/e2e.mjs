// End-to-end test of the static site in headless Chrome.
//   python web/build.py && python -m http.server -d site 8765 &
//   cd web/e2e && npm install && node e2e.mjs        (CHROME=/path/to/chrome to override)
import puppeteer from "puppeteer-core";
const browser = await puppeteer.launch({ executablePath: process.env.CHROME || "/usr/bin/google-chrome", headless: "new", args: ["--no-sandbox"] });
const page = await browser.newPage(); await page.setViewport({ width: 1200, height: 900 });
const errors = []; page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
const reqs = []; page.on("request", (r) => reqs.push(r.method() + " " + r.url()));
const t0 = Date.now(); const lap = (m) => console.log(`[${((Date.now()-t0)/1000).toFixed(1)}s] ${m}`);
const text = (sel) => page.$eval(sel, (e) => e.textContent);
await page.setViewport({ width: 1200, height: 900 });
await page.goto("http://localhost:8765/index.html");
await page.waitForSelector("#engine.ready", { timeout: 240000 }); lap("engine ready: " + await text("#engine-msg"));
await page.click("#btn-example"); await page.waitForSelector("#load-msg .msg"); lap("load: " + (await text("#load-msg")).slice(0, 160));
await page.click("#btn-solve");
await page.waitForSelector("#results table tbody tr", { timeout: 240000 });
lap("solved: " + (await text("#results .stats")).slice(0, 170));
console.log("rows:", await page.$$eval("#results table:first-of-type tbody tr", (r) => r.length));
await page.screenshot({ path: "shot1.png" });
// cancel a panel member of the very first interview, for that whole day (a meaningful change)
const first = await page.$eval("#results table:first-of-type tbody tr", (tr) => [...tr.children].map((td) => td.textContent));
const victim = first[3].split(" + ").pop().replace(/\(lead\)/, "").trim(); lap(`first interview: ${first.join(" | ")} -> cancelling ${victim} on ${first[0]}`);
await page.select("#ch-type", "staff_day");
await page.select("#f-staff-sel", victim); await page.select("#f-date-sel", first[0]);
await page.click("#btn-stage"); lap("staged: " + await text("#staged"));
await page.click("#btn-resched");
await page.waitForFunction(() => document.querySelector("#results h2")?.textContent.includes("Rescheduled") || document.querySelector("#resched-fail h2"), { timeout: 240000 });
lap("after reschedule: " + (await text("#results .stats")).slice(0, 220));
await page.screenshot({ path: "shot2.png", fullPage: true });
await page.select("#ch-type", "add_cand"); await page.type("#f-name", "Late Applicant"); await page.click("#btn-stage");
await page.select("#ch-type", "rm_cand");
const cands = await page.$$eval("#f-cand-sel option", (o) => o.map((x) => x.value)); await page.select("#f-cand-sel", cands[2]); await page.click("#btn-stage");
lap("staged 2: " + await text("#staged"));
await page.click("#btn-resched");
await page.waitForFunction(() => /new/.test(document.querySelector("#results .stats")?.textContent || "") && /Late Applicant/.test(document.querySelector("#results")?.textContent || ""), { timeout: 240000 });
lap("after 2nd reschedule: " + (await text("#results .stats")).slice(0, 220));
// export button works (CSV text produced by the Python side)
const csvOk = await page.evaluate(async () => { const b = [...document.querySelectorAll("button")].find((x) => x.textContent.startsWith("Download schedule")); return !!b; });
const external = reqs.filter((u) => !/localhost:8765|cdn\.jsdelivr\.net/.test(u) && !/ data:| blob:/.test(" " + u));
console.log("download button present:", csvOk);
console.log("requests:", reqs.length, "| non-GET (uploads):", reqs.filter((u) => !u.startsWith("GET")).length, "| hosts other than localhost/jsdelivr:", external.length, external.slice(0, 3));
console.log("console errors:", errors.length, errors.slice(0, 3));
await browser.close();
