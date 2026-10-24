// Browser-only "explore" controls: keyboard navigation and ship search.
// Never loaded by the screensaver (it opens the page with ?saver=1).

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export function setupExplore({ api, onNext, onPrev, onTogglePause, onSelect }) {
  document.body.classList.add('explore');

  const box = document.createElement('div');
  box.className = 'search';
  box.hidden = true;
  box.innerHTML = `
    <div class="search-panel">
      <label class="search-label" for="search-input">Find a vessel</label>
      <input id="search-input" class="search-input" autocomplete="off" spellcheck="false"
             placeholder="Name or MMSI">
      <ol class="search-results"></ol>
      <p class="search-hint">↑ ↓ to choose · return to open · esc to close</p>
    </div>`;
  document.body.append(box);
  const input = box.querySelector('input');
  const list = box.querySelector('ol');

  let results = [];
  let active = 0;
  let timer = null;
  let seq = 0;

  const render = () => {
    list.innerHTML = results.length
      ? results.map((r, i) => `
          <li class="${i === active ? 'active' : ''}" data-i="${i}">
            <span class="r-name">${esc(r.name || `MMSI ${r.mmsi}`)}</span>
            <span class="r-meta">${esc(r.region || '—')}${r.live ? '' : ' · not heard recently'}</span>
          </li>`).join('')
      : (input.value.trim().length >= 2 ? '<li class="empty">No ships by that name yet</li>' : '');
  };

  const query = async () => {
    const q = input.value.trim();
    const mine = ++seq;
    if (q.length < 2) { results = []; render(); return; }
    const r = await api(`/api/search?q=${encodeURIComponent(q)}`).catch(() => null);
    if (mine !== seq) return; // a newer keystroke won
    results = r?.ok ? r.body : [];
    active = 0;
    render();
  };

  const open = () => {
    box.hidden = false;
    input.value = '';
    results = [];
    render();
    input.focus();
  };
  const close = () => { box.hidden = true; input.blur(); };
  const choose = (i) => {
    const r = results[i];
    if (!r) return;
    close();
    onSelect(r.mmsi);
  };

  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(query, 180); });
  list.addEventListener('click', (e) => {
    const li = e.target.closest('li[data-i]');
    if (li) choose(Number(li.dataset.i));
  });
  box.addEventListener('click', (e) => { if (e.target === box) close(); });

  document.addEventListener('keydown', (e) => {
    if (!box.hidden) {
      if (e.key === 'Escape') close();
      else if (e.key === 'ArrowDown') { active = Math.min(active + 1, results.length - 1); render(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { active = Math.max(active - 1, 0); render(); e.preventDefault(); }
      else if (e.key === 'Enter') choose(active);
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { open(); e.preventDefault(); }
      return;
    }
    if (e.key === 'ArrowRight' || e.key === 'n') onNext();
    else if (e.key === 'ArrowLeft' || e.key === 'p') onPrev();
    else if (e.key === ' ') { onTogglePause(); e.preventDefault(); }
    else if (e.key === '/') { open(); e.preventDefault(); }
  });
}
