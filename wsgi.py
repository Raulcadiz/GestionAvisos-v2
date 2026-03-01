"""
Punto de entrada WSGI para PythonAnywhere.

En PythonAnywhere > Web > WSGI configuration file, pon la ruta a este archivo
y asegúrate de que la variable se llama 'application'.

Configuración del archivo WSGI en PythonAnywhere:
  import sys
  sys.path.insert(0, '/home/TUUSUARIO/CadizTecnico')
  from wsgi import application
"""
import sys
import os

# Añadir el directorio del proyecto al path
# PythonAnywhere: cambia TUUSUARIO por tu usuario real
project_path = os.path.dirname(os.path.abspath(__file__))
if project_path not in sys.path:
    sys.path.insert(0, project_path)

# Cargar variables de entorno desde .env
from dotenv import load_dotenv
load_dotenv(os.path.join(project_path, '.env'), override=True)

from app import create_app
application = create_app()
