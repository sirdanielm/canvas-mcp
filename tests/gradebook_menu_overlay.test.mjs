import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../scripts/gradebook-menu-overlay.gs', import.meta.url), 'utf8');
const config = JSON.parse(readFileSync(new URL('../config/sdm-gradebook-workbooks.json', import.meta.url), 'utf8'));
const requestId = 'aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee';
const otherId = '11111111-2222-4333-8444-555555555555';
const prefix = 'sdm.gradebook.refresh.';
const fixedIds = {claim: 2026092901, applied: 2026092902, status: 2026092903, heartbeat: 2026092904};
const request = () => ({v: 1, id: requestId, action: 'REFRESH_BOTH',
  created_at: new Date().toISOString(), workbook_id: config.core.spreadsheet_id});
const heartbeat = overrides => ({kind: 'heartbeat', data: {v: 1, state: 'READY',
  updated_at: new Date().toISOString(), workbook_id: config.core.spreadsheet_id, ...overrides}});

function harness(options = {}) {
  const calls = {menus: [], items: [], alerts: [], ranges: [], active: [], writes: [], locks: [], flushes: 0};
  const metadata = structuredClone(options.metadata ?? []);
  const wrapMetadata = entry => ({
    getValue: () => entry.raw ?? JSON.stringify(entry.data),
    getId: () => entry.metadataId ?? fixedIds[entry.kind] ?? 1000,
    getVisibility: () => entry.visibility ?? 'DOCUMENT',
    getLocation: () => ({getLocationType: () => entry.location ?? 'SPREADSHEET'})
  });
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
    setActiveSheet: sheet => calls.active.push(sheet.getName()),
    createDeveloperMetadataFinder: () => {
      const finder = {withKey: key => {finder.key = key; return finder;},
        find: () => metadata.filter(entry => prefix + entry.kind + '.v1' === finder.key).map(wrapMetadata)};
      return finder;
    },
    addDeveloperMetadata: (key, value, visibility) => {
      assert.equal(key, prefix + 'request.v1');
      assert.equal(visibility, 'DOCUMENT');
      assert.deepEqual(calls.locks, ['acquired'], 'Enqueue requires the document lock');
      calls.writes.push([key, value, visibility]);
      if (!options.dropWrite) metadata.push({kind: 'request', raw: value});
    }
  };
  const menu = {
    addItem: (title, handler) => {calls.items.push([title, handler]); return menu;},
    addSeparator: () => menu,
    addToUi: () => undefined
  };
  const ui = {
    ButtonSet: {OK: 'OK', OK_CANCEL: 'OK_CANCEL'},
    Button: {OK: 'OK', CANCEL: 'CANCEL'},
    createMenu: name => {calls.menus.push(name); return menu;},
    alert: (...args) => {calls.alerts.push(args); return options.cancel ? 'CANCEL' : 'OK';}
  };
  const context = vm.createContext({
    SpreadsheetApp: {getActiveSpreadsheet: () => options.noWorkbook ? null : workbook, getUi: () => ui,
      DeveloperMetadataVisibility: {DOCUMENT: 'DOCUMENT'}, flush: () => {calls.flushes += 1;}},
    Utilities: {getUuid: () => requestId},
    LockService: {getDocumentLock: () => ({
      tryLock: () => {if (options.lockBusy) return false; calls.locks.push('acquired'); return true;},
      releaseLock: () => calls.locks.push('released')})}
  });
  new vm.Script(source).runInContext(context, {timeout: 1000});
  return {context, calls, metadata};
}

test('menu offers accurate guidance, stored status, and GET navigation only', () => {
  const {context, calls} = harness();
  context.onOpen();
  assert.deepEqual(calls.menus, ['Canvas Gradebook']);
  assert.equal(calls.items.length, 6);
  for (const [, handler] of calls.items) assert.equal(typeof context[handler], 'function');
  assert.equal(calls.items.some(([title]) => /setup|token|push|snapshot submissions/i.test(title)), false);
  assert.equal(calls.ranges.length, 0);
});

test('all public entry points reject another workbook before UI or data operations', () => {
  for (const name of ['onOpen', 'sdmGradebookRefreshInstructions', 'snapshotGrAssSubmissions',
    'setupGrAssSubmissionWorkbench', 'saveGrAssSubmissionCanvasToken', 'checkGrAssSubmissionWorkbench',
    'sdmGradebookShowStatus', 'sdmGradebookOpenCore', 'sdmGradebookOpenAdvanced',
    'sdmGradebookRequestRefresh', 'sdmGradebookShowProgress']) {
    const {context, calls} = harness({workbookId: 'different'});
    assert.throws(() => context[name](), /configured central workbook/);
    assert.deepEqual(calls, {menus: [], items: [], alerts: [], ranges: [], active: [], writes: [], locks: [], flushes: 0});
  }
  assert.throws(() => harness({noWorkbook: true}).context.onOpen(), /configured central workbook/);
});

