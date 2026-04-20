from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash

from ..models import User, Encargado
from ..database import db


user_blueprint = Blueprint('users', __name__)


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in ('true', '1', 'si', 'yes', 'y')


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
