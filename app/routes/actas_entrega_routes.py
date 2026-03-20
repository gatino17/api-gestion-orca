from datetime import datetime
from flask import Blueprint, request, jsonify

from ..database import db
from ..models import ActaEntrega, Centro


actas_entrega_blueprint = Blueprint('actas_entrega', __name__)


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _serialize_acta(acta):
    centro = acta.centro
    cliente_nombre = centro.cliente.nombre if centro and centro.cliente else None
    return {
        "id_acta_entrega": acta.id_acta_entrega,
        "centro_id": acta.centro_id,
        "fecha_registro": acta.fecha_registro.isoformat() if acta.fecha_registro else None,
        "region": acta.region,
        "localidad": acta.localidad,
        "tecnico_1": acta.tecnico_1,
        "firma_tecnico_1": acta.firma_tecnico_1,
        "tecnico_2": acta.tecnico_2,
        "firma_tecnico_2": acta.firma_tecnico_2,
        "recepciona_nombre": acta.recepciona_nombre,
        "firma_recepciona": acta.firma_recepciona,
        "equipos_considerados": acta.equipos_considerados,
        "empresa": cliente_nombre,
        "cliente": cliente_nombre,
        "centro": centro.nombre if centro else None,
        "codigo_ponton": centro.nombre_ponton if centro else None,
        "created_at": acta.created_at.isoformat() if acta.created_at else None,
        "updated_at": acta.updated_at.isoformat() if acta.updated_at else None,
    }


@actas_entrega_blueprint.route('/', methods=['GET'])
def listar_actas_entrega():
    try:
        cliente_id = request.args.get('cliente_id', type=int)
        centro_id = request.args.get('centro_id', type=int)
        fecha_desde = _parse_date(request.args.get('fecha_desde'))
        fecha_hasta = _parse_date(request.args.get('fecha_hasta'))

        query = ActaEntrega.query.join(Centro, Centro.id_centro == ActaEntrega.centro_id)

        if cliente_id:
            query = query.filter(Centro.cliente_id == cliente_id)
        if centro_id:
            query = query.filter(ActaEntrega.centro_id == centro_id)
        if fecha_desde:
            query = query.filter(ActaEntrega.fecha_registro >= fecha_desde)
        if fecha_hasta:
            query = query.filter(ActaEntrega.fecha_registro <= fecha_hasta)

        registros = query.order_by(ActaEntrega.fecha_registro.desc(), ActaEntrega.id_acta_entrega.desc()).all()
        return jsonify([_serialize_acta(item) for item in registros]), 200
    except Exception as e:
        return jsonify({"error": f"Error al listar actas de entrega: {str(e)}"}), 500


@actas_entrega_blueprint.route('/', methods=['POST'])
def crear_acta_entrega():
    data = request.get_json() or {}
    try:
        centro_id = data.get("centro_id")
        fecha_registro = _parse_date(data.get("fecha_registro"))
        if not centro_id or not fecha_registro:
            return jsonify({"error": "centro_id y fecha_registro son requeridos"}), 400

        centro = Centro.query.get(centro_id)
        if not centro:
            return jsonify({"error": "Centro no encontrado"}), 404

        acta = ActaEntrega(
            centro_id=centro_id,
            fecha_registro=fecha_registro,
            region=data.get("region"),
            localidad=data.get("localidad"),
            tecnico_1=data.get("tecnico_1"),
            firma_tecnico_1=data.get("firma_tecnico_1"),
            tecnico_2=data.get("tecnico_2"),
            firma_tecnico_2=data.get("firma_tecnico_2"),
            recepciona_nombre=data.get("recepciona_nombre"),
            firma_recepciona=data.get("firma_recepciona"),
            equipos_considerados=data.get("equipos_considerados"),
        )
        db.session.add(acta)
        db.session.commit()
        return jsonify({"message": "Acta de entrega creada", "acta": _serialize_acta(acta)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al crear acta de entrega: {str(e)}"}), 500


@actas_entrega_blueprint.route('/<int:id_acta_entrega>', methods=['PUT'])
def actualizar_acta_entrega(id_acta_entrega):
    data = request.get_json() or {}
    try:
        acta = ActaEntrega.query.get(id_acta_entrega)
        if not acta:
            return jsonify({"error": "Acta de entrega no encontrada"}), 404

        if "centro_id" in data and data.get("centro_id"):
            centro = Centro.query.get(data.get("centro_id"))
            if not centro:
                return jsonify({"error": "Centro no encontrado"}), 404
            acta.centro_id = data.get("centro_id")

        if "fecha_registro" in data:
            fecha = _parse_date(data.get("fecha_registro"))
            if not fecha:
                return jsonify({"error": "fecha_registro invalida"}), 400
            acta.fecha_registro = fecha

        for campo in [
            "region",
            "localidad",
            "tecnico_1",
            "firma_tecnico_1",
            "tecnico_2",
            "firma_tecnico_2",
            "recepciona_nombre",
            "firma_recepciona",
            "equipos_considerados",
        ]:
            if campo in data:
                setattr(acta, campo, data.get(campo))

        db.session.commit()
        return jsonify({"message": "Acta de entrega actualizada", "acta": _serialize_acta(acta)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al actualizar acta de entrega: {str(e)}"}), 500


@actas_entrega_blueprint.route('/<int:id_acta_entrega>', methods=['DELETE'])
def eliminar_acta_entrega(id_acta_entrega):
    try:
        acta = ActaEntrega.query.get(id_acta_entrega)
        if not acta:
            return jsonify({"error": "Acta de entrega no encontrada"}), 404
        db.session.delete(acta)
        db.session.commit()
        return jsonify({"message": "Acta de entrega eliminada"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al eliminar acta de entrega: {str(e)}"}), 500
