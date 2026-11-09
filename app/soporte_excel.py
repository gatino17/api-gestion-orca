from collections import defaultdict
from datetime import date, datetime
from io import BytesIO
import re

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


MESES = ('Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
         'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre')
RESPONSABILIDADES = {
    'cliente': 'Cliente', 'orca': 'Orca', 'terceros': 'Terceros', 'por_determinar': 'Por determinar',
}
ESTADOS = {'pendiente': 'Pendiente', 'en_proceso': 'En seguimiento', 'resuelto': 'Resuelto', 'finalizado': 'Resuelto'}
AZUL = '1269AC'


def _fecha(valor):
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (ValueError, TypeError):
        return None


def _texto(celda, valor):
    texto = ILLEGAL_CHARACTERS_RE.sub('', str(valor if valor is not None else ''))
    if len(texto) > 32767:
        texto = texto[:32748] + ' [texto truncado]'
    celda.value = texto
    # All user text stays literal, including values starting with =, +, - or @.
    celda.data_type = 's'
    celda.alignment = Alignment(vertical='top', wrap_text=True)


def _titulo_hoja(nombre, usados):
    base = re.sub(r'[\[\]:*?/\\]', '-', ILLEGAL_CHARACTERS_RE.sub('', nombre)).strip(" '") or 'Sin cliente'
    titulo = base[:31]
    numero = 2
    while titulo.casefold() in usados:
        sufijo = f' ({numero})'
        titulo = base[:31 - len(sufijo)] + sufijo
        numero += 1
    usados.add(titulo.casefold())
    return titulo


def _banda(hoja, fila, titulo, columnas):
    hoja.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=columnas)
    celda = hoja.cell(fila, 1)
    _texto(celda, titulo)
    celda.font = Font(name='Calibri', size=12, bold=True, color='FFFFFF')
    celda.fill = PatternFill('solid', fgColor=AZUL)
    hoja.row_dimensions[fila].height = 24


def _encabezados(hoja, fila, nombres):
    for indice, nombre in enumerate(nombres, 1):
        celda = hoja.cell(fila, indice)
        _texto(celda, nombre)
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor=AZUL)
    hoja.row_dimensions[fila].height = 30


