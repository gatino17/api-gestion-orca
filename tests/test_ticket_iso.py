import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from flask import Flask
from sqlalchemy.exc import IntegrityError


# Carga los modelos y rutas reales sin iniciar la app ni su base de produccion.
NAMESPACE = '_ticket_iso_tests_app'
APP_PATH = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NAMESPACE, APP_PATH), (NAMESPACE + '.routes', APP_PATH / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
auth = types.ModuleType(NAMESPACE + '.routes.auth_routes')
auth.SECRET_KEY = 'ticket-iso-isolated-test-key-2026'
sys.modules[auth.__name__] = auth
models = importlib.import_module(NAMESPACE + '.models')
db = importlib.import_module(NAMESPACE + '.database').db
permissions = importlib.import_module(NAMESPACE + '.permissions')
routes = importlib.import_module(NAMESPACE + '.routes.ticket_iso_routes')


class TicketISOTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('ticket_iso_tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.ticket_iso_blueprint, url_prefix='/api/ticket-iso')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        permissions.seed_default_roles(db)
        admin = models.User(name='Administrador', email='admin@example.test', password_hash='test', rol='admin')
        tecnico = models.User(name='Tecnico', email='tecnico@example.test', password_hash='test', rol='tecnico')
        encargado = models.User(name='Jorge', email='jorge@example.test', password_hash='test', rol='encargado_tickets')
        role = models.Role(nombre='encargado_tickets')
        cliente = models.Cliente(nombre='Cliente A')
        otro_cliente = models.Cliente(nombre='Cliente B')
        db.session.add_all([admin, tecnico, encargado, role, cliente, otro_cliente])
        db.session.flush()
        db.session.add(models.RolePage(role_id=role.id_role, page_key='ticket_iso'))
        razon = models.RazonSocial(cliente_id=cliente.id_cliente, razon_social='Cliente A SPA')
        db.session.add(razon)
        db.session.flush()
        db.session.add(models.Centro(id_centro=1, nombre='Centro A', area='Chiloe', cliente_id=cliente.id_cliente, razon_social_id=razon.id_razon_social))
        db.session.commit()
        self.admin_id, self.encargado_id = admin.id, encargado.id
        self.admin = self.headers(admin.id)
        self.tecnico = self.headers(tecnico.id)
        self.encargado = self.headers(encargado.id)
        self.otro_cliente_id = otro_cliente.id_cliente
        self.client = self.app.test_client()
        self.payload = {
            'numero_ticket': ' ISO-2026-001 ', 'asunto_procedimiento': 'Revision de procedimiento',
            'fecha_recepcion': '2026-10-14', 'problema': 'Falta actualizar el procedimiento',
            'estado': 'pendiente',
            'origen': 'ticket_iso', 'categoria_procedimiento': 'soporte_posventa',
        }

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def headers(self, user_id, expired=False):
        return {'Authorization': 'Bearer ' + jwt.encode({
            'user_id': user_id,
            'exp': datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1),
        }, auth.SECRET_KEY, algorithm='HS256')}

    def create(self, **changes):
        return self.client.post('/api/ticket-iso/', json={**self.payload, **changes}, headers=self.admin)

    def test_access_requires_session_and_current_permission(self):
        for method, path in [('GET', '/'), ('GET', '/catalogos'), ('GET', '/1'), ('POST', '/'), ('PUT', '/1'), ('DELETE', '/1')]:
            self.assertEqual(self.client.open('/api/ticket-iso' + path, method=method, json=self.payload).status_code, 401)
            self.assertEqual(self.client.open('/api/ticket-iso' + path, method=method, json=self.payload, headers=self.tecnico).status_code, 403)
        self.assertEqual(self.client.get('/api/ticket-iso/', headers=self.headers(self.admin_id, expired=True)).status_code, 401)
        self.assertEqual(self.client.get('/api/ticket-iso/', headers=self.encargado).status_code, 200)

    def test_creation_uses_date_subject_and_authenticated_author(self):
        self.assertEqual(self.client.get('/api/ticket-iso/catalogos', headers=self.admin).status_code, 200)
        response = self.create(area='Falsa', creado_por_id=self.encargado_id, creado_por_nombre='Falso')
        self.assertEqual(response.status_code, 201)
        ticket = response.get_json()['ticket']
        self.assertEqual(ticket['numero_ticket'], 'ISO-2026-001')
        self.assertIsNone(ticket['area'])
        self.assertIsNone(ticket['responsable'])
        self.assertEqual(ticket['asunto_procedimiento'], 'Revision de procedimiento')
        self.assertEqual(ticket['origen'], 'ticket_iso')
        self.assertEqual(ticket['categoria_procedimiento'], 'soporte_posventa')
        self.assertEqual(ticket['fecha_recepcion'], '2026-10-14')
        self.assertEqual(ticket['creado_por_nombre'], 'Admin')
        self.assertEqual(self.client.get('/api/ticket-iso/' + str(ticket['id_ticket']), headers=self.admin).get_json()['ticket'], ticket)

    def test_duplicate_number_is_blocked_on_create_and_edit(self):
        first = self.create().get_json()['ticket']
        self.assertEqual(self.create(numero_ticket=' iso-2026-001 ').status_code, 409)
        second = self.create(numero_ticket='ISO-2026-002').get_json()['ticket']
        response = self.client.put('/api/ticket-iso/' + str(second['id_ticket']), json=self.payload, headers=self.admin)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(models.TicketISO.query.count(), 2)
        self.assertEqual(db.session.get(models.TicketISO, second['id_ticket']).numero_ticket, 'ISO-2026-002')
        self.assertEqual(first['numero_ticket'], 'ISO-2026-001')

    def test_database_also_enforces_uniqueness(self):
        self.create()
        db.session.add(models.TicketISO(cliente_nombre='', centro_nombre='', **routes._validar(self.payload)))
        with self.assertRaises(IntegrityError):
            db.session.commit()
        db.session.rollback()
        self.assertEqual(models.TicketISO.query.count(), 1)

    def test_invalid_input_never_creates_a_record(self):
        invalid = [
            {'asunto_procedimiento': 'x' * 251},
            {'numero_ticket': 'x' * 121}, {'numero_ticket': 123}, {'problema': ' '},
            {'numero_automatico': 'true'},
            {'origen': ''}, {'origen': 'desconocido'}, {'origen': None},
            {'categoria_procedimiento': ''}, {'categoria_procedimiento': 'desconocida'}, {'categoria_procedimiento': 1},
            {'estado': 'desconocido'}, {'fecha_recepcion': '2026-10-14T09:30'},
            {'fecha_recepcion': '2026-02-30'}, {'fecha_recepcion': None},
            {'responsable_id': True}, {'responsable_id': 999}, {'responsable_id': -1}, {'responsable_id': 1.5},
            {'responsable': 123}, {'responsable': 'x' * 101},
            {'observaciones': 'x' * 10001}, {'observaciones': 123},
            {'estado': 'resuelto', 'fecha_cierre': ''}, {'estado': 'resuelto', 'fecha_cierre': '2026-02-30'},
            {'estado': 'resuelto', 'fecha_cierre': '2026-10-13'}, {'fecha_cierre': '2026-10-13'},
            {'fecha_cierre': False}, {'fecha_cierre': 0},
        ]
        for changes in invalid:
            with self.subTest(changes=changes):
                self.assertEqual(self.create(**changes).status_code, 400)
        self.assertEqual(models.TicketISO.query.count(), 0)

    def test_resolution_records_closing_date_and_preserves_author(self):
        self.assertEqual(self.create(estado='resuelto', fecha_recepcion='9999-12-31').status_code, 400)
        response = self.create(estado='resuelto', fecha_recepcion='2020-01-01')
        self.assertEqual(response.status_code, 201)
        ticket = response.get_json()['ticket']
        self.assertIsNotNone(ticket['fecha_cierre'])
        response = self.client.put('/api/ticket-iso/' + str(ticket['id_ticket']), json={**self.payload, 'estado': 'en_seguimiento'}, headers=self.encargado)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()['ticket']['fecha_cierre'])
        self.assertEqual(db.session.get(models.TicketISO, ticket['id_ticket']).creado_por_nombre, 'Admin')
        self.assertNotIn('creado_por_nombre', response.get_json()['ticket'])

    def test_unknown_ticket_returns_404(self):
        self.assertEqual(self.client.get('/api/ticket-iso/999', headers=self.admin).status_code, 404)
        self.assertEqual(self.client.put('/api/ticket-iso/999', json=self.payload, headers=self.admin).status_code, 404)
        self.assertEqual(self.client.delete('/api/ticket-iso/999', headers=self.admin).status_code, 404)

    def test_subject_is_optional_and_legacy_subject_is_preserved_on_edit(self):
        payload = {key: value for key, value in self.payload.items() if key != 'asunto_procedimiento'}
        response = self.client.post('/api/ticket-iso/', json=payload, headers=self.encargado)
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.get_json()['ticket']['asunto_procedimiento'])
        legacy = self.create(numero_ticket='LEGACY').get_json()['ticket']
        response = self.client.put('/api/ticket-iso/' + str(legacy['id_ticket']),
            json={**payload, 'numero_ticket': 'LEGACY', 'problema': 'Problema actualizado'}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket']['asunto_procedimiento'], 'Revision de procedimiento')
        self.assertEqual(response.get_json()['ticket']['problema'], 'Problema actualizado')

    def test_only_admin_can_delete_and_sequence_is_not_reused(self):
        ticket = self.create(numero_ticket='', numero_automatico=True).get_json()['ticket']
        other = self.create(numero_ticket='', numero_automatico=True).get_json()['ticket']
        url = '/api/ticket-iso/' + str(other['id_ticket'])
        self.assertEqual(self.client.delete(url, headers=self.encargado).status_code, 403)
        self.assertIsNotNone(db.session.get(models.TicketISO, other['id_ticket']))
        self.assertEqual(self.client.delete(url, headers=self.admin).status_code, 200)
        self.assertIsNone(db.session.get(models.TicketISO, other['id_ticket']))
        listed = self.client.get('/api/ticket-iso/', headers=self.admin).get_json()['tickets']
        self.assertEqual([row['id_ticket'] for row in listed], [ticket['id_ticket']])
        self.assertEqual(self.client.delete(url, headers=self.admin).status_code, 404)
        next_ticket = self.create(numero_ticket='', numero_automatico=True).get_json()['ticket']
        self.assertTrue(next_ticket['numero_ticket'].endswith('-003'))

    def test_responsible_notes_and_editable_closing_date_are_saved(self):
        catalogos = self.client.get('/api/ticket-iso/catalogos', headers=self.admin).get_json()
        self.assertIn({'id': self.encargado_id, 'nombre': 'Jorge'}, catalogos['responsables'])
        response = self.create(responsable_id=self.encargado_id, responsable_nombre='Nombre falso',
            observaciones='  Validado por auditoria  ', estado='resuelto', fecha_cierre='2026-10-16')
        self.assertEqual(response.status_code, 201)
        ticket = response.get_json()['ticket']
        self.assertEqual(ticket['responsable'], 'Jorge')
        self.assertEqual(ticket['responsable_id'], self.encargado_id)
        self.assertEqual(ticket['observaciones'], 'Validado por auditoria')
        self.assertEqual(ticket['fecha_cierre'], '2026-10-16T15:00:00+00:00')
        response = self.client.put('/api/ticket-iso/' + str(ticket['id_ticket']), json={**self.payload,
            'estado': 'resuelto', 'fecha_cierre': '2026-10-17', 'observaciones': 'Cierre corregido',
            'responsable_id': self.admin_id}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        guardado = self.client.get('/api/ticket-iso/' + str(ticket['id_ticket']), headers=self.admin).get_json()['ticket']
        self.assertEqual(guardado['responsable_id'], self.admin_id)
        self.assertEqual(guardado['observaciones'], 'Cierre corregido')
        self.assertEqual(guardado['fecha_cierre'], '2026-10-17T15:00:00+00:00')

    def test_editing_preserves_omitted_fields_and_allows_explicit_clearing(self):
        ticket = self.create(responsable_id=self.encargado_id, observaciones='Seguimiento').get_json()['ticket']
        url = '/api/ticket-iso/' + str(ticket['id_ticket'])
        response = self.client.put(url, json={**self.payload, 'estado': 'en_seguimiento'}, headers=self.admin)
        self.assertEqual(response.get_json()['ticket']['responsable_id'], self.encargado_id)
        self.assertEqual(response.get_json()['ticket']['observaciones'], 'Seguimiento')
        response = self.client.put(url, json={**self.payload, 'responsable_id': None, 'observaciones': ''}, headers=self.admin)
        self.assertIsNone(response.get_json()['ticket']['responsable_id'])
        self.assertIsNone(response.get_json()['ticket']['observaciones'])

    def test_responsible_accepts_free_text_and_keeps_existing_names_when_editing(self):
        response = self.create(responsable='  Carolina proveedor externo  ')
        self.assertEqual(response.status_code, 201)
        ticket = response.get_json()['ticket']
        self.assertEqual(ticket['responsable'], 'Carolina proveedor externo')
        self.assertIsNone(ticket['responsable_id'])
        url = '/api/ticket-iso/' + str(ticket['id_ticket'])
        response = self.client.put(url, json=self.payload, headers=self.admin)
        self.assertEqual(response.get_json()['ticket']['responsable'], 'Carolina proveedor externo')
        response = self.client.put(url, json={**self.payload, 'responsable': 'Auditor independiente'}, headers=self.admin)
        self.assertEqual(response.get_json()['ticket']['responsable'], 'Auditor independiente')
        response = self.client.put(url, json={**self.payload, 'responsable': ''}, headers=self.admin)
        self.assertIsNone(response.get_json()['ticket']['responsable'])
        anterior = self.create(numero_ticket='ANTERIOR', responsable_id=self.encargado_id).get_json()['ticket']
        response = self.client.put('/api/ticket-iso/' + str(anterior['id_ticket']), json={**self.payload,
            'numero_ticket': 'ANTERIOR', 'responsable': anterior['responsable']}, headers=self.admin)
        self.assertEqual(response.get_json()['ticket']['responsable'], 'Jorge')
        self.assertIsNone(response.get_json()['ticket']['responsable_id'])

    def test_editing_same_closing_day_does_not_erase_existing_timestamp(self):
        ticket = self.create(estado='resuelto', fecha_recepcion='2020-01-01').get_json()['ticket']
        fecha = datetime.fromisoformat(ticket['fecha_cierre']).astimezone(routes.CHILE).date().isoformat()
        response = self.client.put('/api/ticket-iso/' + str(ticket['id_ticket']), json={**self.payload,
            'estado': 'resuelto', 'fecha_recepcion': '2020-01-01', 'fecha_cierre': fecha}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket']['fecha_cierre'], ticket['fecha_cierre'])

    def test_open_ticket_can_save_and_edit_an_expected_closing_date(self):
        response = self.create(fecha_cierre='2026-10-20')
        self.assertEqual(response.status_code, 201)
        ticket = response.get_json()['ticket']
        self.assertEqual(ticket['estado'], 'pendiente')
        self.assertEqual(ticket['fecha_cierre'], '2026-10-20T15:00:00+00:00')
        url = '/api/ticket-iso/' + str(ticket['id_ticket'])
        response = self.client.put(url, json={**self.payload, 'estado': 'en_seguimiento'}, headers=self.admin)
        self.assertEqual(response.get_json()['ticket']['fecha_cierre'], ticket['fecha_cierre'])
        response = self.client.put(url, json={**self.payload, 'estado': 'en_seguimiento', 'fecha_cierre': '2026-10-21'}, headers=self.admin)
        self.assertEqual(response.get_json()['ticket']['fecha_cierre'], '2026-10-21T15:00:00+00:00')
        response = self.client.put(url, json={**self.payload, 'fecha_cierre': None}, headers=self.admin)
        self.assertIsNone(response.get_json()['ticket']['fecha_cierre'])

    def test_automatic_numbers_increment_and_manual_numbers_are_respected(self):
        prefijo = f'ISO-{datetime.now(routes.CHILE).year}-'
        self.assertEqual(self.client.get('/api/ticket-iso/catalogos', headers=self.admin).get_json()['proximo_numero'], prefijo + '001')
        first = self.create(numero_ticket='').get_json()['ticket']
        second = self.create(numero_ticket=None).get_json()['ticket']
        self.assertEqual([first['numero_ticket'], second['numero_ticket']], [prefijo + '001', prefijo + '002'])
        self.assertEqual(self.create(numero_ticket='10').get_json()['ticket']['numero_ticket'], '10')
        self.assertEqual(self.create(numero_ticket='').get_json()['ticket']['numero_ticket'], prefijo + '011')
        self.assertEqual(self.create(numero_ticket='10').status_code, 409)
        self.assertEqual(self.create(numero_ticket='').get_json()['ticket']['numero_ticket'], prefijo + '012')
        response = self.client.put('/api/ticket-iso/' + str(first['id_ticket']), json={**self.payload, 'numero_ticket': '', 'asunto_procedimiento': 'Asunto editado'}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket']['numero_ticket'], prefijo + '001')
        self.assertEqual(self.create(numero_ticket='').get_json()['ticket']['numero_ticket'], prefijo + '013')

    def test_prefilled_preview_can_be_stale_without_causing_duplicates(self):
        sugerido = self.client.get('/api/ticket-iso/catalogos', headers=self.admin).get_json()['proximo_numero']
        primero = self.create(numero_ticket=sugerido, numero_automatico=True).get_json()['ticket']
        segundo = self.create(numero_ticket=sugerido, numero_automatico=True).get_json()['ticket']
        self.assertEqual(primero['numero_ticket'], sugerido)
        self.assertNotEqual(primero['numero_ticket'], segundo['numero_ticket'])
        self.assertTrue(segundo['numero_ticket'].endswith('-002'))
        self.assertEqual(self.create(numero_ticket=sugerido, numero_automatico=False).status_code, 409)

    def test_formatted_manual_numbers_advance_the_sequence_beyond_three_digits(self):
        anio = datetime.now(routes.CHILE).year
        numero = f'ISO-{anio}-999'
        self.assertEqual(self.create(numero_ticket=numero).get_json()['ticket']['numero_ticket'], numero)
        self.assertEqual(self.create(numero_ticket='').get_json()['ticket']['numero_ticket'], f'ISO-{anio}-1000')

    def test_all_requested_origins_and_categories_are_supported(self):
        catalogos = self.client.get('/api/ticket-iso/catalogos', headers=self.admin).get_json()
        self.assertEqual(len(catalogos['origenes']), 7)
        self.assertEqual(len(catalogos['categorias_procedimiento']), 9)
        self.assertEqual(sorted(nombre[:3] for nombre in catalogos['categorias_procedimiento'].values()),
                         [f'{numero:03d}' for numero in range(1, 10)])
        for origen in routes.ORIGENES:
            response = self.create(numero_ticket='', origen=origen)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()['ticket']['origen'], origen)
        for categoria in routes.CATEGORIAS_PROCEDIMIENTO:
            response = self.create(numero_ticket='', categoria_procedimiento=categoria)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()['ticket']['categoria_procedimiento'], categoria)

    def test_editing_persists_origin_and_procedure_category(self):
        ticket = self.create().get_json()['ticket']
        response = self.client.put('/api/ticket-iso/' + str(ticket['id_ticket']), json={**self.payload,
            'origen': 'salida_no_conforme', 'categoria_procedimiento': '001_gestion_comercial'}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        guardado = self.client.get('/api/ticket-iso/' + str(ticket['id_ticket']), headers=self.admin).get_json()['ticket']
        self.assertEqual(guardado['origen'], 'salida_no_conforme')
        self.assertEqual(guardado['categoria_procedimiento'], '001_gestion_comercial')

    def test_dates_survive_daylight_saving_and_legacy_data_is_preserved(self):
        for index, fecha in enumerate(['2026-07-14', '2026-09-06', '2026-10-14']):
            response = self.create(numero_ticket=str(index + 1), fecha_recepcion=fecha)
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.get_json()['ticket']['fecha_recepcion'], fecha)
        legacy = models.TicketISO(numero_ticket='ANTERIOR', fecha_recepcion=datetime(2026, 10, 15, 1, tzinfo=timezone.utc),
            cliente_nombre='Cliente anterior', centro_nombre='Centro anterior', area='Chiloe', equipo_afectado='Camara',
            problema='Registro anterior', estado='pendiente')
        db.session.add(legacy)
        db.session.commit()
        response = self.client.get('/api/ticket-iso/' + str(legacy.id_ticket), headers=self.admin)
        self.assertEqual(response.get_json()['ticket']['fecha_recepcion'], '2026-10-14')
        response = self.client.put('/api/ticket-iso/' + str(legacy.id_ticket), json={**self.payload, 'numero_ticket': 'ANTERIOR'}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket']['centro'], 'Centro anterior')


if __name__ == '__main__':
    unittest.main()
