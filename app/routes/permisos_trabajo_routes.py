from datetime import datetime
import re

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
    acta = permiso.acta_entrega
    cliente_nombre = centro.cliente.nombre if centro and centro.cliente else None
    correo_centro = permiso.correo_centro or (centro.correo_centro if centro else None)
    telefono_centro = permiso.telefono_centro or (centro.telefono if centro else None)
    return {
        "id_permiso_trabajo": permiso.id_permiso_trabajo,
        "centro_id": permiso.centro_id,
        "acta_entrega_id": permiso.acta_entrega_id,
        "fecha_ingreso": permiso.fecha_ingreso.isoformat() if permiso.fecha_ingreso else None,
        "fecha_salida": permiso.fecha_salida.isoformat() if permiso.fecha_salida else None,
        "correo_centro": correo_centro,
        "telefono_centro": telefono_centro,
        "region": permiso.region,
        "localidad": permiso.localidad,
        "tecnico_1": permiso.tecnico_1,
        "tecnico_2": permiso.tecnico_2,
        "recepciona_nombre": permiso.recepciona_nombre,
        "recepciona_rut": permiso.recepciona_rut,
        "firma_tecnico_1": acta.firma_tecnico_1 if acta else None,
        "firma_tecnico_2": acta.firma_tecnico_2 if acta else None,
        "firma_recepciona": permiso.firma_recepciona,
        "puntos_gps": permiso.puntos_gps,
        "sellos": permiso.sellos,
        "medicion_fase_neutro": permiso.medicion_fase_neutro,
        "medicion_neutro_tierra": permiso.medicion_neutro_tierra,
        "hertz": permiso.hertz,
        "descripcion_trabajo": permiso.descripcion_trabajo,
        "empresa": cliente_nombre,
        "cliente": cliente_nombre,
        "centro": centro.nombre if centro else None,
        "codigo_ponton": centro.nombre_ponton if centro else None,
        "base_tierra": centro.base_tierra if centro else None,
        "cantidad_radares": centro.cantidad_radares if centro else None,
        "created_at": permiso.created_at.isoformat() if permiso.created_at else None,
        "updated_at": permiso.updated_at.isoformat() if permiso.updated_at else None,
    }


def _validate_numeric_measure(data, field_name):
    value = data.get(field_name)
    if value in (None, ""):
        return None
    text = str(value).strip().replace(",", ".")
    if not re.fullmatch(r"\d+(?:\.\d+)?", text):
        raise ValueError(f"{field_name} debe contener un numero valido (ej: 220 o 220.5)")
    return text


def _validate_gps_points(value):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None

    points = [p.strip() for p in text.split("|") if p.strip()]
    if not points:
        return None

    coord_pattern = re.compile(r"^-?\d+(?:\.\d+)?\s*,\s*-?\d+(?:\.\d+)?$")
    for point in points:
        if not coord_pattern.fullmatch(point):
            raise ValueError("puntos_gps debe tener formato latitud,longitud (ej: -41.2345,-72.9876)")

    return " | ".join(points)


def _parse_boolish(value):
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in ("si", "sí", "true", "1", "yes", "y"):
        return True
    if text in ("no", "false", "0", "n"):
        return False
    raise ValueError("base_tierra debe ser si/no")


def _parse_optional_int(value, field_name):
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text.isdigit():
        raise ValueError(f"{field_name} debe ser numerico")
    return int(text)


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

        medicion_fase_neutro = _validate_numeric_measure(data, "medicion_fase_neutro")
        medicion_neutro_tierra = _validate_numeric_measure(data, "medicion_neutro_tierra")
        hertz = _validate_numeric_measure(data, "hertz")
        puntos_gps = _validate_gps_points(data.get("puntos_gps"))

        permiso = PermisoTrabajo(
            centro_id=centro_id,
            acta_entrega_id=acta_entrega_id,
            fecha_ingreso=fecha_ingreso,
            fecha_salida=_parse_date(data.get("fecha_salida")),
            correo_centro=data.get("correo_centro"),
            telefono_centro=data.get("telefono_centro"),
            region=data.get("region"),
            localidad=data.get("localidad"),
            tecnico_1=data.get("tecnico_1"),
            tecnico_2=data.get("tecnico_2"),
            recepciona_nombre=data.get("recepciona_nombre"),
            recepciona_rut=data.get("recepciona_rut"),
            firma_recepciona=data.get("firma_recepciona"),
            puntos_gps=puntos_gps,
            sellos=data.get("sellos"),
            medicion_fase_neutro=medicion_fase_neutro,
            medicion_neutro_tierra=medicion_neutro_tierra,
            hertz=hertz,
            descripcion_trabajo=data.get("descripcion_trabajo"),
        )

        # Si vienen datos desde mobile/web, sincronizamos tambien la ficha del centro.
        correo_centro = (data.get("correo_centro") or "").strip()
        telefono_centro = (data.get("telefono_centro") or "").strip()
        base_tierra = _parse_boolish(data.get("base_tierra"))
        cantidad_radares = _parse_optional_int(data.get("cantidad_radares"), "cantidad_radares")
        if correo_centro:
            centro.correo_centro = correo_centro
        if telefono_centro:
            centro.telefono = telefono_centro
        if base_tierra is not None:
            centro.base_tierra = base_tierra
        if cantidad_radares is not None:
            centro.cantidad_radares = cantidad_radares

        db.session.add(permiso)
        db.session.commit()
        return jsonify({"message": "Permiso de trabajo creado", "permiso": _serialize_permiso(permiso)}), 201
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
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

        numeric_fields = [
            "medicion_fase_neutro",
            "medicion_neutro_tierra",
            "hertz",
        ]
        for campo in numeric_fields:
            if campo in data:
                data[campo] = _validate_numeric_measure(data, campo)
        if "puntos_gps" in data:
            data["puntos_gps"] = _validate_gps_points(data.get("puntos_gps"))

        for campo in [
            "correo_centro",
            "telefono_centro",
            "region",
            "localidad",
            "tecnico_1",
            "tecnico_2",
            "recepciona_nombre",
            "recepciona_rut",
            "firma_recepciona",
            "puntos_gps",
            "sellos",
            "medicion_fase_neutro",
            "medicion_neutro_tierra",
            "hertz",
            "descripcion_trabajo",
        ]:
            if campo in data:
                setattr(permiso, campo, data.get(campo))

        # Mantener sincronizado con ficha del centro cuando se edita desde permiso.
        if "correo_centro" in data:
            correo_centro = (data.get("correo_centro") or "").strip()
            if correo_centro:
                centro = Centro.query.get(permiso.centro_id)
                if centro:
                    centro.correo_centro = correo_centro
        if "telefono_centro" in data:
            telefono_centro = (data.get("telefono_centro") or "").strip()
            if telefono_centro:
                centro = Centro.query.get(permiso.centro_id)
                if centro:
                    centro.telefono = telefono_centro
        if "base_tierra" in data:
            base_tierra = _parse_boolish(data.get("base_tierra"))
            if base_tierra is not None:
                centro = Centro.query.get(permiso.centro_id)
                if centro:
                    centro.base_tierra = base_tierra
        if "cantidad_radares" in data:
            cantidad_radares = _parse_optional_int(data.get("cantidad_radares"), "cantidad_radares")
            if cantidad_radares is not None:
                centro = Centro.query.get(permiso.centro_id)
                if centro:
                    centro.cantidad_radares = cantidad_radares

        db.session.commit()
        return jsonify({"message": "Permiso de trabajo actualizado", "permiso": _serialize_permiso(permiso)}), 200
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
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
