from datetime import date, timedelta
from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from sqlalchemy import func, extract
from extensions import db
from models import Aviso, User

estadisticas_bp = Blueprint('estadisticas', __name__, url_prefix='/stats')


@estadisticas_bp.route('/')
@login_required
def index():
    return render_template('estadisticas/index.html')


@estadisticas_bp.route('/api/resumen')
@login_required
def api_resumen():
    """Resumen general: totales, morosos, facturación del mes."""
    hoy = date.today()
    mes = hoy.month
    anio = hoy.year

    # Filtrar por técnico si no es admin
    base = Aviso.query
    if not current_user.es_admin:
        base = base.filter(
            db.or_(Aviso.asignado_a == current_user.id,
                   Aviso.created_by == current_user.id)
        )

    total_activos  = base.filter(Aviso.estado != 'finalizado').count()
    total_morosos  = base.filter(Aviso.cobro_estado == 'moroso').count()
    finalizados    = base.filter(Aviso.estado == 'finalizado').count()

    # Facturación mes actual (total_cliente = mano_obra + gastos_extra - descuento)
    facturado_mes = db.session.query(
        func.sum(
            (func.coalesce(Aviso.precio_mano_obra, 0) +
             func.coalesce(Aviso.gastos_extra, 0) -
             func.coalesce(Aviso.descuento, 0))
        )
    ).filter(
        Aviso.estado == 'finalizado',
        extract('month', Aviso.updated_at) == mes,
        extract('year',  Aviso.updated_at) == anio,
        *([db.or_(Aviso.asignado_a == current_user.id,
                  Aviso.created_by == current_user.id)]
          if not current_user.es_admin else [])
    ).scalar() or 0.0

    beneficio_mes = db.session.query(
        func.sum(
            (func.coalesce(Aviso.precio_mano_obra, 0) +
             func.coalesce(Aviso.gastos_extra, 0) -
             func.coalesce(Aviso.descuento, 0) -
             func.coalesce(Aviso.coste_materiales, 0))
        )
    ).filter(
        Aviso.estado == 'finalizado',
        extract('month', Aviso.updated_at) == mes,
        extract('year',  Aviso.updated_at) == anio,
        *([db.or_(Aviso.asignado_a == current_user.id,
                  Aviso.created_by == current_user.id)]
          if not current_user.es_admin else [])
    ).scalar() or 0.0

    pendiente_cobro = db.session.query(
        func.sum(
            func.coalesce(Aviso.precio_mano_obra, 0) +
            func.coalesce(Aviso.gastos_extra, 0) -
            func.coalesce(Aviso.descuento, 0)
        )
    ).filter(
        Aviso.estado == 'finalizado',
        Aviso.cobro_estado == 'pendiente',
        *([db.or_(Aviso.asignado_a == current_user.id,
                  Aviso.created_by == current_user.id)]
          if not current_user.es_admin else [])
    ).scalar() or 0.0

    return jsonify({
        'total_activos':    total_activos,
        'total_morosos':    total_morosos,
        'finalizados':      finalizados,
        'facturado_mes':    round(facturado_mes, 2),
        'beneficio_mes':    round(beneficio_mes, 2),
        'pendiente_cobro':  round(pendiente_cobro, 2),
    })


@estadisticas_bp.route('/api/ingresos/<periodo>')
@login_required
def api_ingresos(periodo):
    """Ingresos agrupados por día (30d), semana (8sem) o mes (12m)."""
    hoy = date.today()

    filtro_tecnico = (
        [] if current_user.es_admin
        else [db.or_(Aviso.asignado_a == current_user.id,
                     Aviso.created_by == current_user.id)]
    )

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
            *filtro_tecnico
        ).group_by(func.date(Aviso.updated_at)).order_by('periodo').all()

        labels = [(inicio + timedelta(days=i)).strftime('%d/%m') for i in range(30)]
        data_map = {r.periodo: (r.total or 0, r.beneficio or 0, r.num) for r in rows}
        totales   = []
        beneficios = []
        nums      = []
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
            *filtro_tecnico
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
            *filtro_tecnico
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
    """Top 10 aparatos más reparados."""
    filtro_tecnico = (
        [] if current_user.es_admin
        else [db.or_(Aviso.asignado_a == current_user.id,
                     Aviso.created_by == current_user.id)]
    )
    rows = db.session.query(
        Aviso.electrodomestico,
        func.count(Aviso.id).label('total')
    ).filter(
        Aviso.electrodomestico.isnot(None),
        Aviso.electrodomestico != '',
        *filtro_tecnico
    ).group_by(Aviso.electrodomestico).order_by(db.desc('total')).limit(10).all()

    return jsonify({'labels': [r.electrodomestico for r in rows],
                    'values': [r.total for r in rows]})


@estadisticas_bp.route('/api/morosos')
@login_required
def api_morosos():
    """Lista de avisos con cobro_estado = moroso."""
    filtro_tecnico = (
        [] if current_user.es_admin
        else [db.or_(Aviso.asignado_a == current_user.id,
                     Aviso.created_by == current_user.id)]
    )
    avisos = Aviso.query.filter(
        Aviso.cobro_estado == 'moroso',
        *filtro_tecnico
    ).order_by(Aviso.updated_at.desc()).all()

    resultado = []
    for av in avisos:
        resultado.append({
            'id':       av.id,
            'nombre':   av.nombre_cliente,
            'telefono': av.telefono,
            'importe':  av.total_cliente,
            'fecha':    av.fecha_aviso.strftime('%d/%m/%Y'),
            'aparato':  av.electrodomestico or '',
        })
    return jsonify(resultado)


@estadisticas_bp.route('/api/tecnicos')
@login_required
def api_tecnicos():
    """Rendimiento por técnico (solo admin)."""
    if not current_user.es_admin:
        return jsonify({'error': 'Solo administradores'}), 403

    tecnicos = User.query.filter_by(is_active=True).all()
    resultado = []
    for t in tecnicos:
        activos     = Aviso.query.filter_by(asignado_a=t.id).filter(Aviso.estado != 'finalizado').count()
        finalizados = Aviso.query.filter_by(asignado_a=t.id, estado='finalizado').count()
        morosos     = Aviso.query.filter_by(asignado_a=t.id, cobro_estado='moroso').count()

        expr_total = (
            func.coalesce(Aviso.precio_mano_obra, 0) +
            func.coalesce(Aviso.gastos_extra, 0) -
            func.coalesce(Aviso.descuento, 0)
        )
        facturado = db.session.query(func.sum(expr_total)).filter(
            Aviso.asignado_a == t.id,
            Aviso.estado == 'finalizado'
        ).scalar() or 0.0

        resultado.append({
            'nombre':       t.display_name,
            'activos':      activos,
            'finalizados':  finalizados,
            'morosos':      morosos,
            'facturado':    round(facturado, 2),
        })

    resultado.sort(key=lambda x: x['facturado'], reverse=True)
    return jsonify(resultado)
