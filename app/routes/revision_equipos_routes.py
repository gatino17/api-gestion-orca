from datetime import datetime
import json

import jwt
from flask import Blueprint, current_app, jsonify, request

from ..database import db
from ..models import (
    Centro,
    RetiroTerreno,
    RetiroTerrenoEquipo,
    RevisionEquipoDetalle,
    RevisionEquipoEvento,
    RevisionEquipoOrden,
    User,
)


revision_equipos_blueprint = Blueprint("revision_equipos", __name__)

AREAS_VALIDAS = {"camaras", "pc", "energia"}
ESTADOS_VALIDOS = {"pendiente", "en_revision", "diagnosticado", "cerrado"}
RESULTADOS_VALIDOS = {"operativo", "no_operativo", "reparable", "no_reparable", "requiere_repuesto", ""}


def _usuario_actual():
    token_header = request.headers.get("Authorization") or ""
    if not token_header.startswith("Bearer "):
        return None
    token_value = token_header.split("Bearer ", 1)[1].strip()
    if not token_value:
        return None

    secret_candidates = [
        current_app.config.get("SECRET_KEY"),
        "remoto753524",
    ]
    for secret in secret_candidates:
        if not secret:
            continue
        try:
            payload = jwt.decode(token_value, secret, algorithms=["HS256"])
            user_id = payload.get("user_id") or payload.get("id") or payload.get("sub")
            return User.query.get(int(user_id)) if user_id is not None else None
        except Exception:
            continue
    return None


