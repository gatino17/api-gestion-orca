from flask import Blueprint, request, jsonify
from ..models import User
from ..database import db
from werkzeug.security import generate_password_hash


user_blueprint = Blueprint('users', __name__)

@user_blueprint.route('/', methods=['GET'])
def get_users():
    users = User.query.all()
    users_list = [{'id': user.id, 'name': user.name, 'email': user.email, 'rol': user.rol, 'created_at': user.created_at} for user in users]
    return jsonify(users_list)


# Ruta para crear un nuevo usuario
@user_blueprint.route('/', methods=['POST'])
def create_user():
    data = request.get_json()

    # Verificar si los campos necesarios están presentes en la solicitud
    name = data.get('name')
    email = data.get('email')
    rol = data.get('rol')
    password = data.get('password')

    if not name or not email or not rol or not password:
        return jsonify({'message': 'Missing required fields'}), 400
    
    hashed_password = generate_password_hash(password)
    new_user = User(name=name, email=email, rol=rol, password_hash=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    
    return jsonify({'message': 'User created successfully', 'user': {
        'id': new_user.id,
        'name': new_user.name,
        'email': new_user.email,
        'rol': new_user.rol,
        'created_at': new_user.created_at
    }}), 201


# Ruta para actualizar un usuario
@user_blueprint.route('/<int:user_id>', methods=['PUT'])
def update_user(user_id):
    data = request.get_json()
    user = User.query.get(user_id)

    if user is None:
        return jsonify({'message': 'User not found'}), 404

    # Agrega prints para verificar que los datos se reciben y se asignan correctamente
    print("Datos recibidos:", data)
    print("Usuario antes de la actualización:", user.name, user.email, user.rol)

    user.name = data.get('name', user.name)
    user.email = data.get('email', user.email)
    user.rol = data.get('rol', user.rol)

    db.session.commit()
    print("Usuario después de la actualización:", user.name, user.email, user.rol)

    return jsonify({'message': 'User updated successfully', 'user': {
        'id': user.id,
        'name': user.name,
        'email': user.email,
        'rol': user.rol,
        'created_at': user.created_at
    }}), 200



# Ruta para eliminar un usuario
@user_blueprint.route('/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    user = User.query.get(user_id)
    if user is None:
        return jsonify({'message': 'User not found'}), 404

    db.session.delete(user)
    db.session.commit()
    return jsonify({'message': 'User deleted successfully'}), 200

