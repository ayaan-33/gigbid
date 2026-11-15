"""Build docs/report/GigBid_RD_Report.pdf from docs/report/REPORT.md (+ generated tables) using
Playwright's Chromium (print to PDF, A4). Usage: uv run python -m scripts.build_report"""

from __future__ import annotations

import subprocess
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "docs" / "report" / "REPORT.md"
HTML = ROOT / "docs" / "report" / "report.html"
PDF = ROOT / "docs" / "report" / "GigBid_RD_Report.pdf"

CSS = """
@page { size: A4; margin: 16mm 15mm 16mm 15mm; }
body { font-family: -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif; font-size: 9.6pt; line-height: 1.38; color: #111; }
h1 { font-size: 17pt; margin: 0 0 4pt; } h2 { font-size: 12.5pt; margin: 12pt 0 4pt; border-bottom: 1px solid #ccc; padding-bottom: 2pt; }
h3 { font-size: 10.5pt; margin: 8pt 0 3pt; } p { margin: 3pt 0 5pt; } ul, ol { margin: 2pt 0 5pt 16pt; padding: 0; } li { margin: 1pt 0; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0 8pt; font-size: 8.4pt; page-break-inside: avoid; }
th, td { border: 1px solid #bbb; padding: 2pt 4pt; text-align: left; vertical-align: top; } th { background: #f0f0f0; }
code { font-family: Menlo, Consolas, monospace; font-size: 8.4pt; background: #f4f4f4; padding: 0 2px; }
pre { background: #f4f4f4; padding: 5pt; font-size: 8pt; white-space: pre-wrap; } blockquote { margin: 4pt 0; padding-left: 8pt; border-left: 3px solid #ccc; color: #444; }
.appendix { page-break-before: always; }
"""


def main() -> None:
    md = SRC.read_text()
    tables = (ROOT / "docs" / "results_tables.md").read_text().split("\n", 2)[-1]
    md = md.replace("{{TABLES}}", tables)
    from scripts.make_readme_tables import fill
    md = fill(md)
    body = markdown.markdown(md, extensions=["tables", "fenced_code", "sane_lists"])
    body = body.replace("<h2>Appendix", '<h2 class="appendix">Appendix')
    HTML.write_text(f"<!doctype html><html><head><meta charset='utf-8'><title>GigBid R&D report</title><style>{CSS}</style></head><body>{body}</body></html>")
    code = f"""
const {{ chromium }} = require('@playwright/test');
(async () => {{
  const b = await chromium.launch(); const p = await b.newPage();
  await p.goto('file://{HTML}'); await p.pdf({{ path: '{PDF}', format: 'A4', printBackground: true,
    displayHeaderFooter: true, headerTemplate: '<span></span>',
    footerTemplate: '<div style="font-size:7pt;width:100%;text-align:center;color:#666">GigBid R&D report · <span class="pageNumber"></span>/<span class="totalPages"></span></div>',
    margin: {{ top: '14mm', bottom: '16mm', left: '14mm', right: '14mm' }} }});
  await b.close();
}})();"""
    subprocess.run(["node", "-e", code], cwd=ROOT / "apps" / "web", check=True)
    print("wrote", PDF)


if __name__ == "__main__":
    main()
