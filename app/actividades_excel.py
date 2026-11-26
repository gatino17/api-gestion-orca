from collections import defaultdict
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from io import BytesIO
import re

import pytz
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


AZUL = '1263AA'
VERDE = 'DCFCE7'
ROJO = 'FEE2E2'
AMARILLO = 'FEF3C7'
COLUMNAS = ('Centro', 'Estado', 'Ubicacion', 'Mantenciones', 'Levantamiento', 'Instalacion', 'Traslado', 'Cese', 'Retiro', 'Inventario')
DIAS = ('lunes', 'martes', 'miercoles', 'jueves', 'viernes', 'sabado', 'domingo')


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        try:
            return parsedate_to_datetime(str(valor)).date()
        except (ValueError, TypeError, OverflowError):
            return None


def _fecha_texto(valor):
    fecha = _fecha(valor)
    return f'{DIAS[fecha.weekday()]} {fecha:%d/%m/%Y}' if fecha else 'Sin registro'


def _texto(celda, valor):
    texto = ILLEGAL_CHARACTERS_RE.sub('', str(valor if valor is not None else ''))
    celda.value = texto[:32767]
    celda.data_type = 's'
    celda.alignment = Alignment(vertical='top', wrap_text=True)


def _titulo(nombre, usados):
    base = re.sub(r'[\[\]:*?/\\]', '-', ILLEGAL_CHARACTERS_RE.sub('', nombre)).strip(" '") or 'Sin cliente'
    titulo = base[:31]
    contador = 2
    while titulo.casefold() in usados:
        sufijo = f' ({contador})'
        titulo = base[:31 - len(sufijo)] + sufijo
        contador += 1
    usados.add(titulo.casefold())
    return titulo


def agrupar_actividades(actividades):
    """Misma agrupacion por centro que usa la tabla de Registros Documentos."""
    agrupadas = {}
    for act in actividades:
        cid = act['id_centro']
        if cid not in agrupadas:
            agrupadas[cid] = {**act, 'cantidad_mantenciones': 0, 'ultima_fecha_mantencion': None,
                             '_mantencion_con_documento': False}
        else:
            for campo in ('instalacion', 'levantamiento', 'traslado', 'cese', 'retiro', 'inventario'):
                for sufijo in ('documento', 'fecha'):
                    clave = campo + '_' + sufijo
                    if act.get(clave):
                        agrupadas[cid][clave] = act[clave]
        registro = agrupadas[cid]
        if act.get('mantencion_fecha'):
            registro['cantidad_mantenciones'] += 1
            fechas = [_fecha(valor) for valor in (registro['ultima_fecha_mantencion'], act['mantencion_fecha'])]
            registro['ultima_fecha_mantencion'] = max((fecha for fecha in fechas if fecha), default=None)
        registro['_mantencion_con_documento'] |= bool(act.get('mantencion_documento'))
        for campo in ('actas', 'permisos', 'mantenciones'):
            clave = f'cantidad_{campo}_sistema'
            registro[clave] = max(int(registro.get(clave) or 0), int(act.get(clave) or 0))
            clave_fecha = {'actas': 'ultima_fecha_acta_sistema', 'permisos': 'ultima_fecha_permiso_sistema',
                           'mantenciones': 'ultima_fecha_mantencion_sistema'}[campo]
            fechas = [_fecha(valor) for valor in (registro.get(clave_fecha), act.get(clave_fecha))]
            registro[clave_fecha] = max((fecha for fecha in fechas if fecha), default=None)
    return list(agrupadas.values())


def _documento(registro, campo, fecha=None):
    disponible = bool(registro.get(campo + '_documento'))
    valor_fecha = fecha if fecha is not None else registro.get(campo + '_fecha')
    return f'Fecha: {_fecha_texto(valor_fecha)}\nDocumento: {"Disponible" if disponible else "Sin registro"}', VERDE if disponible else ROJO


def _mantenciones(registro):
    resumen = registro.get('resumen_intervenciones_mantencion') or {}
    lineas = []
    if resumen:
        intervenciones, soportes = int(resumen.get('intervenciones') or 0), int(resumen.get('soportes') or 0)
        lineas.extend([f'{intervenciones} {"intervencion" if intervenciones == 1 else "intervenciones"}',
                       f'{soportes} {"registro soporte" if soportes == 1 else "registros soporte"}'])
        if resumen.get('sin_documento'):
            lineas.append(f'Falta documento: {resumen["sin_documento"]}')
        elif soportes:
            lineas.append('Soportes documentados')
    lineas.extend([f'Manual: {registro["cantidad_mantenciones"]} - {_fecha_texto(registro.get("ultima_fecha_mantencion"))}',
                   f'Informe sistema: {registro.get("cantidad_mantenciones_sistema", 0)} - {_fecha_texto(registro.get("ultima_fecha_mantencion_sistema"))}'])
    color = AMARILLO if resumen.get('sin_documento') else VERDE if (resumen.get('documentados') or registro['_mantencion_con_documento'] or registro.get('cantidad_mantenciones_sistema')) else ROJO
    return '\n'.join(lineas), color


