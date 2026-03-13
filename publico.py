from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import Aviso, Portfolio, ELECTRODOMESTICOS
from telegram_bot import notificar_aviso_nuevo

publico_bp = Blueprint('publico', __name__, url_prefix='')


# ── Landing page ─────────────────────────────────────────────────────────────

@publico_bp.route('/')
def index():
    portfolio = (Portfolio.query
                 .filter_by(activo=True)
                 .order_by(Portfolio.orden.asc(), Portfolio.fecha.desc())
                 .limit(6).all())
    return render_template('publico/index.html', portfolio=portfolio)


# ── Solicitar servicio (antes /aviso/nuevo) ───────────────────────────────────

@publico_bp.route('/solicitar', methods=['GET', 'POST'])
def aviso_publico():
    """Formulario público para que el cliente deje un aviso sin login."""
    enviado = False

    if request.method == 'POST':
        nombre = request.form.get('nombre_cliente', '').strip()
        telefono = request.form.get('telefono', '').strip()
        electrodomestico = request.form.get('electrodomestico', '').strip()
        marca = request.form.get('marca', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        calle = request.form.get('calle', '').strip()
        localidad = request.form.get('localidad', '').strip()
        tipo_servicio = request.form.get('tipo_servicio', 'reparacion')

        if not nombre or not telefono:
            flash('El nombre y el teléfono son obligatorios.', 'danger')
            return render_template('publico/aviso_publico.html',
                                   electrodomesticos=ELECTRODOMESTICOS,
                                   form_data=request.form)

        aviso = Aviso(
            nombre_cliente=nombre,
            telefono=telefono,
            electrodomestico=electrodomestico,
            marca=marca,
            descripcion=descripcion,
            calle=calle,
            localidad=localidad,
            estado='pendiente',
            fecha_aviso=date.today(),
            tipo_servicio=tipo_servicio,
            origen='particular',
        )
        db.session.add(aviso)
        db.session.commit()

        notificar_aviso_nuevo(aviso)
        enviado = True

    return render_template('publico/aviso_publico.html',
                           electrodomesticos=ELECTRODOMESTICOS,
                           enviado=enviado,
                           form_data={})


# ── Buscador / comparador de aparatos ────────────────────────────────────────

# Catálogo básico: tipo → { info, problemas, links Electrofactory, consejos }
CATALOGO_APARATOS = {
    'Lavadora': {
        'icono': '🧺',
        'vida_util': '10-15 años',
        'reparar_si': 'El aparato tiene menos de 8 años y el coste de reparación es < 50% del precio de uno nuevo.',
        'cambiar_si': 'Tiene más de 10 años, consume mucha agua/luz o la avería supera el 60% del valor.',
        'problemas': [
            ('No centrifuga', 'Fallo en el motor, escobillas desgastadas o desequilibrio de carga.'),
            ('Pierde agua', 'Junta de puerta dañada, manguera suelta o bomba de desagüe obstruida.'),
            ('No calienta', 'Resistencia quemada o termostato defectuoso.'),
            ('Hace mucho ruido', 'Rodamiento del tambor deteriorado — reparación urgente.'),
            ('No desagüa', 'Filtro obstruido (límpialo primero) o bomba averiada.'),
        ],
        'busqueda_electrofactory': 'lavadora',
        'marcas_recomendadas': ['Bosch', 'Balay', 'Samsung', 'LG', 'Siemens'],
        'consumo_tip': 'Programa eco + carga completa = hasta 40% menos consumo',
    },
    'Frigorífico': {
        'icono': '❄️',
        'vida_util': '15-20 años',
        'reparar_si': 'Avería en motor/compresor con menos de 10 años de uso.',
        'cambiar_si': 'Compresor roto en un aparato de más de 12 años o clase energética A o inferior.',
        'problemas': [
            ('No enfría', 'Gas refrigerante agotado, compresor averiado o termostato defectuoso.'),
            ('Hace hielo en el congelador', 'Fallo en el sistema No Frost — resistencia de deshielo.'),
            ('Hace mucho ruido', 'Compresor al límite o ventilador rozando.'),
            ('Pierde agua interior', 'Desagüe interior obstruido — solución sencilla y económica.'),
            ('Junta de puerta deteriorada', 'Entra calor y el motor trabaja el doble.'),
        ],
        'busqueda_electrofactory': 'frigorifico',
        'marcas_recomendadas': ['Bosch', 'Samsung', 'LG', 'Haier', 'Balay'],
        'consumo_tip': 'Un frigorífico clase D consume hasta 3x más que uno clase A+++',
    },
    'Lavavajillas': {
        'icono': '🍽️',
        'vida_util': '10-15 años',
        'reparar_si': 'Avería en bomba o brazos aspersores con aparato de menos de 8 años.',
        'cambiar_si': 'Resistencia principal quemada en aparato de más de 10 años.',
        'problemas': [
            ('No lava bien', 'Brazos aspersores obstruidos, dosificador de pastilla roto o filtro sucio.'),
            ('No desagüa', 'Bomba de desagüe bloqueada o filtro obstruido.'),
            ('Deja manchas blancas', 'Falta sal o el dosificador de abrillantador está vacío.'),
            ('No calienta el agua', 'Resistencia calefactora averiada.'),
            ('Pierde agua', 'Junta de puerta o manguera de entrada deteriorada.'),
        ],
        'busqueda_electrofactory': 'lavavajillas',
        'marcas_recomendadas': ['Bosch', 'Siemens', 'Balay', 'AEG', 'Whirlpool'],
        'consumo_tip': 'Programa eco a 50°C limpia igual que intensivo y consume un 40% menos',
    },
    'Horno': {
        'icono': '🔥',
        'vida_util': '15-20 años',
        'reparar_si': 'Resistencia quemada o termostato roto — reparaciones económicas.',
        'cambiar_si': 'Fallo en la electrónica principal o cristal interior roto en aparato antiguo.',
        'problemas': [
            ('No calienta', 'Resistencia calefactora quemada — pieza económica.'),
            ('Temperatura incorrecta', 'Termostato o sonda de temperatura defectuosa.'),
            ('No enciende', 'Fallo en el panel electrónico o en el encendido piezoeléctrico.'),
            ('Puerta no cierra bien', 'Bisagras desgastadas o junta deteriorada.'),
            ('Ventilador no funciona', 'Motor del ventilador de convección averiado.'),
        ],
        'busqueda_electrofactory': 'horno',
        'marcas_recomendadas': ['Bosch', 'Balay', 'Siemens', 'Samsung', 'AEG'],
        'consumo_tip': 'No precalientes más de 10 min y aprovecha el calor residual al final',
    },
    'Vitrocerámica': {
        'icono': '⚡',
        'vida_util': '15-20 años',
        'reparar_si': 'Zona de cocción no calienta — fallo en el elemento calefactor.',
        'cambiar_si': 'Superficie muy rayada o agrietada, o fallo en la electrónica principal.',
        'problemas': [
            ('Una zona no calienta', 'Elemento calefactor de esa zona fundido.'),
            ('No enciende ninguna zona', 'Fallo en la placa electrónica de control.'),
            ('Pantalla con error', 'Sobrecalentamiento o fallo de sensor — resetea desconectando la luz.'),
            ('Hace chispas (inducción)', 'Batería de condensadores deteriorada.'),
            ('Superficie rayada', 'Uso de limpiadores abrasivos — solo preventivo con crema específica.'),
        ],
        'busqueda_electrofactory': 'vitroceramica',
        'marcas_recomendadas': ['Bosch', 'Balay', 'Samsung', 'Siemens', 'Teka'],
        'consumo_tip': 'La inducción es un 50% más eficiente que la vitrocerámica convencional',
    },
    'Microondas': {
        'icono': '📡',
        'vida_util': '8-12 años',
        'reparar_si': 'Plato giratorio roto o puerta sin cierre — reparaciones baratas.',
        'cambiar_si': 'Magnetrón averiado — el coste supera casi siempre el valor del aparato.',
        'problemas': [
            ('No calienta', 'Magnetrón averiado — valorar cambio de aparato.'),
            ('Hace chispas dentro', 'Cubierta interior dañada o restos de comida quemados.'),
            ('Plato no gira', 'Motor del plato averiado — pieza económica.'),
            ('Puerta no cierra', 'Pestillos rotos — importante reparar por seguridad.'),
            ('Hace ruido raro', 'Ventilador obstruido o rodillo del plato desgastado.'),
        ],
        'busqueda_electrofactory': 'microondas',
        'marcas_recomendadas': ['Samsung', 'LG', 'Bosch', 'Teka', 'Candy'],
        'consumo_tip': 'Calienta en recipientes de cristal o cerámica, nunca metálicos',
    },
    'Campana extractora': {
        'icono': '💨',
        'vida_util': '15-20 años',
        'reparar_si': 'Motor del ventilador o iluminación — reparaciones sencillas.',
        'cambiar_si': 'Motor quemado en aparato antiguo sin filtros de carbono disponibles.',
        'problemas': [
            ('No aspira bien', 'Filtro de grasa saturado (límpialo en lavavajillas) o filtro de carbono agotado.'),
            ('Hace mucho ruido', 'Filtro obstruido o motor con juego.'),
            ('Luz no funciona', 'Bombilla fundida — cambio sencillo.'),
            ('No enciende', 'Fallo en el interruptor o en la placa electrónica.'),
            ('Gotea grasa', 'Filtro metálico lleno — límpialo cada 2 meses.'),
        ],
        'busqueda_electrofactory': 'campana-extractora',
        'marcas_recomendadas': ['Bosch', 'Balay', 'Teka', 'Siemens', 'AEG'],
        'consumo_tip': 'Limpia el filtro de grasa cada 2 meses — prolonga la vida del motor',
    },
    'Secadora': {
        'icono': '🌀',
        'vida_util': '10-15 años',
        'reparar_si': 'Resistencia o termostato averiado en aparato menor de 8 años.',
        'cambiar_si': 'Motor averiado en aparato de más de 10 años.',
        'problemas': [
            ('No calienta', 'Resistencia o termostato de seguridad fundido.'),
            ('Ropa no seca del todo', 'Filtro de pelusa obstruido o condensador sucio.'),
            ('Tarda mucho', 'Ventilación exterior bloqueada o filtro saturado.'),
            ('Hace ruido', 'Rodamiento desgastado o cuerpo extraño en el tambor.'),
            ('Error en pantalla', 'Sensor de humedad sucio — límpialo con alcohol.'),
        ],
        'busqueda_electrofactory': 'secadora',
        'marcas_recomendadas': ['Bosch', 'Siemens', 'Samsung', 'LG', 'Balay'],
        'consumo_tip': 'Limpia el filtro SIEMPRE tras cada uso — es lo más importante',
    },
    'Aire acondicionado': {
        'icono': '❄️🌡️',
        'vida_util': '12-15 años',
        'reparar_si': 'Fallo en control remoto, filtros o drenaje — reparaciones baratas.',
        'cambiar_si': 'Compresor averiado en aparato de más de 10 años.',
        'problemas': [
            ('No enfría bien', 'Filtros sucios, gas bajo o unidad exterior sucia.'),
            ('Gotea agua al interior', 'Desagüe obstruido — solución sencilla.'),
            ('Hace ruido', 'Filtros sucios o ventilador con suciedad.'),
            ('No enciende', 'Fallo en el control remoto, fusible o placa.'),
            ('Olor desagradable', 'Filtros con bacterias — limpia y desinfecta.'),
        ],
        'busqueda_electrofactory': 'aire-acondicionado',
        'marcas_recomendadas': ['Daikin', 'Mitsubishi', 'Samsung', 'LG', 'Fujitsu'],
        'consumo_tip': 'Cada grado por encima de 24°C en verano = 7% menos consumo',
    },
    'Caldera': {
        'icono': '🔥💧',
        'vida_util': '15-20 años',
        'reparar_si': 'Fallo en electroválvula, bomba o sonda — piezas económicas.',
        'cambiar_si': 'Intercambiador de calor roto o quemador averiado en aparato antiguo.',
        'problemas': [
            ('No enciende', 'Sin gas, presión baja o encendido defectuoso.'),
            ('Presión baja', 'Pérdida de agua en el circuito — comprueba los radiadores.'),
            ('Hace ruido (golpes)', 'Aire en el circuito — purgar radiadores.'),
            ('Agua caliente intermitente', 'Sonda NTC o placa electrónica.'),
            ('Error en pantalla', 'Consulta el código en el manual — suele indicar la avería.'),
        ],
        'busqueda_electrofactory': 'caldera',
        'marcas_recomendadas': ['Vaillant', 'Junkers', 'Baxi', 'Roca', 'Ferroli'],
        'consumo_tip': 'Baja la temperatura de calefacción a 20°C en casa y 15°C de noche',
    },
}


@publico_bp.route('/buscar')
def buscar():
    """Identificador de aparato: el usuario elige o sube foto y ve info + productos."""
    aparato = request.args.get('aparato', '').strip()
    info = CATALOGO_APARATOS.get(aparato) if aparato else None
    aparatos_lista = list(CATALOGO_APARATOS.items())
    return render_template('publico/buscar.html',
                           aparatos=aparatos_lista,
                           aparato_sel=aparato,
                           info=info)


# ── Ofertas Electrofactory ────────────────────────────────────────────────────

CATEGORIAS_OFERTAS = [
    ('lavadoras',      '🧺', 'Lavadoras'),
    ('frigorificos',   '❄️', 'Frigoríficos'),
    ('hornos',         '🔥', 'Hornos'),
    ('lavavajillas',   '🍽️', 'Lavavajillas'),
    ('vitroceramicas', '⚡', 'Vitrocerámicas'),
]


@publico_bp.route('/ofertas')
def ofertas():
    from ofertas_scraper import obtener_ofertas, ELECTROFACTORY_BASE
    categoria = request.args.get('cat', 'lavadoras')
    if categoria not in dict((c[0], c) for c in CATEGORIAS_OFERTAS):
        categoria = 'lavadoras'
    productos = obtener_ofertas(categoria)
    return render_template('publico/ofertas.html',
                           categorias=CATEGORIAS_OFERTAS,
                           categoria_sel=categoria,
                           productos=productos,
                           base_url=ELECTROFACTORY_BASE)


# Redirect de la URL antigua por si alguien la tiene guardada
@publico_bp.route('/aviso/nuevo')
def aviso_publico_legacy():
    return redirect(url_for('publico.aviso_publico'), 301)


# ── Portfolio ─────────────────────────────────────────────────────────────────

@publico_bp.route('/portfolio')
def portfolio():
    items = (Portfolio.query
             .filter_by(activo=True)
             .order_by(Portfolio.orden.asc(), Portfolio.fecha.desc())
             .all())
    return render_template('publico/portfolio.html', items=items)


# ── Consejos de mantenimiento ────────────────────────────────────────────────

CONSEJOS = [
    {
        'icono': '🧺',
        'aparato': 'Lavadora',
        'titulo': 'Limpia el filtro cada 3 meses',
        'texto': (
            'El filtro de la lavadora acumula pelusa, monedas y restos que reducen su eficiencia. '
            'Localízalo en la parte frontal inferior, vacíalo y enjuágalo con agua. '
            'También limpia el cajón del detergente para evitar moho.'
        ),
        'consejo_extra': 'Usa siempre la cantidad correcta de detergente: el exceso crea cal y espuma.',
    },
    {
        'icono': '❄️',
        'aparato': 'Frigorífico',
        'titulo': 'Revisa las juntas de la puerta',
        'texto': (
            'Las juntas de goma desgastadas hacen que el frío escape y el motor trabaje más, '
            'aumentando el consumo eléctrico. Pasa un papel por el contorno: si sale fácilmente, '
            'es hora de cambiar la junta.'
        ),
        'consejo_extra': 'Mantén el frigorífico al 70-80% de capacidad para una circulación óptima del aire.',
    },
    {
        'icono': '🍽️',
        'aparato': 'Lavavajillas',
        'titulo': 'Limpia el brazo aspersor mensualmente',
        'texto': (
            'Los orificios del brazo aspersor se obstruyen con cal y restos de comida. '
            'Desmóntalo (suele enroscar hacia la izquierda), pasa un palillo por los agujeros '
            'y enjuágalo bajo el grifo.'
        ),
        'consejo_extra': 'Pon un vaso con vinagre blanco en el cesto superior y haz un ciclo vacío para eliminar la cal.',
    },
    {
        'icono': '🔥',
        'aparato': 'Horno',
        'titulo': 'Aprovecha la autolimpieza correctamente',
        'texto': (
            'Si tu horno tiene función pirolítica, úsala con la cocina ventilada: alcanza 500°C '
            'y puede generar humo. Retira siempre las bandejas antes. Para hornos sin pirolítica, '
            'limpia con agua caliente y bicarbonato, evita productos abrasivos en el interior.'
        ),
        'consejo_extra': 'Revisa la junta de la puerta del horno: si pierde calor, tu factura de luz sube.',
    },
    {
        'icono': '⚡',
        'aparato': 'Vitrocerámica',
        'titulo': 'Limpia los derrames en caliente (con cuidado)',
        'texto': (
            'Los derrames de azúcar y plástico quemado dañan permanentemente la vitro si no se '
            'retiran rápido. Usa una rasqueta específica de vitrocerámica con cuidado mientras '
            'está aún templada. Nunca uses estropajos de esparto.'
        ),
        'consejo_extra': 'Usa siempre bases planas en los cacharros: las bases onduladas rayan la superficie.',
    },
    {
        'icono': '🌀',
        'aparato': 'Secadora',
        'titulo': 'Limpia el filtro de pelusa tras cada uso',
        'texto': (
            'Un filtro obstruido obliga al motor a esforzarse más y puede provocar sobrecalentamiento. '
            'Es el mantenimiento más sencillo y más olvidado. Cada 6 meses, limpia también '
            'el condensador si tu secadora es de condensación.'
        ),
        'consejo_extra': 'No sobrecargues: la ropa necesita espacio para que el aire caliente circule.',
    },
]


@publico_bp.route('/consejos')
def consejos():
    return render_template('publico/consejos.html', consejos=CONSEJOS)
