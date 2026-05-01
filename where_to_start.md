# Where to Start

This page is a signpost. It points you at the right document based on who you
are and what you want to do. Start here, then follow the link.

Before you go anywhere else, please read the disclaimer at the top of
[README.md](README.md). This software is shared freely, with no warranty and
no support. The responsibility for running your congregation's election
correctly rests entirely with your council.

## I am on the church council and want to understand what this is

You are deciding whether to consider this tool for your congregation's
elections. You do not need to install anything yet.

1. [README.md](README.md) — What the app is and what it is not.
2. [voting-app/docs/COUNCIL_PROPOSAL.md](voting-app/docs/COUNCIL_PROPOSAL.md) — One-page proposal summary for a council meeting.
3. [voting-app/docs/CONGREGATION_GUIDE.md](voting-app/docs/CONGREGATION_GUIDE.md) — What the experience looks like for members on election day.
4. [voting-app/docs/CHURCH_ORDER_NOTES.md](voting-app/docs/CHURCH_ORDER_NOTES.md) — How the app lines up with FRCA Church Order and the Rules for the Election of Office Bearers.
5. [voting-app/docs/SECURITY.md](voting-app/docs/SECURITY.md) — The security and anonymity model.

## I am the technical volunteer who would set this up for my congregation

You are comfortable with Python, a command line, and a home WiFi router, and
you are willing to take responsibility for making this work on election day.

1. [README.md](README.md) — Quick start and project layout.
2. [voting-app/docs/SETUP.md](voting-app/docs/SETUP.md) — Laptop and router setup. The captive-portal section is optional.
3. [voting-app/docs/CONFIGURATION.md](voting-app/docs/CONFIGURATION.md) — First-time setup wizard for your congregation.
4. [voting-app/docs/COMPATIBILITY_TEST.md](voting-app/docs/COMPATIBILITY_TEST.md) — Device testing checklist.
5. [voting-app/docs/UAT_SCRIPT.md](voting-app/docs/UAT_SCRIPT.md) — Dry-run script to walk the council through before the real election.

## I am running the election on the day

You are the admin sitting at the laptop during the meeting.

1. [voting-app/docs/ADMIN_GUIDE.md](voting-app/docs/ADMIN_GUIDE.md) — End-to-end walk-through of running an election.
2. [voting-app/docs/USER_GUIDE.md](voting-app/docs/USER_GUIDE.md) — Screenshot-driven walkthrough of every admin screen.
3. [voting-app/docs/FAILSAFE.md](voting-app/docs/FAILSAFE.md) — What to do when something goes wrong. Keep this printed and next to the laptop.

## I want to demo this at a council meeting

The app has a built-in demo mode with fictional candidates, a yellow banner,
and forgiving code entry so council members can play with it without breaking
anything.

1. [voting-app/docs/DEMO.md](voting-app/docs/DEMO.md) — How to prepare and run the demo.
2. [voting-app/docs/COUNCIL_PROPOSAL.md](voting-app/docs/COUNCIL_PROPOSAL.md) — One-page handout for the meeting.

## I want to read or modify the source code

1. [README.md](README.md) — Project layout.
2. [voting-app/app.py](voting-app/app.py) — The Flask app. All routes live here.
3. [voting-app/tests/](voting-app/tests/) — Unit and scenario tests. Run them with `pytest`.

## Contact

There is no help desk or support contract. If you have a question, a bug
report, or a suggestion, you are welcome to contact the author:

**Jan de Mooij**

Responses are not guaranteed and there is no commitment to act on any
request. Please do not rely on a reply in time for an imminent election.
