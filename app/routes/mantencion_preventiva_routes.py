import json
from datetime import datetime

from flask import Blueprint, jsonify, request

from ..database import db
from ..models import MantencionPreventivaRevision

mantencion_preventiva_blueprint = Blueprint("mantencion_preventiva", __name__)


def _to_int(value, default):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@mantencion_preventiva_blueprint.route("/", methods=["GET"])
def obtener_revisiones_preventivas():
    anio = _to_int(request.args.get("anio"), datetime.utcnow().year)
    mes = _to_int(request.args.get("mes"), datetime.utcnow().month)

    query = MantencionPreventivaRevision.query.filter_by(anio=anio, mes=mes)
    centros = request.args.get("centros")
    if centros:
        ids = []
        for part in centros.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                ids.append(int(part))
            except ValueError:
                continue
        if ids:
            query = query.filter(MantencionPreventivaRevision.centro_id.in_(ids))

    revisiones = query.all()
    data = []
    for revision in revisiones:
        data.append(
            {
                "id_revision": revision.id_revision,
                "centro_id": revision.centro_id,
                "anio": revision.anio,
                "mes": revision.mes,
                "datos_base": json.loads(revision.datos_base_json or "{}"),
                "estados": json.loads(revision.estados_json or "{}"),
                "observacion": revision.observacion or "",
                "fecha_revision": revision.fecha_revision.isoformat() if revision.fecha_revision else "",
            }
        )

    return jsonify(data), 200


@mantencion_preventiva_blueprint.route("/bulk", methods=["POST"])
def guardar_revisiones_preventivas():
    payload = request.get_json(silent=True) or {}
    anio = _to_int(payload.get("anio"), datetime.utcnow().year)
    mes = _to_int(payload.get("mes"), datetime.utcnow().month)
    revisiones = payload.get("revisiones", [])

    if not isinstance(revisiones, list):
        return jsonify({"error": "Formato invalido para revisiones"}), 400

    guardadas = 0
    for item in revisiones:
        try:
            centro_id = int(item.get("centro_id"))
        except (TypeError, ValueError):
            continue

        datos_base = item.get("datos_base") or {}
        estados = item.get("estados") or {}
        observacion = item.get("observacion") or ""
        fecha_revision = item.get("fecha_revision") or ""

        registro = MantencionPreventivaRevision.query.filter_by(
            centro_id=centro_id, anio=anio, mes=mes
        ).first()
        if not registro:
            registro = MantencionPreventivaRevision(
                centro_id=centro_id,
                anio=anio,
                mes=mes,
            )
            db.session.add(registro)

        registro.datos_base_json = json.dumps(datos_base, ensure_ascii=False)
        registro.estados_json = json.dumps(estados, ensure_ascii=False)
        registro.observacion = observacion
        if fecha_revision:
            try:
                registro.fecha_revision = datetime.strptime(fecha_revision, "%Y-%m-%d").date()
            except ValueError:
                registro.fecha_revision = None
        else:
            registro.fecha_revision = None
        guardadas += 1

    db.session.commit()
    return jsonify({"message": "Revisiones guardadas", "guardadas": guardadas}), 200

