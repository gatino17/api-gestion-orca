from datetime import datetime
import json
import re

from flask import Blueprint, jsonify, request

from ..database import db
from ..models import Armado, ArmadoCajaMovimiento, CambioEquipoMantencion, Centro, EquiposIP, MantencionTerreno


mantenciones_terreno_blueprint = Blueprint('mantenciones_terreno', __name__)


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value), '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


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


def _normalize_checklist(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            raise ValueError("checklist_equipos debe ser un JSON valido")
    elif isinstance(value, list):
        parsed = value
    else:
        raise ValueError("checklist_equipos debe ser un arreglo JSON")

    normalized = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        equipo_id = row.get("equipo_id")
        try:
            equipo_id = int(equipo_id) if equipo_id not in (None, "", 0, "0") else None
        except Exception:
            equipo_id = None
        normalized.append(
            {
                "equipo_id": equipo_id,
                "equipo_nombre": str(row.get("equipo_nombre") or "").strip(),
                "numero_serie": str(row.get("numero_serie") or "").strip(),
                "codigo": str(row.get("codigo") or "").strip(),
                "revisado": bool(row.get("revisado")),
                "observacion": str(row.get("observacion") or "").strip(),
            }
        )
    return json.dumps(normalized, ensure_ascii=False)


def _serialize_mantencion(item):
    centro = item.centro
    cliente_nombre = centro.cliente.nombre if centro and centro.cliente else None
    correo_centro = item.correo_centro or (centro.correo_centro if centro else None)
    telefono_centro = item.telefono_centro or (centro.telefono if centro else None)
    return {
        "id_mantencion_terreno": item.id_mantencion_terreno,
        "centro_id": item.centro_id,
        "fecha_ingreso": item.fecha_ingreso.isoformat() if item.fecha_ingreso else None,
        "fecha_salida": item.fecha_salida.isoformat() if item.fecha_salida else None,
        "correo_centro": correo_centro,
        "telefono_centro": telefono_centro,
        "region": item.region,
        "localidad": item.localidad,
        "responsabilidad": item.responsabilidad,
        "tecnico_1": item.tecnico_1,
        "firma_tecnico_1": item.firma_tecnico_1,
        "tecnico_2": item.tecnico_2,
        "firma_tecnico_2": item.firma_tecnico_2,
        "recepciona_nombre": item.recepciona_nombre,
        "recepciona_rut": item.recepciona_rut,
        "firma_recepciona": item.firma_recepciona,
        "puntos_gps": item.puntos_gps,
        "sellos": item.sellos,
        "medicion_fase_neutro": item.medicion_fase_neutro,
        "medicion_neutro_tierra": item.medicion_neutro_tierra,
        "hertz": item.hertz,
        "descripcion_trabajo": item.descripcion_trabajo,
        "evidencia_foto": item.evidencia_foto,
        "checklist_equipos": item.checklist_equipos,
        "empresa": cliente_nombre,
        "cliente": cliente_nombre,
        "centro": centro.nombre if centro else None,
        "codigo_ponton": centro.nombre_ponton if centro else None,
        "base_tierra": centro.base_tierra if centro else None,
        "cantidad_radares": centro.cantidad_radares if centro else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _serialize_cambio_equipo(item):
    return {
        "id_cambio_equipo_mantencion": item.id_cambio_equipo_mantencion,
        "mantencion_id": item.mantencion_id,
        "centro_id": item.centro_id,
        "armado_id": item.armado_id,
        "equipo_id": item.equipo_id,
        "equipo": item.equipo,
        "serie_anterior": item.serie_anterior,
        "codigo_anterior": item.codigo_anterior,
        "serie_nueva": item.serie_nueva,
        "codigo_nuevo": item.codigo_nuevo,
        "tecnico": item.tecnico,
        "observacion": item.observacion,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


@mantenciones_terreno_blueprint.route('/', methods=['GET'])
def listar_mantenciones_terreno():
    try:
        cliente_id = request.args.get('cliente_id', type=int)
        centro_id = request.args.get('centro_id', type=int)
        fecha_desde = _parse_date(request.args.get('fecha_desde'))
        fecha_hasta = _parse_date(request.args.get('fecha_hasta'))

        query = MantencionTerreno.query.join(Centro, Centro.id_centro == MantencionTerreno.centro_id)

        if cliente_id:
            query = query.filter(Centro.cliente_id == cliente_id)
        if centro_id:
            query = query.filter(MantencionTerreno.centro_id == centro_id)
        if fecha_desde:
            query = query.filter(MantencionTerreno.fecha_ingreso >= fecha_desde)
        if fecha_hasta:
            query = query.filter(MantencionTerreno.fecha_ingreso <= fecha_hasta)

        registros = query.order_by(MantencionTerreno.fecha_ingreso.desc(), MantencionTerreno.id_mantencion_terreno.desc()).all()
        return jsonify([_serialize_mantencion(item) for item in registros]), 200
    except Exception as e:
        return jsonify({"error": f"Error al listar mantenciones en terreno: {str(e)}"}), 500


@mantenciones_terreno_blueprint.route('/', methods=['POST'])
def crear_mantencion_terreno():
    data = request.get_json() or {}
    try:
        centro_id = data.get("centro_id")
        fecha_ingreso = _parse_date(data.get("fecha_ingreso"))
        if not centro_id or not fecha_ingreso:
            return jsonify({"error": "centro_id y fecha_ingreso son requeridos"}), 400

        centro = Centro.query.get(centro_id)
        if not centro:
            return jsonify({"error": "Centro no encontrado"}), 404

        medicion_fase_neutro = _validate_numeric_measure(data, "medicion_fase_neutro")
        medicion_neutro_tierra = _validate_numeric_measure(data, "medicion_neutro_tierra")
        hertz = _validate_numeric_measure(data, "hertz")
        puntos_gps = _validate_gps_points(data.get("puntos_gps"))
        checklist_equipos = _normalize_checklist(data.get("checklist_equipos"))

        item = MantencionTerreno(
            centro_id=centro_id,
            fecha_ingreso=fecha_ingreso,
            fecha_salida=_parse_date(data.get("fecha_salida")),
            correo_centro=data.get("correo_centro"),
            telefono_centro=data.get("telefono_centro"),
            region=data.get("region"),
            localidad=data.get("localidad"),
            responsabilidad=data.get("responsabilidad"),
            tecnico_1=data.get("tecnico_1"),
            firma_tecnico_1=data.get("firma_tecnico_1"),
            tecnico_2=data.get("tecnico_2"),
            firma_tecnico_2=data.get("firma_tecnico_2"),
            recepciona_nombre=data.get("recepciona_nombre"),
            recepciona_rut=data.get("recepciona_rut"),
            firma_recepciona=data.get("firma_recepciona"),
            puntos_gps=puntos_gps,
            sellos=data.get("sellos"),
            medicion_fase_neutro=medicion_fase_neutro,
            medicion_neutro_tierra=medicion_neutro_tierra,
            hertz=hertz,
            descripcion_trabajo=data.get("descripcion_trabajo"),
            evidencia_foto=data.get("evidencia_foto"),
            checklist_equipos=checklist_equipos,
        )

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

        db.session.add(item)
        db.session.commit()
        return jsonify({"message": "Mantencion en terreno creada", "mantencion": _serialize_mantencion(item)}), 201
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al crear mantencion en terreno: {str(e)}"}), 500


@mantenciones_terreno_blueprint.route('/<int:id_mantencion_terreno>', methods=['PUT'])
def actualizar_mantencion_terreno(id_mantencion_terreno):
    data = request.get_json() or {}
    try:
        item = MantencionTerreno.query.get(id_mantencion_terreno)
        if not item:
            return jsonify({"error": "Mantencion en terreno no encontrada"}), 404

        if "centro_id" in data and data.get("centro_id"):
            centro = Centro.query.get(data.get("centro_id"))
            if not centro:
                return jsonify({"error": "Centro no encontrado"}), 404
            item.centro_id = data.get("centro_id")

        if "fecha_ingreso" in data:
            fecha_ingreso = _parse_date(data.get("fecha_ingreso"))
            if not fecha_ingreso:
                return jsonify({"error": "fecha_ingreso invalida"}), 400
            item.fecha_ingreso = fecha_ingreso

        if "fecha_salida" in data:
            item.fecha_salida = _parse_date(data.get("fecha_salida"))

        numeric_fields = ["medicion_fase_neutro", "medicion_neutro_tierra", "hertz"]
        for campo in numeric_fields:
            if campo in data:
                data[campo] = _validate_numeric_measure(data, campo)
        if "puntos_gps" in data:
            data["puntos_gps"] = _validate_gps_points(data.get("puntos_gps"))
        if "checklist_equipos" in data:
            data["checklist_equipos"] = _normalize_checklist(data.get("checklist_equipos"))

        for campo in [
            "correo_centro",
            "telefono_centro",
            "region",
            "localidad",
            "responsabilidad",
            "tecnico_1",
            "firma_tecnico_1",
            "tecnico_2",
            "firma_tecnico_2",
            "recepciona_nombre",
            "recepciona_rut",
            "firma_recepciona",
            "puntos_gps",
            "sellos",
            "medicion_fase_neutro",
            "medicion_neutro_tierra",
            "hertz",
            "descripcion_trabajo",
            "evidencia_foto",
            "checklist_equipos",
        ]:
            if campo in data:
                setattr(item, campo, data.get(campo))

        if "correo_centro" in data:
            correo_centro = (data.get("correo_centro") or "").strip()
            if correo_centro:
                centro = Centro.query.get(item.centro_id)
                if centro:
                    centro.correo_centro = correo_centro
        if "telefono_centro" in data:
            telefono_centro = (data.get("telefono_centro") or "").strip()
            if telefono_centro:
                centro = Centro.query.get(item.centro_id)
                if centro:
                    centro.telefono = telefono_centro
        if "base_tierra" in data:
            base_tierra = _parse_boolish(data.get("base_tierra"))
            if base_tierra is not None:
                centro = Centro.query.get(item.centro_id)
                if centro:
                    centro.base_tierra = base_tierra
        if "cantidad_radares" in data:
            cantidad_radares = _parse_optional_int(data.get("cantidad_radares"), "cantidad_radares")
            if cantidad_radares is not None:
                centro = Centro.query.get(item.centro_id)
                if centro:
                    centro.cantidad_radares = cantidad_radares

        db.session.commit()
        return jsonify({"message": "Mantencion en terreno actualizada", "mantencion": _serialize_mantencion(item)}), 200
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al actualizar mantencion en terreno: {str(e)}"}), 500


@mantenciones_terreno_blueprint.route('/<int:id_mantencion_terreno>', methods=['DELETE'])
def eliminar_mantencion_terreno(id_mantencion_terreno):
    try:
        item = MantencionTerreno.query.get(id_mantencion_terreno)
        if not item:
            return jsonify({"error": "Mantencion en terreno no encontrada"}), 404
        db.session.delete(item)
        db.session.commit()
        return jsonify({"message": "Mantencion en terreno eliminada"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al eliminar mantencion en terreno: {str(e)}"}), 500


@mantenciones_terreno_blueprint.route('/<int:id_mantencion_terreno>/cambios_equipo', methods=['GET'])
def listar_cambios_equipo_mantencion(id_mantencion_terreno):
    try:
        mantencion = MantencionTerreno.query.get(id_mantencion_terreno)
        if not mantencion:
            return jsonify({"error": "Mantencion en terreno no encontrada"}), 404

        cambios = (
            CambioEquipoMantencion.query
            .filter(CambioEquipoMantencion.mantencion_id == id_mantencion_terreno)
            .order_by(CambioEquipoMantencion.created_at.desc(), CambioEquipoMantencion.id_cambio_equipo_mantencion.desc())
            .all()
        )
        return jsonify([_serialize_cambio_equipo(c) for c in cambios]), 200
    except Exception as e:
        return jsonify({"error": f"Error al listar cambios de equipo: {str(e)}"}), 500


@mantenciones_terreno_blueprint.route('/<int:id_mantencion_terreno>/cambios_equipo', methods=['POST'])
def crear_cambio_equipo_mantencion(id_mantencion_terreno):
    data = request.get_json() or {}
    try:
        mantencion = MantencionTerreno.query.get(id_mantencion_terreno)
        if not mantencion:
            return jsonify({"error": "Mantencion en terreno no encontrada"}), 404

        equipo_id = data.get("equipo_id")
        if not equipo_id:
            return jsonify({"error": "equipo_id es requerido"}), 400

        equipo = EquiposIP.query.get(equipo_id)
        if not equipo or int(equipo.centro_id or 0) != int(mantencion.centro_id or 0):
            return jsonify({"error": "Equipo no encontrado para este centro"}), 404

        serie_nueva = (data.get("serie_nueva") or "").strip() or None
        codigo_nuevo = (data.get("codigo_nuevo") or "").strip() or None
        # Si no llega codigo_nuevo desde cliente, derivarlo del N° serie nuevo (primeros 5 dígitos),
        # manteniendo el mismo criterio usado en planilla de armado.
        if not codigo_nuevo and serie_nueva:
            solo_numeros = re.sub(r"\D+", "", serie_nueva)
            codigo_nuevo = (solo_numeros[:5] if solo_numeros else serie_nueva[:5]) or None
        if not serie_nueva and not codigo_nuevo:
            return jsonify({"error": "Debes ingresar serie_nueva o codigo_nuevo"}), 400

        serie_anterior = equipo.numero_serie
        codigo_anterior = equipo.codigo

        if serie_nueva:
            equipo.numero_serie = serie_nueva
        if codigo_nuevo:
            equipo.codigo = codigo_nuevo

        armado_id = data.get("armado_id")
        armado = None
        if armado_id:
            armado = Armado.query.get(armado_id)
            if not armado or int(armado.centro_id or 0) != int(mantencion.centro_id or 0):
                return jsonify({"error": "El armado indicado no pertenece al centro"}), 400
        else:
            armado = (
                Armado.query
                .filter(Armado.centro_id == mantencion.centro_id)
                .order_by(Armado.fecha_cierre.desc(), Armado.id_armado.desc())
                .first()
            )

        tecnico = (data.get("tecnico") or "").strip() or mantencion.tecnico_1 or None
        observacion = data.get("observacion")

        cambio = CambioEquipoMantencion(
            mantencion_id=mantencion.id_mantencion_terreno,
            centro_id=mantencion.centro_id,
            armado_id=armado.id_armado if armado else None,
            equipo_id=equipo.id_equipo,
            equipo=equipo.nombre or "Equipo",
            serie_anterior=serie_anterior,
            codigo_anterior=codigo_anterior,
            serie_nueva=equipo.numero_serie,
            codigo_nuevo=equipo.codigo,
            tecnico=tecnico,
            observacion=observacion,
        )
        db.session.add(cambio)

        # Impacta historial global de armados sin borrar trazabilidad anterior.
        if armado:
            # En mantenciones no se debe arrastrar la caja del armado original.
            caja_mov = "Sin caja"
            db.session.add(
                ArmadoCajaMovimiento(
                    armado_id=armado.id_armado,
                    tipo="equipo",
                    item_id=equipo.id_equipo,
                    nombre_item=f"{equipo.nombre} (reemplazo_mantencion_N{mantencion.id_mantencion_terreno})",
                    numero_serie=equipo.numero_serie,
                    caja=caja_mov,
                    cantidad=1,
                    tecnico_id=armado.tecnico_id,
                )
            )

        db.session.commit()
        return jsonify({"message": "Cambio de equipo registrado", "cambio": _serialize_cambio_equipo(cambio)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al registrar cambio de equipo: {str(e)}"}), 500
