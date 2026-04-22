from datetime import datetime

from flask import Blueprint, jsonify, request

from ..database import db
from ..models import Encargado, TecnicoBloqueo


tecnico_bloqueos_blueprint = Blueprint("tecnico_bloqueos", __name__)


def _parse_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _serialize_bloqueo(item: TecnicoBloqueo):
    tecnico = item.tecnico
    return {
        "id_bloqueo": item.id_bloqueo,
        "tecnico_id": item.tecnico_id,
        "tipo": item.tipo,
        "fecha_inicio": item.fecha_inicio.isoformat() if item.fecha_inicio else None,
        "fecha_fin": item.fecha_fin.isoformat() if item.fecha_fin else None,
        "motivo": item.motivo,
        "estado": item.estado,
        "created_by_user_id": item.created_by_user_id,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "tecnico": {
            "id_encargado": tecnico.id_encargado if tecnico else None,
            "nombre_encargado": tecnico.nombre_encargado if tecnico else None,
        },
    }


@tecnico_bloqueos_blueprint.route("/", methods=["GET"])
def listar_bloqueos():
    try:
        query = TecnicoBloqueo.query
        tecnico_id = request.args.get("tecnico_id", type=int)
        estado = (request.args.get("estado") or "").strip().lower()
        if tecnico_id:
            query = query.filter(TecnicoBloqueo.tecnico_id == tecnico_id)
        if estado:
            query = query.filter(TecnicoBloqueo.estado.ilike(estado))

        rows = query.order_by(TecnicoBloqueo.fecha_inicio.desc(), TecnicoBloqueo.id_bloqueo.desc()).all()
        return jsonify([_serialize_bloqueo(row) for row in rows]), 200
    except Exception as exc:
        return jsonify({"error": f"Error al listar bloqueos tecnicos: {str(exc)}"}), 500


@tecnico_bloqueos_blueprint.route("/", methods=["POST"])
def crear_bloqueo():
    try:
        data = request.get_json(silent=True) or {}
        tecnico_id = data.get("tecnico_id")
        tipo = str(data.get("tipo") or "").strip().lower()
        fecha_inicio = _parse_date(data.get("fecha_inicio"))
        fecha_fin = _parse_date(data.get("fecha_fin"))
        motivo = data.get("motivo")
        estado = str(data.get("estado") or "activo").strip().lower()
        created_by_user_id = data.get("created_by_user_id")

        if not tecnico_id:
            return jsonify({"error": "tecnico_id es obligatorio"}), 400
        tecnico = Encargado.query.get(tecnico_id)
        if not tecnico:
            return jsonify({"error": "Tecnico no encontrado"}), 404
        if tipo not in {"vacaciones", "licencia", "permiso", "dia_libre", "compensatorio"}:
            return jsonify({"error": "tipo invalido (vacaciones/licencia/permiso/dia_libre/compensatorio)"}), 400
        if estado not in {"activo", "anulado"}:
            return jsonify({"error": "estado invalido (activo/anulado)"}), 400
        if not fecha_inicio or not fecha_fin:
            return jsonify({"error": "fecha_inicio y fecha_fin son obligatorias"}), 400
        if fecha_fin < fecha_inicio:
            return jsonify({"error": "fecha_fin no puede ser menor a fecha_inicio"}), 400

        item = TecnicoBloqueo(
            tecnico_id=int(tecnico_id),
            tipo=tipo,
            fecha_inicio=fecha_inicio,
            fecha_fin=fecha_fin,
            motivo=motivo,
            estado=estado,
            created_by_user_id=int(created_by_user_id) if created_by_user_id else None,
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({"message": "Bloqueo creado", "bloqueo": _serialize_bloqueo(item)}), 201
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Error al crear bloqueo tecnico: {str(exc)}"}), 500


@tecnico_bloqueos_blueprint.route("/<int:id_bloqueo>", methods=["PUT"])
def actualizar_bloqueo(id_bloqueo: int):
    try:
        data = request.get_json(silent=True) or {}
        item = TecnicoBloqueo.query.get(id_bloqueo)
        if not item:
            return jsonify({"error": "Bloqueo no encontrado"}), 404

        if "tecnico_id" in data and data.get("tecnico_id"):
            tecnico = Encargado.query.get(data.get("tecnico_id"))
            if not tecnico:
                return jsonify({"error": "Tecnico no encontrado"}), 404
            item.tecnico_id = int(data.get("tecnico_id"))

        if "tipo" in data:
            tipo = str(data.get("tipo") or "").strip().lower()
            if tipo not in {"vacaciones", "licencia", "permiso", "dia_libre", "compensatorio"}:
                return jsonify({"error": "tipo invalido (vacaciones/licencia/permiso/dia_libre/compensatorio)"}), 400
            item.tipo = tipo

        if "estado" in data:
            estado = str(data.get("estado") or "").strip().lower()
            if estado not in {"activo", "anulado"}:
                return jsonify({"error": "estado invalido (activo/anulado)"}), 400
            item.estado = estado

        if "motivo" in data:
            item.motivo = data.get("motivo")

        if "fecha_inicio" in data:
            parsed = _parse_date(data.get("fecha_inicio"))
            if not parsed:
                return jsonify({"error": "fecha_inicio invalida"}), 400
            item.fecha_inicio = parsed

        if "fecha_fin" in data:
            parsed = _parse_date(data.get("fecha_fin"))
            if not parsed:
                return jsonify({"error": "fecha_fin invalida"}), 400
            item.fecha_fin = parsed

        if item.fecha_fin < item.fecha_inicio:
            return jsonify({"error": "fecha_fin no puede ser menor a fecha_inicio"}), 400

        db.session.commit()
        return jsonify({"message": "Bloqueo actualizado", "bloqueo": _serialize_bloqueo(item)}), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Error al actualizar bloqueo tecnico: {str(exc)}"}), 500


@tecnico_bloqueos_blueprint.route("/<int:id_bloqueo>", methods=["DELETE"])
def eliminar_bloqueo(id_bloqueo: int):
    try:
        item = TecnicoBloqueo.query.get(id_bloqueo)
        if not item:
            return jsonify({"error": "Bloqueo no encontrado"}), 404
        db.session.delete(item)
        db.session.commit()
        return jsonify({"message": "Bloqueo eliminado"}), 200
    except Exception as exc:
        db.session.rollback()
        return jsonify({"error": f"Error al eliminar bloqueo tecnico: {str(exc)}"}), 500
