from flask import Blueprint, request, jsonify, current_app
from ..models import ActaEntrega, Armado, ArmadoParticipacion, ArmadoMaterial, ArmadoGuiaSalida, Centro, Cliente, User, EquiposIP, RetiroTerreno, RetiroTerrenoEquipo
from ..models import ArmadoCajaMovimiento
from ..database import db
from ..socketio_ext import emit_armado_event
from datetime import datetime
from collections import defaultdict
import unicodedata
import jwt
import re
import json
from sqlalchemy import and_, or_, func
from sqlalchemy.orm import joinedload

armados_blueprint = Blueprint('armados', __name__)
SECRET_KEY = "remoto753524"
EQUIPOS_MIGRADOS_A_MATERIALES = {"bandeja rack - tornillos"}
SINONIMOS_EQUIPOS = {
    "ip pc": "pc",
    "ip pc nvr": "pc",
    "puerta de enlace": "router",
    "router (puerta de enlace)": "router",
    "mastil": "mastil",
    "switch cisco + adaptador": "switch (cisco)",
    "switch cisco": "switch (cisco)",
}
EQUIPOS_PREDEF = [
    "PC",
    "Router",
    "Switch",
    "Switch (Cisco)",
    "Switch raqueable",
    "Switch POE",
    "Mass",
    "Netio",
    "Monitor",
    "Rack 9U - tuercas - tornillos",
    "Zapatilla Rack (PDU)",
    "PC cliente",
    "Rack 2",
    "Ubiquiti TX",
    "Ubiquiti RX",
    "Pantalla",
    "Parlantes",
    "Sensor Magnetico",
    "Mouse",
    "Teclado",
    "Tablero 1200x800x300",
    "Tablero 1000x600x300",
    "Tablero 750x500x250",
    "Inversor cargador Victron",
    "Panel Victron",
    "Bateria 1",
    "Bateria 2",
    "Bateria 3",
    "Bateria 4",
    "Bateria 5",
    "Bateria 6",
    "Sensor magnetico respaldo",
    "Sensor magnetico cargador",
    "Cargador 1",
    "Cargador 2",
    "Tablero Cargador 750x500x250",
    "Tablero 500x400x200",
    "Baliza Interior",
    "Bocina Interior",
    "Baliza Exterior 1",
    "Baliza Exterior 2",
    "Bocina Exterior 1",
    "Bocina Exterior 2",
    "Foco led 1 150W",
    "Foco led 2 150W",
    "Foco led 1 50W",
    "Foco led 2 50W",
    "Fuente poder 12V",
    "Axis P8221",
    "Tablero Derivacion (400x300x200)",
    "Radar 1",
    "Radar 2",
    "Cable rj radar 1",
    "Cable rj radar 2",
    "Soporte radar 1",
    "Soporte radar 2",
    "Camara PTZ Laser",
    "Camara PTZ Laser 2",
    "Camara Modulo",
    "Camara Silo 1",
    "Camara Silo 2",
    "Camara Ensinerador",
    "Ensilaje interior",
    "Ensilaje exterior",
    "Camara Popa",
    "Camara acceso 1",
    "Camara acceso 2",
    "Camara acceso 3",
    "Camara acceso 4",
    "Enlace Ubiquiti",
    "UPS online",
    "Tablero Camara (500x700x250)",
    "Poe Power 1",
    "Poe Power 2",
    "Poe Power 3",
    "Poe Power 4",
    "Poe Power 5",
    "Switch POE 1",
    "Camara Interior",
    "Switch 1",
    "Switch 2",
    "Switch 3",
    "Switch POE 2",
    "Switch 4",
]


def normalizar_texto(valor):
    texto = (valor or "").strip().lower()
    if not texto:
        return ""
    texto = unicodedata.normalize("NFD", texto)
    return "".join(ch for ch in texto if unicodedata.category(ch) != "Mn")


def normalizar_nombre_material(nombre):
    return normalizar_texto(nombre).replace("mesa rack", "mesa respaldo")


def canonizar_nombre_material(nombre):
    texto = (nombre or "").strip()
    if not texto:
        return ""
    return "Mesa respaldo" if normalizar_nombre_material(texto) == "mesa respaldo" else texto


def normalizar_modalidad_salida(valor):
    texto = normalizar_texto(valor).replace(" ", "_")
    if "mano" in texto:
        return "por_mano"
    return "transportista_externo"


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def derivar_codigo_desde_serie(serie):
    raw = (serie or "").strip()
    if not raw:
        return None
    solo_numeros = re.sub(r"\D+", "", raw)
    return (solo_numeros[:5] if solo_numeros else raw[:5]) or None


def parse_cajas_estado(raw):
    if raw is None:
        return {}
    data = raw
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except Exception:
            return {}
    if not isinstance(data, dict):
        return {}
    resultado = {}
    for key, value in data.items():
        nombre = str(key or "").strip()
        if not nombre:
            continue
        estado = str(value or "").strip().lower()
        resultado[nombre] = "cerrada" if estado == "cerrada" else "abierta"
    return resultado


def nombre_caja_seguro(value):
    nombre = str(value or "").strip()
    return nombre or "Pendiente de caja"


def clave_caja(value):
    nombre = nombre_caja_seguro(value)
    normalizado = normalizar_texto(nombre)
    match = re.match(r"^caja\s*(\d+)", normalizado)
    if match:
        return f"caja_{int(match.group(1))}"
    return normalizado


def normalizar_lista_cajas(valores):
    resultado = []
    vistos = {}
    for value in (valores or []):
        nombre = nombre_caja_seguro(value)
        clave = clave_caja(nombre)
        if not clave:
            continue
        anterior = vistos.get(clave)
        if anterior is None:
            vistos[clave] = nombre
            resultado.append(nombre)
            continue
        preferido = nombre if len(nombre) > len(anterior) else anterior
        if preferido != anterior:
            idx = resultado.index(anterior)
            resultado[idx] = preferido
            vistos[clave] = preferido
    return resultado


def es_caja_real(value):
    return clave_caja(value) != clave_caja("Pendiente de caja")


def contar_cajas_reales(valores):
    unicas = {clave_caja(value) for value in (valores or []) if clave_caja(value)}
    return len([clave for clave in unicas if clave != clave_caja("Pendiente de caja")])


def normalizar_estado_registro_equipo(value):
    estado = str(value or "").strip().lower()
    if estado == "no_aplica":
        return "no_aplica"
    if estado == "pendiente":
        return "pendiente"
    return "normal"


def normalizar_estado_registro_material(value):
    return normalizar_estado_registro_equipo(value)


def normalizar_nombre_equipo(nombre):
    valor = normalizar_texto(nombre)
    return SINONIMOS_EQUIPOS.get(valor, valor)


def equipo_migrado_a_material(nombre):
    return normalizar_nombre_equipo(nombre) in EQUIPOS_MIGRADOS_A_MATERIALES


def construir_resumen_armado_equipos_desde_lista(equipos):
    equipos = [e for e in (equipos or []) if not equipo_migrado_a_material(e.nombre)]
    mapa = {normalizar_nombre_equipo(e.nombre): e for e in equipos}
    predef_norm = {normalizar_nombre_equipo(nombre) for nombre in EQUIPOS_PREDEF}

    base = []
    for nombre in EQUIPOS_PREDEF:
        found = mapa.get(normalizar_nombre_equipo(nombre))
        base.append(found)

    extras = [e for e in equipos if normalizar_nombre_equipo(e.nombre) not in predef_norm]
    resumen = [e for e in [*base, *extras] if e is not None]
    total = len(EQUIPOS_PREDEF) + len(extras)
    con_serie = len([e for e in resumen if str(e.numero_serie or "").strip()])
    no_aplica = len([e for e in resumen if normalizar_estado_registro_equipo(e.estado_registro) == "no_aplica"])
    pendientes = len([e for e in resumen if normalizar_estado_registro_equipo(e.estado_registro) == "pendiente"])
    resueltos = con_serie + no_aplica
    porcentaje = round((resueltos / total) * 100) if total else 0
    return {
        "total": total,
        "con_serie": con_serie,
        "no_aplica": no_aplica,
        "pendientes": pendientes,
        "resueltos": resueltos,
        "porcentaje": porcentaje,
    }


