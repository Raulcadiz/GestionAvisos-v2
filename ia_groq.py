"""Acceso a Groq con varias claves y rotación automática.

Las claves se leen, por este orden, de:
  - la variable de entorno GROQ_API_KEYS (separadas por comas o saltos de línea)
  - la variable de entorno GROQ_API_KEY
  - el archivo groq.txt de la raíz del proyecto (una clave por línea)

groq.txt está en .gitignore: nunca debe subirse al repositorio.
"""
import logging
import os
import re
import threading

logger = logging.getLogger(__name__)

RUTA_CLAVES = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'groq.txt')

MODELO_TEXTO = 'openai/gpt-oss-20b'
MODELO_VISION = 'qwen/qwen3.8-27b'

_cerrojo = threading.Lock()
_siguiente = 0


class GroqError(RuntimeError):
    """Error con un mensaje apto para mostrar al usuario."""


def cargar_claves() -> list[str]:
    """Devuelve las claves disponibles, sin duplicados y en orden."""
    candidatas = re.split(r'[,\s]+', os.environ.get('GROQ_API_KEYS', ''))
    candidatas.append(os.environ.get('GROQ_API_KEY', ''))
    try:
        with open(RUTA_CLAVES, encoding='utf-8-sig') as archivo:
            candidatas.extend(archivo.read().split())
    except OSError:
        pass
    return list(dict.fromkeys(c.strip() for c in candidatas if c.strip()))


def _orden_de_uso(total: int) -> list[int]:
    """Reparte las peticiones entre las claves empezando cada vez por una distinta."""
    global _siguiente
    with _cerrojo:
        inicio = _siguiente % total
        _siguiente += 1
    return [(inicio + i) % total for i in range(total)]


def crear_respuesta(**parametros):
    """Llama a chat.completions probando la siguiente clave si una falla o se agota."""
    import groq

    claves = cargar_claves()
    if not claves:
        raise GroqError('No hay claves de Groq. Sube el archivo groq.txt a la carpeta del proyecto.')

    ultimo_codigo = None
    hubo_limite = False
    reintentado = False
    pendientes = _orden_de_uso(len(claves))
    while pendientes:
        indice = pendientes.pop(0)
        cliente = groq.Groq(api_key=claves[indice], max_retries=0, timeout=60)
        try:
            return cliente.chat.completions.create(**parametros)
        except (groq.RateLimitError, groq.AuthenticationError, groq.PermissionDeniedError) as exc:
            ultimo_codigo = exc.status_code
            hubo_limite = hubo_limite or exc.status_code == 429
            logger.warning('Groq: la clave %s respondió %s; se prueba la siguiente.',
                           indice + 1, exc.status_code)
        except groq.InternalServerError as exc:
            # Fallo puntual de Groq, no de la clave: merece un único reintento extra
            ultimo_codigo = exc.status_code
            logger.warning('Groq: error %s del servidor con la clave %s.', exc.status_code, indice + 1)
            if not reintentado:
                reintentado = True
                pendientes.append(indice)
        except groq.APIConnectionError as exc:
            logger.error('Groq: error de conexión: %s', type(exc).__name__)
            raise GroqError('No se pudo conectar con Groq. Inténtalo de nuevo.') from exc

    if hubo_limite:
        raise GroqError('Se ha agotado el límite gratuito de Groq. Inténtalo en unos minutos.')
    if ultimo_codigo and ultimo_codigo >= 500:
        raise GroqError('Groq no está disponible en este momento. Inténtalo de nuevo.')
    raise GroqError('Groq ha rechazado todas las claves. Revisa el archivo groq.txt.')
