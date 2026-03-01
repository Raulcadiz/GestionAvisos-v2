from functools import wraps
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from extensions import db
from models import User, Aviso

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.es_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.route('/')
@login_required
@admin_required
def index():
    tecnicos = User.query.order_by(User.rol, User.username).all()
    # Estadísticas rápidas por técnico
    stats = {}
    for t in tecnicos:
        stats[t.id] = {
            'total':      Aviso.query.filter_by(asignado_a=t.id).count(),
            'activos':    Aviso.query.filter(Aviso.asignado_a==t.id, Aviso.estado!='finalizado').count(),
            'finalizados':Aviso.query.filter_by(asignado_a=t.id, estado='finalizado').count(),
            'morosos':    Aviso.query.filter_by(asignado_a=t.id, cobro_estado='moroso').count(),
        }
    return render_template('admin/index.html', tecnicos=tecnicos, stats=stats)


@admin_bp.route('/tecnico/nuevo', methods=['GET', 'POST'])
@login_required
@admin_required
def nuevo_tecnico():
    if request.method == 'POST':
        username   = request.form.get('username', '').strip()
        password   = request.form.get('password', '').strip()
        nombre     = request.form.get('nombre_completo', '').strip()
        telefono   = request.form.get('telefono_perfil', '').strip()
        tg_chat    = request.form.get('telegram_chat_id', '').strip()
        rol        = request.form.get('rol', 'tecnico')

        if not username or not password:
            flash('Usuario y contraseña son obligatorios.', 'danger')
            return render_template('admin/form_tecnico.html', tecnico=None)

        if User.query.filter_by(username=username).first():
            flash(f'El usuario "{username}" ya existe.', 'danger')
            return render_template('admin/form_tecnico.html', tecnico=None)

        user = User(
            username=username,
            password=generate_password_hash(password),
            nombre_completo=nombre or None,
            telefono_perfil=telefono or None,
            telegram_chat_id=tg_chat or None,
            rol=rol,
            is_active=True,
        )
        db.session.add(user)
        db.session.commit()
        flash(f'Técnico "{username}" creado correctamente.', 'success')
        return redirect(url_for('admin.index'))

    return render_template('admin/form_tecnico.html', tecnico=None)


@admin_bp.route('/tecnico/<int:id>/editar', methods=['GET', 'POST'])
@login_required
@admin_required
def editar_tecnico(id):
    tecnico = User.query.get_or_404(id)

    if request.method == 'POST':
        tecnico.nombre_completo  = request.form.get('nombre_completo', '').strip() or None
        tecnico.telefono_perfil  = request.form.get('telefono_perfil', '').strip() or None
        tecnico.telegram_chat_id = request.form.get('telegram_chat_id', '').strip() or None
        tecnico.rol              = request.form.get('rol', tecnico.rol)

        nueva_password = request.form.get('password', '').strip()
        if nueva_password:
            tecnico.password = generate_password_hash(nueva_password)

        db.session.commit()
        flash(f'Técnico "{tecnico.username}" actualizado.', 'success')
        return redirect(url_for('admin.index'))

    return render_template('admin/form_tecnico.html', tecnico=tecnico)


@admin_bp.route('/tecnico/<int:id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_tecnico(id):
    tecnico = User.query.get_or_404(id)
    if tecnico.username == 'admin':
        flash('No puedes desactivar al administrador principal.', 'danger')
        return redirect(url_for('admin.index'))
    tecnico.is_active = not tecnico.is_active
    db.session.commit()
    estado = 'activado' if tecnico.is_active else 'desactivado'
    flash(f'Técnico "{tecnico.username}" {estado}.', 'info')
    return redirect(url_for('admin.index'))
