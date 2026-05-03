import os
from dotenv import load_dotenv
load_dotenv(override=True)

from flask import Flask
from config import Config
from extensions import db, login_manager


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(os.path.join(os.path.dirname(__file__), 'instance'), exist_ok=True)

    db.init_app(app)

    login_manager.init_app(app)
    login_manager.login_view = 'auth.login_page'
    login_manager.login_message = 'Debes iniciar sesión para acceder.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return User.query.get(int(user_id))

    # Registrar blueprints
    from auth import auth_bp
    from dashboard import dashboard_bp
    from avisos import avisos_bp
    from exports import exports_bp
    from publico import publico_bp
    from admin import admin_bp
    from estadisticas import estadisticas_bp
    from calendario import calendario_bp
    from ia_diagnostico import ia_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(avisos_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(publico_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(estadisticas_bp)
    app.register_blueprint(calendario_bp)
    app.register_blueprint(ia_bp)

    with app.app_context():
        from models import User, Aviso, Photo  # noqa: F401
        db.create_all()
        _migrar_columnas()
        _seed_default_users()

    return app


def _migrar_columnas():
    """Añade columnas nuevas a tablas existentes sin borrar datos."""
    from sqlalchemy import text, inspect
    with db.engine.connect() as conn:
        inspector = inspect(db.engine)

        # ── User ──
        user_cols = [c['name'] for c in inspector.get_columns('user')]
        if 'rol' not in user_cols:
            conn.execute(text("ALTER TABLE user ADD COLUMN rol VARCHAR(20) DEFAULT 'tecnico'"))
            conn.execute(text("UPDATE user SET rol='super_admin' WHERE username='admin'"))
        for col, tipo in [
            ('nombre_completo', 'VARCHAR(150)'),
            ('telefono_perfil', 'VARCHAR(20)'),
            ('telegram_chat_id', 'VARCHAR(50)'),
            ('creado_por_id', 'INTEGER'),
        ]:
            if col not in user_cols:
                conn.execute(text(f"ALTER TABLE user ADD COLUMN {col} {tipo}"))

        # Actualizar admin existente a super_admin si tiene rol 'admin'
        conn.execute(text(
            "UPDATE user SET rol='super_admin' WHERE username='admin' AND rol='admin'"
        ))
        # Asignar técnicos sin creador al super_admin
        conn.execute(text(
            "UPDATE user SET creado_por_id=(SELECT id FROM user WHERE rol='super_admin' LIMIT 1) "
            "WHERE creado_por_id IS NULL AND rol IN ('tecnico','repartidor')"
        ))

        # ── Aviso ──
        aviso_cols = [c['name'] for c in inspector.get_columns('aviso')]
        nuevas_aviso = [
            ('precio_mano_obra',  'FLOAT',        None),
            ('coste_materiales',  'FLOAT',        None),
            ('materiales_desc',   'TEXT',         None),
            ('descuento',         'FLOAT',        None),
            ('gastos_extra',      'FLOAT',        None),
            ('gastos_extra_desc', 'VARCHAR(200)', None),
            ('cobro_estado',      'VARCHAR(20)',  "'pendiente'"),
            ('asignado_a',        'INTEGER',      None),
            ('tipo_servicio',     'VARCHAR(20)',  "'reparacion'"),
            ('origen',            'VARCHAR(30)',  "'particular'"),
            ('admin_asignado_id', 'INTEGER',      None),
        ]
        for col, tipo, default in nuevas_aviso:
            if col not in aviso_cols:
                sql = f"ALTER TABLE aviso ADD COLUMN {col} {tipo}"
                if default:
                    sql += f" DEFAULT {default}"
                conn.execute(text(sql))

        if 'hora_cita' not in aviso_cols:
            conn.execute(text("ALTER TABLE aviso ADD COLUMN hora_cita VARCHAR(5)"))
        if 'items_instalacion' not in aviso_cols:
            conn.execute(text("ALTER TABLE aviso ADD COLUMN items_instalacion TEXT"))

        conn.commit()


def _seed_default_users():
    from models import User
    from werkzeug.security import generate_password_hash
    if User.query.count() == 0:
        admin = User(username='admin', password=generate_password_hash('admin123'),
                     rol='super_admin', nombre_completo='Administrador Principal')
        db.session.add(admin)
        db.session.flush()
        usuarios = [
            User(username='tecnico1', password=generate_password_hash('tecnico123'),
                 rol='tecnico', creado_por_id=admin.id),
            User(username='tecnico2', password=generate_password_hash('tecnico123'),
                 rol='tecnico', creado_por_id=admin.id),
        ]
        db.session.add_all(usuarios)
        db.session.commit()
        print("Usuarios creados: admin/admin123, tecnico1/tecnico123, tecnico2/tecnico123")


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8080)
