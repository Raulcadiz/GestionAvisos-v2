"""
whatsapp_bot.py — Notificaciones WhatsApp vía Meta WhatsApp Cloud API.

Configuración en .env:
  WHATSAPP_TOKEN            → Bearer token de acceso permanente (Meta Developers)
  WHATSAPP_PHONE_NUMBER_ID  → ID del número de teléfono de tu cuenta Business
  WHATSAPP_TEMPLATE_RECIBIDO → Nombre de la plantilla aprobada para aviso recibido
                               (default: 'aviso_recibido')
  WHATSAPP_TEMPLATE_ESTADO   → Nombre de la plantilla aprobada para cambio de estado
                               (default: 'aviso_estado')

Pasos para activar:
  1. Crea una app en https://developers.facebook.com/
  2. Añade el producto "WhatsApp Business"
  3. Copia el TOKEN y el PHONE_NUMBER_ID a .env
  4. Crea y aprueba las plantillas de mensaje en el Business Manager
  5. En modo sandbox puedes enviar a números verificados sin plantillas

Documentación oficial:
  https://developers.facebook.com/docs/whatsapp/cloud-api/messages
"""

import json
import logging
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)

_API_BASE = 'https://graph.facebook.com/v19.0'


# ─── Helpers ────────────────────────────────────────────────────────────────

def _credenciales() -> tuple[str, str]:
    token    = os.environ.get('WHATSAPP_TOKEN', '').strip()
    phone_id = os.environ.get('WHATSAPP_PHONE_NUMBER_ID', '').strip()
    return token, phone_id


def _configurado() -> bool:
    token, phone_id = _credenciales()
    return bool(token and phone_id and 'PON_AQUI' not in token)


def _formatear_telefono(telefono: str) -> str:
    """
    Convierte un número español al formato internacional para WhatsApp.
    Ej: '600 123 456' → '34600123456'
         '+34 600 123 456' → '34600123456'
    """
    limpio = ''.join(c for c in telefono if c.isdigit() or c == '+')
    limpio = limpio.lstrip('+')
    # Si empieza por 6, 7 o 9 (móvil/fijo España) → añadir prefijo 34
    if limpio and limpio[0] in ('6', '7', '9') and len(limpio) == 9:
        limpio = '34' + limpio
    return limpio


