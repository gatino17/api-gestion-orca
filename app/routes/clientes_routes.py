from flask import Blueprint, request, jsonify
from ..models import Cliente
from ..database import db

clientes_blueprint = Blueprint('clientes', __name__)

# Ruta para obtener todos los clientes
@clientes_blueprint.route('/', methods=['GET'])
def get_clientes():
    clientes = Cliente.query.all()
    clientes_data = [{
        'id_cliente': cliente.id_cliente,
        'nombre': cliente.nombre,
        'telefono': cliente.telefono,
        'correo': cliente.correo,
        'contacto': cliente.contacto,
        'ubicacion': cliente.ubicacion,
        # Opcionalmente podrías incluir la imagen codificada en base64, pero no es recomendado para grandes datos
    } for cliente in clientes]
    return jsonify(clientes_data)

@clientes_blueprint.route('/', methods=['POST'])
def create_cliente():
    data = request.get_json()

    nuevo_cliente = Cliente(
        nombre=data.get('nombre'),
        telefono=data.get('telefono'),
        correo=data.get('correo'),
        contacto=data.get('contacto'),
        ubicacion=data.get('ubicacion'),
        imagen=data.get('imagen')  # Asegúrate de pasar la imagen en base64 o un byte array si es necesario
    )
    db.session.add(nuevo_cliente)
    db.session.commit()

    return jsonify({'message': 'Cliente creado exitosamente', 'cliente': {
        'id_cliente': nuevo_cliente.id_cliente,
        'nombre': nuevo_cliente.nombre,
        'telefono': nuevo_cliente.telefono,
        'correo': nuevo_cliente.correo,
        'contacto': nuevo_cliente.contacto,
        'ubicacion': nuevo_cliente.ubicacion
    }}), 201

# Ruta para actualizar un cliente (JSON)
@clientes_blueprint.route('/<int:id_cliente>', methods=['PUT'])
def update_cliente(id_cliente):
    cliente = Cliente.query.get(id_cliente)
    if cliente is None:
        return jsonify({'message': 'Cliente no encontrado'}), 404

    data = request.get_json()

    cliente.nombre = data.get('nombre', cliente.nombre)
    cliente.telefono = data.get('telefono', cliente.telefono)
    cliente.correo = data.get('correo', cliente.correo)
    cliente.contacto = data.get('contacto', cliente.contacto)
    cliente.ubicacion = data.get('ubicacion', cliente.ubicacion)
    cliente.imagen = data.get('imagen', cliente.imagen)  # Asegúrate de pasar la imagen en base64 o un byte array si es necesario

    db.session.commit()

    return jsonify({'message': 'Cliente actualizado exitosamente', 'cliente': {
        'id_cliente': cliente.id_cliente,
        'nombre': cliente.nombre,
        'telefono': cliente.telefono,
        'correo': cliente.correo,
        'contacto': cliente.contacto,
        'ubicacion': cliente.ubicacion
    }}), 200

# Ruta para eliminar un cliente
@clientes_blueprint.route('/<int:id_cliente>', methods=['DELETE'])
def delete_cliente(id_cliente):
    cliente = Cliente.query.get(id_cliente)
    if cliente is None:
        return jsonify({'message': 'Cliente no encontrado'}), 404

    db.session.delete(cliente)
    db.session.commit()

    return jsonify({'message': 'Cliente eliminado exitosamente'}), 200