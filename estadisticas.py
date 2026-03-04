from datetime import date, timedelta
from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, extract
from extensions import db
from models import Aviso, User

estadisticas_bp = Blueprint('estadisticas', __name__, url_prefix='/stats')


def _filtro_equipo():
    """
    Devuelve filtros SQLAlchemy según el rol del usuario:
    - super_admin: sin filtro (ve todo)
    - admin: solo avisos de su equipo (asignados a usuarios que él creó, o creados por él)
    - tecnico/repartidor: solo sus propios avisos
    """
    if current_user.es_super_admin:
        return []
    if current_user.es_admin:
        # IDs de los usuarios del equipo
        equipo_ids = [u.id for u in User.query.filter_by(creado_por_id=current_user.id).all()]
        equipo_ids.append(current_user.id)
        return [db.or_(
            Aviso.asignado_a.in_(equipo_ids),
            Aviso.created_by == current_user.id,
        )]
    # Trabajador: solo sus avisos
    return [db.or_(Aviso.asignado_a == current_user.id,
                   Aviso.created_by == current_user.id)]


@estadisticas_bp.route('/')
@login_required
def index():
    return render_template('estadisticas/index.html')


@estadisticas_bp.route('/api/resumen')
@login_required
def api_resumen():
    hoy = date.today()
    mes = hoy.month
    anio = hoy.year

    filtro = _filtro_equipo()
    base = Aviso.query.filter(*filtro)

    total_activos  = base.filter(Aviso.estado != 'finalizado').count()
    total_morosos  = base.filter(Aviso.cobro_estado == 'moroso').count()
    finalizados    = base.filter(Aviso.estado == 'finalizado').count()

    expr_total = (
        func.coalesce(Aviso.precio_mano_obra, 0) +
        func.coalesce(Aviso.gastos_extra, 0) -
        func.coalesce(Aviso.descuento, 0)
    )

    facturado_mes = db.session.query(func.sum(expr_total)).filter(
        Aviso.estado == 'finalizado',
        extract('month', Aviso.updated_at) == mes,
        extract('year',  Aviso.updated_at) == anio,
        *filtro
    ).scalar() or 0.0

    beneficio_mes = db.session.query(func.sum(
        expr_total - func.coalesce(Aviso.coste_materiales, 0)
    )).filter(
        Aviso.estado == 'finalizado',
        extract('month', Aviso.updated_at) == mes,
        extract('year',  Aviso.updated_at) == anio,
        *filtro
    ).scalar() or 0.0

    pendiente_cobro = db.session.query(func.sum(expr_total)).filter(
        Aviso.estado == 'finalizado',
        Aviso.cobro_estado == 'pendiente',
        *filtro
    ).scalar() or 0.0

    return jsonify({
        'total_activos':   total_activos,
        'total_morosos':   total_morosos,
        'finalizados':     finalizados,
        'facturado_mes':   round(facturado_mes, 2),
        'beneficio_mes':   round(beneficio_mes, 2),
        'pendiente_cobro': round(pendiente_cobro, 2),
    })


