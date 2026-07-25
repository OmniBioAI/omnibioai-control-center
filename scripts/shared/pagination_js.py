from __future__ import annotations

PAGINATION_JS = """
<script id="pg-shared">
function renderPg(prefix, state, applyFn) {
  var total = state.filtered.length;
  var pages = Math.ceil(total / state.pp);
  var pg = document.getElementById(prefix + '-pg');
  if (!pg) return;
  pg.innerHTML = '';
  if (pages <= 1) return;
  var start = (state.page - 1) * state.pp + 1;
  var end = Math.min(state.page * state.pp, total);
  var info = document.createElement('span');
  info.className = 'pg-info';
  info.textContent = start + '–' + end + ' of ' + total;
  pg.appendChild(info);
  var prev = document.createElement('button');
  prev.className = 'pg-btn';
  prev.textContent = '←';
  prev.disabled = state.page === 1;
  prev.onclick = function() { if (state.page > 1) { state.page--; applyFn(); } };
  pg.appendChild(prev);
  var maxB = 5, sP = Math.max(1, state.page - 2), eP = Math.min(pages, sP + maxB - 1);
  if (eP - sP < maxB - 1) sP = Math.max(1, eP - maxB + 1);
  for (var i = sP; i <= eP; i++) {
    (function(p) {
      var btn = document.createElement('button');
      btn.className = 'pg-btn' + (state.page === p ? ' active' : '');
      btn.textContent = p;
      btn.onclick = function() { state.page = p; applyFn(); };
      pg.appendChild(btn);
    })(i);
  }
  var next = document.createElement('button');
  next.className = 'pg-btn';
  next.textContent = '→';
  next.disabled = state.page === pages;
  next.onclick = function() { if (state.page < pages) { state.page++; applyFn(); } };
  pg.appendChild(next);
}
</script>
"""
