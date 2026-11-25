import importlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
from flask import Flask
from PIL import Image
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from werkzeug.datastructures import MultiDict

# No inicia la aplicacion real, ni usa archivos o base de datos de produccion.
NS = '_armado_observacion_tests'
ROOT = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NS, ROOT), (NS + '.routes', ROOT / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
socket = types.ModuleType(NS + '.socketio_ext')
socket.emit_armado_event, socket.emit_actividad_event = Mock(), Mock()
sys.modules[socket.__name__] = socket
models = importlib.import_module(NS + '.models')
db = importlib.import_module(NS + '.database').db
routes = importlib.import_module(NS + '.routes.armado_observacion_routes')
armados = importlib.import_module(NS + '.routes.armados_routes')
TEST_KEY = 'armado-observacion-solo-pruebas'
armados.SECRET_KEY = TEST_KEY


def imagen(nombre='foto.png'):
    data = io.BytesIO()
    Image.new('RGB', (24, 16), 'blue').save(data, format='PNG')
    data.seek(0)
    return data, nombre


class ArmadoObservacionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('armado-observacion-tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.armado_observacion_blueprint, url_prefix='/armados')
        cls.app.register_blueprint(armados.armados_blueprint, url_prefix='/armados')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        self.folder = tempfile.TemporaryDirectory()
        self.app.config['ARMADO_OBSERVACIONES_UPLOAD_FOLDER'] = self.folder.name
        db.create_all()
        db.session.add_all([models.User(id=i, name=role, rol=role, email=role + '@example.test', password_hash='test')
                            for i, role in [(1, 'admin'), (2, 'tecnico'), (3, 'finanzas'), (4, 'inventario')]])
        role = models.Role(nombre='inventario')
        db.session.add(role)
        db.session.flush()
        db.session.add(models.RolePage(role_id=role.id_role, page_key='armados'))
        db.session.add(models.Cliente(id_cliente=1, nombre='Cliente de prueba'))
        razon = models.RazonSocial(cliente_id=1, razon_social='Cliente SPA')
        db.session.add(razon)
        db.session.flush()
        db.session.add(models.Centro(id_centro=1, nombre='Centro', cliente_id=1, razon_social_id=razon.id_razon_social))
        db.session.add_all([models.Armado(id_armado=i, centro_id=1, tecnico_id=2, observacion='Original', estado='en_proceso') for i in (1, 2)])
        db.session.commit()
        socket.emit_armado_event.reset_mock()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.folder.cleanup()

    def headers(self, uid=1):
        return {'Authorization': 'Bearer ' + jwt.encode({'user_id': uid, 'rol': 'admin'}, TEST_KEY, algorithm='HS256')}

    def guardar(self, data=None, uid=1):
        return self.client.put('/armados/1/observacion', data=data or {'observacion': 'Actualizada'},
                               content_type='multipart/form-data', headers=self.headers(uid))

    def listado(self):
        return self.client.get('/armados/1/observacion', headers=self.headers()).get_json()

    def archivos(self):
        return sorted(Path(self.folder.name).iterdir())

    def test_texto_sin_imagenes_conserva_el_comportamiento_y_no_cambia_estado(self):
        self.assertEqual(self.guardar().status_code, 200)
        self.assertEqual(self.listado()['observacion'], 'Actualizada')
        self.assertEqual(self.listado()['imagenes'], [])
        self.assertEqual(db.session.get(models.Armado, 1).estado, 'en_proceso')
        socket.emit_armado_event.assert_called_once()

    def test_guarda_dos_imagenes_y_las_recupera_al_reabrir(self):
        response = self.guardar({'observacion': 'Respaldo del rack', 'imagen_1': imagen(), 'imagen_2': imagen('segunda.png')})
        self.assertEqual(response.status_code, 200, response.get_json())
        data = self.listado()
        self.assertEqual(data['observacion'], 'Respaldo del rack')
        self.assertEqual([i['posicion'] for i in data['imagenes']], [1, 2])
        self.assertEqual(len(self.archivos()), 2)
        for archivo in self.archivos():
            with Image.open(archivo) as img:
                self.assertEqual(img.format, 'JPEG')
        self.assertNotIn('archivo', data['imagenes'][0])

    def test_guarda_titulos_independientes_con_cada_imagen(self):
        response = self.guardar({'imagen_1': imagen(), 'imagen_2': imagen(),
                                 'titulo_1': 'Plano del sistema', 'titulo_2': '  Interior   del rack  '})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([i['nombre'] for i in self.listado()['imagenes']], ['Plano del sistema', 'Interior del rack'])

    def test_renombrar_no_requiere_subir_la_imagen_ni_modifica_el_archivo(self):
        self.guardar({'imagen_1': imagen(), 'titulo_1': 'Plano anterior'})
        previos = self.archivos()
        contenido = previos[0].read_bytes()
        response = self.guardar({'titulo_1': 'Plano del sistema actualizado'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.listado()['imagenes'][0]['nombre'], 'Plano del sistema actualizado')
        self.assertEqual(self.archivos(), previos)
        self.assertEqual(previos[0].read_bytes(), contenido)

    def test_titulo_opcional_y_reemplazo_conservan_el_nombre_enviado(self):
        self.guardar({'imagen_1': imagen(), 'titulo_1': ''})
        self.assertEqual(self.listado()['imagenes'][0]['nombre'], 'foto.png')
        self.guardar({'imagen_1': imagen('reemplazo.png'), 'titulo_1': 'Plano del sistema'})
        self.assertEqual(self.listado()['imagenes'][0]['nombre'], 'Plano del sistema')
        self.guardar({'titulo_1': ''})
        self.assertEqual(self.listado()['imagenes'][0]['nombre'], 'Imagen 1')

    def test_titulo_demasiado_largo_o_sin_imagen_no_guarda_cambios_parciales(self):
        for data in [{'imagen_1': imagen(), 'titulo_1': 'x' * 201},
                     {'titulo_1': 'Sin imagen'}, {'imagen_1': imagen(), 'titulo_2': 'Sin segunda imagen'},
                     MultiDict([('titulo_1', 'Uno'), ('titulo_1', 'Dos')])]:
            self.assertEqual(self.guardar(data).status_code, 400)
            self.assertEqual(self.archivos(), [])
            self.assertEqual(self.listado()['observacion'], 'Original')

    def test_error_de_guardado_conserva_el_titulo_anterior(self):
        self.guardar({'imagen_1': imagen(), 'titulo_1': 'Original'})
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('simulated')):
            response = self.guardar({'titulo_1': 'No guardar'})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.listado()['imagenes'][0]['nombre'], 'Original')

    def test_editar_solo_texto_preserva_las_imagenes_y_permite_vaciar_texto(self):
        self.guardar({'imagen_1': imagen()})
        archivos = self.archivos()
        self.assertEqual(self.guardar({'observacion': ''}).status_code, 200)
        self.assertEqual(self.listado()['observacion'], '')
        self.assertEqual(self.archivos(), archivos)
        self.assertEqual(len(self.listado()['imagenes']), 1)

    def test_reemplazar_y_quitar_elimina_solo_los_archivos_confirmados(self):
        self.guardar({'imagen_1': imagen(), 'imagen_2': imagen()})
        previos = {i.posicion: i.archivo for i in models.ArmadoObservacionImagen.query.all()}
        response = self.guardar({'imagen_1': imagen('nueva.png'), 'eliminar_2': 'true'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(self.listado()['imagenes']), 1)
        self.assertEqual(self.listado()['imagenes'][0]['nombre'], 'nueva.png')
        self.assertEqual(len(self.archivos()), 1)
        self.assertFalse(any(Path(self.folder.name, nombre).exists() for nombre in previos.values()))

    def test_rechaza_tercera_imagen_y_campos_repetidos_sin_cambios_parciales(self):
        for data in [{'imagen_1': imagen(), 'imagen_3': imagen()},
                     MultiDict([('imagen_1', imagen()), ('imagen_1', imagen())]),
                     MultiDict([('observacion', 'Uno'), ('observacion', 'Dos')]),
                     {'imagen_1': imagen(), 'eliminar_1': 'true'}, {'eliminar_1': 'si'}]:
            self.assertEqual(self.guardar(data).status_code, 400)
            self.assertEqual(self.listado()['observacion'], 'Original')
            self.assertEqual(self.archivos(), [])

    def test_valida_contenido_no_solo_extension_y_no_guarda_la_primera_si_falla_la_segunda(self):
        response = self.guardar({'observacion': 'No guardar', 'imagen_1': imagen(),
                                 'imagen_2': (io.BytesIO(b'<script>no es una imagen</script>'), 'falsa.jpg')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.listado()['observacion'], 'Original')
        self.assertEqual(self.archivos(), [])
        self.assertEqual(self.guardar({'imagen_1': imagen('no.svg')}).status_code, 400)

    def test_limite_de_peso_por_imagen(self):
        with patch.object(routes, 'MAX_IMAGEN', 10):
            response = self.guardar({'imagen_1': imagen()})
        self.assertEqual(response.status_code, 400)
        self.assertIn('5 MB', response.get_json()['message'])
        self.assertEqual(self.archivos(), [])

    def test_error_de_base_de_datos_conserva_la_imagen_anterior_y_limpia_la_nueva(self):
        self.guardar({'imagen_1': imagen()})
        previos = self.archivos()
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('simulated')):
            response = self.guardar({'observacion': 'No guardar', 'imagen_1': imagen('nueva.png')})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(self.listado()['observacion'], 'Original')
        self.assertEqual(self.archivos(), previos)
        self.assertEqual(self.listado()['imagenes'][0]['nombre'], 'foto.png')

    def test_lectura_y_escritura_respetan_cuenta_real_y_permisos(self):
        self.assertEqual(self.client.get('/armados/1/observacion').status_code, 401)
        for uid in (2, 3, 999):
            self.assertIn(self.guardar(uid=uid).status_code, (401, 403))
            self.assertIn(self.client.get('/armados/1/observacion', headers=self.headers(uid)).status_code, (401, 403))
        self.assertEqual(self.guardar(uid=4).status_code, 200)

    def test_imagen_privada_y_no_permite_mezclar_armados(self):
        self.guardar({'imagen_1': imagen()})
        iid = self.listado()['imagenes'][0]['id_imagen']
        url = f'/armados/1/observacion/imagenes/{iid}'
        self.assertEqual(self.client.get(url).status_code, 401)
        self.assertEqual(self.client.get(url, headers=self.headers(2)).status_code, 403)
        response = self.client.get(url, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/jpeg')
        self.assertIn('no-store', response.headers['Cache-Control'])
        response.close()
        self.assertEqual(self.client.get(f'/armados/2/observacion/imagenes/{iid}', headers=self.headers()).status_code, 404)

    def test_eliminar_armado_limpia_sus_imagenes_y_no_afecta_otro(self):
        self.guardar({'imagen_1': imagen()})
        response = self.client.delete('/armados/1', headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(models.ArmadoObservacionImagen.query.count(), 0)
        self.assertEqual(self.archivos(), [])
        self.assertIsNotNone(db.session.get(models.Armado, 2))

    def test_base_de_datos_impide_una_tercera_posicion(self):
        db.session.add(models.ArmadoObservacionImagen(armado_id=1, posicion=3, archivo='no.jpg', nombre='no.jpg'))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_armado_inexistente_y_archivo_inexistente_no_simulan_exito(self):
        self.assertEqual(self.client.get('/armados/999/observacion', headers=self.headers()).status_code, 404)
        self.guardar({'imagen_1': imagen()})
        data = self.listado()['imagenes'][0]
        self.archivos()[0].unlink()
        self.assertEqual(self.client.get(f"/armados/1/observacion/imagenes/{data['id_imagen']}", headers=self.headers()).status_code, 404)
