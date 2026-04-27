const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const SHOTS = "screenshots";
const OUT = "voting-app/docs/FRCA_Election_App_Training.pptx";

// Color palette — Navy & Gold (matching the app)
const NAVY = "1A3353";
const GOLD = "D4A843";
const WHITE = "FFFFFF";
const LIGHT = "F5F6FA";
const DARK_TEXT = "2C3E50";
const MID_TEXT = "5D6D7E";

// Font pairing
const HEADER_FONT = "Georgia";
const BODY_FONT = "Calibri";

function imgPath(name) {
  return path.resolve(SHOTS, name);
}

function imgData(name) {
  const buf = fs.readFileSync(imgPath(name));
  return "image/png;base64," + buf.toString("base64");
}

async function main() {
  let pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "FRCA Election App";
  pres.title = "FRCA Election App — Training Guide";

  // ================================================================
  // SLIDE 1: Title
  // ================================================================
  let s1 = pres.addSlide();
  s1.background = { color: NAVY };

  // Gold accent bar at top
  s1.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: GOLD }
  });

  s1.addText("FRCA Election App", {
    x: 0.8, y: 1.2, w: 8.4, h: 1.2,
    fontSize: 44, fontFace: HEADER_FONT, color: GOLD,
    bold: true
  });

  s1.addText("Training Guide for Consistory", {
    x: 0.8, y: 2.3, w: 8.4, h: 0.7,
    fontSize: 22, fontFace: BODY_FONT, color: WHITE
  });

  s1.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 3.3, w: 2, h: 0.04, fill: { color: GOLD }
  });

  s1.addText("Office Bearer Elections for Free Reformed Churches", {
    x: 0.8, y: 3.7, w: 8, h: 0.5,
    fontSize: 14, fontFace: BODY_FONT, color: MID_TEXT, italic: true
  });

  // ================================================================
  // SLIDE 2: What is it?
  // ================================================================
  let s2 = pres.addSlide();
  s2.background = { color: WHITE };

  s2.addText("What is the Election App?", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });

  s2.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  const features = [
    { title: "Offline & Local", desc: "Runs on one laptop over church WiFi. No internet needed." },
    { title: "Phone Voting", desc: "Brothers vote on their own phones using unique one-time codes." },
    { title: "Paper + Digital", desc: "Paper ballots counted alongside digital votes." },
    { title: "Rules Compliant", desc: "Article 2, 6, 7 & 11 thresholds calculated automatically." },
  ];

  features.forEach((f, i) => {
    const y = 1.6 + i * 0.95;
    // Number circle
    s2.addShape(pres.shapes.OVAL, {
      x: 0.8, y: y, w: 0.5, h: 0.5,
      fill: { color: NAVY }
    });
    s2.addText(String(i + 1), {
      x: 0.8, y: y, w: 0.5, h: 0.5,
      fontSize: 16, fontFace: BODY_FONT, color: WHITE,
      align: "center", valign: "middle", bold: true
    });
    s2.addText(f.title, {
      x: 1.5, y: y - 0.05, w: 7.5, h: 0.35,
      fontSize: 18, fontFace: BODY_FONT, color: NAVY, bold: true
    });
    s2.addText(f.desc, {
      x: 1.5, y: y + 0.28, w: 7.5, h: 0.35,
      fontSize: 14, fontFace: BODY_FONT, color: MID_TEXT
    });
  });

  // ================================================================
  // SLIDE 3: How It Works — Overview
  // ================================================================
  let s3 = pres.addSlide();
  s3.background = { color: LIGHT };

  s3.addText("How It Works", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s3.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  const steps = [
    { num: "1", label: "SETUP", desc: "Create election,\nadd offices &\ncandidates" },
    { num: "2", label: "CODES", desc: "Generate & print\nvoting code slips" },
    { num: "3", label: "VOTE", desc: "Brothers enter code\non phone & select\ncandidates" },
    { num: "4", label: "COUNT", desc: "Close voting, add\npaper ballots,\nview results" },
  ];

  steps.forEach((st, i) => {
    const x = 0.5 + i * 2.4;
    // Card background
    s3.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x, y: 1.5, w: 2.1, h: 3.2,
      fill: { color: WHITE }, rectRadius: 0.1,
      shadow: { type: "outer", color: "000000", blur: 4, offset: 2, angle: 135, opacity: 0.1 }
    });
    // Number
    s3.addShape(pres.shapes.OVAL, {
      x: x + 0.7, y: 1.8, w: 0.7, h: 0.7,
      fill: { color: GOLD }
    });
    s3.addText(st.num, {
      x: x + 0.7, y: 1.8, w: 0.7, h: 0.7,
      fontSize: 24, fontFace: BODY_FONT, color: NAVY,
      align: "center", valign: "middle", bold: true
    });
    // Label
    s3.addText(st.label, {
      x: x, y: 2.7, w: 2.1, h: 0.5,
      fontSize: 16, fontFace: BODY_FONT, color: NAVY,
      align: "center", bold: true, charSpacing: 2
    });
    // Description
    s3.addText(st.desc, {
      x: x + 0.15, y: 3.2, w: 1.8, h: 1.2,
      fontSize: 12, fontFace: BODY_FONT, color: MID_TEXT,
      align: "center", valign: "top"
    });

    // Arrow between cards
    if (i < 3) {
      s3.addText("\u2192", {
        x: x + 2.1, y: 2.7, w: 0.3, h: 0.5,
        fontSize: 20, color: GOLD, align: "center", valign: "middle"
      });
    }
  });

  // ================================================================
  // SLIDE 4: Admin Login & Setup
  // ================================================================
  let s4 = pres.addSlide();
  s4.background = { color: WHITE };

  s4.addText("Step 1: First-Time Setup", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s4.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  // Left: text
  s4.addText([
    { text: "Open the admin panel and complete the\nsetup wizard:\n\n", options: { fontSize: 14, color: DARK_TEXT } },
    { text: "\u2022  Congregation name\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  WiFi network name (SSID)\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  New admin password\n\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "This only needs to be done once.", options: { fontSize: 13, color: MID_TEXT, italic: true } },
  ], {
    x: 0.8, y: 1.4, w: 4.2, h: 3.5,
    fontFace: BODY_FONT, valign: "top"
  });

  // Right: screenshot
  s4.addImage({
    data: imgData("04_setup_wizard_filled.png"),
    x: 5.3, y: 1.3, w: 4.2, h: 3.8,
    sizing: { type: "contain", w: 4.2, h: 3.8 }
  });

  // ================================================================
  // SLIDE 5: Create Election
  // ================================================================
  let s5 = pres.addSlide();
  s5.background = { color: LIGHT };

  s5.addText("Step 2: Create an Election", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s5.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  s5.addImage({
    data: imgData("06_create_election.png"),
    x: 0.5, y: 1.4, w: 4.5, h: 3.5,
    sizing: { type: "contain", w: 4.5, h: 3.5 }
  });

  s5.addText([
    { text: "From the dashboard, click \u201c+ New Election\u201d.\n\n", options: { fontSize: 14, color: DARK_TEXT } },
    { text: "Enter:\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  Election name\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  Maximum rounds (typically 2\u20133)\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  Election date\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
  ], {
    x: 5.3, y: 1.5, w: 4.2, h: 3.5,
    fontFace: BODY_FONT, valign: "top"
  });

  // ================================================================
  // SLIDE 6: Offices & Candidates
  // ================================================================
  let s6 = pres.addSlide();
  s6.background = { color: WHITE };

  s6.addText("Step 3: Add Offices & Candidates", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s6.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  s6.addText([
    { text: "For each office (Elder, Deacon):\n\n", options: { fontSize: 14, color: DARK_TEXT } },
    { text: "\u2022  Set the number of vacancies\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  Add candidates by typing names\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  Click \u201cAdd Office\u201d\n\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "Article 2: ", options: { fontSize: 13, color: NAVY, bold: true } },
    { text: "The slate must be exactly\ntwice the vacancies. The app enforces this.", options: { fontSize: 13, color: MID_TEXT, italic: true } },
  ], {
    x: 0.8, y: 1.4, w: 4.2, h: 3.5,
    fontFace: BODY_FONT, valign: "top"
  });

  s6.addImage({
    data: imgData("09_election_setup_complete.png"),
    x: 5.3, y: 1.3, w: 4.2, h: 3.8,
    sizing: { type: "contain", w: 4.2, h: 3.8 }
  });

  // ================================================================
  // SLIDE 7: Generate Codes
  // ================================================================
  let s7 = pres.addSlide();
  s7.background = { color: LIGHT };

  s7.addText("Step 4: Generate & Print Codes", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s7.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  s7.addImage({
    data: imgData("10_codes_generated.png"),
    x: 0.5, y: 1.4, w: 5, h: 3.8,
    sizing: { type: "contain", w: 5, h: 3.8 }
  });

  s7.addText([
    { text: "Generate enough codes for all brothers\nplus some spares.\n\n", options: { fontSize: 14, color: DARK_TEXT } },
    { text: "Then download and print:\n\n", options: { fontSize: 14, color: DARK_TEXT } },
    { text: "\u2022  Code Slips PDF", options: { fontSize: 14, color: DARK_TEXT, bold: true } },
    { text: " \u2014 individual\n   slips with QR codes for each brother\n\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  Paper Ballot PDF", options: { fontSize: 14, color: DARK_TEXT, bold: true } },
    { text: " \u2014 for brothers\n   who prefer to vote on paper\n\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "Each code can only be used once.", options: { fontSize: 13, color: MID_TEXT, italic: true } },
  ], {
    x: 5.6, y: 1.5, w: 3.9, h: 3.8,
    fontFace: BODY_FONT, valign: "top"
  });

  // ================================================================
  // SLIDE 7b: Printable Materials
  // ================================================================
  let s7b = pres.addSlide();
  s7b.background = { color: WHITE };

  s7b.addText("What Gets Printed", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s7b.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  // Code slips (left)
  s7b.addText("Code Slips", {
    x: 0.5, y: 1.4, w: 4.5, h: 0.4,
    fontSize: 18, fontFace: BODY_FONT, color: NAVY, bold: true, align: "center"
  });
  s7b.addText("Each brother receives one slip with a unique\n6-character code and QR code.", {
    x: 0.5, y: 1.75, w: 4.5, h: 0.5,
    fontSize: 12, fontFace: BODY_FONT, color: MID_TEXT, align: "center"
  });
  s7b.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.7, y: 2.35, w: 4.1, h: 3.0,
    fill: { color: LIGHT }, rectRadius: 0.08,
    shadow: { type: "outer", color: "000000", blur: 4, offset: 2, angle: 135, opacity: 0.08 }
  });
  s7b.addImage({
    data: imgData("23_code_slips.png"),
    x: 0.8, y: 2.45, w: 3.9, h: 2.8,
    sizing: { type: "contain", w: 3.9, h: 2.8 }
  });

  // Paper ballot (right)
  s7b.addText("Paper Ballots", {
    x: 5.0, y: 1.4, w: 4.5, h: 0.4,
    fontSize: 18, fontFace: BODY_FONT, color: NAVY, bold: true, align: "center"
  });
  s7b.addText("For brothers who prefer paper.\nCounted alongside digital votes.", {
    x: 5.0, y: 1.75, w: 4.5, h: 0.5,
    fontSize: 12, fontFace: BODY_FONT, color: MID_TEXT, align: "center"
  });
  s7b.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.2, y: 2.35, w: 4.1, h: 3.0,
    fill: { color: LIGHT }, rectRadius: 0.08,
    shadow: { type: "outer", color: "000000", blur: 4, offset: 2, angle: 135, opacity: 0.08 }
  });
  s7b.addImage({
    data: imgData("24_paper_ballot.png"),
    x: 5.3, y: 2.45, w: 3.9, h: 2.8,
    sizing: { type: "contain", w: 3.9, h: 2.8 }
  });

  // ================================================================
  // SLIDE 8: Election Day — Voter Experience
  // ================================================================
  let s8 = pres.addSlide();
  s8.background = { color: NAVY };

  s8.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: GOLD }
  });

  s8.addText("Election Day: How Brothers Vote", {
    x: 0.8, y: 0.3, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: GOLD, bold: true
  });

  // Three phone screenshots side by side
  const voterScreens = [
    { img: "13_voter_enter_code.png", label: "1. Enter Code", desc: "Type the 6-character\ncode from their slip" },
    { img: "15_voter_ballot.png", label: "2. Cast Vote", desc: "Select candidates\nfor each office" },
    { img: "17_voter_confirmation.png", label: "3. Confirmed", desc: "Vote submitted.\nCode is burned." },
  ];

  voterScreens.forEach((vs, i) => {
    const x = 0.5 + i * 3.2;
    // Phone frame
    s8.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x + 0.35, y: 1.3, w: 2.2, h: 3.4,
      fill: { color: "2A4A6B" }, rectRadius: 0.15
    });
    s8.addImage({
      data: imgData(vs.img),
      x: x + 0.45, y: 1.4, w: 2.0, h: 3.2,
      sizing: { type: "contain", w: 2.0, h: 3.2 }
    });
    s8.addText(vs.label, {
      x: x, y: 4.8, w: 2.9, h: 0.35,
      fontSize: 15, fontFace: BODY_FONT, color: GOLD,
      align: "center", bold: true
    });
    s8.addText(vs.desc, {
      x: x, y: 5.1, w: 2.9, h: 0.5,
      fontSize: 11, fontFace: BODY_FONT, color: "B0BEC5",
      align: "center"
    });
  });

  // ================================================================
  // SLIDE 9: Manage & Results
  // ================================================================
  let s9 = pres.addSlide();
  s9.background = { color: WHITE };

  s9.addText("Monitoring & Results", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s9.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  s9.addImage({
    data: imgData("19_manage_results_closed.png"),
    x: 0.3, y: 1.3, w: 6.0, h: 4.0,
    sizing: { type: "contain", w: 6.0, h: 4.0 }
  });

  s9.addText([
    { text: "After closing voting:\n\n", options: { fontSize: 14, color: DARK_TEXT } },
    { text: "\u2022  Enter paper ballot counts\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  Enter postal votes (if any)\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "\u2022  Set brothers present count\n\n", options: { fontSize: 14, color: DARK_TEXT, breakLine: true } },
    { text: "The app automatically calculates\nArticle 6 thresholds:\n\n", options: { fontSize: 14, color: DARK_TEXT } },
    { text: "6a: ", options: { fontSize: 13, color: NAVY, bold: true } },
    { text: "votes > total / vacancies / 2\n", options: { fontSize: 13, color: MID_TEXT, breakLine: true } },
    { text: "6b: ", options: { fontSize: 13, color: NAVY, bold: true } },
    { text: "votes \u2265 participants \u00d7 2/5\n\n", options: { fontSize: 13, color: MID_TEXT, breakLine: true } },
    { text: "Both conditions must be met.", options: { fontSize: 13, color: MID_TEXT, italic: true } },
  ], {
    x: 6.3, y: 1.4, w: 3.4, h: 4.0,
    fontFace: BODY_FONT, valign: "top"
  });

  // ================================================================
  // SLIDE 10: Projector Display
  // ================================================================
  let s10 = pres.addSlide();
  s10.background = { color: NAVY };

  s10.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: GOLD }
  });

  s10.addText("Projector Display", {
    x: 0.8, y: 0.3, w: 9, h: 0.7,
    fontSize: 28, fontFace: HEADER_FONT, color: GOLD, bold: true
  });

  s10.addText("Live results shown to the congregation when enabled by admin.", {
    x: 0.8, y: 0.9, w: 8, h: 0.4,
    fontSize: 13, fontFace: BODY_FONT, color: "B0BEC5", italic: true
  });

  // Screenshot of projector display
  s10.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.6, y: 1.5, w: 8.8, h: 3.8,
    fill: { color: "2A4A6B" }, rectRadius: 0.1
  });
  s10.addImage({
    data: imgData("21_projector_display.png"),
    x: 0.7, y: 1.6, w: 8.6, h: 3.6,
    sizing: { type: "contain", w: 8.6, h: 3.6 }
  });

  // ================================================================
  // SLIDE 11: Safety & Fallback
  // ================================================================
  let s11 = pres.addSlide();
  s11.background = { color: WHITE };

  s11.addText("Safety & Fallback", {
    x: 0.8, y: 0.4, w: 9, h: 0.8,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s11.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 1.1, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  const safetyItems = [
    { title: "Anonymous by Design", desc: "No link between codes and votes in the database. Even with full access, votes cannot be traced." },
    { title: "Paper Is Always the Backup", desc: "If anything goes wrong, switch to paper ballots immediately. Paper and digital votes are counted together." },
    { title: "All Data Stays Local", desc: "The app runs entirely on church WiFi. Nothing is sent to the internet." },
    { title: "Fully Auditable", desc: "The database can be inspected by the consistory at any time. The source code is open." },
  ];

  safetyItems.forEach((item, i) => {
    const y = 1.5 + i * 0.95;
    // Gold left border
    s11.addShape(pres.shapes.RECTANGLE, {
      x: 0.8, y: y, w: 0.06, h: 0.75,
      fill: { color: GOLD }
    });
    s11.addText(item.title, {
      x: 1.1, y: y, w: 8, h: 0.35,
      fontSize: 16, fontFace: BODY_FONT, color: NAVY, bold: true
    });
    s11.addText(item.desc, {
      x: 1.1, y: y + 0.35, w: 8, h: 0.4,
      fontSize: 13, fontFace: BODY_FONT, color: MID_TEXT
    });
  });

  // ================================================================
  // SLIDE 12: Closing
  // ================================================================
  let s12 = pres.addSlide();
  s12.background = { color: NAVY };

  s12.addShape(pres.shapes.RECTANGLE, {
    x: 0, y: 0, w: 10, h: 0.06, fill: { color: GOLD }
  });

  s12.addText("Questions?", {
    x: 0.8, y: 1.5, w: 8.4, h: 1.2,
    fontSize: 44, fontFace: HEADER_FONT, color: GOLD,
    bold: true, align: "center"
  });

  s12.addShape(pres.shapes.RECTANGLE, {
    x: 4, y: 2.8, w: 2, h: 0.04, fill: { color: GOLD }
  });

  s12.addText([
    { text: "The full Admin Guide, Setup Instructions, and\nFailsafe Procedures are included with the app.\n\n", options: { fontSize: 14, color: "B0BEC5" } },
    { text: "Run a dry-run election before election day\nusing the UAT Script.", options: { fontSize: 14, color: GOLD, italic: true } },
  ], {
    x: 1, y: 3.2, w: 8, h: 2,
    fontFace: BODY_FONT, align: "center"
  });

  // Write file
  await pres.writeFile({ fileName: OUT });
  console.log(`Presentation saved to: ${OUT}`);
}

main().catch(console.error);
