from datetime import datetime, timezone

from flask import Blueprint, request, jsonify
import jwt
from sqlalchemy import or_, text

from ..models import Soporte, Centro, Cliente, Ismael, SoporteCaseTomado, User
from ..database import db
from ..socketio_ext import emit_soporte_event
from .auth_routes import SECRET_KEY

soporte_blueprint = Blueprint('soporte', __name__)


def _registrar_case_tomado(case_code=None, ismael_id=None):
    source_id = str(ismael_id or "").strip()
    code = str(case_code or "").strip()

    if source_id:
        exists = SoporteCaseTomado.query.filter_by(ismael_id=source_id).first()
        if exists:
            return
        db.session.add(SoporteCaseTomado(case_code=None, ismael_id=source_id, origen='ismael'))
        return

    if not code:
        return
    exists = SoporteCaseTomado.query.filter_by(case_code=code).first()
    if exists:
        return
    db.session.add(SoporteCaseTomado(case_code=code, ismael_id=None, origen='ismael'))


def _ismael_id_ya_tomado(ismael_id=None):
    source_id = str(ismael_id or "").strip()
    if not source_id:
        return False
    if SoporteCaseTomado.query.filter_by(ismael_id=source_id).first():
        return True
    return Soporte.query.filter_by(ismael_id_origen=source_id).first() is not None


def _case_code_ya_tomado(case_code=None):
    code = str(case_code or "").strip()
    if not code:
        return False
    if SoporteCaseTomado.query.filter_by(case_code=code).first():
        return True
    return Soporte.query.filter_by(case_code=code).first() is not None


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()


def _iso_value(value):
    return value.isoformat() if value else None


def _get_datetime_attr(obj, attr):
    return getattr(obj, attr, None)


def _usuario_autenticado():
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer '):
        return None
    try:
        payload = jwt.decode(authorization[7:], SECRET_KEY, algorithms=['HS256'])
        return User.query.get(payload.get('user_id'))
    except Exception:
        return None

# Crear un nuevo registro de soporte
@soporte_blueprint.route('/', methods=['POST'])
def crear_soporte():
    data = request.json
    origen = str(data.get('origen', 'cliente')).lower().strip()
    if origen not in ('cliente', 'orca', 'terceros'):
        return jsonify({"error": "Origen invalido. Use 'cliente', 'orca' o 'terceros'."}), 400
    prioridad = str(data.get('prioridad', 'media')).lower().strip()
    if prioridad not in ('alta', 'media', 'baja'):
        return jsonify({"error": "Prioridad invalida. Use 'alta', 'media' o 'baja'."}), 400
    tipo = str(data.get('tipo') or '').lower().strip()
    if tipo not in ('terreno', 'remoto'):
        return jsonify({"error": "Tipo invalido. Use 'terreno' o 'remoto'."}), 400
    ismael_id_origen = data.get('ismael_id_origen')
    if _ismael_id_ya_tomado(ismael_id_origen):
        return jsonify({"error": "Este caso de ismael ya fue tomado para soporte."}), 409
    case_code = data.get('case_code')
    external_case_key = str(data.get('external_case_key') or '').strip()
    if external_case_key and not external_case_key.startswith('device-fail:'):
        return jsonify({"error": "Referencia de alerta externa invalida."}), 400
    tracking_code = external_case_key or (
        str(case_code).strip() if str(case_code or '').startswith('device-fail:') else ''
    )
    if tracking_code and _case_code_ya_tomado(tracking_code):
        return jsonify({"error": "Esta alerta de dispositivo ya fue tomada para soporte."}), 409

    nuevo_soporte = Soporte(
        centro_id=data.get('centro_id'),
        problema=data.get('problema'),
        tipo=tipo,
        fecha_soporte=_parse_date(data.get('fecha_soporte')),
        solucion=data.get('solucion'),
        categoria_falla=data.get('categoria_falla'),
        subcategoria_falla=data.get('subcategoria_falla'),
        permiso_trabajo=bool(data.get('permiso_trabajo', False)),
        cambio_equipo=data.get('cambio_equipo', False),
        equipo_cambiado=data.get('equipo_cambiado'),
        origen=origen,
        prioridad=prioridad,
        estado=data.get('estado', 'pendiente'),
        fecha_cierre=_parse_date(data.get('fecha_cierre')),
        case_code=None if external_case_key else case_code,
        ismael_id_origen=ismael_id_origen
    )

    db.session.add(nuevo_soporte)
    _registrar_case_tomado(nuevo_soporte.case_code, nuevo_soporte.ismael_id_origen)
    if external_case_key:
        _registrar_case_tomado(external_case_key)
    db.session.commit()
    emit_soporte_event("soporte_updated", {
        "action": "created",
        "id_soporte": nuevo_soporte.id_soporte,
        "estado": nuevo_soporte.estado,
        "centro_id": nuevo_soporte.centro_id,
        "created_at": _iso_value(_get_datetime_attr(nuevo_soporte, "created_at")),
        "updated_at": _iso_value(_get_datetime_attr(nuevo_soporte, "updated_at")),
    })

    return jsonify({"message": "Soporte creado exitosamente", "id_soporte": nuevo_soporte.id_soporte}), 201

