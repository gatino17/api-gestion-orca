from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
import json
import jwt

from ..database import db
from ..models import ActaEntrega, Armado, Centro, User


actas_entrega_blueprint = Blueprint('actas_entrega', __name__)


def _usuario_actual_desde_token():
    token = request.headers.get("Authorization") or ""
    if not token.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(
            token.split("Bearer ")[1],
            current_app.config.get("SECRET_KEY"),
            algorithms=["HS256"]
        )
        user_id = payload.get("user_id") or payload.get("id") or payload.get("sub")
        if not user_id:
            return None
        return User.query.get(int(user_id))
    except Exception:
        return None


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
    firmas_adicionales = []
    try:
        raw = acta.firmas_tecnicos_adicionales
        if raw:
            parsed = json.loads(raw) if isinstance(raw, str) else raw
            if isinstance(parsed, list):
                firmas_adicionales = parsed
    except Exception:
        firmas_adicionales = []
    return {
        "id_acta_entrega": acta.id_acta_entrega,
        "centro_id": acta.centro_id,
        "armado_id": acta.armado_id,
        "actividad_id": acta.actividad_id,
        "fecha_registro": acta.fecha_registro.isoformat() if acta.fecha_registro else None,
        "codigo_ponton": acta.codigo_ponton or (centro.nombre_ponton if centro else None),
        "region": acta.region,
        "localidad": acta.localidad,
        "tecnico_1": acta.tecnico_1,
        "firma_tecnico_1": acta.firma_tecnico_1,
        "tecnico_2": acta.tecnico_2,
        "firma_tecnico_2": acta.firma_tecnico_2,
        "firmas_tecnicos_adicionales": firmas_adicionales,
        "recepciona_nombre": acta.recepciona_nombre,
        "firma_recepciona": acta.firma_recepciona,
        "equipos_considerados": acta.equipos_considerados,
        "centro_origen_traslado": acta.centro_origen_traslado,
        "tipo_instalacion": acta.tipo_instalacion or "instalacion",
        "empresa": cliente_nombre,
        "cliente": cliente_nombre,
        "centro": centro.nombre if centro else None,
        "codigo_ponton": centro.nombre_ponton if centro else None,
        "created_at": acta.created_at.isoformat() if acta.created_at else None,
        "updated_at": acta.updated_at.isoformat() if acta.updated_at else None,
    }


def _normalize_firmas_adicionales(value):
    if value in (None, "", []):
        return None
    payload = value
    if isinstance(value, str):
        try:
            payload = json.loads(value)
        except Exception:
            return None
    if not isinstance(payload, list):
        return None
    normalizadas = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        nombre = str(item.get("nombre") or "").strip()
        firma = str(item.get("firma") or "").strip()
        if not nombre:
            continue
        normalizadas.append({"nombre": nombre, "firma": firma or None})
    return json.dumps(normalizadas, ensure_ascii=False) if normalizadas else None


def _sync_codigo_ponton_si_tecnico(acta, codigo_ponton_nuevo):
    usuario = _usuario_actual_desde_token()
    if not usuario:
        return
    rol = str(usuario.rol or "").strip().lower()
    if rol != "tecnico":
        return
    tipo = str(acta.tipo_instalacion or "").strip().lower()
    if tipo != "instalacion":
        return
    if codigo_ponton_nuevo is None:
        return
    codigo = str(codigo_ponton_nuevo).strip()
    if not codigo:
        return
    centro = acta.centro or Centro.query.get(acta.centro_id)
    if not centro:
        return
    centro.nombre_ponton = codigo


