from flask import Blueprint, request, jsonify
from ..models import Armado, ArmadoParticipacion, ArmadoMaterial, Centro, User, EquiposIP
from ..models import ArmadoCajaMovimiento
from ..database import db
from datetime import datetime

armados_blueprint = Blueprint('armados', __name__)


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


@armados_blueprint.route('/', methods=['GET'])
def listar_armados():
    estado = request.args.get('estado')
    tecnico_id = request.args.get('tecnico_id')

    query = Armado.query
    if estado:
        query = query.filter(Armado.estado == estado)
    if tecnico_id:
        query = query.filter(Armado.tecnico_id == tecnico_id)

    armados = query.order_by(Armado.fecha_asignacion.desc()).all()
    resultado = []
    for armado in armados:
        participaciones = ArmadoParticipacion.query.filter_by(armado_id=armado.id_armado).order_by(
            ArmadoParticipacion.fecha_inicio.asc(), ArmadoParticipacion.id_participacion.asc()
        ).all()
        historial_tecnicos = [p.tecnico.name if p.tecnico else f"ID {p.tecnico_id}" for p in participaciones]
        # calcular total de cajas (equipos del centro + materiales del armado)
        cajas_equipos = {e.caja or 'Caja 1' for e in EquiposIP.query.filter_by(centro_id=armado.centro_id).all()}
        cajas_materiales = {m.caja or 'Caja 1' for m in ArmadoMaterial.query.filter_by(armado_id=armado.id_armado).all()}
        total_cajas = len(cajas_equipos.union(cajas_materiales)) or 0

        # fecha_inicio real: si hay fecha_inicio ya fijada úsala, si no, la primera fecha de movimiento o la de asignación
        primera_mov = (
            ArmadoCajaMovimiento.query.filter_by(armado_id=armado.id_armado)
            .order_by(ArmadoCajaMovimiento.fecha.asc())
            .first()
        )
        fecha_inicio_real = armado.fecha_inicio or (primera_mov.fecha.date() if primera_mov else None) or armado.fecha_asignacion

        resultado.append({
            "id_armado": armado.id_armado,
            "centro_id": armado.centro_id,
            "centro": {
                "id_centro": armado.centro.id_centro if armado.centro else None,
                "nombre": armado.centro.nombre if armado.centro else None,
                "cliente": armado.centro.cliente.nombre if armado.centro and armado.centro.cliente else None
            },
            "tecnico_id": armado.tecnico_id,
            "tecnico": {
                "id": armado.tecnico.id if armado.tecnico else None,
                "nombre": armado.tecnico.name if armado.tecnico else None,
                "rol": armado.tecnico.rol if armado.tecnico else None
            },
            "estado": armado.estado,
            "fecha_asignacion": armado.fecha_asignacion,
            "fecha_inicio": fecha_inicio_real,
            "fecha_cierre": armado.fecha_cierre,
            "observacion": armado.observacion,
            "total_cajas": total_cajas,
            "tecnicos_historial": historial_tecnicos
        })
    return jsonify(resultado), 200


@armados_blueprint.route('/', methods=['POST'])
def crear_armado():
    data = request.json or {}
    centro_id = data.get('centro_id')
    tecnico_id = data.get('tecnico_id')

    if not centro_id or not tecnico_id:
        return jsonify({"message": "centro_id y tecnico_id son requeridos"}), 400

    nuevo = Armado(
        centro_id=centro_id,
        tecnico_id=tecnico_id,
        estado=data.get('estado', 'pendiente'),
        fecha_asignacion=parse_date(data.get('fecha_asignacion')) or datetime.utcnow().date(),
        fecha_inicio=parse_date(data.get('fecha_inicio')),
        fecha_cierre=parse_date(data.get('fecha_cierre')),
        observacion=data.get('observacion'),
        creado_por=data.get('creado_por')
    )
    db.session.add(nuevo)
    # Crear participación inicial
    participacion = ArmadoParticipacion(
        armado=nuevo,
        tecnico_id=tecnico_id,
        fecha_inicio=nuevo.fecha_asignacion,
        nota=data.get('observacion')
    )
    db.session.add(participacion)
    db.session.commit()
    return jsonify({"message": "Armado creado", "id_armado": nuevo.id_armado}), 201


