"""
Procesador de comandos del bot de Telegram.
Comandos disponibles:
  /hoy          — citas de hoy
  /pendientes   — avisos pendientes
  /material     — esperando material
  /morosos      — clientes morosos
  /buscar TEXTO — busca por nombre, teléfono o calle
  /aviso NUM    — detalle de un aviso por ID
  /stats        — estadísticas del día
  /ayuda        — lista de comandos
"""
from datetime import date
from telegram_bot import enviar_mensaje, enviar_mensaje_a


def _fmt_aviso(av, idx=None):
    """Formatea un aviso para Telegram."""
    prefijo = f'{idx}. ' if idx else ''
    lineas = [f'{prefijo}<b>{av.nombre_cliente}</b>  <code>#{av.id}</code>']
    lineas.append(f'   📞 {av.telefono}')
    if av.calle:
        dir_ = av.calle + (f', {av.localidad}' if av.localidad else '')
        lineas.append(f'   📍 {dir_}')
    if av.electrodomestico:
        lineas.append(f'   🔧 {av.electrodomestico}' + (f' · {av.marca}' if av.marca else ''))
    if av.notas:
        lineas.append(f'   📝 {av.notas[:80]}')
    return '\n'.join(lineas)


def _cmd_hoy(app):
    with app.app_context():
        from models import Aviso
        hoy = date.today()
        avisos = Aviso.query.filter(
            Aviso.fecha_cita == hoy,
            Aviso.estado != 'finalizado'
        ).order_by(Aviso.calle).all()

        hoy_str = hoy.strftime('%d/%m/%Y')
        if not avisos:
            return enviar_mensaje(f'📅 <b>Hoy {hoy_str}</b>\n\n✅ Sin citas para hoy.')

        lineas = [f'📅 <b>Citas de hoy — {hoy_str} ({len(avisos)})</b>', '']
        for i, av in enumerate(avisos, 1):
            lineas.append(_fmt_aviso(av, i))
            lineas.append('')
        return enviar_mensaje('\n'.join(lineas))


def _cmd_pendientes(app):
    with app.app_context():
        from models import Aviso
        avisos = Aviso.query.filter(
            Aviso.estado.in_(['pendiente', 'segunda_visita'])
        ).order_by(Aviso.fecha_aviso.desc()).limit(10).all()

        if not avisos:
            return enviar_mensaje('⏳ <b>Pendientes</b>\n\n✅ No hay avisos pendientes.')

        lineas = [f'⏳ <b>Pendientes ({len(avisos)})</b>', '']
        for av in avisos:
            lineas.append(_fmt_aviso(av))
            lineas.append('')
        return enviar_mensaje('\n'.join(lineas))


def _cmd_material(app):
    with app.app_context():
        from models import Aviso
        avisos = Aviso.query.filter_by(
            estado='esperando_material'
        ).order_by(Aviso.updated_at).all()

        if not avisos:
            return enviar_mensaje('📦 <b>Material</b>\n\n✅ Ningún aviso esperando material.')

        lineas = [f'📦 <b>Esperando material ({len(avisos)})</b>', '']
        for av in avisos:
            dias = (date.today() - av.updated_at.date()).days if av.updated_at else '?'
            lineas.append(_fmt_aviso(av))
            lineas.append(f'   ⏱ {dias} día(s) esperando')
            lineas.append('')
        return enviar_mensaje('\n'.join(lineas))


def _cmd_morosos(app):
    with app.app_context():
        from models import Aviso
        avisos = Aviso.query.filter_by(
            cobro_estado='moroso'
        ).order_by(Aviso.updated_at.desc()).all()

        if not avisos:
            return enviar_mensaje('💰 <b>Morosos</b>\n\n✅ Sin clientes morosos.')

        total = sum(av.total_cliente for av in avisos)
        lineas = [f'⚠️ <b>Morosos ({len(avisos)}) — {total:.2f} € pendientes</b>', '']
        for av in avisos:
            lineas.append(f'<b>{av.nombre_cliente}</b>  <code>#{av.id}</code>')
            lineas.append(f'   📞 {av.telefono}')
            lineas.append(f'   💶 {av.total_cliente:.2f} €')
            if av.electrodomestico:
                lineas.append(f'   🔧 {av.electrodomestico}')
            lineas.append('')
        return enviar_mensaje('\n'.join(lineas))


def _cmd_buscar(app, termino):
    if not termino:
        return enviar_mensaje('🔍 Uso: /buscar nombre o teléfono\nEjemplo: /buscar García')
    with app.app_context():
        from models import Aviso
        from extensions import db
        like = f'%{termino}%'
        avisos = Aviso.query.filter(
            db.or_(
                Aviso.nombre_cliente.ilike(like),
                Aviso.telefono.ilike(like),
                Aviso.calle.ilike(like),
            ),
            Aviso.estado != 'finalizado'
        ).order_by(Aviso.fecha_aviso.desc()).limit(8).all()

        if not avisos:
            return enviar_mensaje(f'🔍 Sin resultados para "<b>{termino}</b>"')

        lineas = [f'🔍 <b>Búsqueda: "{termino}" ({len(avisos)})</b>', '']
        for av in avisos:
            estado = av.estado_label()
            lineas.append(_fmt_aviso(av))
            lineas.append(f'   📌 {estado}')
            lineas.append('')
        return enviar_mensaje('\n'.join(lineas))


