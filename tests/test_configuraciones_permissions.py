import importlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import jwt
from flask import Flask


# Importa las rutas reales sin iniciar la app ni conectar su base de produccion.
NAMESPACE = '_configuraciones_permissions_tests'
APP_PATH = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NAMESPACE, APP_PATH), (NAMESPACE + '.routes', APP_PATH / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
auth = types.ModuleType(NAMESPACE + '.routes.auth_routes')
auth.SECRET_KEY = 'configuraciones-isolated-test-key'
sys.modules[auth.__name__] = auth
socket = types.ModuleType(NAMESPACE + '.socketio_ext')
socket.emit_roles_event = Mock()
sys.modules[socket.__name__] = socket
models = importlib.import_module(NAMESPACE + '.models')
db = importlib.import_module(NAMESPACE + '.database').db
permissions = importlib.import_module(NAMESPACE + '.permissions')
roles = importlib.import_module(NAMESPACE + '.routes.roles_routes')
diagramas = importlib.import_module(NAMESPACE + '.routes.diagramas_routes')


class ConfiguracionesPermissionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('configuraciones_permissions_tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(roles.roles_blueprint, url_prefix='/api/roles')
        cls.app.register_blueprint(diagramas.diagramas_blueprint, url_prefix='/api/diagramas')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        permissions.seed_default_roles(db)
        self.users = {}
        for role in ['admin', 'soporte', 'editor_planos', 'sin_permisos']:
            user = models.User(name=role, email=role + '@example.test', password_hash='test', rol=role)
            self.users[role] = user
            db.session.add(user)
        self.role = models.Role(nombre='editor_planos')
        db.session.add(self.role)
        db.session.flush()
        db.session.add(models.RolePage(role_id=self.role.id_role, page_key='configuraciones'))
        db.session.commit()
        self.client = self.app.test_client()
        socket.emit_roles_event.reset_mock()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def headers(self, role, expired=False, **claims):
        payload = {
            'user_id': self.users[role].id,
            'exp': datetime.now(timezone.utc) + timedelta(hours=-1 if expired else 1),
            **claims,
        }
        return {'Authorization': 'Bearer ' + jwt.encode(payload, auth.SECRET_KEY, algorithm='HS256')}

    def create(self, role='admin'):
        return self.client.post('/api/diagramas/plantillas', data={'nombre': 'Plano original', 'alcance': 'general'}, headers=self.headers(role))

    def test_catalog_and_defaults_preserve_admin_only_until_granted(self):
        catalog = self.client.get('/api/roles/pages').get_json()
        self.assertIn({'key': 'configuraciones', 'label': 'Configuraciones', 'route': '/configuraciones'}, catalog)
        self.assertIn('configuraciones', permissions.get_pages_for_role_name('admin'))
        for role in ['tecnico', 'soporte', 'operaciones', 'finanzas', 'sin_permisos']:
            self.assertNotIn('configuraciones', permissions.get_pages_for_role_name(role))
        self.assertIn('configuraciones', permissions.get_pages_for_role_name('editor_planos'))

    def test_admin_can_assign_and_revoke_configuraciones_through_roles(self):
        response = self.client.post('/api/roles/', json={'nombre': 'dibujante', 'paginas': ['configuraciones']}, headers=self.headers('admin'))
        self.assertEqual(response.status_code, 201)
        role_id = response.get_json()['rol']['id_role']
        self.assertEqual(permissions.get_pages_for_role_name('dibujante'), ['configuraciones'])
        response = self.client.put(f'/api/roles/{role_id}', json={'paginas': []}, headers=self.headers('admin'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(permissions.get_pages_for_role_name('dibujante'), [])
        self.assertEqual(self.client.delete(f'/api/roles/{role_id}', headers=self.headers('admin')).status_code, 200)

    def test_only_current_admin_can_change_roles(self):
        for method, path in [('POST', '/'), ('PUT', f'/{self.role.id_role}'), ('DELETE', f'/{self.role.id_role}')]:
            for headers, status in [({}, 401), (self.headers('admin', expired=True), 401),
                                    (self.headers('editor_planos', rol='admin'), 403), (self.headers('soporte'), 403)]:
                with self.subTest(method=method, status=status):
                    response = self.client.open('/api/roles' + path, method=method, json={'nombre': 'intruso', 'paginas': ['configuraciones']}, headers=headers)
                    self.assertEqual(response.status_code, status)
        self.assertIsNone(models.Role.query.filter_by(nombre='intruso').first())
        self.assertIsNotNone(db.session.get(models.Role, self.role.id_role))
        socket.emit_roles_event.assert_not_called()

    def test_granted_role_and_admin_can_manage_complete_template_lifecycle(self):
        for role in ['admin', 'editor_planos']:
            with self.subTest(role=role):
                headers = self.headers(role)
                response = self.create(role)
                self.assertEqual(response.status_code, 201, response.get_json())
                item = response.get_json()['plantilla']
                template_id = item['id']
                self.assertEqual(item['creado_por'], role)
                self.assertEqual(self.client.get('/api/diagramas/plantillas', headers=headers).status_code, 200)
                response = self.client.put(f'/api/diagramas/plantillas/{template_id}', data={'nombre': 'Editado', 'alcance': 'general'}, headers=headers)
                self.assertEqual(response.status_code, 200, response.get_json())
                response = self.client.put(f'/api/diagramas/plantillas/{template_id}/contenido', json={'vista_general': {'marcadores': []}, 'diagrama_logico': {'nodos': []}}, headers=headers)
                self.assertEqual(response.status_code, 200, response.get_json())
                response = self.client.post(f'/api/diagramas/plantillas/{template_id}/duplicar', json={'nombre': 'Copia', 'alcance': 'general'}, headers=headers)
                self.assertEqual(response.status_code, 201, response.get_json())
                copy = response.get_json()['plantilla']
                self.assertEqual(copy['creado_por'], role)
                for item_id in [template_id, copy['id']]:
                    self.assertEqual(self.client.delete(f'/api/diagramas/plantillas/{item_id}', headers=headers).status_code, 200)

    def test_all_management_routes_require_session_and_current_permission(self):
        template_id = self.create().get_json()['plantilla']['id']
        endpoints = [('GET', ''), ('POST', ''), ('POST', f'/{template_id}/duplicar'),
                     ('PUT', f'/{template_id}'), ('DELETE', f'/{template_id}'), ('PUT', f'/{template_id}/contenido')]
        for method, path in endpoints:
            for headers, status in [({}, 401), (self.headers('admin', expired=True), 401),
                                    (self.headers('soporte'), 403), (self.headers('sin_permisos', paginas=['configuraciones'], rol='admin'), 403)]:
                with self.subTest(method=method, path=path, status=status):
                    response = self.client.open('/api/diagramas/plantillas' + path, method=method, json={'nombre': 'No autorizado'}, headers=headers)
                    self.assertEqual(response.status_code, status)
        self.assertEqual(models.DiagramaPlantilla.query.count(), 1)

    def test_revocation_applies_even_to_an_existing_token(self):
        headers = self.headers('editor_planos', paginas=['configuraciones'])
        self.assertEqual(self.client.get('/api/diagramas/plantillas', headers=headers).status_code, 200)
        self.client.put(f'/api/roles/{self.role.id_role}', json={'paginas': []}, headers=self.headers('admin'))
        self.assertEqual(self.client.get('/api/diagramas/plantillas', headers=headers).status_code, 403)
        self.client.put(f'/api/roles/{self.role.id_role}', json={'paginas': ['configuraciones']}, headers=self.headers('admin'))
        self.assertEqual(self.client.get('/api/diagramas/plantillas', headers=headers).status_code, 200)

    def test_support_can_still_view_diagrams_without_configuration_access(self):
        self.assertEqual(self.create().status_code, 201)
        self.assertEqual(self.client.get('/api/diagramas/resolver', headers=self.headers('soporte')).status_code, 200)
        self.assertEqual(self.client.get('/api/diagramas/resolver').status_code, 401)


if __name__ == '__main__':
    unittest.main()
