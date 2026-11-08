import os
import uuid
from collections import defaultdict
from datetime import date

from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, current_app, send_from_directory,
                   jsonify)
from flask_login import login_required, current_user
from PIL import Image
from sqlalchemy.orm import joinedload, selectinload

from avisos_servicio import (ESTADOS_VALIDOS, ORDENES, aplicar_cita, filtrar_avisos,
                             foto_aviso, leer_filtros, notificar_cambio_cita, parse_duracion,
                             parse_fecha, parse_hora, registrar_cambios, tecnicos_asignables,
                             texto_cita)
from extensions import db
from models import (Aviso, Photo, ESTADOS, ELECTRODOMESTICOS, COBRO_ESTADOS, TIPOS_SERVICIO,
                    ORIGENES, DURACIONES, DURACION_DEFECTO, User)
from telegram_bot import notificar_aviso_nuevo, notificar_cambio_estado, notificar_resumen_lote

avisos_bp = Blueprint('avisos', __name__, url_prefix='/avisos')

MAX_AVISOS_LOTE = 200


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

def _get_admins():
    """Devuelve la lista de admins (para super_admin al asignar admin a un aviso)."""
    return User.query.filter(
        User.is_active == True,
        User.rol.in_(['admin', 'super_admin'])
    ).order_by(User.nombre_completo).all()


def _render_form(aviso, **extra):
    return render_template('avisos/form.html',
                           aviso=aviso,
                           estados=ESTADOS,
                           cobro_estados=COBRO_ESTADOS,
                           electrodomesticos=ELECTRODOMESTICOS,
                           tipos_servicio=TIPOS_SERVICIO,
                           origenes=ORIGENES,
                           duraciones=DURACIONES,
                           duracion_defecto=DURACION_DEFECTO,
                           tecnicos=tecnicos_asignables(current_user),
                           admins=_get_admins(),
                           **extra)


def _leer_fechas_form():
    """Valida las fechas del formulario. Lanza ValueError con un mensaje legible."""
    return (parse_fecha(request.form.get('fecha_aviso', '')),
            parse_fecha(request.form.get('fecha_cita', '')),
            parse_hora(request.form.get('hora_cita', '')),
            parse_duracion(request.form.get('duracion_min', '')))


def _float_or_none(val):
    try:
        return float(val) if val.strip() else None
    except (ValueError, AttributeError):
        return None


def _guardar_fotos(aviso):
    for f in request.files.getlist('photos'):
        if f and f.filename and allowed_file(f.filename):
            db.session.add(Photo(
                aviso_id=aviso.id,
                filename=save_photo(f),
                original_name=f.filename,
                uploaded_by=current_user.id,
            ))


@avisos_bp.route('/')
@login_required
def list_all():
    filtros = leer_filtros(request.args)
    if not current_user.es_admin:
        filtros.pop('tecnico', None)
        filtros.pop('cobro', None)
    page = request.args.get('page', 1, type=int)

    query = filtrar_avisos(Aviso.visibles_para(current_user), filtros).options(
        joinedload(Aviso.tecnico),
        joinedload(Aviso.admin_asignado),
        selectinload(Aviso.photos),
    )
    avisos = query.paginate(
        page=page, per_page=current_app.config['ITEMS_PER_PAGE'], error_out=False
    )

    return render_template('avisos/list.html',
                           avisos=avisos,
                           filtros=filtros,
                           q=filtros.get('q', ''),
                           estados=ESTADOS,
                           tipos_servicio=TIPOS_SERVICIO,
                           cobro_estados=COBRO_ESTADOS,
                           ordenes=ORDENES,
                           tecnicos=tecnicos_asignables(current_user),
                           seleccionable=current_user.es_admin_o_superior)


# ── API búsqueda JSON ──────────────────────────────────────────────────────

