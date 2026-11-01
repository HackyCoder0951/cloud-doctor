#!/usr/bin/env node
// Builds ../Cloud-Doctor-Session-Log.docx from session-log.json.
// To update the log: append an entry to session-log.json (and update "updated" and "status"), then run
//   node docs/14-research-summary/session-log/build_session_log.js
// Needs the `docx` npm package.
const fs = require('fs');
const path = require('path');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell, Header, Footer, AlignmentType, HeadingLevel,
  BorderStyle, WidthType, ShadingType, PageNumber, LevelFormat,
} = require('docx');

const data = JSON.parse(fs.readFileSync(path.join(__dirname, 'session-log.json'), 'utf8'));
const OUT = path.join(__dirname, '..', 'Cloud-Doctor-Session-Log.docx');
const FONT = 'Arial';
const CONTENT_W = 9026; // A4 width 11906 minus 2 x 1440 margins
const INK = '1F2937', MUTED = '6B7280', ACCENT = '1D4ED8', RULE = 'D1D5DB', QUOTE_BG = 'F3F4F6';

const run = (text, o = {}) => new TextRun({ text, font: FONT, color: INK, ...o });
const para = (children, o = {}) => new Paragraph({ children: Array.isArray(children) ? children : [run(children)], spacing: { after: 100, line: 276 }, ...o });
const bullet = (text, ref = 'bullets') => new Paragraph({ numbering: { reference: ref, level: 0 }, children: [run(text, { size: 21 })], spacing: { after: 70, line: 264 } });
const label = (text) => para([run(text, { bold: true, size: 19, color: MUTED, allCaps: true })], { spacing: { before: 140, after: 60 } });

const border = { style: BorderStyle.SINGLE, size: 4, color: RULE };
const cellBorders = { top: border, bottom: border, left: border, right: border };
const cell = (text, w, o = {}) => new TableCell({
  width: { size: w, type: WidthType.DXA }, borders: cellBorders,
  shading: o.fill ? { fill: o.fill, type: ShadingType.CLEAR, color: 'auto' } : undefined,
  margins: { top: 70, bottom: 70, left: 110, right: 110 },
  children: [new Paragraph({ children: [run(String(text), { size: 19, bold: !!o.bold, color: o.color || INK })], spacing: { after: 0 } })],
});
function table(cols, header, rows) {
  const total = cols.reduce((a, b) => a + b, 0);
  return new Table({
    width: { size: total, type: WidthType.DXA }, columnWidths: cols,
    rows: [
      new TableRow({ tableHeader: true, children: header.map((h, i) => cell(h, cols[i], { bold: true, fill: 'E5E7EB' })) }),
      ...rows.map((r) => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, cols[i])) })),
    ],
  });
}

const quote = (text) => new Paragraph({
  children: [run(text, { size: 20, italics: true })],
  shading: { fill: QUOTE_BG, type: ShadingType.CLEAR, color: 'auto' },
  border: { left: { style: BorderStyle.SINGLE, size: 18, color: ACCENT, space: 8 } },
  indent: { left: 200, right: 100 }, spacing: { before: 40, after: 100, line: 264 },
});

const children = [];
children.push(new Paragraph({ children: [run(data.title, { size: 44, bold: true })], spacing: { after: 60 } }));
children.push(new Paragraph({ children: [run(data.subtitle, { size: 24, color: MUTED })], spacing: { after: 200 }, border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: ACCENT, space: 6 } } }));
children.push(table([2200, 6826], ['Item', 'Detail'], [
  ['Project', data.project],
  ['Repository', data.repository],
  ['Last updated', data.updated],
  ['Entries', `${data.entries.length - 1} prompts (numbered 1 to ${data.entries.length - 1}) plus the earlier session summary (0)`],
]));

children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run('How to read this log', { bold: true, size: 30 })], spacing: { before: 300, after: 120 } }));
data.about.forEach((t) => children.push(bullet(t)));

children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run('Phases', { bold: true, size: 30 })], spacing: { before: 300, after: 120 } }));
children.push(table([2700, 1100, 5226], ['Phase', 'Entries', 'What happened'], data.phases.map((p) => [p.name, p.seq, p.note])));

children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run('Timeline at a glance', { bold: true, size: 30 })], spacing: { before: 300, after: 120 } }));
children.push(table([700, 1700, 6626], ['#', 'Date', 'Topic'], data.entries.map((e) => [e.seq, e.date, e.title])));

children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run('Detailed log', { bold: true, size: 30 })], pageBreakBefore: true, spacing: { after: 160 } }));
data.entries.forEach((e) => {
  children.push(new Paragraph({
    heading: HeadingLevel.HEADING_2, keepNext: true,
    children: [run(`#${e.seq}  `, { bold: true, size: 26, color: ACCENT }), run(e.title, { bold: true, size: 26 })],
    spacing: { before: 300, after: 40 },
  }));
  children.push(new Paragraph({ keepNext: true, children: [run(`Date: ${e.date}`, { size: 19, color: MUTED })], spacing: { after: 60 } }));
  children.push(label(e.seq === 0 ? 'Source' : 'Your prompt'));
  children.push(quote(e.prompt));
  children.push(label('Summary of response'));
  e.response.forEach((t) => children.push(bullet(t)));
  if (e.artifacts && e.artifacts.length) {
    children.push(label('Artifacts'));
    children.push(para([run(e.artifacts.join('   |   '), { size: 18, color: MUTED })]));
  }
});

children.push(new Paragraph({ heading: HeadingLevel.HEADING_1, children: [run(`Current status (${data.status.asof})`, { bold: true, size: 30 })], pageBreakBefore: true, spacing: { after: 120 } }));
children.push(label('Branches'));
data.status.branches.forEach((t) => children.push(bullet(t)));
children.push(label('Open items and next steps'));
data.status.open.forEach((t) => children.push(bullet(t)));

const doc = new Document({
  creator: 'Cloud Doctor', title: data.title,
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 30, bold: true, font: FONT }, paragraph: { spacing: { before: 300, after: 120 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 26, bold: true, font: FONT }, paragraph: { spacing: { before: 300, after: 40 }, outlineLevel: 1 } },
    ],
  },
  numbering: { config: [{ reference: 'bullets', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 540, hanging: 270 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1440, right: 1440, bottom: 1300, left: 1440 } } },
    headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT, children: [run(`${data.title}  |  updated ${data.updated}`, { size: 16, color: MUTED })] })] }) },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [run('Page ', { size: 16, color: MUTED }), new TextRun({ children: [PageNumber.CURRENT], font: FONT, size: 16, color: MUTED }), run(' of ', { size: 16, color: MUTED }), new TextRun({ children: [PageNumber.TOTAL_PAGES], font: FONT, size: 16, color: MUTED })] })] }) },
    children,
  }],
});

Packer.toBuffer(doc).then((buf) => { fs.writeFileSync(OUT, buf); console.log('wrote', OUT, buf.length, 'bytes'); });
