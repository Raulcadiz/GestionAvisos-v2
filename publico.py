import hashlib
import hmac
import os
from datetime import date

from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import db
from models import Aviso, ELECTRODOMESTICOS
from telegram_bot import notificar_aviso_nuevo


# ─── Helpers de seguimiento ─────────────────────────────────────────────────

def _token_seguimiento(aviso_id: int) -> str:
    """Genera un token HMAC de 10 caracteres para el seguimiento público.
    Determinístico: mismo id → mismo token. No requiere columna extra en BD."""
    clave = os.environ.get('SECRET_KEY', 'electrobahia-secret-fallback')
    return hmac.new(clave.encode(), str(aviso_id).encode(), hashlib.sha256).hexdigest()[:10]


def url_seguimiento(aviso_id: int) -> str:
    """Devuelve la URL pública de seguimiento para un aviso."""
    return url_for('publico.seguimiento', aviso_id=aviso_id,
                   token=_token_seguimiento(aviso_id), _external=True)

publico_bp = Blueprint('publico', __name__, url_prefix='/aviso')

# Catálogo de ofertas con URLs reales de ElectroFactory
OFERTAS_CATEGORIAS = [
    {
        'nombre':      'Lavadoras',
        'icono':       '🫧',
        'url':         'https://www.tiendaselectrofactory.com/es/3253-LAVADORAS',
        'descripcion': 'Las mejores lavadoras al mejor precio. Bosch, Samsung, Balay y más.',
        'color':       'primary',
    },
    {
        'nombre':      'Frigoríficos',
        'icono':       '🧊',
        'url':         'https://www.tiendaselectrofactory.com/es/3252-FRIGORIFICOS',
        'descripcion': 'Frigoríficos y combi de todas las medidas y marcas.',
        'color':       'info',
    },
    {
        'nombre':      'Lavavajillas',
        'icono':       '🍽️',
        'url':         'https://www.tiendaselectrofactory.com/es/3254-LAVAVAJILLAS',
        'descripcion': 'Lavavajillas eficientes y silenciosos para tu cocina.',
        'color':       'success',
    },
    {
        'nombre':      'Vitrocerámicas',
        'icono':       '🔥',
        'url':         'https://www.tiendaselectrofactory.com/es/3380-ENCASTRE',
        'descripcion': 'Vitrocerámicas, placas de inducción y cocinas encastrables.',
        'color':       'danger',
    },
    {
        'nombre':      'Hornos',
        'icono':       '🫕',
        'url':         'https://www.tiendaselectrofactory.com/es/3380-ENCASTRE',
        'descripcion': 'Hornos eléctricos y multifunción para cocinar como un profesional.',
        'color':       'warning',
    },
]


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

        # Notificar por Telegram y WhatsApp (no bloquean si fallan)
        notificar_aviso_nuevo(aviso)
        try:
            from whatsapp_bot import notificar_aviso_whatsapp
            notificar_aviso_whatsapp(aviso, url_seguimiento(aviso.id))
        except Exception:
            pass

        enviado = True
        link_seguimiento = url_seguimiento(aviso.id)
        return render_template('publico/aviso_publico.html',
                               electrodomesticos=ELECTRODOMESTICOS,
                               enviado=True,
                               aviso_id=aviso.id,
                               link_seguimiento=link_seguimiento,
                               form_data={})

    return render_template('publico/aviso_publico.html',
                           electrodomesticos=ELECTRODOMESTICOS,
                           enviado=enviado,
                           aviso_id=None,
                           link_seguimiento=None,
                           form_data={})


@publico_bp.route('/seguimiento/<int:aviso_id>/<token>')
def seguimiento(aviso_id, token):
    """Página pública de seguimiento de reparación para el cliente."""
    # Verificar token HMAC (protege contra acceso por fuerza bruta)
    if not hmac.compare_digest(token, _token_seguimiento(aviso_id)):
        return render_template('publico/seguimiento.html', aviso=None, error='Enlace no válido.')

    aviso = Aviso.query.get(aviso_id)
    if not aviso:
        return render_template('publico/seguimiento.html', aviso=None, error='Aviso no encontrado.')

    return render_template('publico/seguimiento.html', aviso=aviso, error=None)


@publico_bp.route('/seguimiento')
def seguimiento_buscar():
    """Formulario para buscar el aviso por código (id + token)."""
    codigo = request.args.get('codigo', '').strip()
    error  = None
    aviso  = None

    if codigo:
        try:
            # Formato esperado: "12-abc1234567" (id-token)
            partes = codigo.split('-', 1)
            if len(partes) == 2:
                aviso_id = int(partes[0])
                token    = partes[1]
                if hmac.compare_digest(token, _token_seguimiento(aviso_id)):
                    aviso = Aviso.query.get(aviso_id)
                    if aviso:
                        return redirect(url_for('publico.seguimiento',
                                                aviso_id=aviso_id, token=token))
            error = 'Código no válido. Comprueba el enlace que te enviamos.'
        except (ValueError, TypeError):
            error = 'Formato de código incorrecto.'

    return render_template('publico/seguimiento_buscar.html', error=error, codigo=codigo)


@publico_bp.route('/ofertas')
def ofertas():
    """Página pública con las ofertas de electrodomésticos de ElectroFactory."""
    return render_template('publico/ofertas.html', categorias=OFERTAS_CATEGORIAS)
