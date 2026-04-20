from flask import Blueprint, request, jsonify
from werkzeug.security import check_password_hash
import jwt
import datetime
from sqlalchemy import func

from ..models import User
from ..permissions import get_pages_for_role_name


auth_blueprint = Blueprint('auth', __name__)
SECRET_KEY = "remoto753524"


@auth_blueprint.route('/login', methods=['POST'])
def login():
    data = request.get_json() or {}
    email = (data.get('email') or '').strip()
    password = data.get('password') or ''

    if not email or not password:
        return jsonify({'message': 'Invalid email or password'}), 401

    user = User.query.filter(func.lower(User.email) == email.lower()).first()
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({'message': 'Invalid email or password'}), 401

    token = jwt.encode(
        {
            'user_id': user.id,
            'name': user.name,
            'rol': user.rol,
            'paginas': get_pages_for_role_name(user.rol),
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=1),
        },
        SECRET_KEY,
        algorithm='HS256',
    )
    return jsonify({'message': 'Login successful', 'token': token}), 200


@auth_blueprint.route('/protected', methods=['GET'])
def protected_route():
    token = request.headers.get('Authorization')
    if not token:
        return jsonify({'message': 'Token is missing'}), 401

    try:
        decoded_token = jwt.decode(token.split("Bearer ")[1], SECRET_KEY, algorithms=['HS256'])
        user = User.query.get(decoded_token['user_id'])
        if not user:
            return jsonify({'message': 'Invalid token'}), 401
        return jsonify({'message': f'Welcome {user.name}'}), 200
    except Exception as e:
        return jsonify({'message': 'Token is invalid or expired', 'error': str(e)}), 401
