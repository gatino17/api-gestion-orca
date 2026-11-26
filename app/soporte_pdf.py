from collections import Counter
from datetime import date, datetime
from io import BytesIO
import re
from xml.sax.saxutils import escape

import pytz
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import CondPageBreak, LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


AZUL = colors.HexColor('#1263aa')
TINTA = colors.HexColor('#244361')
ESTADOS = {'pendiente': 'Pendiente', 'en_proceso': 'En seguimiento', 'resuelto': 'Resuelto'}
RESPONSABILIDADES = {'cliente': 'Cliente', 'orca': 'Orca', 'terceros': 'Terceros', 'por_determinar': 'Por determinar'}
COLORES_ESTADO = {'pendiente': '#be123c', 'en_proceso': '#966000', 'resuelto': '#15803d'}
CHILE = pytz.timezone('America/Santiago')


def _texto(valor):
    limpio = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(valor if valor is not None else ''))
    return escape(limpio).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br/>')


def _fecha(valor):
    if not valor:
        return '-'
    if isinstance(valor, (date, datetime)):
        return valor.strftime('%d/%m/%Y')
    return date.fromisoformat(str(valor)[:10]).strftime('%d/%m/%Y')


def _descripcion_resumen(valor):
    texto = ' '.join(str(valor or 'Sin problema registrado').split())
    if len(texto) <= 180:
        return texto
    return texto[:177].rsplit(' ', 1)[0] + '...'


def _hora_creacion(valor):
    if not isinstance(valor, datetime):
        return '-'
    # Las fechas sin zona se interpretan como UTC; las nuevas conservan su zona.
    instante = pytz.UTC.localize(valor) if valor.tzinfo is None else valor
    return instante.astimezone(CHILE).strftime('%H:%M')