def _serialize_detalle(d: RevisionEquipoDetalle):
    return {
        "id_revision_detalle": d.id_revision_detalle,
        "revision_orden_id": d.revision_orden_id,
        "retiro_equipo_id": d.retiro_equipo_id,
        "equipo_nombre": d.equipo_nombre,
        "numero_serie": d.numero_serie,
        "codigo": d.codigo,
        "checklist_ok": bool(d.checklist_ok),
        "diagnostico": d.diagnostico,
        "resultado": d.resultado,
        "disponible_bodega": bool(d.disponible_bodega),
        "fecha_disponible_bodega": d.fecha_disponible_bodega.isoformat() if d.fecha_disponible_bodega else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


def _serialize_orden(o: RevisionEquipoOrden, include_detalles=True):
    centro = o.centro
    cliente = centro.cliente if centro else None
    retiro = o.retiro
    checklist_items = []
    if o.checklist_json:
        try:
            parsed = json.loads(o.checklist_json)
            if isinstance(parsed, list):
                checklist_items = parsed
        except Exception:
            checklist_items = []
    return {
        "id_revision_orden": o.id_revision_orden,
        "retiro_terreno_id": o.retiro_terreno_id,
        "centro_id": o.centro_id,
        "area": o.area,
        "estado": o.estado,
        "asignado_user_id": o.asignado_user_id,
        "asignado_nombre": o.asignado_nombre,
        "creado_por_user_id": o.creado_por_user_id,
        "fecha_asignacion": o.fecha_asignacion.isoformat() if o.fecha_asignacion else None,
        "fecha_inicio_revision": o.fecha_inicio_revision.isoformat() if o.fecha_inicio_revision else None,
        "fecha_cierre": o.fecha_cierre.isoformat() if o.fecha_cierre else None,
        "observacion": o.observacion,
        "checklist_items": checklist_items,
        "centro": {
            "id_centro": centro.id_centro,
            "nombre": centro.nombre,
            "nombre_ponton": centro.nombre_ponton,
            "area": centro.area,
        } if centro else None,
        "cliente": {
            "id_cliente": cliente.id_cliente,
            "nombre": cliente.nombre,
        } if cliente else None,
        "retiro": {
            "id_retiro_terreno": retiro.id_retiro_terreno,
            "fecha_retiro": retiro.fecha_retiro.isoformat() if retiro and retiro.fecha_retiro else None,
            "fecha_recepcion_bodega": retiro.fecha_recepcion_bodega.isoformat() if retiro and retiro.fecha_recepcion_bodega else None,
            "tecnico_1": retiro.tecnico_1 if retiro else None,
            "tecnico_2": retiro.tecnico_2 if retiro else None,
            "observacion": retiro.observacion if retiro else None,
        } if retiro else None,
        "detalles": [_serialize_detalle(d) for d in (o.detalles or [])] if include_detalles else [],
        "eventos": [
            {
                "id_evento": ev.id_evento,
                "revision_detalle_id": ev.revision_detalle_id,
                "evento": ev.evento,
                "resultado": ev.resultado,
                "observacion": ev.observacion,
                "user_nombre": ev.user_nombre,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
            }
            for ev in sorted((o.eventos or []), key=lambda x: x.created_at or datetime.min, reverse=True)
        ] if include_detalles else [],
    }


@revision_equipos_blueprint.route("/ordenes", methods=["GET"])
def listar_ordenes():
    try:
        estado = (request.args.get("estado") or "").strip().lower()
        area = (request.args.get("area") or "").strip().lower()
        asignado_user_id = request.args.get("asignado_user_id", type=int)

        query = RevisionEquipoOrden.query
        if estado:
            query = query.filter(RevisionEquipoOrden.estado == estado)
        if area:
            query = query.filter(RevisionEquipoOrden.area == area)
        if asignado_user_id:
            query = query.filter(RevisionEquipoOrden.asignado_user_id == asignado_user_id)

        rows = query.order_by(
            RevisionEquipoOrden.fecha_asignacion.desc(),
            RevisionEquipoOrden.id_revision_orden.desc(),
        ).all()
        return jsonify([_serialize_orden(o, include_detalles=True) for o in rows]), 200
    except Exception as e:
        return jsonify({"error": f"Error al listar ordenes de revision: {str(e)}"}), 500


@revision_equipos_blueprint.route("/ordenes/<int:id_orden>", methods=["GET"])
def obtener_orden(id_orden):
    try:
        row = RevisionEquipoOrden.query.get(id_orden)
        if not row:
            return jsonify({"error": "Orden no encontrada"}), 404
        return jsonify(_serialize_orden(row, include_detalles=True)), 200
    except Exception as e:
        return jsonify({"error": f"Error al obtener orden de revision: {str(e)}"}), 500


@revision_equipos_blueprint.route("/ordenes", methods=["POST"])
def crear_orden():
    data = request.get_json() or {}
    try:
        area = str(data.get("area") or "").strip().lower()
        if area not in AREAS_VALIDAS:
            return jsonify({"error": "area invalida"}), 400

        retiro_id = data.get("retiro_terreno_id")
        retiro = RetiroTerreno.query.get(retiro_id) if retiro_id else None

        centro_id = data.get("centro_id") or (retiro.centro_id if retiro else None)
        if not centro_id:
            return jsonify({"error": "centro_id es requerido"}), 400
        centro = Centro.query.get(centro_id)
        if not centro:
            return jsonify({"error": "Centro no encontrado"}), 404

        if retiro:
            existente = (
                RevisionEquipoOrden.query.filter(
                    RevisionEquipoOrden.retiro_terreno_id == retiro.id_retiro_terreno,
                    RevisionEquipoOrden.area == area,
                    RevisionEquipoOrden.estado != "cerrado",
                )
                .order_by(RevisionEquipoOrden.id_revision_orden.desc())
                .first()
            )
            if existente:
                return jsonify({"error": "Ya existe una orden activa para este retiro y area"}), 400

        asignado_user_id = data.get("asignado_user_id")
        asignado_nombre = str(data.get("asignado_nombre") or "").strip() or None
        if asignado_user_id:
            u = User.query.get(asignado_user_id)
            if not u:
                return jsonify({"error": "Usuario asignado no encontrado"}), 404
            if not asignado_nombre:
                asignado_nombre = u.name

        usuario = _usuario_actual()

        orden = RevisionEquipoOrden(
            retiro_terreno_id=retiro.id_retiro_terreno if retiro else None,
            centro_id=centro.id_centro,
            area=area,
            estado="pendiente",
            asignado_user_id=asignado_user_id if asignado_user_id else None,
            asignado_nombre=asignado_nombre,
            creado_por_user_id=(usuario.id if usuario else None),
            observacion=data.get("observacion"),
            checklist_json=(json.dumps(data.get("checklist_items"), ensure_ascii=False) if isinstance(data.get("checklist_items"), list) else None),
        )
        db.session.add(orden)
        db.session.flush()

        detalles_payload = data.get("detalles") if isinstance(data.get("detalles"), list) else None
        if detalles_payload is not None:
            for raw in detalles_payload:
                if not isinstance(raw, dict):
                    continue
                nombre = str(raw.get("equipo_nombre") or "").strip()
                if not nombre:
                    continue
                det = RevisionEquipoDetalle(
                    revision_orden_id=orden.id_revision_orden,
                    retiro_equipo_id=raw.get("retiro_equipo_id"),
                    equipo_nombre=nombre,
                    numero_serie=str(raw.get("numero_serie") or "").strip() or None,
                    codigo=str(raw.get("codigo") or "").strip() or None,
                )
                db.session.add(det)
        elif retiro and isinstance(retiro.equipos, list):
            for eq in retiro.equipos:
                if not eq.retirado:
                    continue
                db.session.add(
                    RevisionEquipoDetalle(
                        revision_orden_id=orden.id_revision_orden,
                        retiro_equipo_id=eq.id_retiro_equipo,
                        equipo_nombre=eq.equipo_nombre,
                        numero_serie=eq.numero_serie,
                        codigo=eq.codigo,
                    )
                )

        db.session.commit()
        return jsonify({"message": "Orden de revision creada", "orden": _serialize_orden(orden, include_detalles=True)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al crear orden de revision: {str(e)}"}), 500


@revision_equipos_blueprint.route("/ordenes/<int:id_orden>", methods=["PUT"])
def actualizar_orden(id_orden):
    data = request.get_json() or {}
    try:
        orden = RevisionEquipoOrden.query.get(id_orden)
        if not orden:
            return jsonify({"error": "Orden no encontrada"}), 404

        if "area" in data:
            area = str(data.get("area") or "").strip().lower()
            if area not in AREAS_VALIDAS:
                return jsonify({"error": "area invalida"}), 400
            orden.area = area

        if "estado" in data:
            estado = str(data.get("estado") or "").strip().lower()
            if estado not in ESTADOS_VALIDOS:
                return jsonify({"error": "estado invalido"}), 400
            orden.estado = estado
            if estado == "en_revision" and not orden.fecha_inicio_revision:
                orden.fecha_inicio_revision = datetime.utcnow()
            if estado == "cerrado":
                orden.fecha_cierre = datetime.utcnow()

        if "asignado_user_id" in data:
            uid = data.get("asignado_user_id")
            if uid:
                u = User.query.get(uid)
                if not u:
                    return jsonify({"error": "Usuario asignado no encontrado"}), 404
                orden.asignado_user_id = u.id
                orden.asignado_nombre = str(data.get("asignado_nombre") or u.name or "").strip() or u.name
            else:
                orden.asignado_user_id = None
                orden.asignado_nombre = str(data.get("asignado_nombre") or "").strip() or None

        if "observacion" in data:
            orden.observacion = data.get("observacion")
        if "checklist_items" in data:
            checklist_items = data.get("checklist_items")
            if checklist_items is None:
                orden.checklist_json = None
            elif isinstance(checklist_items, list):
                orden.checklist_json = json.dumps(checklist_items, ensure_ascii=False)
            else:
                return jsonify({"error": "checklist_items invalido"}), 400

        detalles_payload = data.get("detalles")
        if isinstance(detalles_payload, list):
            detalles_actuales = {d.id_revision_detalle: d for d in (orden.detalles or [])}
            for raw in detalles_payload:
                if not isinstance(raw, dict):
                    continue
                detalle_id = raw.get("id_revision_detalle")
                d = detalles_actuales.get(detalle_id)
                if not d:
                    continue
                if "checklist_ok" in raw:
                    d.checklist_ok = bool(raw.get("checklist_ok"))
                if "diagnostico" in raw:
                    d.diagnostico = raw.get("diagnostico")
                if "resultado" in raw:
                    resultado = str(raw.get("resultado") or "").strip().lower()
                    if resultado in {"reparable", "no_reparable"}:
                        resultado = "no_operativo"
                    if resultado not in RESULTADOS_VALIDOS:
                        return jsonify({"error": f"resultado invalido en detalle {detalle_id}"}), 400
                    d.resultado = resultado or None
                    d.disponible_bodega = False if d.resultado != "operativo" else d.disponible_bodega
                if "numero_serie" in raw:
                    d.numero_serie = str(raw.get("numero_serie") or "").strip() or None
                if "codigo" in raw:
                    d.codigo = str(raw.get("codigo") or "").strip() or None

        db.session.commit()
        return jsonify({"message": "Orden actualizada", "orden": _serialize_orden(orden, include_detalles=True)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al actualizar orden de revision: {str(e)}"}), 500


@revision_equipos_blueprint.route("/ordenes/<int:id_orden>", methods=["DELETE"])
def eliminar_orden(id_orden):
    try:
        orden = RevisionEquipoOrden.query.get(id_orden)
        if not orden:
            return jsonify({"error": "Orden no encontrada"}), 404
        db.session.delete(orden)
        db.session.commit()
        return jsonify({"message": "Orden eliminada"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al eliminar orden de revision: {str(e)}"}), 500


@revision_equipos_blueprint.route("/ordenes/<int:id_orden>/devolver_operativos_bodega", methods=["POST"])
def devolver_operativos_bodega(id_orden):
    data = request.get_json() or {}
    try:
        orden = RevisionEquipoOrden.query.get(id_orden)
        if not orden:
            return jsonify({"error": "Orden no encontrada"}), 404

        usuario = _usuario_actual()
        observacion = data.get("observacion")
        actualizados = 0
        for d in (orden.detalles or []):
            resultado = str(d.resultado or "").strip().lower()
            if resultado in {"operativo", "no_operativo", "no_reparable"}:
                d.disponible_bodega = True
                if not d.fecha_disponible_bodega:
                    d.fecha_disponible_bodega = datetime.utcnow()
                db.session.add(
                    RevisionEquipoEvento(
                        revision_orden_id=orden.id_revision_orden,
                        revision_detalle_id=d.id_revision_detalle,
                        evento="devuelto_bodega",
                        resultado=d.resultado,
                        observacion=observacion,
                        user_id=(usuario.id if usuario else None),
                        user_nombre=((usuario.name if usuario else None) or "Sistema"),
                    )
                )
                actualizados += 1

        if actualizados == 0:
            return jsonify({"error": "No hay equipos listos para devolver a bodega"}), 400

        if str(orden.estado or "").lower() != "cerrado":
            orden.estado = "cerrado"
            orden.fecha_cierre = orden.fecha_cierre or datetime.utcnow()

        db.session.commit()
        return jsonify({
            "message": f"Equipos devueltos a bodega: {actualizados}",
            "orden": _serialize_orden(orden, include_detalles=True),
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"Error al devolver equipos a bodega: {str(e)}"}), 500
