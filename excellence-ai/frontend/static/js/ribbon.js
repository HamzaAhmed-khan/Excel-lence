/**
 * ribbon.js — Ribbon tab switching, AI Copilot toggle,
 * floating dock and New-workbook wiring.
 */
const Ribbon = (() => {
  function init() {
    initTabs();
    initCopilotToggle();
    initDock();
    initHamburger();
    initViewBtns();
    initNewBtn();
    initDownloadBtn();
  }

  // ── Ribbon tabs ────────────────────────────────────────────────────────────
  function initTabs() {
    document.querySelectorAll('.ribbon-tab').forEach(tab => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.ribbon-tab').forEach(t => t.classList.remove('active'));
        tab.classList.add('active');
      });
    });
  }

  // ── Copilot panel show/hide ────────────────────────────────────────────────
  function initCopilotToggle() {
    document.querySelectorAll('[data-action="toggle-copilot"]').forEach(btn => {
      btn.addEventListener('click', () => {
        document.getElementById('copilot-panel')?.classList.toggle('hidden');
      });
    });
  }

  // ── Floating dock ──────────────────────────────────────────────────────────
  function initDock() {
    const panel = document.getElementById('copilot-panel');
    const input = document.getElementById('copilot-input');

    // Centre sparkle orb — open copilot and focus input
    document.getElementById('dock-center')?.addEventListener('click', () => {
      panel?.classList.remove('hidden');
      input?.focus();
    });

    // Dock action buttons — open copilot and pre-fill a prompt
    const dockPrompts = {
      'dock-import':  'Import data from a URL or paste a table here',
      'dock-extract': 'Extract data from a PDF or image',
      'dock-clean':   'Clean and normalize all data in this sheet',
      'dock-chart':   'Generate a chart from the data in this sheet',
    };

    Object.entries(dockPrompts).forEach(([id, prompt]) => {
      document.getElementById(id)?.addEventListener('click', () => {
        panel?.classList.remove('hidden');
        if (input) {
          input.value = prompt;
          input.focus();
          // Trigger resize
          input.dispatchEvent(new Event('input'));
        }
      });
    });
  }

  // ── Hamburger (sidebar collapse) ───────────────────────────────────────────
  function initHamburger() {
    document.getElementById('hamburger-btn')?.addEventListener('click', () => {
      document.getElementById('sidebar')?.classList.toggle('collapsed');
    });
  }

  // ── View toggle buttons ────────────────────────────────────────────────────
  function initViewBtns() {
    document.querySelectorAll('.view-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.view-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
      });
    });
  }

  // ── Sidebar "+ New" button ─────────────────────────────────────────────────
  function initNewBtn() {
    // Expose a hook so app.js can override it once it knows the state
    document.querySelector('.btn-new')?.addEventListener('click', () => {
      // Dispatch a custom event that app.js listens to
      document.dispatchEvent(new CustomEvent('excellence:new-workbook'));
    });
  }

  // ── Workbook title bar download ────────────────────────────────────────────
  function initDownloadBtn() {
    document.querySelector('.wb-save-btn')?.addEventListener('click', () => {
      document.dispatchEvent(new CustomEvent('excellence:download-workbook'));
    });
  }

  return { init };
})();
