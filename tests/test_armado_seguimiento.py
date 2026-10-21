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
socket.emit_actividad_event = Mock()
sys.modules[socket.__name__] = socket
models = importlib.import_module(NAMESPACE + '.models')
db = importlib.import_module(NAMESPACE + '.database').db
routes = importlib.import_module(NAMESPACE + '.routes.armados_routes')
actividades_routes = importlib.import_module(NAMESPACE + '.routes.actividades_routes')
actas_routes = importlib.import_module(NAMESPACE + '.routes.actas_entrega_routes')
permisos_routes = importlib.import_module(NAMESPACE + '.routes.permisos_trabajo_routes')
service = importlib.import_module(NAMESPACE + '.armado_seguimiento')
TODAY = date(2026, 10, 20)


class DespachoTest(unittest.TestCase):
    def guia(self, cajas, estado='en_transito_centro', fecha=date(2026, 10, 19), recepcion=None):
        return types.SimpleNamespace(id_guia_salida=1, cajas_json=json.dumps(cajas), estado=estado,
                                     fecha_salida=fecha, fecha_recepcion_centro=recepcion)

    def test_partial_deduplicated_and_received_is_not_installed(self):
        guias = [self.guia(['Caja 1']), self.guia(['Bulto 1'], 'recepcionado_en_centro')]
        resultado = service.resumen_despacho(guias, ['Caja 1', 'Caja 2'], hoy=TODAY)
        self.assertEqual(resultado['bultos_enviados'], 1)
        self.assertEqual(resultado['bultos_recibidos'], 1)
        self.assertFalse(resultado['completo'])
        self.assertFalse(resultado['recepcion_completa'])
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
        self.assertFalse(service.resumen_despacho([], [], hoy=TODAY)['recepcion_completa'])
        self.assertTrue(service.resumen_despacho([self.guia(['Caja 1'])], [], 1, hoy=TODAY)['completo'])

    def test_receipt_requires_all_distinct_boxes_and_uses_real_dates(self):
        guias = [self.guia(['Caja 1'], 'recepcionado_en_centro', recepcion=datetime(2026, 10, 19, 15)),
                 self.guia(['Bulto 1'], 'recepcionado_en_centro', recepcion=datetime(2026, 10, 20, 15)),
                 self.guia(['Caja 2'])]
        resultado = service.resumen_despacho(guias, ['Caja 1', 'Caja 2'], hoy=TODAY)
        self.assertTrue(resultado['completo'])
        self.assertEqual(resultado['bultos_recibidos'], 1)
        self.assertFalse(resultado['recepcion_completa'])
        self.assertEqual(resultado['fecha_recepcion_inicio'], '2026-10-19')
        self.assertIsNone(resultado['fecha_recepcion_completa'])
        guias[-1].estado = 'recepcionado_en_centro'
        guias[-1].fecha_recepcion_centro = datetime(2026, 10, 20, 16, tzinfo=timezone.utc)
        resultado = service.resumen_despacho(guias, ['Caja 1', 'Caja 2'], hoy=TODAY)
        self.assertEqual(resultado['bultos_recibidos'], 2)
        self.assertTrue(resultado['recepcion_completa'])
        self.assertEqual(resultado['fecha_recepcion_completa'], '2026-10-20')

    def test_receipt_date_is_chile_day_and_independent_of_dispatch_order(self):
        guias = [self.guia(['Caja 1'], 'recepcionado_en_centro', fecha=date(2026, 10, 15),
                           recepcion=datetime(2026, 10, 20, 15)),
                 self.guia(['Caja 2'], 'recepcionado_en_centro',
                           recepcion=datetime(2026, 10, 20, 2, tzinfo=timezone.utc))]
        resultado = service.resumen_despacho(guias, ['Caja 1', 'Caja 2'], hoy=TODAY)
        self.assertEqual(resultado['fecha_recepcion_inicio'], '2026-10-19')
        self.assertEqual(resultado['fecha_recepcion_completa'], '2026-10-20')
        self.assertEqual(resultado['fecha_completo'], '2026-10-19')

    def test_legacy_receipt_has_no_fabricated_date(self):
        guia = self.guia(['Caja 1'], 'recepcionado_en_centro')
        resultado = service.resumen_despacho([guia], ['Caja 1'], hoy=TODAY)
        self.assertTrue(resultado['recepcion_completa'])
        self.assertIsNone(resultado['fecha_recepcion_inicio'])
        self.assertIsNone(resultado['fecha_recepcion_completa'])

    def test_future_receipt_does_not_complete_reception(self):
        guia = self.guia(['Caja 1'], 'recepcionado_en_centro', recepcion=datetime(2026, 10, 21, 15))
        resultado = service.resumen_despacho([guia], ['Caja 1'], hoy=TODAY)
        self.assertTrue(resultado['completo'])
        self.assertFalse(resultado['recepcion_completa'])
        self.assertEqual(resultado['bultos_recibidos'], 0)
        self.assertIsNone(resultado['fecha_recepcion_completa'])

    def test_malformed_json_is_ignored(self):
        guia = self.guia([])
        for raw in ['broken', '{}', 'null']:
            guia.cajas_json = raw
            self.assertEqual(service.resumen_despacho([guia], ['Caja 1'], hoy=TODAY)['bultos_enviados'], 0)


class SeguimientoRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('armado_seguimiento_tests')
        cls.app.config.update(TESTING=True, SECRET_KEY=routes.SECRET_KEY,
                              SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.armados_blueprint, url_prefix='/armados')
        cls.app.register_blueprint(actividades_routes.actividades_blueprint, url_prefix='/actividades')
        cls.app.register_blueprint(actas_routes.actas_entrega_blueprint, url_prefix='/actas')
        cls.app.register_blueprint(permisos_routes.permisos_trabajo_blueprint, url_prefix='/permisos')

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
        for name in ['Tecnico', 'Apoyo']:
            db.session.add(models.Encargado(nombre_encargado=name, user_id=self.users[name].id))
        db.session.flush()
        perfiles = models.Encargado.query.all()
        self.actividad = models.Actividad(nombre_actividad='Instalar equipos', area='Instalacion', centro_id=1,
                                          fecha_inicio=date(2026, 10, 19), estado='En progreso',
                                          encargado_principal=perfiles[0], encargado_ayudante=perfiles[1])
        db.session.add(self.actividad)
        self.actividad.vinculo_instalacion = models.ArmadoActividadInstalacion(armado_id=1)
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

    def crear_informe_instalacion(self):
        acta = models.ActaEntrega(centro_id=1, armado_id=1, fecha_registro=date(2026, 10, 19),
                                 tipo_instalacion='instalacion', tecnico_1='Tecnico')
        permiso = models.PermisoTrabajo(centro_id=1, acta_entrega=acta, fecha_ingreso=date(2026, 10, 19),
                                       fecha_salida=TODAY, tecnico_1='Tecnico', firma_tecnico_1='firma-tecnico',
                                       recepciona_nombre='Receptor', firma_recepciona='firma-receptor',
                                       descripcion_trabajo='Sistema instalado y probado')
        db.session.add_all([acta, permiso])
        db.session.commit()
        return acta, permiso

    def test_existing_complete_mobile_report_marks_installed_without_writing_on_get(self):
        acta, permiso = self.crear_informe_instalacion()
        for usuario in ['Admin', 'Inventario']:
            result = self.client.get('/armados/', headers=self.headers(usuario)).get_json()[0]['seguimiento']
            self.assertEqual(result['instalacion']['fecha_instalacion'], '2026-10-20')
            self.assertEqual(result['instalacion']['origen'], 'informe_instalacion')
            self.assertEqual(result['instalacion']['tecnicos'], ['Tecnico'])
            self.assertEqual(result['instalacion']['acta_entrega_id'], acta.id_acta_entrega)
            self.assertEqual(result['instalacion']['permiso_trabajo_id'], permiso.id_permiso_trabajo)
        self.assertEqual(models.ArmadoInstalacionConfirmada.query.count(), 0)

    def test_installation_report_includes_installers_not_armado_builders(self):
        acta, permiso = self.crear_informe_instalacion()
        permiso.tecnico_1 = 'Gustavo Mella'
        permiso.tecnico_2 = 'Renato Vega'
        permiso.firma_tecnico_2 = 'firma-renato'
        permiso.firmas_tecnicos_adicionales = json.dumps([
            {'nombre': 'Gustavo Mella', 'firma': 'firma'}, {'nombre': 'Apoyo instalacion', 'firma': 'firma-apoyo'},
        ])
        db.session.commit()
        tracking = self.client.get('/armados/').get_json()[0]['seguimiento']
        self.assertEqual(tracking['instalacion']['tecnicos'], ['Gustavo Mella', 'Renato Vega', 'Apoyo instalacion'])
        self.assertNotIn('Tecnico', tracking['instalacion']['tecnicos'])

    def test_installation_report_drafts_and_missing_signatures_do_not_finish_armado(self):
        acta, permiso = self.crear_informe_instalacion()
        for campo, valor in [('fecha_salida', None), ('firma_tecnico_1', ''), ('firma_recepciona', ''),
                              ('recepciona_nombre', ''), ('descripcion_trabajo', '  '),
                              ('firmas_tecnicos_adicionales', '[{"nombre":"Apoyo","firma":null}]'),
                              ('firmas_tecnicos_adicionales', 'broken')]:
            with self.subTest(campo=campo, valor=valor):
                original = getattr(permiso, campo)
                setattr(permiso, campo, valor)
                db.session.commit()
                self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion'])
                setattr(permiso, campo, original)
                db.session.commit()
        permiso.tecnico_2 = 'Apoyo'
        db.session.commit()
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion'])

    def test_backdated_installation_retains_actual_date_and_chile_registration_day(self):
        acta, permiso = self.crear_informe_instalacion()
        acta.updated_at = datetime(2026, 10, 20, 2, 30)
        permiso.updated_at = datetime(2026, 10, 20, 2)
        permiso.fecha_ingreso = date(2026, 10, 16)
        permiso.fecha_salida = date(2026, 10, 17)
        acta.fecha_registro = date(2026, 10, 16)
        db.session.commit()
        registro = self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion']
        self.assertEqual(registro['fecha_instalacion'], '2026-10-17')
        self.assertEqual(registro['fecha_registro_seguimiento'], '2026-10-19')

    def test_report_rejects_future_and_out_of_order_dates(self):
        acta, permiso = self.crear_informe_instalacion()
        for fecha in [TODAY + timedelta(days=1), date(2026, 10, 18), date(2026, 9, 1)]:
            with self.subTest(fecha=fecha):
                permiso.fecha_salida = fecha
                db.session.commit()
                self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion'])

    def test_reapuntamiento_or_unlinked_report_does_not_finish_armado(self):
        acta, permiso = self.crear_informe_instalacion()
        acta.tipo_instalacion = 'reapuntamiento'
        db.session.commit()
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion'])
        acta.tipo_instalacion = 'instalacion'
        acta.armado_id = None
        db.session.commit()
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion'])

    def test_report_only_finishes_the_linked_armado_not_other_armados_in_center(self):
        self.crear_informe_instalacion()
        db.session.add(models.Armado(id_armado=2, centro_id=1, tecnico_id=self.users['Tecnico'].id,
                                    estado='finalizado', fecha_asignacion=date(2026, 10, 1)))
        db.session.commit()
        results = {item['id_armado']: item['seguimiento'] for item in self.client.get('/armados/').get_json()}
        self.assertIsNotNone(results[1]['instalacion'])
        self.assertIsNone(results[2]['instalacion'])

    def test_manual_installation_confirmation_takes_precedence_over_report(self):
        self.assertEqual(self.confirmar().status_code, 201)
        self.crear_informe_instalacion()
        instalada = self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion']
        self.assertEqual(instalada['confirmado_por_nombre'], 'Admin')
        self.assertNotIn('origen', instalada)

    def test_saving_and_deleting_mobile_report_notifies_home(self):
        acta, permiso = self.crear_informe_instalacion()
        permiso_id = permiso.id_permiso_trabajo
        socket.emit_armado_event.reset_mock()
        response = self.client.put('/permisos/{}'.format(permiso_id), json={'descripcion_trabajo': 'Instalado'}, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(any(args[0] == 'armado_updated' and args[1]['armado_id'] == 1
                            for args, kwargs in socket.emit_armado_event.call_args_list))
        socket.emit_armado_event.reset_mock()
        response = self.client.delete('/permisos/{}'.format(permiso_id), headers=self.headers())
        self.assertEqual(response.status_code, 200)
        socket.emit_armado_event.assert_called_once()
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion'])

    def test_mobile_report_creation_completes_existing_acta(self):
        acta = models.ActaEntrega(centro_id=1, armado_id=1, fecha_registro=date(2026, 10, 19),
                                 tipo_instalacion='instalacion', tecnico_1='Tecnico', firma_tecnico_1='firma',
                                 recepciona_nombre='Receptor', firma_recepciona='firma')
        db.session.add(acta)
        db.session.commit()
        response = self.client.post('/permisos/', json={
            'centro_id': 1, 'acta_entrega_id': acta.id_acta_entrega, 'fecha_ingreso': '2026-10-19',
            'fecha_salida': '2026-10-20', 'descripcion_trabajo': 'Sistema instalado',
        }, headers=self.headers('Tecnico'))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion']['origen'], 'informe_instalacion')
        self.assertEqual(self.actividad.fecha_termino, TODAY)

    def test_linking_existing_acta_to_armado_refreshes_home(self):
        acta, permiso = self.crear_informe_instalacion()
        acta.armado_id = None
        db.session.commit()
        socket.emit_armado_event.reset_mock()
        response = self.client.put('/actas/{}'.format(acta.id_acta_entrega), json={'armado_id': 1}, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        socket.emit_armado_event.assert_called_once()
        self.assertIsNotNone(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion'])

    def test_get_has_real_dates_dispatch_and_does_not_infer_installation(self):
        result = self.client.get('/armados/', headers=self.headers()).get_json()[0]
        tracking = result['seguimiento']
        self.assertEqual(tracking['fecha_asignacion'], '2026-10-01')
        self.assertEqual(tracking['fecha_inicio'], '2026-10-02')
        self.assertTrue(tracking['despacho']['completo'])
        self.assertTrue(tracking['despacho']['recepcion_completa'])
        self.assertIsNone(tracking['despacho']['fecha_recepcion_completa'])
        self.assertIsNone(tracking['instalacion'])
        self.assertTrue(tracking['puede_confirmar_instalacion'])
        self.assertFalse(self.client.get('/armados/', headers=self.headers('Otro')).get_json()[0]['seguimiento']['puede_confirmar_instalacion'])

    def test_existing_report_supplies_calendar_end_date_without_writing_on_read(self):
        self.crear_informe_instalacion()
        for path in ['/actividades/', '/actividades/mias']:
            result = self.client.get(path, headers=self.headers('Tecnico')).get_json()
            actividad = next(item for item in result if item['id_actividad'] == self.actividad.id_actividad)
            self.assertEqual(actividad['fecha_termino'], '2026-10-20')
        self.assertIsNone(self.actividad.fecha_termino)

    def test_mobile_finalization_persists_missing_calendar_end_date(self):
        self.crear_informe_instalacion()
        response = self.client.put('/actividades/{}'.format(self.actividad.id_actividad), json={'estado': 'Finalizado'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.actividad.fecha_termino, TODAY)

    def test_reassigned_activity_does_not_copy_end_date_from_previous_armado_report(self):
        self.crear_informe_instalacion()
        db.session.add(models.Armado(id_armado=2, centro_id=1, tecnico_id=self.users['Tecnico'].id,
                                    fecha_asignacion=date(2026, 10, 1), estado='finalizado'))
        db.session.commit()
        response = self.client.put('/actividades/{}'.format(self.actividad.id_actividad), json={'armado_id': 2})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.actividad.vinculo_instalacion.armado_id, 2)
        self.assertIsNone(self.actividad.fecha_termino)

    def test_report_save_fills_calendar_end_date_and_emits_activity_event(self):
        acta, permiso = self.crear_informe_instalacion()
        socket.emit_actividad_event.reset_mock()
        response = self.client.put('/permisos/{}'.format(permiso.id_permiso_trabajo), json={'descripcion_trabajo': 'Instalacion finalizada'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.actividad.fecha_termino, TODAY)
        socket.emit_actividad_event.assert_called_once_with('actividad_updated', {
            'action': 'updated', 'id_actividad': self.actividad.id_actividad,
        })

    def test_report_does_not_overwrite_previously_entered_calendar_end_date(self):
        acta, permiso = self.crear_informe_instalacion()
        self.actividad.fecha_termino = date(2026, 10, 19)
        db.session.commit()
        self.client.put('/permisos/{}'.format(permiso.id_permiso_trabajo), json={'descripcion_trabajo': 'Finalizado'})
        self.assertEqual(self.actividad.fecha_termino, date(2026, 10, 19))
        self.assertEqual(self.client.get('/actividades/').get_json()[0]['fecha_termino'], '2026-10-19')

    def test_explicit_activity_report_without_armado_still_supplies_end_date(self):
        acta, permiso = self.crear_informe_instalacion()
        self.actividad.vinculo_instalacion = None
        acta.armado_id = None
        acta.actividad_id = self.actividad.id_actividad
        db.session.commit()
        self.assertEqual(self.client.get('/actividades/').get_json()[0]['fecha_termino'], '2026-10-20')

    def test_report_does_not_complete_unrelated_same_center_activities(self):
        acta, permiso = self.crear_informe_instalacion()
        otra = models.Actividad(nombre_actividad='Otra instalacion', area='Instalacion', centro_id=1,
                                 fecha_inicio=date(2026, 10, 19), estado='En progreso')
        db.session.add(otra)
        db.session.commit()
        result = {item['id_actividad']: item for item in self.client.get('/actividades/').get_json()}
        self.assertEqual(result[self.actividad.id_actividad]['fecha_termino'], '2026-10-20')
        self.assertIsNone(result[otra.id_actividad]['fecha_termino'])

    def test_incomplete_report_does_not_supply_calendar_end_date(self):
        acta, permiso = self.crear_informe_instalacion()
        permiso.firma_recepciona = None
        db.session.commit()
        self.assertIsNone(self.client.get('/actividades/').get_json()[0]['fecha_termino'])

    def test_cancelled_non_installation_or_future_activity_is_not_auto_completed(self):
        acta, permiso = self.crear_informe_instalacion()
        original = (self.actividad.area, self.actividad.estado, self.actividad.fecha_inicio)
        for campo, valor in [('estado', 'Cancelado'), ('area', 'Mantencion'), ('fecha_inicio', TODAY + timedelta(days=1))]:
            with self.subTest(campo=campo):
                self.actividad.area, self.actividad.estado, self.actividad.fecha_inicio = original
                setattr(self.actividad, campo, valor)
                db.session.commit()
                self.assertIsNone(self.client.get('/actividades/').get_json()[0]['fecha_termino'])

    def test_manual_installation_confirmation_fills_calendar_end_date(self):
        self.assertEqual(self.confirmar().status_code, 201)
        self.assertEqual(self.actividad.fecha_termino, TODAY)

    def test_registered_receipt_updates_home_stage_without_confirming_installation(self):
        guia = models.ArmadoGuiaSalida.query.one()
        guia.estado = 'en_transito_centro'
        db.session.commit()
        antes = self.client.get('/armados/').get_json()[0]['seguimiento']['despacho']
        self.assertFalse(antes['recepcion_completa'])
        response = self.client.post('/armados/guias-salida/{}/recepcion-centro'.format(guia.id_guia_salida),
                                    json={'fecha_recepcion_centro': '2026-10-20T02:00:00Z'}, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        tracking = self.client.get('/armados/').get_json()[0]['seguimiento']
        self.assertTrue(tracking['despacho']['recepcion_completa'])
        self.assertEqual(tracking['despacho']['fecha_recepcion_completa'], '2026-10-19')
        self.assertEqual(tracking['despacho']['bultos_recibidos'], 2)
        self.assertIsNone(tracking['instalacion'])

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
        self.actividad.tecnico_ayudante = None
        self.actividad.encargado_ayudante = None
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

    def nueva_actividad(self, **changes):
        return self.client.post('/actividades/', json={
            'nombre_actividad': 'Instalar sistema', 'centro_id': 1, 'armado_id': 1,
            'area': 'Instalacion', 'fecha_inicio': '2026-10-20', 'fecha_termino': '2026-10-21',
            'estado': 'Pendiente', 'tecnico_encargado': models.Encargado.query.first().id_encargado,
            **changes,
        })

    def test_no_assignment_or_missing_date_cannot_confirm(self):
        self.actividad.fecha_inicio = None
        db.session.commit()
        self.assertFalse(self.client.get('/armados/').get_json()[0]['seguimiento']['asignacion_instalacion']['asignada'])
        self.assertEqual(self.confirmar().status_code, 400)
        db.session.delete(self.actividad)
        db.session.commit()
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['asignacion_instalacion'])
        self.assertEqual(self.confirmar().status_code, 400)

    def test_installer_assignment_not_armado_assignment_grants_confirmation(self):
        instalador = models.Encargado(nombre_encargado='Instalador distinto', user_id=self.users['Otro'].id)
        db.session.add(instalador)
        self.actividad.encargado_principal = instalador
        self.actividad.encargado_ayudante = None
        self.actividad.encargados = []
        db.session.commit()
        self.assertEqual(self.confirmar('Tecnico').status_code, 403)
        self.assertEqual(self.confirmar('Otro').status_code, 201)
        self.assertEqual(self.actividad.estado, 'Finalizado')

    def test_future_programming_cannot_be_confirmed_early(self):
        self.actividad.fecha_inicio = date(2026, 10, 21)
        db.session.commit()
        self.assertEqual(self.confirmar().status_code, 400)

    def test_calendar_creation_links_home_and_mobile_without_auto_confirming(self):
        db.session.delete(self.actividad)
        db.session.commit()
        result = self.nueva_actividad()
        self.assertEqual(result.status_code, 201, result.get_json())
        actividad_id = result.get_json()['id_actividad']
        tracking = self.client.get('/armados/').get_json()[0]['seguimiento']
        self.assertEqual(tracking['asignacion_instalacion']['actividad_id'], actividad_id)
        self.assertTrue(tracking['asignacion_instalacion']['asignada'])
        self.assertEqual(tracking['asignacion_instalacion']['instaladores'][0]['nombre'], 'Tecnico')
        self.assertIsNone(tracking['instalacion'])
        mobile = self.client.get('/actividades/mias', headers=self.headers('Tecnico')).get_json()
        self.assertEqual(next(item for item in mobile if item['id_actividad'] == actividad_id)['armado_id'], 1)
        self.client.put('/actividades/' + str(actividad_id), json={'estado': 'Finalizado'})
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['instalacion'])
        self.assertEqual(self.confirmar().status_code, 201)

    def test_duplicate_active_assignment_and_incompatible_activity_rejected(self):
        self.assertEqual(self.nueva_actividad().status_code, 400)
        for changes in [{'area': 'Mantencion'}, {'armado_id': True}, {'armado_id': 999}, {'centro_id': 99}, {'fecha_inicio': '2026-02-30'}, {'fecha_termino': '2026-10-19'}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.nueva_actividad(**changes).status_code, 400)
        self.assertEqual(models.Actividad.query.count(), 1)

    def test_cancelled_assignment_returns_to_pending_and_can_be_replaced(self):
        path = '/actividades/' + str(self.actividad.id_actividad)
        self.assertEqual(self.client.put(path, json={'estado': 'Cancelado'}).status_code, 200)
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['asignacion_instalacion'])
        self.assertEqual(self.confirmar().status_code, 400)
        result = self.nueva_actividad()
        self.assertEqual(result.status_code, 201, result.get_json())
        tracking = self.client.get('/armados/').get_json()[0]['seguimiento']
        self.assertEqual(tracking['asignacion_instalacion']['actividad_id'], result.get_json()['id_actividad'])
        self.assertEqual(self.client.put(path, json={'estado': 'En progreso'}).status_code, 400)

    def test_unrelated_activities_are_not_automatically_linked_by_center(self):
        db.session.delete(self.actividad)
        db.session.commit()
        result = self.nueva_actividad(armado_id=None)
        self.assertEqual(result.status_code, 201)
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['asignacion_instalacion'])
        path = '/actividades/' + str(result.get_json()['id_actividad'])
        self.assertEqual(self.client.put(path, json={'armado_id': 1}).status_code, 200)
        self.assertIsNotNone(self.client.get('/armados/').get_json()[0]['seguimiento']['asignacion_instalacion'])
        self.assertEqual(self.client.put(path, json={'armado_id': None}).status_code, 200)
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['asignacion_instalacion'])

    def test_confirmed_activity_cannot_be_deleted_or_unlinked(self):
        self.confirmar()
        path = '/actividades/' + str(self.actividad.id_actividad)
        self.assertEqual(self.client.delete(path).status_code, 400)
        self.assertEqual(self.client.put(path, json={'armado_id': None}).status_code, 400)
        self.assertEqual(self.client.put(path, json={'estado': 'Cancelado'}).status_code, 400)
        self.assertEqual(self.client.put(path, json={'estado': 'En progreso'}).status_code, 400)
        self.assertEqual(self.client.put(path, json={'fecha_inicio': '2026-10-21'}).status_code, 400)
        self.assertEqual(self.client.put(path, json={'area': 'Retiro'}).status_code, 400)

    def test_deleted_activity_removes_only_assignment_not_armado(self):
        path = '/actividades/' + str(self.actividad.id_actividad)
        self.assertEqual(self.client.delete(path).status_code, 200)
        self.assertEqual(models.Armado.query.count(), 1)
        self.assertEqual(models.ArmadoActividadInstalacion.query.count(), 0)
        self.assertIsNone(self.client.get('/armados/').get_json()[0]['seguimiento']['asignacion_instalacion'])

    def test_admin_closes_single_box_preserving_other_states_and_armado(self):
        self.armado.cajas_estado_json = json.dumps({'Caja 1': 'abierta', 'Caja 2': 'abierta', 'Caja 3': 'cerrada'})
        self.armado.total_cajas_manual = 3
        db.session.commit()
        response = self.client.post('/armados/1/cajas/cerrar', json={'caja': 'Caja 1'}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['cajas_estado'], {'Caja 1': 'cerrada', 'Caja 2': 'abierta', 'Caja 3': 'cerrada'})
        self.assertEqual(json.loads(self.armado.cajas_estado_json), response.get_json()['cajas_estado'])
        self.assertEqual(self.armado.estado, 'finalizado')
        self.assertEqual(self.armado.fecha_cierre, date(2026, 10, 10))
        self.assertEqual(self.armado.total_cajas_manual, 3)
        self.assertEqual(models.ArmadoGuiaSalida.query.count(), 1)
        self.client.post('/armados/1/cajas/cerrar', json={'caja': 'Caja 1'}, headers=self.headers())
        socket.emit_armado_event.assert_called_once()

    def test_closing_boxes_requires_authenticated_current_admin_role(self):
        self.assertEqual(self.client.post('/armados/1/cajas/cerrar', json={'caja': 'Caja 1'}).status_code, 401)
        for name in ['Tecnico', 'Apoyo', 'Inventario', 'Operacion']:
            self.assertEqual(self.client.post('/armados/1/cajas/cerrar', json={'caja': 'Caja 1'}, headers=self.headers(name)).status_code, 403)
        self.assertEqual(self.client.post('/armados/1/cajas/cerrar', json={'caja': 'Caja 1'}, headers=self.headers(expired=True)).status_code, 401)
        self.users['Admin'].rol = 'inventario'
        db.session.commit()
        self.assertEqual(self.client.post('/armados/1/cajas/cerrar', json={'caja': 'Caja 1'}, headers=self.headers()).status_code, 403)

    def test_nonexistent_and_virtual_boxes_are_rejected(self):
        original = self.armado.cajas_estado_json
        for caja in ['', None, [], 'Pendiente de caja', 'Sin caja', 'n/a']:
            self.assertEqual(self.client.post('/armados/1/cajas/cerrar', json={'caja': caja}, headers=self.headers()).status_code, 400)
        self.assertEqual(self.client.post('/armados/1/cajas/cerrar', json={'caja': 'Caja 99'}, headers=self.headers()).status_code, 404)
        self.assertEqual(self.client.post('/armados/99/cajas/cerrar', json={'caja': 'Caja 1'}, headers=self.headers()).status_code, 404)
        self.assertEqual(self.armado.cajas_estado_json, original)

    def test_legacy_box_closure_keeps_other_undeclared_boxes_visible(self):
        self.armado.cajas_estado_json = None
        db.session.add_all([models.ArmadoMaterial(armado_id=1, nombre='Cable', caja='Caja 1', cantidad=1),
                            models.ArmadoMaterial(armado_id=1, nombre='Fuente', caja='Caja 2', cantidad=1)])
        db.session.commit()
        response = self.client.post('/armados/1/cajas/cerrar', json={'caja': 'Caja 1'}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['cajas_estado'], {'Caja 1': 'cerrada', 'Caja 2': 'abierta'})

    def test_admin_reopens_only_selected_box(self):
        response = self.client.post('/armados/1/cajas/abrir', json={'caja': 'Caja 1'}, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['cajas_estado'], {'Caja 1': 'abierta', 'Caja 2': 'cerrada'})
        self.assertEqual(self.armado.estado, 'finalizado')
        self.assertEqual(self.armado.fecha_cierre, date(2026, 10, 10))
        self.client.post('/armados/1/cajas/abrir', json={'caja': 'Caja 1'}, headers=self.headers())
        socket.emit_armado_event.assert_called_once()

    def test_reopen_and_delete_require_current_admin_role(self):
        for method, path in [('POST', '/armados/1/cajas/abrir'), ('DELETE', '/armados/1/cajas')]:
            self.assertEqual(self.client.open(path, method=method, json={'caja': 'Caja 1'}).status_code, 401)
            for name in ['Tecnico', 'Apoyo', 'Inventario', 'Operacion']:
                self.assertEqual(self.client.open(path, method=method, json={'caja': 'Caja 1'}, headers=self.headers(name)).status_code, 403)
            self.assertEqual(self.client.open(path, method=method, json={'caja': 'Pendiente de caja'}, headers=self.headers()).status_code, 400)
            self.assertEqual(self.client.open(path, method=method, json={'caja': 'Caja 99'}, headers=self.headers()).status_code, 404)

    def test_empty_box_deletion_updates_total_without_changing_armado(self):
        models.ArmadoGuiaSalida.query.delete()
        self.armado.total_cajas_manual = 2
        db.session.commit()
        response = self.client.delete('/armados/1/cajas', json={'caja': 'Caja 1'}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertTrue(response.get_json()['eliminada'])
        self.assertEqual(response.get_json()['cajas_estado'], {'Caja 2': 'cerrada'})
        self.assertEqual(response.get_json()['total_cajas'], 1)
        self.assertEqual(self.armado.total_cajas_manual, 1)
        self.assertEqual(self.armado.estado, 'finalizado')
        self.assertEqual(self.armado.fecha_cierre, date(2026, 10, 10))
        self.assertEqual(self.client.get('/armados/').get_json()[0]['total_cajas'], 1)

    def test_dispatched_box_cannot_be_deleted(self):
        before = self.armado.cajas_estado_json
        response = self.client.delete('/armados/1/cajas', json={'caja': 'Caja 1'}, headers=self.headers())
        self.assertEqual(response.status_code, 409)
        self.assertIn('guia', response.get_json()['message'])
        self.assertEqual(self.armado.cajas_estado_json, before)
        self.assertEqual(models.ArmadoGuiaSalida.query.count(), 1)

    def test_current_equipment_or_material_prevents_box_deletion(self):
        models.ArmadoGuiaSalida.query.delete()
        equipo = models.EquiposIP(centro_id=1, nombre='Router', numero_serie='SERIE-TEST', caja='Caja 1')
        material = models.ArmadoMaterial(armado_id=1, nombre='Cable', caja='Caja 2', cantidad=2)
        db.session.add_all([equipo, material])
        db.session.commit()
        for caja in ['Caja 1', 'Caja 2']:
            response = self.client.delete('/armados/1/cajas', json={'caja': caja}, headers=self.headers())
            self.assertEqual(response.status_code, 409)
            self.assertIn('Reasigna', response.get_json()['message'])
        self.assertEqual(models.EquiposIP.query.count(), 1)
        self.assertEqual(float(material.cantidad), 2)

    def test_latest_movement_content_prevents_deletion_even_without_current_item(self):
        models.ArmadoGuiaSalida.query.delete()
        db.session.add(models.ArmadoCajaMovimiento(armado_id=1, tipo='equipo', item_id=9, nombre_item='Router', caja='Caja 1'))
        db.session.commit()
        self.assertEqual(self.client.delete('/armados/1/cajas', json={'caja': 'Caja 1'}, headers=self.headers()).status_code, 409)
        self.assertEqual(models.ArmadoCajaMovimiento.query.count(), 1)

    def test_deleting_last_empty_box_keeps_history_without_recreating_box(self):
        models.ArmadoGuiaSalida.query.delete()
        self.armado.cajas_estado_json = json.dumps({'Caja 1': 'abierta'})
        self.armado.total_cajas_manual = 1
        db.session.add(models.ArmadoCajaMovimiento(armado_id=1, tipo='material', item_id=9, nombre_item='Cable', caja='Caja 1', cantidad=0))
        db.session.commit()
        response = self.client.delete('/armados/1/cajas', json={'caja': 'Caja 1'}, headers=self.headers())
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertEqual(response.get_json()['total_cajas'], 0)
        self.assertEqual(self.client.get('/armados/').get_json()[0]['total_cajas'], 0)
        self.assertEqual(self.client.post('/armados/1/cajas/abrir', json={'caja': 'Caja 1'}, headers=self.headers()).status_code, 404)
        self.assertEqual(models.ArmadoCajaMovimiento.query.count(), 1)

    def test_empty_old_box_can_be_deleted_after_contents_were_reassigned(self):
        models.ArmadoGuiaSalida.query.delete()
        for caja, instante in [('Caja 1', datetime(2026, 10, 18, 12)), ('Caja 2', datetime(2026, 10, 19, 12))]:
            db.session.add(models.ArmadoCajaMovimiento(armado_id=1, tipo='equipo', item_id=9, nombre_item='Router', caja=caja, fecha=instante))
        db.session.commit()
        self.assertEqual(self.client.delete('/armados/1/cajas', json={'caja': 'Caja 1'}, headers=self.headers()).status_code, 200)
        self.assertEqual(models.ArmadoCajaMovimiento.query.count(), 2)

    def test_unknown_guide_schema_blocks_deletion_safely(self):
        for raw in ['broken', '{}', '[{"caja":"Caja 1"}]']:
            models.ArmadoGuiaSalida.query.one().cajas_json = raw
            db.session.commit()
            self.assertEqual(self.client.delete('/armados/1/cajas', json={'caja': 'Caja 1'}, headers=self.headers()).status_code, 409)


if __name__ == '__main__':
    unittest.main()