def calcular_resumen_armado_equipos(centro_id):
    equipos = EquiposIP.query.filter_by(centro_id=centro_id).all()
    return construir_resumen_armado_equipos_desde_lista(equipos)


def construir_detalle_pendientes_armado_desde_lista(equipos):
    equipos = [
        e for e in (equipos or [])
        if not equipo_migrado_a_material(e.nombre)
        and normalizar_estado_registro_equipo(e.estado_registro) == "pendiente"
    ]
    items = [
        {
            "tipo": "equipo",
            "nombre": str(e.nombre or "").strip() or "Equipo",
            "observacion": str(e.observacion_registro or "").strip()
        }
        for e in equipos
    ]
    nombres = [item["nombre"] for item in items if item.get("nombre")]
    if not nombres:
        resumen = ""
    elif len(nombres) <= 2:
        resumen = ", ".join(nombres)
    else:
        resumen = f"{', '.join(nombres[:2])} y {len(nombres) - 2} mas"
    return {
        "items": items,
        "resumen": resumen,
    }


def calcular_detalle_pendientes_armado(centro_id):
    equipos = EquiposIP.query.filter_by(centro_id=centro_id).all()
    return construir_detalle_pendientes_armado_desde_lista(equipos)


def emitir_actualizacion_armado(armado_id, tipo="armado"):
    emit_armado_event(
        "armado_updated",
        {"armado_id": armado_id, "tipo": tipo, "ts": datetime.utcnow().isoformat()},
    )


def serializar_guia_salida(guia):
    if not guia:
        return None
    try:
        cajas = json.loads(guia.cajas_json) if guia.cajas_json else []
    except Exception:
        cajas = []
    if not isinstance(cajas, list):
        cajas = []
    cajas = normalizar_lista_cajas(cajas)
    return {
        "id_guia_salida": guia.id_guia_salida,
        "armado_id": guia.armado_id,
        "numero_guia": guia.numero_guia,
        "fecha_salida": guia.fecha_salida.isoformat() if guia.fecha_salida else None,
        "fecha_recepcion_centro": guia.fecha_recepcion_centro.isoformat() if guia.fecha_recepcion_centro else None,
        "observacion": guia.observacion,
        "tipo_despacho": guia.tipo_despacho,
        "modalidad_salida": guia.modalidad_salida,
        "cajas": cajas,
        "total_cajas_despacho": contar_cajas_reales(cajas),
        "estado": guia.estado,
        "created_at": guia.created_at.isoformat() if guia.created_at else None,
        "updated_at": guia.updated_at.isoformat() if guia.updated_at else None,
    }


def usuario_actual_desde_token():
    token = request.headers.get('Authorization') or ''
    if not token.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(token.split("Bearer ")[1], SECRET_KEY, algorithms=['HS256'])
        user_id = payload.get('user_id') or payload.get('id') or payload.get('sub')
        try:
            user_id = int(user_id)
        except Exception:
            return None
        return User.query.get(user_id)
    except Exception:
        return None


def _participaciones_activas_armado(armado_id):
    return (
        ArmadoParticipacion.query.filter_by(armado_id=armado_id, fecha_fin=None)
        .order_by(ArmadoParticipacion.fecha_inicio.asc(), ArmadoParticipacion.id_participacion.asc())
        .all()
    )


def _serializar_tecnicos_activos(armado):
    activos = _participaciones_activas_armado(armado.id_armado)
    vistos = set()
    resultado = []
    for part in activos:
        tecnico = part.tecnico
        tecnico_id = int(part.tecnico_id or 0)
        if tecnico_id <= 0 or tecnico_id in vistos:
            continue
        vistos.add(tecnico_id)
        resultado.append({
            "id": tecnico.id if tecnico else tecnico_id,
            "nombre": tecnico.name if tecnico else f"ID {tecnico_id}",
            "rol": tecnico.rol if tecnico else None,
            "principal": tecnico_id == int(armado.tecnico_id or 0)
        })

    if not resultado and armado.tecnico_id:
        resultado.append({
            "id": armado.tecnico.id if armado.tecnico else armado.tecnico_id,
            "nombre": armado.tecnico.name if armado.tecnico else f"ID {armado.tecnico_id}",
            "rol": armado.tecnico.rol if armado.tecnico else None,
            "principal": True
        })
    return resultado


@armados_blueprint.route('/', methods=['GET'])
def listar_armados():
    estado = request.args.get('estado')
    tecnico_id = request.args.get('tecnico_id', type=int)
    centro_id = request.args.get('centro_id', type=int)

    query = Armado.query.options(
        joinedload(Armado.centro).joinedload(Centro.cliente),
        joinedload(Armado.tecnico),
    )
    if estado:
        query = query.filter(Armado.estado == estado)
    if tecnico_id:
        armados_activos_subq = (
            db.session.query(ArmadoParticipacion.armado_id)
            .filter(
                ArmadoParticipacion.tecnico_id == tecnico_id,
                ArmadoParticipacion.fecha_fin.is_(None)
            )
            .subquery()
        )
        query = query.filter(
            or_(
                Armado.tecnico_id == tecnico_id,
                Armado.id_armado.in_(armados_activos_subq)
            )
        )
    if centro_id:
        query = query.filter(Armado.centro_id == centro_id)

    armados = query.order_by(Armado.fecha_asignacion.desc()).distinct().all()
    if not armados:
        return jsonify([]), 200

    armado_ids = [int(a.id_armado) for a in armados]
    centro_ids = sorted({int(a.centro_id) for a in armados if a.centro_id})

    participaciones = (
        ArmadoParticipacion.query.options(joinedload(ArmadoParticipacion.tecnico))
        .filter(ArmadoParticipacion.armado_id.in_(armado_ids))
        .order_by(
            ArmadoParticipacion.armado_id.asc(),
            ArmadoParticipacion.fecha_inicio.asc(),
            ArmadoParticipacion.id_participacion.asc(),
        )
        .all()
    )
    participaciones_por_armado = defaultdict(list)
    tecnicos_activos_por_armado = defaultdict(list)
    for part in participaciones:
        arm_id = int(part.armado_id or 0)
        if not arm_id:
            continue
        participaciones_por_armado[arm_id].append(part)
        if part.fecha_fin is None:
            tecnicos_activos_por_armado[arm_id].append(part)

    equipos = EquiposIP.query.filter(EquiposIP.centro_id.in_(centro_ids)).all() if centro_ids else []
    equipos_por_centro = defaultdict(list)
    for equipo in equipos:
        centro_key = int(equipo.centro_id or 0)
        if centro_key:
            equipos_por_centro[centro_key].append(equipo)

    materiales = (
        ArmadoMaterial.query.filter(ArmadoMaterial.armado_id.in_(armado_ids)).all()
        if armado_ids else []
    )
    materiales_por_armado = defaultdict(list)
    for material in materiales:
        armado_key = int(material.armado_id or 0)
        if armado_key:
            materiales_por_armado[armado_key].append(material)

    primeras_fechas_mov = dict(
        db.session.query(
            ArmadoCajaMovimiento.armado_id,
            func.min(ArmadoCajaMovimiento.fecha),
        )
        .filter(ArmadoCajaMovimiento.armado_id.in_(armado_ids))
        .group_by(ArmadoCajaMovimiento.armado_id)
        .all()
    )

    resultado = []
    for armado in armados:
        armado_id = int(armado.id_armado or 0)
        centro_id_actual = int(armado.centro_id or 0)
        participaciones_armado = participaciones_por_armado.get(armado_id, [])
        historial_tecnicos = [
            p.tecnico.name if p.tecnico else f"ID {p.tecnico_id}"
            for p in participaciones_armado
        ]

        vistos = set()
        tecnicos_activos = []
        for part in tecnicos_activos_por_armado.get(armado_id, []):
            tecnico = part.tecnico
            tecnico_id_actual = int(part.tecnico_id or 0)
            if tecnico_id_actual <= 0 or tecnico_id_actual in vistos:
                continue
            vistos.add(tecnico_id_actual)
            tecnicos_activos.append({
                "id": tecnico.id if tecnico else tecnico_id_actual,
                "nombre": tecnico.name if tecnico else f"ID {tecnico_id_actual}",
                "rol": tecnico.rol if tecnico else None,
                "principal": tecnico_id_actual == int(armado.tecnico_id or 0),
            })
        if not tecnicos_activos and armado.tecnico_id:
            tecnicos_activos.append({
                "id": armado.tecnico.id if armado.tecnico else armado.tecnico_id,
                "nombre": armado.tecnico.name if armado.tecnico else f"ID {armado.tecnico_id}",
                "rol": armado.tecnico.rol if armado.tecnico else None,
                "principal": True,
            })

        equipos_centro = equipos_por_centro.get(centro_id_actual, [])
        resumen_armado = construir_resumen_armado_equipos_desde_lista(equipos_centro)
        detalle_pendientes = construir_detalle_pendientes_armado_desde_lista(equipos_centro)

        cajas_equipos = [e.caja for e in equipos_centro]
        cajas_materiales = [m.caja for m in materiales_por_armado.get(armado_id, [])]
        cajas_estado_map = parse_cajas_estado(armado.cajas_estado_json)
        cajas_estado = list(cajas_estado_map.keys())
        if cajas_estado:
            total_cajas_calc = contar_cajas_reales(cajas_estado) or 0
        else:
            total_cajas_calc = contar_cajas_reales([*cajas_equipos, *cajas_materiales]) or 0
        total_cajas = total_cajas_calc if total_cajas_calc > 0 else int(armado.total_cajas_manual or 0)

        primera_mov_fecha = primeras_fechas_mov.get(armado_id)
        fecha_inicio_real = (
            armado.fecha_inicio
            or (primera_mov_fecha.date() if primera_mov_fecha else None)
            or armado.fecha_asignacion
        )

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
            "check_tecnico_fecha": armado.check_tecnico_fecha,
            "observacion": armado.observacion,
            "total_cajas": total_cajas,
            "armado_total_equipos": resumen_armado["total"],
            "armado_equipos_con_serie": resumen_armado["con_serie"],
            "armado_equipos_no_aplica": resumen_armado["no_aplica"],
            "armado_equipos_pendientes": resumen_armado["pendientes"],
            "armado_equipos_resueltos": resumen_armado["resueltos"],
            "porcentaje_armado": resumen_armado["porcentaje"],
            "armado_pendientes_resumen": detalle_pendientes["resumen"],
            "armado_pendientes_detalle": detalle_pendientes["items"],
                "cajas_estado": cajas_estado_map,
                "tecnicos_historial": historial_tecnicos,
                "tecnicos_asignados": tecnicos_activos
            })
    return jsonify(resultado), 200


