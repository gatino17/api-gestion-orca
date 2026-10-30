from datetime import date, datetime, timezone
from io import BytesIO
from pathlib import Path
import re
from xml.sax.saxutils import escape

import pytz
import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import CondPageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


CHILE = pytz.timezone('America/Santiago')
AZUL = colors.HexColor('#1269ac')
TINTA = colors.HexColor('#233c52')


def _texto(valor):
    limpio = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', str(valor if valor is not None else ''))
    return escape(limpio).replace('\r\n', '\n').replace('\r', '\n').replace('\n', '<br/>')


def _fecha(valor):
    if not valor:
        return 'Sin registrar'
    try:
        texto = str(valor)
        if 'T' in texto:
            instante = datetime.fromisoformat(texto.replace('Z', '+00:00'))
            if instante.tzinfo is None:
                instante = instante.replace(tzinfo=timezone.utc)
            return instante.astimezone(CHILE).strftime('%d/%m/%Y')
        return date.fromisoformat(texto[:10]).strftime('%d/%m/%Y')
    except (TypeError, ValueError):
        return 'Sin registrar'


def _fuentes():
    carpeta = Path(reportlab.__file__).resolve().parent / 'fonts'
    if not (carpeta / 'Vera.ttf').is_file() or not (carpeta / 'VeraBd.ttf').is_file():
        return 'Helvetica', 'Helvetica-Bold'
    if 'OrcaISO' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('OrcaISO', str(carpeta / 'Vera.ttf')))
        pdfmetrics.registerFont(TTFont('OrcaISO-Bold', str(carpeta / 'VeraBd.ttf')))
        pdfmetrics.registerFontFamily('OrcaISO', normal='OrcaISO', bold='OrcaISO-Bold',
                                     italic='OrcaISO', boldItalic='OrcaISO-Bold')
    return 'OrcaISO', 'OrcaISO-Bold'


