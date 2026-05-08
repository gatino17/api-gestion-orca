from flask import Blueprint, request, jsonify
from ..models import Encargado, User, db

encargados_bp = Blueprint('encargados', __name__)

def _resolver_nombre_tecnico(user_id, nombre_fallback):
    try:
        uid = int(user_id or 0)
    except Exception:
        uid = 0
    if uid <= 0:
        return str(nombre_fallback or '').strip()
    user = User.query.get(uid)
    if user and str(user.rol or '').strip().lower() == 'tecnico':
        return str(user.name or nombre_fallback or '').strip()
    return str(nombre_fallback or '').strip()

@encargados_bp.route('/', methods=['POST'])
def crear_encargado():
    data = request.get_json()
    user_id = data.get('user_id')
    nombre = _resolver_nombre_tecnico(user_id, data.get('nombre_encargado'))
    nuevo_encargado = Encargado(
        user_id=user_id,
        nombre_encargado=nombre,
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
    cambios = False
    for enc in encargados:
        nombre_sync = _resolver_nombre_tecnico(enc.user_id, enc.nombre_encargado)
        if nombre_sync and nombre_sync != enc.nombre_encargado:
            enc.nombre_encargado = nombre_sync
            cambios = True
    if cambios:
        db.session.commit()
    # Incluye todos los detalles de cada encargado en el JSON de respuesta
    resultado = [
        {
            "id_encargado": enc.id_encargado,
            "user_id": enc.user_id,
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
    if 'user_id' in data:
        encargado.user_id = data.get('user_id')
    encargado.nombre_encargado = _resolver_nombre_tecnico(
        encargado.user_id,
        data.get('nombre_encargado', encargado.nombre_encargado)
    )
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
