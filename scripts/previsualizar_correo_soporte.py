"""Generate an offline email preview without app startup, credentials or SMTP."""
import argparse
import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--salida', type=Path, default=ROOT / 'docs' / 'soporte-correo-vista-previa.html')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('_soporte_plantilla_preview', ROOT / 'app' / 'soporte_plantilla.py')
    plantilla = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(plantilla)
    contenido = dict(id_soporte=1169, cliente='Cermaq', centro='Acopio', area='Puerto Montt',
        fecha='2026-10-26', prioridad='media', estado='pendiente', creado_por='Admin',
        problema='La c\u00e1mara de acceso no presenta conexi\u00f3n. No es posible visualizar la imagen desde la plataforma.',
        sugerencia='Verificar la alimentaci\u00f3n del equipo y el estado del cableado de red.\n'
                   'Comprobar el puerto del switch y realizar una prueba de conexi\u00f3n en terreno.')
    html = plantilla.renderizar_aviso_terreno(contenido, 'Admin', vista_previa=True)
    args.salida.parent.mkdir(parents=True, exist_ok=True)
    args.salida.write_text(html, encoding='utf-8')
    print(f'Vista previa local: {args.salida.resolve()}')
    print('Solo datos de ejemplo. No se consulto la base de datos ni se envio correo.')


if __name__ == '__main__':
    main()
