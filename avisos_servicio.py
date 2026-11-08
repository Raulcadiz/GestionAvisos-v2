"""Reglas comunes para citas, historial y filtrado de avisos."""
import logging
import re
from datetime import date

from extensions import db
from models import Aviso, AvisoHistorial, COBRO_ESTADOS, DURACION_DEFECTO, ESTADOS, User

logger = logging.getLogger(__name__)

_HORA_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')

DURACION_MIN = 15
DURACION_MAX = 720

ESTADOS_VALIDOS = {key for key, _ in ESTADOS}

SIN_CAMBIO = object()  # distingue «no tocar el técnico» de «dejarlo sin asignar»


# ── Validación ─────────────────────────────────────────────────────────────

def parse_fecha(valor):
    """Devuelve un date, o None si viene vacío. Lanza ValueError si no es válido."""
    if valor in (None, ''):
        return None
    try:
        return date.fromisoformat(str(valor).strip()[:10])
    except ValueError:
        raise ValueError(f'Fecha no válida: {valor}')


def parse_hora(valor):
    """Devuelve "HH:MM", o None si viene vacío. Lanza ValueError si no es válida."""
    if valor in (None, ''):
        return None
    hora = str(valor).strip()[:5]
    if not _HORA_RE.match(hora):
        raise ValueError(f'Hora no válida: {valor}')
    return hora


def parse_duracion(valor):
    """Devuelve los minutos, o el valor por defecto si viene vacío."""
    if valor in (None, ''):
        return DURACION_DEFECTO
    try:
        minutos = int(valor)
    except (TypeError, ValueError):
        raise ValueError(f'Duración no válida: {valor}')
    if not DURACION_MIN <= minutos <= DURACION_MAX:
        raise ValueError(f'La duración debe estar entre {DURACION_MIN} y {DURACION_MAX} minutos.')
    return minutos


# ── Técnicos ───────────────────────────────────────────────────────────────

def tecnicos_asignables(usuario):
    """Técnicos y repartidores que el usuario puede asignar."""
    if usuario.es_super_admin:
        return User.query.filter(
            User.is_active == True,  # noqa: E712
            User.rol.in_(['tecnico', 'repartidor'])
        ).order_by(User.nombre_completo).all()
    if usuario.es_admin:
        return (User.query
                .filter_by(is_active=True, creado_por_id=usuario.id)
                .order_by(User.nombre_completo)
                .all())
    return []


# ── Historial ──────────────────────────────────────────────────────────────

def texto_cita(fecha, hora):
    if not fecha:
        return 'Sin cita'
    return f"{fecha.strftime('%d/%m/%Y')} {hora}" if hora else fecha.strftime('%d/%m/%Y')


def _nombre_tecnico(tecnico_id):
    if not tecnico_id:
        return 'Sin asignar'
    tecnico = db.session.get(User, tecnico_id)
    return tecnico.display_name if tecnico else f'Usuario #{tecnico_id}'


def _texto_duracion(minutos):
    horas, resto = divmod(minutos or DURACION_DEFECTO, 60)
    if not horas:
        return f'{resto} min'
    return f'{horas} h {resto} min' if resto else f'{horas} h'


def _etiqueta(opciones, clave):
    return dict(opciones).get(clave, clave or '—')


def foto_aviso(aviso):
    """Captura los campos seguidos antes de modificar un aviso."""
    return {
        'estado':     _etiqueta(ESTADOS, aviso.estado),
        'cita':       texto_cita(aviso.fecha_cita, aviso.hora_cita),
        'duracion':   _texto_duracion(aviso.duracion_min),
        'tecnico':    _nombre_tecnico(aviso.asignado_a),
        'cobro':      _etiqueta(COBRO_ESTADOS, aviso.cobro_estado),
        'tecnico_id': aviso.asignado_a,
        'con_cita':   aviso.fecha_cita is not None,
    }


