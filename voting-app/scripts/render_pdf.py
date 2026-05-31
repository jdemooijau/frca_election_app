"""Render a local HTML file to PDF via headless Chromium.

Used to produce the doc PDFs in voting-app/docs/ (e.g. FAQ.pdf) from a
committed HTML source. Chromium preserves <a href> links as clickable
PDF link annotations and honours CSS paged-media (@page size/margins),
which ReportLab-drawn PDFs do not give us for free.

Usage:
    python scripts/render_pdf.py docs/FAQ.html docs/FAQ.pdf

The renderer tries Playwright's bundled Chromium first, then falls back
to the system Chrome / Edge install via Playwright channels. preferCSSPageSize
makes the @page rule in the HTML drive the page size and margins.
"""

import sys
from pathlib import Path


def render(html_path: Path, pdf_path: Path) -> None:
    from playwright.sync_api import sync_playwright

    file_url = html_path.resolve().as_uri()

    # Try the bundled Chromium first, then channels for system browsers.
    # Any of these produces identical clickable-link output.
    attempts = [
        {},
        {"channel": "chrome"},
        {"channel": "msedge"},
    ]

    last_err = None
    with sync_playwright() as p:
        browser = None
        for opts in attempts:
            try:
                browser = p.chromium.launch(headless=True, **opts)
                break
            except Exception as err:  # noqa: BLE001 - want the next fallback
                last_err = err
        if browser is None:
            raise RuntimeError(
                f"Could not launch Chromium/Chrome/Edge: {last_err}"
            )

        page = browser.new_page()
        page.goto(file_url, wait_until="networkidle")
        page.pdf(
            path=str(pdf_path),
            prefer_css_page_size=True,  # honour @page size/margin in the HTML
            print_background=True,
        )
        browser.close()


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    html_path = Path(sys.argv[1])
    pdf_path = Path(sys.argv[2])
    if not html_path.is_file():
        print(f"HTML source not found: {html_path}")
        return 1
    render(html_path, pdf_path)
    print(f"Rendered {pdf_path} from {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
