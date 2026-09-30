import json
import os
import re
import shutil
from uuid import uuid4

import jwt
from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from ..database import db
from ..models import Centro, Cliente, DiagramaPlantilla, EquiposIP, User
from .auth_routes import SECRET_KEY


diagramas_blueprint = Blueprint('diagramas', __name__)

ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}
ALLOWED_MARKER_TYPES = {
    'internet', 'camara', 'ptz', 'termal', 'radar', 'router', 'switch',
    'computador', 'nvr', 'netio', 'axis', 'victron', 'sensor', 'luminaria',
    'bocina', 'transformador', 'tablero', 'energia', 'otro',
}


def _usuario_actual():
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer '):
        return None
    try:
        payload = jwt.decode(authorization[7:], SECRET_KEY, algorithms=['HS256'])
        return db.session.get(User, payload.get('user_id'))
    except Exception:
        return None


def _admin_actual():
    usuario = _usuario_actual()
    return usuario if usuario and str(usuario.rol or '').strip().lower() == 'admin' else None


def _ruta_imagen_relativa(nombre_archivo):
    return f"diagramas/{nombre_archivo}"


def _directorio_imagenes():
    directorio = os.path.join(current_app.root_path, 'uploads', 'diagramas')
    os.makedirs(directorio, exist_ok=True)
    return directorio


def _guardar_imagen(archivo):
    if not archivo or not archivo.filename:
        return None
    nombre_seguro = secure_filename(archivo.filename)
    extension = nombre_seguro.rsplit('.', 1)[-1].lower() if '.' in nombre_seguro else ''
    if extension not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError('La imagen debe ser PNG, JPG, JPEG o WEBP.')
    nombre_archivo = f"{uuid4().hex}.{extension}"
    archivo.save(os.path.join(_directorio_imagenes(), nombre_archivo))
    return _ruta_imagen_relativa(nombre_archivo)


def _duplicar_imagen(ruta_relativa):
    if not ruta_relativa or not str(ruta_relativa).startswith('diagramas/'):
        return None
    origen = os.path.abspath(os.path.join(current_app.root_path, 'uploads', ruta_relativa))
    if not os.path.isfile(origen):
        return None
    extension = os.path.splitext(origen)[1].lower()
    nombre_archivo = f"{uuid4().hex}{extension}"
    shutil.copy2(origen, os.path.join(_directorio_imagenes(), nombre_archivo))
    return _ruta_imagen_relativa(nombre_archivo)


def _contenido_sin_equipos_fisicos(valor, clave_lista):
    try:
        contenido = json.loads(valor or '{}') if isinstance(valor, str) else dict(valor or {})
    except (TypeError, ValueError, json.JSONDecodeError):
        contenido = {}
    for item in contenido.get(clave_lista, []) if isinstance(contenido.get(clave_lista), list) else []:
        if isinstance(item, dict):
            item['equipo_id'] = None
    return contenido


def _eliminar_imagen(ruta_relativa):
    if not ruta_relativa or not str(ruta_relativa).startswith('diagramas/'):
        return
    ruta = os.path.abspath(os.path.join(current_app.root_path, 'uploads', ruta_relativa))
    raiz = os.path.abspath(os.path.join(current_app.root_path, 'uploads', 'diagramas'))
    if os.path.commonpath([ruta, raiz]) == raiz and os.path.isfile(ruta):
        os.remove(ruta)


def _imagen_url(ruta_relativa):
    return f"/api/uploads/{ruta_relativa}" if ruta_relativa else None


def _serializar(plantilla):
    return {
        'id': plantilla.id_plantilla,
        'nombre': plantilla.nombre,
        'descripcion': plantilla.descripcion or '',
        'alcance': plantilla.alcance,
        'cliente_id': plantilla.cliente_id,
        'cliente': plantilla.cliente.nombre if plantilla.cliente else None,
        'centro_id': plantilla.centro_id,
        'centro': plantilla.centro.nombre if plantilla.centro else None,
        'imagen_general': _imagen_url(plantilla.imagen_general),
        'vista_general_json': plantilla.vista_general_json or '{}',
        'diagrama_logico_json': plantilla.diagrama_logico_json or '{}',
        'estado': plantilla.estado,
        'creado_por': plantilla.creado_por.name if plantilla.creado_por else None,
        'created_at': plantilla.created_at.isoformat() if plantilla.created_at else None,
        'updated_at': plantilla.updated_at.isoformat() if plantilla.updated_at else None,
    }


