/* ── CadizTecnico app.js ────────────────────────────────────────── */

(function () {
  'use strict';

  // ── Búsqueda rápida en la navbar ──────────────────────────────
  const navSearch = document.getElementById('nav-search');
  const navDropdown = document.getElementById('nav-search-results');

  if (navSearch && navDropdown) {
    let searchTimer;

    navSearch.addEventListener('input', function () {
      clearTimeout(searchTimer);
      const q = this.value.trim();

      if (q.length < 2) {
        navDropdown.innerHTML = '';
        navDropdown.classList.remove('show');
        return;
      }

      searchTimer = setTimeout(() => {
        fetch(`/avisos/api/search?q=${encodeURIComponent(q)}`)
          .then(r => r.json())
          .then(data => {
            navDropdown.innerHTML = '';
            if (data.length === 0) {
              navDropdown.innerHTML = '<div class="search-empty">Sin resultados</div>';
            } else {
              data.forEach(item => {
                const a = document.createElement('a');
                a.href = item.url;
                a.className = 'search-item';
                a.innerHTML = `
                  <div class="d-flex justify-content-between align-items-center">
                    <div>
                      <strong>${escapeHtml(item.nombre_cliente)}</strong>
                      <span class="text-muted ms-2 small">${escapeHtml(item.telefono)}</span>
                      ${item.calle ? `<span class="text-muted ms-2 small">${escapeHtml(item.calle)}</span>` : ''}
                    </div>
                    <span class="badge ${item.estado_class} ms-2">${escapeHtml(item.estado)}</span>
                  </div>
                  ${item.electrodomestico ? `<div class="small text-muted">🔧 ${escapeHtml(item.electrodomestico)}</div>` : ''}
                `;
                navDropdown.appendChild(a);
              });
            }
            navDropdown.classList.add('show');
          })
          .catch(() => {
            navDropdown.classList.remove('show');
          });
      }, 300);
    });

    // Cerrar dropdown al hacer clic fuera
    document.addEventListener('click', function (e) {
      if (!navSearch.contains(e.target) && !navDropdown.contains(e.target)) {
        navDropdown.classList.remove('show');
        navDropdown.innerHTML = '';
      }
    });

    // Cerrar con Escape
    navSearch.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        navDropdown.classList.remove('show');
        navDropdown.innerHTML = '';
        this.value = '';
      }
    });
  }

  // ── Confirmar eliminación en formularios ───────────────────────
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', function (e) {
      if (!confirm(this.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });

  // ── Auto-ocultar alertas flash después de 5 segundos ──────────
  document.querySelectorAll('.alert.alert-success, .alert.alert-info').forEach(alert => {
    setTimeout(() => {
      const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
      bsAlert.close();
    }, 5000);
  });

  // ── Utilidad: escape HTML ──────────────────────────────────────
  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

})();
