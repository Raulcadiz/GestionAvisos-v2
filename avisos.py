import os
import uuid
from datetime import date

from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, current_app, send_from_directory,
                   jsonify)
from flask_login import login_required, current_user
from PIL import Image

from extensions import db
from models import Aviso, Photo, ESTADOS, ELECTRODOMESTICOS, COBRO_ESTADOS, User
from telegram_bot import notificar_aviso_nuevo, notificar_cambio_estado

avisos_bp = Blueprint('avisos', __name__, url_prefix='/avisos')


def allowed_file(filename):
    return ('.' in filename and
            filename.rsplit('.', 1)[1].lower() in
            current_app.config['ALLOWED_EXTENSIONS'])


def save_photo(file_obj):
    """Guarda la foto redimensionada con nombre UUID. Devuelve el nombre guardado."""
    ext = file_obj.filename.rsplit('.', 1)[1].lower()
    stored_name = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], stored_name)

    try:
        img = Image.open(file_obj)
        img.thumbnail((1920, 1920), Image.LANCZOS)
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        img.save(filepath, optimize=True, quality=85)
    except Exception:
        # Si Pillow falla (ej. HEIC sin soporte), guardar tal cual
        file_obj.seek(0)
        file_obj.save(filepath)

    return stored_name


def delete_photo_file(filename):
    """Elimina el archivo de foto del disco."""
    filepath = os.path.join(current_app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        os.remove(filepath)


# ── Ruta para servir las fotos ─────────────────────────────────────────────

@avisos_bp.route('/uploads/<filename>')
@login_required
def uploaded_file(filename):
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)


# ── Lista y búsqueda ───────────────────────────────────────────────────────

@avisos_bp.route('/')
@login_required
def list_all():
    q = request.args.get('q', '').strip()
    estado_filter = request.args.get('estado', '')
    page = request.args.get('page', 1, type=int)

    query = Aviso.query
    # Técnicos solo ven sus avisos
    if not current_user.es_admin:
        query = query.filter(
            db.or_(Aviso.asignado_a == current_user.id,
                   Aviso.created_by == current_user.id)
        )

    if q:
        like = f'%{q}%'
        query = query.filter(
            db.or_(
                Aviso.nombre_cliente.ilike(like),
                Aviso.telefono.ilike(like),
                Aviso.calle.ilike(like),
            )
        )

    if estado_filter:
        query = query.filter_by(estado=estado_filter)

    avisos = query.order_by(Aviso.fecha_aviso.desc()).paginate(
        page=page, per_page=current_app.config['ITEMS_PER_PAGE'], error_out=False
    )

    return render_template('avisos/list.html',
                           avisos=avisos,
                           q=q,
                           estado_filter=estado_filter,
                           estados=ESTADOS,
                           cobro_estados=COBRO_ESTADOS)


# ── API búsqueda JSON ──────────────────────────────────────────────────────

@avisos_bp.route('/api/search')
@login_required
def api_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    like = f'%{q}%'
    resultados = Aviso.query.filter(
        db.or_(
            Aviso.nombre_cliente.ilike(like),
            Aviso.telefono.ilike(like),
            Aviso.calle.ilike(like),
        )
    ).order_by(Aviso.fecha_aviso.desc()).limit(10).all()

    datos = [{
        'id': a.id,
        'nombre_cliente': a.nombre_cliente,
        'telefono': a.telefono,
        'calle': a.calle or '',
        'electrodomestico': a.electrodomestico or '',
        'estado': a.estado_label(),
        'estado_class': a.estado_badge_class(),
        'url': url_for('avisos.detail', id=a.id),
    } for a in resultados]

    return jsonify(datos)


# ── Detalle ────────────────────────────────────────────────────────────────

@avisos_bp.route('/<int:id>')
@login_required
def detail(id):
    aviso = Aviso.query.get_or_404(id)
    return render_template('avisos/detail.html',
                           aviso=aviso,
                           estados=ESTADOS)


# ── Crear ──────────────────────────────────────────────────────────────────

