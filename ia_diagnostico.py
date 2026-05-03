"""
ia_diagnostico.py — Diagnóstico IA multi-proveedor.

Proveedores disponibles:
  - 'ollama'     → Ollama local (100% gratis, requiere Ollama instalado)
  - 'groq'       → Groq Cloud API (gratis tier, ultra-rápido, requiere GROQ_API_KEY)
  - 'anthropic'  → Anthropic Claude API (requiere ANTHROPIC_API_KEY en .env)
  - 'openai'     → OpenAI API (requiere OPENAI_API_KEY en .env)

Config persistida en: instance/ia_settings.json
API keys NUNCA se guardan en JSON — se leen de variables de entorno.

Rutas públicas:
  GET  /ia/diagnostico              → chatbot público (sin login)
  GET  /ia/dashboard/diagnostico    → chatbot dashboard (login requerido)
  POST /ia/api/consulta             → API compartida por ambos chatbots

Rutas admin:
  GET/POST /ia/admin/config         → panel de configuración IA
  POST     /ia/admin/ollama/pull    → inicia descarga de modelo Ollama
"""
import base64
import json
import logging
import os
import re
import subprocess
from functools import wraps

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from models import ELECTRODOMESTICOS

logger = logging.getLogger(__name__)

ia_bp = Blueprint('ia', __name__, url_prefix='/ia')


# ─── Decorador admin ────────────────────────────────────────────────────────

