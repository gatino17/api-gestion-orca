import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path

from sqlalchemy import create_engine, inspect, text


# Importa solo la migracion; no carga la configuracion ni la base de produccion.
NAMESPACE = '_ticket_iso_schema_tests_app'
package = types.ModuleType(NAMESPACE)
package.__path__ = [str(Path(__file__).resolve().parents[1] / 'app')]
sys.modules[NAMESPACE] = package
schema = importlib.import_module(NAMESPACE + '.ticket_iso_schema')


class TicketISOSchemaTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='ticket_iso_schema_')
        self.engine = create_engine('sqlite:///' + str(Path(self.folder.name) / 'test.sqlite'))

    def tearDown(self):
        self.engine.dispose()
        self.folder.cleanup()

    def crear_tabla_anterior(self):
        with self.engine.begin() as connection:
            connection.execute(text('CREATE TABLE tickets_iso (id_ticket INTEGER PRIMARY KEY, numero_ticket VARCHAR(120), problema TEXT)'))
            connection.execute(text("INSERT INTO tickets_iso (id_ticket, numero_ticket, problema) VALUES (1, 'ISO-2026-001', 'Registro anterior')"))

    def test_actualiza_tabla_anterior_sin_perder_registros(self):
        self.crear_tabla_anterior()
        agregadas = schema.ensure_ticket_iso_schema(self.engine)
        self.assertEqual(agregadas, [nombre for nombre, _tipo in schema.COLUMNAS_TICKET_ISO])
        columnas = {column['name'] for column in inspect(self.engine).get_columns('tickets_iso')}
        self.assertTrue(set(agregadas).issubset(columnas))
        with self.engine.connect() as connection:
            registro = connection.execute(text('SELECT numero_ticket, problema, asunto_procedimiento, observaciones FROM tickets_iso')).one()
        self.assertEqual(tuple(registro), ('ISO-2026-001', 'Registro anterior', None, None))

    def test_es_idempotente(self):
        self.crear_tabla_anterior()
        schema.ensure_ticket_iso_schema(self.engine)
        self.assertEqual(schema.ensure_ticket_iso_schema(self.engine), [])

    def test_otro_rollback_no_deshace_las_columnas_confirmadas(self):
        self.crear_tabla_anterior()
        schema.ensure_ticket_iso_schema(self.engine)
        with self.engine.connect() as connection:
            transaction = connection.begin()
            connection.execute(text("UPDATE tickets_iso SET problema = 'Cambio no confirmado'"))
            transaction.rollback()
        with self.engine.connect() as connection:
            registro = connection.execute(text('SELECT problema, asunto_procedimiento, origen, categoria_procedimiento, observaciones FROM tickets_iso')).one()
        self.assertEqual(tuple(registro), ('Registro anterior', None, None, None, None))

    def test_no_permite_arrancar_con_la_tabla_ausente(self):
        with self.assertRaisesRegex(RuntimeError, 'No existe la tabla tickets_iso'):
            schema.ensure_ticket_iso_schema(self.engine)


if __name__ == '__main__':
    unittest.main()
