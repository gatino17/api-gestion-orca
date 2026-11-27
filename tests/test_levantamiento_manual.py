import importlib
import io
import os
import sys
import tempfile
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from flask import Flask


# Modelos reales en SQLite temporal, sin iniciar la aplicacion productiva.
NS = '_levantamiento_manual_tests'
ROOT = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NS, ROOT), (NS + '.routes', ROOT / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
models = importlib.import_module(NS + '.models')
db = importlib.import_module(NS + '.database').db
routes = importlib.import_module(NS + '.routes.levantamientos_routes')
actas = importlib.import_module(NS + '.routes.actas_routes')
filtro = importlib.import_module(NS + '.routes.filtro_routes')


class LevantamientoManualTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('levantamiento-manual-tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.levantamientos_blueprint, url_prefix='/api/levantamientos')
        cls.app.register_blueprint(actas.actas_blueprint, url_prefix='/api/actas')
        cls.app.register_blueprint(filtro.filtro_blueprint, url_prefix='/api/filtro')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add(models.Cliente(id_cliente=1, nombre='Cliente prueba'))
        razon = models.RazonSocial(cliente_id=1, razon_social='Razon prueba')
        db.session.add(razon)
        db.session.flush()
        db.session.add_all([models.Centro(id_centro=i, nombre='Centro ' + str(i), cliente_id=1,
                                         razon_social_id=razon.id_razon_social) for i in (1, 2)])
        db.session.commit()
        self.folder = tempfile.TemporaryDirectory()
        self.cwd = patch.object(os, 'getcwd', return_value=self.folder.name)
        self.uploads = patch.object(routes, 'UPLOAD_FOLDER', str(Path(self.folder.name, 'uploads', 'levantamientos_docs')))
        self.cwd.start()
        self.uploads.start()
        self.client = self.app.test_client()

    def tearDown(self):
        self.uploads.stop()
        self.cwd.stop()
        self.folder.cleanup()
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def subir(self, nombre='plano.pptx', contenido=b'presentacion de prueba', centro='1', fecha='2026-11-26', registro=None):
        data = {'centro_id': centro, 'fecha_levantamiento': fecha}
        if nombre is not None:
            data['documento_asociado'] = (io.BytesIO(contenido), nombre)
        endpoint = '/api/actas/levantamientos' + ('/' + str(registro) if registro else '')
        return (self.client.put if registro else self.client.post)(endpoint, data=data)

    def test_powerpoint_se_guarda_lista_y_descarga_por_ambos_enlaces(self):
        for nombre in ('plano.ppt', 'plano.PPTX'):
            with self.subTest(nombre=nombre):
                response = self.subir(nombre=nombre)
                self.assertEqual(response.status_code, 201)
                registro_id = response.get_json()['id_levantamiento']
                for endpoint in (f'/api/filtro/documento/Levantamientos/{registro_id}',
                                 f'/api/levantamientos/{registro_id}/documento'):
                    response = self.client.get(endpoint)
                    self.assertEqual(response.status_code, 200)
                    self.assertTrue(response.headers['Content-Disposition'].startswith('attachment'))
                    self.assertEqual(response.data, b'presentacion de prueba')
                    response.close()
        registros = self.client.get('/api/actas/levantamientos?centro_id=1').get_json()
        self.assertEqual(len(registros), 2)
        self.assertEqual(registros[0]['fecha_levantamiento'], '2026-11-26')
        self.assertEqual(self.client.get('/api/actas/levantamientos?centro_id=2').get_json(), [])

    def test_pdf_e_imagenes_siguen_abriendo_en_linea(self):
        for nombre, mime in [('plano.pdf', 'application/pdf'), ('plano.PNG', 'image/png'), ('foto.jpg', 'image/jpeg')]:
            response = self.subir(nombre=nombre)
            self.assertEqual(response.status_code, 201)
            response = self.client.get('/api/filtro/documento/Levantamientos/' + str(response.get_json()['id_levantamiento']))
            self.assertEqual(response.mimetype, mime)
            self.assertTrue(response.headers['Content-Disposition'].startswith('inline'))
            response.close()

    def test_enlace_de_la_tabla_usa_el_host_real_de_la_api(self):
        self.subir()
        connection = db.engine.raw_connection()
        connection.create_function('concat', -1, lambda *args: ''.join(str(arg) for arg in args if arg is not None))
        connection.close()
        with patch('builtins.print'):
            response = self.client.get('/api/actas/listar', base_url='https://orca.example:24306')
        self.assertEqual(response.status_code, 200)
        fila = next(item for item in response.get_json()['actividades'] if item['id_centro'] == 1)
        self.assertTrue(fila['levantamiento_documento'].startswith('https://orca.example:24306/api/filtro/documento/Levantamientos/'))

    def test_archivo_invalido_no_crea_un_registro_sin_documento(self):
        with patch.object(routes, 'MAX_DOCUMENTO_BYTES', 32):
            for nombre, contenido in [('mal.exe', b'x'), ('vacio.pptx', b''), ('grande.ppt', b'x' * 33)]:
                response = self.subir(nombre=nombre, contenido=contenido)
                self.assertEqual(response.status_code, 400)
                self.assertIn('error', response.get_json())
        self.assertEqual(models.Levantamiento.query.count(), 0)
        self.assertFalse(Path(routes.UPLOAD_FOLDER).exists())

    def test_editar_fecha_conserva_documento_y_no_duplica(self):
        self.subir()
        registro = models.Levantamiento.query.one()
        anterior = registro.documento_asociado
        response = self.subir(nombre=None, fecha='2026-11-25', registro=registro.id_levantamiento)
        self.assertEqual(response.status_code, 200)
        registro = models.Levantamiento.query.one()
        self.assertEqual(registro.fecha_levantamiento, date(2026, 11, 25))
        self.assertEqual(registro.documento_asociado, anterior)
        self.assertTrue(Path(self.folder.name, 'uploads', anterior).is_file())

    def test_reemplazo_usa_nombre_unico_y_limpia_anterior(self):
        self.subir()
        registro = models.Levantamiento.query.one()
        anterior = registro.documento_asociado
        self.assertEqual(self.subir(registro=registro.id_levantamiento).status_code, 200)
        nuevo = models.Levantamiento.query.one().documento_asociado
        self.assertNotEqual(anterior, nuevo)
        self.assertFalse(Path(self.folder.name, 'uploads', anterior).exists())
        self.assertTrue(Path(self.folder.name, 'uploads', nuevo).is_file())

    def test_fallo_bd_al_reemplazar_conserva_original_y_limpia_archivo_nuevo(self):
        self.subir()
        registro = models.Levantamiento.query.one()
        anterior = registro.documento_asociado
        with patch.object(db.session, 'commit', side_effect=RuntimeError('Fallo simulado')):
            self.assertEqual(self.subir(registro=registro.id_levantamiento).status_code, 400)
        self.assertEqual(models.Levantamiento.query.one().documento_asociado, anterior)
        self.assertEqual(len(list(Path(routes.UPLOAD_FOLDER).iterdir())), 1)

    def test_fallo_bd_al_crear_limpia_el_archivo(self):
        with patch.object(db.session, 'commit', side_effect=RuntimeError('Fallo simulado')):
            self.assertEqual(self.subir().status_code, 400)
        self.assertEqual(models.Levantamiento.query.count(), 0)
        self.assertEqual(list(Path(routes.UPLOAD_FOLDER).iterdir()), [])

    def test_reemplazo_invalido_no_modifica_fecha_ni_documento(self):
        self.subir()
        registro = models.Levantamiento.query.one()
        anterior = registro.documento_asociado
        self.assertEqual(self.subir(nombre='mal.exe', fecha='2026-11-01', registro=registro.id_levantamiento).status_code, 400)
        registro = models.Levantamiento.query.one()
        self.assertEqual(registro.fecha_levantamiento, date(2026, 11, 26))
        self.assertEqual(registro.documento_asociado, anterior)
        self.assertTrue(Path(self.folder.name, 'uploads', anterior).is_file())

    def test_centro_fecha_y_registro_invalidos_no_guardan_archivos(self):
        self.assertEqual(self.subir(centro='999').status_code, 404)
        self.assertEqual(self.subir(fecha='mal').status_code, 400)
        self.assertEqual(self.subir(registro=999).status_code, 404)
        self.assertFalse(Path(routes.UPLOAD_FOLDER).exists())
        for centro in ('abc', '0', '-1'):
            self.assertEqual(self.client.get('/api/actas/levantamientos?centro_id=' + centro).status_code, 400)


if __name__ == '__main__':
    unittest.main()
