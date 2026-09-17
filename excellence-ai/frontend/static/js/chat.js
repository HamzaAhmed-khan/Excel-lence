/**
 * chat.js — AI Copilot panel logic.
 * No hardcoded demo data. Connects to /api/chat for all AI operations.
 */
const Chat = (() => {
  let _workbook    = null;
  let _sheet       = null;
  let _initialized = false;

  function init(workbook, sheet) {
    _workbook = workbook;
    _sheet    = sheet;

    if (_initialized) return;
    _initialized = true;

    const form  = document.getElementById('copilot-form');
    const input = document.getElementById('copilot-input');

    form?.addEventListener('submit', e => {
      e.preventDefault();
      const msg = input.value.trim();
      if (!msg) return;
      input.value = '';
      autoResize(input);
      sendMessage(msg);
    });

    input?.addEventListener('keydown', e => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        form?.dispatchEvent(new Event('submit'));
      }
    });

    input?.addEventListener('input', () => autoResize(input));

    // URL scrape button (inside copilot panel)
    document.getElementById('url-scrape-btn')?.addEventListener('click', handleUrlScrape);
    document.getElementById('url-input')?.addEventListener('keydown', e => {
      if (e.key === 'Enter') handleUrlScrape();
    });
  }

  function setContext(workbook, sheet) {
    _workbook = workbook;
    _sheet    = sheet;
  }

  // ── URL scraping ──────────────────────────────────────────────────────────
  async function handleUrlScrape() {
    if (!_workbook) {
      appendAIBubble('Please open or create a workbook first.');
      return;
    }
    const urlInput = document.getElementById('url-input');
    const url = urlInput?.value.trim();
    if (!url) return;

    urlInput.value = '';
    appendAIBubble('Scraping <em>' + escHtml(url) + '</em>…');
    showTyping();

    try {
      const resp = await fetch('/api/extract/url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ url, workbook: _workbook, sheet: _sheet }),
      });
      removeTyping();

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        appendError(err.detail || 'Could not scrape URL.');
        return;
      }
      handleResponse(await resp.json());
    } catch (err) {
      removeTyping();
      appendError('Network error: ' + err.message);
    }
  }

  function autoResize(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 100) + 'px';
  }

  async function sendMessage(text) {
    if (!_workbook) {
      appendAIBubble('Please open or create a workbook first.');
      return;
    }

    appendUserBubble(text);
    showTyping();

    try {
      const resp = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ workbook: _workbook, sheet: _sheet, message: text }),
      });
      removeTyping();

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: 'Unknown error' }));
        appendAIBubble('Error: ' + escHtml(err.detail || err.error || 'Something went wrong.'));
        return;
      }

      handleResponse(await resp.json());
    } catch (err) {
      removeTyping();
      appendAIBubble('Network error: ' + escHtml(err.message));
    }
  }

  function handleResponse(data) {
    if (data.status === 'preview') {
      appendAIBubble('Here\'s what I\'ll do: <em>' + escHtml(data.audit || '') + '</em>');
      renderPreviewCard(data);
    } else if (data.status === 'answer') {
      appendAIBubble(escHtml(data.message || 'Done!'));
    } else if (data.status === 'clarify') {
      appendClarifyBubble(data.question);
    } else if (data.status === 'applied') {
      appendAIBubble('Done! ' + escHtml(data.summary || ''));
      if (data.refreshed_sheet) Grid.setData(data.refreshed_sheet);
      if (data.chart_spec)     renderChartNotice(data.chart_spec);
    } else if (data.status === 'multi_table') {
      renderDisambiguation(data);
    }
  }

  // Called from app.js when extract/image returns directly
  function handleExternalPreview(data) {
    if (!data) return;
    document.getElementById('copilot-panel')?.classList.remove('hidden');
    handleResponse(data);
  }

  // ── Preview card ──────────────────────────────────────────────────────────
  function renderPreviewCard(data) {
    const messages = document.getElementById('copilot-messages');
    if (!messages) return;
    const proposed = data.proposed || {};
    const phase    = data.phase;

    let tableHtml = '';
    if (phase === 'phase1' && proposed.headers) {
      tableHtml = buildPreviewTable(proposed.headers, proposed.rows || []);
    } else if (phase === 'phase2') {
      if (proposed.formulas && proposed.formulas.length) {
        tableHtml = buildPreviewTable(['Cell', 'Formula'],
          proposed.formulas.map(f => [f.cell, f.formula]));
      } else if (proposed.cell_edits && proposed.cell_edits.length) {
        tableHtml = buildPreviewTable(['Cell', 'New Value'],
          proposed.cell_edits.map(e => [e.cell, String(e.value)]));
      } else if (proposed.row_indices && proposed.row_indices.length) {
        tableHtml = buildPreviewTable(['Action', 'Details'], [
          ['Delete rows', 'Excel rows: ' + proposed.row_indices.join(', ')],
          ['Row count', proposed.row_indices.length + ' row(s) will be removed'],
        ]);
      } else if (proposed.col_names && proposed.col_names.length) {
        tableHtml = buildPreviewTable(['Action', 'Columns to delete'],
          proposed.col_names.map(c => ['Delete column', c]));
      } else if (proposed.sort_by) {
        tableHtml = buildPreviewTable(['Action', 'Details'], [
          ['Sort by', proposed.sort_by],
          ['Order', proposed.sort_ascending ? 'Ascending (A→Z / 1→9)' : 'Descending (Z→A / 9→1)'],
        ]);
      } else if (proposed.new_table) {
        tableHtml = buildPreviewTable(
          proposed.new_table.headers || [],
          (proposed.new_table.rows || []).slice(0, 5)
        );
      }
    } else if (phase === 'phase3') {
      tableHtml = buildPreviewTable(
        ['Property', 'Value'],
        Object.entries(proposed).filter(([k]) => k !== 'clarify').map(([k, v]) => [k, String(v)])
      );
    }

    // Confidence badge (phase1 only)
    let confBadge = '';
    if (phase === 'phase1' && proposed.confidence != null) {
      const pct = Math.round(proposed.confidence * 100);
      const lvl = pct >= 80 ? 'high' : pct >= 55 ? 'medium' : 'low';
      confBadge = '<span class="conf-badge conf-' + lvl + '">' + pct + '% confidence</span>';
    }

    // Row count note
    let rowNote = '';
    if (phase === 'phase1' && proposed.total_rows > (proposed.rows || []).length) {
      rowNote = '<div style="padding:2px 12px 6px;font-size:11px;color:#6B7280">Showing first ' +
        (proposed.rows || []).length + ' of ' + proposed.total_rows + ' rows</div>';
    }

    const card = document.createElement('div');
    card.className = 'preview-card';
    card.innerHTML =
      '<div class="preview-card-head">' +
        '<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style="color:#047857">' +
          '<path d="M12 2L13.5 8.5L20 10L13.5 11.5L12 18L10.5 11.5L4 10L10.5 8.5Z"/>' +
        '</svg>' +
        '<span>' +
          (phase === 'phase1' ? 'Preview — Data Extraction' :
           phase === 'phase2' ? 'Preview — Calculation' : 'Preview — Chart') +
        '</span>' +
        confBadge +
      '</div>' +
      '<div style="padding:8px;overflow-x:auto;">' + tableHtml + '</div>' +
      rowNote +
      (proposed.notes
        ? '<div style="padding:4px 12px 8px;font-size:11px;color:#6B7280"><em>' + escHtml(proposed.notes) + '</em></div>'
        : '') +
      '<div class="preview-actions">' +
        '<button class="btn-confirm">Confirm</button>' +
        '<button class="btn-discard">Discard</button>' +
      '</div>';

    card.querySelector('.btn-confirm').addEventListener('click', () => confirmPreview(data.preview_id, card));
    card.querySelector('.btn-discard').addEventListener('click', () => card.remove());

    messages.appendChild(card);
    messages.scrollTop = messages.scrollHeight;
  }

  // ── Multi-table disambiguation ────────────────────────────────────────────
  function renderDisambiguation(data) {
    const messages = document.getElementById('copilot-messages');
    if (!messages) return;

    const card = document.createElement('div');
    card.className = 'disambig-card';

    const tablesHtml = (data.tables || []).map((t, i) => {
      const previewHeaders = (t.headers || []).slice(0, 4);
      const previewRows    = (t.preview_rows || t.sample_rows || []).slice(0, 3);
      let miniHtml = '<table class="table-mini"><thead><tr>';
      previewHeaders.forEach(h => { miniHtml += '<th>' + escHtml(String(h)) + '</th>'; });
      if ((t.headers || []).length > 4) miniHtml += '<th>…</th>';
      miniHtml += '</tr></thead><tbody>';
      previewRows.forEach(row => {
        miniHtml += '<tr>';
        (row || []).slice(0, 4).forEach(cell => { miniHtml += '<td>' + escHtml(String(cell ?? '')) + '</td>'; });
        if ((row || []).length > 4) miniHtml += '<td>…</td>';
        miniHtml += '</tr>';
      });
      miniHtml += '</tbody></table>';

      return '<div class="table-candidate">' +
        '<div class="table-candidate-title">' + escHtml(t.caption || ('Table ' + (i + 1))) + '</div>' +
        '<div class="table-candidate-meta">' + t.row_count + ' rows · ' + (t.headers || []).length + ' columns</div>' +
        miniHtml +
        '<button class="btn-use-table" data-index="' + i + '">Use This Table</button>' +
      '</div>';
    }).join('');

    card.innerHTML =
      '<div class="disambig-header">' +
        '<strong>' + (data.tables || []).length + ' tables found</strong> on ' +
        escHtml(data.page_title || data.url) + ' — choose one to import:' +
      '</div>' +
      tablesHtml;

    card.querySelectorAll('.btn-use-table').forEach(btn => {
      btn.addEventListener('click', async () => {
        const idx = parseInt(btn.dataset.index, 10);
        btn.textContent = 'Loading…';
        btn.disabled    = true;

        try {
          const resp = await fetch('/api/extract/url/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            credentials: 'include',
            body: JSON.stringify({
              scrape_id:   data.scrape_id,
              table_index: idx,
              workbook:    _workbook,
              sheet:       _sheet,
            }),
          });

          if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            appendError(err.detail || 'Failed to load table.');
            btn.textContent = 'Use This Table';
            btn.disabled    = false;
            return;
          }

          card.remove();
          handleResponse(await resp.json());
        } catch (err) {
          appendError('Network error: ' + err.message);
          btn.textContent = 'Use This Table';
          btn.disabled    = false;
        }
      });
    });

    messages.appendChild(card);
    messages.scrollTop = messages.scrollHeight;
  }

  function buildPreviewTable(headers, rows) {
    let h = '<table class="preview-table"><thead><tr>';
    headers.forEach(c => { h += '<th>' + escHtml(String(c)) + '</th>'; });
    h += '</tr></thead><tbody>';
    (rows || []).slice(0, 6).forEach(row => {
      h += '<tr>';
      (Array.isArray(row) ? row : [row]).forEach(cell => {
        h += '<td>' + escHtml(String(cell ?? '')) + '</td>';
      });
      h += '</tr>';
    });
    return h + '</tbody></table>';
  }

  async function confirmPreview(previewId, cardEl) {
    const btn = cardEl.querySelector('.btn-confirm');
    if (btn) { btn.textContent = 'Applying…'; btn.disabled = true; }

    try {
      const resp = await fetch('/api/chat/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ preview_id: previewId, workbook: _workbook, sheet: _sheet }),
      });

      if (!resp.ok) {
        const err = await resp.json().catch(() => ({ error: 'Failed' }));
        appendAIBubble('Apply failed: ' + escHtml(err.detail || err.error || 'Unknown error'));
        if (btn) { btn.textContent = 'Confirm'; btn.disabled = false; }
        return;
      }

      const data = await resp.json();
      cardEl.remove();
      appendAIBubble('Applied. ' + escHtml(data.summary || ''));
      if (data.refreshed_sheet) Grid.setData(data.refreshed_sheet);
      if (data.chart_spec)     renderChartNotice(data.chart_spec);
    } catch (err) {
      appendAIBubble('Network error: ' + escHtml(err.message));
      if (btn) { btn.textContent = 'Confirm'; btn.disabled = false; }
    }
  }

  // ── Bubble helpers ────────────────────────────────────────────────────────
  function appendUserBubble(text) {
    _append('msg-user', escHtml(text));
  }

  function appendAIBubble(html) {
    _append('msg-ai', html);
  }

  function appendClarifyBubble(question) {
    _append('msg-clarify', '<strong>Clarification needed:</strong> ' + escHtml(question));
  }

  function appendInfo(text) {
    _append('msg-hint', escHtml(text));
  }

  function appendError(text) {
    _append('msg-clarify', '<strong>Error:</strong> ' + escHtml(text));
  }

  function _append(cls, html) {
    const messages = document.getElementById('copilot-messages');
    if (!messages) return;
    const div = document.createElement('div');
    div.className = cls;
    div.innerHTML = html;
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function showTyping() {
    const messages = document.getElementById('copilot-messages');
    if (!messages) return;
    const div = document.createElement('div');
    div.id = 'typing-indicator';
    div.className = 'typing-indicator';
    div.innerHTML =
      '<div class="typing-dot"></div>' +
      '<div class="typing-dot"></div>' +
      '<div class="typing-dot"></div>';
    messages.appendChild(div);
    messages.scrollTop = messages.scrollHeight;
  }

  function removeTyping() {
    document.getElementById('typing-indicator')?.remove();
  }

  // ── Chart notice ──────────────────────────────────────────────────────────
  function renderChartNotice(spec) {
    appendAIBubble(
      'Chart <strong>' + escHtml(spec.title || '') + '</strong> has been added to the workbook. ' +
      'Download the file to view it in Excel.'
    );
  }

  // ── SVG bar chart (for inline data display) ───────────────────────────────
  function renderBarChart(container, labels, values, title, unit) {
    unit = unit || '';
    const W = 290, H = 160;
    const PAD = { top: 20, right: 10, bottom: 50, left: 38 };
    const bW = W - PAD.left - PAD.right;
    const bH = H - PAD.top - PAD.bottom;
    const n   = labels.length;
    const barW   = Math.max(4, Math.floor(bW / n) - 3);
    const maxVal = Math.max(...values, 1);
    const yTicks = [0, 25, 50, 75, 100];

    let svg = '<svg class="chart-svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H + '" xmlns="http://www.w3.org/2000/svg">';

    yTicks.forEach(t => {
      const y = PAD.top + bH - (t / maxVal) * bH;
      svg += '<line x1="' + PAD.left + '" y1="' + y.toFixed(1) + '" x2="' + (W - PAD.right) + '" y2="' + y.toFixed(1) + '" class="chart-grid"/>';
      svg += '<text x="' + (PAD.left - 5) + '" y="' + (y + 4).toFixed(1) + '" text-anchor="end" class="chart-label">' + t + unit + '</text>';
    });

    svg += '<line x1="' + PAD.left + '" y1="' + PAD.top + '" x2="' + PAD.left + '" y2="' + (PAD.top + bH) + '" class="chart-axis"/>';
    svg += '<line x1="' + PAD.left + '" y1="' + (PAD.top + bH) + '" x2="' + (W - PAD.right) + '" y2="' + (PAD.top + bH) + '" class="chart-axis"/>';

    values.forEach((val, i) => {
      const x  = PAD.left + i * (bW / n) + 2;
      const bh = (val / maxVal) * bH;
      const y  = PAD.top + bH - bh;
      svg += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + barW + '" height="' + bh.toFixed(1) + '" fill="#10B981" rx="2"><title>' + labels[i] + ': ' + val + unit + '</title></rect>';
      const lx = x + barW / 2, ly = PAD.top + bH + 8;
      svg += '<text x="' + lx.toFixed(1) + '" y="' + ly + '" text-anchor="end" transform="rotate(-35 ' + lx.toFixed(1) + ' ' + ly + ')" class="chart-label" font-size="9">' + escHtml(labels[i]) + '</text>';
    });

    svg += '<text x="' + (W / 2) + '" y="12" text-anchor="middle" class="chart-label" font-size="11" font-weight="600" fill="#111827">' + escHtml(title) + '</text>';
    svg += '</svg>';
    container.innerHTML = svg;
  }

  function escHtml(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  return { init, setContext, sendMessage, handleExternalPreview, appendInfo, appendError, renderBarChart };
})();
