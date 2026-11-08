from datetime import datetime, timedelta

from flask import Blueprint, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import joinedload

from avisos_servicio import (SIN_CAMBIO, ids_con_solape, minutos_de, parse_duracion,
                             parse_fecha, parse_hora, reprogramar, solapes,
                             tecnicos_asignables)
from extensions import db
from models import Aviso, DURACIONES, ESTADOS, User

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


def _ids_equipo():
    ids = {u.id for u in User.query.filter_by(creado_por_id=current_user.id).all()}
    ids.add(current_user.id)
    return ids


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
    asignables = [{'id': t.id, 'nombre': t.display_name}
                  for t in tecnicos_asignables(current_user)]
    return render_template('calendario/index.html',
                           tecnicos=tecnicos,
                           asignables=asignables,
                           estados=ESTADOS,
                           duraciones=DURACIONES)


def _evento(a, mi_equipo, con_solape=False):
    """Representa un aviso como evento de FullCalendar."""
    bg, border, text = _COLORES.get(a.estado, ('#6c757d', '#565e64', '#ffffff'))
    icono = _ICONOS_SERVICIO.get(a.tipo_servicio or 'reparacion', '🔧')

    es_otro_equipo = (
        mi_equipo is not None and
        a.asignado_a is not None and
        a.asignado_a not in mi_equipo
    )
    if es_otro_equipo:
        border = '#adb5bd'
        text = text if text == '#ffffff' else '#555'

    puede_editar = current_user.es_admin_o_superior and a.puede_editar(current_user)
    inicio_min = minutos_de(a.hora_cita)
    con_hora = inicio_min is not None

    evento = {
        'id':               a.id,
        'title':            f"{icono} {a.calle or a.nombre_cliente or 'Sin dirección'}",
        'start':            a.fecha_cita.isoformat(),
        'allDay':           not con_hora,
        'url':              url_for('avisos.detail', id=a.id),
        'backgroundColor':  bg,
        'borderColor':      border,
        'textColor':        text,
        'editable':         puede_editar,
        'classNames':       ['fc-otro-equipo'] if es_otro_equipo else [],
        'extendedProps': {
            'fecha':            a.fecha_cita.isoformat(),
            'estado':           a.estado_label(),
            'estado_clave':     a.estado,
            'nombre_cliente':   a.nombre_cliente,
            'calle':            a.calle or '',
            'telefono':         a.telefono,
            'electrodomestico': a.electrodomestico or '',
            'marca':            a.marca or '',
            'tecnico':          a.tecnico.display_name if a.tecnico else '',
            'tecnico_id':       a.asignado_a or 0,
            'hora_cita':        a.hora_cita or '',
            'duracion_min':     a.duracion_efectiva,
            'duracion_label':   a.duracion_label,
            'localidad':        a.localidad or '',
            'tipo_servicio':    a.tipo_servicio_label(),
            'tipo_icon':        icono,
            'origen':           a.origen_label(),
            'es_otro_equipo':   es_otro_equipo,
            'admin_nombre':     a.admin_asignado.display_name if a.admin_asignado else '',
            'puede_editar':     puede_editar,
            'solape':           con_solape,
        },
    }

    if con_hora:
        inicio = datetime.combine(a.fecha_cita, datetime.min.time()) + timedelta(minutes=inicio_min)
        evento['start'] = inicio.isoformat(timespec='seconds')
        evento['end'] = (inicio + timedelta(minutes=a.duracion_efectiva)).isoformat(timespec='seconds')

    return evento


@calendario_bp.route('/api/eventos')
@login_required
def api_eventos():
    """Devuelve los avisos con fecha_cita en el rango pedido por FullCalendar."""
    tecnico_id    = request.args.get('tecnico_id', type=int)
    tipo_filter   = request.args.get('tipo', '')
    estado_filter = request.args.get('estado', '')
    ver_todos     = request.args.get('todos', '0') == '1'  # admins pueden ver todos los equipos

    try:
        start = parse_fecha(request.args.get('start', ''))
        end   = parse_fecha(request.args.get('end', ''))
    except ValueError:
        return jsonify([])
    if not start or not end:
        return jsonify([])

    q = Aviso.query.options(
        joinedload(Aviso.tecnico),
        joinedload(Aviso.admin_asignado),
    ).filter(
        Aviso.fecha_cita != None,  # noqa: E711
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
        # Admin regular: su equipo, lo suyo y las citas todavía sin dueño
        q = q.filter(db.or_(
            Aviso.asignado_a.in_(_ids_equipo()),
            Aviso.created_by == current_user.id,
            Aviso.admin_asignado_id == current_user.id,
            db.and_(Aviso.admin_asignado_id == None,  # noqa: E711
                    Aviso.asignado_a == None),  # noqa: E711
        ))
    # si ver_todos==True o es super_admin sin filtro: no hay restricción adicional

    if tipo_filter:
        q = q.filter(Aviso.tipo_servicio == tipo_filter)
    if estado_filter == 'activos':
        q = q.filter(Aviso.estado != 'finalizado')
    elif estado_filter:
        q = q.filter(Aviso.estado == estado_filter)

    avisos = q.order_by(Aviso.fecha_cita, Aviso.hora_cita).all()

    # IDs del equipo propio (para marcar avisos de otros admins)
    mi_equipo = _ids_equipo() if current_user.es_admin and not current_user.es_super_admin else None
    con_solape = ids_con_solape(avisos)

    return jsonify([_evento(a, mi_equipo, a.id in con_solape) for a in avisos])


@calendario_bp.route('/api/eventos/<int:id>/reschedule', methods=['PATCH'])
@login_required
def reschedule_evento(id):
    """
    Cambia la cita de un aviso desde el calendario.
    Body JSON: {
      "fecha_cita": "YYYY-MM-DD" | null,  (obligatorio; null quita la cita)
      "hora_cita": "HH:MM" | null,        (si falta, se conserva)
      "duracion_min": 60,                 (opcional)
      "asignado_a": 3 | null              (opcional, solo admins)
    }
    """
    aviso = Aviso.query.get_or_404(id)

    if not aviso.puede_editar(current_user):
        return jsonify({'error': 'Sin permiso para editar este aviso.'}), 403

    data = request.get_json(silent=True) or {}
    if 'fecha_cita' not in data:
        return jsonify({'error': 'Falta la fecha de la cita.'}), 400

    try:
        fecha = parse_fecha(data['fecha_cita'])
        hora = parse_hora(data['hora_cita']) if 'hora_cita' in data else aviso.hora_cita
        duracion = parse_duracion(data['duracion_min']) if 'duracion_min' in data else None
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    tecnico_id = SIN_CAMBIO
    if 'asignado_a' in data:
        if not current_user.es_admin_o_superior:
            return jsonify({'error': 'Solo un administrador puede cambiar el técnico.'}), 403
        tecnico_id = data['asignado_a'] or None
        if tecnico_id != aviso.asignado_a and tecnico_id is not None:
            if tecnico_id not in {t.id for t in tecnicos_asignables(current_user)}:
                return jsonify({'error': 'No puedes asignar a ese técnico.'}), 400

    reprogramar(aviso, current_user, fecha, hora, duracion, tecnico_id)

    return jsonify({
        'ok': True,
        'fecha_cita': aviso.fecha_cita.isoformat() if aviso.fecha_cita else None,
        'hora_cita': aviso.hora_cita,
        'solapes': [{'id': s.id,
                     'cliente': s.nombre_cliente,
                     'hora': s.hora_cita} for s in solapes(aviso)],
    })
