import importlib
import sys
import types
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
from flask import Flask
from sqlalchemy.exc import SQLAlchemyError

# Importacion aislada: no inicia el backend real ni usa su base de datos o SMTP.
NS = '_asignacion_correo_tests'
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
correo = importlib.import_module(NS + '.asignacion_correo')
smtp = importlib.import_module(NS + '.soporte_correo')
actividades = importlib.import_module(NS + '.routes.actividades_routes')
armados = importlib.import_module(NS + '.routes.armados_routes')
TEST_KEY = 'asignacion-solo-pruebas-sin-credenciales-reales'
actividades.JWT_KEYS, armados.SECRET_KEY = [TEST_KEY], TEST_KEY


class AsignacionCorreoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('asignacion-correo-tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False, SECRET_KEY=TEST_KEY,
            SMTP_HOST='smtp.example.test', SMTP_PORT=587, SMTP_FROM='avisos@example.test',
            SMTP_USERNAME='avisos@example.test', SMTP_PASSWORD='solo-pruebas',
            SMTP_USE_TLS=True, SMTP_USE_SSL=False, SOPORTE_TERRENO_DESTINATARIOS='soporte@example.test')
        db.init_app(cls.app)
        cls.app.register_blueprint(actividades.actividades_blueprint, url_prefix='/actividades')
        cls.app.register_blueprint(armados.armados_blueprint, url_prefix='/armados')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add(models.Cliente(id_cliente=1, nombre='Cliente de prueba'))
        razon = models.RazonSocial(cliente_id=1, razon_social='Cliente SPA')
        db.session.add(razon)
        db.session.flush()
        db.session.add(models.Centro(id_centro=1, nombre='Centro de prueba', cliente_id=1, razon_social_id=razon.id_razon_social))
        db.session.add_all([models.User(id=i, name=nombre, email=email, rol=rol, password_hash='prueba')
            for i, nombre, email, rol in [(1, 'Admin', 'admin@example.test', 'admin'),
                (2, 'Principal', 'principal@example.test', 'tecnico'), (3, 'Apoyo', 'apoyo@example.test', 'tecnico'),
                (4, 'Extra', 'extra@example.test', 'tecnico'), (5, 'Solo lectura', 'lector@example.test', 'finanzas')]])
        db.session.add_all([models.Encargado(id_encargado=i, user_id=uid, nombre_encargado=nombre)
            for i, uid, nombre in [(12, 2, 'Principal'), (13, 3, 'Apoyo'), (14, 4, 'Extra'), (15, None, 'Principal sin cuenta')]])
        db.session.commit()
        self.client = self.app.test_client()
        self.payload = dict(nombre_actividad='Instalar equipos', centro_id=1, area='Instalacion',
            estado='Pendiente', prioridad='Alta', fecha_inicio='2026-11-24', tecnico_encargado=12,
            tecnico_ayudante=13, tecnicos_adicionales=[14, 12], notificar_por_correo=True)
        self.patch_sender = patch.object(correo, 'enviar_email')
        self.sender = self.patch_sender.start()
        socket.emit_actividad_event.reset_mock()
        socket.emit_armado_event.reset_mock()

    def tearDown(self):
        self.patch_sender.stop()
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def headers(self, uid=1):
        return {'Authorization': 'Bearer ' + jwt.encode({'user_id': uid, 'rol': 'admin'}, TEST_KEY, algorithm='HS256')}

    def crear(self, **changes):
        response = self.client.post('/actividades/', json={**self.payload, **changes}, headers=self.headers())
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()

    def editar(self, aid, **changes):
        return self.client.put('/actividades/' + str(aid), json=changes, headers=self.headers())

    def test_notifica_titular_apoyo_y_adicionales_por_cuenta_no_por_id_de_encargado(self):
        data = self.crear()
        self.assertEqual(data['aviso_correo']['estado'], 'enviado')
        mensaje, config = self.sender.call_args.args
        self.assertEqual(config['recipients'], ['apoyo@example.test', 'extra@example.test', 'principal@example.test'])
        self.assertNotIn('soporte@example.test', config['recipients'])
        self.assertNotIn('admin@example.test', config['recipients'])
        self.assertIn('#' + str(data['id_actividad']), mensaje['Subject'])
        self.assertIn('24/11/2026', mensaje.get_body(preferencelist=('plain',)).get_content())
        self.assertEqual(len(mensaje.get_all('To')), 1)
        self.assertEqual(models.AsignacionAvisoCorreo.query.one().estado, 'enviado')
        socket.emit_actividad_event.assert_called_once()

    def test_sin_checkbox_conserva_el_flujo_y_las_notificaciones_moviles(self):
        data = self.crear(notificar_por_correo=False)
        self.assertNotIn('aviso_correo', data)
        self.sender.assert_not_called()
        self.assertEqual(models.AsignacionAvisoCorreo.query.count(), 0)
        socket.emit_actividad_event.assert_called_once()

    def test_editar_no_notifica_implicitamente_y_un_aviso_identico_no_se_duplica(self):
        aid = self.crear()['id_actividad']
        self.editar(aid)
        response = self.editar(aid, notificar_por_correo=True)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['aviso_correo']['duplicado'])
        self.sender.assert_called_once()
        self.assertEqual(models.AsignacionAvisoCorreo.query.count(), 1)
        self.editar(aid, nombre_actividad='Descripcion corregida')
        self.sender.assert_called_once()

    def test_valida_sesion_permiso_y_booleano_antes_de_crear_o_editar(self):
        for headers, codigo in [({}, 401), (self.headers(5), 403), (self.headers(999), 401)]:
            self.assertEqual(self.client.post('/actividades/', json=self.payload, headers=headers).status_code, codigo)
        self.assertEqual(self.client.post('/actividades/', json={**self.payload, 'notificar_por_correo': 'si'}, headers=self.headers()).status_code, 400)
        self.assertEqual(models.Actividad.query.count(), 0)
        aid = self.crear(notificar_por_correo=False)['id_actividad']
        self.assertEqual(self.client.put(f'/actividades/{aid}', json={'notificar_por_correo': True, 'nombre_actividad': 'No autorizado'}, headers=self.headers(5)).status_code, 403)
        self.assertEqual(db.session.get(models.Actividad, aid).nombre_actividad, 'Instalar equipos')
        self.sender.assert_not_called()

    def test_cuenta_no_vinculada_no_se_adivina_por_nombre(self):
        data = self.crear(tecnico_encargado=15, tecnico_ayudante=None, tecnicos_adicionales=[])
        self.assertEqual(data['aviso_correo']['estado'], 'sin_destinatarios')
        self.assertEqual(data['aviso_correo']['sin_correo'], ['Principal sin cuenta'])
        self.assertEqual(models.Actividad.query.count(), 1)
        self.sender.assert_not_called()

    def test_un_correo_invalido_avisa_sin_impedir_el_envio_a_los_demas(self):
        db.session.get(models.User, 2).email = 'sin-correo'
        db.session.commit()
        data = self.crear()['aviso_correo']
        self.assertEqual(data['estado'], 'enviado')
        self.assertEqual(data['sin_correo'], ['Principal'])
        self.assertEqual(data['destinatarios'], ['apoyo@example.test', 'extra@example.test'])

    def test_smtp_falla_pero_la_actividad_esta_guardada_y_se_puede_reintentar_sin_recrearla(self):
        self.sender.side_effect = correo.AvisoCorreoError('No se pudo conectar.')
        data = self.crear()
        self.assertEqual(data['aviso_correo']['estado'], 'error')
        self.assertEqual(models.Actividad.query.count(), 1)
        self.sender.side_effect = None
        retry = self.editar(data['id_actividad'], notificar_por_correo=True)
        self.assertEqual(retry.get_json()['aviso_correo']['estado'], 'enviado')
        self.assertEqual(models.AsignacionAvisoCorreo.query.count(), 1)
        self.assertEqual(models.Actividad.query.count(), 1)

    def test_no_reenvia_si_esta_enviando_parcial_o_incierto(self):
        aid = self.crear()['id_actividad']
        for estado in ('enviando', 'parcial', 'incierto'):
            aviso = models.AsignacionAvisoCorreo.query.one()
            aviso.estado = estado
            db.session.commit()
            response = self.editar(aid, notificar_por_correo=True)
            self.assertEqual(response.get_json()['aviso_correo']['estado'], estado)
        self.sender.assert_called_once()

    def test_sin_smtp_informa_error_sin_perder_la_asignacion(self):
        with patch.dict(self.app.config, SMTP_HOST=''):
            data = self.crear()
        self.assertEqual(data['aviso_correo']['estado'], 'error')
        self.assertEqual(models.Actividad.query.count(), 1)
        self.sender.assert_not_called()

    def test_no_envia_si_el_guardado_de_la_actividad_falla(self):
        with patch.object(db.session, 'commit', side_effect=SQLAlchemyError('simulated')):
            with self.assertRaises(SQLAlchemyError):
                self.crear()
        db.session.rollback()
        self.assertEqual(models.Actividad.query.count(), 0)
        self.sender.assert_not_called()

    def test_fallo_al_registrar_aviso_no_deshace_el_trabajo_ya_guardado(self):
        commit = db.session.commit
        intentos = []

        def falla_segundo_commit():
            intentos.append(1)
            if len(intentos) == 2:
                raise SQLAlchemyError('simulated')
            return commit()

        with patch.object(db.session, 'commit', side_effect=falla_segundo_commit):
            data = self.crear()
        self.assertEqual(data['aviso_correo']['estado'], 'error')
        self.assertEqual(models.Actividad.query.count(), 1)
        self.sender.assert_not_called()

    def test_asignar_armado_notifica_a_todos_los_participantes(self):
        data = dict(centro_id=1, tecnico_id=2, tecnicos_ids=[2, 3, 2], observacion='Preparar rack',
                    fecha_inicio='2026-11-24', notificar_por_correo=True)
        response = self.client.post('/armados/', json=data, headers=self.headers())
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()['aviso_correo']['destinatarios'], ['apoyo@example.test', 'principal@example.test'])
        self.assertEqual(models.ArmadoParticipacion.query.count(), 2)
        self.assertEqual(models.AsignacionAvisoCorreo.query.one().armado_id, response.get_json()['id_armado'])
        socket.emit_armado_event.assert_called_once()

    def test_no_basta_ver_el_armado_propio_para_enviar_asignaciones_por_correo(self):
        data = dict(centro_id=1, tecnico_id=2, notificar_por_correo=True)
        for headers, codigo in [({}, 401), (self.headers(2), 403), (self.headers(5), 403)]:
            response = self.client.post('/armados/', json=data, headers=headers)
            self.assertEqual(response.status_code, codigo)
        self.assertEqual(models.Armado.query.count(), 0)
        self.sender.assert_not_called()

    def test_armado_no_envia_a_participaciones_finalizadas(self):
        armado = models.Armado(centro_id=1, tecnico_id=2, fecha_asignacion=date(2026, 11, 24))
        db.session.add(armado)
        db.session.flush()
        db.session.add_all([models.ArmadoParticipacion(armado_id=armado.id_armado, tecnico_id=2),
                            models.ArmadoParticipacion(armado_id=armado.id_armado, tecnico_id=3, fecha_fin=date(2026, 11, 23))])
        db.session.commit()
        result = correo.notificar_asignacion(armado, 'armado', db.session.get(models.User, 1))
        self.assertEqual(result['destinatarios'], ['principal@example.test'])

    def test_plantilla_escapa_contenido_y_los_encabezados_no_admiten_saltos(self):
        data = self.crear(nombre_actividad='<script>alert(1)</script>\nRevisar energia', area='Mantencion\nUrgente')
        mensaje, _ = self.sender.call_args.args
        html = mensaje.get_body(preferencelist=('html',)).get_content()
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('OrcaGest', html)
        self.assertIn('#' + str(data['id_actividad']), html)
        self.assertNotIn('\n', str(mensaje['Subject']))

    def test_configuracion_compartida_no_cambia_los_destinatarios_de_soporte(self):
        self.assertEqual(smtp.configuracion_correo()['recipients'], ['soporte@example.test'])
        self.assertEqual(smtp.configuracion_correo(['principal@example.test'])['recipients'], ['principal@example.test'])
        self.assertEqual(smtp.configuracion_correo()['recipients'], ['soporte@example.test'])
