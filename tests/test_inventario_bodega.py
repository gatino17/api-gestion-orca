import importlib
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from flask import Flask


NAMESPACE = '_inventario_bodega_tests_app'
APP_PATH = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NAMESPACE, APP_PATH), (NAMESPACE + '.routes', APP_PATH / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
socket = types.ModuleType(NAMESPACE + '.socketio_ext')
socket.emit_inventario_event = Mock()
sys.modules[socket.__name__] = socket
models = importlib.import_module(NAMESPACE + '.models')
db = importlib.import_module(NAMESPACE + '.database').db
# Load only the route module, never create_app or the production connection.
with patch('os.makedirs'):
    routes = importlib.import_module(NAMESPACE + '.routes.inventarios_routes')


class InventarioBodegaTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('inventario_bodega_tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.inventarios_blueprint, url_prefix='/inventarios')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        self.client = self.app.test_client()
        self.equipo = models.BodegaInventarioEquipo(id_bodega_equipo=1, codigo='31142', numero_serie='31142001', equipo_nombre='PC')
        self.otro = models.BodegaInventarioEquipo(id_bodega_equipo=2, codigo='31142', numero_serie='31142002', equipo_nombre='PC')
        self.toma = models.BodegaInventarioToma(id_toma=1, nombre='Informe de prueba', estado='abierto')
        db.session.add_all([self.equipo, self.otro, self.toma])
        db.session.commit()
        socket.emit_inventario_event.reset_mock()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def detalle(self, toma_id=1, **params):
        return self.client.get('/inventarios/bodega_tomas/{}'.format(toma_id), query_string=params).get_json()

    def test_deleted_equipment_is_not_missing_in_open_or_closed_reports(self):
        db.session.add(models.BodegaInventarioToma(id_toma=2, nombre='Informe cerrado', estado='cerrado'))
        db.session.commit()
        for toma_id in [1, 2]:
            self.assertEqual(self.detalle(toma_id)['resumen']['faltantes'], 2)
        response = self.client.delete('/inventarios/bodega_equipos/1')
        self.assertEqual(response.status_code, 200)
        for toma_id in [1, 2]:
            resumen = self.detalle(toma_id)['resumen']
            self.assertEqual(resumen['total_esperado'], 1)
            self.assertEqual(resumen['faltantes'], 1)
            self.assertEqual([item['id_bodega_equipo'] for item in resumen['faltantes_detalle']], [2])
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'equipo_eliminado', 'id_bodega_equipo': 1,
        })

    def test_delete_preserves_scan_history_without_reporting_deleted_equipment_as_missing(self):
        db.session.add(models.BodegaInventarioEscaneo(toma_id=1, bodega_equipo=self.equipo,
            codigo=self.equipo.codigo, numero_serie=self.equipo.numero_serie, equipo_nombre='PC', resultado='encontrado'))
        db.session.commit()
        self.assertEqual(self.client.delete('/inventarios/bodega_equipos/1').status_code, 200)
        detalle = self.detalle()
        self.assertEqual(detalle['resumen']['total_escaneos'], 0)
        self.assertEqual(detalle['escaneos'], [])
        historial = models.BodegaInventarioEscaneo.query.one()
        self.assertEqual(historial.numero_serie, '31142001')
        self.assertIsNone(historial.bodega_equipo_id)
        self.assertNotIn('31142001', [item['numero_serie'] for item in detalle['resumen']['faltantes_detalle']])

    def test_existing_deleted_scans_are_hidden_in_list_detail_compact_and_closed_reports(self):
        self.toma.estado = 'cerrado'
        for resultado in ['encontrado', 'duplicado', 'no_corresponde']:
            db.session.add(models.BodegaInventarioEscaneo(toma_id=1, codigo='60109',
                numero_serie='eliminado-' + resultado, equipo_nombre='PC', resultado=resultado))
        db.session.add(models.BodegaInventarioEscaneo(toma_id=1, bodega_equipo=self.otro,
            codigo=self.otro.codigo, numero_serie=self.otro.numero_serie, equipo_nombre='PC', resultado='encontrado'))
        db.session.commit()
        for params in [{}, {'compact': '1'}, {'tipo_equipo': 'PC'}, {'tipo_equipo': 'PC', 'compact': '1'}]:
            detalle = self.detalle(**params)
            self.assertEqual(detalle['resumen']['total_escaneos'], 1)
            self.assertEqual(detalle['resumen']['encontrados'], 1)
            self.assertEqual(detalle['resumen']['faltantes'], 1)
            self.assertEqual([item['numero_serie'] for item in detalle['escaneos']], ['31142002'])
        listado = self.client.get('/inventarios/bodega_tomas').get_json()
        self.assertEqual(listado[0]['resumen']['total_escaneos'], 1)
        self.assertEqual(models.BodegaInventarioEscaneo.query.count(), 4)

    def test_manual_and_unexpected_scans_without_stock_links_are_preserved(self):
        for resultado in ['manual', 'no_esperado']:
            db.session.add(models.BodegaInventarioEscaneo(toma_id=1, numero_serie=resultado,
                equipo_nombre='PC', resultado=resultado))
        db.session.commit()
        detalle = self.detalle(tipo_equipo='PC')
        self.assertEqual(detalle['resumen']['total_escaneos'], 2)
        self.assertEqual(detalle['resumen']['manuales'], 1)
        self.assertEqual(detalle['resumen']['no_esperados'], 1)
        self.assertEqual({item['resultado'] for item in detalle['escaneos']}, {'manual', 'no_esperado'})

    def test_readding_same_series_does_not_restore_or_block_deleted_scan(self):
        db.session.add(models.BodegaInventarioEscaneo(toma_id=1, bodega_equipo=self.equipo,
            codigo=self.equipo.codigo, numero_serie=self.equipo.numero_serie, equipo_nombre='PC', resultado='encontrado'))
        db.session.commit()
        self.assertEqual(self.client.delete('/inventarios/bodega_equipos/1').status_code, 200)
        db.session.add(models.BodegaInventarioEquipo(id_bodega_equipo=3, codigo='31142',
            numero_serie='31142001', equipo_nombre='PC'))
        db.session.commit()
        self.assertEqual(self.detalle()['escaneos'], [])
        with patch.object(routes, '_usuario_actual_desde_token', return_value=None):
            response = self.client.post('/inventarios/bodega_tomas/1/escaneos', json={
                'valor': '31142001', 'tipo_equipo': 'PC',
            })
        self.assertEqual(response.status_code, 201, response.get_json())
        detalle = self.detalle()
        self.assertEqual(detalle['resumen']['total_escaneos'], 1)
        self.assertEqual(detalle['resumen']['encontrados'], 1)
        self.assertEqual(detalle['escaneos'][0]['bodega_equipo_id'], 3)
        self.assertEqual(models.BodegaInventarioEscaneo.query.count(), 2)

    def test_shared_product_code_does_not_remove_other_equipment_series(self):
        self.client.delete('/inventarios/bodega_equipos/1')
        resumen = self.detalle(tipo_equipo='PC')['resumen']
        self.assertEqual([item['numero_serie'] for item in resumen['faltantes_detalle']], ['31142002'])
        tipos = self.client.get('/inventarios/bodega_tipos').get_json()
        self.assertEqual(next(item for item in tipos if item['equipo_nombre'] == 'PC')['total_esperado'], 1)

    def test_nonexistent_equipment_does_not_emit_a_successful_delete_event(self):
        self.assertEqual(self.client.delete('/inventarios/bodega_equipos/99').status_code, 404)
        socket.emit_inventario_event.assert_not_called()
        self.assertEqual(self.detalle()['resumen']['faltantes'], 2)

    def test_equipment_assigned_to_assembly_or_technician_is_not_missing(self):
        self.equipo.equipo_nombre = 'Axis P8221'
        self.equipo.numero_serie = '6010900129'
        self.equipo.estado_asignacion = 'asignado_armado'
        self.otro.estado_asignacion = 'asignado_tecnico'
        db.session.commit()
        for params in [{}, {'tipo_equipo': 'Axis P8221'}, {'compact': '1'}]:
            resumen = self.detalle(**params)['resumen']
            self.assertEqual(resumen['total_esperado'], 0)
            self.assertEqual(resumen['faltantes'], 0)
        self.assertEqual(self.detalle()['resumen']['faltantes_detalle'], [])
        tipos = self.client.get('/inventarios/bodega_tipos').get_json()
        self.assertTrue(all(item['total_esperado'] == 0 for item in tipos))
        self.assertIsNotNone(db.session.get(models.BodegaInventarioEquipo, 1))

    def test_returned_equipment_is_expected_again_and_scans_keep_their_history(self):
        db.session.add(models.BodegaInventarioEscaneo(toma_id=1, bodega_equipo=self.equipo,
            codigo=self.equipo.codigo, numero_serie=self.equipo.numero_serie, equipo_nombre='PC', resultado='encontrado'))
        self.equipo.estado_asignacion = ' ASIGNADO_ARMADO '
        db.session.commit()
        detalle = self.detalle()
        self.assertEqual(detalle['resumen']['total_esperado'], 1)
        self.assertEqual(detalle['resumen']['encontrados'], 0)
        self.assertEqual(detalle['resumen']['faltantes'], 1)
        self.assertEqual(len(detalle['escaneos']), 1)
        self.equipo.estado_asignacion = 'en_bodega'
        db.session.commit()
        resumen = self.detalle()['resumen']
        self.assertEqual(resumen['total_esperado'], 2)
        self.assertEqual(resumen['encontrados'], 1)
        self.assertEqual(resumen['faltantes'], 1)

    def test_create_scan_and_delete_notify_web_and_mobile_with_the_same_report_id(self):
        with patch.object(routes, '_usuario_actual_desde_token', return_value=None):
            response = self.client.post('/inventarios/bodega_tomas/1/escaneos', json={'valor': '31142001'})
        self.assertEqual(response.status_code, 201)
        scan_id = response.get_json()['escaneo']['id_escaneo']
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'escaneo_creado', 'id_toma': 1, 'id_escaneo': scan_id,
        })
        detalle = self.detalle()
        self.assertEqual(detalle['resumen']['encontrados'], 1)
        self.assertEqual(detalle['resumen']['faltantes'], 1)
        socket.emit_inventario_event.reset_mock()
        duplicate = self.client.post('/inventarios/bodega_tomas/1/escaneos', json={'valor': '31142001'})
        self.assertEqual(duplicate.status_code, 409)
        socket.emit_inventario_event.assert_not_called()
        self.assertEqual(self.client.delete('/inventarios/bodega_tomas/escaneos/{}'.format(scan_id)).status_code, 200)
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'escaneo_eliminado', 'id_toma': 1, 'id_escaneo': scan_id,
        })
        self.assertEqual(self.detalle()['resumen']['faltantes'], 2)

    def test_report_creation_closing_and_reopening_emit_updates(self):
        with patch.object(routes, '_usuario_actual_desde_token', return_value=None):
            response = self.client.post('/inventarios/bodega_tomas', json={'nombre': 'Desde movil'})
        self.assertEqual(response.status_code, 201)
        report_id = response.get_json()['toma']['id_toma']
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'toma_creada', 'id_toma': report_id,
        })
        socket.emit_inventario_event.reset_mock()
        self.assertEqual(self.client.post('/inventarios/bodega_tomas/{}/cerrar'.format(report_id)).status_code, 200)
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'toma_cerrada', 'id_toma': report_id,
        })
        socket.emit_inventario_event.reset_mock()
        with patch.object(routes, '_usuario_actual_es_admin', return_value=True):
            response = self.client.post('/inventarios/bodega_tomas/{}/reabrir'.format(report_id))
        self.assertEqual(response.status_code, 200)
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'toma_reabierta', 'id_toma': report_id,
        })

    def test_stock_create_and_edit_notify_and_update_existing_report(self):
        response = self.client.post('/inventarios/bodega_equipos', json={
            'codigo': '60109', 'numero_serie': '6010900129', 'equipo_nombre': 'Axis P8221',
        })
        self.assertEqual(response.status_code, 201)
        stock_id = response.get_json()['items'][0]['id_bodega_equipo']
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'equipos_creados', 'ids_bodega_equipo': [stock_id],
        })
        self.assertEqual(self.detalle()['resumen']['total_esperado'], 3)
        socket.emit_inventario_event.reset_mock()
        response = self.client.put('/inventarios/bodega_equipos/{}'.format(stock_id), json={'equipo_nombre': 'Axis actualizado'})
        self.assertEqual(response.status_code, 200)
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'equipo_actualizado', 'id_bodega_equipo': stock_id,
        })
        self.assertIn('Axis actualizado', [item['equipo_nombre'] for item in self.detalle()['resumen']['faltantes_detalle']])

    def test_assignment_and_return_notify_and_refresh_expected_totals(self):
        db.session.add(models.User(id=5, name='Tecnico prueba', email='test@example.invalid', password_hash='test-only', rol='tecnico'))
        db.session.commit()
        with patch.object(routes, '_usuario_actual_desde_token', return_value=None):
            response = self.client.post('/inventarios/bodega_equipos/1/asignar_tecnico', json={'tecnico_id': 5})
        self.assertEqual(response.status_code, 200)
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'equipo_asignado', 'id_bodega_equipo': 1,
        })
        self.assertEqual(self.detalle()['resumen']['total_esperado'], 1)
        socket.emit_inventario_event.reset_mock()
        self.assertEqual(self.client.post('/inventarios/bodega_equipos/1/devolver_bodega', json={}).status_code, 200)
        socket.emit_inventario_event.assert_called_once_with('inventario_updated', {
            'tipo': 'equipo_devuelto', 'id_bodega_equipo': 1,
        })
        self.assertEqual(self.detalle()['resumen']['total_esperado'], 2)

    def test_failed_transaction_never_announces_an_inventory_change(self):
        with patch.object(db.session, 'commit', side_effect=RuntimeError('Prueba rollback')):
            response = self.client.put('/inventarios/bodega_equipos/1', json={'equipo_nombre': 'No guardar'})
        self.assertEqual(response.status_code, 500)
        socket.emit_inventario_event.assert_not_called()
        self.assertEqual(db.session.get(models.BodegaInventarioEquipo, 1).equipo_nombre, 'PC')

    def test_read_only_refresh_does_not_emit_an_update_loop(self):
        for endpoint in ['/inventarios/bodega_tomas', '/inventarios/bodega_tomas/1',
                         '/inventarios/bodega_tomas/1?compact=1', '/inventarios/bodega_tipos']:
            self.assertEqual(self.client.get(endpoint).status_code, 200)
        socket.emit_inventario_event.assert_not_called()
