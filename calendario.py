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


@calendario_bp.route('/')
@login_required
def index():
    tecnicos = []
    if current_user.es_admin:
        tecnicos = (User.query
                    .filter_by(is_active=True)
                    .order_by(User.username)
                    .all())
    return render_template('calendario/index.html', tecnicos=tecnicos)


@calendario_bp.route('/api/eventos')
@login_required
def api_eventos():
    """Devuelve los avisos con fecha_cita en el rango pedido por FullCalendar."""
    start_str = request.args.get('start', '')
    end_str   = request.args.get('end', '')
    tecnico_id = request.args.get('tecnico_id', type=int)

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
        # Técnico solo ve sus avisos
        q = q.filter(db.or_(
            Aviso.asignado_a == current_user.id,
            Aviso.created_by == current_user.id,
        ))
    elif tecnico_id:
        q = q.filter(Aviso.asignado_a == tecnico_id)

    avisos = q.order_by(Aviso.fecha_cita).all()

    eventos = []
    for a in avisos:
        bg, border, text = _COLORES.get(
            a.estado, ('#6c757d', '#565e64', '#ffffff')
        )

        titulo = a.nombre_cliente
        if a.electrodomestico:
            titulo += f' · {a.electrodomestico}'

        tecnico_nombre = a.tecnico.display_name if a.tecnico else ''

        eventos.append({
            'id':              a.id,
            'title':           titulo,
            'start':           a.fecha_cita.isoformat(),
            'url':             f'/avisos/{a.id}',
            'backgroundColor': bg,
            'borderColor':     border,
            'textColor':       text,
            'extendedProps': {
                'estado':         a.estado_label(),
                'telefono':       a.telefono,
                'electrodomestico': a.electrodomestico or '',
                'tecnico':        tecnico_nombre,
                'localidad':      a.localidad or '',
                'marca':          a.marca or '',
            },
        })

    return jsonify(eventos)