def generar_registros_soporte_pdf(registros, filtros):
    """Exporta registros consultados en el servidor, sin recibir detalles del navegador."""
    archivo = BytesIO()
    documento = SimpleDocTemplate(archivo, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm,
        topMargin=31 * mm, bottomMargin=21 * mm, title='Registros de soporte', author='OrcaGest')
    cuerpo = ParagraphStyle('SoporteBody', fontName='Helvetica', fontSize=9, leading=13,
                            textColor=TINTA, spaceAfter=7, splitLongWords=True)
    pequeno = ParagraphStyle('SoporteMeta', parent=cuerpo, fontSize=8, leading=11, spaceAfter=0)
    resumen = ParagraphStyle('SoporteResumen', parent=pequeno, fontSize=7.7, leading=10.5)
    cabecera_resumen = ParagraphStyle('SoporteResumenCabecera', parent=resumen,
                                    fontName='Helvetica-Bold', textColor=colors.white)
    titulo = ParagraphStyle('SoporteTitle', parent=cuerpo, fontName='Helvetica-Bold', fontSize=17,
                            leading=22, textColor=AZUL, spaceAfter=9)
    caso = ParagraphStyle('SoporteCaso', parent=cuerpo, fontName='Helvetica-Bold', fontSize=11,
                          leading=15, textColor=AZUL, spaceBefore=8, spaceAfter=5)
    generado = datetime.now(CHILE).strftime('%d/%m/%Y %H:%M')
    fecha_informe = ParagraphStyle('SoporteFecha', parent=pequeno, textColor=colors.HexColor('#647c92'), spaceAfter=10)
    historia = [Paragraph('Registros de soporte', titulo), Paragraph(f'Fecha: {generado} - Hora de Chile', fecha_informe)]
    estados = Counter(str(item.get('estado') or 'pendiente').lower() for item in registros)
    etiqueta_eventos = 'evento' if len(registros) == 1 else 'eventos'
    historia.append(Paragraph(f'<b>{len(registros)} {etiqueta_eventos}</b> | Pendientes: {estados["pendiente"]} | '
                             f'En seguimiento: {estados["en_proceso"]} | Resueltos: {estados["resuelto"]}', cuerpo))
    if filtros.get('busqueda'):
        historia.append(Paragraph('<b>Soporte:</b> ' + _texto(filtros['busqueda']), cuerpo))
    if filtros.get('desde') or filtros.get('hasta'):
        historia.append(Paragraph(f'<b>Rango fecha:</b> {_fecha(filtros.get("desde")) if filtros.get("desde") else "Sin limite inicial"}'
                                 f' al {_fecha(filtros.get("hasta")) if filtros.get("hasta") else "Sin limite final"}', cuerpo))
    historia.extend([Paragraph('Incluye todos los resultados filtrados, no solo la pagina visible.', pequeno), Spacer(1, 5 * mm)])

    historia.append(Paragraph('Resumen de eventos', caso))
    historia.extend([Paragraph('Descripcion abreviada. El texto completo se presenta en las paginas de detalle. '
                              'Hora: creacion del registro en horario de Chile.', pequeno), Spacer(1, 3 * mm)])
    filas_resumen = [[Paragraph(nombre, cabecera_resumen) for nombre in
                      ('N', 'Caso', 'Centro / cliente', 'Fecha', 'Hora', 'Estado', 'Descripcion')]]
    for indice, registro in enumerate(registros, 1):
        referencia = f'<b>#{registro["id_soporte"]}</b>'
        if registro.get('case_code'):
            referencia += '<br/>' + _texto(registro['case_code'])
        estado = str(registro.get('estado') or 'pendiente').lower()
        color = COLORES_ESTADO.get(estado, '#52677d')
        filas_resumen.append([
            Paragraph(str(indice), resumen),
            Paragraph(referencia, resumen),
            Paragraph('<b>' + _texto(registro.get('centro') or '-') + '</b><br/>' + _texto(registro.get('cliente') or '-'), resumen),
            Paragraph(_fecha(registro.get('fecha_soporte')), resumen),
            Paragraph(_hora_creacion(registro.get('created_at')), resumen),
            Paragraph(f'<font color="{color}"><b>{_texto(ESTADOS.get(estado, estado))}</b></font>', resumen),
            Paragraph(_texto(_descripcion_resumen(registro.get('problema'))), resumen),
        ])
    tabla_resumen = LongTable(filas_resumen, colWidths=[9 * mm, 30 * mm, 35 * mm, 20 * mm, 15 * mm, 20 * mm, 47 * mm],
                             repeatRows=1, hAlign='LEFT')
    tabla_resumen.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), AZUL),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f5f8fc')]),
        ('LINEBELOW', (0, 1), (-1, -1), .35, colors.HexColor('#d8e5ef')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 6), ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6), ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (0, -1), 3), ('RIGHTPADDING', (0, 0), (0, -1), 3),
    ]))
    historia.extend([tabla_resumen, PageBreak(), Paragraph('Detalle de eventos', titulo)])

    def datos(campos):
        celdas = [Paragraph(f'<b>{_texto(nombre)}:</b> {_texto(valor or "-")}', pequeno) for nombre, valor in campos]
        filas = [celdas[indice:indice + 3] for indice in range(0, len(celdas), 3)]
        filas[-1].extend([''] * (3 - len(filas[-1])))
        tabla = Table(filas, colWidths=[176 * mm / 3] * 3, hAlign='LEFT')
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f5f8fc')),
            ('LINEBEFORE', (0, 0), (0, -1), 2, AZUL),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 7), ('RIGHTPADDING', (0, 0), (-1, -1), 7),
            ('TOPPADDING', (0, 0), (-1, -1), 4), ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        historia.extend([tabla, Spacer(1, 3 * mm)])

    for indice, registro in enumerate(registros, 1):
        historia.append(CondPageBreak(50 * mm))
        referencia = f'{indice:02d} | Soporte #{registro["id_soporte"]}'
        if registro.get('case_code'):
            referencia += ' - ' + str(registro['case_code'])
        historia.append(Paragraph(_texto(referencia), caso))
        estado = str(registro.get('estado') or 'pendiente').lower()
        color = COLORES_ESTADO.get(estado, '#52677d')
        historia.append(Paragraph(f'<font color="{color}"><b>{_texto(ESTADOS.get(estado, estado))}</b></font>', cuerpo))
        campos = [('Centro', registro.get('centro')), ('Cliente', registro.get('cliente')),
                  ('Fecha del evento', _fecha(registro.get('fecha_soporte'))), ('Hora de creacion', _hora_creacion(registro.get('created_at'))),
                  ('Fecha de cierre', _fecha(registro.get('fecha_cierre'))),
                  ('Tipo', str(registro.get('tipo') or '-').capitalize()), ('Prioridad', str(registro.get('prioridad') or 'media').capitalize())]
        creador = registro.get('creado_por_nombre')
        if creador and str(creador).strip().lower() != 'sin registro':
            campos.append(('Creado por', creador))
        campos.extend([('Origen del reporte', str(registro.get('origen') or 'cliente').capitalize()),
                       ('Responsabilidad', RESPONSABILIDADES.get(registro.get('responsabilidad_falla'), 'Por determinar')),
                       ('Categoria', registro.get('categoria_falla')), ('Subcategoria', registro.get('subcategoria_falla')),
                       ('Permiso de trabajo', 'Si' if registro.get('permiso_trabajo') else 'No')])
        datos(campos)
        for etiqueta, campo, vacio in [('Problema', 'problema', 'Sin problema registrado'),
                                       ('Solucion', 'solucion', 'Sin solucion registrada'),
                                       ('Sugerencia de terreno', 'sugerencia', None)]:
            valor = registro.get(campo) or vacio
            if valor:
                historia.append(Paragraph(f'<b>{etiqueta}</b><br/>{_texto(valor)}', cuerpo))
        if registro.get('cambio_equipo'):
            historia.append(Paragraph('<b>Cambio de equipo:</b> ' + _texto(registro.get('equipo_cambiado') or 'Si, sin detalle registrado'), cuerpo))
        historia.append(Spacer(1, 4 * mm))

    def decorar(canvas, doc):
        canvas.saveState()
        canvas.setFont('Helvetica-Bold', 19)
        canvas.setFillColor(AZUL)
        canvas.drawString(17 * mm, A4[1] - 18 * mm, 'OrcaGest')
        canvas.setFont('Helvetica-Bold', 8)
        canvas.drawRightString(A4[0] - 17 * mm, A4[1] - 18 * mm, 'INFORME DE SOPORTE')
        canvas.setStrokeColor(colors.HexColor('#d8e5ef'))
        canvas.line(17 * mm, A4[1] - 24 * mm, A4[0] - 17 * mm, A4[1] - 24 * mm)
        canvas.line(17 * mm, 16 * mm, A4[0] - 17 * mm, 16 * mm)
        canvas.setFont('Helvetica', 7)
        canvas.setFillColor(colors.HexColor('#647c92'))
        canvas.drawString(17 * mm, 11 * mm, f'Generado el {generado} - Hora de Chile')
        canvas.drawRightString(A4[0] - 17 * mm, 11 * mm, f'Pagina {doc.page}')
        canvas.restoreState()

    documento.build(historia, onFirstPage=decorar, onLaterPages=decorar)
    archivo.seek(0)
    return archivo