def registrar_cambios(aviso, usuario, antes):
    """Añade al historial las diferencias respecto a `antes`. No hace commit."""
    ahora = foto_aviso(aviso)
    cambios = []
    for campo in ('estado', 'cita', 'duracion', 'tecnico', 'cobro'):
        if campo == 'duracion' and not (ahora['con_cita'] and antes['con_cita']):
            continue  # la duración solo tiene sentido si había y hay cita
        if antes[campo] != ahora[campo]:
            db.session.add(AvisoHistorial(
                aviso_id=aviso.id,
                user_id=usuario.id if usuario else None,
                campo=campo,
                valor_anterior=antes[campo],
                valor_nuevo=ahora[campo],
            ))
            cambios.append(campo)
    return cambios


# ── Citas ──────────────────────────────────────────────────────────────────

def aplicar_cita(aviso, fecha, hora, duracion=None, tecnico_id=SIN_CAMBIO):
    """Aplica los datos de cita al aviso. No hace commit."""
    aviso.fecha_cita = fecha
    aviso.hora_cita = hora if fecha else None
    if duracion is not None:
        aviso.duracion_min = duracion
    if tecnico_id is not SIN_CAMBIO:
        aviso.asignado_a = tecnico_id


def notificar_cambio_cita(aviso, antes, usuario):
    """Avisa por Telegram a los técnicos afectados. Un fallo nunca rompe la operación."""
    cita_nueva = texto_cita(aviso.fecha_cita, aviso.hora_cita)
    if antes['cita'] == cita_nueva and antes['tecnico_id'] == aviso.asignado_a:
        return
    try:
        from telegram_bot import notificar_cita_tecnico
        anterior = db.session.get(User, antes['tecnico_id']) if antes['tecnico_id'] else None
        nuevo = db.session.get(User, aviso.asignado_a) if aviso.asignado_a else None
        notificar_cita_tecnico(aviso, antes['cita'], cita_nueva, nuevo, anterior,
                               usuario.id if usuario else None)
    except Exception:
        logger.exception('No se pudo notificar el cambio de cita del aviso %s', aviso.id)


def reprogramar(aviso, usuario, fecha, hora, duracion=None, tecnico_id=SIN_CAMBIO):
    """Cambia la cita, registra el historial, guarda y notifica al técnico."""
    antes = foto_aviso(aviso)
    aplicar_cita(aviso, fecha, hora, duracion, tecnico_id)
    registrar_cambios(aviso, usuario, antes)
    db.session.commit()
    notificar_cambio_cita(aviso, antes, usuario)


# ── Solapes ────────────────────────────────────────────────────────────────

def minutos_de(hora):
    """Convierte "HH:MM" en minutos desde medianoche; None si no es válida."""
    if not hora or not _HORA_RE.match(hora):
        return None
    return int(hora[:2]) * 60 + int(hora[3:])


def _intervalo(aviso):
    inicio = minutos_de(aviso.hora_cita)
    if inicio is None:
        return None
    return inicio, inicio + aviso.duracion_efectiva


def solapes(aviso):
    """Otras citas sin finalizar del mismo técnico y día que se cruzan con esta."""
    propio = _intervalo(aviso)
    if not (propio and aviso.fecha_cita and aviso.asignado_a) or aviso.estado == 'finalizado':
        return []
    candidatos = Aviso.query.filter(
        Aviso.id != aviso.id,
        Aviso.asignado_a == aviso.asignado_a,
        Aviso.fecha_cita == aviso.fecha_cita,
        Aviso.hora_cita != None,  # noqa: E711
        Aviso.estado != 'finalizado',
    ).order_by(Aviso.hora_cita).all()
    resultado = []
    for otro in candidatos:
        intervalo = _intervalo(otro)
        if intervalo and propio[0] < intervalo[1] and intervalo[0] < propio[1]:
            resultado.append(otro)
    return resultado


