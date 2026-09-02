const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  WidthType, AlignmentType, TabStopType, BorderStyle, VerticalAlign,
  PageBreak, Footer, PageNumber, PageOrientation
} = require('docx');

const L = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const OUT = process.argv[3];
const FONT = 'Arial';
const SZ = L.pt * 2;
const SZ_CH = L.pt_ch * 2;
const COL_W = Math.floor(L.usable_w / L.cols);
const NONE = { style: BorderStyle.NONE, size: 0, color: 'FFFFFF' };

const SINGLE_TIME = /^\d{2}:\d{2}$/;
const PAD_L = L.cell_pad_left ?? 140;
const PAD_R = L.cell_pad_right ?? 140;

function itemParagraph(r) {
  const spacing = { after: L.after, line: L.line, lineRule: 'atLeast' };
  const time = new TextRun({ text: r.label, bold: true, font: FONT, size: SZ });
  if (SINGLE_TIME.test(r.label)) {
    return new Paragraph({
      spacing,
      indent: { left: L.time_indent, hanging: L.time_indent },
      tabStops: [{ type: TabStopType.LEFT, position: L.time_indent }],
      children: [
        time,
        new TextRun({ text: '\t' + r.title, font: FONT, size: SZ }),
      ],
    });
  }
  return new Paragraph({
    spacing,
    children: [
      time,
      new TextRun({ text: ' ' + r.title, font: FONT, size: SZ }),
    ],
  });
}

function blockParagraphs(b) {
  const out = [new Paragraph({
    keepNext: true,
    spacing: { before: L.head_before, after: L.head_after },
    border: { bottom: { style: BorderStyle.SINGLE, size: 10, space: 2 } },
    children: [new TextRun({ text: b.name, bold: true, font: FONT, size: SZ_CH })],
  })];
  for (const r of b.rows) {
    out.push(itemParagraph(r));
  }
  return out;
}

const children = [];
let first = true;

for (const day of L.days) {
  for (const page of day.pages) {
    children.push(new Paragraph({
      alignment: AlignmentType.CENTER,
      pageBreakBefore: !first,
      spacing: { after: 240 },
      children: [new TextRun({ text: day.title.toUpperCase(), bold: true, font: FONT, size: SZ_CH })],
    }));
    first = false;

    const cells = [];
    for (let i = 0; i < L.cols; i++) {
      const col = page[i];
      const kids = col ? col.items.flatMap(blockParagraphs) : [new Paragraph({ text: '' })];
      cells.push(new TableCell({
        width: { size: COL_W, type: WidthType.DXA },
        verticalAlign: VerticalAlign.TOP,
        margins: { left: PAD_L, right: PAD_R, top: 0, bottom: 0 },
        borders: {
          top: NONE, bottom: NONE, left: NONE,
          right: i < L.cols - 1
            ? { style: BorderStyle.SINGLE, size: 4, color: '999999' }
            : NONE,
        },
        children: kids,
      }));
    }

    children.push(new Table({
      columnWidths: Array(L.cols).fill(COL_W),
      width: { size: COL_W * L.cols, type: WidthType.DXA },
      rows: [new TableRow({ cantSplit: true, children: cells })],
    }));
  }
}

const doc = new Document({
  styles: { default: { document: { run: { font: FONT, size: SZ } } } },
  sections: [{
    properties: {
      page: {
        size: L.landscape
          ? { orientation: PageOrientation.LANDSCAPE, width: 11906, height: 16838 }
          : { orientation: PageOrientation.PORTRAIT },
        margin: L.margins,
      },
    },
    footers: {
      default: new Footer({
        children: [new Paragraph({
          alignment: AlignmentType.CENTER,
          children: [new TextRun({ children: ['— ', PageNumber.CURRENT, ' —'], font: FONT, size: 18 })],
        })],
      }),
    },
    children,
  }],
});

Packer.toBuffer(doc).then(b => { fs.writeFileSync(OUT, b); console.log('готово ' + OUT); });
