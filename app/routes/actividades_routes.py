from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import or_
import jwt
import unicodedata
from ..models import Actividad, Centro, Encargado, User
from ..database import db

actividades_blueprint = Blueprint('actividades', __name__)
JWT_KEYS = ["remoto753524"]


def _usuario_actual_desde_token():
    token = request.headers.get("Authorization") or ""
    if not token.startswith("Bearer "):
        return None
    try:
        token_value = token.split("Bearer ")[1]
        payload = None
        claves = list(JWT_KEYS)
        cfg_key = current_app.config.get("SECRET_KEY")
        if cfg_key and cfg_key not in claves:
            claves.append(cfg_key)
        for secret in claves:
            try:
                payload = jwt.decode(token_value, secret, algorithms=["HS256"])
                break
            except Exception:
                payload = None
        if not payload:
            return None
        user_id = payload.get("user_id") or payload.get("id") or payload.get("sub")
        if not user_id:
            return None
        return User.query.get(int(user_id))
    except Exception:
        return None


def _serialize_actividad(actividad):
    fecha_reclamo = actividad.fecha_reclamo.isoformat() if getattr(actividad, "fecha_reclamo", None) else None
    fecha_inicio = actividad.fecha_inicio.isoformat() if getattr(actividad, "fecha_inicio", None) else None
    fecha_termino = actividad.fecha_termino.isoformat() if getattr(actividad, "fecha_termino", None) else None
    tecnicos_asignados = []
    tecnico_ids = set()

    def push_tecnico(encargado):
        if not encargado:
            return
        enc_id = int(encargado.id_encargado)
        if enc_id in tecnico_ids:
            return
        tecnico_ids.add(enc_id)
        tecnicos_asignados.append({
            "id_encargado": encargado.id_encargado,
            "nombre_encargado": encargado.nombre_encargado
        })

    push_tecnico(actividad.encargado_principal)
    push_tecnico(actividad.encargado_ayudante)
    for enc in (actividad.encargados or []):
        push_tecnico(enc)

    return {
        "id_actividad": actividad.id_actividad,
        "nombre_actividad": actividad.nombre_actividad,
        "fecha_reclamo": fecha_reclamo,
        "fecha_inicio": fecha_inicio,
        "fecha_termino": fecha_termino,
        "area": actividad.area,
        "prioridad": actividad.prioridad,
        "tecnico_encargado": actividad.tecnico_encargado,
        "tecnico_ayudante": actividad.tecnico_ayudante,
        "tiempo_en_dar_solucion": actividad.tiempo_en_dar_solucion,
        "estado": actividad.estado,
        "centro_id": actividad.centro_id,
        "centro": {
            "id_centro": actividad.centro.id_centro if actividad.centro else None,
            "nombre": actividad.centro.nombre if actividad.centro else None,
            "cliente": actividad.centro.cliente.nombre if actividad.centro and actividad.centro.cliente else None,
            "cliente_id": actividad.centro.cliente_id if actividad.centro else None,
            "estado_del_centro": actividad.centro.estado if actividad.centro else None,
            "area": actividad.centro.area if actividad.centro else None,
            "ubicacion": actividad.centro.ubicacion if actividad.centro else None,
            "correo_centro": actividad.centro.correo_centro if actividad.centro else None,
            "telefono": actividad.centro.telefono if actividad.centro else None,
        },
        "encargado_principal": {
            "id_encargado": actividad.encargado_principal.id_encargado if actividad.encargado_principal else None,
            "nombre_encargado": actividad.encargado_principal.nombre_encargado if actividad.encargado_principal else None
        },
        "encargado_ayudante": {
            "id_encargado": actividad.encargado_ayudante.id_encargado if actividad.encargado_ayudante else None,
            "nombre_encargado": actividad.encargado_ayudante.nombre_encargado if actividad.encargado_ayudante else None
        },
        "tecnicos_asignados": tecnicos_asignados
    }


def _normalizar_texto(valor):
    texto = str(valor or "").strip().lower()
    if not texto:
        return ""
    texto = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return " ".join(texto.split())