@armados_blueprint.route('/', methods=['POST'])
def crear_armado():
    data = request.json or {}
    centro_id = data.get('centro_id')
    tecnico_id = data.get('tecnico_id')
    tecnico_secundario_id = data.get('tecnico_secundario_id')
    tecnicos_ids_raw = data.get('tecnicos_ids') if isinstance(data.get('tecnicos_ids'), list) else None

    if not centro_id or not tecnico_id:
        return jsonify({"message": "centro_id y tecnico_id son requeridos"}), 400

    tecnicos_ids = []
    if tecnicos_ids_raw:
        for item in tecnicos_ids_raw:
            try:
                tid = int(item or 0)
            except Exception:
                tid = 0
            if tid > 0 and tid not in tecnicos_ids:
                tecnicos_ids.append(tid)
    else:
        try:
            titular = int(tecnico_id or 0)
        except Exception:
            titular = 0
        try:
            secundario = int(tecnico_secundario_id or 0)
        except Exception:
            secundario = 0
        if titular > 0:
            tecnicos_ids.append(titular)
        if secundario > 0 and secundario not in tecnicos_ids:
            tecnicos_ids.append(secundario)

    if not tecnicos_ids:
        return jsonify({"message": "Debes indicar al menos un tecnico valido"}), 400

    nuevo = Armado(
        centro_id=centro_id,
        tecnico_id=tecnicos_ids[0],
        estado=data.get('estado', 'pendiente'),
        fecha_asignacion=parse_date(data.get('fecha_asignacion')) or datetime.utcnow().date(),
        fecha_inicio=parse_date(data.get('fecha_inicio')),
        fecha_cierre=parse_date(data.get('fecha_cierre')),
        observacion=data.get('observacion'),
        total_cajas_manual=data.get('total_cajas_manual'),
        creado_por=data.get('creado_por')
    )
    db.session.add(nuevo)
    for tecnico_asignado_id in tecnicos_ids:
        participacion = ArmadoParticipacion(
            armado=nuevo,
            tecnico_id=tecnico_asignado_id,
            fecha_inicio=nuevo.fecha_asignacion,
            nota=data.get('observacion')
        )
        db.session.add(participacion)
    db.session.commit()
    emitir_actualizacion_armado(nuevo.id_armado, "armado")
    return jsonify({"message": "Armado creado", "id_armado": nuevo.id_armado}), 201


@armados_blueprint.route('/guias-salida', methods=['GET'])
def listar_guias_salida_armado():
    armados_ids = request.args.getlist('armado_id', type=int)
    query = ArmadoGuiaSalida.query
    if armados_ids:
        query = query.filter(ArmadoGuiaSalida.armado_id.in_(armados_ids))
    guias = query.order_by(ArmadoGuiaSalida.updated_at.desc(), ArmadoGuiaSalida.id_guia_salida.desc()).all()
    return jsonify([serializar_guia_salida(g) for g in guias]), 200


@armados_blueprint.route('/guias-salida', methods=['POST'])
def crear_guia_salida_armado():
    try:
        data = request.json or {}
        armado_id = data.get('armado_id')
        try:
            armado_id = int(armado_id or 0)
        except Exception:
            armado_id = 0
        if not armado_id:
            return jsonify({"message": "armado_id es requerido"}), 400
        armado = Armado.query.get_or_404(armado_id)
        cajas = data.get('cajas') if isinstance(data.get('cajas'), list) else []
        cajas = normalizar_lista_cajas(cajas)
        if not cajas:
            return jsonify({"message": "Debes seleccionar al menos una caja"}), 400

        existentes = ArmadoGuiaSalida.query.filter_by(armado_id=armado_id).order_by(ArmadoGuiaSalida.id_guia_salida.asc()).all()
        usadas = set()
        for guia in existentes:
            try:
                cajas_existentes = json.loads(guia.cajas_json) if guia.cajas_json else []
            except Exception:
                cajas_existentes = []
            usadas.update(clave_caja(c) for c in cajas_existentes if clave_caja(c))
        repetidas = sorted({c for c in cajas if clave_caja(c) in usadas})
        if repetidas:
            return jsonify({"message": f"Las cajas ya fueron despachadas: {', '.join(repetidas)}"}), 409

        numero_guia = str(data.get('numero_guia') or '').strip() or f"GS-{str(armado_id).zfill(4)}-{len(existentes) + 1}"
        fecha_salida = parse_date(data.get('fecha_salida')) or datetime.utcnow().date()
        observacion = data.get('observacion')
        estado = str(data.get('estado') or 'en_transito_centro').strip() or 'en_transito_centro'
        tipo_despacho = str(data.get('tipo_despacho') or ('total' if len(cajas) == 1 else 'parcial')).strip().lower() or 'parcial'
        modalidad_salida = normalizar_modalidad_salida(data.get('modalidad_salida') or 'transportista_externo')

        guia = ArmadoGuiaSalida(
            armado_id=armado_id,
            numero_guia=numero_guia,
            fecha_salida=fecha_salida,
            observacion=observacion,
            estado=estado,
            tipo_despacho=tipo_despacho,
            modalidad_salida=modalidad_salida,
            cajas_json=json.dumps(cajas, ensure_ascii=False),
        )
        db.session.add(guia)
        db.session.commit()
        emitir_actualizacion_armado(armado.id_armado, "guia_salida")
        return jsonify(serializar_guia_salida(guia)), 201
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Error al crear guia de salida")
        return jsonify({"message": "Error al crear guia de salida", "detail": str(exc)}), 500


