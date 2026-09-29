/*
 * Central gradebook menu repair. No network transport or sheet-data writes.
 *
 * INSTALLATION CONTRACT: this is replacement source, not an extra competing
 * onOpen file. Preserve the full bound project first. Replace its existing
 * onOpen and all four legacy wrapper definitions with the definitions below,
 * and add the uniquely named sdmGradebook* helpers. Keep the old runtime and
 * ownership guards unchanged. Verify exactly one definition of each handler
 * in the complete project, exact parent workbook, and complete source readback.
 * This menu supplies navigation/status/guidance; it does not refresh Canvas.
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
    'Refresh is agent-assisted. In your Canvas MCP Codex task, ask:\n\n' +
    '"Refresh both Canvas gradebook mirror tabs from Canvas GETs, preserving pending Edit proposals ' +
    'and the Student Info and Assignment reference tabs. No Canvas writes."\n\n' +
    'The agent prepares and verifies the refresh using the trusted local baselines. ' +
    'This menu does not contact Canvas or refresh any data.\n\n' +
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