def _filtrar_actividades_por_nombre(actividades, nombre_usuario):
    nombre_usuario_norm = _normalizar_texto(nombre_usuario)
    if not nombre_usuario_norm:
        return []

    tokens_usuario = [t for t in nombre_usuario_norm.split(" ") if len(t) >= 3]
    filtradas = []
    for actividad in actividades:
        nombre_principal = _normalizar_texto(
            actividad.encargado_principal.nombre_encargado if actividad.encargado_principal else ""
        )
        nombre_ayudante = _normalizar_texto(
            actividad.encargado_ayudante.nombre_encargado if actividad.encargado_ayudante else ""
        )
        nombres_relacion = [
            _normalizar_texto(enc.nombre_encargado) for enc in (actividad.encargados or [])
        ]
        nombres = [n for n in [nombre_principal, nombre_ayudante, *nombres_relacion] if n]
        if not nombres:
            continue

        coincide = False
        for n in nombres:
            if nombre_usuario_norm in n or n in nombre_usuario_norm:
                coincide = True
                break
            if any(tok in n for tok in tokens_usuario):
                coincide = True
                break

        if coincide:
            filtradas.append(actividad)

    return filtradas


def _encargados_ids_por_nombre(nombre_usuario):
    nombre_usuario_norm = _normalizar_texto(nombre_usuario)
    if not nombre_usuario_norm:
        return []
    tokens_usuario = [t for t in nombre_usuario_norm.split(" ") if len(t) >= 3]
    if not tokens_usuario:
        return []

    ids = []
    for enc in Encargado.query.all():
        nombre_enc = _normalizar_texto(enc.nombre_encargado)
        if not nombre_enc:
            continue
        coincide = (
            nombre_usuario_norm in nombre_enc
            or nombre_enc in nombre_usuario_norm
            or any(tok in nombre_enc for tok in tokens_usuario)
        )
        if coincide:
            try:
                enc_id = int(enc.id_encargado)
            except Exception:
                enc_id = 0
            if enc_id and enc_id not in ids:
                ids.append(enc_id)
    return ids


def _coerce_int_list(values):
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    out = []
    for value in values:
        try:
            iv = int(value)
        except Exception:
            continue
        if iv not in out:
            out.append(iv)
    return out


def _asignar_tecnicos_relacion(actividad, tecnico_encargado, tecnico_ayudante, tecnicos_adicionales):
    ids = []
    for val in [tecnico_encargado, tecnico_ayudante]:
        try:
            iv = int(val) if val is not None else None
        except Exception:
            iv = None
        if iv and iv not in ids:
            ids.append(iv)
    for iv in _coerce_int_list(tecnicos_adicionales):
        if iv not in ids:
            ids.append(iv)
    if not ids:
        actividad.encargados = []
        return
    actividad.encargados = Encargado.query.filter(Encargado.id_encargado.in_(ids)).all()

# Crear nueva actividad
@actividades_blueprint.route('/', methods=['POST'])
def crear_actividad():
    data = request.json
    tecnico_encargado = data.get('tecnico_encargado')
    tecnico_ayudante = data.get('tecnico_ayudante')
    nueva_actividad = Actividad(
        nombre_actividad=data.get('nombre_actividad'),
        fecha_reclamo=data.get('fecha_reclamo'),
        fecha_inicio=data.get('fecha_inicio'),
        fecha_termino=data.get('fecha_termino'),
        area=data.get('area'),
        prioridad=data.get('prioridad'),
        tecnico_encargado=tecnico_encargado,  # ID del encargado principal (opcional)
        tecnico_ayudante=tecnico_ayudante,    # ID del ayudante (opcional)
        tiempo_en_dar_solucion=data.get('tiempo_en_dar_solucion'),
        estado=data.get('estado'),
        centro_id=data.get('centro_id')  # ID del centro (opcional)
    )

    _asignar_tecnicos_relacion(
        nueva_actividad,
        tecnico_encargado,
        tecnico_ayudante,
        data.get('tecnicos_adicionales') or []
    )

    db.session.add(nueva_actividad)
    db.session.commit()
    return jsonify({"message": "Actividad creada exitosamente", "id_actividad": nueva_actividad.id_actividad}), 201

# Listar todas las actividades
@actividades_blueprint.route('/', methods=['GET'])
def obtener_actividades():
    actividades = Actividad.query.all()
    return jsonify([_serialize_actividad(actividad) for actividad in actividades]), 200


