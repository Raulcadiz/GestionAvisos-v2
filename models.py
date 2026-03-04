from datetime import datetime, date
from flask_login import UserMixin
from sqlalchemy import event
from extensions import db


TIPOS_SERVICIO = [
    ('reparacion',  'Reparación',  '🔧'),
    ('instalacion', 'Instalación', '⚡'),
    ('reparto',     'Reparto',     '📦'),
]

ORIGENES = [
    ('particular',     'Particular',      '👤'),
    ('electrofactory', 'ElectroFactory',  '🏪'),
    ('milar',          'Milar',           '🏬'),
    ('inmobiliaria',   'Inmobiliaria',    '🏠'),
    ('otro',           'Otro',            '📋'),
]

ESTADOS = [
    ('pendiente',          'Pendiente'),
    ('hoy',                'Hoy'),
    ('esperando_material', 'Esperando material'),
    ('segunda_visita',     'Segunda visita'),
    ('finalizado',         'Finalizado'),
]

COBRO_ESTADOS = [
    ('pendiente', 'Pendiente de cobro'),
    ('pagado',    'Pagado'),
    ('moroso',    'Moroso'),
]

ELECTRODOMESTICOS = [
    'Lavadora', 'Secadora', 'Lavavajillas', 'Frigorífico', 'Congelador',
    'Horno', 'Microondas', 'Vitrocerámica', 'Cocina gas', 'Campana extractora',
    'Aire acondicionado', 'Caldera', 'Calentador', 'Termo eléctrico',
    'Televisión', 'Lava-secadora', 'Otro',
]