# Listar todos los registros de soporte
@soporte_blueprint.route('/', methods=['GET'])
def obtener_soportes():
    soportes = Soporte.query.all()
    resultado = []
    for soporte in soportes:
        resultado.append({
            "id_soporte": soporte.id_soporte,
            "centro": {
                "id_centro": soporte.centro.id_centro if soporte.centro else None,
                "nombre": soporte.centro.nombre if soporte.centro else None,
                "cliente": soporte.centro.cliente.nombre if soporte.centro and soporte.centro.cliente else None,
                "ubicacion": soporte.centro.ubicacion if soporte.centro else None,
                "area": soporte.centro.area if soporte.centro else None
            },
            "problema": soporte.problema,
            "tipo": soporte.tipo,
            "fecha_soporte": _iso_value(soporte.fecha_soporte),
            "solucion": soporte.solucion,
            "categoria_falla": soporte.categoria_falla,
            "subcategoria_falla": soporte.subcategoria_falla,
            "permiso_trabajo": bool(soporte.permiso_trabajo),
            "cambio_equipo": soporte.cambio_equipo,
            "equipo_cambiado": soporte.equipo_cambiado,
            "origen": soporte.origen or "cliente",
            "prioridad": soporte.prioridad or "media",
            "estado": soporte.estado,
            "fecha_cierre": _iso_value(soporte.fecha_cierre),
            "correo_enviado": soporte.correo_enviado,
            "fecha_envio_correo": _iso_value(soporte.fecha_envio_correo),
            "correo_enviado_por": soporte.correo_enviado_por,
            "case_code": soporte.case_code,
            "ismael_id_origen": soporte.ismael_id_origen,
            "created_at": _iso_value(_get_datetime_attr(soporte, "created_at")),
            "updated_at": _iso_value(_get_datetime_attr(soporte, "updated_at"))
        })

    return jsonify(resultado), 200


@soporte_blueprint.route('/correos/historial', methods=['GET'])
def obtener_historial_correos():
    usuario = _usuario_autenticado()
    if not usuario:
        return jsonify({"error": "Sesion invalida o expirada."}), 401
    if str(usuario.rol or '').strip().lower() != 'admin':
        return jsonify({"error": "Solo un administrador puede consultar este historial."}), 403

    try:
        page = max(1, request.args.get('page', 1, type=int))
        per_page = min(100, max(5, request.args.get('per_page', 10, type=int)))
        query = (
            Soporte.query
            .join(Centro, Soporte.centro_id == Centro.id_centro)
            .join(Cliente, Centro.cliente_id == Cliente.id_cliente)
            .filter(Soporte.correo_enviado.is_(True))
        )

        fecha_desde = _parse_date(request.args.get('fecha_desde'))
        fecha_hasta = _parse_date(request.args.get('fecha_hasta'))
        fecha_envio_local = db.func.date(
            db.func.timezone('America/Santiago', Soporte.fecha_envio_correo)
        )
        if fecha_desde:
            query = query.filter(fecha_envio_local >= fecha_desde)
        if fecha_hasta:
            query = query.filter(fecha_envio_local <= fecha_hasta)

        cliente = str(request.args.get('cliente') or '').strip()
        centro = str(request.args.get('centro') or '').strip()
        responsable = str(request.args.get('responsable') or '').strip()
        tipo = str(request.args.get('tipo') or '').strip().lower()
        busqueda = str(request.args.get('q') or '').strip()
        if cliente:
            query = query.filter(Cliente.nombre.ilike(f'%{cliente}%'))
        if centro:
            query = query.filter(Centro.nombre.ilike(f'%{centro}%'))
        if responsable:
            query = query.filter(Soporte.correo_enviado_por.ilike(f'%{responsable}%'))
        if tipo in ('remoto', 'terreno'):
            query = query.filter(Soporte.tipo == tipo)
        if busqueda:
            patron = f'%{busqueda}%'
            query = query.filter(or_(
                Cliente.nombre.ilike(patron),
                Centro.nombre.ilike(patron),
                Soporte.problema.ilike(patron),
                Soporte.solucion.ilike(patron),
                Soporte.correo_enviado_por.ilike(patron),
            ))

        paginado = query.order_by(Soporte.fecha_envio_correo.desc()).paginate(
            page=page,
            per_page=per_page,
            error_out=False,
        )
        items = [{
            "id_soporte": soporte.id_soporte,
            "cliente": soporte.centro.cliente.nombre if soporte.centro and soporte.centro.cliente else None,
            "centro": soporte.centro.nombre if soporte.centro else None,
            "tipo": soporte.tipo,
            "problema": soporte.problema,
            "solucion": soporte.solucion,
            "fecha_cierre": _iso_value(soporte.fecha_cierre),
            "fecha_envio_correo": _iso_value(soporte.fecha_envio_correo),
            "correo_enviado_por": soporte.correo_enviado_por,
        } for soporte in paginado.items]
        return jsonify({
            "items": items,
            "page": paginado.page,
            "per_page": paginado.per_page,
            "total": paginado.total,
            "pages": paginado.pages,
        }), 200
    except ValueError:
        return jsonify({"error": "El formato de las fechas debe ser AAAA-MM-DD."}), 400


