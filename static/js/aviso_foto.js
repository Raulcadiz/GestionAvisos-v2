// Rellena el formulario de nuevo aviso con los datos leídos de una foto.
(function () {
  const CLAVE = 'eb_aviso_foto';
  const formulario = document.getElementById('form-aviso');

  function pintarEstado(contenedor, texto, clase) {
    const el = contenedor && contenedor.querySelector('.eb-foto-estado');
    if (!el) return;
    el.textContent = texto;
    el.className = `eb-foto-estado small ${clase}`;
  }

  function rellenar(datos) {
    let rellenados = 0;

    Object.entries(datos).forEach(([campo, valor]) => {
      if (campo === 'tipo_servicio') {
        const radio = formulario.querySelector(`input[name="tipo_servicio"][value="${CSS.escape(valor)}"]`);
        if (radio) { radio.click(); rellenados++; }
        return;
      }
      const el = formulario.elements[campo];
      if (!el || (el.tagName !== 'SELECT' && el.value.trim())) return;  // no pisa lo ya escrito
      el.value = valor;
      el.classList.add('border-success', 'bg-success-subtle');
      el.dispatchEvent(new Event('change', { bubbles: true }));
      rellenados++;
    });

    return rellenados;
  }

  function mostrarResultado(contenedor, datos) {
    const total = rellenar(datos);
    pintarEstado(contenedor, `✅ ${total} campos rellenados. Revísalos antes de guardar.`, 'text-success fw-semibold');
  }

  function leerFoto(input) {
    const contenedor = input.closest('.eb-foto-aviso');
    const cuerpo = new FormData();
    cuerpo.append('foto', input.files[0]);

    input.disabled = true;
    pintarEstado(contenedor, '⏳ Leyendo la foto...', 'text-muted');

    fetch('/ia/api/leer-aviso', { method: 'POST', body: cuerpo })
      .then(r => r.json().catch(() => ({ error: 'La foto es demasiado grande o la sesión ha caducado.' })))
      .then(respuesta => {
        if (!respuesta.ok) throw new Error(respuesta.error || 'No se pudo leer la foto.');
        if (formulario) {
          mostrarResultado(contenedor, respuesta.datos);
        } else {
          sessionStorage.setItem(CLAVE, JSON.stringify(respuesta.datos));
          location.href = '/avisos/nuevo?desde_foto=1';
        }
      })
      .catch(error => pintarEstado(contenedor, `❌ ${error.message}`, 'text-danger'))
      .finally(() => {
        input.disabled = false;
        input.value = '';
      });
  }

  document.querySelectorAll('.eb-foto-aviso-input').forEach(input => {
    input.addEventListener('change', () => { if (input.files.length) leerFoto(input); });
  });

  // Datos que llegan desde el botón del panel
  if (formulario) {
    let pendientes = null;
    try {
      pendientes = JSON.parse(sessionStorage.getItem(CLAVE));
      sessionStorage.removeItem(CLAVE);
    } catch (e) { /* almacenamiento no disponible */ }
    if (pendientes) mostrarResultado(document.querySelector('.eb-foto-aviso'), pendientes);
  }
})();
