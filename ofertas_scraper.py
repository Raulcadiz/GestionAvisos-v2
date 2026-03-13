"""
Scraper de ofertas de Electrofactory.
Usa caché en BD para no saturar su servidor y cumplir con la legalidad.
Solo se actualiza cada CACHE_HORAS horas.
"""
import os
import time
import json
import hashlib
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

ELECTROFACTORY_BASE = 'https://www.tiendaselectrofactory.com'
CACHE_HORAS = 6   # Actualizar máximo cada 6 horas
_cache = {}       # { categoria: { 'ts': timestamp, 'items': [...] } }

CATEGORIAS = {
    'lavadoras':       '/categoria/lavadoras',
    'frigorificos':    '/categoria/frigorificos',
    'hornos':          '/categoria/hornos',
    'lavavajillas':    '/categoria/lavavajillas',
    'vitroceramicas':  '/categoria/vitroceramicas',
}

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'es-ES,es;q=0.9',
}


def _cache_valida(categoria):
    if categoria not in _cache:
        return False
    ts = _cache[categoria].get('ts', 0)
    return (time.time() - ts) < CACHE_HORAS * 3600


def _scrape_categoria(ruta):
    """Intenta obtener productos de una categoría. Devuelve lista o []."""
    try:
        url = ELECTROFACTORY_BASE + ruta
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        items = []
        # Selectores comunes en tiendas WooCommerce/PrestaShop:
        productos = (
            soup.select('.product-item') or
            soup.select('.product_item') or
            soup.select('article.product') or
            soup.select('.woocommerce-loop-product') or
            []
        )
        for p in productos[:12]:
            nombre = (
                (p.select_one('.product-title') or
                 p.select_one('h2') or
                 p.select_one('h3') or
                 p.select_one('.woocommerce-loop-product__title'))
            )
            precio = (
                p.select_one('.price') or
                p.select_one('.product-price') or
                p.select_one('span.woocommerce-Price-amount')
            )
            img = p.select_one('img')
            enlace = p.select_one('a')

            if nombre:
                items.append({
                    'nombre': nombre.get_text(strip=True),
                    'precio': precio.get_text(strip=True) if precio else '',
                    'imagen': img.get('src', img.get('data-src', '')) if img else '',
                    'url': enlace.get('href', url) if enlace else url,
                })

        return items
    except Exception:
        return []


def obtener_ofertas(categoria='lavadoras'):
    """
    Devuelve lista de productos de la categoría.
    Usa caché para no saturar el servidor.
    """
    if _cache_valida(categoria):
        return _cache[categoria]['items']

    ruta = CATEGORIAS.get(categoria, CATEGORIAS['lavadoras'])
    items = _scrape_categoria(ruta)

    _cache[categoria] = {'ts': time.time(), 'items': items}
    return items
