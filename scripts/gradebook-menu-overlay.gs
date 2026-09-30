/*
 * Central gradebook menu and local-worker request queue. No Canvas transport
 * or sheet-cell writes; only document-visible coordination metadata is added.
 *
 * INSTALLATION CONTRACT: this is replacement source, not an extra competing
 * onOpen file. Preserve the full bound project first. Replace its existing
 * onOpen and all four legacy wrapper definitions with the definitions below,
 * and add the uniquely named sdmGradebook* helpers. Keep the old runtime and
 * ownership guards unchanged. Verify exactly one definition of each handler
 * in the complete project, exact parent workbook, and complete source readback.
 * A local worker runs the existing canonical refresh after an explicit click.
 */

var SDM_GRADEBOOK_MENU_BINDING_ = {
  workbookId: '13ps0FZLBj2qpclMNKo7Eb95kE4Sb_fgf9s7Ki2_KoNc',
  origin: 'https://fcps.instructure.com',
  courses: [
    {label: 'Core', courseId: '363308', getId: 2026092101, getName: 'Core GET',
      editId: 2026092102, editName: 'Core Edit', syncId: 2026092103, syncName: '_Core Sync'},
    {label: 'Advanced', courseId: '374070', getId: 2026092104, getName: 'Adv GET',
      editId: 2026092105, editName: 'Adv Edit', syncId: 2026092106, syncName: '_Adv Sync'}
  ]
};

var SDM_GRADEBOOK_QUEUE_ = {
  prefix: 'sdm.gradebook.refresh.',
  ids: {claim: 2026092901, applied: 2026092902, status: 2026092903, heartbeat: 2026092904},
  states: ['QUEUED', 'CLAIMING', 'CLAIMED', 'PREPARED', 'SENDING',
    'VERIFYING', 'VERIFIED', 'HELD', 'UNCERTAIN', 'OFFLINE'],
  maxValueChars: 2048,
  heartbeatMaxAgeMs: 180000
};

function sdmGradebookWorkbook_() {
  var workbook = SpreadsheetApp.getActiveSpreadsheet();
  if (!workbook || workbook.getId() !== SDM_GRADEBOOK_MENU_BINDING_.workbookId) {
    throw new Error('Gradebook menu stopped: this is not the configured central workbook.');
  }
  return workbook;
}

function sdmGradebookSheet_(workbook, id, name) {
  var sheet = workbook.getSheetById(id);
  if (!sheet || sheet.getName() !== name) {
    throw new Error('Gradebook menu stopped: the configured sheet binding has changed.');
  }
  return sheet;
}

function sdmGradebookValidateLayout_(workbook) {
  SDM_GRADEBOOK_MENU_BINDING_.courses.forEach(function (course) {
    sdmGradebookSheet_(workbook, course.getId, course.getName);
    sdmGradebookSheet_(workbook, course.editId, course.editName);
    sdmGradebookSheet_(workbook, course.syncId, course.syncName);
  });
}

function onOpen() {
  sdmGradebookWorkbook_();
  SpreadsheetApp.getUi().createMenu('Canvas Gradebook')
    .addItem('Refresh both courses (Canvas GET only)', 'sdmGradebookRequestRefresh')
    .addItem('Show refresh progress', 'sdmGradebookShowProgress')
    .addItem('How to refresh both courses', 'sdmGradebookRefreshInstructions')
    .addItem('Show stored refresh status', 'sdmGradebookShowStatus')
    .addSeparator()
    .addItem('Open Core GET', 'sdmGradebookOpenCore')
    .addItem('Open Advanced GET', 'sdmGradebookOpenAdvanced')
    .addToUi();
}

