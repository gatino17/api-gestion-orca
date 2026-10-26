import os
from pathlib import Path

from dotenv import dotenv_values


SMTP_KEYS = (
    'SMTP_HOST', 'SMTP_PORT', 'SMTP_USE_TLS', 'SMTP_USE_SSL',
    'SMTP_USERNAME', 'SMTP_FROM', 'SMTP_PASSWORD',
    'SOPORTE_TERRENO_DESTINATARIOS',
)


def configurar_smtp_desde_archivo(app, ruta=None):
    ruta = Path(ruta) if ruta is not None else Path(__file__).resolve().parents[1] / 'smtp.env'
    if not ruta.is_file():
        return
    # Read only mail settings; never override server environment or app configuration.
    valores = dotenv_values(ruta, interpolate=False, encoding='utf-8-sig')
    for clave in SMTP_KEYS:
        valor = valores.get(clave)
        if valor is not None and clave not in os.environ and clave not in app.config:
            app.config[clave] = valor