@armados_blueprint.route('/<int:id_armado>', methods=['PUT'])
def actualizar_armado(id_armado):
    data = request.json or {}
    armado = Armado.query.get_or_404(id_armado)

    armado.centro_id = data.get('centro_id', armado.centro_id)
    armado.tecnico_id = data.get('tecnico_id', armado.tecnico_id)
    armado.estado = data.get('estado', armado.estado)
    armado.fecha_asignacion = parse_date(data.get('fecha_asignacion')) or armado.fecha_asignacion
    armado.fecha_inicio = parse_date(data.get('fecha_inicio'))
    armado.fecha_cierre = parse_date(data.get('fecha_cierre'))
    armado.observacion = data.get('observacion', armado.observacion)

    db.session.commit()
    return jsonify({"message": "Armado actualizado"}), 200


@armados_blueprint.route('/<int:id_armado>', methods=['DELETE'])
def eliminar_armado(id_armado):
    armado = Armado.query.get_or_404(id_armado)
    db.session.delete(armado)
    db.session.commit()
    return jsonify({"message": "Armado eliminado"}), 200


@armados_blueprint.route('/<int:id_armado>/materiales', methods=['GET'])
def listar_materiales(id_armado):
    materiales = ArmadoMaterial.query.filter_by(armado_id=id_armado).order_by(ArmadoMaterial.id_material.asc()).all()
    data = [{"id_material": m.id_material, "nombre": m.nombre, "cantidad": float(m.cantidad or 0), "caja": m.caja,
             "caja_tecnico_id": m.caja_tecnico_id,
             "caja_tecnico_nombre": m.caja_tecnico.name if m.caja_tecnico else None} for m in materiales]
    return jsonify(data), 200


@armados_blueprint.route('/<int:id_armado>/materiales', methods=['PUT'])
def guardar_materiales(id_armado):
    payload = request.json or []
    if not isinstance(payload, list):
        return jsonify({"message": "Se espera una lista de materiales"}), 400

    Armado.query.get_or_404(id_armado)
    # limpiar materiales existentes y reemplazar
    ArmadoMaterial.query.filter_by(armado_id=id_armado).delete()
    nuevos = []
    for item in payload:
        nombre = item.get("nombre")
        if not nombre:
            continue
        cantidad = item.get("cantidad") or 0
        caja = item.get("caja") or 'Caja 1'
        caja_tecnico_id = item.get("caja_tecnico_id")
        nuevos.append(ArmadoMaterial(armado_id=id_armado, nombre=nombre, cantidad=cantidad, caja=caja, caja_tecnico_id=caja_tecnico_id))
        db.session.add(ArmadoCajaMovimiento(
            armado_id=id_armado,
            tipo="material",
            item_id=0,
            nombre_item=nombre,
            caja=caja,
            cantidad=cantidad,
            tecnico_id=caja_tecnico_id
        ))
    if nuevos:
        db.session.add_all(nuevos)
    db.session.commit()
    # actualizar item_id en movimientos de material recién creados
    materiales_guardados = ArmadoMaterial.query.filter_by(armado_id=id_armado).all()
    nombre_a_id = {m.nombre: m.id_material for m in materiales_guardados}
    movimientos = ArmadoCajaMovimiento.query.filter_by(armado_id=id_armado, tipo="material", item_id=0).all()
    for mov in movimientos:
        mov.item_id = nombre_a_id.get(mov.nombre_item, 0)
    db.session.commit()
    return jsonify({"message": "Materiales actualizados", "count": len(nuevos)}), 200


@armados_blueprint.route('/<int:id_armado>/movimientos', methods=['GET'])
def listar_movimientos(id_armado):
    movs = ArmadoCajaMovimiento.query.filter_by(armado_id=id_armado).order_by(ArmadoCajaMovimiento.fecha.desc()).all()
    data = []
    for m in movs:
        data.append({
            "id_movimiento": m.id_movimiento,
            "tipo": m.tipo,
            "item_id": m.item_id,
            "nombre_item": m.nombre_item,
            "caja": m.caja,
            "cantidad": float(m.cantidad or 0),
            "tecnico_id": m.tecnico_id,
            "tecnico_nombre": m.tecnico.name if m.tecnico else None,
            "fecha": m.fecha.isoformat()
        })
    return jsonify(data), 200


