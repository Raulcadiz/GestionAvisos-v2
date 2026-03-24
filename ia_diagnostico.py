"""
ia_diagnostico.py — Chatbot de diagnóstico IA con Ollama (100% local, gratis).

Endpoints:
  GET  /ia/diagnostico          → página pública (sin login)
  GET  /ia/dashboard/diagnostico → página dashboard (login requerido)
  POST /ia/api/consulta         → API JSON usada por ambas páginas vía fetch()
"""
import base64
import json
import logging
import re

import ollama
from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required

from models import ELECTRODOMESTICOS

logger = logging.getLogger(__name__)

ia_bp = Blueprint('ia', __name__, url_prefix='/ia')

# ─── Modelos ────────────────────────────────────────────────────────────────
MODELO_VISION = 'llava'      # análisis texto + imagen
MODELO_TEXTO  = 'llama3.2'  # análisis solo texto

# ─── System prompt ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """Eres TecnicoIA, experto en reparación de electrodomésticos con 20 años de experiencia en España.
Analiza la avería descrita y responde ÚNICAMENTE con este JSON válido (sin texto antes ni después):
{
  "averia": "nombre concreto de la avería más probable",
  "probabilidad": 80,
  "coste_min": 50,
  "coste_max": 150,
  "repuesto": "nombre del repuesto principal a sustituir",
  "pasos": [
    "Paso 1: descripción",
    "Paso 2: descripción",
    "Paso 3: descripción"
  ],
  "recomendacion": "reparar",
  "motivo": "Breve explicación de 2-3 frases en español de España."
}

Reglas estrictas:
- probabilidad: entero entre 0 y 100
- coste_min y coste_max: en euros (€), incluye mano de obra estimada y repuesto principal
- recomendacion: exactamente la palabra "reparar" o "cambiar" (sin tildes)
- pasos: entre 2 y 5 pasos concretos y accionables
- Si hay imagen, analiza los daños visibles e inclúyelos
- Todo el contenido textual en español de España
"""


# ─── Helpers ────────────────────────────────────────────────────────────────

def _extraer_json(texto: str) -> dict:
    """Extrae y parsea el primer objeto JSON encontrado en la respuesta del modelo."""
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    if not match:
        raise ValueError("La IA no devolvió un JSON válido.")
    return json.loads(match.group())


def _normalizar(datos: dict, modelo: str) -> dict:
    """Valida y normaliza los campos del diagnóstico."""
    rec = datos.get('recomendacion', 'reparar').lower()
    if rec not in ('reparar', 'cambiar'):
        rec = 'reparar'

    pasos = datos.get('pasos', [])
    if not isinstance(pasos, list):
        pasos = [str(pasos)]

    return {
        'averia':        str(datos.get('averia', 'No determinada')),
        'probabilidad':  max(0, min(100, int(datos.get('probabilidad', 0)))),
        'coste_min':     round(float(datos.get('coste_min', 0)), 2),
        'coste_max':     round(float(datos.get('coste_max', 0)), 2),
        'repuesto':      str(datos.get('repuesto', 'No determinado')),
        'pasos':         [str(p) for p in pasos[:5]],
        'recomendacion': rec,
        'motivo':        str(datos.get('motivo', '')),
        'modelo_usado':  modelo,
    }


# ─── Rutas ──────────────────────────────────────────────────────────────────

@ia_bp.route('/diagnostico')
def diagnostico_publico():
    """Página pública del chatbot de diagnóstico (sin login)."""
    return render_template('ia/diagnostico.html', electrodomesticos=ELECTRODOMESTICOS)


@ia_bp.route('/dashboard/diagnostico')
@login_required
def diagnostico_dashboard():
    """Versión del chatbot integrada en el dashboard (requiere login)."""
    return render_template('ia/diagnostico_dashboard.html', electrodomesticos=ELECTRODOMESTICOS)


@ia_bp.route('/api/consulta', methods=['POST'])
def api_consulta():
    """
    API de diagnóstico IA.  Acepta multipart/form-data:
      - electrodomestico  (str, obligatorio)
      - marca             (str, opcional)
      - descripcion       (str, obligatorio)
      - foto              (file, opcional — activa modelo de visión llava)

    Devuelve JSON:
      { ok: true, resultado: {...} }   |   { error: "..." }
    """
    electrodomestico = request.form.get('electrodomestico', '').strip()
    marca            = request.form.get('marca', '').strip()
    descripcion      = request.form.get('descripcion', '').strip()

    if not electrodomestico or not descripcion:
        return jsonify({'error': 'El electrodoméstico y la descripción son obligatorios.'}), 400

    lineas = [f'Electrodoméstico: {electrodomestico}']
    if marca:
        lineas.append(f'Marca: {marca}')
    lineas.append(f'Descripción de la avería: {descripcion}')
    texto_usuario = '\n'.join(lineas)

    foto_file  = request.files.get('foto')
    con_imagen = bool(foto_file and foto_file.filename)

    try:
        if con_imagen:
            imagen_b64 = base64.b64encode(foto_file.read()).decode('utf-8')
            resp = ollama.chat(
                model=MODELO_VISION,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user',   'content': texto_usuario, 'images': [imagen_b64]},
                ],
            )
            modelo_usado = MODELO_VISION
        else:
            resp = ollama.chat(
                model=MODELO_TEXTO,
                messages=[
                    {'role': 'system', 'content': SYSTEM_PROMPT},
                    {'role': 'user',   'content': texto_usuario},
                ],
            )
            modelo_usado = MODELO_TEXTO

        contenido = resp.message.content
        datos     = _extraer_json(contenido)
        resultado = _normalizar(datos, modelo_usado)
        return jsonify({'ok': True, 'resultado': resultado})

    except ollama.ResponseError as exc:
        logger.warning("Ollama ResponseError: %s", exc)
        return jsonify({
            'error': (
                f'Modelo "{modelo_usado}" no disponible. '
                'Asegúrate de que Ollama está activo y el modelo instalado '
                f'(ollama pull {modelo_usado}).'
            )
        }), 503

    except json.JSONDecodeError as exc:
        logger.warning("JSON inválido en respuesta Ollama: %s", exc)
        return jsonify({'error': 'La IA devolvió una respuesta no válida. Inténtalo de nuevo.'}), 502

    except Exception as exc:
        logger.error("Error inesperado en diagnóstico IA: %s", exc, exc_info=True)
        return jsonify({'error': f'Error interno: {exc}'}), 500
