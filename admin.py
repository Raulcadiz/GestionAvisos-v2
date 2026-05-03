from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from sqlalchemy import func
from extensions import db
from models import User, Aviso, PrecioInstalacion

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    """Requiere rol admin o super_admin."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def super_admin_required(f):
    """Requiere rol super_admin exclusivamente."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_super_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _stats_usuario(user_id):
    """Estadísticas rápidas para un usuario."""
    return {
        'total':       Aviso.query.filter_by(asignado_a=user_id).count(),
        'activos':     Aviso.query.filter(Aviso.asignado_a == user_id,
                                          Aviso.estado != 'finalizado').count(),
        'finalizados': Aviso.query.filter_by(asignado_a=user_id, estado='finalizado').count(),
        'morosos':     Aviso.query.filter_by(asignado_a=user_id, cobro_estado='moroso').count(),
        'facturado':   round(db.session.query(
            func.sum(
                func.coalesce(Aviso.precio_mano_obra, 0) +
                func.coalesce(Aviso.gastos_extra, 0) -
                func.coalesce(Aviso.descuento, 0)
            )
        ).filter(Aviso.asignado_a == user_id, Aviso.estado == 'finalizado').scalar() or 0, 2),
    }


@admin_bp.route('/')
@login_required
@admin_required
def index():
    if current_user.es_super_admin:
        # Super admin ve todos los usuarios
        usuarios = User.query.order_by(User.rol, User.username).all()
    else:
        # Admin regular ve solo su equipo
        usuarios = User.query.filter_by(creado_por_id=current_user.id).order_by(User.username).all()

    stats = {u.id: _stats_usuario(u.id) for u in usuarios}
    return render_template('admin/index.html', usuarios=usuarios, stats=stats)