def _instalacion(registro):
    disponible = bool(registro.get('instalacion_documento'))
    actas, permisos = registro.get('cantidad_actas_sistema', 0), registro.get('cantidad_permisos_sistema', 0)
    texto = (f'Manual: {"Documento disponible" if disponible else "Sin doc"} - {_fecha_texto(registro.get("instalacion_fecha") or registro.get("centro_fecha_instalacion"))}\n'
             f'Actas sistema: {actas} - {_fecha_texto(registro.get("ultima_fecha_acta_sistema"))}\n'
             f'Permisos sistema: {permisos} - {_fecha_texto(registro.get("ultima_fecha_permiso_sistema"))}')
    return texto, VERDE if disponible or actas or permisos else ROJO


def generar_actividades_excel(actividades):
    clientes = defaultdict(list)
    for registro in agrupar_actividades(actividades):
        clientes[registro.get('nombre_cliente') or 'Sin cliente'].append(registro)
    libro = Workbook()
    libro.remove(libro.active)
    usados = set()
    generado = datetime.now(pytz.timezone('America/Santiago')).strftime('%d/%m/%Y %H:%M')
    for cliente in sorted(clientes, key=str.casefold):
        hoja = libro.create_sheet(_titulo(cliente, usados))
        hoja.sheet_view.zoomScale = 75
        for fila, texto in [(1, 'OrcaGest | Actividades y documentos'), (2, cliente),
                             (3, f'{len(clientes[cliente])} centros | Generado: {generado} - Hora de Chile'),
                             (4, 'Verde: respaldo disponible. Rojo: sin documento. Amarillo: soportes de mantencion sin respaldo.'),
                             (5, 'Mismos registros de la tabla Actividades, incluidas todas sus paginas.')]:
            hoja.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=len(COLUMNAS))
            celda = hoja.cell(fila, 1)
            _texto(celda, texto)
            celda.font = Font(name='Calibri', size=15 if fila == 1 else 11, bold=fila < 3, color=AZUL if fila < 3 else '52677D')
            hoja.row_dimensions[fila].height = 27 if fila == 1 else 20
        for indice, nombre in enumerate(COLUMNAS, 1):
            celda = hoja.cell(7, indice)
            _texto(celda, nombre)
            celda.font = Font(name='Calibri', size=11, bold=True, color='FFFFFF')
            celda.fill = PatternFill('solid', fgColor=AZUL)
        hoja.row_dimensions[7].height = 26
        for fila, registro in enumerate(clientes[cliente], 8):
            fecha_cese = registro.get('cese_fecha') or (registro.get('centro_fecha_termino') if str(registro.get('estado') or '').lower() == 'cese' else None)
            celdas = [(registro.get('nombre_centro') or 'Sin centro', None),
                      (registro.get('estado') or 'Sin estado', None),
                      (f'{registro.get("area") or "Sin dato"}\n{registro.get("ubicacion") or "Sin dato"}', None),
                      _mantenciones(registro), _documento(registro, 'levantamiento'), _instalacion(registro),
                      _documento(registro, 'traslado'), _documento(registro, 'cese', fecha_cese),
                      _documento(registro, 'retiro'), _documento(registro, 'inventario')]
            for columna, (valor, color) in enumerate(celdas, 1):
                celda = hoja.cell(fila, columna)
                _texto(celda, valor)
                celda.font = Font(name='Calibri', size=11, color='244361')
                celda.fill = PatternFill('solid', fgColor=color or ('F2F6FA' if fila % 2 == 0 else 'FFFFFF'))
            hoja.row_dimensions[fila].height = 118
        for indice, ancho in enumerate((26, 16, 28, 38, 30, 40, 30, 30, 30, 26), 1):
            hoja.column_dimensions[get_column_letter(indice)].width = ancho
        hoja.freeze_panes = 'C8'
        ultima_columna = get_column_letter(len(COLUMNAS))
        hoja.auto_filter.ref = f'A7:{ultima_columna}{7 + len(clientes[cliente])}'
        hoja.print_title_rows = '1:7'
        hoja.print_area = f'A1:{ultima_columna}{7 + len(clientes[cliente])}'
        hoja.sheet_properties.pageSetUpPr.fitToPage = True
        hoja.page_setup.orientation = 'landscape'
        hoja.page_setup.paperSize = hoja.PAPERSIZE_A3
        hoja.page_setup.fitToWidth = 1
        hoja.page_setup.fitToHeight = 0
    if not clientes:
        hoja = libro.create_sheet('Sin resultados')
        _texto(hoja['A1'], 'No hay actividades para los filtros seleccionados.')
    archivo = BytesIO()
    libro.save(archivo)
    archivo.seek(0)
    return archivo
