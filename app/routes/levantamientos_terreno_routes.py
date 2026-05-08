from datetime import datetime
import json

from flask import Blueprint, jsonify, request

from ..database import db
from ..models import Centro, LevantamientoTerreno


levantamientos_terreno_blueprint = Blueprint('levantamientos_terreno', __name__)


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _normalize_fotos(value):
    if value in (None, "", []):
        return None
    payload = value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            payload = json.loads(text)
        except Exception:
            raise ValueError("fotos debe ser un JSON valido")
    if not isinstance(payload, list):
        raise ValueError("fotos debe ser un arreglo JSON")

    normalizadas = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri") or "").strip()
        descripcion = str(item.get("descripcion") or "").strip()
        if not uri:
            continue
        normalizadas.append({"uri": uri, "descripcion": descripcion})
    return json.dumps(normalizadas, ensure_ascii=False) if normalizadas else None


def _parse_fotos(value):
    if not value:
        return []
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
        return parsed if isinstance(parsed, list) else []
    except Exception:
        return []


def _serialize_levantamiento(item):
    centro = item.centro
    cliente_nombre = centro.cliente.nombre if centro and centro.cliente else None
    return {
        "id_levantamiento_terreno": item.id_levantamiento_terreno,
        "centro_id": item.centro_id,
        "actividad_id": item.actividad_id,
        "fecha_levantamiento": item.fecha_levantamiento.isoformat() if item.fecha_levantamiento else None,
        "region": item.region,
        "localidad": item.localidad,
        "codigo_ponton": item.codigo_ponton,
        "resumen": item.resumen,
        "observaciones": item.observaciones,
        "medicion_voltaje": item.medicion_voltaje,
        "medicion_corriente": item.medicion_corriente,
        "medicion_potencia": item.medicion_potencia,
        "fotos": _parse_fotos(item.fotos),
        "estado": item.estado,
        "empresa": cliente_nombre,
        "cliente": cliente_nombre,
        "centro": centro.nombre if centro else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@levantamientos_terreno_blueprint.route('/', methods=['GET'])
def listar_levantamientos_terreno():
    try:
        cliente_id = request.args.get('cliente_id', type=int)
        centro_id = request.args.get('centro_id', type=int)
        fecha_desde = _parse_date(request.args.get('fecha_desde'))
        fecha_hasta = _parse_date(request.args.get('fecha_hasta'))

        query = LevantamientoTerreno.query.join(Centro, Centro.id_centro == LevantamientoTerreno.centro_id)
        if cliente_id:
            query = query.filter(Centro.cliente_id == cliente_id)
        if centro_id:
            query = query.filter(LevantamientoTerreno.centro_id == centro_id)
        if fecha_desde:
            query = query.filter(LevantamientoTerreno.fecha_levantamiento >= fecha_desde)
        if fecha_hasta:
            query = query.filter(LevantamientoTerreno.fecha_levantamiento <= fecha_hasta)

        registros = query.order_by(
            LevantamientoTerreno.fecha_levantamiento.desc(),
            LevantamientoTerreno.id_levantamiento_terreno.desc(),
        ).all()
        return jsonify([_serialize_levantamiento(item) for item in registros]), 200
    except Exception as e:
        return jsonify({"error": f"Error al listar levantamientos en terreno: {str(e)}"}), 500


@levantamientos_terreno_blueprint.route('/', methods=['POST'])
def crear_levantamiento_terreno():
    data = request.get_json() or {}
    try:
        centro_id = data.get("centro_id")
        fecha_levantamiento = _parse_date(data.get("fecha_levantamiento"))
        if not centro_id or not fecha_levantamiento:
            return jsonify({"error": "centro_id y fecha_levantamiento son requeridos"}), 400

        centro = Centro.query.get(centro_id)
        if not centro:
            return jsonify({"error": "Centro no encontrado"}), 404

        item = LevantamientoTerreno(
            centro_id=centro_id,
            actividad_id=data.get("actividad_id") or None,
            fecha_levantamiento=fecha_levantamiento,
            region=data.get("region"),
            localidad=data.get("localidad"),
            codigo_ponton=data.get("codigo_ponton"),
            resumen=data.get("resumen"),
            observaciones=data.get("observaciones"),
            medicion_voltaje=data.get("medicion_voltaje"),
            medicion_corriente=data.get("medicion_corriente"),
            medicion_potencia=data.get("medicion_potencia"),
            fotos=_normalize_fotos(data.get("fotos")),
            estado=data.get("estado") or "finalizado",
        )

        db.session.add(item)
        db.session.commit()
        return jsonify({"message": "Levantamiento en terreno creado", "levantamiento": _serialize_levantamiento(item)}), 201
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al crear levantamiento en terreno: {str(e)}"}), 500


@levantamientos_terreno_blueprint.route('/<int:id_levantamiento_terreno>', methods=['DELETE'])
def eliminar_levantamiento_terreno(id_levantamiento_terreno):
    try:
        item = LevantamientoTerreno.query.get(id_levantamiento_terreno)
        if not item:
            return jsonify({"error": "Levantamiento en terreno no encontrado"}), 404

        db.session.delete(item)
        db.session.commit()
        return jsonify({"message": "Levantamiento en terreno eliminado"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al eliminar levantamiento en terreno: {str(e)}"}), 500


@levantamientos_terreno_blueprint.route('/<int:id_levantamiento_terreno>', methods=['PUT'])
def actualizar_levantamiento_terreno(id_levantamiento_terreno):
    data = request.get_json() or {}
    try:
        item = LevantamientoTerreno.query.get(id_levantamiento_terreno)
        if not item:
            return jsonify({"error": "Levantamiento en terreno no encontrado"}), 404

        estado_actual = str(item.estado or "").strip().lower()
        if estado_actual != "edicion_autorizada":
            return jsonify({"error": "Solo se puede editar un levantamiento con edicion autorizada"}), 400

        fecha_levantamiento = _parse_date(data.get("fecha_levantamiento")) or item.fecha_levantamiento
        item.fecha_levantamiento = fecha_levantamiento
        item.region = data.get("region", item.region)
        item.localidad = data.get("localidad", item.localidad)
        item.codigo_ponton = data.get("codigo_ponton", item.codigo_ponton)
        item.resumen = data.get("resumen", item.resumen)
        item.observaciones = data.get("observaciones", item.observaciones)
        item.medicion_voltaje = data.get("medicion_voltaje", item.medicion_voltaje)
        item.medicion_corriente = data.get("medicion_corriente", item.medicion_corriente)
        item.medicion_potencia = data.get("medicion_potencia", item.medicion_potencia)
        if "fotos" in data:
            item.fotos = _normalize_fotos(data.get("fotos"))

        item.estado = "finalizado"
        db.session.commit()
        return jsonify({"message": "Levantamiento actualizado", "levantamiento": _serialize_levantamiento(item)}), 200
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al actualizar levantamiento en terreno: {str(e)}"}), 500


@levantamientos_terreno_blueprint.route('/<int:id_levantamiento_terreno>/solicitar_edicion', methods=['POST'])
def solicitar_edicion_levantamiento_terreno(id_levantamiento_terreno):
    try:
        item = LevantamientoTerreno.query.get(id_levantamiento_terreno)
        if not item:
            return jsonify({"error": "Levantamiento en terreno no encontrado"}), 404

        estado_actual = str(item.estado or "").strip().lower()
        if estado_actual not in ("finalizado", "edicion_rechazada"):
            return jsonify({"error": "Solo se puede solicitar edicion para levantamientos finalizados"}), 400

        item.estado = "edicion_solicitada"
        db.session.commit()
        return jsonify({
            "message": "Solicitud de edicion enviada",
            "levantamiento": _serialize_levantamiento(item),
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al solicitar edicion de levantamiento: {str(e)}"}), 500


@levantamientos_terreno_blueprint.route('/<int:id_levantamiento_terreno>/resolver_edicion', methods=['POST'])
def resolver_edicion_levantamiento_terreno(id_levantamiento_terreno):
    data = request.get_json() or {}
    aprobar = bool(data.get("aprobar"))
    try:
        item = LevantamientoTerreno.query.get(id_levantamiento_terreno)
        if not item:
            return jsonify({"error": "Levantamiento en terreno no encontrado"}), 404

        if str(item.estado or "").strip().lower() != "edicion_solicitada":
            return jsonify({"error": "El levantamiento no tiene una solicitud de edicion pendiente"}), 400

        item.estado = "edicion_autorizada" if aprobar else "edicion_rechazada"
        db.session.commit()
        return jsonify({
            "message": "Solicitud de edicion resuelta",
            "levantamiento": _serialize_levantamiento(item),
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al resolver solicitud de edicion: {str(e)}"}), 500
