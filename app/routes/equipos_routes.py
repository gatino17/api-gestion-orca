from flask import Blueprint, request, jsonify
from ..models import EquiposIP, Centro, db

equipos_bp = Blueprint('equipos', __name__)

# Obtener todos los equipos o equipos por centro_id
@equipos_bp.route('/', methods=['GET'])
def obtener_equipos():
    centro_id = request.args.get('centro_id', type=int)  # Permite filtrar por centro_id
    if centro_id:
        equipos = EquiposIP.query.filter_by(centro_id=centro_id).all()
    else:
        equipos = EquiposIP.query.all()
        
    equipos_data = [
        {
            "id_equipo": equipo.id_equipo,
            "centro_id": equipo.centro_id,
            "nombre": equipo.nombre,
            "ip": equipo.ip,
            "observacion": equipo.observacion,
            "codigo": equipo.codigo,
            "numero_serie": equipo.numero_serie,
            "estado": equipo.estado
        } for equipo in equipos
    ]
    
    return jsonify(equipos_data), 200

# Crear equipo
@equipos_bp.route('/', methods=['POST'])
def crear_equipo():
    data = request.json
    centro = Centro.query.get(data.get('centro_id'))
    if not centro:
        return jsonify({"error": "Centro no encontrado"}), 404
    try:
        nuevo_equipo = EquiposIP(
            centro_id=data.get('centro_id'),
            nombre=data.get('nombre'),
            ip=data.get('ip'),
            observacion=data.get('observacion'),
            codigo=data.get('codigo'),
            numero_serie=data.get('numero_serie'),
            estado=data.get('estado')
        )
        db.session.add(nuevo_equipo)
        db.session.commit()
        return jsonify({"message": "Equipo creado con éxito", "equipo": nuevo_equipo.id_equipo}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Actualizar equipo
@equipos_bp.route('/<int:id_equipo>', methods=['PUT'])
def actualizar_equipo(id_equipo):
    equipo = EquiposIP.query.get_or_404(id_equipo)
    data = request.json
    try:
        equipo.ip = data.get('ip', equipo.ip)
        equipo.observacion = data.get('observacion', equipo.observacion)
        equipo.codigo = data.get('codigo', equipo.codigo)
        equipo.numero_serie = data.get('numero_serie', equipo.numero_serie)
        equipo.estado = data.get('estado', equipo.estado)
        db.session.commit()
        return jsonify({"message": "Equipo actualizado con éxito"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


# Eliminar equipo
@equipos_bp.route('/<int:id_equipo>', methods=['DELETE'])
def eliminar_equipo(id_equipo):
    equipo = EquiposIP.query.get_or_404(id_equipo)
    try:
        db.session.delete(equipo)
        db.session.commit()
        return jsonify({"message": "Equipo eliminado con éxito"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
