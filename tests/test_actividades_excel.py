import importlib
import io
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import jwt
from flask import Flask
from openpyxl import load_workbook


# Namespace aislado, base temporal y sin iniciar la aplicacion productiva.
NS = '_actividades_excel_tests'
ROOT = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NS, ROOT), (NS + '.routes', ROOT / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
auth = types.ModuleType(NS + '.routes.auth_routes')
auth.SECRET_KEY = 'actividades-excel-isolated-tests'
sys.modules[auth.__name__] = auth
models = importlib.import_module(NS + '.models')
db = importlib.import_module(NS + '.database').db
routes = importlib.import_module(NS + '.routes.actas_routes')
excel = importlib.import_module(NS + '.actividades_excel')


class ActividadesExcelTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('actividades-excel-tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.actas_blueprint, url_prefix='/api/actas')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        connection = db.engine.raw_connection()
        connection.create_function('concat', -1, lambda *args: ''.join(str(arg) for arg in args if arg is not None))
        connection.close()
        db.session.add_all([models.User(id=i, name=rol, rol=rol, email=rol + '@example.test', password_hash='test')
                            for i, rol in [(1, 'admin'), (2, 'inventario'), (3, 'documentos')]])
        role = models.Role(nombre='documentos')
        db.session.add(role)
        db.session.flush()
        db.session.add(models.RolePage(role_id=role.id_role, page_key='registrosdocumentos'))
        for cid in (1, 2):
            db.session.add(models.Cliente(id_cliente=cid, nombre='Cliente ' + ('A' if cid == 1 else 'B')))
            db.session.flush()
            razon = models.RazonSocial(cliente_id=cid, razon_social='Razon ' + str(cid))
            razon.id_razon_social = cid
            db.session.add(razon)
        db.session.add_all([models.Centro(id_centro=i, nombre=nombre, cliente_id=cid, razon_social_id=cid,
            area='Chiloe', ubicacion='Puerto', estado='cese' if i == 3 else 'activo', fecha_termino=date(2026, 11, 20) if i == 3 else None)
            for i, cid, nombre in [(1, 1, 'Norte'), (2, 1, 'Sur'), (3, 2, 'Otro Norte')]])
        db.session.add(models.InstalacionNueva(centro_id=1, fecha_instalacion=date(2026, 11, 20),
            inicio_monitoreo=date(2026, 11, 20), documento_acta='acta.pdf'))
        db.session.add(models.Levantamiento(centro_id=1, fecha_levantamiento=date(2026, 11, 19), documento_asociado='levantamiento.pdf'))
        db.session.add(models.ActaEntrega(centro_id=2, fecha_registro=date(2026, 11, 21)))
        db.session.add(models.Mantencion(centro_id=1, fecha_mantencion=date(2026, 11, 23), responsable='Tecnico', documento_mantencion='mantencion.pdf'))
        db.session.add(models.Soporte(centro_id=1, tipo='terreno', problema='Mantencion pendiente de documento', fecha_soporte=date(2026, 11, 23)))
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def headers(self, uid=1, **claims):
        return {'Authorization': 'Bearer ' + jwt.encode({'user_id': uid, **claims}, auth.SECRET_KEY, algorithm='HS256')}

    def descargar(self, query='', uid=1):
        with patch('builtins.print'):
            return self.client.get('/api/actas/actividades/excel' + query, headers=self.headers(uid))

    def libro(self, response):
        self.assertEqual(response.status_code, 200, response.get_json(silent=True))
        return load_workbook(io.BytesIO(response.data))

    def test_una_hoja_por_cliente_con_las_mismas_columnas_y_faltantes(self):
        response = self.descargar()
        libro = self.libro(response)
        self.assertEqual(libro.sheetnames, ['Cliente A', 'Cliente B'])
        hoja = libro['Cliente A']
        self.assertEqual([hoja.cell(7, col).value for col in range(1, 11)], list(excel.COLUMNAS))
        self.assertEqual(hoja['A8'].value, 'Norte')
        self.assertEqual(hoja['B7'].value, 'Estado')
        self.assertEqual(hoja['B8'].value, 'activo')
        self.assertEqual(libro['Cliente B']['B8'].value, 'cese')
        self.assertEqual(hoja['C8'].value, 'Chiloe\nPuerto')
        self.assertIn('Falta documento: 1', hoja['D8'].value)
        self.assertIn('Manual: 1', hoja['D8'].value)
        self.assertEqual(hoja['D8'].fill.fgColor.rgb, '00' + excel.AMARILLO)
        self.assertIn('Documento: Disponible', hoja['E8'].value)
        self.assertEqual(hoja['E8'].fill.fgColor.rgb, '00' + excel.VERDE)
        self.assertIn('Manual: Documento disponible', hoja['F8'].value)
        self.assertIn('Actas sistema: 1', hoja['F9'].value)
        self.assertEqual(hoja['F9'].fill.fgColor.rgb, '00' + excel.VERDE)
        self.assertIn('Documento: Sin registro', hoja['J8'].value)
        self.assertEqual(hoja['J8'].fill.fgColor.rgb, '00' + excel.ROJO)
        self.assertIn('20/11/2026', libro['Cliente B']['G8'].value)
        self.assertEqual(hoja.freeze_panes, 'C8')
        self.assertEqual(hoja.auto_filter.ref, 'A7:J9')
        self.assertEqual(hoja.max_column, 10)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')

    def test_cese_precede_a_traslado_sin_intercambiar_sus_datos(self):
        hoja = load_workbook(excel.generar_actividades_excel([dict(id_centro=1, nombre_cliente='Cliente',
            cese_fecha='2026-11-24', cese_documento='cese.pdf',
            traslado_fecha='2026-11-25', traslado_documento='traslado.pdf')])).active
        self.assertEqual(hoja['G7'].value, 'Cese')
        self.assertEqual(hoja['H7'].value, 'Traslado')
        self.assertIn('24/11/2026', hoja['G8'].value)
        self.assertIn('25/11/2026', hoja['H8'].value)

    def test_filtros_de_cliente_y_centro_se_aplican_juntos(self):
        libro = self.libro(self.descargar('?cliente_id=1&nombre_centro=norte'))
        self.assertEqual(libro.sheetnames, ['Cliente A'])
        self.assertEqual(libro.active.auto_filter.ref, 'A7:J8')
        self.assertIn('Norte', libro.active['A8'].value)
        self.assertEqual(self.descargar('?cliente_id=1&nombre_centro=inexistente').status_code, 404)

    def test_sesion_y_permiso_real_de_la_pagina(self):
        self.assertEqual(self.client.get('/api/actas/actividades/excel').status_code, 401)
        self.assertEqual(self.descargar(uid=2).status_code, 403)
        self.assertEqual(self.descargar(uid=3).status_code, 200)
        self.assertEqual(self.descargar(uid=999).status_code, 401)
        self.assertEqual(self.client.get('/api/actas/actividades/excel', headers=self.headers(2, rol='admin')).status_code, 403)

    def test_filtros_invalidos_no_exportan_todos_los_clientes(self):
        for query in ('?cliente_id=abc', '?cliente_id=0', '?cliente_id=-1', '?cliente_id=' + '9' * 30, '?nombre_centro=' + 'x' * 201):
            self.assertEqual(self.descargar(query).status_code, 400)

    def test_errores_de_generacion_no_producen_un_excel_falso(self):
        with patch.object(excel, 'generar_actividades_excel', side_effect=RuntimeError('Error simulado')):
            response = self.descargar()
        self.assertEqual(response.status_code, 500)
        self.assertIn('No se pudo generar', response.get_json()['error'])

    def test_todas_las_paginas_y_agrupacion_por_centro(self):
        filas = [dict(id_centro=i, nombre_centro='Centro ' + str(i), nombre_cliente='Cliente',
                      mantencion_fecha='2026-11-23', mantencion_documento='doc.pdf') for i in range(1, 16)]
        filas.append({**filas[0], 'mantencion_fecha': '2026-11-24'})
        libro = load_workbook(excel.generar_actividades_excel(filas))
        self.assertEqual(libro.active.auto_filter.ref, 'A7:J22')
        self.assertIn('15 centros', libro.active['A3'].value)
        self.assertIn('Manual: 2', libro.active['D8'].value)
        self.assertIn('24/11/2026', libro.active['D8'].value)
        self.assertEqual(libro.active['B8'].value, 'Sin estado')

    def test_hojas_con_nombres_invalidos_largos_y_repetidos_son_seguras(self):
        nombres = ['Cliente/Sur', 'Cliente:Sur', 'cliente-sur', 'X' * 40 + 'A', 'X' * 40 + 'B']
        libro = load_workbook(excel.generar_actividades_excel([dict(id_centro=i, nombre_cliente=nombre) for i, nombre in enumerate(nombres, 1)]))
        self.assertEqual(len(libro.sheetnames), 5)
        self.assertEqual(len({nombre.casefold() for nombre in libro.sheetnames}), 5)
        for hoja in libro:
            self.assertLessEqual(len(hoja.title), 31)
            self.assertFalse(any(char in hoja.title for char in '[]:*?/\\'))
        self.assertEqual({hoja['A2'].value for hoja in libro}, set(nombres))

    def test_varios_documentos_de_instalacion_no_multiplican_mantenciones(self):
        db.session.add(models.InstalacionNueva(centro_id=1, fecha_instalacion=date(2026, 11, 27),
            inicio_monitoreo=date(2026, 11, 27), documento_acta='segundo.pdf'))
        db.session.add(models.Mantencion(centro_id=1, fecha_mantencion=date(2026, 11, 24), responsable='Tecnico'))
        db.session.commit()
        with patch('builtins.print'):
            response = self.client.get('/api/actas/listar?id_centro=1')
        self.assertEqual(response.status_code, 200)
        filas = response.get_json()['actividades']
        self.assertEqual(len(filas), 2)
        self.assertTrue(all(fila['cantidad_documentos_instalacion'] == 2 for fila in filas))
        self.assertTrue(all('20 Nov 2026' in fila['instalacion_fecha'] for fila in filas))
        hoja = self.libro(self.descargar())['Cliente A']
        self.assertIn('Manual: 2', hoja['D8'].value)
        self.assertIn('Documentos manuales: 2', hoja['F8'].value)
        self.assertIn('20/11/2026', hoja['F8'].value)

    def test_documento_adicional_se_detecta_aunque_principal_no_tenga_archivo(self):
        principal = models.InstalacionNueva.query.filter_by(centro_id=1).one()
        principal.documento_acta = None
        db.session.add(models.InstalacionNueva(centro_id=1, fecha_instalacion=date(2026, 11, 27),
            inicio_monitoreo=date(2026, 11, 27), documento_acta='segundo.pdf'))
        db.session.commit()
        with patch('builtins.print'):
            response = self.client.get('/api/actas/listar?id_centro=1')
        fila = response.get_json()['actividades'][0]
        self.assertEqual(fila['cantidad_documentos_instalacion'], 1)
        self.assertTrue(fila['instalacion_documento'].startswith('/api/filtro/documento/Instalaciones/'))
        self.assertIn('Documento disponible', self.libro(self.descargar())['Cliente A']['F8'].value)

    def test_texto_no_se_interpreta_como_formulas_y_fechas_rfc_son_validas(self):
        libro = load_workbook(excel.generar_actividades_excel([dict(id_centro=1, nombre_centro='=SUM(1,2)', nombre_cliente='=Cliente',
            area='@area', ubicacion='-ubicacion', levantamiento_documento='doc.pdf', levantamiento_fecha='Mon, 23 Nov 2026 00:00:00 GMT')]))
        self.assertEqual(libro.active['A8'].data_type, 's')
        self.assertEqual(libro.active['B8'].data_type, 's')
        self.assertEqual(libro.active['C8'].data_type, 's')
        self.assertEqual(libro.active['A2'].data_type, 's')
        self.assertIn('23/11/2026', libro.active['E8'].value)


if __name__ == '__main__':
    unittest.main()
