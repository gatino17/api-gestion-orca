from sqlalchemy import inspect, text


COLUMNAS_TICKET_ISO = (
    ('asunto_procedimiento', 'VARCHAR(250)'),
    ('origen', 'VARCHAR(50)'),
    ('categoria_procedimiento', 'VARCHAR(60)'),
    ('observaciones', 'TEXT'),
    ('resultado_plan_accion', 'TEXT'),
    ('fecha_control', 'DATE'),
)


def ensure_ticket_iso_schema(engine):
    from .models import TicketISOPlanAccion

    # Usa una transaccion propia: un rollback de otras migraciones no debe deshacer estas columnas.
    with engine.begin() as connection:
        postgres = connection.dialect.name == 'postgresql'
        if postgres:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            connection.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': 84573220})

        inspector = inspect(connection)
        if not inspector.has_table('tickets_iso'):
            raise RuntimeError('No existe la tabla tickets_iso. Ejecuta la creacion de tablas antes de su migracion.')
        existentes = {column['name'] for column in inspector.get_columns('tickets_iso')}
        agregadas = []
        for nombre, tipo in COLUMNAS_TICKET_ISO:
            if nombre in existentes:
                continue
            condicion = 'IF NOT EXISTS ' if postgres else ''
            connection.execute(text(f'ALTER TABLE tickets_iso ADD COLUMN {condicion}{nombre} {tipo}'))
            agregadas.append(nombre)

        existentes = {column['name'] for column in inspect(connection).get_columns('tickets_iso')}
        faltantes = [nombre for nombre, _tipo in COLUMNAS_TICKET_ISO if nombre not in existentes]
        if faltantes:
            raise RuntimeError('El esquema de Ticket ISO sigue incompleto: ' + ', '.join(faltantes))
        TicketISOPlanAccion.__table__.create(connection, checkfirst=True)
        fechas = [nombre for nombre in ('updated_at', 'created_at') if nombre in existentes]
        fecha_registro = 'COALESCE(' + ', '.join(fechas + ['CURRENT_TIMESTAMP']) + ')' if fechas else 'CURRENT_TIMESTAMP'
        # La marca unica conserva el plan anterior una sola vez, incluso tras reinicios.
        connection.execute(text(f'''
            INSERT INTO ticket_iso_planes_accion
                (ticket_id, resultado_plan_accion, fecha_control, created_at, es_legado)
            SELECT t.id_ticket, t.resultado_plan_accion, t.fecha_control, {fecha_registro}, TRUE
            FROM tickets_iso t
            WHERE (t.resultado_plan_accion IS NOT NULL OR t.fecha_control IS NOT NULL)
              AND NOT EXISTS (SELECT 1 FROM ticket_iso_planes_accion p WHERE p.ticket_id = t.id_ticket AND p.es_legado = TRUE)
        '''))
    return agregadas
