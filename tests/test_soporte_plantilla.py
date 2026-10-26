import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location(
    '_soporte_plantilla_tests', Path(__file__).resolve().parents[1] / 'app' / 'soporte_plantilla.py')
plantilla = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plantilla)


class SoportePlantillaTest(unittest.TestCase):
    def setUp(self):
        self.caso = dict(id_soporte=1169, cliente='Cliente Prueba', centro='Centro Prueba',
            area='Puerto Montt', fecha='2026-10-26', prioridad='media', estado='pendiente',
            creado_por='Admin', problema='Equipo sin conexion', sugerencia='Revisar energia\ny cableado')

    def test_renders_case_metadata_and_separate_sections(self):
        html = plantilla.renderizar_aviso_terreno(self.caso, 'Tecnico Prueba')
        for value in ('#1169', 'OrcaGest', 'Cliente Prueba', 'Centro Prueba', 'Puerto Montt',
                      '26/10/2026', 'Prioridad media', 'Pendiente', 'Admin', 'Tecnico Prueba',
                      'Problema reportado', 'Equipo sin conexion', 'Revisar energia\ny cableado'):
            self.assertIn(value, html)
        self.assertNotIn('Datos de ejemplo', html)

    def test_escapes_all_user_content_and_keeps_colors_allowlisted(self):
        attack = '<img src=x onerror="alert(1)"> & </td>'
        for key in ('id_soporte', 'cliente', 'centro', 'area', 'fecha', 'creado_por', 'problema', 'sugerencia', 'prioridad'):
            self.caso[key] = attack
        html = plantilla.renderizar_aviso_terreno(self.caso, attack)
        self.assertNotIn('<img', html)
        self.assertIn('&lt;img', html)
        self.assertIn('&amp;', html)
        self.assertNotIn('color: <', html)

    def test_followup_and_priority_colors(self):
        self.caso.update(estado='en_proceso', prioridad='alta')
        html = plantilla.renderizar_aviso_terreno(self.caso, 'Admin')
        self.assertIn('En seguimiento', html)
        self.assertIn('Prioridad alta', html)
        self.assertIn('#b42318', html)

    def test_preview_is_explicit_and_layout_supports_small_screens(self):
        html = plantilla.renderizar_aviso_terreno(self.caso, 'Admin', vista_previa=True)
        self.assertIn('Datos de ejemplo', html)
        self.assertIn('max-width: 600px', html)
        self.assertIn('role="presentation"', html)
        self.assertIn('white-space: pre-wrap', html)
        self.assertNotIn('<script', html)
        self.assertNotIn('https://', html)

    def test_empty_or_invalid_date_is_safe(self):
        for value in (None, '-', ''):
            self.caso['fecha'] = value
            self.assertIn('Fecha de registro', plantilla.renderizar_aviso_terreno(self.caso, 'Admin'))


if __name__ == '__main__':
    unittest.main()
