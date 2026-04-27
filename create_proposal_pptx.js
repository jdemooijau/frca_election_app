const pptxgen = require("pptxgenjs");
const fs = require("fs");
const path = require("path");

const SHOTS = "screenshots";
const OUT = "voting-app/docs/FRCA_Election_App_Proposal.pptx";

// Color palette — Navy & Gold (matching the app)
const NAVY = "1A3353";
const GOLD = "D4A843";
const WHITE = "FFFFFF";
const LIGHT = "F5F6FA";
const DARK_TEXT = "2C3E50";
const MID_TEXT = "5D6D7E";
const LIGHT_NAVY = "2A4A6B";

const HEADER_FONT = "Georgia";
const BODY_FONT = "Calibri";

function imgData(name) {
  const buf = fs.readFileSync(path.resolve(SHOTS, name));
  return "image/png;base64," + buf.toString("base64");
}

async function main() {
  let pres = new pptxgen();
  pres.layout = "LAYOUT_16x9";
  pres.author = "FRCA Election App";
  pres.title = "FRCA Election App — Proposal";

  // ================================================================
  // SLIDE 1: Title
  // ================================================================
  let s1 = pres.addSlide();
  s1.background = { color: NAVY };
  s1.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: GOLD } });

  s1.addText("FRCA Election App", {
    x: 0.8, y: 1.0, w: 8.4, h: 1.2,
    fontSize: 48, fontFace: HEADER_FONT, color: GOLD, bold: true
  });
  s1.addText("Digital Voting for Office Bearer Elections", {
    x: 0.8, y: 2.1, w: 8.4, h: 0.7,
    fontSize: 22, fontFace: BODY_FONT, color: WHITE
  });
  s1.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 3.1, w: 2, h: 0.04, fill: { color: GOLD } });
  s1.addText([
    { text: "Offline  \u00b7  Anonymous  \u00b7  Rules-Compliant  \u00b7  Auditable", options: { fontSize: 16, color: "B0BEC5" } },
  ], { x: 0.8, y: 3.5, w: 8, h: 0.5, fontFace: BODY_FONT });

  s1.addText("Free Reformed Churches of Australia", {
    x: 0.8, y: 4.6, w: 8, h: 0.4,
    fontSize: 13, fontFace: BODY_FONT, color: MID_TEXT, italic: true
  });

  // ================================================================
  // SLIDE 2: Paper vs Digital — Process Comparison
  // ================================================================
  let s2 = pres.addSlide();
  s2.background = { color: LIGHT };

  s2.addText("How It Changes the Process", {
    x: 0.8, y: 0.3, w: 9, h: 0.7,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s2.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 0.95, w: 1.5, h: 0.04, fill: { color: GOLD } });

  // LEFT COLUMN — Paper (current)
  const colL = 0.4;
  const colR = 5.2;
  const colW = 4.4;

  // Paper header
  s2.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: colL, y: 1.3, w: colW, h: 0.55,
    fill: { color: "8B4513" }, rectRadius: 0.08
  });
  s2.addText("Current: Paper Ballots", {
    x: colL, y: 1.3, w: colW, h: 0.55,
    fontSize: 16, fontFace: BODY_FONT, color: WHITE, bold: true, align: "center", valign: "middle"
  });

  const paperSteps = [
    { num: "1", text: "Print blank ballot papers" },
    { num: "2", text: "Hand out ballots at the door" },
    { num: "3", text: "Brothers fill in names by hand" },
    { num: "4", text: "Collect all ballot papers" },
    { num: "5", text: "2\u20133 brothers count every paper manually" },
    { num: "6", text: "Calculate thresholds by hand" },
    { num: "7", text: "Announce results" },
  ];

  paperSteps.forEach((step, i) => {
    const y = 2.05 + i * 0.47;
    s2.addShape(pres.shapes.OVAL, {
      x: colL + 0.15, y: y + 0.03, w: 0.35, h: 0.35,
      fill: { color: "8B4513" }
    });
    s2.addText(step.num, {
      x: colL + 0.15, y: y + 0.03, w: 0.35, h: 0.35,
      fontSize: 12, fontFace: BODY_FONT, color: WHITE, align: "center", valign: "middle", bold: true
    });
    s2.addText(step.text, {
      x: colL + 0.65, y: y, w: colW - 0.8, h: 0.4,
      fontSize: 13, fontFace: BODY_FONT, color: DARK_TEXT, valign: "middle"
    });
  });

  // Pain points
  s2.addText([
    { text: "Slow counting  \u00b7  Human error  \u00b7  No live progress", options: { fontSize: 11, color: "C0392B", italic: true } }
  ], { x: colL, y: 5.15, w: colW, h: 0.3, fontFace: BODY_FONT, align: "center" });

  // RIGHT COLUMN — Digital (new)
  s2.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: colR, y: 1.3, w: colW, h: 0.55,
    fill: { color: NAVY }, rectRadius: 0.08
  });
  s2.addText("New: Digital + Paper", {
    x: colR, y: 1.3, w: colW, h: 0.55,
    fontSize: 16, fontFace: BODY_FONT, color: GOLD, bold: true, align: "center", valign: "middle"
  });

  const digitalSteps = [
    { num: "1", text: "Generate unique voting codes" },
    { num: "2", text: "Hand out code slips at the door" },
    { num: "3", text: "Brothers vote on their phones" },
    { num: "4", text: "Votes counted instantly" },
    { num: "5", text: "Enter paper ballot totals (if any)" },
    { num: "6", text: "Thresholds calculated automatically" },
    { num: "7", text: "Show results on projector" },
  ];

  digitalSteps.forEach((step, i) => {
    const y = 2.05 + i * 0.47;
    s2.addShape(pres.shapes.OVAL, {
      x: colR + 0.15, y: y + 0.03, w: 0.35, h: 0.35,
      fill: { color: NAVY }
    });
    s2.addText(step.num, {
      x: colR + 0.15, y: y + 0.03, w: 0.35, h: 0.35,
      fontSize: 12, fontFace: BODY_FONT, color: GOLD, align: "center", valign: "middle", bold: true
    });
    s2.addText(step.text, {
      x: colR + 0.65, y: y, w: colW - 0.8, h: 0.4,
      fontSize: 13, fontFace: BODY_FONT, color: DARK_TEXT, valign: "middle"
    });
  });

  // Benefits
  s2.addText([
    { text: "Instant results  \u00b7  No counting errors  \u00b7  Live progress", options: { fontSize: 11, color: "27AE60", italic: true } }
  ], { x: colR, y: 5.15, w: colW, h: 0.3, fontFace: BODY_FONT, align: "center" });

  // Center divider
  s2.addShape(pres.shapes.RECTANGLE, {
    x: 4.9, y: 1.5, w: 0.03, h: 3.8, fill: { color: "D0D0D0" }
  });

  // ================================================================
  // SLIDE 2b: Printable Materials
  // ================================================================
  let s2b = pres.addSlide();
  s2b.background = { color: WHITE };

  s2b.addText("What Gets Printed", {
    x: 0.8, y: 0.3, w: 9, h: 0.7,
    fontSize: 32, fontFace: HEADER_FONT, color: NAVY, bold: true
  });
  s2b.addShape(pres.shapes.RECTANGLE, {
    x: 0.8, y: 0.95, w: 1.5, h: 0.04, fill: { color: GOLD }
  });

  // Code slips (left)
  s2b.addText("Code Slips", {
    x: 0.5, y: 1.2, w: 4.5, h: 0.35,
    fontSize: 18, fontFace: BODY_FONT, color: NAVY, bold: true, align: "center"
  });
  s2b.addText("Each brother receives one slip with a unique\n6-character code and QR code.", {
    x: 0.5, y: 1.55, w: 4.5, h: 0.5,
    fontSize: 12, fontFace: BODY_FONT, color: MID_TEXT, align: "center"
  });
  s2b.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.7, y: 2.15, w: 4.1, h: 3.1,
    fill: { color: LIGHT }, rectRadius: 0.08,
    shadow: { type: "outer", color: "000000", blur: 4, offset: 2, angle: 135, opacity: 0.08 }
  });
  s2b.addImage({
    data: imgData("23_code_slips.png"),
    x: 0.8, y: 2.25, w: 3.9, h: 2.9,
    sizing: { type: "contain", w: 3.9, h: 2.9 }
  });

  // Paper ballot (right)
  s2b.addText("Paper Ballots", {
    x: 5.0, y: 1.2, w: 4.5, h: 0.35,
    fontSize: 18, fontFace: BODY_FONT, color: NAVY, bold: true, align: "center"
  });
  s2b.addText("For brothers who prefer paper.\nCounted alongside digital votes.", {
    x: 5.0, y: 1.55, w: 4.5, h: 0.5,
    fontSize: 12, fontFace: BODY_FONT, color: MID_TEXT, align: "center"
  });
  s2b.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 5.2, y: 2.15, w: 4.1, h: 3.1,
    fill: { color: LIGHT }, rectRadius: 0.08,
    shadow: { type: "outer", color: "000000", blur: 4, offset: 2, angle: 135, opacity: 0.08 }
  });
  s2b.addImage({
    data: imgData("24_paper_ballot.png"),
    x: 5.3, y: 2.25, w: 3.9, h: 2.9,
    sizing: { type: "contain", w: 3.9, h: 2.9 }
  });

  // ================================================================
  // SLIDE 3: How Brothers Vote (with phone screenshots)
  // ================================================================
  let s3 = pres.addSlide();
  s3.background = { color: NAVY };
  s3.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: GOLD } });

  s3.addText("Election Day: How Brothers Vote", {
    x: 0.5, y: 0.25, w: 9, h: 0.7,
    fontSize: 32, fontFace: HEADER_FONT, color: GOLD, bold: true
  });

  const voterScreens = [
    { img: "13_voter_enter_code.png", label: "1. Enter Code", desc: "Type the 6-character\ncode from their slip" },
    { img: "15_voter_ballot.png", label: "2. Cast Vote", desc: "Select candidates\nfor each office" },
    { img: "17_voter_confirmation.png", label: "3. Confirmed", desc: "Vote submitted.\nCode is burned." },
  ];

  voterScreens.forEach((vs, i) => {
    const x = 0.5 + i * 3.2;
    // Phone frame
    s3.addShape(pres.shapes.ROUNDED_RECTANGLE, {
      x: x + 0.35, y: 1.15, w: 2.2, h: 3.5,
      fill: { color: LIGHT_NAVY }, rectRadius: 0.15
    });
    s3.addImage({
      data: imgData(vs.img),
      x: x + 0.45, y: 1.25, w: 2.0, h: 3.3,
      sizing: { type: "contain", w: 2.0, h: 3.3 }
    });
    s3.addText(vs.label, {
      x: x, y: 4.75, w: 2.9, h: 0.35,
      fontSize: 15, fontFace: BODY_FONT, color: GOLD, align: "center", bold: true
    });
    s3.addText(vs.desc, {
      x: x, y: 5.05, w: 2.9, h: 0.5,
      fontSize: 11, fontFace: BODY_FONT, color: "B0BEC5", align: "center"
    });
  });

  // ================================================================
  // SLIDE 4: Projector Display
  // ================================================================
  let s4 = pres.addSlide();
  s4.background = { color: NAVY };
  s4.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: GOLD } });

  s4.addText("Live Projector Display", {
    x: 0.8, y: 0.25, w: 9, h: 0.65,
    fontSize: 28, fontFace: HEADER_FONT, color: GOLD, bold: true
  });
  s4.addText("Real-time results shown to the congregation during and after voting.", {
    x: 0.8, y: 0.8, w: 8, h: 0.35,
    fontSize: 13, fontFace: BODY_FONT, color: "B0BEC5", italic: true
  });

  // Projector screenshot in a frame
  s4.addShape(pres.shapes.ROUNDED_RECTANGLE, {
    x: 0.5, y: 1.3, w: 9.0, h: 4.1,
    fill: { color: LIGHT_NAVY }, rectRadius: 0.1
  });
  s4.addImage({
    data: imgData("21_projector_display.png"),
    x: 0.6, y: 1.4, w: 8.8, h: 3.9,
    sizing: { type: "contain", w: 8.8, h: 3.9 }
  });

  // ================================================================
  // SLIDE 5: Closing
  // ================================================================
  let s5 = pres.addSlide();
  s5.background = { color: NAVY };
  s5.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: GOLD } });

  s5.addText("Key Assurances", {
    x: 0.8, y: 0.5, w: 8.4, h: 0.7,
    fontSize: 32, fontFace: HEADER_FONT, color: GOLD, bold: true
  });
  s5.addShape(pres.shapes.RECTANGLE, { x: 0.8, y: 1.15, w: 1.5, h: 0.04, fill: { color: GOLD } });

  const assurances = [
    { title: "Anonymous by Design", desc: "No link between codes and votes in the database. Votes cannot be traced, even with full access." },
    { title: "Offline & Local", desc: "Runs entirely on one laptop over church WiFi. No data leaves the building. No internet required." },
    { title: "Paper Is Always the Backup", desc: "Paper ballots remain a first-class option. If anything goes wrong, switch to paper immediately." },
    { title: "Rules-Compliant", desc: "Article 2 slate validation, Article 6 threshold calculations, Article 7 partial ballot support \u2014 all automatic." },
    { title: "Open Source & Auditable", desc: "The consistory can inspect the source code and database at any time. Nothing is hidden." },
  ];

  assurances.forEach((item, i) => {
    const y = 1.55 + i * 0.75;
    s5.addShape(pres.shapes.RECTANGLE, {
      x: 0.8, y: y, w: 0.06, h: 0.55, fill: { color: GOLD }
    });
    s5.addText(item.title, {
      x: 1.1, y: y - 0.02, w: 8, h: 0.3,
      fontSize: 15, fontFace: BODY_FONT, color: WHITE, bold: true
    });
    s5.addText(item.desc, {
      x: 1.1, y: y + 0.28, w: 8, h: 0.35,
      fontSize: 12, fontFace: BODY_FONT, color: "B0BEC5"
    });
  });

  // Write file
  await pres.writeFile({ fileName: OUT });
  console.log(`Proposal saved to: ${OUT}`);
}

main().catch(console.error);
