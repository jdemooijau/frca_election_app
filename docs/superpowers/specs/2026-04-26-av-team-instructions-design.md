# AV Team Instructions Sheet — Design

## Purpose

Add a one-page A4 PDF (`av_instructions.pdf`) to the printer pack zip. The
admin prints it with the ballots and hands it to whoever runs the liturgy
screen on election day. The sheet tells them how to get the `/display` page
onto the screen from the AV booth PC.

## Scope

- Assumes connection model (a): the AV booth has its own PC. The AV person
  connects that PC to the election WiFi and opens the display URL in Chrome.
- Pre-fills WiFi SSID, WiFi password, and the configured `voting_base_url`
  from the existing zip-generation context.
- Plain tone. Simple text-and-headings layout matching the other zip PDFs
  (Navy title, A4, ReportLab `SimpleDocTemplate`).

## Content

Title: "Liturgy Screen Setup — Office Bearer Election"

One short intro sentence, then five numbered sections:

1. Connect the AV PC to the election WiFi (SSID + password, note that it is
   internet-free and the PC stays on it for the meeting).
2. Open the display page in Chrome (URL = `{base_url}/display`; fallback note
   that the admin can give a numeric IP if the URL doesn't load).
3. Make it fill the screen (F11 fullscreen; Ctrl + / Ctrl - to zoom; Ctrl 0
   resets to 100%; designed for 16:9).
4. Leave it alone for the rest of the meeting (auto-advances through phases,
   refreshes itself).
5. If the page goes blank or freezes (F5 to refresh; check WiFi; ask admin).

Footer: "Questions on the day → election admin at the laptop in the hall."

## Implementation outline

- New function `generate_av_instructions_pdf(wifi_ssid, wifi_password, base_url)`
  in `voting-app/pdf_generators.py`, modeled on
  `generate_attendance_register_pdf` for style.
- Wire it into `generate_printer_pack_zip` so the new PDF is added as
  `av_instructions.pdf`.
- Add a one-line entry for it in the existing `INSTRUCTIONS.txt` block so the
  printer knows what the file is and that it is for the admin (not for them
  to act on).
- No new settings, routes, or DB changes.

## Out of scope

- Connection model (b): AV plugs into the admin laptop via HDMI directly.
- A separate doc for `/displayphone`.
- Screensaver / sleep guidance (AV teams handle this routinely).