@armados_blueprint.route('/<int:id_armado>/guia-salida', methods=['GET'])
def obtener_guia_salida_armado(id_armado):
    Armado.query.get_or_404(id_armado)
    guia = ArmadoGuiaSalida.query.filter_by(armado_id=id_armado).order_by(ArmadoGuiaSalida.updated_at.desc(), ArmadoGuiaSalida.id_guia_salida.desc()).first()
    if not guia:
        return jsonify({"message": "Guia de salida no encontrada"}), 404
    return jsonify(serializar_guia_salida(guia)), 200


@armados_blueprint.route('/<int:id_armado>/guia-salida', methods=['PUT'])
def guardar_guia_salida_armado(id_armado):
    armado = Armado.query.get_or_404(id_armado)
    data = request.json or {}
    numero_guia = str(data.get('numero_guia') or '').strip() or f"GS-{str(id_armado).zfill(4)}"
    fecha_salida = parse_date(data.get('fecha_salida')) or datetime.utcnow().date()
    observacion = data.get('observacion')
    estado = str(data.get('estado') or 'en_transito_centro').strip() or 'en_transito_centro'
    tipo_despacho = str(data.get('tipo_despacho') or 'total').strip().lower() or 'total'
    modalidad_salida = normalizar_modalidad_salida(data.get('modalidad_salida') or 'transportista_externo')
    cajas = data.get('cajas') if isinstance(data.get('cajas'), list) else []
    cajas = normalizar_lista_cajas(cajas)

    guia = ArmadoGuiaSalida.query.filter_by(armado_id=id_armado).order_by(ArmadoGuiaSalida.updated_at.desc(), ArmadoGuiaSalida.id_guia_salida.desc()).first()
    if not guia:
        guia = ArmadoGuiaSalida(
            armado_id=id_armado,
            numero_guia=numero_guia,
            fecha_salida=fecha_salida,
            observacion=observacion,
            estado=estado,
            tipo_despacho=tipo_despacho,
            modalidad_salida=modalidad_salida,
            cajas_json=json.dumps(cajas, ensure_ascii=False),
        )
        db.session.add(guia)
    else:
        guia.numero_guia = numero_guia
        guia.fecha_salida = fecha_salida
        guia.observacion = observacion
        guia.estado = estado
        guia.tipo_despacho = tipo_despacho
        guia.modalidad_salida = modalidad_salida
        guia.cajas_json = json.dumps(cajas, ensure_ascii=False)
        guia.updated_at = datetime.utcnow()

    db.session.commit()
    emitir_actualizacion_armado(armado.id_armado, "guia_salida")
    return jsonify(serializar_guia_salida(guia)), 200


@armados_blueprint.route('/guias-salida/<int:id_guia_salida>', methods=['PUT'])
def actualizar_guia_salida(id_guia_salida):
    try:
        guia = ArmadoGuiaSalida.query.get_or_404(id_guia_salida)
        data = request.json or {}
        numero_guia = str(data.get('numero_guia') or '').strip() or guia.numero_guia
        fecha_salida = parse_date(data.get('fecha_salida')) or guia.fecha_salida or datetime.utcnow().date()
        observacion = data.get('observacion')
        estado = str(data.get('estado') or guia.estado or 'en_transito_centro').strip() or 'en_transito_centro'
        tipo_despacho = str(data.get('tipo_despacho') or guia.tipo_despacho or 'total').strip().lower() or 'total'
        modalidad_salida = normalizar_modalidad_salida(data.get('modalidad_salida') or guia.modalidad_salida or 'transportista_externo')
        cajas = data.get('cajas') if isinstance(data.get('cajas'), list) else None

        if cajas is not None:
            cajas = normalizar_lista_cajas(cajas)
            if not cajas:
                return jsonify({"message": "Debes seleccionar al menos una caja"}), 400
            otras = ArmadoGuiaSalida.query.filter(
                ArmadoGuiaSalida.armado_id == guia.armado_id,
                ArmadoGuiaSalida.id_guia_salida != guia.id_guia_salida
            ).all()
            usadas = set()
            for item in otras:
                try:
                    cajas_otras = json.loads(item.cajas_json) if item.cajas_json else []
                except Exception:
                    cajas_otras = []
                usadas.update(clave_caja(c) for c in cajas_otras if clave_caja(c))
            repetidas = sorted({c for c in cajas if clave_caja(c) in usadas})
            if repetidas:
                return jsonify({"message": f"Las cajas ya fueron despachadas: {', '.join(repetidas)}"}), 409
            guia.cajas_json = json.dumps(cajas, ensure_ascii=False)

        guia.numero_guia = numero_guia
        guia.fecha_salida = fecha_salida
        guia.observacion = observacion
        guia.estado = estado
        guia.tipo_despacho = tipo_despacho
        guia.modalidad_salida = modalidad_salida
        guia.updated_at = datetime.utcnow()
        db.session.commit()
        emitir_actualizacion_armado(guia.armado_id, "guia_salida")
        return jsonify(serializar_guia_salida(guia)), 200
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Error al actualizar guia de salida")
        return jsonify({"message": "Error al actualizar guia de salida", "detail": str(exc)}), 500


@armados_blueprint.route('/<int:id_armado>/guia-salida/recepcion-centro', methods=['POST'])
def marcar_recepcion_centro_guia(id_armado):
    Armado.query.get_or_404(id_armado)
    guia = ArmadoGuiaSalida.query.filter_by(armado_id=id_armado).order_by(ArmadoGuiaSalida.updated_at.desc(), ArmadoGuiaSalida.id_guia_salida.desc()).first()
    if not guia:
        return jsonify({"message": "Guia de salida no encontrada"}), 404

    data = request.json or {}
    fecha_recepcion = data.get('fecha_recepcion_centro')
    if fecha_recepcion:
        try:
            guia.fecha_recepcion_centro = datetime.fromisoformat(str(fecha_recepcion).replace("Z", "+00:00"))
        except ValueError:
            guia.fecha_recepcion_centro = datetime.utcnow()
    else:
        guia.fecha_recepcion_centro = datetime.utcnow()
    guia.estado = 'recepcionado_en_centro'
    guia.updated_at = datetime.utcnow()
    db.session.commit()
    emitir_actualizacion_armado(id_armado, "guia_salida")
    return jsonify(serializar_guia_salida(guia)), 200


@armados_blueprint.route('/guias-salida/<int:id_guia_salida>/recepcion-centro', methods=['POST'])
def marcar_recepcion_centro_guia_por_id(id_guia_salida):
    guia = ArmadoGuiaSalida.query.get_or_404(id_guia_salida)
    data = request.json or {}
    fecha_recepcion = data.get('fecha_recepcion_centro')
    if fecha_recepcion:
        try:
            guia.fecha_recepcion_centro = datetime.fromisoformat(str(fecha_recepcion).replace("Z", "+00:00"))
        except ValueError:
            guia.fecha_recepcion_centro = datetime.utcnow()
    else:
        guia.fecha_recepcion_centro = datetime.utcnow()
    guia.estado = 'recepcionado_en_centro'
    guia.updated_at = datetime.utcnow()
    db.session.commit()
    emitir_actualizacion_armado(guia.armado_id, "guia_salida")
    return jsonify(serializar_guia_salida(guia)), 200


@armados_blueprint.route('/<int:id_armado>/guia-salida', methods=['DELETE'])
def eliminar_guia_salida_armado(id_armado):
    Armado.query.get_or_404(id_armado)
    guia = ArmadoGuiaSalida.query.filter_by(armado_id=id_armado).order_by(ArmadoGuiaSalida.updated_at.desc(), ArmadoGuiaSalida.id_guia_salida.desc()).first()
    if not guia:
        return jsonify({"message": "Guia de salida no encontrada"}), 404
    db.session.delete(guia)
    db.session.commit()
    emitir_actualizacion_armado(id_armado, "guia_salida")
    return jsonify({"message": "Guia de salida eliminada"}), 200


@armados_blueprint.route('/guias-salida/<int:id_guia_salida>', methods=['DELETE'])
def eliminar_guia_salida_por_id(id_guia_salida):
    guia = ArmadoGuiaSalida.query.get_or_404(id_guia_salida)
    armado_id = guia.armado_id
    db.session.delete(guia)
    db.session.commit()
    emitir_actualizacion_armado(armado_id, "guia_salida")
    return jsonify({"message": "Guia de salida eliminada"}), 200