test('all stale legacy actions redirect to guidance without legacy runtime or setup writes', () => {
  for (const name of ['snapshotGrAssSubmissions', 'setupGrAssSubmissionWorkbench',
    'saveGrAssSubmissionCanvasToken', 'checkGrAssSubmissionWorkbench']) {
    const {context, calls} = harness();
    context[name]();
    assert.equal(calls.alerts.length, 1);
    assert.match(calls.alerts[0][1], /does not contact Canvas/);
    assert.match(calls.alerts[0][1], /pending Edit proposals/);
    assert.match(calls.alerts[0][1], /No Canvas writes/);
    assert.equal(calls.ranges.length, 0);
    assert.equal(calls.writes.length, 0);
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

test('confirmed request queues only exact authorized protocol under lock and reads it back', () => {
  const {context, calls, metadata} = harness({metadata: [heartbeat()]});
  context.sdmGradebookRequestRefresh();
  assert.equal(calls.writes.length, 1);
  const saved = JSON.parse(calls.writes[0][1]);
  assert.deepEqual(Object.keys(saved).sort(), ['action', 'created_at', 'id', 'v', 'workbook_id']);
  assert.equal(saved.id, requestId);
  assert.equal(saved.action, 'REFRESH_BOTH');
  assert.equal(saved.workbook_id, config.core.spreadsheet_id);
  assert.equal(metadata.filter(x => x.kind === 'request').length, 1);
  assert.deepEqual(calls.locks, ['acquired', 'released']);
  assert.equal(calls.flushes, 1);
  assert.equal(calls.ranges.length, 0);
  assert.match(calls.alerts[0][1], /keep this workbook idle/);
  assert.match(calls.alerts.at(-1)[1], /Refresh queued/);
});

test('canceling confirmation performs no queue read, write or lock acquisition', () => {
  const {context, calls} = harness({cancel: true, metadata: [heartbeat()]});
  context.sdmGradebookRequestRefresh();
  assert.equal(calls.writes.length, 0);
  assert.deepEqual(calls.locks, []);
});

test('existing immutable request is deduplicated even when heartbeat is absent', () => {
  const pending = request();
  const {context, calls, metadata} = harness({metadata: [{kind: 'request', data: pending}]});
  context.sdmGradebookRequestRefresh();
  assert.equal(calls.writes.length, 0);
  assert.deepEqual(metadata, [{kind: 'request', data: pending}]);
  assert.match(calls.alerts.at(-1)[1], /already exists/);
  assert.deepEqual(calls.locks, ['acquired', 'released']);
});

test('offline, stale, future, wrong-workbook and non-ready heartbeats cannot enqueue', () => {
  const overrides = [null, {state: 'OFFLINE'}, {updated_at: new Date(Date.now() - 181000).toISOString()},
    {updated_at: new Date(Date.now() + 60000).toISOString()}, {workbook_id: 'different'},
    {updated_at: 'arbitrary private text'}];
  for (const patch of overrides) {
    const {context, calls} = harness({metadata: patch ? [heartbeat(patch)] : []});
    assert.throws(() => context.sdmGradebookRequestRefresh(), /worker is not ready/);
    assert.equal(calls.writes.length, 0);
    assert.deepEqual(calls.locks, ['acquired', 'released']);
  }
});

test('busy document lock stops enqueue without releasing another execution lock', () => {
  const {context, calls} = harness({lockBusy: true, metadata: [heartbeat()]});
  assert.throws(() => context.sdmGradebookRequestRefresh(), /Another menu request/);
  assert.equal(calls.writes.length, 0);
  assert.deepEqual(calls.locks, []);
});

test('malformed and duplicate request records fail closed before enqueue', () => {
  const variants = [
    [{kind: 'request', data: request()}, {kind: 'request', data: request()}],
    [{kind: 'request', raw: 'not-json'}],
    [{kind: 'request', data: {...request(), action: 'PUSH'}}],
    [{kind: 'request', data: {...request(), extra: 'unexpected'}}],
    [{kind: 'request', data: {...request(), workbook_id: 'different'}}],
    [{kind: 'request', data: {...request(), v: 2}}],
    [{kind: 'request', data: {...request(), id: 'bad-id'}}],
    [{kind: 'request', data: {...request(), created_at: 'arbitrary text'}}],
    [{kind: 'request', data: {...request(), created_at: new Date(Date.now() + 60000).toISOString()}}],
    [{kind: 'request', data: request(), visibility: 'PROJECT'}],
    [{kind: 'request', data: request(), location: 'SHEET'}],
    [{kind: 'request', raw: 'x'.repeat(2049)}]
  ];
  for (const records of variants) {
    const {context, calls} = harness({metadata: [heartbeat(), ...records]});
    assert.throws(() => context.sdmGradebookRequestRefresh(), /needs reconciliation/);
    assert.equal(calls.writes.length, 0);
    assert.deepEqual(calls.locks, ['acquired', 'released']);
  }
});

test('orphan, mismatched and duplicate claim markers cannot start new work', () => {
  for (const records of [
    [{kind: 'claim', data: {v: 1, id: requestId}}],
    [{kind: 'applied', data: {v: 1, id: requestId}}],
    [{kind: 'request', data: request()}, {kind: 'claim', data: {v: 1, id: otherId}}],
    [{kind: 'request', data: request()}, {kind: 'applied', data: {v: 1, id: requestId}}],
    [{kind: 'request', data: request()}, {kind: 'claim', data: {v: 1, id: requestId}, metadataId: 42}],
    [{kind: 'request', data: request()}, {kind: 'claim', data: {v: 1, id: requestId}},
      {kind: 'claim', data: {v: 1, id: requestId}}]
  ]) {
    const {context, calls} = harness({metadata: [heartbeat(), ...records]});
    assert.throws(() => context.sdmGradebookRequestRefresh(), /needs reconciliation/);
    assert.equal(calls.writes.length, 0);
  }
});

test('request write without confirmed readback stops as uncertain and never retries', () => {
  const {context, calls} = harness({dropWrite: true, metadata: [heartbeat()]});
  assert.throws(() => context.sdmGradebookRequestRefresh(), /confirmation is uncertain/);
  assert.equal(calls.writes.length, 1);
  assert.deepEqual(calls.locks, ['acquired', 'released']);
});

test('receipt status displays only allowed state, time, and nonnegative integer aggregates', () => {
  const status = {v: 1, id: requestId, state: 'VERIFIED', updated_at: new Date().toISOString(),
    workbook_id: config.core.spreadsheet_id, error: 'private raw error',
    summary: {core: {students: 120, assignments: 18, pending_edits: 2, names: 'private rows'},
      advanced: {students: 'private count', assignments: -2, pending_edits: 1.2}}};
  const {context, calls} = harness({metadata: [{kind: 'status', data: status}, heartbeat()]});
  context.sdmGradebookShowProgress();
  const text = calls.alerts[0][1];
  assert.match(text, /State: VERIFIED/);
  assert.match(text, /students: 120, assignments: 18, pending edits: 2/);
  assert.doesNotMatch(text, /private|assignments: -2|pending edits: 1\.2/);
  assert.equal(calls.writes.length, 0);
  assert.equal(calls.ranges.length, 0);
});

test('a prior receipt cannot report a different current request as verified', () => {
  const {context, calls} = harness({metadata: [{kind: 'request', data: request()},
    {kind: 'status', data: {v: 1, id: otherId, state: 'VERIFIED', updated_at: new Date().toISOString(),
      workbook_id: config.core.spreadsheet_id}}]});
  context.sdmGradebookShowProgress();
  assert.match(calls.alerts[0][1], /State: QUEUED/);
  assert.doesNotMatch(calls.alerts[0][1], /State: VERIFIED/);
});

test('unknown status or wrong heartbeat metadata identity cannot be trusted', () => {
  const validStatus = {v: 1, id: requestId, state: 'VERIFIED', updated_at: new Date().toISOString(),
    workbook_id: config.core.spreadsheet_id};
  for (const records of [
    [{kind: 'status', data: {...validStatus, state: 'unexpected private status'}}],
    [{kind: 'status', data: {...validStatus, workbook_id: 'different'}}],
    [{kind: 'status', data: {...validStatus, updated_at: 'invalid'}}],
    [{...heartbeat(), metadataId: 42}], [heartbeat(), heartbeat()]
  ]) {
    const {context, calls} = harness({metadata: records});
    assert.throws(() => context.sdmGradebookShowProgress(), /needs reconciliation/);
    assert.equal(calls.alerts.length, 0);
    assert.equal(calls.writes.length, 0);
  }
});

test('uncertain prior status prevents enqueue even with a ready heartbeat', () => {
  const {context, calls} = harness({metadata: [heartbeat(), {kind: 'status', data: {
    v: 1, id: requestId, state: 'UNCERTAIN', updated_at: new Date().toISOString(),
    workbook_id: config.core.spreadsheet_id}}]});
  assert.throws(() => context.sdmGradebookRequestRefresh(), /needs reconciliation/);
  assert.equal(calls.writes.length, 0);
});

test('released HELD permits a new request only with no queue markers and a fresh READY heartbeat', () => {
  const held = {kind: 'status', data: {v: 1, id: otherId, state: 'HELD',
    updated_at: new Date().toISOString(), workbook_id: config.core.spreadsheet_id}};
  const success = harness({metadata: [held, heartbeat()]});
  success.context.sdmGradebookRequestRefresh();
  assert.equal(success.calls.writes.length, 1);
  for (const additions of [[], [heartbeat({state: 'OFFLINE'})],
    [heartbeat({updated_at: new Date(Date.now() - 181000).toISOString()})]]) {
    const h = harness({metadata: [held, ...additions]});
    assert.throws(() => h.context.sdmGradebookRequestRefresh(), /worker is not ready/);
    assert.equal(h.calls.writes.length, 0);
  }
  for (const kind of ['claim', 'applied']) {
    const h = harness({metadata: [held, heartbeat(), {kind, data: {v: 1, id: otherId}}]});
    assert.throws(() => h.context.sdmGradebookRequestRefresh(), /needs reconciliation/);
    assert.equal(h.calls.writes.length, 0);
  }
});
