from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape


_templates = Environment(
    loader=FileSystemLoader(Path(__file__).resolve().parent / 'templates' / 'correo'),
    autoescape=select_autoescape(['html']),
    undefined=StrictUndefined,
)


def renderizar_aviso_terreno(contenido, enviado_por, vista_previa=False):
    try:
        fecha = date.fromisoformat(str(contenido['fecha'])[:10]).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        fecha = str(contenido['fecha'] or '-')
    prioridad = str(contenido['prioridad'] or 'media').lower()
    prioridades = {
        'alta': ('Alta', '#b42318', '#fff1f0'),
        'media': ('Media', '#8a5200', '#fff5dd'),
        'baja': ('Baja', '#176449', '#eaf7f0'),
    }
    etiqueta, color, fondo = prioridades.get(prioridad, (prioridad.capitalize(), '#475569', '#f1f5f9'))
    pendiente = contenido['estado'] == 'pendiente'
    return _templates.get_template('soporte_terreno.html').render(
        caso=contenido, enviado_por=enviado_por, fecha=fecha, vista_previa=vista_previa,
        prioridad=etiqueta, prioridad_color=color, prioridad_fondo=fondo,
        estado='Pendiente' if pendiente else 'En seguimiento',
        estado_color='#b42318' if pendiente else '#8a5200',
        estado_fondo='#fff1f0' if pendiente else '#fff5dd',
    )