class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id               = db.Column(db.Integer, primary_key=True)
    username         = db.Column(db.String(80), unique=True, nullable=False)
    password         = db.Column(db.String(256), nullable=False)
    is_active        = db.Column(db.Boolean, default=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    # Perfil
    # rol: 'super_admin' | 'admin' | 'tecnico' | 'repartidor'
    rol              = db.Column(db.String(20), default='tecnico')
    nombre_completo  = db.Column(db.String(150))
    telefono_perfil  = db.Column(db.String(20))
    telegram_chat_id = db.Column(db.String(50))

    # Jerarquía: admin que creó este usuario
    creado_por_id    = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    avisos = db.relationship('Aviso', backref='creado_por', lazy=True,
                             foreign_keys='Aviso.created_by')

    # ── Propiedades de rol ──────────────────────────────────────────

    @property
    def es_super_admin(self):
        return self.rol == 'super_admin'

    @property
    def es_admin(self):
        """True para admin Y super_admin (compatibilidad con código existente)."""
        return self.rol in ('admin', 'super_admin')

    @property
    def es_admin_o_superior(self):
        return self.rol in ('admin', 'super_admin')

    @property
    def es_trabajador(self):
        """True para técnicos y repartidores."""
        return self.rol in ('tecnico', 'repartidor')

    @property
    def rol_label(self):
        return {
            'super_admin': 'Super Admin',
            'admin':       'Administrador',
            'tecnico':     'Técnico',
            'repartidor':  'Repartidor',
        }.get(self.rol, self.rol)

    @property
    def rol_badge_class(self):
        return {
            'super_admin': 'bg-danger',
            'admin':       'bg-primary',
            'tecnico':     'bg-success',
            'repartidor':  'bg-warning text-dark',
        }.get(self.rol, 'bg-secondary')

    @property
    def display_name(self):
        return self.nombre_completo or self.username

    def puede_ver_economico(self, aviso):
        """
        - super_admin: siempre
        - admin: solo si es el admin asignado del aviso (o no tiene admin asignado = legacy)
        - técnico/repartidor: nunca
        """
        if self.rol == 'super_admin':
            return True
        if self.rol == 'admin':
            if aviso.admin_asignado_id is None or aviso.admin_asignado_id == self.id:
                return True
        return False


class Aviso(db.Model):
    __tablename__ = 'aviso'

    id = db.Column(db.Integer, primary_key=True)

    # Datos del cliente
    nombre_cliente = db.Column(db.String(150), nullable=False)
    telefono       = db.Column(db.String(20),  nullable=False, index=True)
    calle          = db.Column(db.String(200))
    localidad      = db.Column(db.String(100))

    # Datos del electrodoméstico
    electrodomestico = db.Column(db.String(100))
    marca            = db.Column(db.String(100))
    descripcion      = db.Column(db.Text)
    notas            = db.Column(db.Text)

    # Tipo de servicio y origen
    tipo_servicio = db.Column(db.String(20), default='reparacion')  # reparacion|instalacion|reparto
    origen        = db.Column(db.String(30), default='particular')  # particular|electrofactory|milar|inmobiliaria|otro

    # Fechas
    fecha_aviso = db.Column(db.Date, nullable=False, default=date.today)
    fecha_cita  = db.Column(db.Date, nullable=True)

    # Estado del aviso
    estado = db.Column(db.String(30), nullable=False, default='pendiente', index=True)

    # Económico
    precio_mano_obra  = db.Column(db.Float, nullable=True)
    coste_materiales  = db.Column(db.Float, nullable=True)
    materiales_desc   = db.Column(db.Text,  nullable=True)
    descuento         = db.Column(db.Float, nullable=True)
    gastos_extra      = db.Column(db.Float, nullable=True)
    gastos_extra_desc = db.Column(db.String(200), nullable=True)
    cobro_estado      = db.Column(db.String(20), default='pendiente')

    # Auditoría y asignación
    created_at        = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at        = db.Column(db.DateTime, default=datetime.utcnow)
    created_by        = db.Column(db.Integer,  db.ForeignKey('user.id'), nullable=True)
    asignado_a        = db.Column(db.Integer,  db.ForeignKey('user.id'), nullable=True)
    admin_asignado_id = db.Column(db.Integer,  db.ForeignKey('user.id'), nullable=True)

    # Relaciones
    photos          = db.relationship('Photo', backref='aviso', lazy=True,
                                      cascade='all, delete-orphan')
    tecnico         = db.relationship('User', foreign_keys=[asignado_a],
                                      backref=db.backref('avisos_asignados', lazy=True))
    admin_asignado  = db.relationship('User', foreign_keys=[admin_asignado_id],
                                      backref=db.backref('avisos_administrados', lazy=True))

    # ── Permisos ────────────────────────────────────────────────────

    def puede_editar(self, user):
        """
        - super_admin: siempre
        - admin: si es el admin asignado o no hay admin asignado (avisos legacy)
        - tecnico/repartidor: solo si está asignado al aviso
        """
        if user.es_super_admin:
            return True
        if user.es_admin:
            return self.admin_asignado_id is None or self.admin_asignado_id == user.id
        return self.asignado_a == user.id

    # ── Tipo de servicio ────────────────────────────────────────────

    def tipo_servicio_label(self):
        for key, label, _ in TIPOS_SERVICIO:
            if key == self.tipo_servicio:
                return label
        return 'Reparación'

    def tipo_servicio_icon(self):
        for key, _, icon in TIPOS_SERVICIO:
            if key == self.tipo_servicio:
                return icon
        return '🔧'

    def origen_label(self):
        for key, label, _ in ORIGENES:
            if key == self.origen:
                return label
        return 'Particular'

    def origen_icon(self):
        for key, _, icon in ORIGENES:
            if key == self.origen:
                return icon
        return '👤'

    # ── Métodos de estado ──────────────────────────────────────────

    def estado_label(self):
        for key, label in ESTADOS:
            if key == self.estado:
                return label
        return self.estado

    def estado_badge_class(self):
        return {
            'pendiente':          'bg-warning text-dark',
            'hoy':                'bg-danger',
            'esperando_material': 'bg-info text-dark',
            'segunda_visita':     'bg-primary',
            'finalizado':         'bg-success',
        }.get(self.estado, 'bg-secondary')

    def cobro_label(self):
        for key, label in COBRO_ESTADOS:
            if key == self.cobro_estado:
                return label
        return self.cobro_estado or 'Pendiente de cobro'

    def cobro_badge_class(self):
        return {
            'pagado':    'bg-success',
            'pendiente': 'bg-warning text-dark',
            'moroso':    'bg-danger',
        }.get(self.cobro_estado, 'bg-secondary')

    # ── Cálculos económicos ────────────────────────────────────────

    @property
    def total_cliente(self):
        base = (self.precio_mano_obra or 0) + (self.gastos_extra or 0)
        desc = self.descuento or 0
        return round(max(base - desc, 0), 2)

    @property
    def beneficio(self):
        return round(self.total_cliente - (self.coste_materiales or 0), 2)

    @property
    def tiene_datos_economicos(self):
        return any([
            self.precio_mano_obra is not None,
            self.coste_materiales is not None,
            self.gastos_extra is not None,
        ])


@event.listens_for(Aviso, 'before_update')
def update_timestamp(mapper, connection, target):
    target.updated_at = datetime.utcnow()


class Photo(db.Model):
    __tablename__ = 'photo'

    id            = db.Column(db.Integer, primary_key=True)
    aviso_id      = db.Column(db.Integer, db.ForeignKey('aviso.id'), nullable=False)
    filename      = db.Column(db.String(256), nullable=False)
    original_name = db.Column(db.String(256))
    uploaded_at   = db.Column(db.DateTime, default=datetime.utcnow)
    uploaded_by   = db.Column(db.Integer,  db.ForeignKey('user.id'), nullable=True)
