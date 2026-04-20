# Running the Demo at a Council Meeting

This app includes a demo mode that populates a complete practice election with
fictional Dutch candidate names. The demo is tailored to the Free Reformed
Church of Darling Downs and can be run at a council proposal meeting to show
the app in action.

> **Before following these instructions, please read the disclaimer in the main
> README. You are fully responsible for correct setup and operation.**

## What demo mode does

- Loads a ready-to-run practice election with 4 elder candidates and 4 deacon candidates
- Uses fictional Dutch candidate names generated from (but not matching) the real member database
- Displays a bright yellow banner on every page: "DEMO MODE — Practice election with fictional candidates"
- Adds a "DEMO" watermark to all generated PDFs
- Accepts any voting code (even invalid or blank ones) with a non-blocking notice, so council members can try the app without getting stuck on typos
- Offers a special Dual Ballot Handout PDF that shows both paper and online voting options on a single sheet
- Can be completely reset with one command after the meeting

## Before the meeting

1. Open a terminal in the `voting-app` directory
2. Run the seed script:
   ```bash
   python scripts/seed_demo.py
   ```
3. Type `YES` when prompted
4. Review the generated candidate names on the console
5. Print or email `docs/COUNCIL_PROPOSAL.md` to council members as a pre-read.
   This is a one-page summary of the proposal that explains what will be
   presented and reminds them to bring a smartphone to the meeting so they
   can try the live demonstration.
6. Start the app:
   ```bash
   ./run.sh    # Linux/Mac
   start.bat   # Windows
   ```
7. Open the admin page in a browser and log in
8. Click "Download Dual Ballot Handout PDF" and print 20+ copies on plain A4
9. Print `demo_code_slips.pdf` (cut into individual slips)
10. Set up the GL.iNet Flint 2 router and confirm the laptop has IP 192.168.8.100
11. Right-click `captive-portal-on.bat` → Run as administrator (enables port forwarding for captive portal)
12. Open the projector display page (`/display`) on a second device connected to the projector

## At the meeting

1. Present the proposal
2. Hand out one Dual Ballot Handout page per council member
3. Explain briefly: "Each sheet shows both voting options. You only need to choose one."
4. Invite council members to connect to the ChurchVote WiFi and try voting on their phones
5. Show the projector display updating in real time
6. Optionally reveal the vote counts on the projector toward the end
7. Run a second round if any council member wants to see how that works
8. Answer any questions with the app live in front of them

## Loading the demo from the admin page

You can also load the demo directly from the admin interface, without using the
command line:

1. Go to the admin dashboard
2. Click "Advanced Actions"
3. Click "Load Demo Election"
4. Type `LOAD DEMO` in the confirmation box
5. Re-enter the admin password
6. The demo is loaded, and download links for the PDFs appear

## Forgiving code entry in demo mode

While the app is in demo mode:

- Any 6-character code will be accepted (even invalid or unused ones)
- A blank code will also be accepted
- The app assigns a fresh code automatically and shows a small notice

This means council members can play with the app freely without getting stuck
on typos. A notice on the ballot page explains what happened.

In production mode (demo flag off), code entry is strict and all validation
rules apply normally.

## After the meeting

1. Stop the app (Ctrl+C in the terminal)
2. Run the reset script:
   ```bash
   python scripts/reset_app.py
   ```
3. Type `YES` when prompted
4. The app is now reset and ready for the real 2026 election setup

Or, while the app is still running, you can click "Exit Demo and Reset" in the
admin Advanced Actions section.

## Dual ballot handout

The Dual Ballot Handout PDF is a special document designed for proposal
meetings. Each page contains:

- **Top half:** A traditional paper ballot with checkboxes for the 4 elder
  candidates and 4 deacon candidates
- **Bottom half:** An online code ballot with a QR code, a printed 6-character
  code, WiFi instructions, and a fallback URL
- **Explanation:** That the council member only needs to choose one method

This lets each council member hold both options in their hand and see that the
two methods coexist seamlessly. It is much more persuasive than a written
proposal alone.

Generate it from the admin dashboard after loading the demo:

- Click "Download Dual Ballot Handout PDF"
- Print on plain A4 paper
- Hand out one page per council member at the meeting
- No cutting required — each page is a complete handout