@soporte_blueprint.route('/ismael', methods=['GET'])
def obtener_casos_ismael():
    try:
        limit = request.args.get('limit', default=30, type=int)
        if not limit or limit < 1:
            limit = 30
        limit = min(limit, 200)

        ids_tomados = {
            str(item.ismael_id).strip().lower()
            for item in SoporteCaseTomado.query.all()
            if str(item.ismael_id or "").strip()
        }
        ids_tomados.update(
            str(item.ismael_id_origen).strip().lower()
            for item in Soporte.query.with_entities(Soporte.ismael_id_origen).all()
            if str(item.ismael_id_origen or "").strip()
        )

        rows = (
            Ismael.query
            .order_by(Ismael.created_at.desc(), Ismael.updated_at.desc())
            .limit(limit)
            .all()
        )

        data = []
        for row in rows:
            row_id = str(row.id or "").strip().lower()
            if row_id and row_id in ids_tomados:
                continue
            data.append({
                "id": row.id,
                "case_code": row.case_code,
                "centro": row.centro,
                "hora_llegada": row.hora_llegada.isoformat() if row.hora_llegada else None,
                "hora_envio_correo": row.hora_envio_correo.isoformat() if row.hora_envio_correo else None,
                "correo": row.correo,
                "analisis": row.analisis,
                "sugerencias": row.sugerencias,
                "respuesta_final": row.respuesta_final,
                "respuesta_enviada": bool(row.respuesta_enviada),
                "correo_remitente": row.correo_remitente,
                "correos_destinatarios": row.correos_destinatarios,
                "correos_copia": row.correos_copia,
                "asunto": row.asunto,
                "falla_especifica": row.falla_especifica,
                "estado": row.estado,
                "accion_pendiente": row.accion_pendiente,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            })

        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": f"Error al obtener casos de ismael: {str(e)}"}), 500


