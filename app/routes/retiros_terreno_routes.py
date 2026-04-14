from datetime import datetime
import jwt

from flask import Blueprint, jsonify, request

from ..database import db
from ..models import Centro, EquiposIP, RetiroTerreno, RetiroTerrenoEquipo, User


retiros_terreno_blueprint = Blueprint('retiros_terreno', __name__)
SECRET_KEY = "remoto753524"


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _usuario_actual_desde_token():
    token = request.headers.get("Authorization") or ""
    if not token.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(token.split("Bearer ")[1], SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id") or payload.get("id") or payload.get("sub")
        try:
            user_id = int(user_id)
        except Exception:
            return None
        return User.query.get(user_id)
    except Exception:
        return None


def _normalize_bool(value):
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return False
    text = str(value).strip().lower()
    return text in ("true", "1", "si", "sí", "yes", "y")


def _serialize_equipo(item: RetiroTerrenoEquipo):
    return {
        "id_retiro_equipo": item.id_retiro_equipo,
        "equipo_id": item.equipo_id,
        "equipo_nombre": item.equipo_nombre,
        "numero_serie": item.numero_serie,
        "codigo": item.codigo,
        "retirado": bool(item.retirado),
        "recibido_bodega": bool(item.recibido_bodega),
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _serialize_retiro(item: RetiroTerreno):
    centro = item.centro
    cliente_nombre = centro.cliente.nombre if centro and centro.cliente else None
    return {
        "id_retiro_terreno": item.id_retiro_terreno,
        "centro_id": item.centro_id,
        "fecha_retiro": item.fecha_retiro.isoformat() if item.fecha_retiro else None,
        "tipo_retiro": item.tipo_retiro,
        "estado_logistico": item.estado_logistico,
        "observacion": item.observacion,
        "observacion_bodega": item.observacion_bodega,
        "recepcion_bodega_por": item.recepcion_bodega_por,
        "recepcion_bodega_user_id": item.recepcion_bodega_user_id,
        "fecha_recepcion_bodega": item.fecha_recepcion_bodega.isoformat() if item.fecha_recepcion_bodega else None,
        "tecnico_1": item.tecnico_1,
        "firma_tecnico_1": item.firma_tecnico_1,
        "tecnico_2": item.tecnico_2,
        "firma_tecnico_2": item.firma_tecnico_2,
        "recepciona_nombre": item.recepciona_nombre,
        "recepciona_rut": item.recepciona_rut,
        "firma_recepciona": item.firma_recepciona,
        "empresa": cliente_nombre,
        "cliente": cliente_nombre,
        "centro": centro.nombre if centro else None,
        "codigo_ponton": centro.nombre_ponton if centro else None,
        "region": centro.area if centro else None,
        "localidad": centro.ubicacion if centro else None,
        "equipos": [_serialize_equipo(eq) for eq in (item.equipos or [])],
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _build_equipos_rows(payload_rows):
    rows = []
    for raw in (payload_rows or []):
        if not isinstance(raw, dict):
            continue
        equipo_id = raw.get("equipo_id")
        equipo_nombre = str(raw.get("equipo_nombre") or raw.get("nombre") or "").strip()
        numero_serie = str(raw.get("numero_serie") or "").strip() or None
        codigo = str(raw.get("codigo") or "").strip() or None
        retirado = _normalize_bool(raw.get("retirado"))
        recibido_bodega = _normalize_bool(raw.get("recibido_bodega"))
        if not equipo_nombre:
            if equipo_id:
                ref = EquiposIP.query.get(equipo_id)
                if ref and ref.nombre:
                    equipo_nombre = ref.nombre
        if not equipo_nombre:
            continue
        rows.append(
            RetiroTerrenoEquipo(
                equipo_id=equipo_id if equipo_id else None,
                equipo_nombre=equipo_nombre,
                numero_serie=numero_serie,
                codigo=codigo,
                retirado=retirado,
                recibido_bodega=recibido_bodega,
            )
        )
    return rows


@retiros_terreno_blueprint.route('/', methods=['GET'])
def listar_retiros_terreno():
    try:
        cliente_id = request.args.get('cliente_id', type=int)
        centro_id = request.args.get('centro_id', type=int)
        estado_logistico = request.args.get('estado_logistico', type=str)
        fecha_desde = _parse_date(request.args.get('fecha_desde'))
        fecha_hasta = _parse_date(request.args.get('fecha_hasta'))

        query = RetiroTerreno.query.join(Centro, Centro.id_centro == RetiroTerreno.centro_id)

        if cliente_id:
            query = query.filter(Centro.cliente_id == cliente_id)
        if centro_id:
            query = query.filter(RetiroTerreno.centro_id == centro_id)
        if estado_logistico:
            query = query.filter(RetiroTerreno.estado_logistico == estado_logistico)
        if fecha_desde:
            query = query.filter(RetiroTerreno.fecha_retiro >= fecha_desde)
        if fecha_hasta:
            query = query.filter(RetiroTerreno.fecha_retiro <= fecha_hasta)

        registros = query.order_by(RetiroTerreno.fecha_retiro.desc(), RetiroTerreno.id_retiro_terreno.desc()).all()
        return jsonify([_serialize_retiro(item) for item in registros]), 200
    except Exception as e:
        return jsonify({"error": f"Error al listar retiros en terreno: {str(e)}"}), 500


@retiros_terreno_blueprint.route('/', methods=['POST'])
def crear_retiro_terreno():
    data = request.get_json() or {}
    try:
        centro_id = data.get("centro_id")
        fecha_retiro = _parse_date(data.get("fecha_retiro"))
        if not centro_id or not fecha_retiro:
            return jsonify({"error": "centro_id y fecha_retiro son requeridos"}), 400

        centro = Centro.query.get(centro_id)
        if not centro:
            return jsonify({"error": "Centro no encontrado"}), 404

        usuario_actual = _usuario_actual_desde_token()
        tecnico_token = (usuario_actual.name if usuario_actual else None) or None
        tecnico_1 = data.get("tecnico_1") or tecnico_token
        tecnico_2 = data.get("tecnico_2")

        item = RetiroTerreno(
            centro_id=centro_id,
            fecha_retiro=fecha_retiro,
            tipo_retiro=str(data.get("tipo_retiro") or "parcial"),
            estado_logistico=str(data.get("estado_logistico") or "retirado_centro"),
            observacion=data.get("observacion"),
            observacion_bodega=data.get("observacion_bodega"),
            recepcion_bodega_por=data.get("recepcion_bodega_por"),
            recepcion_bodega_user_id=data.get("recepcion_bodega_user_id"),
            fecha_recepcion_bodega=datetime.utcnow() if str(data.get("estado_logistico") or "") == "en_bodega" else None,
            tecnico_1=tecnico_1,
            firma_tecnico_1=data.get("firma_tecnico_1"),
            tecnico_2=tecnico_2,
            firma_tecnico_2=data.get("firma_tecnico_2"),
            recepciona_nombre=data.get("recepciona_nombre"),
            recepciona_rut=data.get("recepciona_rut"),
            firma_recepciona=data.get("firma_recepciona"),
        )

        equipos_rows = _build_equipos_rows(data.get("equipos"))
        for row in equipos_rows:
            item.equipos.append(row)

        db.session.add(item)
        db.session.commit()
        return jsonify({"message": "Retiro en terreno creado", "retiro": _serialize_retiro(item)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al crear retiro en terreno: {str(e)}"}), 500


@retiros_terreno_blueprint.route('/<int:id_retiro_terreno>', methods=['PUT'])
def actualizar_retiro_terreno(id_retiro_terreno):
    data = request.get_json() or {}
    try:
        item = RetiroTerreno.query.get(id_retiro_terreno)
        if not item:
            return jsonify({"error": "Retiro en terreno no encontrado"}), 404

        if "centro_id" in data and data.get("centro_id"):
            centro = Centro.query.get(data.get("centro_id"))
            if not centro:
                return jsonify({"error": "Centro no encontrado"}), 404
            item.centro_id = data.get("centro_id")

        if "fecha_retiro" in data:
            fecha_retiro = _parse_date(data.get("fecha_retiro"))
            if not fecha_retiro:
                return jsonify({"error": "fecha_retiro invalida"}), 400
            item.fecha_retiro = fecha_retiro

        for campo in [
            "tipo_retiro",
            "estado_logistico",
            "observacion",
            "observacion_bodega",
            "recepcion_bodega_por",
            "recepcion_bodega_user_id",
            "tecnico_1",
            "firma_tecnico_1",
            "tecnico_2",
            "firma_tecnico_2",
            "recepciona_nombre",
            "recepciona_rut",
            "firma_recepciona",
        ]:
            if campo in data:
                setattr(item, campo, data.get(campo))

        if "estado_logistico" in data and str(data.get("estado_logistico") or "") == "en_bodega":
            if not item.fecha_recepcion_bodega:
                item.fecha_recepcion_bodega = datetime.utcnow()

        if "equipos" in data:
            item.equipos.clear()
            for row in _build_equipos_rows(data.get("equipos")):
                item.equipos.append(row)

        db.session.commit()
        return jsonify({"message": "Retiro en terreno actualizado", "retiro": _serialize_retiro(item)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al actualizar retiro en terreno: {str(e)}"}), 500


@retiros_terreno_blueprint.route('/<int:id_retiro_terreno>', methods=['DELETE'])
def eliminar_retiro_terreno(id_retiro_terreno):
    try:
        item = RetiroTerreno.query.get(id_retiro_terreno)
        if not item:
            return jsonify({"error": "Retiro en terreno no encontrado"}), 404
        db.session.delete(item)
        db.session.commit()
        return jsonify({"message": "Retiro en terreno eliminado"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al eliminar retiro en terreno: {str(e)}"}), 500


@retiros_terreno_blueprint.route('/<int:id_retiro_terreno>/recepcionar_bodega', methods=['POST'])
def recepcionar_retiro_en_bodega(id_retiro_terreno):
    data = request.get_json() or {}
    try:
        item = RetiroTerreno.query.get(id_retiro_terreno)
        if not item:
            return jsonify({"error": "Retiro en terreno no encontrado"}), 404

        item.estado_logistico = "en_bodega"
        item.fecha_recepcion_bodega = datetime.utcnow()
        item.recepcion_bodega_por = data.get("recepcion_bodega_por") or item.recepcion_bodega_por
        item.recepcion_bodega_user_id = data.get("recepcion_bodega_user_id") or item.recepcion_bodega_user_id
        item.observacion_bodega = data.get("observacion_bodega") or item.observacion_bodega

        equipos_payload = data.get("equipos")
        if isinstance(equipos_payload, list):
            by_id = {
                int(eq.id_retiro_equipo): eq
                for eq in (item.equipos or [])
                if getattr(eq, "id_retiro_equipo", None) is not None
            }
            for raw in equipos_payload:
                try:
                    eq_id = int(raw.get("id_retiro_equipo"))
                except Exception:
                    continue
                eq = by_id.get(eq_id)
                if not eq:
                    continue
                if "recibido_bodega" in raw:
                    eq.recibido_bodega = _normalize_bool(raw.get("recibido_bodega"))

        db.session.commit()
        return jsonify({"message": "Retiro recepcionado en bodega", "retiro": _serialize_retiro(item)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al recepcionar retiro en bodega: {str(e)}"}), 500