@armados_blueprint.route('/<int:id_armado>', methods=['PUT'])
def actualizar_armado(id_armado):
    data = request.json or {}
    armado = Armado.query.get_or_404(id_armado)

    armado.centro_id = data.get('centro_id', armado.centro_id)
    armado.tecnico_id = data.get('tecnico_id', armado.tecnico_id)
    armado.estado = data.get('estado', armado.estado)

    # Solo actualizar fechas cuando el campo viene explÃ­citamente en payload.
    # Evita borrar/modificar fechas por requests parciales (ej: solo estado).
    if 'fecha_asignacion' in data:
        parsed = parse_date(data.get('fecha_asignacion'))
        if parsed is not None:
            armado.fecha_asignacion = parsed

    if 'fecha_inicio' in data:
        parsed = parse_date(data.get('fecha_inicio'))
        armado.fecha_inicio = parsed if parsed is not None else armado.fecha_inicio

    if 'fecha_cierre' in data:
        parsed = parse_date(data.get('fecha_cierre'))
        armado.fecha_cierre = parsed if parsed is not None else armado.fecha_cierre
    if 'check_tecnico_fecha' in data:
        parsed = parse_date(data.get('check_tecnico_fecha'))
        armado.check_tecnico_fecha = parsed if parsed is not None else armado.check_tecnico_fecha

    armado.observacion = data.get('observacion', armado.observacion)
    if 'total_cajas_manual' in data:
        try:
            armado.total_cajas_manual = int(data.get('total_cajas_manual') or 0)
        except (TypeError, ValueError):
            armado.total_cajas_manual = armado.total_cajas_manual
    if 'cajas_estado' in data:
        armado.cajas_estado_json = json.dumps(parse_cajas_estado(data.get('cajas_estado')), ensure_ascii=False)

    db.session.commit()
    emitir_actualizacion_armado(armado.id_armado, "armado")
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
    data = [{"id_material": m.id_material, "nombre": canonizar_nombre_material(m.nombre), "cantidad": float(m.cantidad or 0), "caja": m.caja,
             "caja_tecnico_id": m.caja_tecnico_id,
             "caja_tecnico_nombre": m.caja_tecnico.name if m.caja_tecnico else None,
             "estado_registro": m.estado_registro or "normal",
             "observacion_registro": m.observacion_registro} for m in materiales]
    return jsonify(data), 200


@armados_blueprint.route('/<int:id_armado>/materiales', methods=['PUT'])
def guardar_materiales(id_armado):
    payload = request.json or []
    if not isinstance(payload, list):
        return jsonify({"message": "Se espera una lista de materiales"}), 400

    Armado.query.get_or_404(id_armado)
    existentes = ArmadoMaterial.query.filter_by(armado_id=id_armado).all()
    por_nombre = {normalizar_nombre_material(m.nombre): m for m in existentes if normalizar_nombre_material(m.nombre)}
    cambios = 0

    for item in payload:
        nombre = canonizar_nombre_material(item.get("nombre"))
        if not nombre:
            continue

        id_material = item.get("id_material")
        cantidad = float(item.get("cantidad") or 0)
        cantidad_delta = float(item.get("cantidad_delta") or 0)
        caja = item.get("caja") or 'Caja 1'
        caja_tecnico_id = item.get("caja_tecnico_id")
        estado_registro = normalizar_estado_registro_material(item.get("estado_registro"))
        observacion_registro = item.get("observacion_registro")
        accion_material = normalizar_texto(item.get("accion_material") or item.get("accion") or "")
        key = normalizar_nombre_material(nombre)
        actual = None

        # Prioridad: actualizar por ID cuando venga en payload (evita cruces por nombre/acentos).
        if id_material is not None:
            try:
                id_num = int(id_material)
                actual = next((m for m in existentes if m.id_material == id_num), None)
            except (TypeError, ValueError):
                actual = None

        if actual is None:
            actual = por_nombre.get(key)

        if actual:
            cant_actual = float(actual.cantidad or 0)
            caja_actual = actual.caja or 'Caja 1'
            if actual.nombre != nombre:
                actual.nombre = nombre
            if accion_material == "incremento":
                if cantidad_delta == 0:
                    continue
                actual.cantidad = cant_actual + cantidad_delta
                if caja_tecnico_id is not None:
                    actual.caja_tecnico_id = caja_tecnico_id
                actual.estado_registro = estado_registro
                actual.observacion_registro = observacion_registro if estado_registro == "pendiente" else None
                db.session.add(ArmadoCajaMovimiento(
                    armado_id=id_armado,
                    tipo="material",
                    item_id=actual.id_material,
                    nombre_item=actual.nombre,
                    caja=actual.caja or "Caja 1",
                    cantidad=cantidad_delta,
                    accion="incremento",
                    cantidad_anterior=cant_actual,
                    cantidad_nueva=actual.cantidad or 0,
                    tecnico_id=actual.caja_tecnico_id
                ))
                cambios += 1
                continue

            cambio = (
                (cant_actual != cantidad) or
                (caja_actual != caja) or
                (normalizar_estado_registro_material(actual.estado_registro) != estado_registro) or
                ((actual.observacion_registro or None) != (observacion_registro if estado_registro == "pendiente" else None))
            )
            if not cambio:
                continue

            actual.cantidad = cantidad
            actual.caja = caja
            actual.estado_registro = estado_registro
            actual.observacion_registro = observacion_registro if estado_registro == "pendiente" else None
            if caja_tecnico_id is not None:
                actual.caja_tecnico_id = caja_tecnico_id

            db.session.add(ArmadoCajaMovimiento(
                armado_id=id_armado,
                tipo="material",
                item_id=actual.id_material,
                nombre_item=actual.nombre,
                caja=actual.caja or "Caja 1",
                cantidad=actual.cantidad or 0,
                accion="ajuste",
                cantidad_anterior=cant_actual,
                cantidad_nueva=actual.cantidad or 0,
                tecnico_id=actual.caja_tecnico_id
            ))
            cambios += 1
            continue

        nuevo = ArmadoMaterial(
            armado_id=id_armado,
            nombre=nombre,
            cantidad=cantidad,
            caja=caja,
            caja_tecnico_id=caja_tecnico_id,
            estado_registro=estado_registro,
            observacion_registro=observacion_registro if estado_registro == "pendiente" else None
        )
        db.session.add(nuevo)
        db.session.flush()

        db.session.add(ArmadoCajaMovimiento(
            armado_id=id_armado,
            tipo="material",
            item_id=nuevo.id_material,
            nombre_item=nuevo.nombre,
            caja=nuevo.caja or "Caja 1",
            cantidad=nuevo.cantidad or 0,
            accion="creacion",
            cantidad_anterior=0,
            cantidad_nueva=nuevo.cantidad or 0,
            tecnico_id=nuevo.caja_tecnico_id
        ))
        por_nombre[key] = nuevo
        cambios += 1

    db.session.commit()
    if cambios:
        emitir_actualizacion_armado(id_armado, "material")
    return jsonify({"message": "Materiales actualizados", "count": cambios}), 200


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
            "numero_serie": m.numero_serie,
            "caja": m.caja,
            "cantidad": float(m.cantidad or 0),
            "accion": m.accion,
            "cantidad_anterior": float(m.cantidad_anterior or 0) if m.cantidad_anterior is not None else None,
            "cantidad_nueva": float(m.cantidad_nueva or 0) if m.cantidad_nueva is not None else None,
            "tecnico_id": m.tecnico_id,
            "tecnico_nombre": m.tecnico.name if m.tecnico else None,
            "fecha": m.fecha.isoformat()
        })
    return jsonify(data), 200


