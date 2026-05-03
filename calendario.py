from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from extensions import db
from models import Aviso, User

calendario_bp = Blueprint('calendario', __name__, url_prefix='/calendario')

# Colores por estado (fondo, borde, texto)
_COLORES = {
    'pendiente':          ('#ffc107', '#e0a800', '#000000'),
    'hoy':                ('#dc3545', '#b02a37', '#ffffff'),
    'esperando_material': ('#0dcaf0', '#0aa2c0', '#000000'),
    'segunda_visita':     ('#0d6efd', '#0a58ca', '#ffffff'),
    'finalizado':         ('#adb5bd', '#868e96', '#000000'),
}

_ICONOS_SERVICIO = {
    'reparacion':  '🔧',
    'instalacion': '⚡',
    'reparto':     '📦',
}


@calendario_bp.route('/')
@login_required
def index():
    tecnicos = []
    if current_user.es_admin:
        if current_user.es_super_admin:
            tecnicos = (User.query
                        .filter_by(is_active=True)
                        .order_by(User.username)
                        .all())
        else:
            tecnicos = (User.query
                        .filter_by(is_active=True, creado_por_id=current_user.id)
                        .order_by(User.username)
                        .all())
    return render_template('calendario/index.html', tecnicos=tecnicos)


@calendario_bp.route('/api/eventos')
@login_required
def api_eventos():
    """Devuelve los avisos con fecha_cita en el rango pedido por FullCalendar."""
    start_str   = request.args.get('start', '')
    end_str     = request.args.get('end', '')
    tecnico_id  = request.args.get('tecnico_id', type=int)
    tipo_filter = request.args.get('tipo', '')
    ver_todos   = request.args.get('todos', '0') == '1'  # admins pueden ver todos los equipos

    try:
        start = datetime.fromisoformat(start_str[:10]).date()
        end   = datetime.fromisoformat(end_str[:10]).date()
    except (ValueError, TypeError):
        return jsonify([])

    q = Aviso.query.filter(
        Aviso.fecha_cita != None,
        Aviso.fecha_cita >= start,
        Aviso.fecha_cita <  end,
    )

    if not current_user.es_admin:
        q = q.filter(db.or_(
            Aviso.asignado_a == current_user.id,
            Aviso.created_by == current_user.id,
        ))
    elif tecnico_id:
        q = q.filter(Aviso.asignado_a == tecnico_id)
    elif not current_user.es_super_admin and not ver_todos:
        # Admin regular: solo su equipo
        equipo_ids = [u.id for u in User.query.filter_by(creado_por_id=current_user.id).all()]
        equipo_ids.append(current_user.id)
        q = q.filter(db.or_(
            Aviso.asignado_a.in_(equipo_ids),
            Aviso.created_by == current_user.id,
        ))
    # si ver_todos==True o es super_admin sin filtro: no hay restricción adicional

    if tipo_filter:
        q = q.filter_by(tipo_servicio=tipo_filter)

    avisos = q.order_by(Aviso.fecha_cita, Aviso.hora_cita).all()

    # IDs del equipo propio (para marcar avisos de otros admins)
    if current_user.es_admin and not current_user.es_super_admin:
        mi_equipo = {u.id for u in User.query.filter_by(creado_por_id=current_user.id).all()}
        mi_equipo.add(current_user.id)
    else:
        mi_equipo = None  # super_admin: sin distinción

    eventos = []
    for a in avisos:
        bg, border, text = _COLORES.get(
            a.estado, ('#6c757d', '#565e64', '#ffffff')
        )

        icono = _ICONOS_SERVICIO.get(a.tipo_servicio or 'reparacion', '🔧')
        calle_titulo = a.calle or a.nombre_cliente or 'Sin dirección'
        titulo = f'{icono} {calle_titulo}'

        tecnico_nombre = a.tecnico.display_name if a.tecnico else ''
        tid            = a.asignado_a or 0

        # Si el aviso es de otro equipo, indicarlo visualmente
        es_otro_equipo = (
            mi_equipo is not None and
            a.asignado_a is not None and
            a.asignado_a not in mi_equipo
        )
        if es_otro_equipo:
            border = '#adb5bd'
            text   = text if text == '#ffffff' else '#555'

        # Fecha+hora para FullCalendar (si hay hora la incluye)
        start_iso = a.fecha_cita.isoformat()
        if a.hora_cita:
            start_iso = f'{start_iso}T{a.hora_cita}:00'

        admin_nombre = ''
        if a.admin_asignado:
            admin_nombre = a.admin_asignado.display_name

        eventos.append({
            'id':              a.id,
            'title':           titulo,
            'start':           start_iso,
            'url':             f'/avisos/{a.id}',
            'backgroundColor': bg,
            'borderColor':     border,
            'textColor':       text,
            'classNames':      ['fc-otro-equipo'] if es_otro_equipo else [],
            'extendedProps': {
                'estado':           a.estado_label(),
                'nombre_cliente':   a.nombre_cliente,
                'calle':            a.calle or '',
                'telefono':         a.telefono,
                'electrodomestico': a.electrodomestico or '',
                'marca':            a.marca or '',
                'tecnico':          tecnico_nombre,
                'tecnico_id':       tid,
                'hora_cita':        a.hora_cita or '',
                'localidad':        a.localidad or '',
                'tipo_servicio':    a.tipo_servicio_label(),
                'tipo_icon':        icono,
                'origen':           a.origen_label(),
                'es_otro_equipo':   es_otro_equipo,
                'admin_nombre':     admin_nombre,
            },
        })

    return jsonify(eventos)


@calendario_bp.route('/api/eventos/<int:id>/reschedule', methods=['PATCH'])
@login_required
def reschedule_evento(id):
    """
    Actualiza la fecha_cita de un aviso vía drag-and-drop del calendario.
    Body JSON: { "fecha_cita": "YYYY-MM-DD" }
    """
    aviso = Aviso.query.get_or_404(id)

    if not aviso.puede_editar(current_user):
        return jsonify({'error': 'Sin permiso para editar este aviso.'}), 403

    data = request.get_json(silent=True) or {}
    fecha_str = data.get('fecha_cita', '')

    try:
        from datetime import date as date_type
        aviso.fecha_cita = date_type.fromisoformat(fecha_str[:10])
        db.session.commit()
        return jsonify({'ok': True, 'fecha_cita': aviso.fecha_cita.isoformat()})
    except (ValueError, TypeError) as exc:
        return jsonify({'error': f'Fecha inválida: {exc}'}), 400
