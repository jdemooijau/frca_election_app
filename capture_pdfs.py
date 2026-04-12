"""Download PDFs via requests, render first page with PyMuPDF."""
import requests
import fitz  # PyMuPDF

BASE = "http://localhost:5000"
OUT = "screenshots"

# Login and get session cookie
session = requests.Session()

# Get CSRF token
resp = session.get(f"{BASE}/admin/login")
import re
csrf = re.search(r'name="csrf_token" value="([^"]+)"', resp.text).group(1)

# Login
session.post(f"{BASE}/admin/login", data={"csrf_token": csrf, "password": "council2026"})

# Download code slips PDF
print("Downloading code slips PDF...")
resp = session.get(f"{BASE}/admin/election/1/codes/pdf")
print(f"  Status: {resp.status_code}, Content-Type: {resp.headers.get('content-type', 'unknown')}")

if resp.status_code == 200 and b"%PDF" in resp.content[:10]:
    with open(f"{OUT}/code_slips.pdf", "wb") as f:
        f.write(resp.content)
    # Render first page
    doc = fitz.open(f"{OUT}/code_slips.pdf")
    page = doc[0]
    pix = page.get_pixmap(dpi=200)
    pix.save(f"{OUT}/23_code_slips.png")
    doc.close()
    print(f"  -> 23_code_slips.png ({pix.width}x{pix.height})")
else:
    print(f"  Failed: {resp.text[:200]}")

# Download paper ballot PDF
print("Downloading paper ballot PDF...")
resp = session.get(f"{BASE}/admin/election/1/paper-ballot-pdf/1")
print(f"  Status: {resp.status_code}, Content-Type: {resp.headers.get('content-type', 'unknown')}")

if resp.status_code == 200 and b"%PDF" in resp.content[:10]:
    with open(f"{OUT}/paper_ballot.pdf", "wb") as f:
        f.write(resp.content)
    doc = fitz.open(f"{OUT}/paper_ballot.pdf")
    page = doc[0]
    pix = page.get_pixmap(dpi=200)
    pix.save(f"{OUT}/24_paper_ballot.png")
    doc.close()
    print(f"  -> 24_paper_ballot.png ({pix.width}x{pix.height})")
else:
    print(f"  Failed: {resp.text[:200]}")

print("Done!")