@armados_blueprint.route('/movimientos', methods=['GET'])
def listar_movimientos_recientes():
    """Historial global de movimientos (equipos y materiales) mÃ¡s recientes."""
    try:
        limite = int(request.args.get('limit', 20))
    except ValueError:
        limite = 20
    try:
        page = max(int(request.args.get('page', 1)), 1)
    except ValueError:
        page = 1

    armado_id = request.args.get('armado_id', type=int)
    centro_id = request.args.get('centro_id', type=int)
    cliente = (request.args.get('cliente') or '').strip()
    numero_serie = (request.args.get('numero_serie') or '').strip()

    base_query = ArmadoCajaMovimiento.query.filter(ArmadoCajaMovimiento.cantidad != 0)  # solo cambios reales
    joined_armado = False
    if armado_id:
        base_query = base_query.filter(ArmadoCajaMovimiento.armado_id == armado_id)
    if centro_id:
        if not joined_armado:
            base_query = base_query.join(Armado, Armado.id_armado == ArmadoCajaMovimiento.armado_id)
            joined_armado = True
        base_query = base_query.filter(Armado.centro_id == centro_id)
    if cliente:
        if not joined_armado:
            base_query = base_query.join(Armado, Armado.id_armado == ArmadoCajaMovimiento.armado_id)
            joined_armado = True
        base_query = (
            base_query
            .join(Centro, Centro.id_centro == Armado.centro_id)
            .join(Cliente, Cliente.id_cliente == Centro.cliente_id)
            .filter(Cliente.nombre.ilike(cliente))
        )
    if numero_serie:
        base_query = base_query.filter(
            ArmadoCajaMovimiento.numero_serie.ilike(f"%{numero_serie}%")
        )
    total = base_query.count()
    movs = (
        base_query
        .options(joinedload(ArmadoCajaMovimiento.tecnico))
        .order_by(
            ArmadoCajaMovimiento.fecha.desc(),
            ArmadoCajaMovimiento.id_movimiento.desc()
        )
        .offset((page - 1) * limite)
        .limit(limite)
        .all()
    )
    data = []
    armados_map = {}
    armado_ids = list({m.armado_id for m in movs if m.armado_id})
    if armado_ids:
        armados_map = {
            a.id_armado: a
            for a in (
                Armado.query
                .options(joinedload(Armado.centro))
                .filter(Armado.id_armado.in_(armado_ids))
                .all()
            )
        }
    for m in movs:
        armado = armados_map.get(m.armado_id)
        data.append({
            "id_movimiento": m.id_movimiento,
            "armado_id": m.armado_id,
            "tipo": m.tipo,
            "item_id": m.item_id,
            "nombre_item": m.nombre_item,
            "numero_serie": m.numero_serie,
            "caja": m.caja,
            "cantidad": float(m.cantidad or 0),
            "accion": m.accion,
            "cantidad_anterior": float(m.cantidad_anterior or 0) if m.cantidad_anterior is not None else None,
            "cantidad_nueva": float(m.cantidad_nueva or 0) if m.cantidad_nueva is not None else None,
            "tecnico_id": m.tecnico_id,
            "tecnico_nombre": m.tecnico.name if m.tecnico else None,
            "fecha": m.fecha.isoformat(),
            "centro_nombre": armado.centro.nombre if armado and armado.centro else None
        })
    return jsonify({"items": data, "total": total, "page": page, "limit": limite}), 200