def generar_ticket_iso_pdf(ticket, origenes, categorias):
    """Render an authorized ticket snapshot in memory, without changing its data."""
    normal, negrita = _fuentes()
    salida = BytesIO()
    documento = SimpleDocTemplate(salida, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=33 * mm, bottomMargin=20 * mm, title=f"Ticket ISO {ticket['numero_ticket']}", author='OrcaGest')
    cuerpo = ParagraphStyle('ISOBody', fontName=normal, fontSize=9, leading=14, textColor=TINTA,
                            spaceAfter=8, splitLongWords=True, alignment=TA_LEFT)
    seccion = ParagraphStyle('ISOSection', parent=cuerpo, fontName=negrita, fontSize=11,
                            textColor=AZUL, spaceBefore=14, spaceAfter=8)
    pequeno = ParagraphStyle('ISOMeta', parent=cuerpo, fontSize=8, leading=12, spaceAfter=0)
    titulo = ParagraphStyle('ISOTitle', parent=seccion, fontSize=17, leading=22, spaceBefore=0)
    historia = []

    def parrafo(valor, vacio='Sin registrar'):
        return Paragraph(_texto(valor or vacio), cuerpo)

    def encabezado(nombre):
        historia.extend([CondPageBreak(25 * mm), Paragraph(_texto(nombre), seccion)])

    def bloque(nombre, texto):
        encabezado(nombre)
        historia.append(parrafo(texto))

    def datos(campos):
        celdas = [Paragraph(f'<b>{_texto(nombre)}</b><br/>{_texto(valor or "Sin registrar")}', pequeno)
                  for nombre, valor in campos]
        filas = [celdas[indice:indice + 2] for indice in range(0, len(celdas), 2)]
        if len(filas[-1]) == 1:
            filas[-1].append('')
        tabla = Table(filas, colWidths=[documento.width / 2] * 2, hAlign='LEFT')
        tabla.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f1f6fa')),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 9), ('RIGHTPADDING', (0, 0), (-1, -1), 9),
            ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
        ]))
        historia.extend([tabla, Spacer(1, 5 * mm)])

    estados = {'pendiente': 'Pendiente', 'en_seguimiento': 'En seguimiento', 'resuelto': 'Resuelto'}
    historia.append(Paragraph('Detalle del ticket', titulo))
    historia.append(Paragraph(f'<b>{_texto(ticket["numero_ticket"])}</b>', seccion))
    datos([
        ('Estado', estados.get(ticket.get('estado'), ticket.get('estado'))),
        ('Fecha de recepcion', _fecha(ticket.get('fecha_recepcion'))),
        ('Categoria de procedimiento', categorias.get(ticket.get('categoria_procedimiento'), 'Sin categoria registrada')),
        ('Origen', origenes.get(ticket.get('origen'), 'Sin origen registrado')),
    ])
    bloque('Descripcion del problema', ticket.get('problema'))
    datos([('Responsable', ticket.get('responsable')), ('Fecha de registro', _fecha(ticket.get('fecha_registro_descripcion')))])
    bloque('Accion inmediata', ticket.get('accion_inmediata'))
    datos([('Responsable de la accion inmediata', ticket.get('responsable_accion_inmediata')),
           ('Fecha de accion', _fecha(ticket.get('fecha_accion_inmediata')))])
    encabezado('Seguimiento del ticket')
    seguimiento = ticket.get('amerita_seguimiento')
    historia.append(parrafo('Amerita seguimiento: ' + ('Si' if seguimiento is True else 'No' if seguimiento is False else 'Sin especificar')))
    if seguimiento is True:
        preguntas = ticket.get('seguimiento_preguntas') or []
        for indice in range(5):
            item = preguntas[indice] if indice < len(preguntas) else {}
            historia.append(Paragraph(f'<b>Pregunta {indice + 1}:</b> {_texto(item.get("pregunta") or "Pendiente de definir")}', cuerpo))
            historia.append(parrafo(item.get('respuesta'), 'Respuesta pendiente.'))
        bloque('Causa raiz', ticket.get('causa_raiz'))
        datos([('Responsable de causa raiz', ticket.get('responsable_causa_raiz')),
               ('Fecha de causa raiz', _fecha(ticket.get('fecha_causa_raiz')))])
    bloque('Resultados obtenidos', ticket.get('observaciones'))
    planes = ticket.get('planes_accion') or []
    encabezado(f'Planes de accion ({len(planes)})')
    if not planes:
        historia.append(parrafo('Sin planes de accion registrados.'))
    for indice, plan in enumerate(planes):
        encabezado(f'Plan {plan.get("numero") or len(planes) - indice}')
        historia.append(parrafo(plan.get('resultado_plan_accion')))
        datos([('Fecha de control', _fecha(plan.get('fecha_control'))), ('Registrado', _fecha(plan.get('created_at')))])
    if ticket.get('solucion'):
        bloque('Solucion aplicada', ticket['solucion'])
    encabezado('Cierre del caso')
    datos([('Fecha de cierre' if ticket.get('estado') == 'resuelto' else 'Fecha de cierre prevista', _fecha(ticket.get('fecha_cierre')))])
    if ticket.get('creado_por_nombre'):
        datos([('Registrado por', ticket['creado_por_nombre'])])

    generado = datetime.now(CHILE).strftime('%d/%m/%Y %H:%M')

    def decorar(canvas, doc):
        canvas.saveState()
        canvas.setFillColor(AZUL)
        canvas.setFont(negrita, 18)
        canvas.drawString(18 * mm, A4[1] - 18 * mm, 'OrcaGest')
        canvas.setFont(negrita, 9)
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 15 * mm, 'TICKET ISO')
        referencia = str(ticket['numero_ticket']).replace('\n', ' ').replace('\r', ' ')
        while pdfmetrics.stringWidth(referencia, normal, 8) > 80 * mm:
            referencia = referencia[:-4] + '...'
        canvas.setFont(normal, 8)
        canvas.drawRightString(A4[0] - 18 * mm, A4[1] - 21 * mm, referencia)
        canvas.setStrokeColor(colors.HexColor('#cddce6'))
        canvas.line(18 * mm, A4[1] - 26 * mm, A4[0] - 18 * mm, A4[1] - 26 * mm)
        canvas.line(18 * mm, 16 * mm, A4[0] - 18 * mm, 16 * mm)
        canvas.setFillColor(colors.HexColor('#637f95'))
        canvas.setFont(normal, 7)
        canvas.drawString(18 * mm, 11 * mm, f'Generado el {generado} - Hora de Chile')
        canvas.drawRightString(A4[0] - 18 * mm, 11 * mm, f'Pagina {doc.page}')
        canvas.restoreState()

    documento.build(historia, onFirstPage=decorar, onLaterPages=decorar)
    salida.seek(0)
    return salida
