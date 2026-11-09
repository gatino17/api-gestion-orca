import importlib.util
from datetime import date
from io import BytesIO
from pathlib import Path
import unittest

from openpyxl import load_workbook


spec = importlib.util.spec_from_file_location('_soporte_excel_tests', Path(__file__).resolve().parents[1] / 'app' / 'soporte_excel.py')
excel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(excel)


class SoporteExcelTest(unittest.TestCase):
    def setUp(self):
        self.casos = [
            dict(id_soporte=1, cliente='Cliente A', centro='Norte', fecha_soporte=date(2026, 1, 5), responsabilidad_falla='cliente',
                 origen='orca', estado='resuelto', problema='Falla de camara', solucion='Cable reemplazado', fecha_cierre=date(2026, 1, 6)),
            dict(id_soporte=2, cliente='Cliente A', centro='Sur', fecha_soporte=date(2026, 2, 5), responsabilidad_falla='orca', estado='pendiente'),
            dict(id_soporte=3, cliente='Cliente B', centro='Sur', fecha_soporte=date(2026, 1, 5), responsabilidad_falla=None),
            dict(id_soporte=4, cliente='Cliente A', centro='Norte', fecha_soporte=date(2025, 12, 31), responsabilidad_falla='terceros'),
        ]

    def libro(self, casos=None):
        archivo = excel.generar_responsabilidad_excel(self.casos if casos is None else casos, 2026)
        self.assertEqual(archivo.read(2), b'PK')
        archivo.seek(0)
        return load_workbook(BytesIO(archivo.read()))

    def test_real_workbook_with_one_sheet_per_client_monthly_totals_and_details(self):
        libro = self.libro()
        self.assertEqual(libro.sheetnames, ['Cliente A', 'Cliente B'])
        hoja = libro['Cliente A']
        self.assertEqual([hoja.cell(fila, 1).value for fila in range(7, 19)], list(excel.MESES))
        self.assertEqual([hoja.cell(7, col).value for col in range(2, 7)], [1, 0, 0, 0, 1])
        self.assertEqual([hoja.cell(8, col).value for col in range(2, 7)], [0, 1, 0, 0, 1])
        self.assertEqual([hoja.cell(19, col).value for col in range(2, 7)], [1, 1, 0, 0, 2])
        self.assertEqual(hoja['B7'].data_type, 'n')
        self.assertEqual(hoja['G23'].value, 'Falla de camara')
        self.assertEqual(hoja['H23'].value, 'Cable reemplazado')
        self.assertEqual(hoja['D23'].value, 'Cliente')
        self.assertEqual(hoja['J23'].value, 'Orca')
        self.assertEqual(hoja['E23'].value, 'Resuelto')
        self.assertEqual(hoja['E23'].fill.fgColor.rgb, '00DCFCE7')
        self.assertEqual(hoja['E24'].fill.fgColor.rgb, '00FEE2E2')
        self.assertEqual(hoja['F23'].value.date(), date(2026, 1, 6))
        self.assertEqual(hoja.auto_filter.ref, 'A22:J24')
        self.assertEqual(libro['Cliente B']['E7'].value, 1)
        self.assertEqual(libro['Cliente B']['H23'].value, 'Sin solucion registrada')
        self.assertNotIn('#4', [hoja.cell(fila, 1).value for fila in range(23, hoja.max_row + 1)])

    def test_unknown_responsibility_is_counted_without_using_report_origin(self):
        casos = [{**self.casos[0], 'responsabilidad_falla': ' otro ', 'origen': 'cliente'}]
        hoja = self.libro(casos).active
        self.assertEqual(hoja['E7'].value, 1)
        self.assertEqual(hoja['B7'].value, 0)
        self.assertEqual(hoja['D23'].value, 'Por determinar')

    def test_sheet_names_are_safe_unique_and_keep_full_client_name_inside(self):
        nombres = ['X' * 40 + ':A', 'X' * 40 + '/B', 'Ventas/Sur', 'Ventas:Sur', 'ventas-sur', "'Otro'"]
        libro = self.libro([{**self.casos[0], 'cliente': nombre} for nombre in nombres])
        self.assertEqual(len({nombre.casefold() for nombre in libro.sheetnames}), len(nombres))
        for hoja in libro:
            self.assertLessEqual(len(hoja.title), 31)
            self.assertFalse(any(char in hoja.title for char in '[]:*?/\\'))
        self.assertEqual({hoja['A2'].value for hoja in libro}, set(nombres))

    def test_user_text_is_literal_not_spreadsheet_formulas_and_xml_controls_are_removed(self):
        for valor in ['=HYPERLINK("https://example.test","Abrir")', '+SUM(1,2)', '-1+1', '@SUM(1,2)']:
            hoja = self.libro([{**self.casos[0], 'case_code': valor, 'problema': valor, 'solucion': valor}]).active
            for direccion in ['A23', 'G23', 'H23']:
                self.assertEqual(hoja[direccion].value, valor)
                self.assertEqual(hoja[direccion].data_type, 's')
        hoja = self.libro([{**self.casos[0], 'problema': 'Texto\x00\x08 valido\nNueva linea'}]).active
        self.assertEqual(hoja['G23'].value, 'Texto valido\nNueva linea')

    def test_long_text_and_empty_workbook_remain_valid(self):
        hoja = self.libro([{**self.casos[0], 'solucion': 'Texto' * 10000}]).active
        self.assertLessEqual(len(hoja['H23'].value), 32767)
        self.assertTrue(hoja['H23'].value.endswith('[texto truncado]'))
        self.assertEqual(self.libro([]).sheetnames, ['Sin casos'])


if __name__ == '__main__':
    unittest.main()
