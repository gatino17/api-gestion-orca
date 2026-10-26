import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
from flask import Flask
from sqlalchemy import create_engine, inspect, text


NAMESPACE = '_soporte_aviso_tests_app'
APP_PATH = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NAMESPACE, APP_PATH), (NAMESPACE + '.routes', APP_PATH / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
auth = types.ModuleType(NAMESPACE + '.routes.auth_routes')
auth.SECRET_KEY = 'soporte-isolated-tests-key'
sys.modules[auth.__name__] = auth
socket = types.ModuleType(NAMESPACE + '.socketio_ext')
socket.emit_soporte_event = Mock()
sys.modules[socket.__name__] = socket
models = importlib.import_module(NAMESPACE + '.models')
db = importlib.import_module(NAMESPACE + '.database').db
correo = importlib.import_module(NAMESPACE + '.soporte_correo')
schema = importlib.import_module(NAMESPACE + '.soporte_schema')
routes = importlib.import_module(NAMESPACE + '.routes.soporte_routes')


class SoporteAvisoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('soporte_aviso_tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False, SMTP_HOST='smtp.example.test', SMTP_PORT=587,
            SMTP_USERNAME='notificaciones@example.test', SMTP_PASSWORD='test-password',
            SMTP_FROM='notificaciones@example.test', SMTP_USE_TLS=True, SMTP_USE_SSL=False,
            SOPORTE_TERRENO_DESTINATARIOS='soporte@orcatecnologia.cl')
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.soporte_blueprint, url_prefix='/api/soporte')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        user = models.User(name='Tecnico Prueba', email='tecnico@example.test', password_hash='test', rol='tecnico')
        cliente = models.Cliente(nombre='Cliente Prueba')
        db.session.add_all([user, cliente])
        db.session.flush()
        razon = models.RazonSocial(cliente_id=cliente.id_cliente, razon_social='Cliente SPA')
        db.session.add(razon)
        db.session.flush()
        db.session.add(models.Centro(id_centro=1, nombre='Centro Prueba', area='Chiloe',
            cliente_id=cliente.id_cliente, razon_social_id=razon.id_razon_social))
        db.session.commit()
        self.headers = {'Authorization': 'Bearer ' + jwt.encode({'user_id': user.id}, auth.SECRET_KEY, algorithm='HS256')}
        self.client = self.app.test_client()
        self.payload = dict(centro_id=1, problema='Camara sin conexion', tipo='terreno', fecha_soporte='2026-10-26',
            sugerencia='Revisar energia y cableado', solucion='Sin intervencion aun', estado='pendiente', prioridad='alta')
        self.sender = patch.object(correo, 'enviar_mensaje')
        self.send = self.sender.start()

    def tearDown(self):
        self.sender.stop()
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def create(self, **changes):
        response = self.client.post('/api/soporte/', json={**self.payload, **changes}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.get_json())
        return response.get_json()['id_soporte']

    def notify(self, id_soporte):
        return self.client.post(f'/api/soporte/{id_soporte}/aviso-terreno', headers=self.headers)

    def test_persists_suggestion_separately_and_never_sends_implicitly(self):
        id_soporte = self.create(enviar_correo=True)
        self.client.put(f'/api/soporte/{id_soporte}', json={'prioridad': 'baja'}, headers=self.headers)
        row = self.client.get('/api/soporte/', headers=self.headers).get_json()[0]
        self.assertEqual(row['sugerencia'], self.payload['sugerencia'])
        self.assertEqual(row['solucion'], self.payload['solucion'])
        self.assertIsNone(row['aviso_terreno'])
        self.send.assert_not_called()

    def test_requires_session_for_edit_and_notification(self):
        id_soporte = self.create()
        self.assertEqual(self.client.post(f'/api/soporte/{id_soporte}/aviso-terreno').status_code, 401)
        self.assertEqual(self.client.put(f'/api/soporte/{id_soporte}', json={'sugerencia': 'Cambiar'}).status_code, 401)
        self.send.assert_not_called()

    def test_only_open_field_support_can_notify(self):
        for changes in [dict(tipo='remoto'), dict(estado='resuelto'), dict(fecha_cierre='2026-10-26')]:
            self.assertEqual(self.notify(self.create(**changes)).status_code, 409)
        self.send.assert_not_called()

    def test_empty_problem_or_suggestion_is_not_sent(self):
        for changes in [dict(sugerencia=' '), dict(problema=' ')]:
            self.assertEqual(self.notify(self.create(**changes)).status_code, 400)
        self.send.assert_not_called()

    def test_validates_suggestion_on_create_and_edit(self):
        id_soporte = self.create()
        for value in [['No es texto'], 'x' * 10001]:
            response = self.client.post('/api/soporte/', json={**self.payload, 'sugerencia': value}, headers=self.headers)
            self.assertEqual(response.status_code, 400)
            response = self.client.put(f'/api/soporte/{id_soporte}', json={'sugerencia': value}, headers=self.headers)
            self.assertEqual(response.status_code, 400)

    def test_sends_to_configured_address_with_problem_suggestion_and_author(self):
        id_soporte = self.create(estado='en_proceso')
        response = self.notify(id_soporte)
        self.assertEqual(response.status_code, 200, response.get_json())
        contenido, config, _message_id, author = self.send.call_args.args
        self.assertEqual(config['recipients'], ['soporte@orcatecnologia.cl'])
        self.assertEqual(contenido['problema'], self.payload['problema'])
        self.assertEqual(contenido['sugerencia'], self.payload['sugerencia'])
        self.assertEqual(contenido['cliente'], 'Cliente Prueba')
        self.assertEqual(contenido['creado_por'], 'Tecnico Prueba')
        self.assertEqual(author, 'Tecnico Prueba')
        aviso = self.client.get('/api/soporte/').get_json()[0]['aviso_terreno']
        self.assertEqual(aviso['estado'], 'enviado')
        self.assertTrue(aviso['fecha_envio'])
        self.assertNotIn('SMTP_PASSWORD', str(response.get_json()))

    def test_double_request_does_not_send_twice(self):
        id_soporte = self.create()
        self.assertEqual(self.notify(id_soporte).status_code, 200)
        self.assertEqual(self.notify(id_soporte).status_code, 200)
        self.send.assert_called_once()
        self.assertEqual(models.SoporteAvisoTerreno.query.count(), 1)

    def test_failed_mail_keeps_support_and_retry_only_retries_mail(self):
        id_soporte = self.create()
        self.send.side_effect = correo.AvisoCorreoError('No se pudo conectar.')
        self.assertEqual(self.notify(id_soporte).status_code, 502)
        self.assertEqual(models.Soporte.query.count(), 1)
        self.assertEqual(models.SoporteAvisoTerreno.query.one().estado, 'error')
        message_id = self.send.call_args.args[2]
        self.send.side_effect = None
        self.assertEqual(self.notify(id_soporte).status_code, 200)
        self.assertEqual(self.send.call_args.args[2], message_id)
        self.assertEqual(models.SoporteAvisoTerreno.query.count(), 1)
        self.assertEqual(models.Soporte.query.count(), 1)

    def test_concurrent_or_uncertain_delivery_is_not_resent(self):
        id_soporte = self.create()
        self.notify(id_soporte)
        aviso = models.SoporteAvisoTerreno.query.one()
        for state in ['enviando', 'incierto', 'parcial']:
            aviso.estado = state
            db.session.commit()
            self.send.reset_mock()
            self.assertEqual(self.notify(id_soporte).status_code, 409)
            self.send.assert_not_called()

    def test_explicit_notification_after_changed_suggestion_is_a_new_snapshot(self):
        id_soporte = self.create()
        self.notify(id_soporte)
        self.client.put(f'/api/soporte/{id_soporte}', json={'sugerencia': 'Revisar switch'}, headers=self.headers)
        self.assertEqual(self.send.call_count, 1)
        self.notify(id_soporte)
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(models.SoporteAvisoTerreno.query.count(), 2)

    def test_missing_smtp_does_not_undo_saved_support(self):
        id_soporte = self.create()
        with patch.dict(self.app.config, SMTP_HOST=''):
            response = self.notify(id_soporte)
        self.assertEqual(response.status_code, 503)
        self.assertTrue(response.get_json()['reintentable'])
        self.assertEqual(models.Soporte.query.count(), 1)
        self.send.assert_not_called()

    def test_does_not_change_closure_email_tracking(self):
        id_soporte = self.create()
        soporte = db.session.get(models.Soporte, id_soporte)
        original = soporte.correo_enviado
        self.notify(id_soporte)
        db.session.refresh(soporte)
        self.assertEqual(soporte.correo_enviado, original)
        self.assertIsNone(soporte.fecha_envio_correo)

    def test_failure_committing_after_delivery_does_not_allow_blind_resend(self):
        id_soporte = self.create()
        original_commit = db.session.commit
        commits = []
        def commit():
            commits.append(True)
            if len(commits) == 3:
                raise RuntimeError('Simulated database failure')
            return original_commit()
        with patch.object(db.session, 'commit', side_effect=commit):
            self.assertEqual(self.notify(id_soporte).status_code, 503)
        self.assertEqual(self.notify(id_soporte).status_code, 409)
        self.send.assert_called_once()

    def test_real_message_builder_uses_tls_and_contains_no_password(self):
        self.sender.stop()
        server = Mock()
        server.__enter__ = Mock(return_value=server)
        server.__exit__ = Mock(return_value=False)
        server.send_message.return_value = {}
        with patch.object(correo.smtplib, 'SMTP', return_value=server):
            response = self.notify(self.create())
        self.assertEqual(response.status_code, 200)
        server.starttls.assert_called_once()
        message = server.send_message.call_args.args[0]
        self.assertEqual(message['To'], 'soporte@orcatecnologia.cl')
        self.assertEqual(message.get_content_type(), 'multipart/alternative')
        self.assertIn('Camara sin conexion', message.get_body(preferencelist=('plain',)).get_content())
        self.assertIn('Revisar energia y cableado', message.get_body(preferencelist=('plain',)).get_content())
        html = message.get_body(preferencelist=('html',)).get_content()
        self.assertIn('OrcaGest', html)
        self.assertIn('Camara sin conexion', html)
        self.assertIn('Revisar energia y cableado', html)
        self.assertNotIn('Datos de ejemplo', html)
        self.assertNotIn('test-password', str(message))

    def test_smtp_rejection_is_retryable_without_leaking_server_details(self):
        self.sender.stop()
        with patch.object(correo.smtplib, 'SMTP', side_effect=correo.smtplib.SMTPAuthenticationError(535, b'test-password')):
            response = self.notify(self.create())
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['aviso_terreno']['estado'], 'error')
        self.assertNotIn('test-password', str(response.get_json()))

    def test_gmail_transport_uses_authenticated_account_and_starttls(self):
        self.sender.stop()
        server = Mock()
        server.__enter__ = Mock(return_value=server)
        server.__exit__ = Mock(return_value=False)
        server.send_message.return_value = {}
        with patch.dict(self.app.config, SMTP_HOST='smtp.gmail.com', SMTP_USERNAME='emisor@gmail.com', SMTP_FROM='emisor@gmail.com'), \
                patch.object(correo.smtplib, 'SMTP', return_value=server) as smtp:
            self.assertEqual(self.notify(self.create()).status_code, 200)
        smtp.assert_called_once_with('smtp.gmail.com', 587, timeout=15)
        server.login.assert_called_once_with('emisor@gmail.com', 'test-password')
        self.assertEqual(server.send_message.call_args.args[0]['From'], 'emisor@gmail.com')

    def test_ssl_transport_does_not_start_tls_twice(self):
        self.sender.stop()
        server = Mock()
        server.__enter__ = Mock(return_value=server)
        server.__exit__ = Mock(return_value=False)
        server.send_message.return_value = {}
        with patch.dict(self.app.config, SMTP_USE_SSL=True, SMTP_USE_TLS=False, SMTP_PORT=465), \
                patch.object(correo.smtplib, 'SMTP_SSL', return_value=server) as smtp:
            self.assertEqual(self.notify(self.create()).status_code, 200)
        self.assertEqual(smtp.call_args.args[1], 465)
        server.starttls.assert_not_called()

    def test_timeout_during_transmission_is_not_blindly_retried(self):
        self.sender.stop()
        server = Mock()
        server.__enter__ = Mock(return_value=server)
        server.__exit__ = Mock(return_value=False)
        server.send_message.side_effect = TimeoutError()
        id_soporte = self.create()
        with patch.object(correo.smtplib, 'SMTP', return_value=server):
            response = self.notify(id_soporte)
            self.assertEqual(response.status_code, 502)
            self.assertEqual(response.get_json()['aviso_terreno']['estado'], 'incierto')
            self.assertEqual(self.notify(id_soporte).status_code, 409)
        server.send_message.assert_called_once()

    def test_partial_rejection_requires_manual_verification(self):
        self.sender.stop()
        server = Mock()
        server.__enter__ = Mock(return_value=server)
        server.__exit__ = Mock(return_value=False)
        server.send_message.return_value = {'rechazado@example.test': (550, 'Rejected')}
        with patch.object(correo.smtplib, 'SMTP', return_value=server):
            response = self.notify(self.create())
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['aviso_terreno']['estado'], 'parcial')

    def test_credentials_missing_and_unencrypted_connections_fail_without_sending(self):
        id_soporte = self.create()
        for config in [dict(SMTP_PASSWORD=''), dict(SMTP_USE_TLS=False, SMTP_USE_SSL=False)]:
            with patch.dict(self.app.config, config):
                self.assertEqual(self.notify(id_soporte).status_code, 503)
        self.send.assert_not_called()

    def test_deleted_support_removes_notification_history(self):
        id_soporte = self.create()
        self.notify(id_soporte)
        self.assertEqual(self.client.delete(f'/api/soporte/{id_soporte}').status_code, 200)
        self.assertEqual(models.SoporteAvisoTerreno.query.count(), 0)


class SoporteSchemaTest(unittest.TestCase):
    def test_upgrades_legacy_table_without_losing_data_and_is_idempotent(self):
        engine = create_engine('sqlite:///:memory:')
        try:
            with engine.begin() as connection:
                connection.execute(text('CREATE TABLE soporte (id_soporte INTEGER PRIMARY KEY, problema TEXT)'))
                connection.execute(text("INSERT INTO soporte VALUES (1, 'Problema anterior')"))
            schema.ensure_soporte_schema(engine)
            schema.ensure_soporte_schema(engine)
            self.assertIn('sugerencia', {item['name'] for item in inspect(engine).get_columns('soporte')})
            self.assertTrue(inspect(engine).has_table('soporte_avisos_terreno'))
            with engine.connect() as connection:
                self.assertEqual(tuple(connection.execute(text('SELECT problema, sugerencia FROM soporte')).one()), ('Problema anterior', None))
        finally:
            engine.dispose()


if __name__ == '__main__':
    unittest.main()
