from datetime import datetime

from flask import Blueprint, request, jsonify
from ..models import Soporte, Centro, Ismael, SoporteCaseTomado
from ..database import db

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


def _parse_date(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value
    return datetime.strptime(str(value), "%Y-%m-%d").date()

# Crear un nuevo registro de soporte
@soporte_blueprint.route('/', methods=['POST'])
def crear_soporte():
    data = request.json
    origen = str(data.get('origen', 'cliente')).lower().strip()
    if origen not in ('cliente', 'orca'):
        return jsonify({"error": "Origen invalido. Use 'cliente' u 'orca'."}), 400

    nuevo_soporte = Soporte(
        centro_id=data.get('centro_id'),
        problema=data.get('problema'),
        tipo=data.get('tipo'),  # "terreno" o "remoto"
        fecha_soporte=_parse_date(data.get('fecha_soporte')),
        solucion=data.get('solucion'),
        categoria_falla=data.get('categoria_falla'),
        cambio_equipo=data.get('cambio_equipo', False),
        equipo_cambiado=data.get('equipo_cambiado'),
        origen=origen,
        estado=data.get('estado', 'pendiente'),
        fecha_cierre=_parse_date(data.get('fecha_cierre')),
        case_code=data.get('case_code'),
        ismael_id_origen=data.get('ismael_id_origen')
    )

    db.session.add(nuevo_soporte)
    _registrar_case_tomado(nuevo_soporte.case_code, nuevo_soporte.ismael_id_origen)
    db.session.commit()

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
                "cliente": soporte.centro.cliente.nombre if soporte.centro and soporte.centro.cliente else None          
            },
            "problema": soporte.problema,
            "tipo": soporte.tipo,
            "fecha_soporte": soporte.fecha_soporte.isoformat() if soporte.fecha_soporte else None,
            "solucion": soporte.solucion,
            "categoria_falla": soporte.categoria_falla,
            "cambio_equipo": soporte.cambio_equipo,
            "equipo_cambiado": soporte.equipo_cambiado,
            "origen": soporte.origen or "cliente",
            "estado": soporte.estado,
            "fecha_cierre": soporte.fecha_cierre.isoformat() if soporte.fecha_cierre else None,
            "case_code": soporte.case_code,
            "ismael_id_origen": soporte.ismael_id_origen
        })

    return jsonify(resultado), 200


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

# Actualizar un registro de soporte
@soporte_blueprint.route('/<int:id_soporte>', methods=['PUT'])
def actualizar_soporte(id_soporte):
    data = request.json
    soporte = Soporte.query.get_or_404(id_soporte)

    soporte.centro_id = data.get('centro_id', soporte.centro_id)
    soporte.problema = data.get('problema', soporte.problema)
    soporte.tipo = data.get('tipo', soporte.tipo)
    if 'fecha_soporte' in data:
        soporte.fecha_soporte = _parse_date(data.get('fecha_soporte'))
    soporte.solucion = data.get('solucion', soporte.solucion)
    soporte.categoria_falla = data.get('categoria_falla', soporte.categoria_falla)
    soporte.cambio_equipo = data.get('cambio_equipo', soporte.cambio_equipo)
    soporte.equipo_cambiado = data.get('equipo_cambiado', soporte.equipo_cambiado)
    if 'origen' in data:
        origen = str(data.get('origen', 'cliente')).lower().strip()
        if origen not in ('cliente', 'orca'):
            return jsonify({"error": "Origen invalido. Use 'cliente' u 'orca'."}), 400
        soporte.origen = origen
    soporte.estado = data.get('estado', soporte.estado)
    if 'case_code' in data:
        soporte.case_code = data.get('case_code')
    if 'ismael_id_origen' in data:
        soporte.ismael_id_origen = data.get('ismael_id_origen')
    _registrar_case_tomado(soporte.case_code, soporte.ismael_id_origen)
    if 'fecha_cierre' in data:
        soporte.fecha_cierre = _parse_date(data.get('fecha_cierre'))

    db.session.commit()
    return jsonify({"message": "Soporte actualizado exitosamente"}), 200

# Eliminar un registro de soporte
@soporte_blueprint.route('/<int:id_soporte>', methods=['DELETE'])
def eliminar_soporte(id_soporte):
    soporte = Soporte.query.get_or_404(id_soporte)
    _registrar_case_tomado(soporte.case_code, soporte.ismael_id_origen)
    db.session.delete(soporte)
    db.session.commit()
    return jsonify({"message": "Soporte eliminado exitosamente"}), 200




