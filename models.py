from datetime import datetime, date
from flask_login import UserMixin
from sqlalchemy import event
from extensions import db


class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id               = db.Column(db.Integer, primary_key=True)
    username         = db.Column(db.String(80), unique=True, nullable=False)
    password         = db.Column(db.String(256), nullable=False)
    is_active        = db.Column(db.Boolean, default=True)
    created_at       = db.Column(db.DateTime, default=datetime.utcnow)

    # Perfil
    rol              = db.Column(db.String(20), default='tecnico')  # 'admin' | 'tecnico'
    nombre_completo  = db.Column(db.String(150))
    telefono_perfil  = db.Column(db.String(20))
    telegram_chat_id = db.Column(db.String(50))

    avisos = db.relationship('Aviso', backref='creado_por', lazy=True,
                             foreign_keys='Aviso.created_by')

    @property
    def es_admin(self):
        return self.rol == 'admin'

    @property
    def display_name(self):
        return self.nombre_completo or self.username


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

    # Fechas
    fecha_aviso = db.Column(db.Date, nullable=False, default=date.today)
    fecha_cita  = db.Column(db.Date, nullable=True)

    # Estado del aviso
    estado = db.Column(db.String(30), nullable=False, default='pendiente', index=True)

    # Económico
    precio_mano_obra  = db.Column(db.Float, nullable=True)     # € mano de obra
    coste_materiales  = db.Column(db.Float, nullable=True)     # € coste piezas (interno)
    materiales_desc   = db.Column(db.Text,  nullable=True)     # descripción piezas
    descuento         = db.Column(db.Float, nullable=True)     # € descuento al cliente
    gastos_extra      = db.Column(db.Float, nullable=True)     # desplazamiento, urgencia…
    gastos_extra_desc = db.Column(db.String(200), nullable=True)
    cobro_estado      = db.Column(db.String(20), default='pendiente')  # pagado|pendiente|moroso

    # Auditoría y asignación
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow)
    created_by  = db.Column(db.Integer,  db.ForeignKey('user.id'), nullable=True)
    asignado_a  = db.Column(db.Integer,  db.ForeignKey('user.id'), nullable=True)

    # Relaciones
    photos   = db.relationship('Photo', backref='aviso', lazy=True,
                               cascade='all, delete-orphan')
    tecnico  = db.relationship('User', foreign_keys=[asignado_a],
                               backref=db.backref('avisos_asignados', lazy=True))

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
        """Total a cobrar al cliente = mano_obra + gastos_extra - descuento."""
        base = (self.precio_mano_obra or 0) + (self.gastos_extra or 0)
        desc = self.descuento or 0
        return round(max(base - desc, 0), 2)

    @property
    def beneficio(self):
        """Beneficio neto = total_cliente - coste_materiales."""
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
