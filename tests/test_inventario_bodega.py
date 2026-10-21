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
        self.assertEqual(detalle['resumen']['total_escaneos'], 1)
        self.assertEqual(detalle['escaneos'][0]['numero_serie'], '31142001')
        self.assertIsNone(detalle['escaneos'][0]['bodega_equipo_id'])
        self.assertNotIn('31142001', [item['numero_serie'] for item in detalle['resumen']['faltantes_detalle']])

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
