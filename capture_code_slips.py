"""Use Playwright to generate codes and capture the PDF via session."""
import time
import fitz
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5000"
OUT = "screenshots"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()

        # Login
        page.goto(f"{BASE}/admin/login")
        page.wait_for_load_state("networkidle")
        page.fill('input[name="password"]', 'council2026')
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle")

        # Go to codes tab
        page.goto(f"{BASE}/admin/election/1/codes")
        page.wait_for_load_state("networkidle")

        # Delete existing codes if any
        del_btn = page.locator('button:has-text("Delete All Codes")')
        if del_btn.count() > 0:
            page.on("dialog", lambda d: d.accept())
            del_btn.click()
            page.wait_for_load_state("networkidle")
            print("Deleted existing codes")

        # Generate new codes
        count_input = page.locator('input[name="count"]')
        if count_input.count() > 0:
            count_input.fill("20")
            page.click('button:has-text("Generate")')
            page.wait_for_load_state("networkidle")
            print("Generated 20 codes")

        # Now try to get the PDF via JavaScript fetch (shares session cookies)
        pdf_data = page.evaluate("""async () => {
            const resp = await fetch('/admin/election/1/codes/pdf');
            const ct = resp.headers.get('content-type');
            if (!ct || !ct.includes('pdf')) return null;
            const buf = await resp.arrayBuffer();
            const bytes = new Uint8Array(buf);
            let binary = '';
            for (let i = 0; i < bytes.length; i++) {
                binary += String.fromCharCode(bytes[i]);
            }
            return btoa(binary);
        }""")

        if pdf_data:
            import base64
            pdf_bytes = base64.b64decode(pdf_data)
            with open(f"{OUT}/code_slips.pdf", "wb") as f:
                f.write(pdf_bytes)
            doc = fitz.open(f"{OUT}/code_slips.pdf")
            pg = doc[0]
            pix = pg.get_pixmap(dpi=200)
            pix.save(f"{OUT}/23_code_slips.png")
            doc.close()
            print(f"  -> 23_code_slips.png ({pix.width}x{pix.height})")
        else:
            print("PDF not available (codes may have expired from session)")

        browser.close()


if __name__ == "__main__":
    main()
