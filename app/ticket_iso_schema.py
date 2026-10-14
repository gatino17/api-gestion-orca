from sqlalchemy import inspect, text


COLUMNAS_TICKET_ISO = (
    ('asunto_procedimiento', 'VARCHAR(250)'),
    ('origen', 'VARCHAR(50)'),
    ('categoria_procedimiento', 'VARCHAR(60)'),
    ('observaciones', 'TEXT'),
)


def ensure_ticket_iso_schema(engine):
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
    return agregadas