def _admin_required(f):
    """Requiere rol admin o superior (reutiliza lógica de models.User)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


# ─── Configuración ──────────────────────────────────────────────────────────

DEFAULTS = {
    'provider':            'ollama',
    'ollama_texto_model':  'llama3.2',
    'ollama_vision_model': 'llava',
    'groq_model':          'llama-3.1-8b-instant',
    'anthropic_model':     'claude-3-5-haiku-20241022',
    'openai_model':        'gpt-4o-mini',
}

# Modelos Groq activos (actualizados 2026 — ver console.groq.com/docs/models)
GROQ_MODELS = [
    ('llama-3.1-8b-instant',        'Llama 3.1 8B — rapidísimo, gratis ⭐'),
    ('llama-3.3-70b-versatile',     'Llama 3.3 70B — más potente, gratis'),
    ('llama-3.2-11b-vision-preview','Llama 3.2 11B Vision — texto + imagen, gratis'),
    ('llama-3.2-90b-vision-preview','Llama 3.2 90B Vision — visión potente, gratis'),
    ('gemma2-9b-it',                'Gemma 2 9B — Google (puede estar deprecado)'),
]

# Tabla de migración: modelos Groq antiguos → sustituto actual
_GROQ_DEPRECATED = {
    'llama3-8b-8192':    'llama-3.1-8b-instant',
    'llama3-70b-8192':   'llama-3.3-70b-versatile',
    'mixtral-8x7b-32768':'llama-3.3-70b-versatile',
    'gemma-7b-it':       'llama-3.1-8b-instant',
}

ANTHROPIC_MODELS = [
    'claude-3-5-haiku-20241022',
    'claude-3-5-sonnet-20241022',
    'claude-opus-4-5',
]

OPENAI_MODELS = [
    'gpt-4o-mini',
    'gpt-4o',
    'gpt-4-turbo',
]

OLLAMA_POPULARES = [
    ('llama3.2',         'Llama 3.2 3B — texto rápido'),
    ('llama3.1',         'Llama 3.1 8B — texto potente'),
    ('mistral',          'Mistral 7B — texto, muy bueno'),
    ('llava',            'LLaVA 7B — visión (texto + foto)'),
    ('llava:13b',        'LLaVA 13B — visión mejorada'),
    ('moondream',        'Moondream 2 — visión ligero'),
    ('phi3',             'Phi-3 Mini — texto ultraligero'),
]


def _settings_path() -> str:
    instance = os.path.join(os.path.dirname(__file__), 'instance')
    os.makedirs(instance, exist_ok=True)
    return os.path.join(instance, 'ia_settings.json')


def load_settings() -> dict:
    path = _settings_path()
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            cfg = {**DEFAULTS, **data}
            # Migrar modelos Groq deprecados automáticamente
            if cfg.get('groq_model') in _GROQ_DEPRECATED:
                cfg['groq_model'] = _GROQ_DEPRECATED[cfg['groq_model']]
                save_settings(cfg)  # persiste la migración
            return cfg
        except Exception:
            pass
    return dict(DEFAULTS)


def save_settings(nuevos: dict):
    current = load_settings()
    current.update({k: v for k, v in nuevos.items() if k in DEFAULTS})
    with open(_settings_path(), 'w', encoding='utf-8') as f:
        json.dump(current, f, ensure_ascii=False, indent=2)


# ─── System prompt ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = (
    "Eres TecnicoIA, experto en reparación de electrodomésticos con 20 años de experiencia en España.\n"
    "Analiza la avería y responde ÚNICAMENTE con este JSON válido (sin texto antes ni después):\n"
    "{\n"
    '  "averia": "nombre concreto de la avería más probable",\n'
    '  "probabilidad": 80,\n'
    '  "coste_min": 50,\n'
    '  "coste_max": 150,\n'
    '  "repuesto": "nombre del repuesto principal a sustituir",\n'
    '  "pasos": ["Paso 1: ...", "Paso 2: ...", "Paso 3: ..."],\n'
    '  "recomendacion": "reparar",\n'
    '  "motivo": "Breve explicación de 2-3 frases en español de España."\n'
    "}\n\n"
    "Reglas estrictas:\n"
    "- probabilidad: entero 0-100\n"
    "- coste_min, coste_max: en euros €, incluye mano de obra y repuesto\n"
    "- recomendacion: exactamente 'reparar' o 'cambiar'\n"
    "- pasos: entre 2 y 5 pasos concretos y accionables\n"
    "- Si hay imagen, analiza los daños visibles e inclúyelos en el análisis\n"
    "- Todo el contenido en español de España"
)


# ─── Helpers ────────────────────────────────────────────────────────────────

def _extraer_json(texto: str) -> dict:
    match = re.search(r'\{.*\}', texto, re.DOTALL)
    if not match:
        raise ValueError("La IA no devolvió un JSON válido.")
    return json.loads(match.group())


def _normalizar(datos: dict, modelo: str) -> dict:
    rec = str(datos.get('recomendacion', 'reparar')).lower()
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


# ─── Proveedores ────────────────────────────────────────────────────────────

def _llamar_ollama(texto: str, imagen_b64: str | None, cfg: dict) -> tuple[str, str]:
    import ollama as _ollama
    if imagen_b64:
        model = cfg['ollama_vision_model']
        resp = _ollama.chat(model=model, messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user',   'content': texto, 'images': [imagen_b64]},
        ])
    else:
        model = cfg['ollama_texto_model']
        resp = _ollama.chat(model=model, messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user',   'content': texto},
        ])
    return resp.message.content, model


def _llamar_groq(texto: str, imagen_b64: str | None, imagen_mt: str | None, cfg: dict) -> tuple[str, str]:
    """Groq — texto y visión (modelos llama-3.2-*-vision-preview)."""
    from groq import Groq as _Groq
    api_key = os.environ.get('GROQ_API_KEY', '')
    if not api_key:
        raise RuntimeError("GROQ_API_KEY no configurada en .env")
    client = _Groq(api_key=api_key)
    model = cfg['groq_model']

    # Soporte visión para modelos Groq que lo admiten
    es_vision = 'vision' in model and imagen_b64 and imagen_mt
    if es_vision:
        user_content = [
            {'type': 'text', 'text': texto},
            {'type': 'image_url', 'image_url': {
                'url': f'data:{imagen_mt};base64,{imagen_b64}',
            }},
        ]
    else:
        user_content = texto

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user',   'content': user_content},
        ],
        max_tokens=1024,
        temperature=0.2,
    )
    return resp.choices[0].message.content, model


def _llamar_anthropic(texto: str, imagen_b64: str | None, imagen_mt: str | None, cfg: dict) -> tuple[str, str]:
    import anthropic as _anthropic
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY no configurada en .env")
    client = _anthropic.Anthropic(api_key=api_key)
    model  = cfg['anthropic_model']

    if imagen_b64:
        content = [
            {
                'type': 'image',
                'source': {
                    'type':       'base64',
                    'media_type': imagen_mt or 'image/jpeg',
                    'data':       imagen_b64,
                },
            },
            {'type': 'text', 'text': texto},
        ]
    else:
        content = texto

    resp = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{'role': 'user', 'content': content}],
    )
    return resp.content[0].text, model


def _llamar_openai(texto: str, imagen_b64: str | None, imagen_mt: str | None, cfg: dict) -> tuple[str, str]:
    from openai import OpenAI as _OpenAI
    api_key = os.environ.get('OPENAI_API_KEY', '')
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY no configurada en .env")
    client = _OpenAI(api_key=api_key)
    model  = cfg['openai_model']

    if imagen_b64:
        content = [
            {'type': 'text', 'text': texto},
            {'type': 'image_url', 'image_url': {
                'url': f'data:{imagen_mt or "image/jpeg"};base64,{imagen_b64}'
            }},
        ]
    else:
        content = texto

    resp = client.chat.completions.create(
        model=model,
        messages=[
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user',   'content': content},
        ],
        max_tokens=1024,
    )
    return resp.choices[0].message.content, model


# ─── Rutas públicas / dashboard ─────────────────────────────────────────────

@ia_bp.route('/diagnostico')
def diagnostico_publico():
    """Chatbot de diagnóstico IA — acceso público sin login."""
    return render_template('ia/diagnostico.html', electrodomesticos=ELECTRODOMESTICOS)


@ia_bp.route('/dashboard/diagnostico')
@login_required
def diagnostico_dashboard():
    """Chatbot de diagnóstico IA — versión dashboard con login."""
    cfg = load_settings()
    return render_template('ia/diagnostico_dashboard.html',
                           electrodomesticos=ELECTRODOMESTICOS,
                           ia_provider=cfg['provider'])


@ia_bp.route('/api/consulta', methods=['POST'])
def api_consulta():
    """
    API de diagnóstico compartida por el chatbot público y el dashboard.
    Acepta multipart/form-data:
      - electrodomestico  str  obligatorio
      - marca             str  opcional
      - descripcion       str  obligatorio
      - foto              file opcional  (activa visión si el modelo lo soporta)
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
    imagen_b64 = None
    imagen_mt  = None
    if con_imagen:
        imagen_b64 = base64.b64encode(foto_file.read()).decode('utf-8')
        imagen_mt  = foto_file.mimetype or 'image/jpeg'

    cfg      = load_settings()
    provider = cfg.get('provider', 'ollama')

    try:
        if provider == 'anthropic':
            contenido, modelo_usado = _llamar_anthropic(texto_usuario, imagen_b64, imagen_mt, cfg)
        elif provider == 'openai':
            contenido, modelo_usado = _llamar_openai(texto_usuario, imagen_b64, imagen_mt, cfg)
        elif provider == 'groq':
            contenido, modelo_usado = _llamar_groq(texto_usuario, imagen_b64, imagen_mt, cfg)
        else:
            contenido, modelo_usado = _llamar_ollama(texto_usuario, imagen_b64, cfg)

        datos     = _extraer_json(contenido)
        resultado = _normalizar(datos, modelo_usado)
        return jsonify({'ok': True, 'resultado': resultado})

    except json.JSONDecodeError:
        return jsonify({'error': 'La IA devolvió una respuesta no válida. Inténtalo de nuevo.'}), 502
    except Exception as exc:
        logger.error("Error IA (%s): %s", provider, exc, exc_info=True)
        return jsonify({'error': str(exc)}), 500