@actas_entrega_blueprint.route('/', methods=['GET'])
def listar_actas_entrega():
    try:
        cliente_id = request.args.get('cliente_id', type=int)
        centro_id = request.args.get('centro_id', type=int)
        fecha_desde = _parse_date(request.args.get('fecha_desde'))
        fecha_hasta = _parse_date(request.args.get('fecha_hasta'))
        tipo_instalacion = request.args.get('tipo_instalacion', type=str)

        query = ActaEntrega.query.join(Centro, Centro.id_centro == ActaEntrega.centro_id)

        if cliente_id:
            query = query.filter(Centro.cliente_id == cliente_id)
        if centro_id:
            query = query.filter(ActaEntrega.centro_id == centro_id)
        if fecha_desde:
            query = query.filter(ActaEntrega.fecha_registro >= fecha_desde)
        if fecha_hasta:
            query = query.filter(ActaEntrega.fecha_registro <= fecha_hasta)
        if tipo_instalacion:
            query = query.filter(ActaEntrega.tipo_instalacion == tipo_instalacion.strip().lower())

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
        armado_id = data.get("armado_id")
        if armado_id in ("", None):
            armado_id = None
        if armado_id is not None:
            try:
                armado_id = int(armado_id)
            except (TypeError, ValueError):
                return jsonify({"error": "armado_id invalido"}), 400
            armado = Armado.query.get(armado_id)
            if not armado:
                return jsonify({"error": "Armado no encontrado"}), 404
            if int(armado.centro_id or 0) != int(centro_id):
                return jsonify({"error": "El armado no pertenece al centro seleccionado"}), 400

        tipo_instalacion = str(data.get("tipo_instalacion") or "instalacion").strip().lower()
        if tipo_instalacion not in ["instalacion", "reapuntamiento"]:
            return jsonify({"error": "tipo_instalacion invalido"}), 400

        acta = ActaEntrega(
            centro_id=centro_id,
            armado_id=armado_id,
            actividad_id=data.get("actividad_id"),
            fecha_registro=fecha_registro,
            codigo_ponton=data.get("codigo_ponton"),
            region=data.get("region"),
            localidad=data.get("localidad"),
            tecnico_1=data.get("tecnico_1"),
            firma_tecnico_1=data.get("firma_tecnico_1"),
            tecnico_2=data.get("tecnico_2"),
            firma_tecnico_2=data.get("firma_tecnico_2"),
            firmas_tecnicos_adicionales=_normalize_firmas_adicionales(data.get("firmas_tecnicos_adicionales")),
            recepciona_nombre=data.get("recepciona_nombre"),
            firma_recepciona=data.get("firma_recepciona"),
            equipos_considerados=data.get("equipos_considerados"),
            centro_origen_traslado=data.get("centro_origen_traslado"),
            tipo_instalacion=tipo_instalacion,
        )
        _sync_codigo_ponton_si_tecnico(acta, data.get("codigo_ponton"))
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

        if "armado_id" in data:
            armado_id = data.get("armado_id")
            if armado_id in ("", None):
                acta.armado_id = None
            else:
                try:
                    armado_id = int(armado_id)
                except (TypeError, ValueError):
                    return jsonify({"error": "armado_id invalido"}), 400
                armado = Armado.query.get(armado_id)
                if not armado:
                    return jsonify({"error": "Armado no encontrado"}), 404
                if int(armado.centro_id or 0) != int(acta.centro_id or 0):
                    return jsonify({"error": "El armado no pertenece al centro seleccionado"}), 400
                acta.armado_id = armado_id

        if "fecha_registro" in data:
            fecha = _parse_date(data.get("fecha_registro"))
            if not fecha:
                return jsonify({"error": "fecha_registro invalida"}), 400
            acta.fecha_registro = fecha

        for campo in [
            "region",
            "localidad",
            "codigo_ponton",
            "actividad_id",
            "tecnico_1",
            "firma_tecnico_1",
            "tecnico_2",
            "firma_tecnico_2",
            "firmas_tecnicos_adicionales",
            "recepciona_nombre",
            "firma_recepciona",
            "equipos_considerados",
            "centro_origen_traslado",
        ]:
            if campo in data:
                if campo == "firmas_tecnicos_adicionales":
                    setattr(acta, campo, _normalize_firmas_adicionales(data.get(campo)))
                else:
                    setattr(acta, campo, data.get(campo))

        if "tipo_instalacion" in data:
            tipo_instalacion = str(data.get("tipo_instalacion") or "instalacion").strip().lower()
            if tipo_instalacion not in ["instalacion", "reapuntamiento"]:
                return jsonify({"error": "tipo_instalacion invalido"}), 400
            acta.tipo_instalacion = tipo_instalacion

        _sync_codigo_ponton_si_tecnico(acta, data.get("codigo_ponton") if "codigo_ponton" in data else None)

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