@soporte_blueprint.route('/fallas-dispositivos', methods=['GET'])
def obtener_fallas_dispositivos():
    fuentes = (
        ('reportefailaqua', 'aquachile', 'Aquachile'),
        ('reportefailcbay', 'caleta-bay', 'Caleta Bay'),
        ('reportefailsaysen', 'salmones-aysen', 'Salmones Aysen'),
    )
    try:
        limit = request.args.get('limit', default=200, type=int)
        limit = min(max(limit or 200, 1), 500)
        codigos_tomados = {
            str(item.case_code).strip().lower()
            for item in SoporteCaseTomado.query.with_entities(SoporteCaseTomado.case_code).all()
            if str(item.case_code or '').strip()
        }
        codigos_tomados.update(
            str(item.case_code).strip().lower()
            for item in Soporte.query.with_entities(Soporte.case_code).all()
            if str(item.case_code or '').strip()
        )

        resultados = []
        for tabla, fuente, cliente in fuentes:
            existe = db.session.execute(
                text("SELECT to_regclass(:tabla)"), {"tabla": tabla}
            ).scalar()
            if not existe:
                continue

            consulta = text(f"""
                SELECT id, entity_type, router_id, id_site, device_name, target_ip,
                       check_type, offline_since, recovered_at, duration_s, source_id, created_at
                FROM {tabla}
                WHERE recovered_at IS NULL
                  AND offline_since IS NOT NULL
                  AND offline_since <= NOW() - INTERVAL '5 minutes'
                ORDER BY offline_since DESC NULLS LAST, created_at DESC NULLS LAST
                LIMIT :limit
            """)
            rows = db.session.execute(consulta, {"limit": limit}).mappings().all()
            for row in rows:
                codigo_origen = f"device-fail:{fuente}:{row['id']}"
                if codigo_origen.lower() in codigos_tomados:
                    continue
                centro = str(row['router_id'] or row['device_name'] or '').strip()
                resultados.append({
                    "id": row['id'],
                    "source_key": codigo_origen,
                    "fuente": fuente,
                    "cliente": cliente,
                    "centro": centro,
                    "entity_type": row['entity_type'],
                    "router_id": row['router_id'],
                    "id_site": row['id_site'],
                    "device_name": row['device_name'],
                    "target_ip": row['target_ip'],
                    "check_type": row['check_type'],
                    "offline_since": _iso_value(row['offline_since']),
                    "recovered_at": _iso_value(row['recovered_at']),
                    "duration_s": row['duration_s'],
                    "source_id": row['source_id'],
                    "created_at": _iso_value(row['created_at']),
                    "estado": "recuperado" if row['recovered_at'] else "activo",
                })

        resultados.sort(key=lambda item: (
            item['estado'] != 'activo',
            -(datetime.fromisoformat(item['offline_since']).timestamp()
              if item.get('offline_since') else 0),
        ))
        return jsonify(resultados[:limit]), 200
    except Exception as e:
        return jsonify({"error": f"Error al obtener fallas de dispositivos: {str(e)}"}), 500


