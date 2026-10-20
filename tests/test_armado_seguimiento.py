import importlib
import json
import sys
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
from flask import Flask


# Import real models/routes without running create_app or accessing production.
NAMESPACE = '_armado_seguimiento_tests_app'
APP_PATH = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NAMESPACE, APP_PATH), (NAMESPACE + '.routes', APP_PATH / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
socket = types.ModuleType(NAMESPACE + '.socketio_ext')
socket.emit_armado_event = Mock()
sys.modules[socket.__name__] = socket
models = importlib.import_module(NAMESPACE + '.models')
db = importlib.import_module(NAMESPACE + '.database').db
routes = importlib.import_module(NAMESPACE + '.routes.armados_routes')
service = importlib.import_module(NAMESPACE + '.armado_seguimiento')
TODAY = date(2026, 10, 20)


class DespachoTest(unittest.TestCase):
    def guia(self, cajas, estado='en_transito_centro', fecha=date(2026, 10, 19)):
        return types.SimpleNamespace(id_guia_salida=1, cajas_json=json.dumps(cajas), estado=estado, fecha_salida=fecha)

    def test_partial_deduplicated_and_received_is_not_installed(self):
        guias = [self.guia(['Caja 1']), self.guia(['Bulto 1'], 'recepcionado_en_centro')]
        resultado = service.resumen_despacho(guias, ['Caja 1', 'Caja 2'], hoy=TODAY)
        self.assertEqual(resultado['bultos_enviados'], 1)
        self.assertEqual(resultado['bultos_recibidos'], 1)
        self.assertFalse(resultado['completo'])
        guias.append(self.guia(['Caja 2'], fecha=TODAY))
        self.assertEqual(service.resumen_despacho(guias, ['Caja 1', 'Caja 2'], hoy=TODAY)['fecha_completo'], '2026-10-20')

    def test_ignore_cancelled_future_unknown_and_virtual_boxes(self):
        guias = [self.guia(['Caja 1'], 'cancelado'), self.guia(['Caja 1'], fecha=date(2026, 10, 21)),
                 self.guia(['Caja 99', 'Sin caja', 'Pendiente de caja'])]
        resultado = service.resumen_despacho(guias, ['Caja 1', 'Sin caja'], hoy=TODAY)
        self.assertEqual(resultado['total_bultos'], 1)
        self.assertEqual(resultado['bultos_enviados'], 0)

    def test_zero_total_never_completes_and_manual_total_is_supported(self):
        self.assertFalse(service.resumen_despacho([], [], hoy=TODAY)['completo'])
        self.assertTrue(service.resumen_despacho([self.guia(['Caja 1'])], [], 1, hoy=TODAY)['completo'])

    def test_malformed_json_is_ignored(self):
        guia = self.guia([])
        for raw in ['broken', '{}', 'null']:
            guia.cajas_json = raw
            self.assertEqual(service.resumen_despacho([guia], ['Caja 1'], hoy=TODAY)['bultos_enviados'], 0)


class SeguimientoRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('armado_seguimiento_tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.armados_blueprint, url_prefix='/armados')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.today_patch = patch.object(routes, 'hoy_chile', return_value=TODAY)
        self.service_patch = patch.object(service, 'hoy_chile', return_value=TODAY)
        self.today_patch.start()
        self.service_patch.start()
        self.users = {}
        for name, role in [('Admin', 'admin'), ('Operacion', 'operaciones'), ('Tecnico', 'tecnico'), ('Otro', 'tecnico'), ('Apoyo', 'tecnico'), ('Inventario', 'inventario')]:
            user = models.User(name=name, rol=role, email=name + '@example.test', password_hash='test')
            db.session.add(user)
            self.users[name] = user
        cliente = models.Cliente(nombre='Cliente')
        db.session.add(cliente)
        db.session.flush()
        razon = models.RazonSocial(cliente_id=cliente.id_cliente, razon_social='Razon')
        db.session.add(razon)
        db.session.flush()
        db.session.add(models.Centro(id_centro=1, nombre='Centro A', cliente_id=cliente.id_cliente, razon_social_id=razon.id_razon_social))
        self.armado = models.Armado(id_armado=1, centro_id=1, tecnico_id=self.users['Tecnico'].id, estado='finalizado',
                                   fecha_asignacion=date(2026, 10, 1), fecha_inicio=date(2026, 10, 2), fecha_cierre=date(2026, 10, 10),
                                   cajas_estado_json=json.dumps({'Caja 1': 'cerrada', 'Caja 2': 'cerrada'}))
        db.session.add(self.armado)
        db.session.add(models.ArmadoParticipacion(armado_id=1, tecnico_id=self.users['Apoyo'].id, fecha_inicio=date(2026, 10, 2)))
        db.session.add(models.ArmadoGuiaSalida(armado_id=1, numero_guia='GS1', fecha_salida=date(2026, 10, 15),
                                             cajas_json=json.dumps(['Caja 1', 'Caja 2']), estado='recepcionado_en_centro'))
        db.session.commit()
        socket.emit_armado_event.reset_mock()
        self.client = self.app.test_client()
        self.payload = {'fecha_instalacion': '2026-10-20', 'acta_entrega_id': None, 'observacion': 'Instalado y probado'}

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.today_patch.stop()
        self.service_patch.stop()

    def headers(self, name='Admin', expired=False):
        token = jwt.encode({'user_id': self.users[name].id, 'exp': datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1)},
                           routes.SECRET_KEY, algorithm='HS256')
        return {'Authorization': 'Bearer ' + token}

    def confirmar(self, name='Admin', **changes):
        return self.client.post('/armados/1/instalacion-confirmada', json={**self.payload, **changes}, headers=self.headers(name))

    def test_get_has_real_dates_dispatch_and_does_not_infer_installation(self):
        result = self.client.get('/armados/', headers=self.headers()).get_json()[0]
        tracking = result['seguimiento']
        self.assertEqual(tracking['fecha_asignacion'], '2026-10-01')
        self.assertEqual(tracking['fecha_inicio'], '2026-10-02')
        self.assertTrue(tracking['despacho']['completo'])
        self.assertIsNone(tracking['instalacion'])
        self.assertTrue(tracking['puede_confirmar_instalacion'])
        self.assertFalse(self.client.get('/armados/', headers=self.headers('Otro')).get_json()[0]['seguimiento']['puede_confirmar_instalacion'])

    def test_assignment_date_is_not_real_start_and_acta_is_not_installation(self):
        self.armado.fecha_inicio = None
        self.armado.estado = 'pendiente'
        db.session.add(models.ActaEntrega(centro_id=1, armado_id=1, fecha_registro=TODAY, tipo_instalacion='instalacion'))
        db.session.commit()
        tracking = self.client.get('/armados/').get_json()[0]['seguimiento']
        self.assertIsNone(tracking['fecha_inicio'])
        self.assertFalse(tracking['inicio_registrado'])
        self.assertIsNone(tracking['instalacion'])
        self.assertEqual(len(tracking['actas']), 1)

    def test_inventory_sees_same_timeline_as_admin_without_installation_permission(self):
        admin = self.client.get('/armados/', headers=self.headers()).get_json()
        response = self.client.get('/armados/', headers=self.headers('Inventario'))
        self.assertEqual(response.status_code, 200)
        inventario = response.get_json()
        self.assertEqual([item['id_armado'] for item in inventario], [item['id_armado'] for item in admin])
        for item, expected in zip(inventario, admin):
            tracking = item['seguimiento']
            self.assertFalse(tracking['puede_confirmar_instalacion'])
            self.assertEqual({key: value for key, value in tracking.items() if key != 'puede_confirmar_instalacion'},
                             {key: value for key, value in expected['seguimiento'].items() if key != 'puede_confirmar_instalacion'})
        self.assertEqual(self.confirmar('Inventario').status_code, 403)

    def test_start_can_come_from_first_movement(self):
        self.armado.fecha_inicio = None
        db.session.add(models.ArmadoCajaMovimiento(armado_id=1, tipo='equipo', item_id=1, nombre_item='Router', caja='Caja 1', fecha=datetime(2026, 10, 3, 14)))
        db.session.commit()
        self.assertEqual(self.client.get('/armados/').get_json()[0]['seguimiento']['fecha_inicio'], '2026-10-03')

    def test_authentication_and_current_assignment_required(self):
        self.assertEqual(self.client.post('/armados/1/instalacion-confirmada', json=self.payload).status_code, 401)
        self.assertEqual(self.client.post('/armados/1/instalacion-confirmada', json=self.payload, headers=self.headers(expired=True)).status_code, 401)
        self.assertEqual(self.confirmar('Otro').status_code, 403)
        self.assertEqual(self.client.post('/armados/999/instalacion-confirmada', json=self.payload, headers=self.headers()).status_code, 404)
        part = models.ArmadoParticipacion.query.one()
        part.fecha_fin = TODAY
        db.session.commit()
        self.assertEqual(self.confirmar('Apoyo').status_code, 403)

    def test_allowed_roles_and_active_support(self):
        for name in ['Admin', 'Operacion', 'Tecnico', 'Apoyo']:
            with self.subTest(name=name):
                self.assertEqual(self.confirmar(name).status_code, 201)
                registro = db.session.get(models.ArmadoInstalacionConfirmada, 1)
                self.assertEqual(registro.confirmado_por_id, self.users[name].id)
                db.session.delete(registro)
                db.session.commit()

    def test_invalid_and_future_dates_and_chronology(self):
        for fecha in [None, 2, '', '2026-2-20', '2026-02-30', '2026-10-21', '2026-10-14']:
            with self.subTest(fecha=fecha):
                self.assertEqual(self.confirmar(fecha_instalacion=fecha).status_code, 400)
        self.assertEqual(models.ArmadoInstalacionConfirmada.query.count(), 0)

    def test_not_finished_partial_and_unknown_dispatch_are_rejected(self):
        self.armado.estado = 'prefinalizado'
        db.session.commit()
        self.assertEqual(self.confirmar().status_code, 400)
        self.armado.estado = 'finalizado'
        guia = models.ArmadoGuiaSalida.query.one()
        guia.cajas_json = '["Caja 1"]'
        db.session.commit()
        self.assertEqual(self.confirmar().status_code, 400)
        db.session.delete(guia)
        self.armado.cajas_estado_json = None
        db.session.commit()
        self.assertEqual(self.confirmar().status_code, 400)

    def test_confirmation_persists_is_idempotent_and_does_not_change_armado_state(self):
        result = self.confirmar(confirmado_por_nombre='Falso')
        self.assertEqual(result.status_code, 201)
        self.assertEqual(result.get_json()['instalacion']['confirmado_por_nombre'], 'Admin')
        self.assertEqual(self.confirmar().status_code, 200)
        self.assertEqual(self.confirmar(observacion='Otro cierre').status_code, 409)
        self.assertEqual(models.ArmadoInstalacionConfirmada.query.count(), 1)
        self.assertEqual(self.armado.estado, 'finalizado')
        self.assertEqual(self.armado.fecha_cierre, date(2026, 10, 10))
        socket.emit_armado_event.assert_called_once()
        self.assertEqual(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion']['fecha_instalacion'], '2026-10-20')

    def test_acta_must_belong_to_this_armado_and_installation(self):
        acta = models.ActaEntrega(centro_id=1, fecha_registro=TODAY, tipo_instalacion='instalacion')
        db.session.add(acta)
        db.session.commit()
        self.assertEqual(self.confirmar(acta_entrega_id=acta.id_acta_entrega).status_code, 400)
        acta.armado_id = 1
        acta.tipo_instalacion = 'reapuntamiento'
        db.session.commit()
        self.assertEqual(self.confirmar(acta_entrega_id=acta.id_acta_entrega).status_code, 400)
        acta.tipo_instalacion = 'instalacion'
        db.session.commit()
        self.assertEqual(self.confirmar(acta_entrega_id=acta.id_acta_entrega).status_code, 201)

    def test_same_center_does_not_share_installation_with_another_armado(self):
        self.confirmar()
        db.session.add(models.Armado(id_armado=2, centro_id=1, tecnico_id=self.users['Tecnico'].id, estado='pendiente'))
        db.session.commit()
        results = {item['id_armado']: item['seguimiento'] for item in self.client.get('/armados/').get_json()}
        self.assertIsNotNone(results[1]['instalacion'])
        self.assertIsNone(results[2]['instalacion'])

    def test_malformed_fields_do_not_save(self):
        for payload in [[], None, {'fecha_instalacion': '2026-10-20', 'observacion': ['no']},
                        {**self.payload, 'acta_entrega_id': True}, {**self.payload, 'observacion': 'x' * 2001}]:
            self.assertEqual(self.client.post('/armados/1/instalacion-confirmada', json=payload, headers=self.headers()).status_code, 400)

    def test_new_status_transitions_record_dates_without_payload_dates(self):
        self.armado.estado = 'pendiente'
        self.armado.fecha_inicio = None
        self.armado.fecha_cierre = None
        db.session.commit()
        self.assertEqual(self.client.put('/armados/1', json={'estado': 'en_proceso'}).status_code, 200)
        self.assertEqual(self.armado.fecha_inicio, TODAY)
        self.assertIsNone(self.armado.fecha_cierre)
        self.client.put('/armados/1', json={'estado': 'prefinalizado'})
        self.assertIsNone(self.armado.fecha_cierre)
        self.client.put('/armados/1', json={'estado': 'finalizado'})
        self.assertEqual(self.armado.fecha_cierre, TODAY)

    def test_editing_legacy_record_does_not_invent_dates_or_overwrite_existing(self):
        self.armado.fecha_cierre = None
        db.session.commit()
        self.client.put('/armados/1', json={'observacion': 'Revision de observacion'})
        self.assertIsNone(self.armado.fecha_cierre)
        self.assertEqual(self.armado.fecha_inicio, date(2026, 10, 2))
        self.client.put('/armados/1', json={'estado': 'en_proceso'})
        self.assertEqual(self.armado.fecha_inicio, date(2026, 10, 2))
        self.client.put('/armados/1', json={'estado': 'finalizado', 'fecha_cierre': '2026-10-19'})
        self.assertEqual(self.armado.fecha_cierre, date(2026, 10, 19))


if __name__ == '__main__':
    unittest.main()