def _resolver_asignacion(data):
    alcance = str(data.get('alcance') or 'general').strip().lower()
    if alcance not in {'general', 'cliente', 'centro'}:
        raise ValueError('El alcance seleccionado no es valido.')

    if alcance == 'general':
        return alcance, None, None

    if alcance == 'cliente':
        try:
            cliente_id = int(data.get('cliente_id'))
        except (TypeError, ValueError):
            raise ValueError('Selecciona un cliente para esta plantilla.')
        if not db.session.get(Cliente, cliente_id):
            raise ValueError('El cliente seleccionado no existe.')
        return alcance, cliente_id, None

    try:
        centro_id = int(data.get('centro_id'))
    except (TypeError, ValueError):
        raise ValueError('Selecciona un centro para esta plantilla.')
    centro = db.session.get(Centro, centro_id)
    if not centro:
        raise ValueError('El centro seleccionado no existe.')
    return alcance, centro.cliente_id, centro.id_centro


def _normalizar_vista_general(payload):
    if not isinstance(payload, dict):
        raise ValueError('El contenido de la vista general no es valido.')
    marcadores = payload.get('marcadores', [])
    if not isinstance(marcadores, list) or len(marcadores) > 500:
        raise ValueError('La lista de marcadores no es valida.')

    resultado = []
    for indice, marcador in enumerate(marcadores):
        if not isinstance(marcador, dict):
            raise ValueError('Uno de los marcadores no es valido.')
        nombre = str(marcador.get('nombre') or '').strip()[:120]
        if not nombre:
            raise ValueError('Todos los marcadores deben tener un nombre.')
        tipo = str(marcador.get('tipo') or 'otro').strip().lower()
        if tipo not in ALLOWED_MARKER_TYPES:
            tipo = 'otro'
        color = str(marcador.get('color') or '#ef4444').strip().lower()
        if not re.fullmatch(r'#[0-9a-f]{6}', color):
            color = '#ef4444'
        try:
            x = min(100.0, max(0.0, float(marcador.get('x', 50))))
            y = min(100.0, max(0.0, float(marcador.get('y', 50))))
        except (TypeError, ValueError):
            raise ValueError('La posicion de un marcador no es valida.')
        equipo_id = marcador.get('equipo_id')
        try:
            equipo_id = int(equipo_id) if equipo_id not in (None, '') else None
        except (TypeError, ValueError):
            equipo_id = None
        resultado.append({
            'id': str(marcador.get('id') or f'marcador-{indice + 1}')[:80],
            'nombre': nombre,
            'tipo': tipo,
            'tipo_equipo': str(marcador.get('tipo_equipo') or '').strip()[:120],
            'color': color,
            'x': round(x, 3),
            'y': round(y, 3),
            'equipo_id': equipo_id,
            'zona_id': str(marcador.get('zona_id') or '').strip()[:80],
            'descripcion': str(marcador.get('descripcion') or '').strip()[:500],
        })
    zonas = payload.get('zonas', [])
    if not isinstance(zonas, list) or len(zonas) > 200:
        raise ValueError('La lista de zonas no es valida.')
    zonas_resultado = []
    for indice, zona in enumerate(zonas):
        if not isinstance(zona, dict):
            raise ValueError('Una de las zonas no es valida.')
        nombre = str(zona.get('nombre') or '').strip()[:120]
        if not nombre:
            raise ValueError('Todas las zonas deben tener un nombre.')
        color = str(zona.get('color') or '#0ea5e9').strip().lower()
        if not re.fullmatch(r'#[0-9a-f]{6}', color):
            color = '#0ea5e9'
        try:
            x = min(100.0, max(0.0, float(zona.get('x', 40))))
            y = min(100.0, max(0.0, float(zona.get('y', 40))))
            ancho = min(100.0, max(5.0, float(zona.get('ancho', 20))))
            alto = min(100.0, max(5.0, float(zona.get('alto', 15))))
            opacidad = min(0.8, max(0.0, float(zona.get('opacidad', 0.2))))
        except (TypeError, ValueError):
            raise ValueError('Las dimensiones de una zona no son validas.')
        zonas_resultado.append({
            'id': str(zona.get('id') or f'zona-{indice + 1}')[:80],
            'nombre': nombre,
            'color': color,
            'x': round(x, 3),
            'y': round(y, 3),
            'ancho': round(ancho, 3),
            'alto': round(alto, 3),
            'opacidad': round(opacidad, 2),
        })
    return {'version': 1, 'marcadores': resultado, 'zonas': zonas_resultado}


