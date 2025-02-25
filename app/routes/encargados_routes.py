from flask import Blueprint, request, jsonify
from ..models import Encargado, db

encargados_bp = Blueprint('encargados', __name__)

@encargados_bp.route('/', methods=['POST'])
def crear_encargado():
    data = request.get_json()
    nuevo_encargado = Encargado(
        nombre_encargado=data['nombre_encargado'],
        telefono=data.get('telefono'),
        direccion=data.get('direccion'),
        especialidad=data.get('especialidad'),
        licencia_conducir=data.get('licencia_conducir', False)
    )
    db.session.add(nuevo_encargado)
    db.session.commit()
    return jsonify({"message": "Encargado creado exitosamente"}), 201

@encargados_bp.route('/', methods=['GET'])
def obtener_encargados():
    encargados = Encargado.query.all()
    # Incluye todos los detalles de cada encargado en el JSON de respuesta
    resultado = [
        {
            "id_encargado": enc.id_encargado,
            "nombre_encargado": enc.nombre_encargado,
            "telefono": enc.telefono,
            "direccion": enc.direccion,
            "especialidad": enc.especialidad,
            "licencia_conducir": enc.licencia_conducir
        }
        for enc in encargados
    ]
    return jsonify(resultado), 200


@encargados_bp.route('/<int:id>', methods=['PUT'])
def actualizar_encargado(id):
    data = request.get_json()
    encargado = Encargado.query.get_or_404(id)
    encargado.nombre_encargado = data.get('nombre_encargado', encargado.nombre_encargado)
    encargado.telefono = data.get('telefono', encargado.telefono)
    encargado.direccion = data.get('direccion', encargado.direccion)
    encargado.especialidad = data.get('especialidad', encargado.especialidad)
    encargado.licencia_conducir = data.get('licencia_conducir', encargado.licencia_conducir)
    db.session.commit()
    return jsonify({"message": "Encargado actualizado exitosamente"}), 200

@encargados_bp.route('/<int:id>', methods=['DELETE'])
def eliminar_encargado(id):
    encargado = Encargado.query.get_or_404(id)
    db.session.delete(encargado)
    db.session.commit()
    return jsonify({"message": "Encargado eliminado exitosamente"}), 200