@actividades_blueprint.route('/mias', methods=['GET'])
def obtener_actividades_mias():
    usuario = _usuario_actual_desde_token()
    if not usuario:
        return jsonify({"message": "Token invalido o ausente"}), 401

    estado = (request.args.get("estado") or "").strip()
    area = (request.args.get("area") or "").strip()
    perfil = Encargado.query.filter_by(user_id=usuario.id).first()
    query = Actividad.query

    # Soporta ambos esquemas:
    # - tecnico_* guardando id_encargado (modelo normal)
    # - tecnico_* guardando user.id (datos legacy/migrados)
    tecnico_ids = [int(usuario.id)]
    if perfil and perfil.id_encargado:
        tecnico_ids.append(int(perfil.id_encargado))
    for enc_id in _encargados_ids_por_nombre(usuario.name):
        if enc_id not in tecnico_ids:
            tecnico_ids.append(enc_id)

    query = query.filter(
        or_(
            Actividad.tecnico_encargado.in_(tecnico_ids),
            Actividad.tecnico_ayudante.in_(tecnico_ids),
            Actividad.encargados.any(Encargado.id_encargado.in_(tecnico_ids)),
            Actividad.encargados.any(Encargado.user_id == usuario.id),
            Actividad.encargado_principal.has(Encargado.user_id == usuario.id),
            Actividad.encargado_ayudante.has(Encargado.user_id == usuario.id),
        )
    )
    if estado:
        query = query.filter(Actividad.estado.ilike(estado))
    if area:
        query = query.filter(Actividad.area.ilike(area))

    actividades = query.order_by(Actividad.fecha_inicio.asc().nullslast(), Actividad.id_actividad.desc()).all()

    # Fallback adicional por nombre del tecnico (cubre registros legacy con ids inconsistentes).
    base_fallback = Actividad.query.order_by(
        Actividad.fecha_inicio.asc().nullslast(),
        Actividad.id_actividad.desc()
    ).all()
    filtradas = _filtrar_actividades_por_nombre(base_fallback, usuario.name)

    merged = []
    vistos = set()
    for actividad in [*actividades, *filtradas]:
        aid = int(getattr(actividad, "id_actividad", 0) or 0)
        if not aid or aid in vistos:
            continue
        vistos.add(aid)
        merged.append(actividad)

    return jsonify([_serialize_actividad(actividad) for actividad in merged]), 200

# Actualizar actividad
@actividades_blueprint.route('/<int:id_actividad>', methods=['PUT'])
def actualizar_actividad(id_actividad):
    data = request.json
    actividad = Actividad.query.get_or_404(id_actividad)

    actividad.nombre_actividad = data.get('nombre_actividad', actividad.nombre_actividad)
    actividad.fecha_reclamo = data.get('fecha_reclamo', actividad.fecha_reclamo)
    actividad.fecha_inicio = data.get('fecha_inicio', actividad.fecha_inicio)
    actividad.fecha_termino = data.get('fecha_termino', actividad.fecha_termino)
    actividad.area = data.get('area', actividad.area)
    actividad.prioridad = data.get('prioridad', actividad.prioridad)
    actividad.tecnico_encargado = data.get('tecnico_encargado', actividad.tecnico_encargado)
    actividad.tecnico_ayudante = data.get('tecnico_ayudante', actividad.tecnico_ayudante)
    actividad.tiempo_en_dar_solucion = data.get('tiempo_en_dar_solucion', actividad.tiempo_en_dar_solucion)
    actividad.estado = data.get('estado', actividad.estado)
    actividad.centro_id = data.get('centro_id', actividad.centro_id)

    _asignar_tecnicos_relacion(
        actividad,
        actividad.tecnico_encargado,
        actividad.tecnico_ayudante,
        data.get('tecnicos_adicionales') if 'tecnicos_adicionales' in data else [
            enc.id_encargado for enc in (actividad.encargados or [])
            if enc.id_encargado not in {actividad.tecnico_encargado, actividad.tecnico_ayudante}
        ]
    )

    db.session.commit()
    return jsonify({"message": "Actividad actualizada exitosamente"}), 200

# Eliminar actividad
@actividades_blueprint.route('/<int:id_actividad>', methods=['DELETE'])
def eliminar_actividad(id_actividad):
    actividad = Actividad.query.get_or_404(id_actividad)
    db.session.delete(actividad)
    db.session.commit()
    return jsonify({"message": "Actividad eliminada exitosamente"}), 200