def _normalizar_diagrama_logico(payload):
    if not isinstance(payload, dict):
        raise ValueError('El contenido del diagrama logico no es valido.')
    nodos = payload.get('nodos', [])
    conexiones = payload.get('conexiones', [])
    grupos = payload.get('grupos', [])
    if not isinstance(nodos, list) or len(nodos) > 300:
        raise ValueError('La lista de nodos no es valida.')
    if not isinstance(conexiones, list) or len(conexiones) > 600:
        raise ValueError('La lista de conexiones no es valida.')
    if not isinstance(grupos, list) or len(grupos) > 100:
        raise ValueError('La lista de grupos no es valida.')

    nodos_resultado = []
    ids_nodos = set()
    for indice, nodo in enumerate(nodos):
        if not isinstance(nodo, dict):
            raise ValueError('Uno de los nodos no es valido.')
        nombre = str(nodo.get('nombre') or '').strip()[:120]
        if not nombre:
            raise ValueError('Todos los nodos deben tener un nombre.')
        nodo_id = str(nodo.get('id') or f'nodo-{indice + 1}')[:80]
        if nodo_id in ids_nodos:
            raise ValueError('El diagrama contiene nodos duplicados.')
        ids_nodos.add(nodo_id)
        tipo = str(nodo.get('tipo') or 'otro').strip().lower()
        if tipo not in ALLOWED_MARKER_TYPES:
            tipo = 'otro'
        color = str(nodo.get('color') or '#0ea5e9').strip().lower()
        if not re.fullmatch(r'#[0-9a-f]{6}', color):
            color = '#0ea5e9'
        try:
            x = min(100.0, max(0.0, float(nodo.get('x', 50))))
            y = min(100.0, max(0.0, float(nodo.get('y', 50))))
        except (TypeError, ValueError):
            raise ValueError('La posicion de un nodo no es valida.')
        equipo_id = nodo.get('equipo_id')
        try:
            equipo_id = int(equipo_id) if equipo_id not in (None, '') else None
        except (TypeError, ValueError):
            equipo_id = None
        nodos_resultado.append({
            'id': nodo_id,
            'nombre': nombre,
            'tipo': tipo,
            'tipo_equipo': str(nodo.get('tipo_equipo') or '').strip()[:120],
            'color': color,
            'x': round(x, 3),
            'y': round(y, 3),
            'equipo_id': equipo_id,
            'descripcion': str(nodo.get('descripcion') or '').strip()[:500],
        })

    conexiones_resultado = []
    pares = set()
    for indice, conexion in enumerate(conexiones):
        if not isinstance(conexion, dict):
            raise ValueError('Una de las conexiones no es valida.')
        origen = str(conexion.get('origen') or '')[:80]
        destino = str(conexion.get('destino') or '')[:80]
        if origen not in ids_nodos or destino not in ids_nodos or origen == destino:
            raise ValueError('Una conexion referencia nodos no validos.')
        par = (origen, destino)
        par_inverso = (destino, origen)
        if par in pares or par_inverso in pares:
            continue
        pares.add(par)
        color_conexion = str(conexion.get('color') or '#38d2f2').strip().lower()
        if not re.fullmatch(r'#[0-9a-f]{6}', color_conexion):
            color_conexion = '#38d2f2'
        conexiones_resultado.append({
            'id': str(conexion.get('id') or f'conexion-{indice + 1}')[:80],
            'origen': origen,
            'destino': destino,
            'color': color_conexion,
        })
    grupos_resultado = []
    for indice, grupo in enumerate(grupos):
        if not isinstance(grupo, dict):
            raise ValueError('Uno de los grupos no es valido.')
        nombre = str(grupo.get('nombre') or '').strip()[:120]
        if not nombre:
            raise ValueError('Todos los grupos deben tener un nombre.')
        color = str(grupo.get('color') or '#0ea5e9').strip().lower()
        if not re.fullmatch(r'#[0-9a-f]{6}', color):
            color = '#0ea5e9'
        try:
            x = min(100.0, max(0.0, float(grupo.get('x', 50))))
            y = min(100.0, max(0.0, float(grupo.get('y', 50))))
            ancho = min(100.0, max(10.0, float(grupo.get('ancho', 35))))
            alto = min(100.0, max(10.0, float(grupo.get('alto', 30))))
            opacidad = min(0.6, max(0.0, float(grupo.get('opacidad', 0.12))))
        except (TypeError, ValueError):
            raise ValueError('Las dimensiones de un grupo no son validas.')
        grupos_resultado.append({
            'id': str(grupo.get('id') or f'grupo-{indice + 1}')[:80],
            'nombre': nombre,
            'color': color,
            'x': round(x, 3),
            'y': round(y, 3),
            'ancho': round(ancho, 3),
            'alto': round(alto, 3),
            'opacidad': round(opacidad, 2),
        })
    return {
        'version': 1,
        'nodos': nodos_resultado,
        'conexiones': conexiones_resultado,
        'grupos': grupos_resultado,
    }