@avisos_bp.route('/api/search')
@login_required
def api_search():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])

    like = f'%{q}%'
    resultados = Aviso.visibles_para(current_user).filter(
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
    if not aviso.puede_ver(current_user):
        flash('No tienes permiso para ver este aviso.', 'danger')
        return redirect(url_for('avisos.list_all'))

    puede_ver_economico = current_user.puede_ver_economico(aviso)
    historial = [h for h in aviso.historial if h.campo != 'cobro' or puede_ver_economico]
    return render_template('avisos/detail.html',
                           aviso=aviso,
                           estados=ESTADOS,
                           historial=historial,
                           puede_ver_economico=puede_ver_economico,
                           puede_editar=aviso.puede_editar(current_user))


# ── Crear ──────────────────────────────────────────────────────────────────

@avisos_bp.route('/nuevo', methods=['GET', 'POST'])
@login_required
def create():
    # Técnicos y repartidores no pueden crear avisos
    if current_user.es_trabajador:
        flash('No tienes permiso para crear avisos. Contacta con tu administrador.', 'warning')
        return redirect(url_for('dashboard.index'))

    if request.method == 'POST':
        try:
            fecha_aviso, fecha_cita, hora_cita, duracion = _leer_fechas_form()
        except ValueError as exc:
            flash(str(exc), 'danger')
            return _render_form(None)

        estado = request.form.get('estado', 'pendiente')
        if estado not in ESTADOS_VALIDOS:
            estado = 'pendiente'

        # Determinar admin_asignado_id
        if current_user.es_super_admin:
            admin_raw = request.form.get('admin_asignado_id', '')
            admin_asignado_id = int(admin_raw) if admin_raw.isdigit() else None
        else:
            admin_asignado_id = current_user.id

        aviso = Aviso(
            nombre_cliente=request.form.get('nombre_cliente', '').strip(),
            telefono=request.form.get('telefono', '').strip(),
            calle=request.form.get('calle', '').strip(),
            localidad=request.form.get('localidad', '').strip(),
            electrodomestico=request.form.get('electrodomestico', '').strip(),
            marca=request.form.get('marca', '').strip(),
            descripcion=request.form.get('descripcion', '').strip(),
            notas=request.form.get('notas', '').strip(),
            estado=estado,
            tipo_servicio=request.form.get('tipo_servicio', 'reparacion'),
            origen=request.form.get('origen', 'particular'),
            created_by=current_user.id,
            admin_asignado_id=admin_asignado_id,
            precio_mano_obra=_float_or_none(request.form.get('precio_mano_obra', '')),
            coste_materiales=_float_or_none(request.form.get('coste_materiales', '')),
            materiales_desc=request.form.get('materiales_desc', '').strip() or None,
            descuento=_float_or_none(request.form.get('descuento', '')),
            gastos_extra=_float_or_none(request.form.get('gastos_extra', '')),
            gastos_extra_desc=request.form.get('gastos_extra_desc', '').strip() or None,
            cobro_estado=request.form.get('cobro_estado', 'pendiente'),
            asignado_a=request.form.get('asignado_a', type=int) or None,
        )

        if fecha_aviso:
            aviso.fecha_aviso = fecha_aviso
        aplicar_cita(aviso, fecha_cita, hora_cita, duracion)
        aviso.items_instalacion = request.form.get('items_instalacion_json', '').strip() or None

        if not aviso.nombre_cliente or not aviso.telefono:
            flash('El nombre del cliente y el teléfono son obligatorios.', 'danger')
            return _render_form(None)

        db.session.add(aviso)
        db.session.flush()  # Para obtener el ID antes de guardar fotos
        _guardar_fotos(aviso)
        db.session.commit()
        notificar_aviso_nuevo(aviso)
        flash(f'Aviso #{aviso.id} creado correctamente.', 'success')
        return redirect(url_for('avisos.detail', id=aviso.id))

    return _render_form(None,
                        prefill_fecha_cita=request.args.get('fecha_cita', ''),
                        prefill_hora_cita=request.args.get('hora_cita', ''),
                        prefill_duracion=request.args.get('duracion', type=int),
                        prefill_asignado=request.args.get('asignado_a', type=int))


# ── Editar ─────────────────────────────────────────────────────────────────

@avisos_bp.route('/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def edit(id):
    aviso = Aviso.query.get_or_404(id)

    # Verificar permisos de edición
    if not aviso.puede_editar(current_user):
        flash('No tienes permiso para editar este aviso.', 'danger')
        return redirect(url_for('avisos.detail', id=id))

    if request.method == 'POST':
        try:
            fecha_aviso, fecha_cita, hora_cita, duracion = _leer_fechas_form()
        except ValueError as exc:
            flash(str(exc), 'danger')
            return _render_form(aviso)

        antes = foto_aviso(aviso)

        # Solo admins con permiso pueden cambiar datos principales del cliente/aparato
        if current_user.es_admin_o_superior:
            aviso.nombre_cliente = request.form.get('nombre_cliente', '').strip()
            aviso.telefono = request.form.get('telefono', '').strip()
            aviso.calle = request.form.get('calle', '').strip()
            aviso.localidad = request.form.get('localidad', '').strip()
            aviso.tipo_servicio = request.form.get('tipo_servicio', aviso.tipo_servicio or 'reparacion')
            aviso.origen = request.form.get('origen', aviso.origen or 'particular')
        aviso.electrodomestico = request.form.get('electrodomestico', '').strip()
        aviso.marca = request.form.get('marca', '').strip()
        aviso.descripcion = request.form.get('descripcion', '').strip()
        aviso.notas = request.form.get('notas', '').strip()
        nuevo_estado = request.form.get('estado', aviso.estado)
        if nuevo_estado in ESTADOS_VALIDOS:
            aviso.estado = nuevo_estado

        if current_user.es_admin_o_superior:
            aviso.precio_mano_obra  = _float_or_none(request.form.get('precio_mano_obra', ''))
            aviso.coste_materiales  = _float_or_none(request.form.get('coste_materiales', ''))
            aviso.materiales_desc   = request.form.get('materiales_desc', '').strip() or None
            aviso.descuento         = _float_or_none(request.form.get('descuento', ''))
            aviso.gastos_extra      = _float_or_none(request.form.get('gastos_extra', ''))
            aviso.gastos_extra_desc = request.form.get('gastos_extra_desc', '').strip() or None
            aviso.cobro_estado      = request.form.get('cobro_estado', aviso.cobro_estado)
            asignado_raw = request.form.get('asignado_a', '')
            aviso.asignado_a = int(asignado_raw) if asignado_raw.isdigit() else None

        # Solo super_admin puede reasignar el admin del aviso
        if current_user.es_super_admin:
            admin_raw = request.form.get('admin_asignado_id', '')
            aviso.admin_asignado_id = int(admin_raw) if admin_raw.isdigit() else None

        if fecha_aviso:
            aviso.fecha_aviso = fecha_aviso
        if request.form.get('limpiar_cita'):
            aplicar_cita(aviso, None, None, duracion)
        else:
            # Con la fecha en blanco se conserva la cita que ya tuviera
            aplicar_cita(aviso, fecha_cita or aviso.fecha_cita, hora_cita, duracion)
        items_json = request.form.get('items_instalacion_json', '').strip()
        aviso.items_instalacion = items_json or None

        if current_user.es_admin_o_superior and (not aviso.nombre_cliente or not aviso.telefono):
            flash('El nombre del cliente y el teléfono son obligatorios.', 'danger')
            return _render_form(aviso)

        _guardar_fotos(aviso)
        registrar_cambios(aviso, current_user, antes)
        db.session.commit()
        notificar_cambio_cita(aviso, antes, current_user)
        flash('Aviso actualizado correctamente.', 'success')
        return redirect(url_for('avisos.detail', id=aviso.id))

    return _render_form(aviso)


# ── Cambiar estado (AJAX) ──────────────────────────────────────────────────

@avisos_bp.route('/<int:id>/estado', methods=['POST'])
@login_required
def change_estado(id):
    aviso = Aviso.query.get_or_404(id)
    if not aviso.puede_editar(current_user):
        return jsonify({'ok': False, 'error': 'Sin permiso para editar este aviso.'}), 403

    data = request.get_json(silent=True) or {}
    nuevo_estado = data.get('estado') or request.form.get('estado', '')

    if nuevo_estado in ESTADOS_VALIDOS:
        estado_anterior = aviso.estado
        antes = foto_aviso(aviso)
        aviso.estado = nuevo_estado
        registrar_cambios(aviso, current_user, antes)
        db.session.commit()
        notificar_cambio_estado(aviso, estado_anterior)
        # Notificación WhatsApp al cliente (no bloquea si falla)
        try:
            from publico import url_seguimiento
            from whatsapp_bot import notificar_estado_whatsapp
            notificar_estado_whatsapp(aviso, estado_anterior, url_seguimiento(aviso.id))
        except Exception:
            pass
        return jsonify({'ok': True, 'estado': aviso.estado,
                        'estado_label': aviso.estado_label(),
                        'estado_class': aviso.estado_badge_class()})

    return jsonify({'ok': False, 'error': 'Estado no válido'}), 400


# ── Acciones en bloque ─────────────────────────────────────────────────────

def _preparar_lote(accion, valor):
    """Valida la acción y devuelve una función que la aplica a un aviso."""
    if accion == 'estado':
        if valor not in ESTADOS_VALIDOS:
            raise ValueError('Estado no válido.')
        def aplicar(aviso):
            aviso.estado = valor
        return aplicar

    if accion == 'tecnico':
        tecnico_id = None
        if valor not in (None, ''):
            try:
                tecnico_id = int(valor)
            except (TypeError, ValueError):
                raise ValueError('Técnico no válido.')
            if tecnico_id not in {t.id for t in tecnicos_asignables(current_user)}:
                raise ValueError('No puedes asignar a ese técnico.')
        def aplicar(aviso):
            aviso.asignado_a = tecnico_id
        return aplicar

    if accion == 'fecha':
        fecha = parse_fecha(valor)
        if fecha is None:
            raise ValueError('Indica una fecha.')
        def aplicar(aviso):
            aplicar_cita(aviso, fecha, aviso.hora_cita)
        return aplicar

    raise ValueError('Acción no válida.')


@avisos_bp.route('/lote', methods=['POST'])
@login_required
def lote():
    if not current_user.es_admin_o_superior:
        return jsonify({'ok': False, 'error': 'Sin permiso.'}), 403

    data = request.get_json(silent=True) or {}
    ids = data.get('ids')
    if (not isinstance(ids, list) or not ids
            or not all(isinstance(i, int) for i in ids)):
        return jsonify({'ok': False, 'error': 'Selecciona al menos un aviso.'}), 400
    if len(ids) > MAX_AVISOS_LOTE:
        return jsonify({'ok': False,
                        'error': f'Máximo {MAX_AVISOS_LOTE} avisos a la vez.'}), 400

    try:
        aplicar = _preparar_lote(data.get('accion'), data.get('valor'))
    except ValueError as exc:
        return jsonify({'ok': False, 'error': str(exc)}), 400

    avisos = {a.id: a for a in Aviso.query.filter(Aviso.id.in_(ids)).all()}
    omitidos = []
    actualizados = 0
    resumen = defaultdict(list)  # técnico → líneas del mensaje

    for aviso_id in dict.fromkeys(ids):
        aviso = avisos.get(aviso_id)
        if aviso is None or not aviso.puede_editar(current_user):
            omitidos.append(aviso_id)
            continue

        antes = foto_aviso(aviso)
        aplicar(aviso)
        if not registrar_cambios(aviso, current_user, antes):
            continue
        actualizados += 1

        cliente = aviso.nombre_cliente
        if antes['tecnico_id'] != aviso.asignado_a:
            if aviso.asignado_a:
                resumen[aviso.asignado_a].append(f'📌 #{aviso.id} {cliente}: asignado a ti')
            if antes['tecnico_id']:
                resumen[antes['tecnico_id']].append(f'↩️ #{aviso.id} {cliente}: ya no es tuyo')
        elif aviso.asignado_a:
            if antes['estado'] != aviso.estado_label():
                detalle = f"{antes['estado']} → {aviso.estado_label()}"
            else:
                detalle = f"{antes['cita']} → {texto_cita(aviso.fecha_cita, aviso.hora_cita)}"
            resumen[aviso.asignado_a].append(f'🗓️ #{aviso.id} {cliente}: {detalle}')

    db.session.commit()

    for tecnico_id, lineas in resumen.items():
        if tecnico_id == current_user.id:
            continue
        try:
            notificar_resumen_lote(db.session.get(User, tecnico_id), lineas)
        except Exception:
            current_app.logger.exception('No se pudo enviar el resumen al técnico %s', tecnico_id)

    return jsonify({'ok': True, 'actualizados': actualizados, 'omitidos': omitidos})


# ── Duplicar aviso ─────────────────────────────────────────────────────────

@avisos_bp.route('/<int:id>/duplicar', methods=['POST'])
@login_required
def duplicar(id):
    if not current_user.es_admin_o_superior:
        flash('No tienes permiso para duplicar avisos.', 'danger')
        return redirect(url_for('avisos.list_all'))

    original = Aviso.query.get_or_404(id)
    nuevo = Aviso(
        nombre_cliente=original.nombre_cliente,
        telefono=original.telefono,
        calle=original.calle,
        localidad=original.localidad,
        electrodomestico=original.electrodomestico,
        marca=original.marca,
        descripcion=original.descripcion,
        tipo_servicio=original.tipo_servicio,
        origen=original.origen,
        estado='segunda_visita',
        fecha_aviso=date.today(),
        fecha_cita=None,
        notas=f'Segunda visita. Aviso original: #{original.id}',
        created_by=current_user.id,
        admin_asignado_id=original.admin_asignado_id,
        asignado_a=original.asignado_a,
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
    if not current_user.es_admin or not aviso.puede_editar(current_user):
        flash('No tienes permiso para eliminar este aviso.', 'danger')
        return redirect(url_for('avisos.detail', id=id))
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
    if not photo.aviso.puede_editar(current_user):
        flash('No tienes permiso para eliminar esta foto.', 'danger')
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
    avisos = Aviso.visibles_para(current_user).filter_by(
        telefono=telefono
    ).order_by(Aviso.fecha_aviso.desc()).all()

    nombre = avisos[0].nombre_cliente if avisos else telefono

    return render_template('avisos/customer_history.html',
                           avisos=avisos,
                           telefono=telefono,
                           nombre=nombre)