function sdmGradebookRefreshInstructions() {
  sdmGradebookWorkbook_();
  var ui = SpreadsheetApp.getUi();
  ui.alert('Refresh the Canvas gradebook mirrors',
    'Choose Canvas Gradebook → Refresh both courses (Canvas GET only). Keep this workbook idle ' +
    'until Show refresh progress reports VERIFIED. The Mac and its local gradebook worker must ' +
    'be awake and online; a recent READY heartbeat is required before a request is queued.\n\n' +
    'The worker uses Canvas GETs and trusted local baselines, preserving pending Edit proposals ' +
    'and the Student Info and Assignment reference tabs. No Canvas writes. ' +
    'This menu does not contact Canvas; it queues one request for the local worker.\n\n' +
    'If progress is HELD or UNCERTAIN, ask the Canvas MCP Codex task to reconcile the ' +
    'existing request. Repeated clicks never replace an active request.\n\n' +
    'The old GrAss Submissions snapshot command belongs to a different workbook layout. ' +
    'Do not run its setup command or clear ownership records in this gradebook.', ui.ButtonSet.OK);
}

// Existing menu instances may still call this legacy handler until reload.
function snapshotGrAssSubmissions() {
  return sdmGradebookRefreshInstructions();
}

function setupGrAssSubmissionWorkbench() {
  return sdmGradebookRefreshInstructions();
}

function saveGrAssSubmissionCanvasToken() {
  return sdmGradebookRefreshInstructions();
}

function checkGrAssSubmissionWorkbench() {
  return sdmGradebookRefreshInstructions();
}

function sdmGradebookQueueError_() {
  throw new Error('Gradebook refresh queue needs reconciliation. No new request was created.');
}

function sdmGradebookUuid_(value) {
  return typeof value === 'string' &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
}

function sdmGradebookIsoTime_(value) {
  if (typeof value !== 'string' ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) ||
      isNaN(Date.parse(value))) return null;
  return new Date(value).toISOString();
}

function sdmGradebookQueueRecord_(workbook, kind) {
  var key = SDM_GRADEBOOK_QUEUE_.prefix + kind + '.v1';
  var records = workbook.createDeveloperMetadataFinder().withKey(key).find();
  if (records.length > 1) sdmGradebookQueueError_();
  if (!records.length) return null;
  var record = records[0];
  if (String(record.getVisibility()) !== 'DOCUMENT' ||
      String(record.getLocation().getLocationType()) !== 'SPREADSHEET' ||
      (kind !== 'request' && record.getId() !== SDM_GRADEBOOK_QUEUE_.ids[kind])) {
    sdmGradebookQueueError_();
  }
  var value = record.getValue(), data;
  if (typeof value !== 'string' || value.length > SDM_GRADEBOOK_QUEUE_.maxValueChars) {
    sdmGradebookQueueError_();
  }
  try { data = JSON.parse(value); } catch (ignored) { sdmGradebookQueueError_(); }
  if (!data || Array.isArray(data) || data.v !== 1) sdmGradebookQueueError_();
  return {metadata: record, data: data};
}

function sdmGradebookValidateRequest_(data) {
  if (Object.keys(data).sort().join(',') !== 'action,created_at,id,v,workbook_id' ||
      !sdmGradebookUuid_(data.id) || data.action !== 'REFRESH_BOTH' ||
      data.workbook_id !== SDM_GRADEBOOK_MENU_BINDING_.workbookId ||
      !sdmGradebookIsoTime_(data.created_at) || Date.parse(data.created_at) > Date.now() + 30000) {
    sdmGradebookQueueError_();
  }
}

function sdmGradebookQueueState_(workbook) {
  var result = {};
  ['request', 'claim', 'applied', 'status', 'heartbeat'].forEach(function (kind) {
    result[kind] = sdmGradebookQueueRecord_(workbook, kind);
  });
  if (result.request) sdmGradebookValidateRequest_(result.request.data);
  ['claim', 'applied'].forEach(function (kind) {
    if (result[kind] && (!result.request || result[kind].data.id !== result.request.data.id)) {
      sdmGradebookQueueError_();
    }
  });
  if (result.applied && !result.claim) sdmGradebookQueueError_();
  if (result.status) sdmGradebookValidateStatus_(result.status.data);
  return result;
}

function sdmGradebookValidateStatus_(status) {
  if (!sdmGradebookUuid_(status.id) || status.workbook_id !== SDM_GRADEBOOK_MENU_BINDING_.workbookId ||
      SDM_GRADEBOOK_QUEUE_.states.indexOf(status.state) === -1 ||
      !sdmGradebookIsoTime_(status.updated_at)) sdmGradebookQueueError_();
}

