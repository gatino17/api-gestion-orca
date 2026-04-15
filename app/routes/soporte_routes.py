from datetime import datetime

from flask import Blueprint, request, jsonify
from ..models import Soporte, Centro
from ..database import db

soporte_blueprint = Blueprint('soporte', __name__)


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()

# Crear un nuevo registro de soporte
@soporte_blueprint.route('/', methods=['POST'])
def crear_soporte():
    data = request.json
    origen = str(data.get('origen', 'cliente')).lower().strip()
    if origen not in ('cliente', 'orca'):
        return jsonify({"error": "Origen invalido. Use 'cliente' u 'orca'."}), 400

    nuevo_soporte = Soporte(
        centro_id=data.get('centro_id'),
        problema=data.get('problema'),
        tipo=data.get('tipo'),  # "terreno" o "remoto"
        fecha_soporte=_parse_date(data.get('fecha_soporte')),
        solucion=data.get('solucion'),
        categoria_falla=data.get('categoria_falla'),
        cambio_equipo=data.get('cambio_equipo', False),
        equipo_cambiado=data.get('equipo_cambiado'),
        origen=origen,
        estado=data.get('estado', 'pendiente'),
        fecha_cierre=_parse_date(data.get('fecha_cierre'))
    )

    db.session.add(nuevo_soporte)
    db.session.commit()

    return jsonify({"message": "Soporte creado exitosamente", "id_soporte": nuevo_soporte.id_soporte}), 201

# Listar todos los registros de soporte
@soporte_blueprint.route('/', methods=['GET'])
def obtener_soportes():
    soportes = Soporte.query.all()
    resultado = []
    for soporte in soportes:
        resultado.append({
            "id_soporte": soporte.id_soporte,
            "centro": {
                "id_centro": soporte.centro.id_centro if soporte.centro else None,
                "nombre": soporte.centro.nombre if soporte.centro else None,
                "cliente": soporte.centro.cliente.nombre if soporte.centro and soporte.centro.cliente else None          
            },
            "problema": soporte.problema,
            "tipo": soporte.tipo,
            "fecha_soporte": soporte.fecha_soporte.isoformat() if soporte.fecha_soporte else None,
            "solucion": soporte.solucion,
            "categoria_falla": soporte.categoria_falla,
            "cambio_equipo": soporte.cambio_equipo,
            "equipo_cambiado": soporte.equipo_cambiado,
            "origen": soporte.origen or "cliente",
            "estado": soporte.estado,
            "fecha_cierre": soporte.fecha_cierre.isoformat() if soporte.fecha_cierre else None
        })

    return jsonify(resultado), 200

# Actualizar un registro de soporte
@soporte_blueprint.route('/<int:id_soporte>', methods=['PUT'])
def actualizar_soporte(id_soporte):
    data = request.json
    soporte = Soporte.query.get_or_404(id_soporte)

    soporte.centro_id = data.get('centro_id', soporte.centro_id)
    soporte.problema = data.get('problema', soporte.problema)
    soporte.tipo = data.get('tipo', soporte.tipo)
    if 'fecha_soporte' in data:
        soporte.fecha_soporte = _parse_date(data.get('fecha_soporte'))
    soporte.solucion = data.get('solucion', soporte.solucion)
    soporte.categoria_falla = data.get('categoria_falla', soporte.categoria_falla)
    soporte.cambio_equipo = data.get('cambio_equipo', soporte.cambio_equipo)
    soporte.equipo_cambiado = data.get('equipo_cambiado', soporte.equipo_cambiado)
    if 'origen' in data:
        origen = str(data.get('origen', 'cliente')).lower().strip()
        if origen not in ('cliente', 'orca'):
            return jsonify({"error": "Origen invalido. Use 'cliente' u 'orca'."}), 400
        soporte.origen = origen
    soporte.estado = data.get('estado', soporte.estado)
    if 'fecha_cierre' in data:
        soporte.fecha_cierre = _parse_date(data.get('fecha_cierre'))

    db.session.commit()
    return jsonify({"message": "Soporte actualizado exitosamente"}), 200

# Eliminar un registro de soporte
@soporte_blueprint.route('/<int:id_soporte>', methods=['DELETE'])
def eliminar_soporte(id_soporte):
    soporte = Soporte.query.get_or_404(id_soporte)
    db.session.delete(soporte)
    db.session.commit()
    return jsonify({"message": "Soporte eliminado exitosamente"}), 200




