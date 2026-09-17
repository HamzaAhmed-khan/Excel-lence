/**
 * app.js — ExcelLence AI main controller.
 * Wires ribbon, formula bar, file watcher, workbook CRUD.
 * Every ribbon button does something real.
 */
(async function () {
  const state = {
    workbook:  null,
    sheet:     null,
    sheets:    [],
    zoom:      100,
    workbooks: [],
    linkedFile: null,   // local_path if a file is linked
    freezeRow: false,
    freezeCol: false,
    gridlines: true,
  };

  // ── Boot ─────────────────────────────────────────────────────────────────
  await boot();
  initRibbon();
  initFormulaBar();
  initKeyboard();
  initModals();

  async function boot() {
    try {
      const resp = await fetch('/api/workbooks', { credentials: 'include' });
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      state.workbooks = await resp.json();
      renderSidebar();
      if (!state.workbooks.length) { showEmptyState(); Chat.init(null, null); return; }
      await openWorkbook(state.workbooks[0]);
    } catch (err) {
      console.error('Boot:', err);
      showEmptyState();
      Chat.init(null, null);
    }
  }

  async function openWorkbook(wb) {
    state.workbook = wb.name;
    state.sheets   = wb.sheets && wb.sheets.length ? wb.sheets : ['Sheet1'];
    state.sheet    = state.sheets[0];
    updateFilename();
    renderSidebar();
    initSheetTabs();
    Chat.init(state.workbook, state.sheet);
    await loadSheet(state.workbook, state.sheet);
    updateStatus('Ready');
    // Check if this workbook has a linked file
    checkLinkedFile();
  }

  // ── Linked file status ────────────────────────────────────────────────────
  async function checkLinkedFile() {
    if (!state.workbook) return;
    try {
      const r = await fetch('/api/filewatcher/status/' + encodeURIComponent(state.workbook), { credentials: 'include' });
      if (!r.ok) return;
      const d = await r.json();
      if (d.linked) {
        state.linkedFile = d.local_path;
        showLinkedPill(d.filename || d.local_path);
      } else {
        state.linkedFile = null;
        hideLinkedPill();
      }
    } catch { /* ignore */ }
  }

  function showLinkedPill(name) {
    const sec = document.getElementById('linked-file-section');
    const pill = document.getElementById('linked-pill-name');
    const syncBtn  = document.getElementById('rb-sync-in');
    const saveBtn  = document.getElementById('rb-save-back');
    const lbl      = document.getElementById('rg-filesync-label');
    if (sec)  sec.style.display = '';
    if (pill) pill.textContent = name;
    if (syncBtn) syncBtn.style.display = '';
    if (saveBtn) saveBtn.style.display = '';
    if (lbl)    lbl.style.display = '';
  }

  function hideLinkedPill() {
    const sec = document.getElementById('linked-file-section');
    const syncBtn  = document.getElementById('rb-sync-in');
    const saveBtn  = document.getElementById('rb-save-back');
    const lbl      = document.getElementById('rg-filesync-label');
    if (sec)  sec.style.display = 'none';
    if (syncBtn) syncBtn.style.display = 'none';
    if (saveBtn) saveBtn.style.display = 'none';
    if (lbl)    lbl.style.display = 'none';
  }

  // ── Sidebar ───────────────────────────────────────────────────────────────
  function renderSidebar() {
    const list = document.getElementById('wb-list');
    if (!list) return;
    if (!state.workbooks.length) {
      list.innerHTML = '<div class="wb-empty">No workbooks yet.<br>Click + New Workbook to start.</div>';
      return;
    }
    list.innerHTML = '';
    state.workbooks.forEach(wb => {
      const item = document.createElement('div');
      item.className = 'wb-item' + (wb.name === state.workbook ? ' active' : '');
      item.innerHTML =
        '<svg width="13" height="13"><use href="#icon-file"/></svg>' +
        '<span class="wb-name">' + escHtml(wb.name.replace(/\.xlsx$/i, '')) + '</span>';
      item.addEventListener('click', () => openWorkbook(wb));
      list.appendChild(item);
    });
  }

  // ── New workbook ──────────────────────────────────────────────────────────
  async function createNewWorkbook() {
    const name = prompt('Workbook name (without .xlsx):');
    if (!name || !name.trim()) return;
    updateStatus('Creating…');
    try {
      const resp = await fetch('/api/workbooks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ name: name.trim() }),
      });
      if (!resp.ok) { const e = await resp.json().catch(() => ({})); alert(e.detail || 'Could not create.'); updateStatus('Ready'); return; }
      const wb = await resp.json();
      state.workbooks.unshift(wb);
      await openWorkbook(wb);
    } catch (err) { alert('Error: ' + err.message); updateStatus('Ready'); }
  }

  // ── xlsx upload ───────────────────────────────────────────────────────────
  async function handleXlsxUpload(file) {
    const fd = new FormData();
    fd.append('file', file);
    updateStatus('Uploading…');
    try {
      const resp = await fetch('/api/workbooks/upload', { method: 'POST', credentials: 'include', body: fd });
      if (!resp.ok) { const e = await resp.json().catch(() => ({})); alert(e.detail || 'Upload failed.'); updateStatus('Ready'); return; }
      const result = await resp.json();
      const listResp = await fetch('/api/workbooks', { credentials: 'include' });
      state.workbooks = listResp.ok ? await listResp.json() : state.workbooks;
      const uploaded = state.workbooks.find(w => w.name === result.name) || { name: result.name, sheets: ['Sheet1'] };
      await openWorkbook(uploaded);
    } catch (err) { alert('Error: ' + err.message); updateStatus('Ready'); }
  }

  // ── PDF extraction ────────────────────────────────────────────────────────
  async function handlePdfExtract(file) {
    if (!state.workbook) { alert('Please open or create a workbook first.'); return; }
    openCopilot();
    const fd = new FormData();
    fd.append('file', file);
    fd.append('workbook', state.workbook);
    fd.append('sheet', state.sheet || 'Sheet1');
    updateStatus('Extracting PDF…');
    Chat.appendInfo('Reading "' + file.name + '"…');
    try {
      const resp = await fetch('/api/extract/pdf', { method: 'POST', credentials: 'include', body: fd });
      if (!resp.ok) { const e = await resp.json().catch(() => ({})); Chat.appendError(e.detail || 'PDF extraction failed.'); updateStatus('Ready'); return; }
      updateStatus('Ready');
      Chat.handleExternalPreview(await resp.json());
    } catch (err) { Chat.appendError('Error: ' + err.message); updateStatus('Ready'); }
  }

  // ── Image extraction ──────────────────────────────────────────────────────
  async function handleImageExtract(file) {
    if (!state.workbook) { alert('Please open or create a workbook first.'); return; }
    openCopilot();
    const fd = new FormData();
    fd.append('file', file);
    fd.append('workbook', state.workbook);
    fd.append('sheet', state.sheet || 'Sheet1');
    updateStatus('Extracting image…');
    Chat.appendInfo('Extracting table from "' + file.name + '"…');
    try {
      const resp = await fetch('/api/extract/image', { method: 'POST', credentials: 'include', body: fd });
      if (!resp.ok) { const e = await resp.json().catch(() => ({})); Chat.appendError(e.detail || 'Image extraction failed.'); updateStatus('Ready'); return; }
      updateStatus('Ready');
      Chat.handleExternalPreview(await resp.json());
    } catch (err) { Chat.appendError('Error: ' + err.message); updateStatus('Ready'); }
  }

  // ── URL extraction ────────────────────────────────────────────────────────
  async function handleUrlExtract(url) {
    if (!state.workbook) { alert('Please open or create a workbook first.'); return; }
    openCopilot();
    Chat.appendInfo('Scraping ' + url + '…');
    updateStatus('Scraping URL…');
    try {
      const resp = await fetch('/api/extract/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ url, workbook: state.workbook, sheet: state.sheet }),
      });
      if (!resp.ok) { const e = await resp.json().catch(() => ({})); Chat.appendError(e.detail || 'Scrape failed.'); updateStatus('Ready'); return; }
      updateStatus('Ready');
      Chat.handleExternalPreview(await resp.json());
    } catch (err) { Chat.appendError('Error: ' + err.message); updateStatus('Ready'); }
  }

  // ── Undo ──────────────────────────────────────────────────────────────────
  async function handleUndo() {
    if (!state.workbook) return;
    updateStatus('Undoing…');
    try {
      const resp = await fetch('/api/workbooks/' + encodeURIComponent(state.workbook) + '/undo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ sheet: state.sheet }),
      });
      if (!resp.ok) { const e = await resp.json().catch(() => ({})); updateStatus(e.detail || 'No undo available.'); return; }
      const data = await resp.json();
      if (data.headers !== undefined) Grid.setData(data);
      updateStatus('Undo applied');
    } catch (err) { updateStatus('Undo failed: ' + err.message); }
  }

  // ── Sheet helpers ─────────────────────────────────────────────────────────
  async function loadSheet(workbook, sheet) {
    try {
      const resp = await fetch(
        '/api/workbooks/' + encodeURIComponent(workbook) + '?sheet=' + encodeURIComponent(sheet),
        { credentials: 'include' }
      );
      if (!resp.ok) throw new Error('HTTP ' + resp.status);
      Grid.setData(await resp.json());
    } catch { Grid.setData({ name: sheet, headers: [], rows: [], num_formats: {} }); }
  }

  function initSheetTabs() {
    const container = document.getElementById('sheet-tabs');
    if (!container) return;
    container.innerHTML = '';
    state.sheets.forEach(name => {
      const tab = document.createElement('div');
      tab.className = 'sheet-tab' + (name === state.sheet ? ' active' : '');
      tab.textContent = name;
      tab.addEventListener('click', () => switchSheet(name));
      container.appendChild(tab);
    });
  }

  async function switchSheet(name) {
    state.sheet = name;
    document.querySelectorAll('.sheet-tab').forEach(t =>
      t.classList.toggle('active', t.textContent === name)
    );
    Chat.setContext(state.workbook, state.sheet);
    if (state.workbook) await loadSheet(state.workbook, name);
  }

  function openCopilot() {
    document.getElementById('copilot-panel')?.classList.remove('hidden');
  }

  // ── Formula bar ───────────────────────────────────────────────────────────
  function initFormulaBar() {
    const refInput = document.getElementById('cell-ref-input');
    const valInput = document.getElementById('formula-bar-input');

    document.addEventListener('grid:cellselect', e => {
      if (refInput) refInput.value = e.detail.ref || '';
      if (valInput) valInput.value = String(e.detail.value != null ? e.detail.value : '');
    });

    valInput && valInput.addEventListener('keydown', async function(e) {
      if (e.key !== 'Enter') return;
      e.preventDefault();
      const ref = refInput ? refInput.value : '';
      const val = valInput.value;
      if (!ref || !state.workbook) return;
      // Send as an AI edit_cells request so it goes through the preview flow
      openCopilot();
      Chat.sendMessage('Set cell ' + ref + ' to: ' + val);
    });
  }

  // ── Ribbon wiring ─────────────────────────────────────────────────────────
  function initRibbon() {
    const xlsxInput = document.getElementById('file-xlsx');
    const pdfInput  = document.getElementById('file-pdf');
    const imageInput = document.getElementById('file-image');

    // Tab switching
    document.querySelectorAll('.ribbon-tab').forEach(function(tab) {
      tab.addEventListener('click', function() {
        document.querySelectorAll('.ribbon-tab').forEach(function(t) { t.classList.remove('active'); });
        document.querySelectorAll('.ribbon-panel').forEach(function(p) { p.classList.remove('active'); });
        tab.classList.add('active');
        const panel = document.getElementById('ribbon-' + tab.dataset.tab);
        if (panel) panel.classList.add('active');
      });
    });

    // ── Home tab ────────────────────────────────────────────────────────────
    document.getElementById('rb-undo') && document.getElementById('rb-undo').addEventListener('click', handleUndo);

    document.getElementById('rb-redo') && document.getElementById('rb-redo').addEventListener('click', function() {
      openCopilot();
      Chat.appendInfo('Type your next instruction or re-send a previous one.');
    });

    // Font format buttons — send via AI copilot
    document.getElementById('rb-bold') && document.getElementById('rb-bold').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      Chat.sendMessage('Bold all header cells in this sheet by applying bold formatting.');
    });
    document.getElementById('rb-italic') && document.getElementById('rb-italic').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      Chat.sendMessage('Apply italic formatting to the first data column in this sheet.');
    });
    document.getElementById('rb-underline') && document.getElementById('rb-underline').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      Chat.sendMessage('Apply underline formatting to the header row of this sheet.');
    });

    // Number format buttons
    document.getElementById('rb-dollar') && document.getElementById('rb-dollar').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      const col = _colName(Grid.getActiveCell() ? Grid.getActiveCell().col : -1);
      openCopilot();
      Chat.sendMessage('Format ' + col + ' as currency with $ sign and 2 decimal places.');
    });
    document.getElementById('rb-percent') && document.getElementById('rb-percent').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      const col = _colName(Grid.getActiveCell() ? Grid.getActiveCell().col : -1);
      openCopilot();
      Chat.sendMessage('Format ' + col + ' as percentage (multiply by 100 and add % sign).');
    });
    document.getElementById('rb-comma') && document.getElementById('rb-comma').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      const col = _colName(Grid.getActiveCell() ? Grid.getActiveCell().col : -1);
      openCopilot();
      Chat.sendMessage('Format ' + col + ' with thousands separators (e.g. 1,234,567).');
    });
    document.getElementById('rb-dec-inc') && document.getElementById('rb-dec-inc').addEventListener('click', function() {
      if (!state.workbook) return;
      openCopilot();
      Chat.sendMessage('Increase the decimal places shown in the active column by 1.');
    });
    document.getElementById('rb-dec-dec') && document.getElementById('rb-dec-dec').addEventListener('click', function() {
      if (!state.workbook) return;
      openCopilot();
      Chat.sendMessage('Decrease the decimal places shown in the active column by 1.');
    });

    // Sort / Filter
    document.getElementById('rb-sort-az') && document.getElementById('rb-sort-az').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      const active = Grid.getActiveCell();
      const col = active ? _colName(active.col) : 'the first column';
      openCopilot();
      Chat.sendMessage('Sort all data rows ascending (A→Z) by ' + col + '.');
    });
    document.getElementById('rb-sort-za') && document.getElementById('rb-sort-za').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      const active = Grid.getActiveCell();
      const col = active ? _colName(active.col) : 'the first column';
      openCopilot();
      Chat.sendMessage('Sort all data rows descending (Z→A) by ' + col + '.');
    });
    document.getElementById('rb-del-dupes') && document.getElementById('rb-del-dupes').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      Chat.sendMessage('Find and delete all duplicate rows in this sheet, keeping the first occurrence of each.');
    });

    // AI Copilot button
    document.getElementById('btn-ai-copilot') && document.getElementById('btn-ai-copilot').addEventListener('click', function() {
      document.getElementById('copilot-panel') && document.getElementById('copilot-panel').classList.toggle('hidden');
    });

    // ── Insert tab ──────────────────────────────────────────────────────────
    document.getElementById('rb-new-table') && document.getElementById('rb-new-table').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      const input = document.getElementById('copilot-input');
      if (input) { input.value = 'Create a table with columns: '; input.focus(); }
    });
    document.getElementById('rb-chart-col') && document.getElementById('rb-chart-col').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      Chat.sendMessage('Generate a column chart from the data in this sheet.');
    });
    document.getElementById('rb-chart-line') && document.getElementById('rb-chart-line').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      Chat.sendMessage('Generate a line chart from the data in this sheet to show trends.');
    });
    document.getElementById('rb-chart-pie') && document.getElementById('rb-chart-pie').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      Chat.sendMessage('Generate a pie chart from the data in this sheet showing proportions.');
    });

    // ── Data tab ────────────────────────────────────────────────────────────
    document.getElementById('rb-link-file') && document.getElementById('rb-link-file').addEventListener('click', function() {
      if (!state.workbook) { alert('Open or create a workbook first, then link a file.'); return; }
      const m = document.getElementById('link-modal');
      if (m) m.classList.remove('hidden');
      const pi = document.getElementById('link-path-input');
      if (pi) pi.focus();
    });

    document.getElementById('rb-import-xlsx') && document.getElementById('rb-import-xlsx').addEventListener('click', function() {
      if (xlsxInput) xlsxInput.click();
    });
    xlsxInput && xlsxInput.addEventListener('change', function(e) {
      const file = e.target.files && e.target.files[0];
      if (file) handleXlsxUpload(file);
      xlsxInput.value = '';
    });

    document.getElementById('rb-from-pdf') && document.getElementById('rb-from-pdf').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      if (pdfInput) pdfInput.click();
    });
    pdfInput && pdfInput.addEventListener('change', function(e) {
      const file = e.target.files && e.target.files[0];
      if (file) handlePdfExtract(file);
      pdfInput.value = '';
    });

    document.getElementById('rb-from-image') && document.getElementById('rb-from-image').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      if (imageInput) imageInput.click();
    });
    imageInput && imageInput.addEventListener('change', function(e) {
      const file = e.target.files && e.target.files[0];
      if (file) handleImageExtract(file);
      imageInput.value = '';
    });

    document.getElementById('rb-from-url') && document.getElementById('rb-from-url').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      const m = document.getElementById('url-modal');
      if (m) m.classList.remove('hidden');
      const ui = document.getElementById('url-modal-input');
      if (ui) ui.focus();
    });

    // File sync buttons
    document.getElementById('rb-sync-in') && document.getElementById('rb-sync-in').addEventListener('click', async function() {
      if (!state.workbook || !state.linkedFile) return;
      updateStatus('Syncing from local file…');
      try {
        const resp = await fetch('/api/filewatcher/sync', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ workbook: state.workbook, sheet: state.sheet }),
        });
        if (!resp.ok) { const e = await resp.json().catch(() => ({})); alert(e.detail || 'Sync failed.'); updateStatus('Ready'); return; }
        const data = await resp.json();
        if (data.refreshed_sheet) Grid.setData(data.refreshed_sheet);
        updateStatus('Synced from local file');
      } catch (err) { alert('Sync error: ' + err.message); updateStatus('Ready'); }
    });

    document.getElementById('rb-save-back') && document.getElementById('rb-save-back').addEventListener('click', async function() {
      if (!state.workbook || !state.linkedFile) return;
      if (!confirm('Write current workbook state back to ' + state.linkedFile + '?')) return;
      updateStatus('Saving back…');
      try {
        const resp = await fetch('/api/filewatcher/save-back', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ workbook: state.workbook }),
        });
        if (!resp.ok) { const e = await resp.json().catch(() => ({})); alert(e.detail || 'Save-back failed.'); updateStatus('Ready'); return; }
        const d = await resp.json();
        updateStatus('Saved to ' + d.saved_to);
        showSavedBadge();
      } catch (err) { alert('Error: ' + err.message); updateStatus('Ready'); }
    });

    // Unlink
    document.getElementById('btn-unlink') && document.getElementById('btn-unlink').addEventListener('click', async function() {
      if (!state.workbook) return;
      if (!confirm('Unlink the local file? The workbook copy will remain.')) return;
      await fetch('/api/filewatcher/unlink/' + encodeURIComponent(state.workbook), {
        method: 'DELETE', credentials: 'include',
      });
      state.linkedFile = null;
      hideLinkedPill();
    });

    // ── Formulas tab ────────────────────────────────────────────────────────
    document.getElementById('rb-autosum') && document.getElementById('rb-autosum').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      const active = Grid.getActiveCell();
      const col = active ? _colName(active.col) : 'the first numeric column';
      openCopilot();
      Chat.sendMessage('Insert a SUM formula at the bottom of ' + col + ' to total all values.');
    });
    document.getElementById('rb-autoavg') && document.getElementById('rb-autoavg').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      const active = Grid.getActiveCell();
      const col = active ? _colName(active.col) : 'the first numeric column';
      openCopilot();
      Chat.sendMessage('Insert an AVERAGE formula at the bottom of ' + col + '.');
    });
    document.getElementById('rb-autocount') && document.getElementById('rb-autocount').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      Chat.sendMessage('Insert a COUNT formula to count the number of data rows in this sheet.');
    });
    document.getElementById('rb-ask-formula') && document.getElementById('rb-ask-formula').addEventListener('click', function() {
      if (!state.workbook) { alert('Open a workbook first.'); return; }
      openCopilot();
      const input = document.getElementById('copilot-input');
      if (input) { input.value = 'Write a formula to '; input.focus(); }
    });

    // ── View tab ────────────────────────────────────────────────────────────
    initZoom();

    document.getElementById('rb-freeze-row') && document.getElementById('rb-freeze-row').addEventListener('click', function() {
      const btn = document.getElementById('rb-freeze-row');
      const ga = document.querySelector('.grid-area');
      state.freezeRow = !state.freezeRow;
      if (ga) ga.classList.toggle('freeze-row', state.freezeRow);
      if (btn) btn.classList.toggle('rb-pressed', state.freezeRow);
    });
    document.getElementById('rb-freeze-col') && document.getElementById('rb-freeze-col').addEventListener('click', function() {
      const btn = document.getElementById('rb-freeze-col');
      const ga = document.querySelector('.grid-area');
      state.freezeCol = !state.freezeCol;
      if (ga) ga.classList.toggle('freeze-col', state.freezeCol);
      if (btn) btn.classList.toggle('rb-pressed', state.freezeCol);
    });
    document.getElementById('rb-toggle-gridlines') && document.getElementById('rb-toggle-gridlines').addEventListener('click', function() {
      const btn = document.getElementById('rb-toggle-gridlines');
      state.gridlines = !state.gridlines;
      const tbl = document.querySelector('.spreadsheet');
      if (tbl) tbl.style.borderCollapse = state.gridlines ? 'collapse' : 'separate';
      document.querySelectorAll('.spreadsheet td, .spreadsheet th').forEach(function(cell) {
        cell.style.borderColor = state.gridlines ? '' : 'transparent';
      });
      if (btn) btn.classList.toggle('rb-pressed', !state.gridlines);
    });

    // ── Global buttons ──────────────────────────────────────────────────────
    document.getElementById('btn-new') && document.getElementById('btn-new').addEventListener('click', createNewWorkbook);
    document.getElementById('hamburger-btn') && document.getElementById('hamburger-btn').addEventListener('click', function() {
      const sb = document.getElementById('sidebar');
      if (sb) sb.classList.toggle('collapsed');
    });
    document.getElementById('copilot-close') && document.getElementById('copilot-close').addEventListener('click', function() {
      const cp = document.getElementById('copilot-panel');
      if (cp) cp.classList.add('hidden');
    });
    document.getElementById('btn-download-wb') && document.getElementById('btn-download-wb').addEventListener('click', function() {
      if (!state.workbook) { alert('No workbook open.'); return; }
      window.open('/api/workbooks/' + encodeURIComponent(state.workbook) + '/download', '_blank');
      showSavedBadge();
    });

    async function doLogout() {
      await fetch('/api/auth/logout', { method: 'POST', credentials: 'include' });
      window.location.href = '/login';
    }
    document.getElementById('logout-btn') && document.getElementById('logout-btn').addEventListener('click', doLogout);
    document.getElementById('logout-btn-2') && document.getElementById('logout-btn-2').addEventListener('click', doLogout);
  }

  // ── Zoom (in View tab) ────────────────────────────────────────────────────
  function initZoom() {
    const slider = document.getElementById('ribbon-zoom-slider');
    const label  = document.getElementById('zoom-pct-label');
    const minus  = document.getElementById('rb-zoom-out');
    const plus   = document.getElementById('rb-zoom-in');

    function applyZoom(val) {
      state.zoom = Math.max(50, Math.min(200, val));
      const grid = document.getElementById('grid-container');
      if (grid) grid.style.fontSize = (state.zoom / 100) * 13 + 'px';
      if (slider) slider.value = state.zoom;
      if (label)  label.textContent = state.zoom + '%';
    }
    slider && slider.addEventListener('input', function() { applyZoom(parseInt(slider.value)); });
    minus && minus.addEventListener('click',  function() { applyZoom(state.zoom - 10); });
    plus  && plus.addEventListener('click',   function() { applyZoom(state.zoom + 10); });
  }

  // ── Modals ────────────────────────────────────────────────────────────────
  function initModals() {
    // ── Link file modal ─────────────────────────────────────────────────────
    function closeLinkModal() {
      const m = document.getElementById('link-modal');
      if (m) m.classList.add('hidden');
      const errEl = document.getElementById('link-modal-err');
      if (errEl) errEl.style.display = 'none';
    }
    document.getElementById('link-modal-close') && document.getElementById('link-modal-close').addEventListener('click', closeLinkModal);
    document.getElementById('link-modal-cancel') && document.getElementById('link-modal-cancel').addEventListener('click', closeLinkModal);
    document.getElementById('link-modal') && document.getElementById('link-modal').addEventListener('click', function(e) {
      if (e.target === e.currentTarget) closeLinkModal();
    });

    document.getElementById('link-path-input') && document.getElementById('link-path-input').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        const btn = document.getElementById('link-path-submit');
        if (btn) btn.click();
      }
    });

    document.getElementById('link-path-submit') && document.getElementById('link-path-submit').addEventListener('click', async function() {
      const pathInput = document.getElementById('link-path-input');
      const errEl = document.getElementById('link-modal-err');
      const submitBtn = document.getElementById('link-path-submit');
      const path = pathInput ? pathInput.value.trim() : '';
      if (!path) {
        if (errEl) { errEl.textContent = 'Please enter a file path.'; errEl.style.display = ''; }
        return;
      }
      if (errEl) errEl.style.display = 'none';
      submitBtn.textContent = 'Linking…';
      submitBtn.disabled = true;

      try {
        const resp = await fetch('/api/filewatcher/link', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify({ workbook: state.workbook, local_path: path }),
        });
        if (!resp.ok) {
          const e = await resp.json().catch(() => ({}));
          if (errEl) { errEl.textContent = e.detail || 'Failed to link file.'; errEl.style.display = ''; }
          submitBtn.textContent = 'Link File';
          submitBtn.disabled = false;
          return;
        }
        const data = await resp.json();
        state.linkedFile = data.local_path;
        const fname = path.split(/[/\\]/).pop();
        showLinkedPill(fname);
        if (data.refreshed_sheet) Grid.setData(data.refreshed_sheet);
        if (data.sheets) {
          state.sheets = data.sheets;
          state.sheet  = data.sheets[0];
          initSheetTabs();
        }
        closeLinkModal();
        if (pathInput) pathInput.value = '';
        updateFilename();
      } catch (err) {
        if (errEl) { errEl.textContent = 'Error: ' + err.message; errEl.style.display = ''; }
      } finally {
        submitBtn.textContent = 'Link File';
        submitBtn.disabled = false;
      }
    });

    // ── URL modal ────────────────────────────────────────────────────────────
    function closeUrlModal() {
      const m = document.getElementById('url-modal');
      if (m) m.classList.add('hidden');
      const errEl = document.getElementById('url-modal-err');
      if (errEl) errEl.style.display = 'none';
    }
    document.getElementById('url-modal-close') && document.getElementById('url-modal-close').addEventListener('click', closeUrlModal);
    document.getElementById('url-modal-cancel') && document.getElementById('url-modal-cancel').addEventListener('click', closeUrlModal);
    document.getElementById('url-modal') && document.getElementById('url-modal').addEventListener('click', function(e) {
      if (e.target === e.currentTarget) closeUrlModal();
    });
    document.getElementById('url-modal-input') && document.getElementById('url-modal-input').addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        const btn = document.getElementById('url-modal-submit');
        if (btn) btn.click();
      }
    });
    document.getElementById('url-modal-submit') && document.getElementById('url-modal-submit').addEventListener('click', async function() {
      const inp = document.getElementById('url-modal-input');
      const errEl = document.getElementById('url-modal-err');
      const btn = document.getElementById('url-modal-submit');
      const url = inp ? inp.value.trim() : '';
      if (!url) {
        if (errEl) { errEl.textContent = 'Please enter a URL.'; errEl.style.display = ''; }
        return;
      }
      if (errEl) errEl.style.display = 'none';
      btn.textContent = 'Scraping…';
      btn.disabled = true;
      closeUrlModal();
      if (inp) inp.value = '';
      await handleUrlExtract(url);
      btn.textContent = 'Scrape';
      btn.disabled = false;
    });
  }

  // ── Keyboard shortcuts ────────────────────────────────────────────────────
  function initKeyboard() {
    document.addEventListener('keydown', function(e) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        const cs = document.getElementById('cmd-search');
        if (cs) cs.focus();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === 'z') {
        e.preventDefault();
        handleUndo();
      }
    });
    const cmdSearch = document.getElementById('cmd-search');
    cmdSearch && cmdSearch.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && cmdSearch.value.trim()) {
        const val = cmdSearch.value.trim();
        cmdSearch.value = '';
        openCopilot();
        Chat.sendMessage(val);
      }
    });
  }

  // ── Empty state ───────────────────────────────────────────────────────────
  function showEmptyState() {
    const container = document.getElementById('grid-container');
    if (container) {
      container.innerHTML =
        '<div class="empty-state">' +
        '<svg width="52" height="52" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="9" y1="13" x2="15" y2="13"/><line x1="9" y1="17" x2="15" y2="17"/></svg>' +
        '<h3>No workbooks yet</h3>' +
        '<p>Click <strong>+ New Workbook</strong> in the sidebar, or use the ribbon Data tab to import or link a file.</p>' +
        '<button class="btn-empty-action" onclick="document.getElementById(\'btn-new\').click()">+ New Workbook</button>' +
        '</div>';
    }
    const tabs = document.getElementById('sheet-tabs');
    if (tabs) tabs.innerHTML = '';
    updateFilename();
    updateStatus('Ready');
  }

  // ── Helpers ───────────────────────────────────────────────────────────────
  function updateStatus(msg) {
    const el = document.getElementById('status-text');
    if (el) el.textContent = msg;
  }

  function updateFilename() {
    const el = document.getElementById('wb-filename');
    if (el) el.textContent = state.workbook || 'No workbook open';
  }

  function showSavedBadge() {
    const badge = document.getElementById('wb-saved-badge');
    if (!badge) return;
    badge.style.display = '';
    clearTimeout(badge._timer);
    badge._timer = setTimeout(function() { badge.style.display = 'none'; }, 3000);
  }

  function _colName(colIdx) {
    if (colIdx < 0) return 'the numeric columns';
    const active = Grid.getActiveCell();
    if (active && active.row === 0) return 'the header row';
    try {
      const val = Grid.getValue(0, colIdx);
      if (val) return '"' + val + '" column';
    } catch (ex) { /* ignore */ }
    const LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';
    if (colIdx < 26) return 'column ' + LETTERS[colIdx];
    return 'column ' + LETTERS[Math.floor(colIdx / 26) - 1] + LETTERS[colIdx % 26];
  }

  function escHtml(str) {
    return String(str != null ? str : '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
})();
