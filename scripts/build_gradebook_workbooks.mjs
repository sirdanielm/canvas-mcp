/** Build Canvas / Working workbook pairs from private snapshot artifacts.
 * Run using the bundled artifact-tool runtime; never log student records.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const [outputDir, ...snapshotPaths] = process.argv.slice(2);
if (!outputDir || !snapshotPaths.length) throw new Error('Usage: builder OUTPUT_DIR SNAPSHOT...');
await fs.mkdir(outputDir, { recursive: true, mode: 0o700 });
const column = index => {
  let result = '';
  for (let n = index + 1; n > 0; n = Math.floor((n - 1) / 26)) result = String.fromCharCode(65 + (n - 1) % 26) + result;
  return result;
};
const literal = value => typeof value === 'string' && /^[=+\-@]/.test(value) ? "'" + value : value;
const colors = { ink: '#2D3B45', blue: '#0869B2', header: '#F2F3F4', line: '#DFE3E6', late: '#E2F2FC', excused: '#FFF2CC', missing: '#FCE4E8', edited: '#DDF3E4' };

async function build(snapshot, snapshotId, label, preview = false) {
  const workbook = Workbook.create();
  const count = snapshot.students.length;
  const lastRow = count + 5;
  const lastColumn = column(snapshot.assignments.length + 1);
  for (const tab of ['Canvas', 'Working']) {
    const sheet = workbook.worksheets.add(tab);
    sheet.showGridLines = false;
    const all = sheet.getRange(`A1:${lastColumn}${lastRow}`);
    all.format.font = { name: 'Arial', size: 11, color: colors.ink };
    all.format.rowHeight = 36;
    all.format.verticalAlignment = 'center';
    sheet.getRange(`A1:A${lastRow}`).format.columnWidthPx = 90;
    sheet.getRange(`B1:B${lastRow}`).format.columnWidthPx = 255;
    sheet.getRange(`C1:${lastColumn}${lastRow}`).format.columnWidthPx = 125;
    sheet.getRange('B1').values = [[`${label} Chemistry — ${tab}`]];
    sheet.getRange('B1').format.font = { name: 'Arial', size: 16, color: colors.blue };
    sheet.getRange('B2').values = [[tab === 'Canvas' ? 'Canvas snapshot · read only' : 'Edit scores here · changes stay local']];
    sheet.getRange('B2').format.font = { name: 'Arial', size: 10, color: '#57636C' };
    sheet.getRange('B2').format.wrapText = true;
    sheet.getRange('C2').values = [[`Refreshed ${new Date(snapshot.fetched_at).toLocaleString('en-US', { timeZone: 'America/New_York' })} ET`]];
    sheet.getRange('G2').values = [['Blue: late   Yellow: excused   Pink: missing']];
    sheet.getRange('B3').values = [['Student Name']];
    sheet.getRange('B4').values = [['Points possible']];
    sheet.getRange('A5:B5').values = [['Canvas user ID', 'Canvas assignment IDs']];
    sheet.getRange(`C3:${lastColumn}3`).values = [snapshot.assignments.map(a => literal(a.name))];
    sheet.getRange(`C4:${lastColumn}4`).values = [snapshot.assignments.map(a => a.points_possible)];
    sheet.getRange(`C5:${lastColumn}5`).values = [snapshot.assignments.map(a => a.id)];
    sheet.getRange(`B3:${lastColumn}4`).format.fill = colors.header;
    sheet.getRange(`B3:${lastColumn}3`).format.font = { name: 'Arial', size: 11, bold: true, color: colors.ink };
    sheet.getRange(`B3:${lastColumn}3`).format.wrapText = true;
    sheet.getRange(`B3:${lastColumn}3`).format.rowHeight = 66;
    sheet.getRange(`C3:${lastColumn}${lastRow}`).format.horizontalAlignment = 'center';
    sheet.getRange(`A5:${lastColumn}5`).format.font = { name: 'Arial', size: 8, color: '#6B7280' };
    sheet.getRange(`A5:${lastColumn}5`).format.rowHeight = 15;
    const matrix = snapshot.students.map(student => [
      student.id, literal(`${student.name}\n${student.sections.join(', ')}`),
      ...snapshot.assignments.map(a => {
        const cell = snapshot.cells[`${student.id}:${a.id}`];
        return cell?.value === 'EX' ? 'Excused' : (cell?.value ?? null);
      }),
    ]);
    if (count) {
      sheet.getRange(`A6:${lastColumn}${lastRow}`).values = matrix;
      sheet.getRange(`B6:B${lastRow}`).format.font = { name: 'Arial', size: 11, color: colors.blue };
      sheet.getRange(`B6:B${lastRow}`).format.wrapText = true;
      sheet.getRange(`C6:${lastColumn}${lastRow}`).setNumberFormat('General');
      for (let r = 0; r < count; r++) {
        if (r % 2) sheet.getRange(`B${r + 6}:${lastColumn}${r + 6}`).format.fill = colors.header;
        for (let c = 0; c < snapshot.assignments.length; c++) {
          const cell = snapshot.cells[`${snapshot.students[r].id}:${snapshot.assignments[c].id}`];
          const fill = cell?.excused ? colors.excused : cell?.missing ? colors.missing : cell?.late ? colors.late : null;
          if (fill) sheet.getRange(`${column(c + 2)}${r + 6}`).format.fill = fill;
        }
      }
      sheet.getRange(`B3:${lastColumn}${lastRow}`).format.borders = { preset: 'all', style: 'thin', color: colors.line };
      if (tab === 'Working') {
        const original = `INDEX(INDIRECT("'Canvas'!$C$6:$${lastColumn}$${lastRow}"),MATCH($A6,INDIRECT("'Canvas'!$A$6:$A$${lastRow}"),0),MATCH(C$5,INDIRECT("'Canvas'!$C$5:$${lastColumn}$5"),0))`;
        sheet.getRange(`C6:${lastColumn}${lastRow}`).conditionalFormats.addCustom(
          `=OR(ISBLANK(C6)<>ISBLANK(${original}),C6<>${original})`,
          { fill: colors.edited, font: { bold: true } },
        );
      }
    }
    sheet.freezePanes.freezeRows(5);
    sheet.freezePanes.freezeColumns(2);
    sheet.tabColor = tab === 'Canvas' ? colors.blue : '#217346';
  }
  const meta = workbook.worksheets.add('_Sync');
  meta.getRange('A1:B8').values = [
    ['Schema version', 1], ['Snapshot ID', snapshotId], ['Canvas course ID', snapshot.course_id],
    ['Canvas origin', snapshot.origin], ['Snapshot time', snapshot.fetched_at],
    ['Scope', snapshot.scope], ['Canvas writes', 'Unavailable in this initial build'],
    ['Source', `${snapshot.origin}/courses/${snapshot.course_id}/gradebook`],
  ];
  meta.getRange('A1:A8').format.columnWidth = 22;
  meta.getRange('B1:B8').format.columnWidth = 80;
  meta.getRange('B5').setNumberFormat('yyyy-mm-dd hh:mm:ss');
  if (preview) {
    for (const tab of ['Canvas', 'Working', '_Sync']) {
      const blob = await workbook.render({ sheetName: tab, range: tab === '_Sync' ? 'A1:B8' : 'B1:H11', scale: 1.5, format: 'png' });
      await fs.writeFile(path.join(outputDir, `${label.toLowerCase()}-${tab.toLowerCase()}-preview.png`), new Uint8Array(await blob.arrayBuffer()));
    }
    return;
  }
  const errors = await workbook.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!', options: { useRegex: true, maxResults: 10 }, summary: 'Formula error scan' });
  await fs.writeFile(path.join(outputDir, `${label.toLowerCase()}-qa.json`), JSON.stringify({ students: count, assignments: snapshot.assignments.length, formulaScan: errors.ndjson }));
  const file = path.join(outputDir, `Chemistry ${label} Gradebook.xlsx`);
  await (await SpreadsheetFile.exportXlsx(workbook)).save(file);
  await fs.chmod(file, 0o600);
  console.log(JSON.stringify({ file, students: count, assignments: snapshot.assignments.length, lastRow, lastColumn }));
}

for (const snapshotPath of snapshotPaths) {
  const snapshot = JSON.parse(await fs.readFile(snapshotPath, 'utf8'));
  const match = path.basename(snapshotPath).match(/^snapshot-([a-f0-9]{64})\.json$/);
  if (!match || snapshot.schema_version !== 1 || !snapshot.students.length || !snapshot.assignments.length) throw new Error('A complete supported snapshot is required.');
  const label = snapshot.course_id === '363308' ? 'Core' : snapshot.course_id === '374070' ? 'Advanced' : null;
  if (!label) throw new Error('Unconfigured course');
  await build(snapshot, match[1], label);
  // Separate synthetic preview: no student names, identifiers, or real scores in images.
  const demo = structuredClone(snapshot);
  demo.students = Array.from({ length: 6 }, (_, i) => ({ id: String(1000 + i), name: `Example Student ${i + 1}`, sections: [i % 2 ? 'A2' : 'A4'] }));
  demo.cells = {};
  for (const [r, student] of demo.students.entries()) for (const [c, assignment] of demo.assignments.entries()) {
    const excused = r === 3 && c === 1;
    demo.cells[`${student.id}:${assignment.id}`] = { value: excused ? 'EX' : r === 2 && c === 2 ? null : (r + c) % 5 === 0 ? 0 : assignment.points_possible, excused, missing: false, late: (r + c) % 3 === 0 };
  }
  await build(demo, 'Synthetic preview', label, true);
}
