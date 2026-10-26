from sqlalchemy import inspect, text


def ensure_soporte_schema(engine):
    from .models import SoporteAvisoTerreno

    # Independent transaction: unrelated startup migrations must not roll this back.
    with engine.begin() as connection:
        postgres = connection.dialect.name == 'postgresql'
        if postgres:
            connection.execute(text("SET LOCAL lock_timeout = '5s'"))
            connection.execute(text("SET LOCAL statement_timeout = '30s'"))
            connection.execute(text('SELECT pg_advisory_xact_lock(84573221)'))
        inspector = inspect(connection)
        if not inspector.has_table('soporte'):
            raise RuntimeError('No existe la tabla soporte.')
        if 'sugerencia' not in {column['name'] for column in inspector.get_columns('soporte')}:
            condition = 'IF NOT EXISTS ' if postgres else ''
            connection.execute(text(f'ALTER TABLE soporte ADD COLUMN {condition}sugerencia TEXT'))
        SoporteAvisoTerreno.__table__.create(connection, checkfirst=True)
