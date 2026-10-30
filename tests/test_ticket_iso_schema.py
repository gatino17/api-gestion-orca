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

    def test_adds_root_metadata_without_changing_existing_root_cause(self):
        self.crear_tabla_anterior()
        nuevas = {'responsable_causa_raiz', 'fecha_causa_raiz'}
        with self.engine.begin() as connection:
            for nombre, tipo in schema.COLUMNAS_TICKET_ISO:
                if nombre not in nuevas:
                    connection.execute(text(f'ALTER TABLE tickets_iso ADD COLUMN {nombre} {tipo}'))
            connection.execute(text("UPDATE tickets_iso SET causa_raiz = 'Causa anterior', responsable_accion_inmediata = 'Persona accion'"))
        self.assertEqual(set(schema.ensure_ticket_iso_schema(self.engine)), nuevas)
        self.assertEqual(schema.ensure_ticket_iso_schema(self.engine), [])
        with self.engine.connect() as connection:
            row = connection.execute(text('SELECT causa_raiz, responsable_accion_inmediata, responsable_causa_raiz, fecha_causa_raiz FROM tickets_iso')).one()
            self.assertEqual(tuple(row), ('Causa anterior', 'Persona accion', None, None))

    def test_new_followup_columns_are_nullable_and_keep_saved_answers_on_restart(self):
        self.crear_tabla_anterior()
        schema.ensure_ticket_iso_schema(self.engine)
        columnas = {column['name']: column for column in inspect(self.engine).get_columns('tickets_iso')}
        for campo in ('accion_inmediata', 'amerita_seguimiento', 'seguimiento_preguntas', 'causa_raiz'):
            self.assertTrue(columnas[campo]['nullable'])
        with self.engine.begin() as connection:
            anterior = connection.execute(text('SELECT accion_inmediata, amerita_seguimiento, seguimiento_preguntas FROM tickets_iso')).one()
            self.assertEqual(tuple(anterior), (None, None, None))
            connection.execute(text('UPDATE tickets_iso SET accion_inmediata = :accion, amerita_seguimiento = TRUE, seguimiento_preguntas = :preguntas'),
                               {'accion': 'Medida inicial', 'preguntas': '[{"pregunta":"Causa?","respuesta":"En revision"}]'})
        self.assertEqual(schema.ensure_ticket_iso_schema(self.engine), [])
        with self.engine.connect() as connection:
            saved = connection.execute(text('SELECT accion_inmediata, amerita_seguimiento, seguimiento_preguntas FROM tickets_iso')).one()
            self.assertEqual(tuple(saved), ('Medida inicial', 1, '[{"pregunta":"Causa?","respuesta":"En revision"}]'))

    def test_adds_root_cause_without_relabeling_or_moving_existing_results(self):
        self.crear_tabla_anterior()
        with self.engine.begin() as connection:
            for nombre, tipo in schema.COLUMNAS_TICKET_ISO:
                if nombre != 'causa_raiz':
                    connection.execute(text(f'ALTER TABLE tickets_iso ADD COLUMN {nombre} {tipo}'))
            connection.execute(text("UPDATE tickets_iso SET observaciones = 'Resultados historicos'"))
        self.assertEqual(schema.ensure_ticket_iso_schema(self.engine), ['causa_raiz'])
        self.assertEqual(schema.ensure_ticket_iso_schema(self.engine), [])
        with self.engine.connect() as connection:
            row = connection.execute(text('SELECT observaciones, causa_raiz FROM tickets_iso')).one()
            self.assertEqual(tuple(row), ('Resultados historicos', None))

    def test_agrega_plan_a_esquema_previo_y_conserva_datos(self):
        self.crear_tabla_anterior()
        with self.engine.begin() as connection:
            for nombre, tipo in schema.COLUMNAS_TICKET_ISO[:4]:
                connection.execute(text(f'ALTER TABLE tickets_iso ADD COLUMN {nombre} {tipo}'))
            connection.execute(text("UPDATE tickets_iso SET observaciones = 'Notas existentes'"))
        self.assertEqual(schema.ensure_ticket_iso_schema(self.engine), [nombre for nombre, _tipo in schema.COLUMNAS_TICKET_ISO[4:]])
        with self.engine.connect() as connection:
            registro = connection.execute(text('SELECT observaciones, resultado_plan_accion, fecha_control FROM tickets_iso')).one()
        self.assertEqual(tuple(registro), ('Notas existentes', None, None))
        self.assertEqual(schema.ensure_ticket_iso_schema(self.engine), [])

    def test_adds_description_date_and_separate_action_metadata_without_backfilling(self):
        self.crear_tabla_anterior()
        nuevas = {'fecha_registro_descripcion', 'responsable_accion_inmediata', 'fecha_accion_inmediata'}
        with self.engine.begin() as connection:
            for nombre, tipo in schema.COLUMNAS_TICKET_ISO:
                if nombre not in nuevas:
                    connection.execute(text(f'ALTER TABLE tickets_iso ADD COLUMN {nombre} {tipo}'))
            connection.execute(text("UPDATE tickets_iso SET accion_inmediata = 'Medida anterior', observaciones = 'Resultados anteriores'"))
        self.assertEqual(set(schema.ensure_ticket_iso_schema(self.engine)), nuevas)
        self.assertEqual(schema.ensure_ticket_iso_schema(self.engine), [])
        with self.engine.connect() as connection:
            row = connection.execute(text('SELECT accion_inmediata, observaciones, fecha_registro_descripcion, responsable_accion_inmediata, fecha_accion_inmediata FROM tickets_iso')).one()
            self.assertEqual(tuple(row), ('Medida anterior', 'Resultados anteriores', None, None, None))

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

    def test_conserva_plan_legacy_una_vez_sin_tocar_plan_nuevo(self):
        self.crear_tabla_anterior()
        schema.ensure_ticket_iso_schema(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("UPDATE tickets_iso SET resultado_plan_accion = 'Plan anterior', fecha_control = '2026-10-15'"))
        schema.ensure_ticket_iso_schema(self.engine)
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO ticket_iso_planes_accion (ticket_id, resultado_plan_accion, created_at, es_legado) VALUES (1, 'Segundo plan', CURRENT_TIMESTAMP, FALSE)"))
        schema.ensure_ticket_iso_schema(self.engine)
        schema.ensure_ticket_iso_schema(self.engine)
        with self.engine.connect() as connection:
            planes = connection.execute(text('SELECT resultado_plan_accion, fecha_control, es_legado FROM ticket_iso_planes_accion ORDER BY id_plan')).all()
        self.assertEqual(len(planes), 2)
        self.assertEqual(tuple(planes[0]), ('Plan anterior', '2026-10-15', 1))
        self.assertEqual(planes[1][0], 'Segundo plan')


if __name__ == '__main__':
    unittest.main()
