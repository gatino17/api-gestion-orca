import importlib.util
from pathlib import Path
import unittest

from pypdf import PdfReader


spec = importlib.util.spec_from_file_location('_ticket_iso_pdf_tests', Path(__file__).resolve().parents[1] / 'app' / 'ticket_iso_pdf.py')
pdf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdf)


class TicketISOPDFTest(unittest.TestCase):
    def setUp(self):
        self.ticket = dict(numero_ticket='ISO-2026-001', fecha_recepcion='2026-10-14', estado='pendiente',
            origen='ticket_iso', categoria_procedimiento='bodega', problema='Problema registrado',
            accion_inmediata='Accion realizada', responsable='Persona descripcion', fecha_registro_descripcion='2026-10-15',
            responsable_accion_inmediata='Persona accion', fecha_accion_inmediata='2026-10-16',
            amerita_seguimiento=True, causa_raiz='Causa identificada', responsable_causa_raiz='Persona analisis',
            fecha_causa_raiz='2026-10-17', observaciones='Resultados obtenidos', planes_accion=[],
            seguimiento_preguntas=[{'pregunta': f'Consulta {n}', 'respuesta': f'Respuesta {n}'} for n in range(1, 6)])

    def render(self):
        archivo = pdf.generar_ticket_iso_pdf(self.ticket, {'ticket_iso': 'Ticket ISO'}, {'bodega': '006 Bodega'})
        self.assertEqual(archivo.read(5), b'%PDF-')
        archivo.seek(0)
        reader = PdfReader(archivo)
        return reader, '\n'.join(page.extract_text() for page in reader.pages)

    def test_contains_all_ticket_sections_and_independent_metadata(self):
        _reader, texto = self.render()
        for valor in ('OrcaGest', 'ISO-2026-001', '006 Bodega', 'Problema registrado', 'Persona descripcion',
                      '15/10/2026', 'Accion realizada', 'Persona accion', '16/10/2026', 'Causa identificada',
                      'Persona analisis', '17/10/2026', 'Consulta 5', 'Respuesta 5', 'Resultados obtenidos'):
            self.assertIn(valor, texto)

    def test_long_text_and_seven_plans_paginate_without_losing_the_end(self):
        self.ticket.update(problema='x' * 10000, observaciones=('Resultado extenso ' * 500) + 'FIN RESULTADOS',
            planes_accion=[dict(numero=n, resultado_plan_accion=('Accion detallada ' * 100) + f'FIN PLAN {n}', fecha_control='2026-10-20') for n in range(7, 0, -1)])
        reader, texto = self.render()
        texto_continuo = ' '.join(texto.split())
        self.assertGreater(len(reader.pages), 1)
        self.assertIn('Planes de accion (7)', texto)
        self.assertIn('FIN RESULTADOS', texto_continuo)
        for numero in range(1, 8):
            self.assertIn(f'FIN PLAN {numero}', texto_continuo)
        for pagina in reader.pages:
            self.assertIn('OrcaGest', pagina.extract_text())

    def test_escapes_markup_and_renders_spanish_characters(self):
        self.ticket['problema'] = '<img src="https://example.test/image.png"/> & <b>Revision</b>\nRevisi\u00f3n de acci\u00f3n inmediata'
        _reader, texto = self.render()
        self.assertIn('<img', texto)
        self.assertIn('<b>Revision</b>', texto)
        self.assertIn('Revisi\u00f3n de acci\u00f3n inmediata', texto)

    def test_no_followup_hides_root_cause_and_answers(self):
        self.ticket['amerita_seguimiento'] = False
        _reader, texto = self.render()
        self.assertIn('Amerita seguimiento: No', texto)
        self.assertNotIn('Causa identificada', texto)
        self.assertNotIn('Persona analisis', texto)
        self.assertNotIn('Consulta 1', texto)

    def test_optional_fields_closing_date_and_author_visibility(self):
        self.ticket.update(estado='resuelto', fecha_cierre='2026-10-16T01:00:00+00:00', creado_por_nombre='Administrador visible')
        _reader, texto = self.render()
        self.assertIn('Fecha de cierre', texto)
        self.assertIn('Administrador visible', texto)
        self.assertEqual(pdf._fecha(self.ticket['fecha_cierre']), '15/10/2026')
        self.ticket.pop('creado_por_nombre')
        _reader, texto = self.render()
        self.assertNotIn('Administrador visible', texto)


if __name__ == '__main__':
    unittest.main()
