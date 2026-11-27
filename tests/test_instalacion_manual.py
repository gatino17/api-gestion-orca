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


# Modelos reales con base temporal; no importa ni inicia la aplicacion productiva.
NS = '_instalacion_manual_tests'
ROOT = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NS, ROOT), (NS + '.routes', ROOT / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
auth = types.ModuleType(NS + '.routes.auth_routes')
auth.SECRET_KEY = 'instalacion-isolated-tests'
sys.modules[auth.__name__] = auth
models = importlib.import_module(NS + '.models')
db = importlib.import_module(NS + '.database').db
routes = importlib.import_module(NS + '.routes.instalaciones_routes')
actas = importlib.import_module(NS + '.routes.actas_routes')
historial = importlib.import_module(NS + '.routes.consultascentro_historial_routes')
filtro = importlib.import_module(NS + '.routes.filtro_routes')


class InstalacionManualTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('instalacion-manual-tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.instalaciones_blueprint, url_prefix='/api/instalaciones')
        cls.app.register_blueprint(actas.actas_blueprint, url_prefix='/api/actas')
        cls.app.register_blueprint(historial.consultascentro_historial_bp, url_prefix='/api/consultas_centro')
        cls.app.register_blueprint(filtro.filtro_blueprint, url_prefix='/api/filtro')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add(models.Cliente(id_cliente=1, nombre='Cliente prueba'))
        razon = models.RazonSocial(cliente_id=1, razon_social='Razon prueba')
        db.session.add(razon)
        db.session.flush()
        db.session.add_all([models.Centro(id_centro=i, nombre='Centro ' + str(i), cliente_id=1, razon_social_id=razon.id_razon_social) for i in (1, 2)])
        db.session.commit()
        self.folder = tempfile.TemporaryDirectory()
        self.cwd = patch.object(os, 'getcwd', return_value=self.folder.name)
        self.uploads = patch.object(routes, 'UPLOAD_FOLDER', str(Path(self.folder.name, 'uploads', 'instalaciones_docs')))
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

    def subir(self, nombre='acta.pdf', contenido=b'%PDF-1.4 prueba', centro='1', fecha='2026-11-25', **extra):
        data = {'centro_id': centro, 'fecha_instalacion': fecha, 'observacion': 'Sistema instalado'}
        data.update(extra)
        if nombre is not None:
            data['documento_acta'] = (io.BytesIO(contenido), nombre)
        return self.client.post('/api/actas/instalaciones', data=data)

    def test_manual_se_lista_por_centro_y_se_abre_desde_historial(self):
        self.assertEqual(self.subir().status_code, 201)
        self.assertEqual(self.client.get('/api/instalaciones/?centro_id=2').get_json(), [])
        listado = self.client.get('/api/instalaciones/?centro_id=1').get_json()
        self.assertEqual(len(listado), 1)
        self.assertTrue(listado[0]['documento_acta'])
        self.assertEqual(db.session.get(models.Centro, 1).fecha_instalacion, date(2026, 11, 25))
        item = self.client.get('/api/consultas_centro/centro_historial/1').get_json()['historial']['instalaciones'][0]
        self.assertEqual(item['documento'], '/api/filtro/documento/Instalaciones/' + str(listado[0]['id_instalacion']))
        self.assertIsNotNone(item['inicio_monitoreo'])
        response = self.client.get(item['documento'])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertTrue(response.headers['Content-Disposition'].startswith('inline'))
        self.assertEqual(response.data, b'%PDF-1.4 prueba')
        response.close()

    def test_actualizar_sin_archivo_conserva_respaldo_y_no_duplica(self):
        self.subir()
        antes = models.InstalacionNueva.query.one().documento_acta
        self.assertEqual(self.subir(nombre=None, fecha='2026-11-24').status_code, 201)
        item = models.InstalacionNueva.query.one()
        self.assertEqual(item.documento_acta, antes)
        self.assertEqual(item.fecha_instalacion, date(2026, 11, 24))
        self.assertTrue(Path(self.folder.name, 'uploads', antes).is_file())

    def test_agrega_documentos_con_fecha_propia_sin_reemplazar_original(self):
        primero = self.subir().get_json()['id_instalacion']
        original = db.session.get(models.InstalacionNueva, primero).documento_acta
        segundo = self.subir(fecha='2026-11-27', nuevo_documento='1').get_json()['id_instalacion']
        self.assertNotEqual(primero, segundo)
        self.assertEqual(models.InstalacionNueva.query.count(), 2)
        self.assertEqual(db.session.get(models.InstalacionNueva, primero).documento_acta, original)
        self.assertTrue(Path(self.folder.name, 'uploads', original).is_file())
        self.assertEqual(db.session.get(models.Centro, 1).fecha_instalacion, date(2026, 11, 25))
        listado = self.client.get('/api/instalaciones/?centro_id=1').get_json()
        self.assertEqual({r['fecha_instalacion'] for r in listado}, {'2026-11-25', '2026-11-27'})
        historial = self.client.get('/api/consultas_centro/centro_historial/1').get_json()['historial']['instalaciones']
        self.assertEqual(len(historial), 2)
        for item in historial:
            response = self.client.get(item['documento'])
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_edita_solo_el_documento_seleccionado_y_su_fecha(self):
        primero = self.subir().get_json()['id_instalacion']
        segundo = self.subir(nuevo_documento='1').get_json()['id_instalacion']
        anterior = db.session.get(models.InstalacionNueva, segundo).documento_acta
        self.assertEqual(self.subir(id_instalacion=str(segundo), fecha='2026-11-28').status_code, 201)
        self.assertEqual(db.session.get(models.InstalacionNueva, primero).fecha_instalacion, date(2026, 11, 25))
        self.assertEqual(db.session.get(models.InstalacionNueva, segundo).fecha_instalacion, date(2026, 11, 28))
        self.assertEqual(db.session.get(models.Centro, 1).fecha_instalacion, date(2026, 11, 25))
        self.assertFalse(Path(self.folder.name, 'uploads', anterior).exists())
        self.assertEqual(len(list(Path(routes.UPLOAD_FOLDER).iterdir())), 2)
        actual = db.session.get(models.InstalacionNueva, segundo).documento_acta
        self.assertEqual(self.subir(nombre=None, id_instalacion=str(segundo), observacion='Actualizado').status_code, 201)
        self.assertEqual(db.session.get(models.InstalacionNueva, segundo).documento_acta, actual)
        self.assertEqual(db.session.get(models.InstalacionNueva, segundo).observacion, 'Actualizado')

    def test_no_edita_registros_de_otro_centro_ni_agrega_sin_documento(self):
        registro = self.subir().get_json()['id_instalacion']
        self.assertEqual(self.subir(centro='2', id_instalacion=str(registro)).status_code, 404)
        self.assertEqual(self.subir(id_instalacion='999').status_code, 404)
        self.assertEqual(self.subir(id_instalacion='invalido').status_code, 400)
        self.assertEqual(self.subir(nombre=None, nuevo_documento='1').status_code, 400)
        self.assertEqual(self.subir(id_instalacion=str(registro), nuevo_documento='1').status_code, 400)
        self.assertEqual(models.InstalacionNueva.query.count(), 1)
        self.assertEqual(len(list(Path(routes.UPLOAD_FOLDER).iterdir())), 1)

    def test_error_al_agregar_no_afecta_documentos_anteriores(self):
        self.subir()
        original = models.InstalacionNueva.query.one().documento_acta
        with patch.object(db.session, 'commit', side_effect=RuntimeError('Error de prueba')):
            self.assertEqual(self.subir(nuevo_documento='1').status_code, 400)
        self.assertEqual(models.InstalacionNueva.query.one().documento_acta, original)
        self.assertEqual(len(list(Path(routes.UPLOAD_FOLDER).iterdir())), 1)

    def test_reemplazo_usa_nombre_unico_y_elimina_anterior_despues_de_confirmar(self):
        self.subir()
        antes = models.InstalacionNueva.query.one().documento_acta
        self.assertEqual(self.subir().status_code, 201)
        nuevo = models.InstalacionNueva.query.one().documento_acta
        self.assertNotEqual(antes, nuevo)
        self.assertFalse(Path(self.folder.name, 'uploads', antes).exists())
        self.assertTrue(Path(self.folder.name, 'uploads', nuevo).exists())

    def test_error_bd_conserva_original_y_limpia_nuevo_archivo(self):
        self.subir()
        antes = models.InstalacionNueva.query.one().documento_acta
        with patch.object(db.session, 'commit', side_effect=RuntimeError('Error de prueba')):
            self.assertEqual(self.subir().status_code, 400)
        self.assertEqual(models.InstalacionNueva.query.one().documento_acta, antes)
        self.assertEqual(len(list(Path(routes.UPLOAD_FOLDER).iterdir())), 1)

    def test_archivo_invalido_no_crea_ni_modifica_instalacion(self):
        for nombre, contenido in [('archivo.exe', b'x'), ('vacio.pdf', b''), ('grande.pdf', b'x' * (routes.MAX_DOCUMENTO_BYTES + 1))]:
            self.assertEqual(self.subir(nombre=nombre, contenido=contenido).status_code, 400)
        self.assertEqual(models.InstalacionNueva.query.count(), 0)
        self.assertIsNone(db.session.get(models.Centro, 1).fecha_instalacion)

    def test_fecha_y_centro_invalidos_no_guardan_archivo(self):
        self.assertEqual(self.subir(centro='999').status_code, 404)
        self.assertEqual(self.subir(fecha='invalid').status_code, 400)
        self.assertFalse(Path(routes.UPLOAD_FOLDER).exists())

    def test_png_se_abre_con_mime_correcto_y_no_como_jpeg(self):
        self.subir(nombre='plano.PNG', contenido=b'png de prueba')
        item = models.InstalacionNueva.query.one()
        response = self.client.get(f'/api/filtro/documento/Instalaciones/{item.id_instalacion}')
        self.assertEqual(response.mimetype, 'image/png')
        response.close()

    def test_abrir_documento_no_requiere_api_path_de_python_39(self):
        self.subir()
        item = models.InstalacionNueva.query.one()
        with patch.object(Path, 'is_relative_to', side_effect=AttributeError('No disponible en Python 3.8'), create=True):
            response = self.client.get(f'/api/filtro/documento/Instalaciones/{item.id_instalacion}')
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_documento_inexistente_o_fuera_de_uploads_es_404(self):
        self.assertEqual(self.client.get('/api/filtro/documento/Instalaciones/999').status_code, 404)
        self.subir(nombre=None)
        item = models.InstalacionNueva.query.one()
        endpoint = f'/api/filtro/documento/Instalaciones/{item.id_instalacion}'
        self.assertEqual(self.client.get(endpoint).status_code, 404)
        Path(self.folder.name, 'privado.pdf').write_bytes(b'privado')
        item.documento_acta = '../privado.pdf'
        db.session.commit()
        self.assertEqual(self.client.get(endpoint).status_code, 404)
        item.documento_acta = 'instalaciones_docs/borrado.pdf'
        db.session.commit()
        self.assertEqual(self.client.get(endpoint).status_code, 404)


if __name__ == '__main__':
    unittest.main()