@diagramas_blueprint.route('/plantillas', methods=['GET'])
def listar_plantillas():
    if not _admin_actual():
        return jsonify({'error': 'Acceso exclusivo para administradores.'}), 403
    plantillas = DiagramaPlantilla.query.order_by(
        DiagramaPlantilla.estado.asc(),
        DiagramaPlantilla.updated_at.desc(),
    ).all()
    return jsonify({'plantillas': [_serializar(item) for item in plantillas]})


@diagramas_blueprint.route('/resolver', methods=['GET'])
def resolver_plantilla():
    if not _usuario_actual():
        return jsonify({'error': 'Sesion invalida o expirada.'}), 401

    centro_id = request.args.get('centro_id', type=int)
    cliente_id = request.args.get('cliente_id', type=int)
    centro = None
    if centro_id:
        centro = db.session.get(Centro, centro_id)
        if not centro:
            return jsonify({'error': 'El centro seleccionado no existe.'}), 404
        cliente_id = centro.cliente_id

    orden = (DiagramaPlantilla.updated_at.desc(), DiagramaPlantilla.id_plantilla.desc())
    plantilla = None
    origen = None

    if centro:
        plantilla = (
            DiagramaPlantilla.query
            .filter_by(estado='activo', alcance='centro', centro_id=centro.id_centro)
            .order_by(*orden)
            .first()
        )
        if plantilla:
            origen = 'centro'

    if not plantilla and cliente_id:
        plantilla = (
            DiagramaPlantilla.query
            .filter_by(estado='activo', alcance='cliente', cliente_id=cliente_id)
            .order_by(*orden)
            .first()
        )
        if plantilla:
            origen = 'cliente'

    if not plantilla:
        plantilla = (
            DiagramaPlantilla.query
            .filter_by(estado='activo', alcance='general')
            .order_by(*orden)
            .first()
        )
        if plantilla:
            origen = 'general'

    return jsonify({
        'plantilla': _serializar(plantilla) if plantilla else None,
        'origen': origen,
        'centro_id': centro.id_centro if centro else None,
        'cliente_id': cliente_id,
    })