function sdmGradebookHeartbeatReady_(heartbeat) {
  if (!heartbeat) return false;
  var data = heartbeat.data, time = sdmGradebookIsoTime_(data.updated_at);
  var age = time ? Date.now() - Date.parse(time) : Infinity;
  return data.state === 'READY' && data.workbook_id === SDM_GRADEBOOK_MENU_BINDING_.workbookId &&
    age >= -30000 && age <= SDM_GRADEBOOK_QUEUE_.heartbeatMaxAgeMs;
}

function sdmGradebookRequestRefresh() {
  var workbook = sdmGradebookWorkbook_();
  sdmGradebookValidateLayout_(workbook);
  var ui = SpreadsheetApp.getUi();
  if (ui.alert('Refresh both courses from Canvas?',
    'Save your edits and keep this workbook idle until refresh progress reports VERIFIED. ' +
    'The local worker refreshes the two mirrors and preserves pending Edit proposals. ' +
    'Canvas is read with GET requests only. No grades are sent to Canvas.', ui.ButtonSet.OK_CANCEL) !== ui.Button.OK) {
    return;
  }
  var lock = LockService.getDocumentLock(), acquired = false, result;
  try {
    acquired = !!lock && lock.tryLock(5000);
    if (!acquired) throw new Error('Another menu request is running. Please check refresh progress.');
    var state = sdmGradebookQueueState_(workbook);
    if (state.request) {
      result = 'A refresh request already exists. Check Show refresh progress; a second request was not added.';
    } else {
      // A released HELD receipt is historical. No request/claim/applied marker
      // remains, and only a fresh READY worker can authorize a new enqueue.
      if (state.status && ['VERIFIED', 'HELD'].indexOf(state.status.data.state) === -1) {
        sdmGradebookQueueError_();
      }
      if (!sdmGradebookHeartbeatReady_(state.heartbeat)) {
        throw new Error('The local gradebook worker is not ready. Wake the Mac or reconnect the worker, then try again. No request was queued.');
      }
      var request = {v: 1, id: Utilities.getUuid().toLowerCase(), action: 'REFRESH_BOTH',
        created_at: new Date().toISOString(), workbook_id: SDM_GRADEBOOK_MENU_BINDING_.workbookId};
      sdmGradebookValidateRequest_(request);
      var serialized = JSON.stringify(request);
      if (serialized.length > 2048) sdmGradebookQueueError_();
      workbook.addDeveloperMetadata(SDM_GRADEBOOK_QUEUE_.prefix + 'request.v1', serialized,
        SpreadsheetApp.DeveloperMetadataVisibility.DOCUMENT);
      SpreadsheetApp.flush();
      var readback = sdmGradebookQueueRecord_(workbook, 'request');
      if (!readback || JSON.stringify(readback.data) !== serialized) {
        throw new Error('Request confirmation is uncertain. Check refresh progress or ask for reconciliation; do not create another request.');
      }
      result = 'Refresh queued for the local worker. Keep this workbook idle and use Show refresh progress. ' +
        'The mirrors are updated only after validation; completion requires VERIFIED status.';
    }
  } finally {
    if (acquired) lock.releaseLock();
  }
  ui.alert('Canvas gradebook refresh', result, ui.ButtonSet.OK);
}

function sdmGradebookSafeProgress_(state) {
  var lines = [];
  if (state.request) {
    lines.push('Request queued at: ' + sdmGradebookIsoTime_(state.request.data.created_at));
    if (state.status && state.status.data.id !== state.request.data.id) {
      lines.push('State: QUEUED (the prior receipt belongs to another request)');
      return lines.join('\n');
    }
  }
  if (state.status) {
    var status = state.status.data;
    sdmGradebookValidateStatus_(status);
    lines.push('State: ' + status.state);
    lines.push('Status time: ' + sdmGradebookIsoTime_(status.updated_at));
    ['core', 'advanced'].forEach(function (course) {
      var summary = status.summary && status.summary[course];
      if (!summary || typeof summary !== 'object') return;
      var counts = [];
      ['students', 'assignments', 'pending_edits'].forEach(function (key) {
        var value = summary[key];
        if (typeof value === 'number' && isFinite(value) && value >= 0 && Math.floor(value) === value) {
          counts.push(key.replace('_', ' ') + ': ' + value);
        }
      });
      if (counts.length) lines.push((course === 'core' ? 'Core' : 'Advanced') + ' — ' + counts.join(', '));
    });
  } else if (state.request) {
    lines.push('State: ' + (state.applied ? 'VERIFYING' : state.claim ? 'CLAIMED' : 'QUEUED'));
  } else {
    lines.push('No refresh request or completion receipt is recorded.');
  }
  return lines.join('\n');
}

