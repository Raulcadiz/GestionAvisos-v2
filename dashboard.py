import os
from datetime import date, timedelta
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from extensions import db
from models import Aviso
from telegram_bot import diagnosticar, enviar_mensaje, notificar_resumen_dia, notificar_material_pendiente

dashboard_bp = Blueprint('dashboard', __name__)


def _base_query():
    """Query base filtrada por rol del usuario actual."""
    q = Aviso.query
    if not current_user.es_admin:
        q = q.filter(db.or_(Aviso.asignado_a == current_user.id,
                             Aviso.created_by == current_user.id))
    return q


@dashboard_bp.route('/')
@login_required
def index():
    hoy = date.today()
    proximos_dias = hoy + timedelta(days=7)
    bq = _base_query()

    contadores = {
        'hoy': bq.filter(
            Aviso.fecha_cita == hoy,
            Aviso.estado != 'finalizado'
        ).count(),
        'material': bq.filter(Aviso.estado == 'esperando_material').count(),
        'pendientes': bq.filter(Aviso.estado == 'pendiente').count(),
        'proximas': bq.filter(
            Aviso.fecha_cita > hoy,
            Aviso.fecha_cita <= proximos_dias,
            Aviso.estado != 'finalizado'
        ).count(),
        'segunda_visita': bq.filter(Aviso.estado == 'segunda_visita').count(),
        'total': bq.filter(Aviso.estado != 'finalizado').count(),
    }

    avisos_hoy = _base_query().filter(
        Aviso.fecha_cita == hoy,
        Aviso.estado != 'finalizado'
    ).order_by(Aviso.fecha_cita).all()

    avisos_pendientes = _base_query().filter(
        Aviso.estado.in_(['pendiente', 'segunda_visita'])
    ).order_by(Aviso.fecha_aviso.desc()).limit(5).all()

    return render_template('dashboard/index.html',
                           contadores=contadores,
                           avisos_hoy=avisos_hoy,
                           avisos_pendientes=avisos_pendientes,
                           hoy=hoy)


@dashboard_bp.route('/dashboard/hoy')
@login_required
def hoy():
    hoy_date = date.today()
    avisos = _base_query().filter(
        Aviso.fecha_cita == hoy_date,
        Aviso.estado != 'finalizado'
    ).order_by(Aviso.nombre_cliente).all()
    return render_template('dashboard/lista_filtrada.html',
                           avisos=avisos,
                           titulo='Avisos de Hoy',
                           icono='📅',
                           color='danger')


@dashboard_bp.route('/dashboard/ruta')
@login_required
def modo_ruta():
    hoy_date = date.today()
    avisos = _base_query().filter(
        Aviso.fecha_cita == hoy_date,
        Aviso.estado != 'finalizado'
    ).order_by(Aviso.calle).all()
    return render_template('dashboard/modo_ruta.html',
                           avisos=avisos,
                           hoy=hoy_date)


@dashboard_bp.route('/dashboard/material')
@login_required
def material():
    avisos = _base_query().filter(
        Aviso.estado == 'esperando_material'
    ).order_by(Aviso.fecha_aviso.desc()).all()
    return render_template('dashboard/lista_filtrada.html',
                           avisos=avisos,
                           titulo='Esperando Material',
                           icono='📦',
                           color='info')


@dashboard_bp.route('/dashboard/proximas')
@login_required
def proximas():
    hoy_date = date.today()
    proximos_dias = hoy_date + timedelta(days=7)
    avisos = _base_query().filter(
        Aviso.fecha_cita > hoy_date,
        Aviso.fecha_cita <= proximos_dias,
        Aviso.estado != 'finalizado'
    ).order_by(Aviso.fecha_cita).all()
    return render_template('dashboard/lista_filtrada.html',
                           avisos=avisos,
                           titulo='Próximas Citas (7 días)',
                           icono='🗓️',
                           color='primary')


@dashboard_bp.route('/dashboard/finalizados')
@login_required
def finalizados():
    avisos = _base_query().filter(
        Aviso.estado == 'finalizado'
    ).order_by(Aviso.updated_at.desc()).limit(100).all()
    return render_template('dashboard/lista_filtrada.html',
                           avisos=avisos,
                           titulo='Finalizados',
                           icono='✅',
                           color='success')


@dashboard_bp.route('/dashboard/telegram')
@login_required
def telegram_ajustes():
    estado = diagnosticar()
    return render_template('dashboard/telegram.html', estado=estado)


@dashboard_bp.route('/dashboard/telegram/test', methods=['POST'])
@login_required
def telegram_test():
    ok = enviar_mensaje('✅ <b>Prueba desde CadizTécnico</b>\n\nLa conexión con Telegram funciona correctamente.')
    return jsonify({'ok': ok})


@dashboard_bp.route('/dashboard/telegram/resumen', methods=['POST'])
@login_required
def telegram_resumen():
    hoy_date = date.today()
    avisos = _base_query().filter(
        Aviso.fecha_cita == hoy_date,
        Aviso.estado != 'finalizado'
    ).order_by(Aviso.calle).all()
    ok = notificar_resumen_dia(avisos)
    return jsonify({'ok': ok, 'total': len(avisos)})


@dashboard_bp.route('/dashboard/telegram/material', methods=['POST'])
@login_required
def telegram_material():
    avisos = _base_query().filter(
        Aviso.estado == 'esperando_material'
    ).order_by(Aviso.updated_at).all()
    ok = notificar_material_pendiente(avisos)
    return jsonify({'ok': ok, 'total': len(avisos)})


@dashboard_bp.route('/telegram/webhook', methods=['POST'])
def telegram_webhook():
    """
    Endpoint que recibe los updates del bot de Telegram.
    Registrar en BotFather con:
      https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://TUDOMINIO/telegram/webhook
    """
    # Verificar token secreto en cabecera para evitar llamadas no autorizadas
    token_esperado = os.environ.get('TELEGRAM_BOT_TOKEN', '')
    token_header   = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    secret_env     = os.environ.get('TELEGRAM_WEBHOOK_SECRET', '')

    # Si hay secret configurado, verificarlo
    if secret_env and token_header != secret_env:
        return jsonify({'ok': False}), 403

    update = request.get_json(silent=True) or {}
    if update:
        from telegram_commands import procesar_update
        procesar_update(update, current_app._get_current_object())

    return jsonify({'ok': True})
