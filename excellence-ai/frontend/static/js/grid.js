/**
 * grid.js — Spreadsheet grid renderer and cell interaction manager.
 * Public API: setData(sheetJson), getSelection(), getActiveCell()
 */
const Grid = (() => {
  let _data = { headers: [], rows: [], num_formats: {} };
  let _activeRow = -1;
  let _activeCol = -1;
  let _selStart = null;
  let _selEnd = null;
  let _editing = false;
  let _editCell = null;

  const COL_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');

  function colLetter(idx) {
    // 0-indexed: 0→A, 25→Z, 26→AA
    if (idx < 26) return COL_LETTERS[idx];
    return COL_LETTERS[Math.floor(idx / 26) - 1] + COL_LETTERS[idx % 26];
  }

  function formatValue(val, fmt) {
    if (val === null || val === undefined || val === '') return '';
    if (typeof val === 'number') {
      if (fmt && fmt.includes('%')) {
        return (val * (val <= 1 ? 100 : 1)).toFixed(2) + '%';
      }
      if (fmt && (fmt.includes('$') || fmt.includes('"$"'))) {
        return '$' + val.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
      }
      if (fmt && fmt.includes('#,##0') && !fmt.includes('.')) {
        return val.toLocaleString('en-US', { maximumFractionDigits: 0 });
      }
      if (typeof val === 'number' && Number.isFinite(val)) {
        return val.toLocaleString('en-US');
      }
    }
    return String(val);
  }

  function isNumericCol(colIdx) {
    const fmt = _data.num_formats ? _data.num_formats[colLetter(colIdx)] : null;
    if (fmt) return true;
    // Heuristic: check first 3 data rows
    for (let r = 0; r < Math.min(3, _data.rows.length); r++) {
      const v = _data.rows[r][colIdx];
      if (v !== '' && v !== null && !isNaN(Number(v))) return true;
    }
    return false;
  }

  function getNumFmt(colIdx) {
    if (_data.num_formats) {
      return _data.num_formats[colLetter(colIdx)] || null;
    }
    return null;
  }

  function render() {
    const container = document.getElementById('grid-container');
    if (!container) return;

    const numDataCols = _data.headers.length || 0;
    const numDataRows = _data.rows.length || 0;
    // Display at least 20 rows, up to data + 5 buffer
    const visibleRows = Math.max(20, numDataRows + 5);
    const visibleCols = Math.max(8, numDataCols + 3);

    let html = '<table class="spreadsheet" id="spreadsheet-table">';

    // Column headers
    html += '<thead><tr>';
    html += '<th class="row-hdr"></th>';
    for (let c = 0; c < visibleCols; c++) {
      const letter = colLetter(c);
      const isActive = c === _activeCol;
      html += `<th class="${isActive ? 'col-active' : ''}" data-col="${c}">${letter}</th>`;
    }
    html += '</tr></thead>';

    // Body
    html += '<tbody>';

    // Row 1: data header row (if we have headers)
    if (_data.headers.length > 0) {
      const isActiveRow = _activeRow === 0;
      html += `<tr class="data-header${isActiveRow ? ' row-active' : ''}" data-row="0">`;
      html += `<td class="row-hdr${isActiveRow ? ' row-hdr-active' : ''}">1</td>`;
      for (let c = 0; c < visibleCols; c++) {
        const h = c < _data.headers.length ? _data.headers[c] : '';
        const isActiveCell = _activeRow === 0 && _activeCol === c;
        const filterIcon = h ? `<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" style="display:inline;vertical-align:middle;margin-left:4px;color:#059669"><polyline points="6 9 12 15 18 9"></polyline></svg>` : '';
        html += `<td data-row="0" data-col="${c}" class="${isActiveCell ? 'cell-active' : ''}">${escHtml(h)}${filterIcon}</td>`;
      }
      html += '</tr>';
    }

    // Data rows
    const totalRowIdx = numDataRows - 1;
    for (let r = 0; r < numDataRows; r++) {
      const row = _data.rows[r];
      const isTotal = r === totalRowIdx && row[0] === 'Total';
      const isActiveRow = _activeRow === r + 1;
      html += `<tr${isTotal ? ' class="total-row"' : (isActiveRow ? ' class="row-active"' : '')} data-row="${r + 1}">`;
      html += `<td class="row-hdr${isActiveRow ? ' row-hdr-active' : ''}">${r + 2}</td>`;
      for (let c = 0; c < visibleCols; c++) {
        const val = c < row.length ? row[c] : '';
        const fmt = getNumFmt(c);
        const displayVal = formatValue(val, fmt);
        const isNum = isNumericCol(c) && c > 0;
        const isActiveCell = _activeRow === r + 1 && _activeCol === c;
        const inSel = isInSelection(r + 1, c);
        let cls = [];
        if (isNum) cls.push('num');
        if (isActiveCell) cls.push('cell-active');
        if (inSel && !isActiveCell) cls.push('cell-selected');
        html += `<td data-row="${r + 1}" data-col="${c}" class="${cls.join(' ')}">${escHtml(displayVal)}</td>`;
      }
      html += '</tr>';
    }

    // Empty buffer rows
    for (let r = numDataRows; r < visibleRows; r++) {
      const dispRow = r + (numDataRows > 0 && _data.headers.length > 0 ? 2 : 1);
      html += `<tr data-row="${r + (numDataRows > 0 ? numDataRows + 1 : 1)}">`;
      html += `<td class="row-hdr">${dispRow}</td>`;
      for (let c = 0; c < visibleCols; c++) {
        html += `<td data-row="${r + numDataRows + 1}" data-col="${c}"></td>`;
      }
      html += '</tr>';
    }

    html += '</tbody></table>';
    container.innerHTML = html;
    attachGridListeners();
  }

  function isInSelection(row, col) {
    if (!_selStart || !_selEnd) return false;
    const minR = Math.min(_selStart.row, _selEnd.row);
    const maxR = Math.max(_selStart.row, _selEnd.row);
    const minC = Math.min(_selStart.col, _selEnd.col);
    const maxC = Math.max(_selStart.col, _selEnd.col);
    return row >= minR && row <= maxR && col >= minC && col <= maxC;
  }

  function escHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  }

  function attachGridListeners() {
    const table = document.getElementById('spreadsheet-table');
    if (!table) return;

    table.addEventListener('mousedown', (e) => {
      const td = e.target.closest('td[data-row]');
      if (!td || td.classList.contains('row-hdr')) return;
      const row = parseInt(td.dataset.row);
      const col = parseInt(td.dataset.col);
      _activeRow = row;
      _activeCol = col;
      _selStart = { row, col };
      _selEnd = { row, col };
      document.dispatchEvent(new CustomEvent('grid:cellselect', {
        detail: {
          row, col,
          ref: `${colLetter(col)}${row + 1}`,
          value: row === 0
            ? (_data.headers[col] || '')
            : (_data.rows[row - 1]?.[col] ?? ''),
        }
      }));
      render();
    });

    table.addEventListener('mousemove', (e) => {
      if (!_selStart || !e.buttons) return;
      const td = e.target.closest('td[data-row]');
      if (!td || td.classList.contains('row-hdr')) return;
      const row = parseInt(td.dataset.row);
      const col = parseInt(td.dataset.col);
      if (_selEnd && _selEnd.row === row && _selEnd.col === col) return;
      _selEnd = { row, col };
      render();
    });

    table.addEventListener('dblclick', (e) => {
      const td = e.target.closest('td[data-row]');
      if (!td || td.classList.contains('row-hdr')) return;
      startEdit(td);
    });
  }

  function startEdit(td) {
    if (_editing) return;
    _editing = true;
    _editCell = td;
    const original = td.textContent;
    td.contentEditable = 'true';
    td.focus();
    // Select all text
    const range = document.createRange();
    range.selectNodeContents(td);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    td.addEventListener('keydown', onEditKeydown);
    td.addEventListener('blur', commitEdit, { once: true });
  }

  function onEditKeydown(e) {
    if (e.key === 'Escape') {
      cancelEdit();
    } else if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      commitEdit();
    }
  }

  function commitEdit() {
    if (!_editing || !_editCell) return;
    _editCell.contentEditable = 'false';
    _editCell.removeEventListener('keydown', onEditKeydown);
    _editing = false;
    _editCell = null;
  }

  function cancelEdit() {
    if (!_editing || !_editCell) return;
    _editCell.contentEditable = 'false';
    _editCell.removeEventListener('keydown', onEditKeydown);
    _editing = false;
    render(); // re-render to restore original value
    _editCell = null;
  }


  // ── Keyboard navigation ───────────────────────────────────────────────────
  document.addEventListener('keydown', (e) => {
    if (_editing) return;
    const moves = { ArrowUp: [-1,0], ArrowDown: [1,0], ArrowLeft: [0,-1], ArrowRight: [0,1] };
    if (moves[e.key]) {
      e.preventDefault();
      const [dr, dc] = moves[e.key];
      _activeRow = Math.max(0, (_activeRow === -1 ? 0 : _activeRow) + dr);
      _activeCol = Math.max(0, (_activeCol === -1 ? 0 : _activeCol) + dc);
      _selStart = { row: _activeRow, col: _activeCol };
      _selEnd = { row: _activeRow, col: _activeCol };
      render();
    }
    if (e.key === 'Escape') {
      _selStart = null;
      _selEnd = null;
      render();
    }
  });

  // ── Public API ────────────────────────────────────────────────────────────
  function setData(sheetJson) {
    _data = sheetJson || { headers: [], rows: [], num_formats: {} };
    _activeRow = -1;
    _activeCol = -1;
    _selStart = null;
    _selEnd = null;
    render();
  }

  function getSelection() {
    return { start: _selStart, end: _selEnd };
  }

  function getActiveCell() {
    if (_activeRow < 0 || _activeCol < 0) return null;
    return { row: _activeRow, col: _activeCol, ref: `${colLetter(_activeCol)}${_activeRow + 1}` };
  }

  function getValue(row, col) {
    if (row === 0) return _data.headers[col] || '';
    return _data.rows[row - 1]?.[col] ?? '';
  }

  return { setData, getSelection, getActiveCell, getValue, render };
})();