function sdmGradebookShowProgress() {
  var workbook = sdmGradebookWorkbook_();
  sdmGradebookValidateLayout_(workbook);
  var state = sdmGradebookQueueState_(workbook);
  var text = sdmGradebookSafeProgress_(state) + '\n\nLocal worker: ' +
    (sdmGradebookHeartbeatReady_(state.heartbeat) ? 'READY' : 'not currently READY') +
    '\nKeep this workbook idle while a refresh runs. If status is HELD or UNCERTAIN, ' +
    'ask Codex to reconcile the existing request. No Canvas writes are performed.';
  var ui = SpreadsheetApp.getUi();
  ui.alert('Canvas gradebook refresh progress', text, ui.ButtonSet.OK);
}

function sdmGradebookStoredStatus_(workbook, course) {
  var sheet = sdmGradebookSheet_(workbook, course.syncId, course.syncName);
  // These cells contain only course identity, origin, time and an aggregate.
  // Never read score grids, student rows, reference tabs or script properties.
  var identity = sheet.getRange('A3:B5').getValues();
  var pending = sheet.getRange('A10:B10').getValues();
  if (identity.length !== 3 || identity[0][0] !== 'Canvas course ID' ||
      String(identity[0][1]) !== course.courseId || identity[1][0] !== 'Canvas origin' ||
      identity[1][1] !== SDM_GRADEBOOK_MENU_BINDING_.origin ||
      identity[2][0] !== 'Snapshot time' || pending.length !== 1 ||
      pending[0][0] !== 'Pending at refresh') {
    throw new Error('Gradebook menu stopped: stored refresh metadata does not match the configured course.');
  }
  var rawTime = identity[2][1], time;
  if (rawTime instanceof Date && !isNaN(rawTime.getTime())) {
    time = rawTime.toISOString();
  } else if (typeof rawTime === 'string' &&
      /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(rawTime) &&
      !isNaN(Date.parse(rawTime))) {
    time = new Date(rawTime).toISOString();
  } else {
    time = 'unavailable';
  }
  var rawCount = pending[0][1];
  var count = typeof rawCount === 'number' && isFinite(rawCount) && rawCount >= 0 &&
    Math.floor(rawCount) === rawCount ? String(rawCount) : 'unavailable';
  return course.label + ': snapshot time ' + time + '\nPending edits at that refresh: ' + count;
}

function sdmGradebookShowStatus() {
  var workbook = sdmGradebookWorkbook_();
  sdmGradebookValidateLayout_(workbook);
  var lines = SDM_GRADEBOOK_MENU_BINDING_.courses.map(function (course) {
    return sdmGradebookStoredStatus_(workbook, course);
  });
  var ui = SpreadsheetApp.getUi();
  ui.alert('Stored mirror refresh status', lines.join('\n\n') +
    '\n\nThis is stored metadata, not a live Canvas check. It does not verify the local baseline or ' +
    'count edits made since the last refresh.', ui.ButtonSet.OK);
}

function sdmGradebookOpen_(index) {
  var workbook = sdmGradebookWorkbook_();
  sdmGradebookValidateLayout_(workbook);
  var course = SDM_GRADEBOOK_MENU_BINDING_.courses[index];
  workbook.setActiveSheet(sdmGradebookSheet_(workbook, course.getId, course.getName));
}

function sdmGradebookOpenCore() {
  sdmGradebookOpen_(0);
}

function sdmGradebookOpenAdvanced() {
  sdmGradebookOpen_(1);
}