@avisos_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def create():
    if request.method == 'POST':
        def _float_or_none(val):
            try:
                return float(val) if val.strip() else None
            except (ValueError, AttributeError):
                return None

        aviso = Aviso(
            nombre_cliente=request.form.get('nombre_cliente', '').strip(),
            telefono=request.form.get('telefono', '').strip(),
            calle=request.form.get('calle', '').strip(),
            localidad=request.form.get('localidad', '').strip(),
            electrodomestico=request.form.get('electrodomestico', '').strip(),
            marca=request.form.get('marca', '').strip(),
            descripcion=request.form.get('descripcion', '').strip(),
            notas=request.form.get('notas', '').strip(),
            estado=request.form.get('estado', 'pendiente'),
            created_by=current_user.id,
            precio_mano_obra=_float_or_none(request.form.get('precio_mano_obra', '')),
            coste_materiales=_float_or_none(request.form.get('coste_materiales', '')),
            materiales_desc=request.form.get('materiales_desc', '').strip() or None,
            descuento=_float_or_none(request.form.get('descuento', '')),
            gastos_extra=_float_or_none(request.form.get('gastos_extra', '')),
            gastos_extra_desc=request.form.get('gastos_extra_desc', '').strip() or None,
            cobro_estado=request.form.get('cobro_estado', 'pendiente'),
            asignado_a=request.form.get('asignado_a', type=int) or None,
        )

        fecha_aviso_str = request.form.get('fecha_aviso', '')
        fecha_cita_str = request.form.get('fecha_cita', '')
        if fecha_aviso_str:
            from datetime import datetime
            aviso.fecha_aviso = datetime.strptime(fecha_aviso_str, '%Y-%m-%d').date()
        if fecha_cita_str:
            from datetime import datetime
            aviso.fecha_cita = datetime.strptime(fecha_cita_str, '%Y-%m-%d').date()

        if not aviso.nombre_cliente or not aviso.telefono:
            flash('El nombre del cliente y el teléfono son obligatorios.', 'danger')
            tecnicos = User.query.filter_by(is_active=True).all()
            return render_template('avisos/form.html',
                                   aviso=None,
                                   estados=ESTADOS,
                                   cobro_estados=COBRO_ESTADOS,
                                   electrodomesticos=ELECTRODOMESTICOS,
                                   tecnicos=tecnicos)

        db.session.add(aviso)
        db.session.flush()  # Para obtener el ID antes de guardar fotos

        # Guardar fotos
        files = request.files.getlist('photos')
        for f in files:
            if f and f.filename and allowed_file(f.filename):
                stored = save_photo(f)
                photo = Photo(
                    aviso_id=aviso.id,
                    filename=stored,
                    original_name=f.filename,
                    uploaded_by=current_user.id,
                )
                db.session.add(photo)

        db.session.commit()
        notificar_aviso_nuevo(aviso)
        flash(f'Aviso #{aviso.id} creado correctamente.', 'success')
        return redirect(url_for('avisos.detail', id=aviso.id))

    tecnicos = User.query.filter_by(is_active=True).all()
    return render_template('avisos/form.html',
                           aviso=None,
                           estados=ESTADOS,
                           cobro_estados=COBRO_ESTADOS,
                           electrodomesticos=ELECTRODOMESTICOS,
                           tecnicos=tecnicos)


# ── Editar ─────────────────────────────────────────────────────────────────

@avisos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def edit(id):
    aviso = Aviso.query.get_or_404(id)

    if request.method == 'POST':
        aviso.nombre_cliente = request.form.get('nombre_cliente', '').strip()
        aviso.telefono = request.form.get('telefono', '').strip()
        aviso.calle = request.form.get('calle', '').strip()
        aviso.localidad = request.form.get('localidad', '').strip()
        aviso.electrodomestico = request.form.get('electrodomestico', '').strip()
        aviso.marca = request.form.get('marca', '').strip()
        aviso.descripcion = request.form.get('descripcion', '').strip()
        aviso.notas = request.form.get('notas', '').strip()
        aviso.estado = request.form.get('estado', aviso.estado)

        def _float_or_none(val):
            try:
                return float(val) if val.strip() else None
            except (ValueError, AttributeError):
                return None

        aviso.precio_mano_obra  = _float_or_none(request.form.get('precio_mano_obra', ''))
        aviso.coste_materiales  = _float_or_none(request.form.get('coste_materiales', ''))
        aviso.materiales_desc   = request.form.get('materiales_desc', '').strip() or None
        aviso.descuento         = _float_or_none(request.form.get('descuento', ''))
        aviso.gastos_extra      = _float_or_none(request.form.get('gastos_extra', ''))
        aviso.gastos_extra_desc = request.form.get('gastos_extra_desc', '').strip() or None
        aviso.cobro_estado      = request.form.get('cobro_estado', aviso.cobro_estado)
        asignado_raw = request.form.get('asignado_a', '')
        aviso.asignado_a = int(asignado_raw) if asignado_raw.isdigit() else None

        fecha_aviso_str = request.form.get('fecha_aviso', '')
        fecha_cita_str = request.form.get('fecha_cita', '')
        if fecha_aviso_str:
            from datetime import datetime
            aviso.fecha_aviso = datetime.strptime(fecha_aviso_str, '%Y-%m-%d').date()
        if fecha_cita_str:
            from datetime import datetime
            aviso.fecha_cita = datetime.strptime(fecha_cita_str, '%Y-%m-%d').date()
        elif request.form.get('limpiar_cita'):
            aviso.fecha_cita = None

        if not aviso.nombre_cliente or not aviso.telefono:
            flash('El nombre del cliente y el teléfono son obligatorios.', 'danger')
            tecnicos = User.query.filter_by(is_active=True).all()
            return render_template('avisos/form.html',
                                   aviso=aviso,
                                   estados=ESTADOS,
                                   cobro_estados=COBRO_ESTADOS,
                                   electrodomesticos=ELECTRODOMESTICOS,
                                   tecnicos=tecnicos)

        # Nuevas fotos
        files = request.files.getlist('photos')
        for f in files:
            if f and f.filename and allowed_file(f.filename):
                stored = save_photo(f)
                photo = Photo(
                    aviso_id=aviso.id,
                    filename=stored,
                    original_name=f.filename,
                    uploaded_by=current_user.id,
                )
                db.session.add(photo)

        db.session.commit()
        flash('Aviso actualizado correctamente.', 'success')
        return redirect(url_for('avisos.detail', id=aviso.id))

    tecnicos = User.query.filter_by(is_active=True).all()
    return render_template('avisos/form.html',
                           aviso=aviso,
                           estados=ESTADOS,
                           cobro_estados=COBRO_ESTADOS,
                           electrodomesticos=ELECTRODOMESTICOS,
                           tecnicos=tecnicos)


