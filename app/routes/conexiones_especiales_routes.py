from flask import Blueprint, request, jsonify
from ..models import ConexionesEspeciales, db

conexiones_bp = Blueprint('conexiones', __name__)

# Obtener todas las conexiones o conexiones por centro_id
@conexiones_bp.route('/', methods=['GET'])
def obtener_conexiones():
    centro_id = request.args.get('centro_id', type=int)  # Permite filtrar por centro_id
    if centro_id:
        conexiones = ConexionesEspeciales.query.filter_by(centro_id=centro_id).all()
    else:
        conexiones = ConexionesEspeciales.query.all()
        
    conexiones_data = [
        {
            "id": conexion.id,
            "centro_id": conexion.centro_id,
            "nombre": conexion.nombre,
            "numero_conexion": conexion.numero_conexion
        } for conexion in conexiones
    ]
    
    return jsonify(conexiones_data), 200

# Crear conexión especial
@conexiones_bp.route('/', methods=['POST'])
def crear_conexion():
    data = request.json
    try:
        nueva_conexion = ConexionesEspeciales(
            centro_id=data.get('centro_id'),
            nombre=data.get('nombre'),
            numero_conexion=data.get('numero_conexion')
        )
        db.session.add(nueva_conexion)
        db.session.commit()
        return jsonify({"message": "Conexión especial creada con éxito", "conexion_id": nueva_conexion.id}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Actualizar conexión especial
@conexiones_bp.route('/<int:id>', methods=['PUT'])
def actualizar_conexion(id):
    conexion = ConexionesEspeciales.query.get_or_404(id)
    data = request.json
    try:
        conexion.numero_conexion = data.get('numero_conexion', conexion.numero_conexion)
        db.session.commit()
        return jsonify({"message": "Conexión especial actualizada con éxito"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Eliminar conexión especial
@conexiones_bp.route('/<int:id>', methods=['DELETE'])
def eliminar_conexion(id):
    conexion = ConexionesEspeciales.query.get_or_404(id)
    try:
        db.session.delete(conexion)
        db.session.commit()
        return jsonify({"message": "Conexión especial eliminada con éxito"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
