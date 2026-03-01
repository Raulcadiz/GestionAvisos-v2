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

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(avisos_bp)
    app.register_blueprint(exports_bp)
    app.register_blueprint(publico_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(estadisticas_bp)
    app.register_blueprint(calendario_bp)

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
            conn.execute(text("UPDATE user SET rol='admin' WHERE username='admin'"))
        for col, tipo in [
            ('nombre_completo', 'VARCHAR(150)'),
            ('telefono_perfil', 'VARCHAR(20)'),
            ('telegram_chat_id', 'VARCHAR(50)'),
        ]:
            if col not in user_cols:
                conn.execute(text(f"ALTER TABLE user ADD COLUMN {col} {tipo}"))

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
        ]
        for col, tipo, default in nuevas_aviso:
            if col not in aviso_cols:
                sql = f"ALTER TABLE aviso ADD COLUMN {col} {tipo}"
                if default:
                    sql += f" DEFAULT {default}"
                conn.execute(text(sql))

        conn.commit()


def _seed_default_users():
    from models import User
    from werkzeug.security import generate_password_hash
    if User.query.count() == 0:
        usuarios = [
            User(username='admin',    password=generate_password_hash('admin123'),    rol='admin'),
            User(username='tecnico1', password=generate_password_hash('tecnico123'), rol='tecnico'),
            User(username='tecnico2', password=generate_password_hash('tecnico123'), rol='tecnico'),
        ]
        db.session.add_all(usuarios)
        db.session.commit()
        print("Usuarios creados: admin/admin123, tecnico1/tecnico123, tecnico2/tecnico123")


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=8080)
