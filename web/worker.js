/* Web Worker: runs Python (Pyodide) off the UI thread.
 * The CSV text sent here is processed in memory, in this browser tab only. */
const PYODIDE_URL = "https://cdn.jsdelivr.net/pyodide/v0.29.0/full/pyodide.js";
importScripts(PYODIDE_URL);

const say = (msg) => postMessage({ type: "progress", msg });

const ready = (async () => {
  say("Starting Python…");
  const pyodide = await loadPyodide();
  say("Downloading numpy and scipy (first visit only, cached afterwards)…");
  await pyodide.loadPackage(["numpy", "scipy"]);
  say("Loading the scheduler…");
  const res = await fetch("pybundle.zip?v=__BUNDLE_HASH__");
  if (!res.ok) throw new Error("Could not load pybundle.zip (" + res.status + ")");
  pyodide.unpackArchive(await res.arrayBuffer(), "zip", { extractDir: "/pybundle" });
  pyodide.runPython("import sys; sys.path.insert(0, '/pybundle'); import webapi.api as _api");
  const dispatch = pyodide.runPython("_api.dispatch");
  say("");
  postMessage({ type: "ready" });
  return dispatch;
})();
ready.catch((e) => postMessage({ type: "fatal", msg: String(e && e.message || e) }));

onmessage = async (ev) => {
  const { id, method, payload } = ev.data;
  try {
    const dispatch = await ready;
    const out = dispatch(method, JSON.stringify(payload || {}));
    postMessage({ type: "result", id, result: JSON.parse(out) });
  } catch (e) {
    postMessage({ type: "result", id, result: { ok: false, error: String(e && e.message || e) } });
  }
};