def generar_responsabilidad_excel(registros, anio, centro=''):
    """Build an annual workbook from authorized records, without database access."""
    por_cliente = defaultdict(list)
    for registro in registros:
        fecha = _fecha(registro.get('fecha_soporte'))
        if fecha and fecha.year == anio:
            por_cliente[str(registro.get('cliente') or 'Sin cliente')].append(registro)

    libro = Workbook()
    libro.remove(libro.active)
    libro.properties.creator = 'OrcaGest'
    libro.properties.title = f'Responsabilidad de la falla - {anio}'
    usados = set()
    for cliente in sorted(por_cliente, key=lambda value: (value.casefold(), value)):
        casos = sorted(por_cliente[cliente], key=lambda row: (_fecha(row['fecha_soporte']), row.get('id_soporte') or 0))
        hoja = libro.create_sheet(_titulo_hoja(cliente, usados))
        hoja.sheet_view.showGridLines = False
        hoja.sheet_view.zoomScale = 85
        _banda(hoja, 1, 'OrcaGest | Responsabilidad de la falla', 11)
        _texto(hoja.cell(2, 1), cliente)
        hoja.merge_cells('A2:K2')
        hoja.cell(2, 1).font = Font(size=14, bold=True, color=AZUL)
        total_permisos = sum(caso.get('permiso_trabajo') is True for caso in casos)
        _texto(hoja.cell(3, 1), f'A\u00f1o: {anio} | Centro: {centro or "Todos"} | Casos: {len(casos)} | Con permiso de trabajo: {total_permisos}')
        hoja.merge_cells('A3:K3')
        _banda(hoja, 5, 'Resumen mensual', 7)
        _encabezados(hoja, 6, ['Mes', *RESPONSABILIDADES.values(), 'Total', 'Con permiso de trabajo'])
        conteos = [[0] * 4 for _ in range(12)]
        permisos_por_mes = [0] * 12
        claves = list(RESPONSABILIDADES)
        for caso in casos:
            responsabilidad = str(caso.get('responsabilidad_falla') or '').strip().lower()
            indice = claves.index(responsabilidad) if responsabilidad in claves else 3
            mes_indice = _fecha(caso['fecha_soporte']).month - 1
            conteos[mes_indice][indice] += 1
            if caso.get('permiso_trabajo') is True:
                permisos_por_mes[mes_indice] += 1
        for fila, (mes, valores) in enumerate(zip(MESES, conteos), 7):
            _texto(hoja.cell(fila, 1), mes)
            for columna, valor in enumerate([*valores, sum(valores), permisos_por_mes[fila - 7]], 2):
                celda = hoja.cell(fila, columna, valor)
                celda.alignment = Alignment(horizontal='center')
                celda.number_format = '0'
            for celda in hoja[fila][:7]:
                celda.fill = PatternFill('solid', fgColor='F1F6FA' if fila % 2 else 'FFFFFF')
        _texto(hoja.cell(19, 1), 'Total anual')
        for columna in range(4):
            hoja.cell(19, columna + 2, sum(valores[columna] for valores in conteos))
        hoja.cell(19, 6, len(casos))
        hoja.cell(19, 7, total_permisos)
        for celda in hoja[19][:7]:
            celda.font = Font(bold=True, color=AZUL)
            celda.fill = PatternFill('solid', fgColor='DBEAFE')
        hoja.cell(19, 7).font = Font(bold=True, color='166534')
        hoja.cell(19, 7).fill = PatternFill('solid', fgColor='DCFCE7')
        _texto(hoja.cell(20, 1), 'Los casos con permiso de trabajo ya estan incluidos en el total de casos.')
        hoja.merge_cells('A20:G20')
        hoja.cell(20, 1).font = Font(size=9, italic=True, color='64748B')

        _banda(hoja, 21, 'Detalle de casos', 11)
        _encabezados(hoja, 22, ['Caso', 'Fecha', 'Centro', 'Responsabilidad', 'Estado', 'Fecha de cierre',
                               'Problema', 'Solucion', 'Categoria', 'Origen del reporte', 'Permiso de trabajo'])
        for fila, caso in enumerate(casos, 23):
            responsabilidad = str(caso.get('responsabilidad_falla') or '').strip().lower()
            estado = str(caso.get('estado') or 'pendiente').strip().lower() or 'pendiente'
            valores = [caso.get('case_code') or f'#{caso.get("id_soporte")}', _fecha(caso['fecha_soporte']),
                       caso.get('centro') or 'Sin centro', RESPONSABILIDADES.get(responsabilidad, 'Por determinar'),
                       ESTADOS.get(estado, estado), _fecha(caso.get('fecha_cierre')),
                       caso.get('problema') or 'Sin descripcion', str(caso.get('solucion') or '').strip() or 'Sin solucion registrada',
                       caso.get('categoria_falla') or 'Sin categoria', str(caso.get('origen') or 'cliente').capitalize(),
                       'Si' if caso.get('permiso_trabajo') is True else 'No']
            for columna, valor in enumerate(valores, 1):
                celda = hoja.cell(fila, columna)
                if isinstance(valor, date):
                    celda.value = valor
                    celda.number_format = 'DD/MM/YYYY'
                else:
                    _texto(celda, valor)
                celda.alignment = Alignment(vertical='top', wrap_text=True)
            color = {'resuelto': 'DCFCE7', 'finalizado': 'DCFCE7', 'en_proceso': 'FEF3C7', 'pendiente': 'FEE2E2'}.get(estado, 'E2E8F0')
            hoja.cell(fila, 5).fill = PatternFill('solid', fgColor=color)
            if caso.get('permiso_trabajo') is True:
                hoja.cell(fila, 11).fill = PatternFill('solid', fgColor='DCFCE7')
                hoja.cell(fila, 11).font = Font(bold=True, color='166534')
            lineas = max(sum(max(1, (len(parte) + 54) // 55) for parte in str(valor).split('\n')) for valor in valores[6:8])
            hoja.row_dimensions[fila].height = min(180, max(30, lineas * 15))
        hoja.auto_filter.ref = f'A22:K{22 + len(casos)}'
        hoja.freeze_panes = 'D7'
        hoja.print_options.horizontalCentered = True
        hoja.sheet_properties.pageSetUpPr.fitToPage = True
        hoja.page_setup.orientation = 'landscape'
        hoja.page_setup.paperSize = hoja.PAPERSIZE_A3
        hoja.page_setup.fitToWidth = 1
        hoja.page_setup.fitToHeight = 0
        for indice, ancho in enumerate([18, 14, 26, 24, 20, 16, 60, 60, 24, 22, 22], 1):
            hoja.column_dimensions[get_column_letter(indice)].width = ancho

    if not por_cliente:
        hoja = libro.create_sheet('Sin casos')
        _banda(hoja, 1, 'OrcaGest | Responsabilidad de la falla', 6)
        _texto(hoja.cell(3, 1), f'Sin casos para el ano {anio} y los filtros seleccionados.')
        hoja.merge_cells('A3:F3')
        hoja.column_dimensions['A'].width = 30
    salida = BytesIO()
    libro.save(salida)
    salida.seek(0)
    return salida