def _enviar_request(phone_id: str, token: str, payload: dict) -> bool:
    """Realiza la llamada HTTP a la Meta Cloud API."""
    url  = f'{_API_BASE}/{phone_id}/messages'
    body = json.dumps(payload).encode('utf-8')
    req  = urllib.request.Request(
        url,
        data=body,
        method='POST',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:
            data = json.loads(resp.read())
            return bool(data.get('messages'))
    except urllib.error.HTTPError as exc:
        body_err = exc.read().decode('utf-8', errors='ignore')
        logger.error('WhatsApp HTTPError %s: %s', exc.code, body_err)
        return False
    except Exception as exc:
        logger.error('WhatsApp error: %s', exc)
        return False


# ─── Envío de plantillas ────────────────────────────────────────────────────

def _enviar_template(telefono: str, template_name: str, componentes: list) -> bool:
    """Envía un mensaje de plantilla aprobada de WhatsApp Business."""
    if not _configurado():
        logger.debug('WhatsApp no configurado — omitiendo envío')
        return False

    token, phone_id = _credenciales()
    numero = _formatear_telefono(telefono)
    if not numero:
        logger.warning('WhatsApp: teléfono no válido: %s', telefono)
        return False

    payload = {
        'messaging_product': 'whatsapp',
        'to':                numero,
        'type':              'template',
        'template': {
            'name':     template_name,
            'language': {'code': 'es'},
            'components': componentes,
        },
    }
    ok = _enviar_request(phone_id, token, payload)
    if ok:
        logger.info('WhatsApp enviado a %s (plantilla: %s)', numero, template_name)
    return ok


def _enviar_texto_libre(telefono: str, mensaje: str) -> bool:
    """
    Envía un mensaje de texto libre.
    NOTA: Solo funciona en la ventana de 24 h tras un mensaje del cliente,
    o en modo sandbox con números verificados.
    """
    if not _configurado():
        return False

    token, phone_id = _credenciales()
    numero = _formatear_telefono(telefono)
    if not numero:
        return False

    payload = {
        'messaging_product': 'whatsapp',
        'to':   numero,
        'type': 'text',
        'text': {'body': mensaje, 'preview_url': False},
    }
    return _enviar_request(phone_id, token, payload)


# ─── Notificaciones de negocio ───────────────────────────────────────────────

def notificar_aviso_whatsapp(aviso, url_seguimiento: str = '') -> bool:
    """
    Notifica al cliente que su aviso ha sido recibido.
    Usa la plantilla 'aviso_recibido' con los parámetros:
      {{1}} → nombre del cliente
      {{2}} → número de aviso
      {{3}} → enlace de seguimiento
    """
    template = os.environ.get('WHATSAPP_TEMPLATE_RECIBIDO', 'aviso_recibido')

    componentes = [{
        'type': 'body',
        'parameters': [
            {'type': 'text', 'text': aviso.nombre_cliente},
            {'type': 'text', 'text': str(aviso.id)},
            {'type': 'text', 'text': url_seguimiento or 'https://electrobahia.es'},
        ],
    }]

    ok = _enviar_template(aviso.telefono, template, componentes)

    # Fallback a texto libre si falla la plantilla (sandbox / testing)
    if not ok:
        mensaje = (
            f'✅ *ElectroBahía* — Aviso #{aviso.id} recibido\n\n'
            f'Hola {aviso.nombre_cliente}, hemos registrado su solicitud de reparación.\n'
            f'Nos pondremos en contacto muy pronto.\n\n'
        )
        if url_seguimiento:
            mensaje += f'🔍 Siga el estado: {url_seguimiento}'
        ok = _enviar_texto_libre(aviso.telefono, mensaje)

    return ok


def notificar_estado_whatsapp(aviso, estado_anterior: str, url_seguimiento: str = '') -> bool:
    """
    Notifica al cliente el cambio de estado de su reparación.
    Usa la plantilla 'aviso_estado' con los parámetros:
      {{1}} → nombre del cliente
      {{2}} → número de aviso
      {{3}} → nuevo estado en texto amigable
      {{4}} → enlace de seguimiento
    """
    etiquetas = {
        'pendiente':          '⏳ Pendiente de visita',
        'hoy':                '📅 ¡Su técnico viene hoy!',
        'esperando_material': '📦 Esperando repuesto',
        'segunda_visita':     '🔁 Segunda visita programada',
        'finalizado':         '✅ ¡Reparación completada!',
    }
    label_nuevo = etiquetas.get(aviso.estado, aviso.estado_label())
    template    = os.environ.get('WHATSAPP_TEMPLATE_ESTADO', 'aviso_estado')

    componentes = [{
        'type': 'body',
        'parameters': [
            {'type': 'text', 'text': aviso.nombre_cliente},
            {'type': 'text', 'text': str(aviso.id)},
            {'type': 'text', 'text': label_nuevo},
            {'type': 'text', 'text': url_seguimiento or 'https://electrobahia.es'},
        ],
    }]

    ok = _enviar_template(aviso.telefono, template, componentes)

    # Fallback texto libre
    if not ok:
        mensaje = (
            f'🔧 *ElectroBahía* — Aviso #{aviso.id}\n\n'
            f'Hola {aviso.nombre_cliente}, su reparación ha cambiado de estado:\n'
            f'*{label_nuevo}*\n\n'
        )
        if url_seguimiento:
            mensaje += f'🔍 Ver estado: {url_seguimiento}'
        ok = _enviar_texto_libre(aviso.telefono, mensaje)

    return ok


def diagnosticar_whatsapp() -> dict:
    """Comprueba la configuración y devuelve un dict de estado."""
    token, phone_id = _credenciales()
    if not token or 'PON_AQUI' in token:
        return {'ok': False, 'error': 'WHATSAPP_TOKEN no configurado en .env'}
    if not phone_id:
        return {'ok': False, 'error': 'WHATSAPP_PHONE_NUMBER_ID no configurado en .env'}

    # Verificar token consultando info del número
    url = f'{_API_BASE}/{phone_id}'
    req = urllib.request.Request(
        url,
        headers={'Authorization': f'Bearer {token}'},
    )
    try:
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=6, context=ctx) as resp:
            data = json.loads(resp.read())
            nombre = data.get('display_phone_number', data.get('verified_name', '?'))
            return {'ok': True, 'numero': nombre, 'phone_id': phone_id}
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            return {'ok': False, 'error': 'Token inválido (401)'}
        return {'ok': False, 'error': f'HTTP {exc.code}'}
    except Exception as exc:
        return {'ok': False, 'error': str(exc)}
