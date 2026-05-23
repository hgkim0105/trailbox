// Trailbox Hub — small client-side enhancements. No framework, no build step.

(function () {
  'use strict';

  const html = document.documentElement;

  // ── Theme toggle ──────────────────────────────────────────────────────
  // base.html applies data-theme synchronously before paint (see <head> init).
  // This handler swaps it on click and persists.

  const SUN_PATHS = '<circle cx="8" cy="8" r="2.5"/><path d="M8 1.5V3M8 13v1.5M14.5 8H13M3 8H1.5M3.6 3.6l1 1M11.4 11.4l1 1M11.4 4.6l1-1M3.6 12.4l1-1"/>';
  const MOON_PATHS = '<path d="M13.5 9.5A6 6 0 0 1 6.5 2.5 6 6 0 1 0 13.5 9.5Z"/>';

  function currentTheme() {
    return html.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
  }

  function paintThemeIcon() {
    // Show the icon for the theme you would switch TO: dark mode → show sun.
    const next = currentTheme() === 'dark' ? SUN_PATHS : MOON_PATHS;
    document.querySelectorAll('[data-theme-icon]').forEach((el) => { el.innerHTML = next; });
  }

  function setTheme(t) {
    html.setAttribute('data-theme', t);
    try { localStorage.setItem('hub_theme', t); } catch (e) { /* private mode */ }
    paintThemeIcon();
  }

  document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('[data-action="toggle-theme"]');
    if (!btn) return;
    ev.preventDefault();
    setTheme(currentTheme() === 'dark' ? 'light' : 'dark');
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', paintThemeIcon);
  } else {
    paintThemeIcon();
  }

  // ── Segmented control (.seg + .seg__btn) ───────────────────────────────
  // Click a button → mark active, fire 'seg-change' on the group with detail.value.
  document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('.seg .seg__btn');
    if (!btn) return;
    const group = btn.parentElement;
    group.querySelectorAll('.seg__btn').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    const value = btn.dataset.value || btn.textContent.trim();
    group.dispatchEvent(new CustomEvent('seg-change', { detail: { value: value, button: btn } }));
  });

  // ── Tabs (.tabs + .tabs__item) ─────────────────────────────────────────
  // [data-tab] on the button, [data-tab-panel] on the matching panel.
  document.addEventListener('click', function (ev) {
    const btn = ev.target.closest('.tabs .tabs__item[data-tab]');
    if (!btn) return;
    const tabs = btn.parentElement;
    const scope = tabs.closest('[data-tabs-scope]') || document;
    const target = btn.dataset.tab;
    tabs.querySelectorAll('.tabs__item').forEach((b) => b.classList.remove('active'));
    btn.classList.add('active');
    scope.querySelectorAll('[data-tab-panel]').forEach((p) => {
      p.hidden = p.dataset.tabPanel !== target;
    });
  });

  // ── Copy to clipboard ([data-copy="..."]) ─────────────────────────────
  document.addEventListener('click', async function (ev) {
    const btn = ev.target.closest('[data-copy]');
    if (!btn) return;
    ev.preventDefault();
    const text = btn.dataset.copy;
    try {
      await navigator.clipboard.writeText(text);
      if (!btn.dataset.copyOrigText) btn.dataset.copyOrigText = btn.textContent;
      btn.textContent = btn.dataset.copyDone || '복사됨';
      btn.classList.add('btn--success');
      setTimeout(() => {
        btn.textContent = btn.dataset.copyOrigText;
        btn.classList.remove('btn--success');
      }, 1500);
    } catch (e) {
      console.error('clipboard write failed', e);
    }
  });

  // ── Confirm for danger buttons (legacy: button.danger, new: .btn--danger) ──
  document.addEventListener('submit', function (ev) {
    const form = ev.target;
    if (!(form instanceof HTMLFormElement)) return;
    if (form.dataset.confirmed === '1') return;
    if (form.getAttribute('onsubmit')) return;
    const btn = form.querySelector('button.danger, button.btn--danger');
    if (!btn) return;
    const msg = form.dataset.confirm || '정말 진행하시겠습니까?';
    if (!window.confirm(msg)) {
      ev.preventDefault();
    } else {
      form.dataset.confirmed = '1';
    }
  });
})();