def _cmd_aviso(app, num_str):
    if not num_str.isdigit():
        return enviar_mensaje('❌ Uso: /aviso número\nEjemplo: /aviso 42')
    with app.app_context():
        from models import Aviso
        av = Aviso.query.get(int(num_str))
        if not av:
            return enviar_mensaje(f'❌ Aviso #{num_str} no encontrado.')

        lineas = [
            f'📋 <b>Aviso #{av.id}</b>  —  {av.estado_label()}',
            '',
            f'👤 <b>{av.nombre_cliente}</b>',
            f'📞 {av.telefono}',
        ]
        if av.calle:
            lineas.append(f'📍 {av.calle}' + (f', {av.localidad}' if av.localidad else ''))
        if av.electrodomestico:
            lineas.append(f'🔧 {av.electrodomestico}' + (f' · {av.marca}' if av.marca else ''))
        if av.descripcion:
            lineas.append(f'📝 {av.descripcion}')
        if av.notas:
            lineas.append(f'🗒 Notas: {av.notas}')
        if av.fecha_cita:
            lineas.append(f'🗓 Cita: {av.fecha_cita.strftime("%d/%m/%Y")}')
        if av.tiene_datos_economicos:
            lineas.append('')
            if av.precio_mano_obra is not None:
                lineas.append(f'💶 Mano de obra: {av.precio_mano_obra:.2f} €')
            if av.coste_materiales is not None:
                lineas.append(f'🔩 Materiales: {av.coste_materiales:.2f} €')
            lineas.append(f'💰 Beneficio: {av.beneficio:.2f} €')
        return enviar_mensaje('\n'.join(lineas))


def _cmd_stats(app):
    with app.app_context():
        from models import Aviso
        from extensions import db
        hoy = date.today()

        total_activos   = Aviso.query.filter(Aviso.estado != 'finalizado').count()
        citas_hoy       = Aviso.query.filter(Aviso.fecha_cita == hoy, Aviso.estado != 'finalizado').count()
        pendientes      = Aviso.query.filter_by(estado='pendiente').count()
        material        = Aviso.query.filter_by(estado='esperando_material').count()
        segunda         = Aviso.query.filter_by(estado='segunda_visita').count()
        finalizados_hoy = Aviso.query.filter(
            Aviso.estado == 'finalizado',
            Aviso.updated_at >= date.today()
        ).count()

        # Facturación del mes actual
        from sqlalchemy import extract, func
        mes = date.today().month
        anio = date.today().year
        factura = db.session.query(
            func.sum(Aviso.precio_mano_obra + Aviso.coste_materiales)
        ).filter(
            Aviso.estado == 'finalizado',
            extract('month', Aviso.updated_at) == mes,
            extract('year', Aviso.updated_at) == anio,
        ).scalar() or 0.0

        beneficio_mes = db.session.query(
            func.sum(Aviso.precio_mano_obra - db.func.coalesce(Aviso.coste_materiales, 0))
        ).filter(
            Aviso.estado == 'finalizado',
            extract('month', Aviso.updated_at) == mes,
            extract('year', Aviso.updated_at) == anio,
            Aviso.precio_mano_obra.isnot(None)
        ).scalar() or 0.0

        lineas = [
            f'📊 <b>Estadísticas — {hoy.strftime("%d/%m/%Y")}</b>',
            '',
            f'📅 Citas hoy:        <b>{citas_hoy}</b>',
            f'⏳ Pendientes:       <b>{pendientes}</b>',
            f'📦 Esperando mat.:   <b>{material}</b>',
            f'🔁 Segunda visita:   <b>{segunda}</b>',
            f'✅ Finalizados hoy:  <b>{finalizados_hoy}</b>',
            f'📂 Total activos:    <b>{total_activos}</b>',
            '',
            f'💶 Facturado este mes: <b>{factura:.2f} €</b>',
            f'💰 Beneficio este mes: <b>{beneficio_mes:.2f} €</b>',
        ]
        return enviar_mensaje('\n'.join(lineas))


def _cmd_ayuda():
    texto = (
        '🤖 <b>Comandos disponibles</b>\n\n'
        '/hoy — Citas de hoy con dirección\n'
        '/pendientes — Avisos sin asignar\n'
        '/material — Esperando piezas\n'
        '/morosos — Clientes morosos\n'
        '/buscar <i>texto</i> — Busca por nombre/tel/calle\n'
        '/aviso <i>número</i> — Detalle completo de un aviso\n'
        '/stats — Resumen y facturación del mes\n'
        '/ayuda — Esta ayuda\n'
    )
    return enviar_mensaje(texto)


# ── Dispatcher principal ───────────────────────────────────────────────────

def procesar_update(update: dict, app) -> bool:
    """
    Recibe un update de Telegram y ejecuta el comando correspondiente.
    Devuelve True si se procesó algo.
    """
    message = update.get('message') or update.get('edited_message')
    if not message:
        return False

    text = message.get('text', '').strip()
    if not text.startswith('/'):
        return False

    partes  = text.split(maxsplit=1)
    comando = partes[0].split('@')[0].lower()   # /comando@BotNombre → /comando
    args    = partes[1].strip() if len(partes) > 1 else ''

    if comando == '/hoy':
        _cmd_hoy(app)
    elif comando == '/pendientes':
        _cmd_pendientes(app)
    elif comando == '/material':
        _cmd_material(app)
    elif comando == '/morosos':
        _cmd_morosos(app)
    elif comando == '/buscar':
        _cmd_buscar(app, args)
    elif comando == '/aviso':
        _cmd_aviso(app, args)
    elif comando == '/stats':
        _cmd_stats(app)
    elif comando in ('/ayuda', '/help', '/start'):
        _cmd_ayuda()
    else:
        enviar_mensaje(f'❓ Comando desconocido: <code>{comando}</code>\nEscribe /ayuda para ver los disponibles.')

    return True
