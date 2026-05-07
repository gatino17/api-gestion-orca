from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
import json
import re

from flask import Blueprint, jsonify, request

from ..database import db
from ..models import Centro, RendicionAbono, RendicionGasto

rendiciones_blueprint = Blueprint("rendiciones", __name__)


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _parse_decimal(value):
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _safe_json_array(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []


def _normalize_text(value):
    txt = str(value or "").strip().lower()
    if not txt:
        return ""
    return re.sub(r"\s+", " ", txt)


def _tecnico_key(tecnico_user_id, tecnico_nombre):
    user_id = int(tecnico_user_id or 0)
    if user_id > 0:
        return f"id:{user_id}"
    nombre = _normalize_text(tecnico_nombre)
    return f"name:{nombre}" if nombre else ""


def _serialize_rendicion(item: RendicionGasto):
    centro = item.centro
    cliente = item.cliente or (centro.cliente if centro else None)
    return {
        "id_rendicion": item.id_rendicion,
        "tecnico_user_id": item.tecnico_user_id,
        "tecnico_nombre": item.tecnico_nombre,
        "cliente_id": item.cliente_id or (cliente.id_cliente if cliente else None),
        "cliente_nombre": cliente.nombre if cliente else None,
        "centro_id": item.centro_id,
        "centro_nombre": centro.nombre if centro else None,
        "actividad_tipo": item.actividad_tipo,
        "actividad_id": item.actividad_id,
        "categoria": item.categoria,
        "descripcion": item.descripcion,
        "monto": float(item.monto or 0),
        "medio_pago": item.medio_pago,
        "fecha_gasto": item.fecha_gasto.isoformat() if item.fecha_gasto else None,
        "estado": item.estado,
        "edicion_solicitada": bool(item.edicion_solicitada),
        "edicion_motivo": item.edicion_motivo,
        "edicion_respuesta": item.edicion_respuesta,
        "edicion_solicitada_at": item.edicion_solicitada_at.isoformat() if item.edicion_solicitada_at else None,
        "edicion_resuelta_at": item.edicion_resuelta_at.isoformat() if item.edicion_resuelta_at else None,
        "editable_hasta": item.editable_hasta.isoformat() if item.editable_hasta else None,
        "adjuntos": _safe_json_array(item.adjuntos_json),
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _serialize_abono(item: RendicionAbono):
    return {
        "id_abono": item.id_abono,
        "tecnico_user_id": item.tecnico_user_id,
        "tecnico_nombre": item.tecnico_nombre,
        "fecha_abono": item.fecha_abono.isoformat() if item.fecha_abono else None,
        "monto": float(item.monto or 0),
        "transferido_por": item.transferido_por,
        "referencia": item.referencia,
        "observacion": item.observacion,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _calcular_saldos(abonos, rendiciones_enviadas):
    data = defaultdict(
        lambda: {
            "tecnico_user_id": None,
            "tecnico_nombre": "",
            "total_abonos": Decimal("0"),
            "total_rendido": Decimal("0"),
        }
    )

    for item in abonos:
        key = _tecnico_key(item.tecnico_user_id, item.tecnico_nombre)
        if not key:
            continue
        row = data[key]
        row["tecnico_user_id"] = item.tecnico_user_id or row["tecnico_user_id"]
        if not row["tecnico_nombre"]:
            row["tecnico_nombre"] = str(item.tecnico_nombre or "").strip()
        row["total_abonos"] += Decimal(str(item.monto or 0))

    for item in rendiciones_enviadas:
        key = _tecnico_key(item.tecnico_user_id, item.tecnico_nombre)
        if not key:
            continue
        row = data[key]
        row["tecnico_user_id"] = item.tecnico_user_id or row["tecnico_user_id"]
        if not row["tecnico_nombre"]:
            row["tecnico_nombre"] = str(item.tecnico_nombre or "").strip()
        row["total_rendido"] += Decimal(str(item.monto or 0))

    out = []
    for row in data.values():
        saldo = row["total_abonos"] - row["total_rendido"]
        out.append(
            {
                "tecnico_user_id": row["tecnico_user_id"],
                "tecnico_nombre": row["tecnico_nombre"] or None,
                "total_abonos": float(row["total_abonos"]),
                "total_rendido": float(row["total_rendido"]),
                "saldo": float(saldo),
            }
        )

    out.sort(key=lambda x: (_normalize_text(x.get("tecnico_nombre")), -(x.get("tecnico_user_id") or 0)))
    return out


@rendiciones_blueprint.route("/", methods=["GET"])
def listar_rendiciones():
    q = RendicionGasto.query

    tecnico_user_id = request.args.get("tecnico_user_id", type=int)
    cliente_id = request.args.get("cliente_id", type=int)
    centro_id = request.args.get("centro_id", type=int)
    estado = str(request.args.get("estado", "")).strip().lower()
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    top = request.args.get("top", default=400, type=int)

    if tecnico_user_id:
        q = q.filter(RendicionGasto.tecnico_user_id == tecnico_user_id)
    if cliente_id:
        q = q.filter(RendicionGasto.cliente_id == cliente_id)
    if centro_id:
        q = q.filter(RendicionGasto.centro_id == centro_id)
    if estado:
        q = q.filter(RendicionGasto.estado == estado)
    if fecha_desde:
        q = q.filter(RendicionGasto.fecha_gasto >= _parse_date(fecha_desde))
    if fecha_hasta:
        q = q.filter(RendicionGasto.fecha_gasto <= _parse_date(fecha_hasta))

    top = max(1, min(top or 400, 2000))
    items = q.order_by(RendicionGasto.fecha_gasto.desc(), RendicionGasto.created_at.desc()).limit(top).all()
    return jsonify([_serialize_rendicion(item) for item in items]), 200


@rendiciones_blueprint.route("/abonos", methods=["GET"])
def listar_abonos():
    q = RendicionAbono.query

    tecnico_user_id = request.args.get("tecnico_user_id", type=int)
    tecnico_nombre = str(request.args.get("tecnico_nombre", "")).strip()
    fecha_desde = request.args.get("fecha_desde")
    fecha_hasta = request.args.get("fecha_hasta")
    top = request.args.get("top", default=500, type=int)

    if tecnico_user_id:
        q = q.filter(RendicionAbono.tecnico_user_id == tecnico_user_id)
    elif tecnico_nombre:
        q = q.filter(RendicionAbono.tecnico_nombre.ilike(f"%{tecnico_nombre}%"))
    if fecha_desde:
        q = q.filter(RendicionAbono.fecha_abono >= _parse_date(fecha_desde))
    if fecha_hasta:
        q = q.filter(RendicionAbono.fecha_abono <= _parse_date(fecha_hasta))

    top = max(1, min(top or 500, 2000))
    items = q.order_by(RendicionAbono.fecha_abono.desc(), RendicionAbono.created_at.desc()).limit(top).all()
    return jsonify([_serialize_abono(item) for item in items]), 200


@rendiciones_blueprint.route("/abonos", methods=["POST"])
def crear_abono():
    data = request.get_json() or {}

    tecnico_user_id = data.get("tecnico_user_id")
    tecnico_nombre = str(data.get("tecnico_nombre", "")).strip()
    transferido_por = str(data.get("transferido_por", "")).strip()
    fecha_abono = _parse_date(data.get("fecha_abono"))
    monto = _parse_decimal(data.get("monto"))

    if not tecnico_user_id and not tecnico_nombre:
        return jsonify({"error": "Debes indicar tecnico_user_id o tecnico_nombre."}), 400
    if not transferido_por:
        return jsonify({"error": "El campo transferido_por es obligatorio."}), 400
    if not fecha_abono:
        return jsonify({"error": "Fecha de abono es obligatoria (YYYY-MM-DD)."}), 400
    if monto <= 0:
        return jsonify({"error": "El monto debe ser mayor a 0."}), 400

    nuevo = RendicionAbono(
        tecnico_user_id=tecnico_user_id,
        tecnico_nombre=tecnico_nombre or None,
        fecha_abono=fecha_abono,
        monto=monto,
        transferido_por=transferido_por,
        referencia=str(data.get("referencia", "")).strip() or None,
        observacion=str(data.get("observacion", "")).strip() or None,
    )
    db.session.add(nuevo)
    db.session.commit()
    return jsonify({"message": "Abono registrado", "abono": _serialize_abono(nuevo)}), 201


@rendiciones_blueprint.route("/saldos", methods=["GET"])
def listar_saldos_tecnicos():
    tecnico_user_id = request.args.get("tecnico_user_id", type=int)
    tecnico_nombre = str(request.args.get("tecnico_nombre", "")).strip()

    q_abonos = RendicionAbono.query
    q_rendiciones = RendicionGasto.query.filter(RendicionGasto.estado == "enviado")

    if tecnico_user_id:
        q_abonos = q_abonos.filter(RendicionAbono.tecnico_user_id == tecnico_user_id)
        q_rendiciones = q_rendiciones.filter(RendicionGasto.tecnico_user_id == tecnico_user_id)
    elif tecnico_nombre:
        like = f"%{tecnico_nombre}%"
        q_abonos = q_abonos.filter(RendicionAbono.tecnico_nombre.ilike(like))
        q_rendiciones = q_rendiciones.filter(RendicionGasto.tecnico_nombre.ilike(like))

    saldos = _calcular_saldos(q_abonos.all(), q_rendiciones.all())
    return jsonify(saldos), 200


@rendiciones_blueprint.route("/", methods=["POST"])
def crear_rendicion():
    data = request.get_json() or {}
    descripcion = str(data.get("descripcion", "")).strip()
    fecha_gasto = _parse_date(data.get("fecha_gasto"))

    if not descripcion:
        return jsonify({"error": "Descripcion es obligatoria."}), 400
    if not fecha_gasto:
        return jsonify({"error": "Fecha de gasto es obligatoria (YYYY-MM-DD)."}), 400

    centro_id = data.get("centro_id")
    cliente_id = data.get("cliente_id")
    if centro_id and not cliente_id:
        centro = Centro.query.get(centro_id)
        if centro and centro.cliente:
            cliente_id = centro.cliente.id_cliente

    adjuntos = _safe_json_array(data.get("adjuntos"))
    nuevo = RendicionGasto(
        tecnico_user_id=data.get("tecnico_user_id"),
        tecnico_nombre=data.get("tecnico_nombre"),
        cliente_id=cliente_id,
        centro_id=centro_id,
        actividad_tipo=data.get("actividad_tipo"),
        actividad_id=data.get("actividad_id"),
        categoria=data.get("categoria"),
        descripcion=descripcion,
        monto=_parse_decimal(data.get("monto")),
        medio_pago=data.get("medio_pago"),
        fecha_gasto=fecha_gasto,
        estado=str(data.get("estado", "borrador")).strip().lower() or "borrador",
        adjuntos_json=json.dumps(adjuntos, ensure_ascii=False),
    )
    db.session.add(nuevo)
    db.session.commit()
    return jsonify({"message": "Rendicion creada", "rendicion": _serialize_rendicion(nuevo)}), 201


@rendiciones_blueprint.route("/<int:id_rendicion>", methods=["PUT"])
def actualizar_rendicion(id_rendicion):
    item = RendicionGasto.query.get_or_404(id_rendicion)
    data = request.get_json() or {}
    estado_actual = str(item.estado or "").strip().lower()
    if estado_actual == "enviado":
        return jsonify({"error": "Rendicion enviada. Debes solicitar edicion para modificar."}), 400
    if estado_actual == "edicion_solicitada":
        return jsonify({"error": "La solicitud de edicion esta pendiente de aprobacion."}), 400
    if estado_actual == "edicion_rechazada":
        return jsonify({"error": "La solicitud de edicion fue rechazada."}), 400
    if estado_actual == "edicion_autorizada" and item.editable_hasta and datetime.utcnow() > item.editable_hasta:
        return jsonify({"error": "La autorizacion de edicion expiro. Solicita nuevamente."}), 400

    if "tecnico_user_id" in data:
        item.tecnico_user_id = data.get("tecnico_user_id")
    if "tecnico_nombre" in data:
        item.tecnico_nombre = data.get("tecnico_nombre")
    if "cliente_id" in data:
        item.cliente_id = data.get("cliente_id")
    if "centro_id" in data:
        item.centro_id = data.get("centro_id")
    if "actividad_tipo" in data:
        item.actividad_tipo = data.get("actividad_tipo")
    if "actividad_id" in data:
        item.actividad_id = data.get("actividad_id")
    if "categoria" in data:
        item.categoria = data.get("categoria")
    if "descripcion" in data:
        descripcion = str(data.get("descripcion", "")).strip()
        if not descripcion:
            return jsonify({"error": "Descripcion es obligatoria."}), 400
        item.descripcion = descripcion
    if "monto" in data:
        item.monto = _parse_decimal(data.get("monto"))
    if "medio_pago" in data:
        item.medio_pago = data.get("medio_pago")
    if "fecha_gasto" in data:
        item.fecha_gasto = _parse_date(data.get("fecha_gasto"))
    if "estado" in data:
        item.estado = str(data.get("estado") or "borrador").strip().lower()
    if "adjuntos" in data:
        item.adjuntos_json = json.dumps(_safe_json_array(data.get("adjuntos")), ensure_ascii=False)
    if item.estado == "edicion_autorizada":
        item.estado = "borrador"
    item.edicion_solicitada = False

    db.session.commit()
    return jsonify({"message": "Rendicion actualizada", "rendicion": _serialize_rendicion(item)}), 200


@rendiciones_blueprint.route("/<int:id_rendicion>/enviar", methods=["POST"])
def enviar_rendicion(id_rendicion):
    item = RendicionGasto.query.get_or_404(id_rendicion)
    item.estado = "enviado"
    item.edicion_solicitada = False
    item.edicion_respuesta = None
    item.editable_hasta = None
    db.session.commit()
    return jsonify({"message": "Rendicion enviada", "rendicion": _serialize_rendicion(item)}), 200


@rendiciones_blueprint.route("/<int:id_rendicion>", methods=["DELETE"])
def eliminar_rendicion(id_rendicion):
    item = RendicionGasto.query.get_or_404(id_rendicion)
    db.session.delete(item)
    db.session.commit()
    return jsonify({"message": "Rendicion eliminada"}), 200


@rendiciones_blueprint.route("/<int:id_rendicion>/solicitar_edicion", methods=["POST"])
def solicitar_edicion_rendicion(id_rendicion):
    item = RendicionGasto.query.get_or_404(id_rendicion)
    estado = str(item.estado or "").strip().lower()
    if estado not in ("enviado", "edicion_rechazada"):
        return jsonify({"error": "Solo puedes solicitar edicion en rendiciones enviadas."}), 400
    data = request.get_json() or {}
    motivo = str(data.get("motivo", "")).strip() or None
    item.estado = "edicion_solicitada"
    item.edicion_solicitada = True
    item.edicion_motivo = motivo
    item.edicion_solicitada_at = datetime.utcnow()
    item.edicion_respuesta = None
    item.edicion_resuelta_at = None
    item.editable_hasta = None
    db.session.commit()
    return jsonify({"message": "Solicitud de edicion enviada", "rendicion": _serialize_rendicion(item)}), 200


@rendiciones_blueprint.route("/<int:id_rendicion>/resolver_edicion", methods=["POST"])
def resolver_edicion_rendicion(id_rendicion):
    item = RendicionGasto.query.get_or_404(id_rendicion)
    if str(item.estado or "").strip().lower() != "edicion_solicitada":
        return jsonify({"error": "La rendicion no tiene solicitud de edicion pendiente."}), 400
    data = request.get_json() or {}
    accion = str(data.get("accion", "")).strip().lower()
    respuesta = str(data.get("respuesta", "")).strip() or None
    horas = int(data.get("horas", 24) or 24)
    horas = max(1, min(horas, 168))
    if accion not in ("aprobar", "rechazar"):
        return jsonify({"error": "Accion invalida. Usa aprobar o rechazar."}), 400
    item.edicion_resuelta_at = datetime.utcnow()
    item.edicion_respuesta = respuesta
    item.edicion_solicitada = False
    if accion == "aprobar":
        item.estado = "edicion_autorizada"
        item.editable_hasta = datetime.utcnow() + timedelta(hours=horas)
    else:
        item.estado = "edicion_rechazada"
        item.editable_hasta = None
    db.session.commit()
    return jsonify({"message": f"Solicitud {accion}da", "rendicion": _serialize_rendicion(item)}), 200
