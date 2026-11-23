import importlib
import io
import tempfile
import sys
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import jwt
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

# Namespace aislado: nunca inicia la aplicacion ni conecta a produccion.
NS = '_mantencion_intervenciones_tests'
ROOT = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NS, ROOT), (NS + '.routes', ROOT / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
auth = types.ModuleType(NS + '.routes.auth_routes')
auth.SECRET_KEY = 'mantencion-isolated-tests'
sys.modules[auth.__name__] = auth
models = importlib.import_module(NS + '.models')
db = importlib.import_module(NS + '.database').db
service = importlib.import_module(NS + '.mantencion_intervenciones')
routes = importlib.import_module(NS + '.routes.mantencion_intervenciones_routes')
historial = importlib.import_module(NS + '.routes.consultascentro_historial_routes')
actas = importlib.import_module(NS + '.routes.actas_routes')
manuales = importlib.import_module(NS + '.routes.mantenciones_routes')


class IntervencionesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('mantenciones-tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.mantencion_intervenciones_bp, url_prefix='/api/intervenciones-mantencion')
        cls.app.register_blueprint(historial.consultascentro_historial_bp, url_prefix='/api/consultas_centro')
        cls.app.register_blueprint(actas.actas_blueprint, url_prefix='/api/actas')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add(models.Cliente(id_cliente=1, nombre='Cliente prueba'))
        razon = models.RazonSocial(cliente_id=1, razon_social='Razon prueba')
        db.session.add(razon)
        db.session.flush()
        db.session.add_all([models.Centro(id_centro=i, nombre='Centro ' + str(i), cliente_id=1, razon_social_id=razon.id_razon_social) for i in (1, 2)])
        db.session.add_all([models.User(id=1, name='Admin', email='a@example.test', password_hash='test', rol='admin'),
                            models.User(id=2, name='Lector', email='l@example.test', password_hash='test', rol='finanzas')])
        db.session.add_all([models.Soporte(id_soporte=i, centro_id=1 if i < 4 else 2, tipo='remoto' if i == 3 else 'terreno',
                                          problema='Problema ' + str(i), fecha_soporte=date(2026, 11, 23)) for i in (1, 2, 3, 4)])
        db.session.add_all([models.Mantencion(id_mantencion=i, centro_id=2 if i == 12 else 1, fecha_mantencion=date(2026, 11, 23),
                                             responsable='Tecnico', documento_mantencion=None if i == 13 else 'archivo.pdf') for i in (11, 12, 13)])
        db.session.add_all([models.MantencionTerreno(id_mantencion_terreno=i, centro_id=2 if i == 22 else 1,
                                                    fecha_ingreso=date(2026, 11, 23)) for i in (21, 22)])
        db.session.commit()
        self.client = self.app.test_client()
        token = jwt.encode({'user_id': 1, 'exp': datetime.now(timezone.utc) + timedelta(hours=1)}, auth.SECRET_KEY, algorithm='HS256')
        self.headers = {'Authorization': 'Bearer ' + token}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def datos(self):
        return self.client.get('/api/intervenciones-mantencion/centros/1').get_json()

    def link(self, tipo='manual', did=11, soporte=1, headers=None):
        return self.client.post('/api/intervenciones-mantencion/soportes/%s/documentos' % soporte,
                                json={'tipo': tipo, 'documento_id': did}, headers=self.headers if headers is None else headers)

    def subir(self, soporte=1, headers=None, nombre='informe.pdf'):
        data = {'centro_id': '1', 'fecha_mantencion': '2026-11-23',
                'responsable': 'Tecnico', 'observacion': 'Trabajo realizado',
                'documento_mantencion': (io.BytesIO(b'archivo de prueba'), nombre)}
        if soporte is not None:
            data['soporte_id'] = str(soporte)
        return self.client.post('/api/actas/mantenciones', data=data,
                                headers=self.headers if headers is None else headers)

    def test_adjunta_y_vincula_manual_en_una_transaccion(self):
        antes = self.datos()['resumen']['intervenciones']
        with tempfile.TemporaryDirectory() as folder, patch.object(manuales, 'UPLOAD_FOLDER', folder):
            response = self.subir()
            self.assertEqual(response.status_code, 201)
            mid = response.get_json()['id_mantencion']
            vinculo = models.SoporteDocumentoMantencion.query.one()
            self.assertEqual(vinculo.mantencion_id, mid)
            self.assertEqual(vinculo.soporte_id, 1)
            self.assertEqual(vinculo.creado_por_id, 1)
            self.assertEqual(len(list(Path(folder).iterdir())), 1)
            self.assertEqual(self.datos()['resumen']['intervenciones'], antes)
            self.assertEqual(self.datos()['resumen']['sin_documento'], 1)

    def test_adjuntar_valida_destino_permisos_y_archivo_antes_de_guardar(self):
        antes = models.Mantencion.query.count()
        token = jwt.encode({'user_id': 2, 'rol': 'admin'}, auth.SECRET_KEY, algorithm='HS256')
        with tempfile.TemporaryDirectory() as folder, patch.object(manuales, 'UPLOAD_FOLDER', folder):
            for sid in (3, 4, 999, 'abc', '-1'):
                self.assertEqual(self.subir(soporte=sid).status_code, 400)
            self.assertEqual(self.subir(headers={}).status_code, 401)
            self.assertEqual(self.subir(headers={'Authorization': 'Bearer ' + token}).status_code, 403)
            self.assertEqual(self.subir(nombre='archivo.exe').status_code, 400)
            self.assertEqual(models.Mantencion.query.count(), antes)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_error_al_guardar_manual_no_deja_archivo_registro_ni_vinculo(self):
        antes = models.Mantencion.query.count()
        with tempfile.TemporaryDirectory() as folder, patch.object(manuales, 'UPLOAD_FOLDER', folder):
            with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('simulated')):
                self.assertEqual(self.subir().status_code, 400)
            self.assertEqual(models.Mantencion.query.count(), antes)
            self.assertEqual(models.SoporteDocumentoMantencion.query.count(), 0)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_manual_sin_soporte_conserva_ingreso_independiente(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(manuales, 'UPLOAD_FOLDER', folder):
            self.assertEqual(self.subir(soporte=None).status_code, 201)
            self.assertEqual(models.SoporteDocumentoMantencion.query.count(), 0)

    def test_no_asocia_por_centro_fecha_ni_documentos_de_instalacion(self):
        db.session.add(models.ActaEntrega(centro_id=1, fecha_registro=date(2026, 11, 23)))
        db.session.commit()
        datos = self.datos()
        self.assertEqual(datos['resumen']['soportes'], 2)
        self.assertEqual(datos['resumen']['sin_documento'], 2)
        self.assertEqual(len(datos['disponibles']), 3)
        self.assertFalse(any(i.get('id_soporte') in (3, 4) for i in datos['items']))

    def test_vincula_manual_y_no_duplica_intervencion_ni_documento(self):
        antes = self.datos()['resumen']['intervenciones']
        self.assertEqual(self.link().status_code, 200)
        self.assertEqual(self.link().status_code, 200)
        datos = self.datos()
        self.assertEqual(datos['resumen']['intervenciones'], antes - 1)
        self.assertEqual(datos['resumen']['sin_documento'], 1)
        caso = next(i for i in datos['items'] if i.get('id_soporte') == 1)
        self.assertEqual(len(caso['documentos']), 1)
        self.assertFalse(caso['falta_documento'])
        self.assertEqual(models.SoporteDocumentoMantencion.query.count(), 1)

    def test_varios_documentos_siguen_siendo_una_intervencion(self):
        self.link()
        self.link('sistema', 21)
        caso = next(i for i in self.datos()['items'] if i.get('id_soporte') == 1)
        self.assertEqual(len(caso['documentos']), 2)
        self.assertEqual(self.datos()['resumen']['soportes'], 2)

    def test_un_manual_sin_archivo_no_respalda_el_soporte(self):
        self.assertEqual(self.link(did=13).status_code, 200)
        self.assertEqual(self.datos()['resumen']['sin_documento'], 2)

    def test_reconoce_referencia_explicita_por_actividad(self):
        actividad = models.Actividad(nombre_actividad='Mantencion', centro_id=1, soporte_id=1)
        db.session.add(actividad)
        db.session.flush()
        db.session.get(models.MantencionTerreno, 21).actividad_id = actividad.id_actividad
        db.session.commit()
        self.assertEqual(self.datos()['resumen']['sin_documento'], 1)
        self.assertEqual(self.link('sistema', 21).status_code, 200)
        self.assertEqual(models.SoporteDocumentoMantencion.query.count(), 0)
        self.assertEqual(self.link('sistema', 21, soporte=2).status_code, 409)

    def test_rechaza_documentos_de_otro_centro_y_soportes_remotos(self):
        for tipo, did in [('manual', 12), ('sistema', 22), ('manual', 999)]:
            self.assertEqual(self.link(tipo, did).status_code, 400)
        self.assertEqual(self.link(soporte=3).status_code, 400)
        self.assertEqual(models.SoporteDocumentoMantencion.query.count(), 0)

    def test_un_documento_no_puede_respaldar_dos_intervenciones(self):
        self.link()
        self.assertEqual(self.link(soporte=2).status_code, 409)

    def test_permisos_usan_usuario_real_y_no_el_rol_del_token(self):
        self.assertEqual(self.link(headers={}).status_code, 401)
        token = jwt.encode({'user_id': 2, 'rol': 'admin'}, auth.SECRET_KEY, algorithm='HS256')
        self.assertEqual(self.link(headers={'Authorization': 'Bearer ' + token}).status_code, 403)

    def test_valida_payload_y_no_acepta_booleanos_como_ids(self):
        for payload in [{'tipo': 'manual', 'documento_id': True}, {'tipo': 'manual', 'documento_id': '11'},
                        {'tipo': 'instalacion', 'documento_id': 11}, {}, []]:
            response = self.client.post('/api/intervenciones-mantencion/soportes/1/documentos', json=payload, headers=self.headers)
            self.assertEqual(response.status_code, 400)

    def test_desvincular_no_elimina_el_documento_y_restaura_aviso(self):
        self.link()
        vid = models.SoporteDocumentoMantencion.query.first().id
        self.assertEqual(self.client.delete('/api/intervenciones-mantencion/soportes/2/documentos/%s' % vid, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.delete('/api/intervenciones-mantencion/soportes/1/documentos/%s' % vid, headers=self.headers).status_code, 200)
        self.assertIsNotNone(db.session.get(models.Mantencion, 11))
        self.assertEqual(self.datos()['resumen']['sin_documento'], 2)

    def test_eliminar_documento_restaurara_falta_documento(self):
        self.link()
        db.session.delete(db.session.get(models.Mantencion, 11))
        db.session.commit()
        self.assertEqual(models.SoporteDocumentoMantencion.query.count(), 0)
        self.assertEqual(self.datos()['resumen']['sin_documento'], 2)

    def test_historial_usa_agrupacion_y_rollbacks_no_guardan_vinculos(self):
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('simulated')):
            self.assertEqual(self.link().status_code, 500)
        self.assertEqual(models.SoporteDocumentoMantencion.query.count(), 0)
        self.link()
        res = self.client.get('/api/consultas_centro/centro_historial/1')
        self.assertEqual(res.status_code, 200)
        items = res.get_json()['historial']['intervenciones_mantencion']
        self.assertEqual(len([i for i in items if i.get('id_soporte') == 1]), 1)

    def test_resumen_registros_documentos_es_el_mismo_del_historial(self):
        connection = db.engine.raw_connection()
        connection.create_function('concat', -1, lambda *args: ''.join(str(a) for a in args if a is not None))
        connection.close()
        self.link()
        with patch('builtins.print'):
            response = self.client.get('/api/actas/listar?id_centro=1')
        self.assertEqual(response.status_code, 200, response.get_json())
        rows = response.get_json()['actividades']
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row['resumen_intervenciones_mantencion'], self.datos()['resumen'])

    def test_normaliza_modalidad_terreno_sin_cambiar_datos(self):
        db.session.get(models.Soporte, 1).tipo = ' TERRENO '
        db.session.commit()
        self.assertEqual(self.datos()['resumen']['soportes'], 2)
        self.assertEqual(self.link().status_code, 200)