def ids_con_solape(avisos):
    """IDs de los avisos de la lista que se cruzan con otro del mismo técnico y día."""
    grupos = {}
    for aviso in avisos:
        intervalo = _intervalo(aviso)
        if intervalo and aviso.asignado_a and aviso.estado != 'finalizado':
            grupos.setdefault((aviso.asignado_a, aviso.fecha_cita), []).append((intervalo, aviso.id))

    marcados = set()
    for citas in grupos.values():
        citas.sort()
        fin_max, id_max = None, None
        for (inicio, fin), aviso_id in citas:
            if fin_max is not None and inicio < fin_max:
                marcados.update((aviso_id, id_max))
            if fin_max is None or fin > fin_max:
                fin_max, id_max = fin, aviso_id
    return marcados


# ── Filtros de la lista y del Excel ────────────────────────────────────────

ORDENES = [
    ('aviso_desc',  'Aviso: más recientes'),
    ('aviso_asc',   'Aviso: más antiguos'),
    ('cita_asc',    'Cita: más próximas'),
    ('cita_desc',   'Cita: más lejanas'),
    ('cliente',     'Cliente (A-Z)'),
    ('actualizado', 'Última actualización'),
]

_CAMPOS_FILTRO = ('q', 'estado', 'tipo', 'tecnico', 'cobro', 'desde', 'hasta',
                  'sin_cita', 'atrasados', 'orden')


def leer_filtros(args):
    """Devuelve solo los filtros con valor, para reutilizarlos en enlaces."""
    filtros = {}
    for campo in _CAMPOS_FILTRO:
        valor = (args.get(campo) or '').strip()
        if valor:
            filtros[campo] = valor
    return filtros


def _fecha_o_none(valor):
    try:
        return parse_fecha(valor)
    except ValueError:
        return None


def filtrar_avisos(query, filtros):
    """Aplica a la query los filtros devueltos por `leer_filtros` y su orden."""
    if filtros.get('q'):
        like = f"%{filtros['q']}%"
        query = query.filter(db.or_(
            Aviso.nombre_cliente.ilike(like),
            Aviso.telefono.ilike(like),
            Aviso.calle.ilike(like),
            Aviso.localidad.ilike(like),
            Aviso.electrodomestico.ilike(like),
            Aviso.marca.ilike(like),
        ))
    if filtros.get('estado'):
        query = query.filter(Aviso.estado == filtros['estado'])
    if filtros.get('tipo'):
        query = query.filter(Aviso.tipo_servicio == filtros['tipo'])
    if filtros.get('cobro'):
        query = query.filter(Aviso.cobro_estado == filtros['cobro'])

    tecnico = filtros.get('tecnico', '')
    if tecnico == 'sin':
        query = query.filter(Aviso.asignado_a == None)  # noqa: E711
    elif tecnico.isdigit():
        query = query.filter(Aviso.asignado_a == int(tecnico))

    desde = _fecha_o_none(filtros.get('desde'))
    hasta = _fecha_o_none(filtros.get('hasta'))
    if desde:
        query = query.filter(Aviso.fecha_cita >= desde)
    if hasta:
        query = query.filter(Aviso.fecha_cita <= hasta)
    if filtros.get('sin_cita'):
        query = query.filter(Aviso.fecha_cita == None)  # noqa: E711
    if filtros.get('atrasados'):
        query = query.filter(Aviso.fecha_cita < date.today(),
                             Aviso.estado != 'finalizado')

    sin_fecha_al_final = Aviso.fecha_cita.is_(None)
    orden = {
        'aviso_asc':   (Aviso.fecha_aviso.asc(), Aviso.id.asc()),
        'cita_asc':    (sin_fecha_al_final, Aviso.fecha_cita.asc(), Aviso.hora_cita.asc()),
        'cita_desc':   (sin_fecha_al_final, Aviso.fecha_cita.desc(), Aviso.hora_cita.desc()),
        'cliente':     (Aviso.nombre_cliente.asc(),),
        'actualizado': (Aviso.updated_at.desc(),),
    }.get(filtros.get('orden'), (Aviso.fecha_aviso.desc(), Aviso.id.desc()))
    return query.order_by(*orden)