@admin_bp.route('/usuario/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_tecnico():
    # Determinar roles permitidos según quien crea
    if current_user.es_super_admin:
        roles_permitidos = ['super_admin', 'admin', 'tecnico', 'repartidor']
    else:
        roles_permitidos = ['tecnico', 'repartidor']

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        nombre   = request.form.get('nombre_completo', '').strip()
        telefono = request.form.get('telefono_perfil', '').strip()
        tg_chat  = request.form.get('telegram_chat_id', '').strip()
        rol      = request.form.get('rol', 'tecnico')

        # Validar que el rol sea permitido
        if rol not in roles_permitidos:
            flash('Rol no permitido.', 'danger')
            return render_template('admin/form_tecnico.html', tecnico=None,
                                   roles_permitidos=roles_permitidos)

        if not username or not password:
            flash('Usuario y contraseña son obligatorios.', 'danger')
            return render_template('admin/form_tecnico.html', tecnico=None,
                                   roles_permitidos=roles_permitidos)

        if User.query.filter_by(username=username).first():
            flash(f'El usuario "{username}" ya existe.', 'danger')
            return render_template('admin/form_tecnico.html', tecnico=None,
                                   roles_permitidos=roles_permitidos)

        user = User(
            username=username,
            password=generate_password_hash(password),
            nombre_completo=nombre or None,
            telefono_perfil=telefono or None,
            telegram_chat_id=tg_chat or None,
            rol=rol,
            is_active=True,
            creado_por_id=current_user.id,
        )
        db.session.add(user)
        db.session.commit()
        flash(f'Usuario "{username}" creado correctamente.', 'success')
        return redirect(url_for('admin.index'))

    return render_template('admin/form_tecnico.html', tecnico=None,
                           roles_permitidos=roles_permitidos)


@admin_bp.route('/usuario/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_tecnico(id):
    tecnico = User.query.get_or_404(id)

    # Solo super_admin puede editar cualquier usuario
    # Admin regular solo puede editar a los de su equipo
    if not current_user.es_super_admin:
        if tecnico.creado_por_id != current_user.id:
            abort(403)

    if current_user.es_super_admin:
        roles_permitidos = ['super_admin', 'admin', 'tecnico', 'repartidor']
    else:
        roles_permitidos = ['tecnico', 'repartidor']

    if request.method == 'POST':
        tecnico.nombre_completo  = request.form.get('nombre_completo', '').strip() or None
        tecnico.telefono_perfil  = request.form.get('telefono_perfil', '').strip() or None
        tecnico.telegram_chat_id = request.form.get('telegram_chat_id', '').strip() or None

        nuevo_rol = request.form.get('rol', tecnico.rol)
        if nuevo_rol in roles_permitidos:
            tecnico.rol = nuevo_rol

        nueva_password = request.form.get('password', '').strip()
        if nueva_password:
            tecnico.password = generate_password_hash(nueva_password)

        db.session.commit()
        flash(f'Usuario "{tecnico.username}" actualizado.', 'success')
        return redirect(url_for('admin.index'))

    return render_template('admin/form_tecnico.html', tecnico=tecnico,
                           roles_permitidos=roles_permitidos)


@admin_bp.route('/usuario/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_tecnico(id):
    tecnico = User.query.get_or_404(id)

    # No se puede desactivar a un super_admin
    if tecnico.es_super_admin:
        flash('No puedes desactivar a un super administrador.', 'danger')
        return redirect(url_for('admin.index'))

    # Admin regular solo puede gestionar su equipo
    if not current_user.es_super_admin and tecnico.creado_por_id != current_user.id:
        abort(403)

    tecnico.is_active = not tecnico.is_active
    db.session.commit()
    estado = 'activado' if tecnico.is_active else 'desactivado'
    flash(f'Usuario "{tecnico.username}" {estado}.', 'info')
    return redirect(url_for('admin.index'))


# Mantener ruta antigua por compatibilidad con links existentes
@admin_bp.route('/tecnico/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_tecnico_legacy():
    return redirect(url_for('admin.nuevo_tecnico'))


@admin_bp.route('/tecnico/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_tecnico_legacy(id):
    return redirect(url_for('admin.editar_tecnico', id=id))


# ── Precios de instalación ─────────────────────────────────────────────────

@admin_bp.route('/precios')
@login_required
@admin_required
def precios():
    items = PrecioInstalacion.query.order_by(PrecioInstalacion.orden, PrecioInstalacion.aparato).all()
    return render_template('admin/precios.html', items=items)


@admin_bp.route('/precios/nuevo', methods=['POST'])
@login_required
@admin_required
def precio_nuevo():
    aparato = request.form.get('aparato', '').strip()
    desc    = request.form.get('descripcion', '').strip()
    precio  = request.form.get('precio', '0').strip()
    orden   = request.form.get('orden', '0').strip()
    if not aparato:
        flash('El nombre del aparato es obligatorio.', 'danger')
        return redirect(url_for('admin.precios'))
    try:
        precio_f = float(precio)
        orden_i  = int(orden)
    except ValueError:
        flash('Precio u orden inválido.', 'danger')
        return redirect(url_for('admin.precios'))
    item = PrecioInstalacion(
        aparato=aparato,
        descripcion=desc or None,
        precio=precio_f,
        orden=orden_i,
        activo=True,
    )
    db.session.add(item)
    db.session.commit()
    flash(f'Precio "{aparato}" añadido.', 'success')
    return redirect(url_for('admin.precios'))


@admin_bp.route('/precios/<int:id>/editar', methods=['POST'])
@login_required
@admin_required
def precio_editar(id):
    item = PrecioInstalacion.query.get_or_404(id)
    item.aparato     = request.form.get('aparato', item.aparato).strip()
    item.descripcion = request.form.get('descripcion', '').strip() or None
    try:
        item.precio = float(request.form.get('precio', item.precio))
        item.orden  = int(request.form.get('orden', item.orden))
    except ValueError:
        flash('Precio u orden inválido.', 'danger')
        return redirect(url_for('admin.precios'))
    item.activo = request.form.get('activo') == '1'
    db.session.commit()
    flash(f'Precio "{item.aparato}" actualizado.', 'success')
    return redirect(url_for('admin.precios'))


@admin_bp.route('/precios/<int:id>/eliminar', methods=['POST'])
@login_required
@admin_required
def precio_eliminar(id):
    item = PrecioInstalacion.query.get_or_404(id)
    nombre = item.aparato
    db.session.delete(item)
    db.session.commit()
    flash(f'Precio "{nombre}" eliminado.', 'warning')
    return redirect(url_for('admin.precios'))


@admin_bp.route('/precios/api')
@login_required
def precios_api():
    """JSON con todos los precios activos, para el formulario de avisos."""
    items = (PrecioInstalacion.query
             .filter_by(activo=True)
             .order_by(PrecioInstalacion.orden, PrecioInstalacion.aparato)
             .all())
    return jsonify([{
        'id':          i.id,
        'aparato':     i.aparato,
        'descripcion': i.descripcion or '',
        'precio':      i.precio,
    } for i in items])