@armados_blueprint.route('/<int:id_armado>/historial-equipos', methods=['GET'])
def historial_equipos_armado(id_armado):
    armado = Armado.query.get_or_404(id_armado)

    def _clave_equipo_referencia(item):
        try:
            equipo_id = int(item.get("equipo_id")) if item.get("equipo_id") not in (None, "", 0, "0") else None
        except Exception:
            equipo_id = None
        if equipo_id:
            return f"id:{equipo_id}"
        nombre = normalizar_texto(item.get("nombre") or item.get("nombre_item") or "")
        numero_serie = normalizar_texto(item.get("numero_serie") or item.get("serie_actual") or "")
        codigo = normalizar_texto(item.get("codigo") or "")
        return f"raw:{nombre}|{numero_serie}|{codigo}"

    acta_referencia = (
        ActaEntrega.query
        .filter(
            ActaEntrega.armado_id == id_armado,
            ActaEntrega.armado_equipos_json.isnot(None),
        )
        .order_by(ActaEntrega.updated_at.desc(), ActaEntrega.id_acta_entrega.desc())
        .first()
    )
    acta_equipos_referencia = []
    if acta_referencia and acta_referencia.armado_equipos_json:
        try:
            parsed_acta = json.loads(acta_referencia.armado_equipos_json) if isinstance(acta_referencia.armado_equipos_json, str) else acta_referencia.armado_equipos_json
            if isinstance(parsed_acta, list):
                acta_equipos_referencia = [item for item in parsed_acta if isinstance(item, dict)]
        except Exception:
            acta_equipos_referencia = []
    claves_referencia_acta = {
        _clave_equipo_referencia(item)
        for item in acta_equipos_referencia
    } if acta_equipos_referencia else set()

    movimientos = (
        ArmadoCajaMovimiento.query
        .filter(
            ArmadoCajaMovimiento.armado_id == id_armado,
            ArmadoCajaMovimiento.tipo == 'equipo',
            ArmadoCajaMovimiento.cantidad != 0
        )
        .order_by(ArmadoCajaMovimiento.fecha.asc(), ArmadoCajaMovimiento.id_movimiento.asc())
        .all()
    )

    equipos_actuales = {
        int(e.id_equipo): e
        for e in EquiposIP.query.filter_by(centro_id=armado.centro_id).all()
    }

    retiros_equipos = (
        RetiroTerrenoEquipo.query
        .join(RetiroTerreno, RetiroTerreno.id_retiro_terreno == RetiroTerrenoEquipo.retiro_terreno_id)
        .filter(
            RetiroTerreno.centro_id == armado.centro_id,
            RetiroTerrenoEquipo.retirado.is_(True)
        )
        .order_by(
            RetiroTerreno.fecha_retiro.desc(),
            RetiroTerreno.id_retiro_terreno.desc(),
            RetiroTerrenoEquipo.id_retiro_equipo.desc()
        )
        .all()
    )

    retiro_por_item_id = {}
    retiro_por_nombre = {}
    for retiro_eq in retiros_equipos:
        retiro = retiro_eq.retiro
        if not retiro:
            continue
        dato_retiro = {
            "serie_retirada": (retiro_eq.numero_serie or "").strip() or "-",
            "serie_retirada_fecha": retiro.fecha_retiro.isoformat() if retiro.fecha_retiro else None,
            "correlativo_retiro": str(retiro.id_retiro_terreno),
        }
        equipo_id = int(retiro_eq.equipo_id or 0) if retiro_eq.equipo_id else 0
        if equipo_id and equipo_id not in retiro_por_item_id:
            retiro_por_item_id[equipo_id] = dato_retiro
        nombre_key = normalizar_texto(retiro_eq.equipo_nombre or "")
        if nombre_key and nombre_key not in retiro_por_nombre:
            retiro_por_nombre[nombre_key] = dato_retiro

    resumen_map = {}
    ultima_serie_por_item = {}
    eventos = []

    for m in movimientos:
        item_key = int(m.item_id or 0)
        item = resumen_map.get(item_key)
        serie_mov = (m.numero_serie or "").strip()
        fecha_mov = m.fecha.isoformat() if m.fecha else None
        accion_mov = normalizar_texto(m.accion or "")
        es_devuelto_bodega = accion_mov == "devuelto_bodega"
        correlativo_match = re.search(r"reemplazo_mantencion_N(\d+)", str(m.nombre_item or ""), flags=re.IGNORECASE)
        correlativo_mov = correlativo_match.group(1) if correlativo_match else None

        serie_anterior = ultima_serie_por_item.get(item_key, "")

        if item is None:
            equipo_actual = equipos_actuales.get(item_key)
            nombre_base = (
                (equipo_actual.nombre if equipo_actual else None)
                or (m.nombre_item or "")
            )
            retiro_actual = retiro_por_item_id.get(item_key)
            if not retiro_actual:
                retiro_actual = retiro_por_nombre.get(normalizar_texto(nombre_base or ""))
            item = {
                "item_id": item_key,
                "nombre_item": nombre_base,
                "serie_inicial": serie_mov or "-",
                "serie_inicial_fecha": fecha_mov,
                "serie_anterior_actual": "-",
                "serie_anterior_actual_fecha": None,
                "serie_actual": serie_mov or "-",
                "serie_actual_fecha": fecha_mov,
                "correlativo_ultimo": correlativo_mov,
                "serie_retirada": (retiro_actual or {}).get("serie_retirada", "-"),
                "serie_retirada_fecha": (retiro_actual or {}).get("serie_retirada_fecha"),
                "correlativo_retiro": (retiro_actual or {}).get("correlativo_retiro"),
                "devuelto_bodega": False,
                "fecha_devuelto_bodega": None,
                "serie_devuelta_bodega": "-",
                "ultimo_evento": accion_mov or "movimiento",
                "cambios": 0,
                "ultima_actualizacion": m.fecha.isoformat() if m.fecha else None
            }
            resumen_map[item_key] = item
        else:
            item["ultimo_evento"] = accion_mov or item.get("ultimo_evento") or "movimiento"
            item["ultima_actualizacion"] = m.fecha.isoformat() if m.fecha else item["ultima_actualizacion"]

        if es_devuelto_bodega:
            serie_base_devuelta = serie_mov or item.get("serie_actual") or item.get("serie_inicial") or "-"
            serie_actual_anterior = item.get("serie_actual") or "-"
            if serie_actual_anterior not in ("", "-"):
                item["serie_anterior_actual"] = serie_actual_anterior
                item["serie_anterior_actual_fecha"] = item.get("serie_actual_fecha")
            item["devuelto_bodega"] = True
            item["fecha_devuelto_bodega"] = fecha_mov
            item["serie_devuelta_bodega"] = serie_base_devuelta or "-"
            item["serie_actual"] = "-"
            item["serie_actual_fecha"] = fecha_mov
            if serie_mov:
                ultima_serie_por_item[item_key] = serie_mov
        else:
            if item.get("devuelto_bodega"):
                item["devuelto_bodega"] = False
                item["fecha_devuelto_bodega"] = None
                item["serie_devuelta_bodega"] = "-"
            if serie_mov and serie_mov != item["serie_actual"]:
                item["cambios"] += 1
                item["serie_anterior_actual"] = item["serie_actual"] or "-"
                item["serie_anterior_actual_fecha"] = item.get("serie_actual_fecha")
                item["serie_actual"] = serie_mov
                item["serie_actual_fecha"] = fecha_mov
                if correlativo_mov:
                    item["correlativo_ultimo"] = correlativo_mov
            if serie_mov:
                ultima_serie_por_item[item_key] = serie_mov

        eventos.append({
            "id_movimiento": m.id_movimiento,
            "item_id": item_key,
            "nombre_item": m.nombre_item,
            "serie_anterior": serie_anterior or "-",
            "serie_nueva": serie_mov or "-",
            "fecha_serie_anterior": item.get("serie_anterior_actual_fecha") if item else None,
            "fecha_serie_nueva": fecha_mov,
            "correlativo": correlativo_mov,
            "numero_serie": serie_mov or "-",
            "accion": accion_mov or "-",
            "devuelto_bodega": es_devuelto_bodega,
            "tecnico_id": m.tecnico_id,
            "tecnico_nombre": m.tecnico.name if m.tecnico else None,
            "fecha": m.fecha.isoformat() if m.fecha else None
        })

    for item in resumen_map.values():
        item_key = int(item.get("item_id") or 0)
        eq_actual = equipos_actuales.get(item_key)
        serie_eq_actual = (eq_actual.numero_serie or "").strip() if eq_actual else ""
        if item.get("devuelto_bodega"):
            item["serie_actual"] = "-"
            item["serie_actual_fecha"] = item.get("fecha_devuelto_bodega") or item.get("serie_actual_fecha")
        elif serie_eq_actual:
            if (item.get("serie_actual") or "-") in ("", "-"):
                item["serie_actual"] = serie_eq_actual
            if (item.get("serie_inicial") or "-") in ("", "-"):
                item["serie_inicial"] = serie_eq_actual
        retiro_actual = retiro_por_item_id.get(item_key)
        if not retiro_actual:
            retiro_actual = retiro_por_nombre.get(normalizar_texto(item.get("nombre_item") or ""))
        if retiro_actual:
            item["serie_retirada"] = retiro_actual.get("serie_retirada") or "-"
            item["serie_retirada_fecha"] = retiro_actual.get("serie_retirada_fecha")
            item["correlativo_retiro"] = retiro_actual.get("correlativo_retiro")
        else:
            item["serie_retirada"] = item.get("serie_retirada") or "-"
            item["serie_retirada_fecha"] = item.get("serie_retirada_fecha")
            item["correlativo_retiro"] = item.get("correlativo_retiro")

    # Fallback: si no hay movimientos historicos para un equipo, usar estado actual de planilla
    # para que "Detalle tecnico" no quede vacio.
    for equipo_id, eq in equipos_actuales.items():
        if equipo_id in resumen_map:
            continue
        nombre_eq = (eq.nombre or "").strip() or "-"
        serie_eq = (eq.numero_serie or "").strip() or "-"
        retiro_actual = retiro_por_item_id.get(equipo_id) or retiro_por_nombre.get(normalizar_texto(nombre_eq))
        resumen_map[equipo_id] = {
            "item_id": equipo_id,
            "nombre_item": nombre_eq,
            "serie_inicial": serie_eq,
            "serie_inicial_fecha": None,
            "serie_anterior_actual": "-",
            "serie_anterior_actual_fecha": None,
            "serie_actual": serie_eq,
            "serie_actual_fecha": None,
            "correlativo_ultimo": None,
            "serie_retirada": (retiro_actual or {}).get("serie_retirada", "-"),
            "serie_retirada_fecha": (retiro_actual or {}).get("serie_retirada_fecha"),
            "correlativo_retiro": (retiro_actual or {}).get("correlativo_retiro"),
            "devuelto_bodega": False,
            "fecha_devuelto_bodega": None,
            "serie_devuelta_bodega": "-",
            "ultimo_evento": "estado_actual",
            "cambios": 0,
            "ultima_actualizacion": None,
        }

    resumen_lista = list(resumen_map.values())
    if claves_referencia_acta:
        resumen_lista = [
            item for item in resumen_lista
            if (
                f"id:{int(item.get('item_id') or 0)}" in claves_referencia_acta
                or _clave_equipo_referencia({
                    "nombre_item": item.get("nombre_item"),
                    "serie_actual": item.get("serie_actual"),
                    "numero_serie": item.get("serie_actual"),
                    "codigo": "",
                }) in claves_referencia_acta
                or _clave_equipo_referencia({
                    "nombre_item": item.get("nombre_item"),
                    "serie_actual": item.get("serie_inicial"),
                    "numero_serie": item.get("serie_inicial"),
                    "codigo": "",
                }) in claves_referencia_acta
            )
        ]

    resumen = sorted(
        resumen_lista,
        key=lambda x: (-int(x.get("cambios", 0)), str(x.get("nombre_item", "")))
    )

    total_equipos_referencia = len(acta_equipos_referencia) if acta_equipos_referencia else len(resumen)
    equipos_instalados_referencia = (
        len([
            item
            for item in acta_equipos_referencia
            if normalizar_texto(item.get("estado_uso") or "instalado") == "instalado"
        ])
        if acta_equipos_referencia
        else len([
            item
            for item in resumen
            if str(item.get("serie_actual") or "").strip() not in ("", "-") and not item.get("devuelto_bodega")
        ])
    )
    equipos_devueltos_referencia = (
        len([
            item
            for item in acta_equipos_referencia
            if normalizar_texto(item.get("estado_uso") or "") == "devuelto_bodega"
        ])
        if acta_equipos_referencia
        else len([item for item in resumen if item.get("devuelto_bodega")])
    )

    return jsonify({
        "armado": {
            "id_armado": armado.id_armado,
            "centro_id": armado.centro_id,
            "centro_nombre": armado.centro.nombre if armado.centro else None,
            "cliente_nombre": (
                armado.centro.cliente.nombre
                if armado.centro and armado.centro.cliente
                else None
            ),
            "total_equipos_referencia": total_equipos_referencia,
            "equipos_instalados_referencia": equipos_instalados_referencia,
            "equipos_devueltos_referencia": equipos_devueltos_referencia,
        },
        "resumen": resumen,
        "eventos": list(reversed(eventos))
    }), 200