@armados_blueprint.route('/movimientos', methods=['GET'])
def listar_movimientos_recientes():
    """Historial global de movimientos (equipos y materiales) más recientes."""
    try:
        limite = int(request.args.get('limit', 20))
    except ValueError:
        limite = 20
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except ValueError:
        page = 1

    base_query = ArmadoCajaMovimiento.query.filter(ArmadoCajaMovimiento.cantidad != 0)  # solo cambios reales
    total = base_query.count()
    movs = (
        base_query
        .order_by(ArmadoCajaMovimiento.fecha.desc())
        .offset((page - 1) * limite)
        .limit(limite)
        .all()
    )
    data = []
    # Consulta opcional de centros para contexto
    armados_cache = {}
    for m in movs:
        armado = armados_cache.get(m.armado_id)
        if armado is None:
            armado = Armado.query.get(m.armado_id)
            armados_cache[m.armado_id] = armado
        data.append({
            "id_movimiento": m.id_movimiento,
            "armado_id": m.armado_id,
            "tipo": m.tipo,
            "item_id": m.item_id,
            "nombre_item": m.nombre_item,
            "caja": m.caja,
            "cantidad": float(m.cantidad or 0),
            "tecnico_id": m.tecnico_id,
            "tecnico_nombre": m.tecnico.name if m.tecnico else None,
            "fecha": m.fecha.isoformat(),
            "centro_nombre": armado.centro.nombre if armado and armado.centro else None
        })
    return jsonify({"items": data, "total": total, "page": page, "limit": limite}), 200


@armados_blueprint.route('/<int:id_armado>/participaciones', methods=['GET'])
def listar_participaciones(id_armado):
    participaciones = ArmadoParticipacion.query.filter_by(armado_id=id_armado).order_by(
        ArmadoParticipacion.fecha_inicio.asc(), ArmadoParticipacion.id_participacion.asc()
    ).all()
    resultado = []
    for p in participaciones:
        resultado.append({
            "id_participacion": p.id_participacion,
            "armado_id": p.armado_id,
            "tecnico_id": p.tecnico_id,
            "tecnico_nombre": p.tecnico.name if p.tecnico else None,
            "fecha_inicio": p.fecha_inicio,
            "fecha_fin": p.fecha_fin,
            "nota": p.nota
        })
    return jsonify(resultado), 200


@armados_blueprint.route('/<int:id_armado>/participaciones', methods=['POST'])
def crear_participacion(id_armado):
    data = request.json or {}
    tecnico_id = data.get('tecnico_id')
    nota = data.get('nota')
    if not tecnico_id:
        return jsonify({"message": "tecnico_id es requerido"}), 400

    armado = Armado.query.get_or_404(id_armado)

    # Cerrar participación vigente
    vigente = ArmadoParticipacion.query.filter_by(armado_id=id_armado, fecha_fin=None).first()
    hoy = datetime.utcnow().date()
    if vigente:
        vigente.fecha_fin = hoy

    # Nueva participación
    nueva = ArmadoParticipacion(
        armado_id=id_armado,
        tecnico_id=tecnico_id,
        fecha_inicio=hoy,
        nota=nota
    )
    armado.tecnico_id = tecnico_id  # actualizar técnico activo
    db.session.add(nueva)
    db.session.commit()

    return jsonify({"message": "Participación creada", "id_participacion": nueva.id_participacion}), 201


@armados_blueprint.route('/participaciones/<int:id_participacion>', methods=['PUT'])
def actualizar_participacion(id_participacion):
    data = request.json or {}
    participacion = ArmadoParticipacion.query.get_or_404(id_participacion)
    participacion.fecha_inicio = parse_date(data.get('fecha_inicio')) or participacion.fecha_inicio
    participacion.fecha_fin = parse_date(data.get('fecha_fin'))
    participacion.nota = data.get('nota', participacion.nota)
    db.session.commit()
    return jsonify({"message": "Participación actualizada"}), 200


@armados_blueprint.route('/participaciones/<int:id_participacion>', methods=['DELETE'])
def eliminar_participacion(id_participacion):
    participacion = ArmadoParticipacion.query.get_or_404(id_participacion)
    armado = participacion.armado

    db.session.delete(participacion)

    # Si el técnico activo coincide y hay otro historial, usar el más reciente; si no, dejar null
    if armado and armado.tecnico_id == participacion.tecnico_id:
        ultimo = (
            ArmadoParticipacion.query.filter(
                ArmadoParticipacion.armado_id == armado.id_armado,
                ArmadoParticipacion.id_participacion != participacion.id_participacion
            )
            .order_by(ArmadoParticipacion.fecha_inicio.desc(), ArmadoParticipacion.id_participacion.desc())
            .first()
        )
        armado.tecnico_id = ultimo.tecnico_id if ultimo else None

    db.session.commit()
    return jsonify({"message": "Participación eliminada"}), 200
