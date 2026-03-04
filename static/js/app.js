/* ── ElectroBahía app.js ─────────────────────────────────────────── */

(function () {
  'use strict';

  // ── Auto-ocultar alertas flash (5 segundos) ────────────────────
  document.querySelectorAll('.alert.alert-success, .alert.alert-info').forEach(alert => {
    setTimeout(() => {
      try {
        bootstrap.Alert.getOrCreateInstance(alert).close();
      } catch (e) {}
    }, 5000);
  });

  // ── Confirmar eliminación en formularios ──────────────────────
  document.querySelectorAll('form[data-confirm]').forEach(form => {
    form.addEventListener('submit', function (e) {
      if (!confirm(this.dataset.confirm)) {
        e.preventDefault();
      }
    });
  });

})();
