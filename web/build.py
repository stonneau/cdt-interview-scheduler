"""Build the static site into ``site/``: the page, the worker and ``pybundle.zip``.

    python web/build.py          # then: python -m http.server -d site 8000

``pybundle.zip`` holds the pure-Python packages Pyodide imports in the browser
(scheduler, data_models, webapi): no OR-Tools, no pandas.
"""

import hashlib
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
OUT = ROOT / "site"
PACKAGES = ["scheduler", "data_models", "webapi"]
EXCLUDE = {"utils.py"}   # data_models/utils.py needs pandas and is not used by the solver


def main():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir()

    bundle = OUT / "pybundle.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as z:
        for pkg in PACKAGES:
            for f in sorted((ROOT / pkg).rglob("*.py")):
                if f.name in EXCLUDE or "__pycache__" in f.parts:
                    continue
                z.write(f, f.relative_to(ROOT).as_posix())
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()[:10]

    for name in ["index.html", "style.css", "app.js"]:
        shutil.copy(WEB / name, OUT / name)
    worker = (WEB / "worker.js").read_text().replace("__BUNDLE_HASH__", digest)
    (OUT / "worker.js").write_text(worker)
    (OUT / ".nojekyll").write_text("")
    print(f"Built {OUT} (pybundle {bundle.stat().st_size // 1024} KiB, hash {digest})")


if __name__ == "__main__":
    main()
