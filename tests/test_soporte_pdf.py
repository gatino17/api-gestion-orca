import importlib
import io
import sys
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import jwt
from flask import Flask
from pypdf import PdfReader


# Nunca importa create_app ni conecta con la base de datos del sistema.
NS = '_soporte_pdf_tests'
ROOT = Path(__file__).resolve().parents[1] / 'app'
for name, folder in [(NS, ROOT), (NS + '.routes', ROOT / 'routes')]:
    package = types.ModuleType(name)
    package.__path__ = [str(folder)]
    sys.modules[name] = package
auth = types.ModuleType(NS + '.routes.auth_routes')
auth.SECRET_KEY = 'soporte-pdf-isolated-tests'
sys.modules[auth.__name__] = auth
socket = types.ModuleType(NS + '.socketio_ext')
socket.emit_soporte_event = Mock()
sys.modules[socket.__name__] = socket
models = importlib.import_module(NS + '.models')
db = importlib.import_module(NS + '.database').db
routes = importlib.import_module(NS + '.routes.soporte_routes')
pdf = importlib.import_module(NS + '.soporte_pdf')


class SoportePDFTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask('soporte-pdf-tests')
        cls.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(cls.app)
        cls.app.register_blueprint(routes.soporte_blueprint, url_prefix='/api/soporte')

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.create_all()
        db.session.add_all([models.User(id=i, name=rol, rol=rol, email=rol + '@example.test', password_hash='test')
                            for i, rol in [(1, 'admin'), (2, 'tecnico'), (3, 'inventario')]])
        db.session.add(models.Cliente(id_cliente=1, nombre='Cliente Prueba'))
        razon = models.RazonSocial(cliente_id=1, razon_social='Razon Prueba')
        db.session.add(razon)
        db.session.flush()
        db.session.add(models.Centro(id_centro=1, nombre='Centro Prueba', cliente_id=1, razon_social_id=razon.id_razon_social))
        db.session.add_all([models.Soporte(id_soporte=i, centro_id=1, fecha_soporte=date(2026, 10, i),
            problema=f'Problema del evento {i}', solucion=f'Solucion del evento {i}', tipo='terreno', estado='resuelto',
            creado_por_nombre='Franco Dinamarca' if i < 15 else 'Otra Persona', fecha_cierre=date(2026, 10, i),
            prioridad='media', responsabilidad_falla='cliente', permiso_trabajo=True) for i in range(1, 16)])
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()

    def headers(self, uid=1, **claims):
        return {'Authorization': 'Bearer ' + jwt.encode({'user_id': uid, **claims}, auth.SECRET_KEY, algorithm='HS256')}

    def exportar(self, ids=None, filtros=None, uid=1):
        return self.client.post('/api/soporte/registros/pdf', json={'ids': [3, 2] if ids is None else ids,
            'filtros': {} if filtros is None else filtros}, headers=self.headers(uid))

    def contenido(self, respuesta):
        self.assertEqual(respuesta.status_code, 200, respuesta.get_json(silent=True))
        self.assertEqual(respuesta.mimetype, 'application/pdf')
        return '\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(respuesta.data)).pages)

    def test_descarga_exclusiva_para_admin_y_no_confia_en_rol_del_token(self):
        self.assertEqual(self.client.post('/api/soporte/registros/pdf', json={'ids': [1]}).status_code, 401)
        for uid in (2, 3, 999):
            response = self.client.post('/api/soporte/registros/pdf', json={'ids': [1]}, headers=self.headers(uid, rol='admin'))
            self.assertIn(response.status_code, (401, 403))

    def test_pdf_incluye_solo_ids_filtrados_en_orden_y_detalles_de_la_bd(self):
        respuesta = self.exportar(filtros={'busqueda': 'franco', 'desde': '2026-10-02', 'hasta': '2026-10-03', 'periodo': 'Ano actual'})
        texto = self.contenido(respuesta)
        self.assertIn('OrcaGest', texto)
        self.assertIn('2 eventos', texto)
        for esperado in ('franco', '02/10/2026', '03/10/2026', 'Franco Dinamarca', 'Centro Prueba', 'Cliente Prueba',
                         'Problema del evento 3', 'Solucion del evento 2', 'Responsabilidad', 'Permiso de trabajo'):
            self.assertIn(esperado, texto)
        self.assertNotIn('Soporte #1\n', texto)
        self.assertNotIn('Otra Persona', texto)
        self.assertLess(texto.index('Soporte #3'), texto.index('Soporte #2'))
        self.assertTrue(respuesta.headers['Content-Disposition'].startswith('attachment'))
        self.assertEqual(respuesta.headers['Cache-Control'], 'private, no-store')
        self.assertEqual(respuesta.headers['X-Content-Type-Options'], 'nosniff')
        respuesta.close()

    def test_exporta_todas_las_paginas_no_solo_diez_resultados(self):
        texto = self.contenido(self.exportar(list(range(14, 0, -1))))
        self.assertIn('14 eventos', texto)
        self.assertIn('Soporte #14', texto)
        self.assertIn('Soporte #1', texto)
        self.assertNotIn('Soporte #15', texto)

    def test_resumen_con_descripcion_antes_del_detalle_en_otra_hoja(self):
        respuesta = self.exportar([3, 2])
        lector = PdfReader(io.BytesIO(respuesta.data))
        paginas = [pagina.extract_text() for pagina in lector.pages]
        self.assertGreaterEqual(len(paginas), 2)
        for esperado in ('Resumen de eventos', '#3', '#2', 'Problema del evento 3', 'Centro Prueba', 'Fecha', 'Estado', 'Descripcion'):
            self.assertIn(esperado, paginas[0])
        self.assertNotIn('Detalle de eventos', paginas[0])
        self.assertNotIn('Solucion del evento', paginas[0])
        self.assertIn('Detalle de eventos', paginas[1])
        self.assertIn('Solucion del evento 3', '\n'.join(paginas[1:]))

    def test_encabezado_simple_con_fecha_debajo_del_titulo_y_sin_periodo_general(self):
        respuesta = self.exportar([3, 2], {'busqueda': 'franco', 'periodo': 'Ano actual',
            'periodo_desde': '2026-01-01', 'periodo_hasta': '2026-12-31',
            'desde': '2026-10-02', 'hasta': '2026-10-03'})
        primera = PdfReader(io.BytesIO(respuesta.data)).pages[0].extract_text()
        self.assertIn('Soporte: franco', primera)
        self.assertIn('Rango fecha: 02/10/2026 al 03/10/2026', primera)
        self.assertRegex(primera, r'Fecha: \d{2}/\d{2}/\d{4} \d{2}:\d{2} - Hora de Chile')
        self.assertLess(primera.index('Registros de soporte'), primera.index('Fecha:'))
        self.assertLess(primera.index('Fecha:'), primera.index('2 eventos'))
        for eliminado in ('Busqueda:', 'Periodo de la pagina:', 'Ano actual', 'Periodo:', 'Rango de la tabla:', '01/01/2026', '31/12/2026'):
            self.assertNotIn(eliminado, primera)

    def test_contador_antes_de_caso_y_hora_real_despues_de_fecha(self):
        db.session.get(models.Soporte, 3).created_at = datetime(2026, 10, 3, 13, 45)
        db.session.get(models.Soporte, 2).created_at = datetime(2026, 10, 2, 0, 15)
        db.session.commit()
        original = pdf.LongTable
        tablas = []

        def capturar(filas, **kwargs):
            tablas.append([[celda.getPlainText() for celda in fila] for fila in filas])
            return original(filas, **kwargs)

        with patch.object(pdf, 'LongTable', side_effect=capturar):
            respuesta = self.exportar([3, 2])
        texto = self.contenido(respuesta)
        self.assertEqual(tablas[0][0], ['N', 'Caso', 'Centro / cliente', 'Fecha', 'Hora', 'Estado', 'Descripcion'])
        self.assertEqual([fila[0] for fila in tablas[0][1:]], ['1', '2'])
        self.assertEqual([fila[1] for fila in tablas[0][1:]], ['#3', '#2'])
        self.assertEqual([fila[3] for fila in tablas[0][1:]], ['03/10/2026', '02/10/2026'])
        self.assertEqual([fila[4] for fila in tablas[0][1:]], ['10:45', '21:15'])
        self.assertIn('Hora de creacion: 10:45', texto)
        self.assertIn('Hora de creacion: 21:15', texto)

    def test_hora_de_creacion_respeta_utc_y_cambios_de_horario_de_chile(self):
        self.assertEqual(pdf._hora_creacion(datetime(2026, 7, 3, 13, 45)), '09:45')
        self.assertEqual(pdf._hora_creacion(datetime(2026, 10, 3, 13, 45, tzinfo=timezone.utc)), '10:45')
        self.assertEqual(pdf._hora_creacion(datetime(2026, 10, 3, 10, 45, tzinfo=timezone(timedelta(hours=-3)))), '10:45')
        self.assertEqual(pdf._hora_creacion(None), '-')
        self.assertEqual(pdf._hora_creacion(date(2026, 10, 3)), '-')

    def test_creacion_guarda_hora_real_y_editar_no_la_cambia(self):
        antes = datetime.now(timezone.utc).replace(tzinfo=None)
        respuesta = self.client.post('/api/soporte/', json={'centro_id': 1, 'fecha_soporte': '2026-10-01',
            'tipo': 'remoto', 'problema': 'Nuevo evento', 'created_at': '2000-01-01T00:00:00Z'}, headers=self.headers())
        self.assertEqual(respuesta.status_code, 201)
        sid = respuesta.get_json()['id_soporte']
        registro = db.session.get(models.Soporte, sid)
        original = registro.created_at
        guardado = original.astimezone(timezone.utc).replace(tzinfo=None) if original.tzinfo else original
        self.assertGreaterEqual(guardado, antes)
        self.assertLessEqual(guardado, datetime.now(timezone.utc).replace(tzinfo=None))
        self.assertEqual(self.client.put(f'/api/soporte/{sid}', json={'prioridad': 'alta',
            'created_at': '2000-01-01T00:00:00Z'}, headers=self.headers()).status_code, 200)
        self.assertEqual(db.session.get(models.Soporte, sid).created_at, original)

    def test_resumen_largo_repite_cabeceras_y_no_mezcla_paginas_de_detalle(self):
        registros = [dict(id_soporte=i, centro='Centro', cliente='Cliente', fecha_soporte=date(2026, 10, 1),
                          estado='pendiente', problema=('Descripcion del evento ' + str(i) + ' ') * 15,
                          solucion='Solucion completa ' + str(i)) for i in range(1, 51)]
        archivo = pdf.generar_registros_soporte_pdf(registros, {})
        paginas = [pagina.extract_text() for pagina in PdfReader(archivo).pages]
        inicio_detalle = next(indice for indice, texto in enumerate(paginas) if 'Detalle de eventos' in texto)
        self.assertGreater(inicio_detalle, 1)
        for texto in paginas[:inicio_detalle]:
            self.assertIn('Descripcion', texto)
            self.assertIn('Centro / cliente', texto)
            self.assertNotIn('Solucion completa', texto)
        self.assertIn('#50', '\n'.join(paginas[:inicio_detalle]))
        self.assertIn('Solucion completa 50', '\n'.join(paginas[inicio_detalle:]))

    def test_contador_es_continuo_a_traves_de_paginas_y_no_inventa_horas(self):
        registros = [dict(id_soporte=100 + i, centro='Centro', cliente='Cliente', fecha_soporte=date(2026, 10, 1),
                          problema='Problema de prueba ' * 10) for i in range(1, 51)]
        original = pdf.LongTable
        tablas = []

        def capturar(filas, **kwargs):
            tablas.append([[celda.getPlainText() for celda in fila] for fila in filas])
            return original(filas, **kwargs)

        with patch.object(pdf, 'LongTable', side_effect=capturar):
            archivo = pdf.generar_registros_soporte_pdf(registros, {})
        paginas = [pagina.extract_text() for pagina in PdfReader(archivo).pages]
        inicio_detalle = next(indice for indice, texto in enumerate(paginas) if 'Detalle de eventos' in texto)
        self.assertGreater(inicio_detalle, 1)
        self.assertEqual([fila[0] for fila in tablas[0][1:]], [str(i) for i in range(1, 51)])
        self.assertEqual([fila[4] for fila in tablas[0][1:]], ['-'] * 50)

    def test_metadatos_en_tres_columnas_ocupan_menos_altura(self):
        original = pdf.Table
        medidas = []

        def medir(*args, **kwargs):
            tabla = original(*args, **kwargs)
            medidas.append((len(kwargs['colWidths']), tabla.wrap(500, 700)[1]))
            return tabla

        with patch.object(pdf, 'Table', side_effect=medir):
            self.contenido(self.exportar([1]))
        self.assertEqual(len(medidas), 1)
        self.assertEqual(medidas[0][0], 3)
        self.assertLess(medidas[0][1], 110)

    def test_valida_ids_vacios_repetidos_malformados_y_limite(self):
        for ids in ([], [True], [1.5], ['1'], [-1], [0], [1, 1], [2147483648], list(range(1, 5002)), 'todos'):
            self.assertEqual(self.exportar(ids).status_code, 400)

    def test_rechaza_solicitud_sin_json_y_filtros_invalidos(self):
        self.assertEqual(self.client.post('/api/soporte/registros/pdf', data='no-json', headers=self.headers()).status_code, 400)
        for filtros in ([], {'no_existe': 'x'}, {'busqueda': 10}, {'busqueda': 'x' * 501},
                        {'desde': '2026-02-30'}, {'desde': '2026-10-15', 'hasta': '2026-10-01'},
                        {'periodo_desde': '2027-01-01', 'periodo_hasta': '2026-12-31'}):
            self.assertEqual(self.exportar(filtros=filtros).status_code, 400)

    def test_registro_eliminado_no_produce_un_informe_incompleto(self):
        self.assertEqual(self.exportar([1, 999]).status_code, 409)

    def test_error_de_generacion_es_controlado_y_no_modifica_eventos(self):
        with patch.object(pdf, 'generar_registros_soporte_pdf', side_effect=RuntimeError('Error simulado')):
            respuesta = self.exportar()
        self.assertEqual(respuesta.status_code, 500)
        self.assertIn('No se pudo generar', respuesta.get_json()['error'])
        self.assertEqual(models.Soporte.query.count(), 15)

    def test_textos_largos_y_etiquetas_no_se_truncan_ni_interpretan_como_html(self):
        registro = db.session.get(models.Soporte, 1)
        registro.problema = '<b>texto literal & seguro</b> ' + ('detalle ' * 4000) + 'FIN_PROBLEMA'
        registro.solucion = 'Solucion completa FIN_SOLUCION'
        registro.sugerencia = 'Sugerencia de terreno'
        registro.creado_por_nombre = None
        db.session.commit()
        texto = self.contenido(self.exportar([1], {'busqueda': '<b> & filtro'}))
        self.assertIn('1 evento', texto)
        self.assertNotIn('1 eventos', texto)
        self.assertIn('<b>texto literal & seguro</b>', texto)
        self.assertIn('FIN_PROBLEMA', texto)
        self.assertIn('FIN_SOLUCION', texto)
        self.assertIn('Sugerencia de terreno', texto)
        self.assertNotIn('Creado por', texto)


if __name__ == '__main__':
    unittest.main()
