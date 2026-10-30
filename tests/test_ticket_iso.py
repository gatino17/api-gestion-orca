import importlib
import sys
import types
import unittest
from io import BytesIO
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from flask import Flask
from sqlalchemy.exc import IntegrityError
from pypdf import PdfReader


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
        for method, path in [('GET', '/'), ('GET', '/catalogos'), ('GET', '/1'), ('GET', '/1/pdf'), ('POST', '/'), ('PUT', '/1'), ('DELETE', '/1'), ('POST', '/1/planes-accion'), ('PATCH', '/1/planes-accion/1'), ('PATCH', '/1/cierre')]:
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

    def test_pdf_requires_existing_ticket_and_current_permission_without_writing_data(self):
        self.assertEqual(self.client.get('/api/ticket-iso/999/pdf', headers=self.admin).status_code, 404)
        ticket = self.create(accion_inmediata='Medida inicial', responsable='Persona descripcion',
            fecha_registro_descripcion='2026-10-15', responsable_accion_inmediata='Persona accion',
            fecha_accion_inmediata='2026-10-16', amerita_seguimiento=True, causa_raiz='Causa registrada',
            responsable_causa_raiz='Persona analisis', fecha_causa_raiz='2026-10-17', observaciones='Resultados reales').get_json()['ticket']
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        before = self.client.get(url, headers=self.admin).get_json()['ticket']
        response = self.client.get(url + '/pdf', headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/pdf')
        self.assertTrue(response.data.startswith(b'%PDF-'))
        self.assertIn('inline', response.headers['Content-Disposition'])
        self.assertIn('no-store', response.headers['Cache-Control'])
        texto = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.data)).pages)
        self.assertIn('Persona analisis', texto)
        self.assertIn('Resultados reales', texto)
        self.assertEqual(self.client.get(url, headers=self.admin).get_json()['ticket'], before)
        response = self.client.get(url + '/pdf', headers=self.encargado)
        self.assertEqual(response.status_code, 200)
        texto = '\n'.join(page.extract_text() for page in PdfReader(BytesIO(response.data)).pages)
        self.assertNotIn('Registrado por', texto)

    def test_followup_is_optional_and_immediate_action_is_trimmed(self):
        response = self.create(accion_inmediata='  Se informa al responsable  ')
        self.assertEqual(response.status_code, 201)
        ticket = response.get_json()['ticket']
        self.assertEqual(ticket['accion_inmediata'], 'Se informa al responsable')
        self.assertIsNone(ticket['amerita_seguimiento'])
        self.assertEqual(ticket['seguimiento_preguntas'], [])
        self.assertEqual(self.create(numero_ticket='ISO-2026-002', amerita_seguimiento=False).get_json()['ticket']['amerita_seguimiento'], False)

    def test_description_and_action_have_separate_responsibles_and_dates(self):
        response = self.create(responsable='Persona descripcion', fecha_registro_descripcion='2026-10-15',
            accion_inmediata='Se informa al equipo', responsable_accion_inmediata='  Persona accion  ', fecha_accion_inmediata='2026-10-16')
        self.assertEqual(response.status_code, 201)
        ticket = response.get_json()['ticket']
        esperados = {'responsable': 'Persona descripcion', 'fecha_registro_descripcion': '2026-10-15',
                     'responsable_accion_inmediata': 'Persona accion', 'fecha_accion_inmediata': '2026-10-16'}
        for campo, valor in esperados.items():
            self.assertEqual(ticket[campo], valor)
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        for campo, valor in esperados.items():
            self.assertEqual(self.client.get(url, headers=self.admin).get_json()['ticket'][campo], valor)
        response = self.client.put(url, json=self.payload, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        for campo, valor in esperados.items():
            self.assertEqual(response.get_json()['ticket'][campo], valor)
        response = self.client.put(url, json={**self.payload, 'responsable_accion_inmediata': 'Nueva persona',
                                             'fecha_accion_inmediata': '2026-10-17'}, headers=self.admin)
        saved = response.get_json()['ticket']
        self.assertEqual(saved['responsable'], 'Persona descripcion')
        self.assertEqual(saved['fecha_registro_descripcion'], '2026-10-15')
        self.assertEqual(saved['responsable_accion_inmediata'], 'Nueva persona')
        self.assertEqual(saved['fecha_accion_inmediata'], '2026-10-17')

    def test_clearing_action_metadata_does_not_clear_description_metadata(self):
        ticket = self.create(responsable='Persona descripcion', fecha_registro_descripcion='2026-10-15',
                             responsable_accion_inmediata='Persona accion', fecha_accion_inmediata='2026-10-16').get_json()['ticket']
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        response = self.client.put(url, json={**self.payload, 'responsable_accion_inmediata': '', 'fecha_accion_inmediata': None}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        saved = response.get_json()['ticket']
        self.assertIsNone(saved['responsable_accion_inmediata'])
        self.assertIsNone(saved['fecha_accion_inmediata'])
        self.assertEqual(saved['responsable'], 'Persona descripcion')
        self.assertEqual(saved['fecha_registro_descripcion'], '2026-10-15')
        response = self.client.put(url, json={**self.payload, 'fecha_registro_descripcion': ''}, headers=self.admin)
        self.assertIsNone(response.get_json()['ticket']['fecha_registro_descripcion'])

    def test_new_metadata_is_optional_and_does_not_copy_names_or_dates(self):
        ticket = self.create(responsable='Persona descripcion').get_json()['ticket']
        self.assertIsNone(ticket['responsable_accion_inmediata'])
        self.assertIsNone(ticket['fecha_accion_inmediata'])
        self.assertIsNone(ticket['fecha_registro_descripcion'])
        for indice, fecha in enumerate(('2026-09-06', '2026-04-05'), start=2):
            saved = self.create(numero_ticket=f'ISO-2026-{indice:03d}', fecha_registro_descripcion=fecha,
                                fecha_accion_inmediata=fecha).get_json()['ticket']
            self.assertEqual(saved['fecha_registro_descripcion'], fecha)
            self.assertEqual(saved['fecha_accion_inmediata'], fecha)

    def test_invalid_metadata_is_rejected_without_changing_the_ticket(self):
        for campo in ('fecha_registro_descripcion', 'fecha_accion_inmediata'):
            for valor in ('2026-02-30', 'no-fecha', '2026-10-15T12:00:00Z', 123, [], {}):
                self.assertEqual(self.create(**{campo: valor}).status_code, 400)
        for valor in ('x' * 101, ['Persona'], 123):
            self.assertEqual(self.create(responsable_accion_inmediata=valor).status_code, 400)
        self.assertEqual(models.TicketISO.query.count(), 0)
        ticket = self.create(responsable_accion_inmediata='Conservar', fecha_accion_inmediata='2026-10-16').get_json()['ticket']
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        response = self.client.put(url, json={**self.payload, 'responsable_accion_inmediata': 'No guardar',
                                             'fecha_accion_inmediata': 'fecha-invalida'}, headers=self.admin)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get(url, headers=self.admin).get_json()['ticket']['responsable_accion_inmediata'], 'Conservar')

    def test_root_cause_is_independent_from_results_and_preserved_when_omitted(self):
        ticket = self.create(amerita_seguimiento=True, causa_raiz='  Falta de capacitacion  ',
                             observaciones='Procedimiento actualizado').get_json()['ticket']
        self.assertEqual(ticket['causa_raiz'], 'Falta de capacitacion')
        self.assertEqual(ticket['observaciones'], 'Procedimiento actualizado')
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        response = self.client.put(url, json=self.payload, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket']['causa_raiz'], ticket['causa_raiz'])
        self.assertEqual(response.get_json()['ticket']['observaciones'], ticket['observaciones'])
        response = self.client.put(url, json={**self.payload, 'causa_raiz': 'Causa corregida'}, headers=self.admin)
        self.assertEqual(response.get_json()['ticket']['causa_raiz'], 'Causa corregida')
        self.assertEqual(self.client.get(url, headers=self.admin).get_json()['ticket']['observaciones'], 'Procedimiento actualizado')
        response = self.client.put(url, json={**self.payload, 'causa_raiz': ''}, headers=self.admin)
        self.assertIsNone(response.get_json()['ticket']['causa_raiz'])

    def test_root_cause_is_saved_only_when_followup_is_yes(self):
        for indice, valor in enumerate((False, None)):
            ticket = self.create(numero_ticket=f'ISO-2026-{indice + 1:03d}', amerita_seguimiento=True,
                                 causa_raiz='Causa identificada', observaciones='Resultados a conservar').get_json()['ticket']
            response = self.client.put(f"/api/ticket-iso/{ticket['id_ticket']}",
                json={**self.payload, 'numero_ticket': ticket['numero_ticket'], 'amerita_seguimiento': valor}, headers=self.admin)
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.get_json()['ticket']['causa_raiz'])
            self.assertEqual(response.get_json()['ticket']['observaciones'], 'Resultados a conservar')
        response = self.create(numero_ticket='ISO-2026-003', causa_raiz='No hay seguimiento')
        self.assertIsNone(response.get_json()['ticket']['causa_raiz'])

    def test_root_cause_metadata_is_separate_and_survives_edits(self):
        ticket = self.create(amerita_seguimiento=True, causa_raiz='Causa identificada',
            responsable='Persona descripcion', fecha_registro_descripcion='2026-10-15',
            responsable_accion_inmediata='Persona accion', fecha_accion_inmediata='2026-10-16',
            responsable_causa_raiz='  Persona analisis  ', fecha_causa_raiz='2026-10-17').get_json()['ticket']
        self.assertEqual(ticket['responsable_causa_raiz'], 'Persona analisis')
        self.assertEqual(ticket['fecha_causa_raiz'], '2026-10-17')
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        response = self.client.put(url, json=self.payload, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket']['responsable_causa_raiz'], 'Persona analisis')
        self.assertEqual(response.get_json()['ticket']['fecha_causa_raiz'], '2026-10-17')
        response = self.client.put(url, json={**self.payload, 'responsable_causa_raiz': 'Otra persona', 'fecha_causa_raiz': '2026-10-18'}, headers=self.admin)
        saved = response.get_json()['ticket']
        self.assertEqual(saved['responsable_causa_raiz'], 'Otra persona')
        self.assertEqual(saved['fecha_causa_raiz'], '2026-10-18')
        self.assertEqual(saved['responsable'], 'Persona descripcion')
        self.assertEqual(saved['fecha_registro_descripcion'], '2026-10-15')
        self.assertEqual(saved['responsable_accion_inmediata'], 'Persona accion')
        self.assertEqual(saved['fecha_accion_inmediata'], '2026-10-16')
        saved = self.client.get(url, headers=self.admin).get_json()['ticket']
        self.assertEqual(saved['responsable_causa_raiz'], 'Otra persona')

    def test_disabling_followup_or_clearing_root_metadata_does_not_change_other_blocks(self):
        for indice, valor in enumerate((False, None)):
            ticket = self.create(numero_ticket=f'ISO-2026-{indice + 1:03d}', amerita_seguimiento=True,
                responsable_causa_raiz='Analista', fecha_causa_raiz='2026-10-17',
                responsable_accion_inmediata='Conservar', observaciones='Resultados').get_json()['ticket']
            response = self.client.put(f"/api/ticket-iso/{ticket['id_ticket']}", json={**self.payload,
                'numero_ticket': ticket['numero_ticket'], 'amerita_seguimiento': valor}, headers=self.admin)
            saved = response.get_json()['ticket']
            self.assertIsNone(saved['responsable_causa_raiz'])
            self.assertIsNone(saved['fecha_causa_raiz'])
            self.assertEqual(saved['responsable_accion_inmediata'], 'Conservar')
            self.assertEqual(saved['observaciones'], 'Resultados')
        ticket = self.create(numero_ticket='ISO-2026-003', amerita_seguimiento=True,
                             responsable_causa_raiz='Analista', fecha_causa_raiz='2026-10-17').get_json()['ticket']
        response = self.client.put(f"/api/ticket-iso/{ticket['id_ticket']}", json={**self.payload, 'numero_ticket': ticket['numero_ticket'],
                                  'responsable_causa_raiz': '', 'fecha_causa_raiz': ''}, headers=self.admin)
        self.assertIsNone(response.get_json()['ticket']['responsable_causa_raiz'])
        self.assertIsNone(response.get_json()['ticket']['fecha_causa_raiz'])

    def test_root_metadata_is_optional_and_validated(self):
        ticket = self.create(amerita_seguimiento=True, responsable='No copiar').get_json()['ticket']
        self.assertIsNone(ticket['responsable_causa_raiz'])
        self.assertIsNone(ticket['fecha_causa_raiz'])
        for valor in ('x' * 101, [], 123):
            self.assertEqual(self.create(numero_ticket='ISO-2026-002', amerita_seguimiento=True, responsable_causa_raiz=valor).status_code, 400)
        for valor in ('2026-02-30', '2026-10-17T12:00:00Z', {}, 123):
            self.assertEqual(self.create(numero_ticket='ISO-2026-002', amerita_seguimiento=True, fecha_causa_raiz=valor).status_code, 400)
        self.assertEqual(models.TicketISO.query.count(), 1)

    def test_invalid_root_cause_is_rejected_without_losing_saved_results(self):
        for valor in (123, {}, ['texto'], 'x' * 10001):
            self.assertEqual(self.create(amerita_seguimiento=True, causa_raiz=valor).status_code, 400)
        self.assertEqual(models.TicketISO.query.count(), 0)
        ticket = self.create(amerita_seguimiento=True, causa_raiz='Causa real', observaciones='Resultados reales').get_json()['ticket']
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        response = self.client.put(url, json={**self.payload, 'causa_raiz': 123, 'observaciones': 'No guardar'}, headers=self.admin)
        self.assertEqual(response.status_code, 400)
        saved = self.client.get(url, headers=self.admin).get_json()['ticket']
        self.assertEqual(saved['causa_raiz'], 'Causa real')
        self.assertEqual(saved['observaciones'], 'Resultados reales')

    def test_followup_saves_five_editable_questions_and_answers(self):
        preguntas = [{'pregunta': f'  Pregunta {n}  ', 'respuesta': f'  Respuesta {n}  '} for n in range(5)]
        ticket = self.create(amerita_seguimiento=True, seguimiento_preguntas=preguntas).get_json()['ticket']
        esperadas = [{'pregunta': f'Pregunta {n}', 'respuesta': f'Respuesta {n}'} for n in range(5)]
        self.assertIs(ticket['amerita_seguimiento'], True)
        self.assertEqual(ticket['seguimiento_preguntas'], esperadas)
        self.assertEqual(ticket['estado'], 'pendiente')
        self.assertEqual(ticket['planes_accion'], [])
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        self.assertEqual(self.client.get(url, headers=self.admin).get_json()['ticket']['seguimiento_preguntas'], esperadas)
        self.assertEqual(self.client.get('/api/ticket-iso/', headers=self.admin).get_json()['tickets'][0]['seguimiento_preguntas'], esperadas)
        esperadas[0] = {'pregunta': 'Pregunta corregida', 'respuesta': 'Respuesta corregida'}
        response = self.client.put(url, json={**self.payload, 'seguimiento_preguntas': esperadas}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket']['seguimiento_preguntas'], esperadas)

    def test_followup_can_be_completed_later_and_omitted_fields_are_preserved(self):
        ticket = self.create(amerita_seguimiento=True, accion_inmediata='Medida inicial').get_json()['ticket']
        self.assertEqual(ticket['seguimiento_preguntas'], [{'pregunta': '', 'respuesta': ''} for _ in range(5)])
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        response = self.client.put(url, json=self.payload, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        saved = response.get_json()['ticket']
        self.assertEqual(saved['accion_inmediata'], 'Medida inicial')
        self.assertTrue(saved['amerita_seguimiento'])
        self.assertEqual(saved['seguimiento_preguntas'], ticket['seguimiento_preguntas'])

    def test_clearing_or_disabling_followup_clears_answers_but_keeps_plans(self):
        for indice, valor in enumerate((False, None)):
            ticket = self.create(numero_ticket=f'ISO-2026-{indice + 1:03d}', amerita_seguimiento=True,
                                 accion_inmediata='Medida inicial').get_json()['ticket']
            url = f"/api/ticket-iso/{ticket['id_ticket']}"
            self.client.post(url + '/planes-accion', json={'resultado_plan_accion': 'Plan independiente'}, headers=self.admin)
            response = self.client.put(url, json={**self.payload, 'numero_ticket': ticket['numero_ticket'],
                'amerita_seguimiento': valor, 'seguimiento_preguntas': [], 'accion_inmediata': ''}, headers=self.admin)
            self.assertEqual(response.status_code, 200)
            saved = response.get_json()['ticket']
            self.assertIs(saved['amerita_seguimiento'], valor)
            self.assertEqual(saved['seguimiento_preguntas'], [])
            self.assertIsNone(saved['accion_inmediata'])
            self.assertEqual(len(saved['planes_accion']), 1)

    def test_invalid_followup_is_rejected_without_creating_records(self):
        vacias = [{'pregunta': '', 'respuesta': ''} for _ in range(5)]
        invalidos = [
            {'amerita_seguimiento': valor} for valor in ('si', 'false', 0, 1, [], {})
        ] + [
            {'accion_inmediata': ['No es texto']}, {'accion_inmediata': 'x' * 10001},
            *[{'amerita_seguimiento': True, 'seguimiento_preguntas': valor} for valor in (
                [], vacias[:4], vacias + vacias, {}, 'texto', [None] * 5,
                [{'pregunta': 'x' * 501}] + vacias[1:],
                [{'pregunta': 'Valida', 'respuesta': 'x' * 4001}] + vacias[1:],
                [{'pregunta': 123}] + vacias[1:],
                [{'pregunta': '', 'respuesta': 'Sin pregunta'}] + vacias[1:],
            )],
        ]
        for cambios in invalidos:
            with self.subTest(campos=cambios.keys()):
                self.assertEqual(self.create(**cambios).status_code, 400)
        self.assertEqual(models.TicketISO.query.count(), 0)

    def test_invalid_followup_edit_keeps_saved_content(self):
        ticket = self.create(amerita_seguimiento=True, accion_inmediata='Conservar').get_json()['ticket']
        url = f"/api/ticket-iso/{ticket['id_ticket']}"
        response = self.client.put(url, json={**self.payload, 'accion_inmediata': 'No guardar', 'seguimiento_preguntas': []}, headers=self.admin)
        self.assertEqual(response.status_code, 400)
        saved = self.client.get(url, headers=self.admin).get_json()['ticket']
        self.assertEqual(saved['accion_inmediata'], 'Conservar')
        self.assertEqual(saved['seguimiento_preguntas'], ticket['seguimiento_preguntas'])

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
        self.assertEqual(self.client.post('/api/ticket-iso/999/planes-accion', json={}, headers=self.admin).status_code, 404)
        self.assertEqual(self.client.patch('/api/ticket-iso/999/cierre', json={}, headers=self.admin).status_code, 404)

    def test_seven_action_plans_are_independent_ordered_and_do_not_close_case(self):
        ticket = self.create(responsable='Responsable externo', observaciones='Notas iniciales').get_json()['ticket']
        url = '/api/ticket-iso/' + str(ticket['id_ticket'])
        for number in range(1, 8):
            response = self.client.post(url + '/planes-accion', json={
                'resultado_plan_accion': '  Resultado ' + str(number) + '  ', 'fecha_control': '2026-10-20',
                'problema': 'No sobrescribir', 'responsable': 'No sobrescribir', 'creado_por_nombre': 'Falso',
            }, headers=self.encargado)
            self.assertEqual(response.status_code, 201)
            saved = response.get_json()['ticket']
            self.assertEqual(len(saved['planes_accion']), number)
            self.assertEqual(saved['estado'], 'pendiente')
            self.assertIsNone(saved['fecha_cierre'])
        saved = self.client.get(url, headers=self.admin).get_json()['ticket']
        self.assertEqual([plan['numero'] for plan in saved['planes_accion']], list(range(7, 0, -1)))
        self.assertEqual([plan['resultado_plan_accion'] for plan in saved['planes_accion']], ['Resultado ' + str(n) for n in range(7, 0, -1)])
        self.assertEqual(len({plan['id_plan'] for plan in saved['planes_accion']}), 7)
        self.assertTrue(all(plan['creado_por_nombre'] == 'Jorge' for plan in saved['planes_accion']))
        self.assertEqual(saved['problema'], ticket['problema'])
        self.assertEqual(saved['responsable'], ticket['responsable'])
        self.assertEqual(saved['observaciones'], ticket['observaciones'])
        response = self.client.put(url, json={**self.payload, 'estado': 'en_seguimiento'}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.get_json()['ticket']['planes_accion']), 7)
        self.assertEqual(self.client.put(url, json={**self.payload, 'fecha_recepcion': '2026-10-21'}, headers=self.admin).status_code, 400)

    def test_case_closing_is_separate_and_preserves_all_plans(self):
        ticket = self.create().get_json()['ticket']
        url = '/api/ticket-iso/' + str(ticket['id_ticket'])
        self.client.post(url + '/planes-accion', json={'resultado_plan_accion': 'Resultado inicial', 'fecha_control': '2026-10-15'}, headers=self.admin)
        before = self.client.get(url, headers=self.admin).get_json()['ticket']['planes_accion']
        response = self.client.patch(url + '/cierre', json={'fecha_cierre': '2026-10-16'}, headers=self.encargado)
        self.assertEqual(response.status_code, 200)
        closed = response.get_json()['ticket']
        self.assertEqual(closed['estado'], 'resuelto')
        self.assertEqual(closed['fecha_cierre'], '2026-10-16T15:00:00+00:00')
        self.assertNotIn('creado_por_nombre', closed['planes_accion'][0])
        self.assertEqual(self.client.get(url, headers=self.admin).get_json()['ticket']['planes_accion'], before)
        response = self.client.post(url + '/planes-accion', json={'resultado_plan_accion': 'Nota posterior'}, headers=self.admin)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.get_json()['ticket']['fecha_cierre'], closed['fecha_cierre'])
        self.assertEqual(response.get_json()['ticket']['estado'], 'resuelto')
        self.assertEqual(len(response.get_json()['ticket']['planes_accion']), 2)
        response = self.client.put(url, json={**self.payload, 'estado': 'resuelto', 'fecha_cierre': '2026-10-17'}, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['ticket']['fecha_cierre'], '2026-10-17T15:00:00+00:00')
        self.assertEqual(len(response.get_json()['ticket']['planes_accion']), 2)

    def test_edit_selected_plan_preserves_count_other_plans_author_and_case_closing(self):
        ticket = self.create(estado='resuelto', fecha_cierre='2026-10-20').get_json()['ticket']
        url = '/api/ticket-iso/' + str(ticket['id_ticket'])
        for index in range(7):
            self.client.post(url + '/planes-accion', json={'resultado_plan_accion': 'Plan ' + str(index + 1), 'fecha_control': '2026-10-15'}, headers=self.encargado)
        before = self.client.get(url, headers=self.admin).get_json()['ticket']
        selected = before['planes_accion'][-1]
        response = self.client.patch(url + '/planes-accion/' + str(selected['id_plan']), json={
            'resultado_plan_accion': '  Resultado corregido  ', 'fecha_control': '2026-10-16',
            'ticket_id': 999, 'creado_por_nombre': 'Falso',
        }, headers=self.admin)
        self.assertEqual(response.status_code, 200)
        after = response.get_json()['ticket']
        self.assertEqual(len(after['planes_accion']), 7)
        self.assertEqual(after['planes_accion'][:-1], before['planes_accion'][:-1])
        self.assertEqual(after['planes_accion'][-1], {**selected, 'resultado_plan_accion': 'Resultado corregido', 'fecha_control': '2026-10-16'})
        self.assertEqual(after['estado'], 'resuelto')
        self.assertEqual(after['fecha_cierre'], before['fecha_cierre'])
        self.assertEqual(after['problema'], before['problema'])

    def test_edit_plan_rejects_wrong_ticket_invalid_data_and_keeps_original_record(self):
        first = self.create().get_json()['ticket']
        second = self.create(numero_ticket='OTRO').get_json()['ticket']
        url = '/api/ticket-iso/' + str(first['id_ticket'])
        response = self.client.post(url + '/planes-accion', json={'resultado_plan_accion': 'Original', 'fecha_control': '2026-10-15'}, headers=self.admin)
        plan = response.get_json()['ticket']['planes_accion'][0]
        endpoint = url + '/planes-accion/' + str(plan['id_plan'])
        other = '/api/ticket-iso/' + str(second['id_ticket']) + '/planes-accion/' + str(plan['id_plan'])
        self.assertEqual(self.client.patch(other, json={'resultado_plan_accion': 'Falso'}, headers=self.admin).status_code, 404)
        self.assertEqual(self.client.patch(url + '/planes-accion/999', json={}, headers=self.admin).status_code, 404)
        for payload in [None, [], {}, {'resultado_plan_accion': ' '}, {'resultado_plan_accion': 'x' * 2001},
            {'resultado_plan_accion': 'Nuevo', 'fecha_control': '2026-10-13'},
            {'resultado_plan_accion': 'Nuevo', 'fecha_control': False},
            {'resultado_plan_accion': 'Nuevo', 'fecha_cierre': '2026-10-20'}]:
            self.assertEqual(self.client.patch(endpoint, json=payload, headers=self.encargado).status_code, 400)
        self.assertEqual(self.client.get(url, headers=self.admin).get_json()['ticket']['planes_accion'], [plan])
        response = self.client.patch(endpoint, json={'resultado_plan_accion': 'Corregido', 'fecha_control': None}, headers=self.encargado)
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.get_json()['ticket']['planes_accion'][0]['fecha_control'])

    def test_ticket_iso_role_can_delete_but_other_roles_with_page_access_cannot(self):
        for index, nombre in enumerate(['ticket iso', 'ticket_iso', 'Ticket-ISO']):
            role = models.Role(nombre=nombre.lower())
            user = models.User(name='Encargado ISO', email='iso' + str(index) + '@example.test', password_hash='test', rol=nombre)
            db.session.add_all([role, user])
            db.session.flush()
            db.session.add(models.RolePage(role_id=role.id_role, page_key='ticket_iso'))
            db.session.commit()
            ticket = self.create(numero_ticket='BORRAR-' + str(index)).get_json()['ticket']
            url = '/api/ticket-iso/' + str(ticket['id_ticket'])
            self.assertEqual(self.client.delete(url, headers=self.encargado).status_code, 403)
            self.assertEqual(self.client.delete(url, headers=self.headers(user.id)).status_code, 200)
        ticket = self.create(numero_ticket='PROTEGIDO').get_json()['ticket']
        token = jwt.encode({'user_id': self.encargado_id, 'rol': 'ticket iso'}, auth.SECRET_KEY, algorithm='HS256')
        self.assertEqual(self.client.delete('/api/ticket-iso/' + str(ticket['id_ticket']), headers={'Authorization': 'Bearer ' + token}).status_code, 403)

    def test_action_plan_validates_without_inserting_invalid_records(self):
        ticket = self.create().get_json()['ticket']
        url = '/api/ticket-iso/' + str(ticket['id_ticket']) + '/planes-accion'
        invalid = [None, [], {}, {'resultado_plan_accion': '  '}, {'resultado_plan_accion': 123},
            {'resultado_plan_accion': 'x' * 2001}]
        invalid += [{'resultado_plan_accion': 'Valido', **changes} for changes in [
            {'fecha_control': '2026-02-30'}, {'fecha_control': False}, {'fecha_control': '2026-10-13'},
            {'fecha_cierre': None}, {'fecha_cierre': '2026-10-16'}]]
        for payload in invalid:
            with self.subTest(payload=payload):
                self.assertEqual(self.client.post(url, json=payload, headers=self.admin).status_code, 400)
        self.assertEqual(models.TicketISOPlanAccion.query.count(), 0)
        self.assertEqual(self.client.post(url, json={'resultado_plan_accion': 'Sin control'}, headers=self.admin).status_code, 201)
        self.assertIsNone(models.TicketISOPlanAccion.query.one().fecha_control)

    def test_closing_validates_date_and_deleted_ticket_removes_its_plans(self):
        ticket = self.create().get_json()['ticket']
        url = '/api/ticket-iso/' + str(ticket['id_ticket'])
        for payload in [None, [], {}, {'fecha_cierre': ''}, {'fecha_cierre': False}, {'fecha_cierre': '2026-10-13'}, {'fecha_cierre': '2026-02-30'}]:
            self.assertEqual(self.client.patch(url + '/cierre', json=payload, headers=self.admin).status_code, 400)
        self.client.post(url + '/planes-accion', json={'resultado_plan_accion': 'Plan a eliminar'}, headers=self.admin)
        self.assertEqual(models.TicketISOPlanAccion.query.count(), 1)
        self.assertEqual(self.client.delete(url, headers=self.admin).status_code, 200)
        self.assertEqual(models.TicketISOPlanAccion.query.count(), 0)

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