@diagramas_blueprint.route('/plantillas', methods=['POST'])
def crear_plantilla():
    usuario = _admin_actual()
    if not usuario:
        return jsonify({'error': 'Acceso exclusivo para administradores.'}), 403

    data = request.form
    nombre = str(data.get('nombre') or '').strip()
    if not nombre:
        return jsonify({'error': 'Ingresa un nombre para la plantilla.'}), 400

    imagen = None
    try:
        alcance, cliente_id, centro_id = _resolver_asignacion(data)
        imagen = _guardar_imagen(request.files.get('imagen_general'))
        plantilla = DiagramaPlantilla(
            nombre=nombre,
            descripcion=str(data.get('descripcion') or '').strip(),
            alcance=alcance,
            cliente_id=cliente_id,
            centro_id=centro_id,
            imagen_general=imagen,
            vista_general_json='{}',
            diagrama_logico_json='{}',
            estado='activo' if str(data.get('estado') or 'activo').lower() == 'activo' else 'inactivo',
            creado_por_id=usuario.id,
        )
        db.session.add(plantilla)
        db.session.commit()
        return jsonify({'message': 'Plantilla creada correctamente.', 'plantilla': _serializar(plantilla)}), 201
    except ValueError as exc:
        if imagen:
            _eliminar_imagen(imagen)
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        if imagen:
            _eliminar_imagen(imagen)
        return jsonify({'error': f'No se pudo crear la plantilla: {str(exc)}'}), 500


@diagramas_blueprint.route('/plantillas/<int:plantilla_id>/duplicar', methods=['POST'])
def duplicar_plantilla(plantilla_id):
    usuario = _admin_actual()
    if not usuario:
        return jsonify({'error': 'Acceso exclusivo para administradores.'}), 403
    origen = db.session.get(DiagramaPlantilla, plantilla_id)
    if not origen:
        return jsonify({'error': 'La plantilla de origen no existe.'}), 404

    data = request.get_json(silent=True) or {}
    nombre = str(data.get('nombre') or '').strip()
    if not nombre:
        return jsonify({'error': 'Ingresa un nombre para la nueva plantilla.'}), 400

    imagen_copiada = None
    try:
        alcance, cliente_id, centro_id = _resolver_asignacion(data)
        vista_general = _normalizar_vista_general(
            _contenido_sin_equipos_fisicos(origen.vista_general_json, 'marcadores')
        )
        diagrama_logico = _normalizar_diagrama_logico(
            _contenido_sin_equipos_fisicos(origen.diagrama_logico_json, 'nodos')
        )
        imagen_copiada = _duplicar_imagen(origen.imagen_general)
        duplicada = DiagramaPlantilla(
            nombre=nombre,
            descripcion=str(data.get('descripcion') if data.get('descripcion') is not None else origen.descripcion or '').strip(),
            alcance=alcance,
            cliente_id=cliente_id,
            centro_id=centro_id,
            imagen_general=imagen_copiada,
            vista_general_json=json.dumps(vista_general, ensure_ascii=False),
            diagrama_logico_json=json.dumps(diagrama_logico, ensure_ascii=False),
            estado='activo' if str(data.get('estado') or 'activo').lower() == 'activo' else 'inactivo',
            creado_por_id=usuario.id,
        )
        db.session.add(duplicada)
        db.session.commit()
        return jsonify({'message': 'Plantilla duplicada correctamente.', 'plantilla': _serializar(duplicada)}), 201
    except ValueError as exc:
        if imagen_copiada:
            _eliminar_imagen(imagen_copiada)
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        if imagen_copiada:
            _eliminar_imagen(imagen_copiada)
        return jsonify({'error': f'No se pudo duplicar la plantilla: {str(exc)}'}), 500


