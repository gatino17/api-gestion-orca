from datetime import datetime

from flask import Blueprint, jsonify, request

from ..database import db
from ..models import ActaEntrega, Centro, PermisoTrabajo


permisos_trabajo_blueprint = Blueprint('permisos_trabajo', __name__)


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _serialize_permiso(permiso):
    centro = permiso.centro
    cliente_nombre = centro.cliente.nombre if centro and centro.cliente else None
    return {
        "id_permiso_trabajo": permiso.id_permiso_trabajo,
        "centro_id": permiso.centro_id,
        "acta_entrega_id": permiso.acta_entrega_id,
        "fecha_ingreso": permiso.fecha_ingreso.isoformat() if permiso.fecha_ingreso else None,
        "fecha_salida": permiso.fecha_salida.isoformat() if permiso.fecha_salida else None,
        "correo_centro": permiso.correo_centro,
        "region": permiso.region,
        "localidad": permiso.localidad,
        "tecnico_1": permiso.tecnico_1,
        "tecnico_2": permiso.tecnico_2,
        "recepciona_nombre": permiso.recepciona_nombre,
        "puntos_gps": permiso.puntos_gps,
        "descripcion_trabajo": permiso.descripcion_trabajo,
        "empresa": cliente_nombre,
        "cliente": cliente_nombre,
        "centro": centro.nombre if centro else None,
        "codigo_ponton": centro.nombre_ponton if centro else None,
        "created_at": permiso.created_at.isoformat() if permiso.created_at else None,
        "updated_at": permiso.updated_at.isoformat() if permiso.updated_at else None,
    }


@permisos_trabajo_blueprint.route('/', methods=['GET'])
def listar_permisos_trabajo():
    try:
        cliente_id = request.args.get('cliente_id', type=int)
        centro_id = request.args.get('centro_id', type=int)
        fecha_desde = _parse_date(request.args.get('fecha_desde'))
        fecha_hasta = _parse_date(request.args.get('fecha_hasta'))

        query = PermisoTrabajo.query.join(Centro, Centro.id_centro == PermisoTrabajo.centro_id)

        if cliente_id:
            query = query.filter(Centro.cliente_id == cliente_id)
        if centro_id:
            query = query.filter(PermisoTrabajo.centro_id == centro_id)
        if fecha_desde:
            query = query.filter(PermisoTrabajo.fecha_ingreso >= fecha_desde)
        if fecha_hasta:
            query = query.filter(PermisoTrabajo.fecha_ingreso <= fecha_hasta)

        registros = query.order_by(PermisoTrabajo.fecha_ingreso.desc(), PermisoTrabajo.id_permiso_trabajo.desc()).all()
        return jsonify([_serialize_permiso(item) for item in registros]), 200
    except Exception as e:
        return jsonify({"error": f"Error al listar permisos de trabajo: {str(e)}"}), 500


@permisos_trabajo_blueprint.route('/', methods=['POST'])
def crear_permiso_trabajo():
    data = request.get_json() or {}
    try:
        centro_id = data.get("centro_id")
        fecha_ingreso = _parse_date(data.get("fecha_ingreso"))
        if not centro_id or not fecha_ingreso:
            return jsonify({"error": "centro_id y fecha_ingreso son requeridos"}), 400

        centro = Centro.query.get(centro_id)
        if not centro:
            return jsonify({"error": "Centro no encontrado"}), 404

        acta_entrega_id = data.get("acta_entrega_id")
        if acta_entrega_id:
            acta = ActaEntrega.query.get(acta_entrega_id)
            if not acta:
                return jsonify({"error": "Acta de entrega no encontrada"}), 404

        permiso = PermisoTrabajo(
            centro_id=centro_id,
            acta_entrega_id=acta_entrega_id,
            fecha_ingreso=fecha_ingreso,
            fecha_salida=_parse_date(data.get("fecha_salida")),
            correo_centro=data.get("correo_centro"),
            region=data.get("region"),
            localidad=data.get("localidad"),
            tecnico_1=data.get("tecnico_1"),
            tecnico_2=data.get("tecnico_2"),
            recepciona_nombre=data.get("recepciona_nombre"),
            puntos_gps=data.get("puntos_gps"),
            descripcion_trabajo=data.get("descripcion_trabajo"),
        )
        db.session.add(permiso)
        db.session.commit()
        return jsonify({"message": "Permiso de trabajo creado", "permiso": _serialize_permiso(permiso)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al crear permiso de trabajo: {str(e)}"}), 500


@permisos_trabajo_blueprint.route('/<int:id_permiso_trabajo>', methods=['PUT'])
def actualizar_permiso_trabajo(id_permiso_trabajo):
    data = request.get_json() or {}
    try:
        permiso = PermisoTrabajo.query.get(id_permiso_trabajo)
        if not permiso:
            return jsonify({"error": "Permiso de trabajo no encontrado"}), 404

        if "centro_id" in data and data.get("centro_id"):
            centro = Centro.query.get(data.get("centro_id"))
            if not centro:
                return jsonify({"error": "Centro no encontrado"}), 404
            permiso.centro_id = data.get("centro_id")

        if "acta_entrega_id" in data:
            acta_entrega_id = data.get("acta_entrega_id")
            if acta_entrega_id:
                acta = ActaEntrega.query.get(acta_entrega_id)
                if not acta:
                    return jsonify({"error": "Acta de entrega no encontrada"}), 404
            permiso.acta_entrega_id = acta_entrega_id

        if "fecha_ingreso" in data:
            fecha_ingreso = _parse_date(data.get("fecha_ingreso"))
            if not fecha_ingreso:
                return jsonify({"error": "fecha_ingreso invalida"}), 400
            permiso.fecha_ingreso = fecha_ingreso

        if "fecha_salida" in data:
            permiso.fecha_salida = _parse_date(data.get("fecha_salida"))

        for campo in [
            "correo_centro",
            "region",
            "localidad",
            "tecnico_1",
            "tecnico_2",
            "recepciona_nombre",
            "puntos_gps",
            "descripcion_trabajo",
        ]:
            if campo in data:
                setattr(permiso, campo, data.get(campo))

        db.session.commit()
        return jsonify({"message": "Permiso de trabajo actualizado", "permiso": _serialize_permiso(permiso)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al actualizar permiso de trabajo: {str(e)}"}), 500


@permisos_trabajo_blueprint.route('/<int:id_permiso_trabajo>', methods=['DELETE'])
def eliminar_permiso_trabajo(id_permiso_trabajo):
    try:
        permiso = PermisoTrabajo.query.get(id_permiso_trabajo)
        if not permiso:
            return jsonify({"error": "Permiso de trabajo no encontrado"}), 404
        db.session.delete(permiso)
        db.session.commit()
        return jsonify({"message": "Permiso de trabajo eliminado"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al eliminar permiso de trabajo: {str(e)}"}), 500

