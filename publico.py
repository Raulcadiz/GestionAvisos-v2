from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import Aviso, ELECTRODOMESTICOS
from telegram_bot import notificar_aviso_nuevo

publico_bp = Blueprint('publico', __name__, url_prefix='/aviso')


@publico_bp.route('/nuevo', methods=['GET', 'POST'])
def aviso_publico():
    """Formulario público para que el cliente deje un aviso sin necesidad de login."""
    enviado = False

    if request.method == 'POST':
        nombre = request.form.get('nombre_cliente', '').strip()
        telefono = request.form.get('telefono', '').strip()
        electrodomestico = request.form.get('electrodomestico', '').strip()
        marca = request.form.get('marca', '').strip()
        descripcion = request.form.get('descripcion', '').strip()
        calle = request.form.get('calle', '').strip()
        localidad = request.form.get('localidad', '').strip()

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
        )
        db.session.add(aviso)
        db.session.commit()

        # Notificar por Telegram (no bloquea si falla)
        notificar_aviso_nuevo(aviso)

        enviado = True

    return render_template('publico/aviso_publico.html',
                           electrodomesticos=ELECTRODOMESTICOS,
                           enviado=enviado,
                           form_data={})