@diagramas_blueprint.route('/plantillas/<int:plantilla_id>', methods=['PUT'])
def actualizar_plantilla(plantilla_id):
    if not _admin_actual():
        return jsonify({'error': 'Acceso exclusivo para administradores.'}), 403
    plantilla = db.session.get(DiagramaPlantilla, plantilla_id)
    if not plantilla:
        return jsonify({'error': 'Plantilla no encontrada.'}), 404

    data = request.form
    nombre = str(data.get('nombre') or '').strip()
    if not nombre:
        return jsonify({'error': 'Ingresa un nombre para la plantilla.'}), 400

    imagen_anterior = plantilla.imagen_general
    imagen_nueva = None
    try:
        alcance, cliente_id, centro_id = _resolver_asignacion(data)
        imagen_nueva = _guardar_imagen(request.files.get('imagen_general'))
        plantilla.nombre = nombre
        plantilla.descripcion = str(data.get('descripcion') or '').strip()
        plantilla.alcance = alcance
        plantilla.cliente_id = cliente_id
        plantilla.centro_id = centro_id
        plantilla.estado = 'activo' if str(data.get('estado') or 'activo').lower() == 'activo' else 'inactivo'
        if imagen_nueva:
            plantilla.imagen_general = imagen_nueva
        db.session.commit()
        if imagen_nueva and imagen_anterior:
            _eliminar_imagen(imagen_anterior)
        return jsonify({'message': 'Plantilla actualizada correctamente.', 'plantilla': _serializar(plantilla)})
    except ValueError as exc:
        if imagen_nueva:
            _eliminar_imagen(imagen_nueva)
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        if imagen_nueva:
            _eliminar_imagen(imagen_nueva)
        return jsonify({'error': f'No se pudo actualizar la plantilla: {str(exc)}'}), 500


@diagramas_blueprint.route('/plantillas/<int:plantilla_id>', methods=['DELETE'])
def eliminar_plantilla(plantilla_id):
    if not _admin_actual():
        return jsonify({'error': 'Acceso exclusivo para administradores.'}), 403
    plantilla = db.session.get(DiagramaPlantilla, plantilla_id)
    if not plantilla:
        return jsonify({'error': 'Plantilla no encontrada.'}), 404
    imagen = plantilla.imagen_general
    try:
        db.session.delete(plantilla)
        db.session.commit()
        _eliminar_imagen(imagen)
        return jsonify({'message': 'Plantilla eliminada correctamente.'})
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': f'No se pudo eliminar la plantilla: {str(exc)}'}), 500


@diagramas_blueprint.route('/plantillas/<int:plantilla_id>/contenido', methods=['PUT'])
def guardar_contenido_plantilla(plantilla_id):
    if not _admin_actual():
        return jsonify({'error': 'Acceso exclusivo para administradores.'}), 403
    plantilla = db.session.get(DiagramaPlantilla, plantilla_id)
    if not plantilla:
        return jsonify({'error': 'Plantilla no encontrada.'}), 404

    data = request.get_json(silent=True) or {}
    if 'vista_general' not in data and 'diagrama_logico' not in data:
        return jsonify({'error': 'No se recibio contenido para guardar.'}), 400
    try:
        vista_general = None
        diagrama_logico = None
        if 'vista_general' in data:
            vista_general = _normalizar_vista_general(data.get('vista_general'))
        if 'diagrama_logico' in data:
            diagrama_logico = _normalizar_diagrama_logico(data.get('diagrama_logico'))
        equipos_asociados = set()
        if vista_general:
            equipos_asociados.update(
                item['equipo_id'] for item in vista_general['marcadores'] if item.get('equipo_id')
            )
        if diagrama_logico:
            equipos_asociados.update(
                item['equipo_id'] for item in diagrama_logico['nodos'] if item.get('equipo_id')
            )
        if equipos_asociados:
            if not plantilla.centro_id:
                raise ValueError('Solo una plantilla por centro puede asociar equipos reales.')
            equipos_validos = {
                item.id_equipo for item in EquiposIP.query.filter(
                    EquiposIP.centro_id == plantilla.centro_id,
                    EquiposIP.id_equipo.in_(equipos_asociados),
                ).all()
            }
            if equipos_validos != equipos_asociados:
                raise ValueError('Uno de los equipos no pertenece al centro de la plantilla.')
        if vista_general:
            plantilla.vista_general_json = json.dumps(vista_general, ensure_ascii=True, separators=(',', ':'))
        if diagrama_logico:
            plantilla.diagrama_logico_json = json.dumps(diagrama_logico, ensure_ascii=True, separators=(',', ':'))
        db.session.commit()
        return jsonify({
            'message': 'Contenido del diagrama guardado correctamente.',
            'plantilla': _serializar(plantilla),
        })
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception as exc:
        db.session.rollback()
        return jsonify({'error': f'No se pudo guardar la vista general: {str(exc)}'}), 500
