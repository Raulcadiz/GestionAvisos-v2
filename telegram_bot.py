import os
import ssl
import urllib.request
import urllib.parse
import urllib.error
import json
import logging
from dotenv import load_dotenv
load_dotenv(override=True)

logger = logging.getLogger(__name__)


def _ssl_context():
    """
    Contexto SSL adaptativo por plataforma:
    - Linux/PythonAnywhere: SSL estándar del sistema funciona directamente
    - Windows + OpenSSL 3.x: necesita certifi + SECLEVEL=1 por clave débil en certificado intermedio de Telegram
    """
    import platform
    if platform.system() == 'Windows':
        # Windows con OpenSSL 3.x necesita bajar el nivel de seguridad
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
            ctx.set_ciphers('DEFAULT@SECLEVEL=1')
            return ctx
        except Exception:
            pass
        # Fallback Windows sin certifi
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    else:
        # Linux/Mac: contexto estándar del sistema
        return ssl.create_default_context()


# ─────────────────────────────────────────────
# Núcleo: envío básico
# ─────────────────────────────────────────────

def _get_credenciales():
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    return token, chat_id


def diagnosticar() -> dict:
    """
    Comprueba la configuración de Telegram y devuelve un dict con el resultado.
    Útil para la página de ajustes del panel.
    """
    token, chat_id = _get_credenciales()

    if not token or 'PON_AQUI' in token:
        return {'ok': False, 'error': 'TELEGRAM_BOT_TOKEN no configurado en .env'}
    if not chat_id or 'PON_AQUI' in chat_id:
        return {'ok': False, 'error': 'TELEGRAM_CHAT_ID no configurado en .env'}

    # Verificar token con getMe
    url = f'https://api.telegram.org/bot{token}/getMe'
    try:
        with urllib.request.urlopen(url, timeout=5, context=_ssl_context()) as resp:
            data = json.loads(resp.read())
            if data.get('ok'):
                bot_name = data['result'].get('username', '?')
                return {'ok': True, 'bot': bot_name, 'chat_id': chat_id}
            return {'ok': False, 'error': 'Respuesta inesperada de Telegram'}
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return {'ok': False, 'error': 'Token inválido (401) — regenera el token en @BotFather'}
        return {'ok': False, 'error': f'HTTP {e.code}: {e.reason}'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


def _enviar_a_chat(token: str, chat_id: str, texto: str) -> bool:
    """Envío interno a un chat_id específico."""
    url = f'https://api.telegram.org/bot{token}/sendMessage'
    datos = urllib.parse.urlencode({
        'chat_id': chat_id,
        'text': texto,
        'parse_mode': 'HTML',
    }).encode('utf-8')
    try:
        req = urllib.request.Request(url, data=datos, method='POST')
        with urllib.request.urlopen(req, timeout=5, context=_ssl_context()) as resp:
            resultado = json.loads(resp.read())
            return resultado.get('ok', False)
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8', errors='ignore')
        logger.error(f'Telegram HTTPError {e.code}: {body}')
        return False
    except Exception as e:
        logger.error(f'Telegram error: {e}')
        return False


def enviar_mensaje(texto: str) -> bool:
    """
    Envía un mensaje HTML al chat configurado en .env (chat admin).
    """
    token, chat_id = _get_credenciales()
    if not token or not chat_id or 'PON_AQUI' in token or 'PON_AQUI' in chat_id:
        logger.warning('Telegram no configurado — revisa .env')
        return False
    return _enviar_a_chat(token, chat_id, texto)


def enviar_mensaje_a(chat_id_destino: str, texto: str) -> bool:
    """
    Envía un mensaje HTML a un chat_id específico (ej: técnico asignado).
    """
    token, _ = _get_credenciales()
    if not token or not chat_id_destino or 'PON_AQUI' in token:
        return False
    return _enviar_a_chat(token, chat_id_destino, texto)


# ─────────────────────────────────────────────
# Notificaciones de avisos
# ─────────────────────────────────────────────

def notificar_aviso_nuevo(aviso) -> bool:
    """Notifica la creación de un aviso nuevo. También al técnico asignado si tiene chat_id."""
    origen = '🌐 <i>vía formulario web</i>' if not aviso.created_by else '👨‍🔧 <i>vía panel</i>'
    lineas = [
        f'🔔 <b>Nuevo aviso #{aviso.id}</b>  {origen}',
        '',
        f'👤 <b>{aviso.nombre_cliente}</b>',
        f'📞 {aviso.telefono}',
    ]
    if aviso.calle:
        dir_ = aviso.calle + (f', {aviso.localidad}' if aviso.localidad else '')
        lineas.append(f'📍 {dir_}')
    if aviso.electrodomestico:
        electro = aviso.electrodomestico + (f' · {aviso.marca}' if aviso.marca else '')
        lineas.append(f'🔧 {electro}')
    if aviso.descripcion:
        lineas.append(f'📝 {aviso.descripcion[:300]}')

    texto = '\n'.join(lineas)
    ok = enviar_mensaje(texto)

    # Notificar también al técnico asignado (si tiene chat_id distinto al admin)
    if aviso.tecnico and aviso.tecnico.telegram_chat_id:
        tg_id = aviso.tecnico.telegram_chat_id.strip()
        _, admin_chat = _get_credenciales()
        if tg_id and tg_id != admin_chat:
            asignado_txt = texto + f'\n\n📌 <i>Asignado a ti: {aviso.tecnico.display_name}</i>'
            enviar_mensaje_a(tg_id, asignado_txt)

    return ok


def notificar_cambio_estado(aviso, estado_anterior: str) -> bool:
    """Notifica cuando se cambia el estado de un aviso."""
    iconos = {
        'pendiente': '⏳',
        'hoy': '📅',
        'esperando_material': '📦',
        'segunda_visita': '🔁',
        'finalizado': '✅',
    }
    etiquetas = {
        'pendiente': 'Pendiente',
        'hoy': 'Para hoy',
        'esperando_material': 'Esperando material',
        'segunda_visita': 'Segunda visita',
        'finalizado': 'Finalizado',
    }
    icono_nuevo = iconos.get(aviso.estado, '🔄')
    label_ant = etiquetas.get(estado_anterior, estado_anterior)
    label_nuevo = etiquetas.get(aviso.estado, aviso.estado)

    lineas = [
        f'{icono_nuevo} <b>Aviso #{aviso.id} → {label_nuevo}</b>',
        f'👤 {aviso.nombre_cliente}  📞 {aviso.telefono}',
        f'<i>{label_ant} → {label_nuevo}</i>',
    ]
    if aviso.estado == 'finalizado':
        lineas.append('🎉 ¡Reparación completada!')
    if aviso.notas:
        lineas.append(f'📝 {aviso.notas[:150]}')

    return enviar_mensaje('\n'.join(lineas))


def notificar_resumen_dia(avisos_hoy) -> bool:
    """Envía el resumen de citas del día, ordenado como la ruta."""
    from datetime import date
    hoy_str = date.today().strftime('%d/%m/%Y')

    if not avisos_hoy:
        return enviar_mensaje(
            f'📅 <b>Resumen del día — {hoy_str}</b>\n\n'
            '✅ No tienes citas programadas para hoy.'
        )

    lineas = [f'📅 <b>Citas de hoy — {hoy_str} ({len(avisos_hoy)} avisos)</b>', '']
    for i, av in enumerate(avisos_hoy, 1):
        lineas.append(f'<b>{i}. {av.nombre_cliente}</b>')
        lineas.append(f'   📞 {av.telefono}')
        if av.calle:
            dir_ = av.calle + (f', {av.localidad}' if av.localidad else '')
            lineas.append(f'   📍 {dir_}')
        if av.electrodomestico:
            lineas.append(f'   🔧 {av.electrodomestico}')
        if av.notas:
            lineas.append(f'   📝 {av.notas[:100]}')
        lineas.append('')

    return enviar_mensaje('\n'.join(lineas))


def notificar_material_pendiente(avisos_material) -> bool:
    """Recuerda los avisos que llevan esperando material."""
    if not avisos_material:
        return False

    lineas = [f'📦 <b>Esperando material ({len(avisos_material)} avisos)</b>', '']
    for av in avisos_material:
        dias = (
            (__import__('datetime').date.today() - av.updated_at.date()).days
            if av.updated_at else '?'
        )
        lineas.append(f'• <b>{av.nombre_cliente}</b> — {av.electrodomestico or "electro"}')
        lineas.append(f'  📞 {av.telefono}  ·  {dias} día(s) esperando')
        if av.notas:
            lineas.append(f'  📝 {av.notas[:80]}')
        lineas.append('')

    return enviar_mensaje('\n'.join(lineas))
