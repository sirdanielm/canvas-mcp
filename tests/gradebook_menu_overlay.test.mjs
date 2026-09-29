import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../scripts/gradebook-menu-overlay.gs', import.meta.url), 'utf8');
const config = JSON.parse(readFileSync(new URL('../config/sdm-gradebook-workbooks.json', import.meta.url), 'utf8'));

function harness(options = {}) {
  const calls = {menus: [], items: [], alerts: [], ranges: [], active: []};
  const byId = new Map();
  for (const binding of Object.values(config)) {
    for (const role of ['Canvas', 'Working', '_Sync']) {
      const id = binding.sheets[role];
      byId.set(id, {
        getName: () => options.renameId === id ? 'Unexpected sheet' : binding.tab_names[role],
        getRange: range => {
          assert.equal(role, '_Sync', 'Only operational metadata may be read');
          calls.ranges.push([id, range]);
          const values = {
            'A3:B5': [['Canvas course ID', options.courseId ?? binding.course_id],
              ['Canvas origin', options.origin ?? 'https://fcps.instructure.com'],
              ['Snapshot time', options.time ?? '2026-09-29T19:11:21.446352+00:00']],
            'A10:B10': [['Pending at refresh', options.pending ?? 0]]
          };
          assert.ok(Object.hasOwn(values, range), 'Unapproved metadata range');
          return {getValues: () => values[range]};
        }
      });
    }
  }
  if (options.missingId) byId.delete(options.missingId);
  const workbook = {
    getId: () => options.workbookId ?? config.core.spreadsheet_id,
    getSheetById: id => byId.get(id),
    setActiveSheet: sheet => calls.active.push(sheet.getName())
  };
  const menu = {
    addItem: (title, handler) => {calls.items.push([title, handler]); return menu;},
    addSeparator: () => menu,
    addToUi: () => undefined
  };
  const ui = {
    ButtonSet: {OK: 'OK'},
    createMenu: name => {calls.menus.push(name); return menu;},
    alert: (...args) => calls.alerts.push(args)
  };
  const context = vm.createContext({
    SpreadsheetApp: {getActiveSpreadsheet: () => options.noWorkbook ? null : workbook, getUi: () => ui}
  });
  new vm.Script(source).runInContext(context, {timeout: 1000});
  return {context, calls};
}

test('menu offers accurate guidance, stored status, and GET navigation only', () => {
  const {context, calls} = harness();
  context.onOpen();
  assert.deepEqual(calls.menus, ['Canvas Gradebook']);
  assert.equal(calls.items.length, 4);
  for (const [, handler] of calls.items) assert.equal(typeof context[handler], 'function');
  assert.equal(calls.items.some(([title]) => /setup|token|push|snapshot submissions/i.test(title)), false);
  assert.equal(calls.ranges.length, 0);
});

test('all public entry points reject another workbook before UI or data operations', () => {
  for (const name of ['onOpen', 'sdmGradebookRefreshInstructions', 'snapshotGrAssSubmissions',
    'setupGrAssSubmissionWorkbench', 'saveGrAssSubmissionCanvasToken', 'checkGrAssSubmissionWorkbench',
    'sdmGradebookShowStatus', 'sdmGradebookOpenCore', 'sdmGradebookOpenAdvanced']) {
    const {context, calls} = harness({workbookId: 'different'});
    assert.throws(() => context[name](), /configured central workbook/);
    assert.deepEqual(calls, {menus: [], items: [], alerts: [], ranges: [], active: []});
  }
  assert.throws(() => harness({noWorkbook: true}).context.onOpen(), /configured central workbook/);
});

test('all stale legacy actions redirect to guidance without legacy runtime or setup writes', () => {
  for (const name of ['snapshotGrAssSubmissions', 'setupGrAssSubmissionWorkbench',
    'saveGrAssSubmissionCanvasToken', 'checkGrAssSubmissionWorkbench']) {
    const {context, calls} = harness();
    context[name]();
    assert.equal(calls.alerts.length, 1);
    assert.match(calls.alerts[0][1], /does not contact Canvas or refresh any data/);
    assert.match(calls.alerts[0][1], /pending Edit proposals/);
    assert.match(calls.alerts[0][1], /No Canvas writes/);
    assert.equal(calls.ranges.length, 0);
  }
});

test('status reads only four approved metadata ranges and labels freshness limits', () => {
  const {context, calls} = harness({pending: 3});
  context.sdmGradebookShowStatus();
  assert.deepEqual(calls.ranges, [[2026092103, 'A3:B5'], [2026092103, 'A10:B10'],
    [2026092106, 'A3:B5'], [2026092106, 'A10:B10']]);
  assert.match(calls.alerts[0][1], /Pending edits at that refresh: 3/);
  assert.match(calls.alerts[0][1], /stored metadata, not a live Canvas check/);
  assert.match(calls.alerts[0][1], /does not verify the local baseline/);
});

test('status cannot reflect arbitrary sensitive text from timestamp or count cells', () => {
  const {context, calls} = harness({time: 'private unexpected value', pending: 'private count value'});
  context.sdmGradebookShowStatus();
  assert.match(calls.alerts[0][1], /snapshot time unavailable/);
  assert.match(calls.alerts[0][1], /refresh: unavailable/);
  assert.doesNotMatch(calls.alerts[0][1], /private/);
});

test('metadata course and origin mismatch stop status display', () => {
  for (const options of [{courseId: 'wrong-course'}, {origin: 'https://example.com'}]) {
    const {context, calls} = harness(options);
    assert.throws(() => context.sdmGradebookShowStatus(), /metadata does not match/);
    assert.equal(calls.alerts.length, 0);
  }
});

test('missing or renamed exact sheet bindings stop navigation and status', () => {
  for (const options of [{missingId: 2026092102}, {renameId: 2026092103}]) {
    const {context, calls} = harness(options);
    for (const name of ['sdmGradebookShowStatus', 'sdmGradebookOpenCore', 'sdmGradebookOpenAdvanced']) {
      assert.throws(() => context[name](), /sheet binding has changed/);
    }
    assert.equal(calls.ranges.length, 0);
    assert.equal(calls.active.length, 0);
  }
});

test('navigation selects only the two configured mirror sheets', () => {
  const {context, calls} = harness();
  context.sdmGradebookOpenCore();
  context.sdmGradebookOpenAdvanced();
  assert.deepEqual(calls.active, ['Core GET', 'Adv GET']);
  assert.equal(calls.ranges.length, 0);
});

test('overlay has no network, credential, cell-write, property-write or legacy runtime calls', () => {
  assert.doesNotMatch(source, /UrlFetchApp|fetch\s*\(|PropertiesService|\.setValues?\s*\(|\.clear\s*\(|\.insertSheet\s*\(|submissionWorkbenchRuntime\./);
  assert.equal((source.match(/function onOpen\(/g) ?? []).length, 1);
  assert.equal((source.match(/function snapshotGrAssSubmissions\(/g) ?? []).length, 1);
});