@armados_blueprint.route('/movimientos/<int:id_movimiento>', methods=['DELETE'])
def eliminar_movimiento_global(id_movimiento):
    usuario = usuario_actual_desde_token()
    if not usuario or (usuario.rol or "").lower() != "admin":
        return jsonify({"message": "No autorizado"}), 403

    movimiento = ArmadoCajaMovimiento.query.get(id_movimiento)
    if not movimiento:
        return jsonify({"message": "Movimiento no encontrado"}), 404

    armado_id = movimiento.armado_id
    restauracion = None

    try:
        if movimiento.tipo == "equipo" and movimiento.item_id:
            armado = Armado.query.get(armado_id)
            equipo = EquiposIP.query.get(movimiento.item_id)
            if equipo and armado and int(equipo.centro_id or 0) == int(armado.centro_id or 0):
                base_query = ArmadoCajaMovimiento.query.filter(
                    ArmadoCajaMovimiento.armado_id == armado_id,
                    ArmadoCajaMovimiento.tipo == "equipo",
                    ArmadoCajaMovimiento.item_id == movimiento.item_id,
                    ArmadoCajaMovimiento.cantidad != 0,
                )
                ultimo_mov = base_query.order_by(
                    ArmadoCajaMovimiento.fecha.desc(),
                    ArmadoCajaMovimiento.id_movimiento.desc(),
                ).first()
                # Solo se restaura planilla si se borra el ultimo movimiento del equipo.
                if ultimo_mov and int(ultimo_mov.id_movimiento) == int(movimiento.id_movimiento):
                    mov_anterior = (
                        base_query.filter(
                            ArmadoCajaMovimiento.id_movimiento != movimiento.id_movimiento,
                            or_(
                                ArmadoCajaMovimiento.fecha < movimiento.fecha,
                                and_(
                                    ArmadoCajaMovimiento.fecha == movimiento.fecha,
                                    ArmadoCajaMovimiento.id_movimiento < movimiento.id_movimiento,
                                ),
                            ),
                        )
                        .order_by(
                            ArmadoCajaMovimiento.fecha.desc(),
                            ArmadoCajaMovimiento.id_movimiento.desc(),
                        )
                        .first()
                    )
                    serie_restaurada = (mov_anterior.numero_serie or "").strip() if mov_anterior else None
                    equipo.numero_serie = serie_restaurada or None
                    equipo.codigo = derivar_codigo_desde_serie(serie_restaurada)
                    restauracion = {
                        "equipo_id": equipo.id_equipo,
                        "serie_restaurada": equipo.numero_serie,
                        "codigo_restaurado": equipo.codigo,
                    }
    except Exception:
        # Nunca bloquear eliminacion por un error de restauracion.
        restauracion = None

    db.session.delete(movimiento)
    db.session.commit()
    emitir_actualizacion_armado(armado_id, "movimiento_deleted")
    return jsonify({
        "message": "Movimiento eliminado",
        "id_movimiento": id_movimiento,
        "restauracion": restauracion,
    }), 200


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
    reemplaza_tecnico_id = data.get('reemplaza_tecnico_id')
    nota = data.get('nota')
    if not tecnico_id:
        return jsonify({"message": "tecnico_id es requerido"}), 400

    armado = Armado.query.get_or_404(id_armado)

    try:
        tecnico_id = int(tecnico_id)
    except (TypeError, ValueError):
        return jsonify({"message": "tecnico_id invalido"}), 400

    try:
        reemplaza_tecnico_id = int(reemplaza_tecnico_id) if reemplaza_tecnico_id is not None else None
    except (TypeError, ValueError):
        return jsonify({"message": "reemplaza_tecnico_id invalido"}), 400

    vigentes = ArmadoParticipacion.query.filter_by(armado_id=id_armado, fecha_fin=None).all()
    hoy = datetime.utcnow().date()
    reemplaza_principal = True
    vigentes_ids = {int(v.tecnico_id or 0) for v in vigentes}

    if reemplaza_tecnico_id is not None:
        objetivos = [v for v in vigentes if int(v.tecnico_id or 0) == reemplaza_tecnico_id]
        if not objetivos:
            return jsonify({"message": "No se encontro el tecnico actual a reemplazar"}), 404
        if tecnico_id in vigentes_ids and tecnico_id != reemplaza_tecnico_id:
            return jsonify({"message": "El tecnico seleccionado ya esta asignado al armado"}), 409
        for vigente in objetivos:
            vigente.fecha_fin = hoy
        reemplaza_principal = any(int(v.tecnico_id or 0) == int(armado.tecnico_id or 0) for v in objetivos)
    else:
        for vigente in vigentes:
            vigente.fecha_fin = hoy

    nueva = None
    if tecnico_id != reemplaza_tecnico_id:
        nueva = ArmadoParticipacion(
            armado_id=id_armado,
            tecnico_id=tecnico_id,
            fecha_inicio=hoy,
            nota=nota
        )
        db.session.add(nueva)

    if reemplaza_principal:
        armado.tecnico_id = tecnico_id

    db.session.commit()

    return jsonify({"message": "Participacion creada", "id_participacion": nueva.id_participacion if nueva else None}), 201


@armados_blueprint.route('/participaciones/<int:id_participacion>', methods=['PUT'])
def actualizar_participacion(id_participacion):
    data = request.json or {}
    participacion = ArmadoParticipacion.query.get_or_404(id_participacion)
    participacion.fecha_inicio = parse_date(data.get('fecha_inicio')) or participacion.fecha_inicio
    participacion.fecha_fin = parse_date(data.get('fecha_fin'))
    participacion.nota = data.get('nota', participacion.nota)
    db.session.commit()
    return jsonify({"message": "ParticipaciÃ³n actualizada"}), 200


@armados_blueprint.route('/participaciones/<int:id_participacion>', methods=['DELETE'])
def eliminar_participacion(id_participacion):
    participacion = ArmadoParticipacion.query.get_or_404(id_participacion)
    armado = participacion.armado
    force = str(request.args.get("force", "")).lower() in ("1", "true", "si", "yes")

    # Regla de seguridad: solo permitir borrar participaciÃ³n si ese tÃ©cnico
    # no registrÃ³ movimientos en la planilla.
    if not force:
        tiene_movimientos = (
            ArmadoCajaMovimiento.query.filter(
                ArmadoCajaMovimiento.armado_id == participacion.armado_id,
                ArmadoCajaMovimiento.tecnico_id == participacion.tecnico_id
            ).first()
            is not None
        )
        if tiene_movimientos:
            return jsonify({
                "message": "No se puede eliminar: este tÃ©cnico ya registrÃ³ cambios en la planilla."
            }), 409

    db.session.delete(participacion)

    # Si era la Ãºltima participaciÃ³n, eliminar el armado completo.
    restantes = (
        ArmadoParticipacion.query.filter(
            ArmadoParticipacion.armado_id == participacion.armado_id,
            ArmadoParticipacion.id_participacion != participacion.id_participacion
        ).count()
    )
    if restantes == 0 and armado:
        db.session.delete(armado)
        db.session.commit()
        emitir_actualizacion_armado(participacion.armado_id, "armado")
        return jsonify({"message": "ParticipaciÃ³n y armado eliminados"}), 200

    # Si el tÃ©cnico activo coincide y hay otro historial, usar el mÃ¡s reciente.
    # Si no hay otro historial, conservar el tÃ©cnico actual para no violar NOT NULL.
    if armado and armado.tecnico_id == participacion.tecnico_id:
        ultimo = (
            ArmadoParticipacion.query.filter(
                ArmadoParticipacion.armado_id == armado.id_armado,
                ArmadoParticipacion.id_participacion != participacion.id_participacion
            )
            .order_by(ArmadoParticipacion.fecha_inicio.desc(), ArmadoParticipacion.id_participacion.desc())
            .first()
        )
        if ultimo:
            armado.tecnico_id = ultimo.tecnico_id

    db.session.commit()
    emitir_actualizacion_armado(participacion.armado_id, "armado")
    return jsonify({"message": "ParticipaciÃ³n eliminada"}), 200