@estadisticas_bp.route('/api/ingresos/<periodo>')
@login_required
def api_ingresos(periodo):
    hoy = date.today()
    filtro = _filtro_equipo()

    expr_total = (
        func.coalesce(Aviso.precio_mano_obra, 0) +
        func.coalesce(Aviso.gastos_extra, 0) -
        func.coalesce(Aviso.descuento, 0)
    )
    expr_beneficio = expr_total - func.coalesce(Aviso.coste_materiales, 0)

    if periodo == 'dia':
        inicio = hoy - timedelta(days=29)
        rows = db.session.query(
            func.date(Aviso.updated_at).label('periodo'),
            func.sum(expr_total).label('total'),
            func.sum(expr_beneficio).label('beneficio'),
            func.count(Aviso.id).label('num'),
        ).filter(
            Aviso.estado == 'finalizado',
            Aviso.updated_at >= inicio,
            *filtro
        ).group_by(func.date(Aviso.updated_at)).order_by('periodo').all()

        labels = [(inicio + timedelta(days=i)).strftime('%d/%m') for i in range(30)]
        data_map = {r.periodo: (r.total or 0, r.beneficio or 0, r.num) for r in rows}
        totales = []
        beneficios = []
        nums = []
        for i in range(30):
            d = (inicio + timedelta(days=i)).strftime('%Y-%m-%d')
            v = data_map.get(d, (0, 0, 0))
            totales.append(round(v[0], 2))
            beneficios.append(round(v[1], 2))
            nums.append(v[2])

    elif periodo == 'semana':
        inicio = hoy - timedelta(weeks=7)
        rows = db.session.query(
            extract('year',  Aviso.updated_at).label('anio'),
            extract('week',  Aviso.updated_at).label('semana'),
            func.sum(expr_total).label('total'),
            func.sum(expr_beneficio).label('beneficio'),
            func.count(Aviso.id).label('num'),
        ).filter(
            Aviso.estado == 'finalizado',
            Aviso.updated_at >= inicio,
            *filtro
        ).group_by('anio', 'semana').order_by('anio', 'semana').all()

        labels = []
        totales = []
        beneficios = []
        nums = []
        for r in rows:
            labels.append(f'Sem {int(r.semana)}')
            totales.append(round(r.total or 0, 2))
            beneficios.append(round(r.beneficio or 0, 2))
            nums.append(r.num)

    else:  # mes
        rows = db.session.query(
            extract('year',  Aviso.updated_at).label('anio'),
            extract('month', Aviso.updated_at).label('mes'),
            func.sum(expr_total).label('total'),
            func.sum(expr_beneficio).label('beneficio'),
            func.count(Aviso.id).label('num'),
        ).filter(
            Aviso.estado == 'finalizado',
            Aviso.updated_at >= hoy - timedelta(days=365),
            *filtro
        ).group_by('anio', 'mes').order_by('anio', 'mes').all()

        MESES = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic']
        labels = []
        totales = []
        beneficios = []
        nums = []
        for r in rows:
            labels.append(f"{MESES[int(r.mes)-1]} {int(r.anio)}")
            totales.append(round(r.total or 0, 2))
            beneficios.append(round(r.beneficio or 0, 2))
            nums.append(r.num)

    return jsonify({'labels': labels, 'totales': totales,
                    'beneficios': beneficios, 'nums': nums})


@estadisticas_bp.route('/api/aparatos')
@login_required
def api_aparatos():
    filtro = _filtro_equipo()
    rows = db.session.query(
        Aviso.electrodomestico,
        func.count(Aviso.id).label('total')
    ).filter(
        Aviso.electrodomestico.isnot(None),
        Aviso.electrodomestico != '',
        *filtro
    ).group_by(Aviso.electrodomestico).order_by(db.desc('total')).limit(10).all()

    return jsonify({'labels': [r.electrodomestico for r in rows],
                    'values': [r.total for r in rows]})


@estadisticas_bp.route('/api/morosos')
@login_required
def api_morosos():
    filtro = _filtro_equipo()
    avisos = Aviso.query.filter(
        Aviso.cobro_estado == 'moroso',
        *filtro
    ).order_by(Aviso.updated_at.desc()).all()

    return jsonify([{
        'id':       av.id,
        'nombre':   av.nombre_cliente,
        'telefono': av.telefono,
        'importe':  av.total_cliente,
        'fecha':    av.fecha_aviso.strftime('%d/%m/%Y'),
        'aparato':  av.electrodomestico or '',
    } for av in avisos])


@estadisticas_bp.route('/api/tecnicos')
@login_required
def api_tecnicos():
    """Rendimiento por técnico — solo para admins, filtrando su equipo."""
    if not current_user.es_admin:
        return jsonify({'error': 'Solo administradores'}), 403

    if current_user.es_super_admin:
        tecnicos = User.query.filter_by(is_active=True).all()
    else:
        tecnicos = User.query.filter_by(is_active=True,
                                        creado_por_id=current_user.id).all()

    expr_total = (
        func.coalesce(Aviso.precio_mano_obra, 0) +
        func.coalesce(Aviso.gastos_extra, 0) -
        func.coalesce(Aviso.descuento, 0)
    )

    resultado = []
    for t in tecnicos:
        activos     = Aviso.query.filter_by(asignado_a=t.id).filter(Aviso.estado != 'finalizado').count()
        finalizados = Aviso.query.filter_by(asignado_a=t.id, estado='finalizado').count()
        morosos     = Aviso.query.filter_by(asignado_a=t.id, cobro_estado='moroso').count()
        facturado   = db.session.query(func.sum(expr_total)).filter(
            Aviso.asignado_a == t.id,
            Aviso.estado == 'finalizado'
        ).scalar() or 0.0

        resultado.append({
            'nombre':      t.display_name,
            'rol':         t.rol_label,
            'activos':     activos,
            'finalizados': finalizados,
            'morosos':     morosos,
            'facturado':   round(facturado, 2),
        })

    resultado.sort(key=lambda x: x['facturado'], reverse=True)
    return jsonify(resultado)
