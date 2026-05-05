from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash
import json

from ..models import User, Encargado
from ..database import db


user_blueprint = Blueprint('users', __name__)
SUPERVISOR_AREA_OPCIONES = ('camaras', 'pc', 'energia')


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in ('true', '1', 'si', 'yes', 'y')


def _normalize_supervisor_areas(value):
    if isinstance(value, str):
        raw = [x.strip().lower() for x in value.split(',') if str(x).strip()]
    elif isinstance(value, (list, tuple, set)):
        raw = [str(x).strip().lower() for x in value if str(x).strip()]
    else:
        raw = []

    out = []
    seen = set()
    for item in raw:
        if item in SUPERVISOR_AREA_OPCIONES and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _serialize_supervisor_areas(user):
    raw = user.supervisor_areas
    if not raw:
        return []
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        parsed = []
    return _normalize_supervisor_areas(parsed)


def _serialize_user(user):
    perfil = Encargado.query.filter_by(user_id=user.id).first()
    tecnico = None
    if perfil:
        tecnico = {
            'id_encargado': perfil.id_encargado,
            'nombre_encargado': perfil.nombre_encargado,
            'telefono': perfil.telefono,
            'direccion': perfil.direccion,
            'especialidad': perfil.especialidad,
            'licencia_conducir': perfil.licencia_conducir,
        }
    return {
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'rol': user.rol,
        'created_at': user.created_at,
        'tecnico': tecnico,
        'supervisor_areas': _serialize_supervisor_areas(user),
    }


def _upsert_perfil_tecnico(user, payload):
    if (user.rol or '').lower() != 'tecnico':
        perfil_existente = Encargado.query.filter_by(user_id=user.id).first()
        if perfil_existente:
            perfil_existente.user_id = None
        return

    tecnico_payload = payload.get('tecnico') if isinstance(payload.get('tecnico'), dict) else {}
    perfil = Encargado.query.filter_by(user_id=user.id).first()
    if not perfil:
        perfil = Encargado(user_id=user.id, nombre_encargado=user.name)
        db.session.add(perfil)

    perfil.nombre_encargado = tecnico_payload.get('nombre_encargado') or user.name
    perfil.telefono = tecnico_payload.get('telefono')
    perfil.direccion = tecnico_payload.get('direccion')
    perfil.especialidad = tecnico_payload.get('especialidad')
    perfil.licencia_conducir = _to_bool(tecnico_payload.get('licencia_conducir'))


@user_blueprint.route('/', methods=['GET'])
def get_users():
    users = User.query.all()
    return jsonify([_serialize_user(user) for user in users]), 200


@user_blueprint.route('/', methods=['POST'])
def create_user():
    data = request.get_json() or {}
    name = data.get('name')
    email = data.get('email')
    rol = data.get('rol')
    password = data.get('password')

    if not name or not email or not rol or not password:
        return jsonify({'message': 'Missing required fields'}), 400

    try:
        new_user = User(
            name=name,
            email=email,
            rol=rol,
            password_hash=generate_password_hash(password),
            supervisor_areas=json.dumps(
                _normalize_supervisor_areas(data.get('supervisor_areas') if str(rol).lower() == 'supervisor' else [])
            ),
        )
        db.session.add(new_user)
        db.session.flush()
        _upsert_perfil_tecnico(new_user, data)
        db.session.commit()
        return jsonify({'message': 'User created successfully', 'user': _serialize_user(new_user)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Error creating user: {str(e)}'}), 400


@user_blueprint.route('/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.get_json() or {}
    user = User.query.get(user_id)

    if user is None:
        return jsonify({'message': 'User not found'}), 404

    try:
        user.name = data.get('name', user.name)
        user.email = data.get('email', user.email)
        user.rol = data.get('rol', user.rol)
        if str(user.rol or '').lower() == 'supervisor':
            user.supervisor_areas = json.dumps(_normalize_supervisor_areas(data.get('supervisor_areas')))
        else:
            user.supervisor_areas = json.dumps([])
        password = data.get('password')
        if isinstance(password, str) and password.strip():
            user.password_hash = generate_password_hash(password.strip())

        _upsert_perfil_tecnico(user, data)
        db.session.commit()
        return jsonify({'message': 'User updated successfully', 'user': _serialize_user(user)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': f'Error updating user: {str(e)}'}), 400


@user_blueprint.route('/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    user = User.query.get(user_id)
    if user is None:
        return jsonify({'message': 'User not found'}), 404

    perfil = Encargado.query.filter_by(user_id=user.id).first()
    if perfil:
        perfil.user_id = None

    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted successfully'}), 200
