"""Utilidades para subir imágenes a Cloudinary."""
import os
import cloudinary
import cloudinary.uploader


def _init():
    cloudinary.config(
        cloud_name=os.environ.get('CLOUDINARY_CLOUD_NAME', ''),
        api_key=os.environ.get('CLOUDINARY_API_KEY', ''),
        api_secret=os.environ.get('CLOUDINARY_API_SECRET', ''),
    )


def subir_imagen(archivo, carpeta='portfolio'):
    """
    Sube un archivo de imagen a Cloudinary y devuelve la URL segura.
    archivo: objeto file de Flask (request.files['campo'])
    """
    _init()
    result = cloudinary.uploader.upload(
        archivo,
        folder=carpeta,
        resource_type='image',
        transformation=[{'width': 1200, 'crop': 'limit', 'quality': 'auto'}],
    )
    return result.get('secure_url', '')


def eliminar_imagen(public_id):
    """Elimina una imagen de Cloudinary por su public_id."""
    _init()
    cloudinary.uploader.destroy(public_id)