@soporte_blueprint.route('/casos-externos/<origen>/<case_id>', methods=['DELETE'])
def eliminar_caso_externo(origen, case_id):
    usuario = _usuario_autenticado()
    if not usuario:
        return jsonify({"error": "Sesion invalida o expirada."}), 401
    if str(usuario.rol or '').strip().lower() != 'admin':
        return jsonify({"error": "Solo un administrador puede eliminar casos externos."}), 403

    tablas_dispositivos = {
        'aquachile': 'reportefailaqua',
        'caleta-bay': 'reportefailcbay',
        'salmones-aysen': 'reportefailsaysen',
    }
    try:
        origen_normalizado = str(origen or '').strip().lower()
        if origen_normalizado == 'ismael':
            caso = db.session.get(Ismael, case_id)
            if not caso:
                return jsonify({"error": "El mensaje de Ismael ya no existe."}), 404
            db.session.delete(caso)
        elif origen_normalizado in tablas_dispositivos:
            try:
                id_dispositivo = int(case_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Identificador de alerta invalido."}), 400
            tabla = tablas_dispositivos[origen_normalizado]
            resultado = db.session.execute(
                text(f"DELETE FROM {tabla} WHERE id = :id"),
                {"id": id_dispositivo},
            )
            if not resultado.rowcount:
                db.session.rollback()
                return jsonify({"error": "La alerta de dispositivo ya no existe."}), 404
        else:
            return jsonify({"error": "Origen de caso externo invalido."}), 400

        db.session.commit()
        emit_soporte_event("soporte_updated", {
            "action": "external_case_deleted",
            "origen": origen_normalizado,
            "case_id": case_id,
        })
        return jsonify({"message": "Caso eliminado correctamente."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"No se pudo eliminar el caso: {str(e)}"}), 500

# Actualizar un registro de soporte
@soporte_blueprint.route('/<int:id_soporte>', methods=['PUT'])
def actualizar_soporte(id_soporte):
    data = request.json
    soporte = Soporte.query.get_or_404(id_soporte)
    estado_anterior = str(soporte.estado or '').lower()

    soporte.centro_id = data.get('centro_id', soporte.centro_id)
    soporte.problema = data.get('problema', soporte.problema)
    if 'tipo' in data:
        tipo = str(data.get('tipo') or '').lower().strip()
        if tipo not in ('terreno', 'remoto'):
            return jsonify({"error": "Tipo invalido. Use 'terreno' o 'remoto'."}), 400
        soporte.tipo = tipo
    if 'fecha_soporte' in data:
        soporte.fecha_soporte = _parse_date(data.get('fecha_soporte'))
    soporte.solucion = data.get('solucion', soporte.solucion)
    soporte.categoria_falla = data.get('categoria_falla', soporte.categoria_falla)
    soporte.subcategoria_falla = data.get('subcategoria_falla', soporte.subcategoria_falla)
    if 'permiso_trabajo' in data:
        soporte.permiso_trabajo = bool(data.get('permiso_trabajo'))
    soporte.cambio_equipo = data.get('cambio_equipo', soporte.cambio_equipo)
    soporte.equipo_cambiado = data.get('equipo_cambiado', soporte.equipo_cambiado)
    if 'origen' in data:
        origen = str(data.get('origen', 'cliente')).lower().strip()
        if origen not in ('cliente', 'orca', 'terceros'):
            return jsonify({"error": "Origen invalido. Use 'cliente', 'orca' o 'terceros'."}), 400
        soporte.origen = origen
    if 'prioridad' in data:
        prioridad = str(data.get('prioridad', 'media')).lower().strip()
        if prioridad not in ('alta', 'media', 'baja'):
            return jsonify({"error": "Prioridad invalida. Use 'alta', 'media' o 'baja'."}), 400
        soporte.prioridad = prioridad
    soporte.estado = data.get('estado', soporte.estado)
    estado_nuevo = str(soporte.estado or '').lower()
    estados_resueltos = ('resuelto', 'finalizado')
    if estado_nuevo in estados_resueltos and estado_anterior not in estados_resueltos:
        soporte.correo_enviado = False
        soporte.fecha_envio_correo = None
        soporte.correo_enviado_por = None
    elif estado_nuevo not in estados_resueltos and estado_anterior in estados_resueltos:
        soporte.correo_enviado = None
        soporte.fecha_envio_correo = None
        soporte.correo_enviado_por = None
    if 'case_code' in data:
        soporte.case_code = data.get('case_code')
    if 'ismael_id_origen' in data:
        soporte.ismael_id_origen = data.get('ismael_id_origen')
    _registrar_case_tomado(soporte.case_code, soporte.ismael_id_origen)
    if 'fecha_cierre' in data:
        soporte.fecha_cierre = _parse_date(data.get('fecha_cierre'))

    db.session.commit()
    emit_soporte_event("soporte_updated", {
        "action": "updated",
        "id_soporte": soporte.id_soporte,
        "estado": soporte.estado,
        "centro_id": soporte.centro_id,
        "created_at": _iso_value(_get_datetime_attr(soporte, "created_at")),
        "updated_at": _iso_value(_get_datetime_attr(soporte, "updated_at")),
    })
    return jsonify({"message": "Soporte actualizado exitosamente"}), 200


@soporte_blueprint.route('/<int:id_soporte>/correo-enviado', methods=['PATCH'])
def marcar_correo_enviado(id_soporte):
    usuario = _usuario_autenticado()
    if not usuario:
        return jsonify({"error": "Sesion invalida o expirada."}), 401

    soporte = Soporte.query.get_or_404(id_soporte)
    if str(soporte.estado or '').lower() not in ('resuelto', 'finalizado'):
        return jsonify({"error": "El correo solo puede confirmarse en un soporte resuelto."}), 409

    if not soporte.correo_enviado:
        soporte.correo_enviado = True
        soporte.fecha_envio_correo = datetime.now(timezone.utc)
        soporte.correo_enviado_por = usuario.name
        db.session.commit()

    emit_soporte_event("soporte_updated", {
        "action": "correo_enviado",
        "id_soporte": soporte.id_soporte,
        "estado": soporte.estado,
        "centro_id": soporte.centro_id,
        "correo_enviado": True,
        "fecha_envio_correo": _iso_value(soporte.fecha_envio_correo),
    })
    return jsonify({
        "message": "Correo marcado como enviado.",
        "correo_enviado": True,
        "fecha_envio_correo": _iso_value(soporte.fecha_envio_correo),
        "correo_enviado_por": soporte.correo_enviado_por,
    }), 200

# Eliminar un registro de soporte
@soporte_blueprint.route('/<int:id_soporte>', methods=['DELETE'])
def eliminar_soporte(id_soporte):
    soporte = Soporte.query.get_or_404(id_soporte)
    payload = {
        "action": "deleted",
        "id_soporte": soporte.id_soporte,
        "estado": soporte.estado,
        "centro_id": soporte.centro_id,
    }
    _registrar_case_tomado(soporte.case_code, soporte.ismael_id_origen)
    db.session.delete(soporte)
    db.session.commit()
    emit_soporte_event("soporte_updated", payload)
    return jsonify({"message": "Soporte eliminado exitosamente"}), 200