# ── Cambiar estado (AJAX) ──────────────────────────────────────────────────

@avisos_bp.route('/<int:id>/estado', methods=['POST'])
@login_required
def change_estado(id):
    aviso = Aviso.query.get_or_404(id)
    data = request.get_json(silent=True) or {}
    nuevo_estado = data.get('estado') or request.form.get('estado', '')

    estados_validos = [e[0] for e in ESTADOS]
    if nuevo_estado in estados_validos:
        estado_anterior = aviso.estado
        aviso.estado = nuevo_estado
        db.session.commit()
        notificar_cambio_estado(aviso, estado_anterior)
        return jsonify({'ok': True, 'estado': aviso.estado,
                        'estado_label': aviso.estado_label(),
                        'estado_class': aviso.estado_badge_class()})

    return jsonify({'ok': False, 'error': 'Estado no válido'}), 400


# ── Duplicar aviso ─────────────────────────────────────────────────────────

@avisos_bp.route('/<int:id>/duplicar', methods=['POST'])
@login_required
def duplicar(id):
    original = Aviso.query.get_or_404(id)
    nuevo = Aviso(
        nombre_cliente=original.nombre_cliente,
        telefono=original.telefono,
        calle=original.calle,
        localidad=original.localidad,
        electrodomestico=original.electrodomestico,
        marca=original.marca,
        descripcion=original.descripcion,
        estado='segunda_visita',
        fecha_aviso=date.today(),
        fecha_cita=None,
        notas=f'Segunda visita. Aviso original: #{original.id}',
        created_by=current_user.id,
    )
    db.session.add(nuevo)
    db.session.commit()
    flash(f'Aviso duplicado como segunda visita (#{nuevo.id}).', 'success')
    return redirect(url_for('avisos.edit', id=nuevo.id))


# ── Eliminar aviso ─────────────────────────────────────────────────────────

@avisos_bp.route('/<int:id>/eliminar', methods=['POST'])
@login_required
def eliminar(id):
    aviso = Aviso.query.get_or_404(id)
    # Eliminar fotos del disco
    for photo in aviso.photos:
        delete_photo_file(photo.filename)
    db.session.delete(aviso)
    db.session.commit()
    flash(f'Aviso #{id} eliminado.', 'warning')
    return redirect(url_for('avisos.list_all'))


# ── Eliminar foto individual ───────────────────────────────────────────────

@avisos_bp.route('/<int:aviso_id>/fotos/<int:photo_id>/eliminar', methods=['POST'])
@login_required
def delete_photo(aviso_id, photo_id):
    photo = Photo.query.get_or_404(photo_id)
    if photo.aviso_id != aviso_id:
        flash('Foto no encontrada en este aviso.', 'danger')
        return redirect(url_for('avisos.detail', id=aviso_id))
    delete_photo_file(photo.filename)
    db.session.delete(photo)
    db.session.commit()
    flash('Foto eliminada.', 'info')
    return redirect(url_for('avisos.edit', id=aviso_id))


# ── Historial cliente ──────────────────────────────────────────────────────

@avisos_bp.route('/cliente/<telefono>')
@login_required
def customer_history(telefono):
    avisos = Aviso.query.filter_by(
        telefono=telefono
    ).order_by(Aviso.fecha_aviso.desc()).all()

    nombre = avisos[0].nombre_cliente if avisos else telefono

    return render_template('avisos/customer_history.html',
                           avisos=avisos,
                           telefono=telefono,
                           nombre=nombre)