# ─── Rutas admin — configuración IA ─────────────────────────────────────────

@ia_bp.route('/admin/config', methods=['GET', 'POST'])
@login_required
@_admin_required
def admin_config():
    """Panel de configuración del proveedor IA."""
    cfg = load_settings()

    if request.method == 'POST':
        save_settings({
            'provider':            request.form.get('provider', 'ollama'),
            'ollama_texto_model':  request.form.get('ollama_texto_model',  DEFAULTS['ollama_texto_model']),
            'ollama_vision_model': request.form.get('ollama_vision_model', DEFAULTS['ollama_vision_model']),
            'groq_model':          request.form.get('groq_model',          DEFAULTS['groq_model']),
            'anthropic_model':     request.form.get('anthropic_model',     DEFAULTS['anthropic_model']),
            'openai_model':        request.form.get('openai_model',        DEFAULTS['openai_model']),
        })
        flash('Configuración IA guardada correctamente.', 'success')
        return redirect(url_for('ia.admin_config'))

    return render_template(
        'admin/ia_config.html',
        cfg=cfg,
        ollama_populares=OLLAMA_POPULARES,
        groq_models=GROQ_MODELS,
        anthropic_models=ANTHROPIC_MODELS,
        openai_models=OPENAI_MODELS,
        groq_key_ok=bool(os.environ.get('GROQ_API_KEY')),
        anthropic_key_ok=bool(os.environ.get('ANTHROPIC_API_KEY')),
        openai_key_ok=bool(os.environ.get('OPENAI_API_KEY')),
    )


@ia_bp.route('/admin/ollama/pull', methods=['POST'])
@login_required
@_admin_required
def admin_ollama_pull():
    """Inicia la descarga de un modelo Ollama en background. Responde inmediatamente."""
    model = request.form.get('model', '').strip()
    # Validación básica: solo caracteres alfanuméricos, punto, dos puntos y guion
    if not model or not re.match(r'^[\w.\-:]+$', model):
        return jsonify({'error': 'Nombre de modelo no válido.'}), 400
    try:
        subprocess.Popen(
            ['ollama', 'pull', model],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({'ok': True, 'msg': f'Descarga de "{model}" iniciada. Puede tardar varios minutos.'})
    except FileNotFoundError:
        return jsonify({'error': 'Ollama no está instalado o no está en el PATH del servidor.'}), 503
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
