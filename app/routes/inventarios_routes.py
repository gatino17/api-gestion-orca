import os
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from decimal import Decimal
from werkzeug.utils import secure_filename
import jwt
from sqlalchemy import or_
from ..models import Inventario, Centro, BodegaInventarioEquipo, BodegaInventarioToma, BodegaInventarioEscaneo, User, db

# Crear el blueprint
inventarios_blueprint = Blueprint('inventarios', __name__)
SECRET_KEY = "remoto753524"

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/inventarios_docs')

CATALOGO_INVENTARIO_GRUPOS = [
    {
        "categoria": "Oficina",
        "items": [
            "PC", "Monitor", "Mouse", "Teclado", "Router", "Switch", "Switch (Cisco)",
            "Switch raqueable", "Camara Interior", "Parlantes", "Sensor Magnetico",
            "Rack 9U - tuercas - tornillos", "Zapatilla Rack (PDU)",
        ],
    },
    {"categoria": "Base tierra", "items": ["PC cliente", "Rack 2", "Ubiquiti TX", "Ubiquiti RX", "Pantalla"]},
    {
        "categoria": "Tablero Alarma",
        "items": [
            "Tablero 500x400x200", "Baliza Interior", "Bocina Interior", "Baliza Exterior",
            "Bocina Exterior", "Foco led 150W", "Foco led 50W", "Fuente poder 12V", "Axis P8221",
        ],
    },
    {
        "categoria": "Tablero Respaldo",
        "items": [
            "Tablero 1200x800x300", "Tablero 1000x600x300", "Inversor cargador Victron",
            "Panel Victron", "Bateria 1", "Bateria 2", "Bateria 3", "Bateria 4", "Bateria 5",
            "Bateria 6", "Switch POE", "Sensor magnetico respaldo", "Sensor magnetico cargador",
            "Cargador 1", "Cargador 2", "Tablero Cargador 750x500x250", "UPS online",
        ],
    },
    {
        "categoria": "Mastil",
        "items": [
            "Tablero Derivacion (400x300x200)", "Radar 1", "Radar 2", "Cable rj radar 1",
            "Cable rj radar 2", "Soporte radar 1", "Soporte radar 2", "Camara PTZ termal",
            "Camara PTZ Laser", "Camara PTZ Laser 2", "Camara Modulo", "Camara Silo 1",
            "Camara Silo 2", "Camara Ensinerador", "Ensilaje interior", "Ensilaje exterior",
            "Camara Popa", "Camara acceso 1", "Camara acceso 2", "Camara acceso 3",
            "Camara acceso 4", "Enlace Ubiquiti",
        ],
    },
    {
        "categoria": "Tablero Camara",
        "items": [
            "Tablero Camara (500x700x250)", "Poe Power 1", "Poe Power 2", "Poe Power 3",
            "Poe Power 4", "Poe Power 5", "Switch POE 1", "Switch POE 2", "Mass",
            "Tablero 750x500x250", "Switch 1", "Switch 2", "Switch 3", "Switch 4", "Netio",
        ],
    },
]

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def _parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _serialize_bodega_equipo(item: BodegaInventarioEquipo):
    return {
        "id_bodega_equipo": item.id_bodega_equipo,
        "numero_serie": item.numero_serie,
        "codigo": item.codigo,
        "equipo_nombre": item.equipo_nombre,
        "descripcion_producto": item.descripcion_producto,
        "fecha_ingreso": item.fecha_ingreso.isoformat() if item.fecha_ingreso else None,
        "orden_compra": item.orden_compra,
        "valor": float(item.valor) if item.valor is not None else None,
        "modelo": item.modelo,
        "estado_equipo": item.estado_equipo,
        "ubicacion": item.ubicacion,
        "imagen_base64": item.imagen_base64,
        "imagen_nombre": item.imagen_nombre,
        "estado_asignacion": item.estado_asignacion,
        "tecnico_asignado_id": item.tecnico_asignado_id,
        "tecnico_asignado_nombre": item.tecnico_asignado_nombre,
        "asignado_por_id": item.asignado_por_id,
        "asignado_por_nombre": item.asignado_por_nombre,
        "fecha_asignacion": item.fecha_asignacion.isoformat() if item.fecha_asignacion else None,
        "fecha_devolucion": item.fecha_devolucion.isoformat() if item.fecha_devolucion else None,
        "observacion_asignacion": item.observacion_asignacion,
        "observacion_devolucion": item.observacion_devolucion,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _normalizar_busqueda(valor):
    return str(valor or "").strip().lower()


def _duplicate_bodega_equipo_response(item: BodegaInventarioEquipo):
    ubicacion = item.ubicacion or "Bodega"
    equipo = item.equipo_nombre or "Equipo"
    serie = item.numero_serie or "-"
    estado = item.estado_equipo or "-"
    detalle = f"Ya existe en {ubicacion}: {equipo}, serie {serie}, estado {estado}."
    return jsonify({
        "error": detalle,
        "duplicado": True,
        "existente": _serialize_bodega_equipo(item),
        "estado_asignacion": item.estado_asignacion or "en_bodega",
    }), 400


def _normalizar_tipo_equipo(valor):
    return str(valor or "").strip()


def _equipos_esperados_bodega(tipo_equipo=None):
    query = (
        BodegaInventarioEquipo.query
        .filter(
            or_(
                BodegaInventarioEquipo.estado_asignacion.is_(None),
                db.func.lower(BodegaInventarioEquipo.estado_asignacion) != "asignado_tecnico"
            )
        )
    )
    tipo = _normalizar_tipo_equipo(tipo_equipo)
    if tipo:
        query = query.filter(db.func.lower(BodegaInventarioEquipo.equipo_nombre) == tipo.lower())
    return query.order_by(BodegaInventarioEquipo.equipo_nombre.asc(), BodegaInventarioEquipo.codigo.asc()).all()


def _buscar_equipo_bodega(valor):
    valor = str(valor or "").strip()
    if not valor:
        return None
    valor_norm = valor.lower()
    return (
        BodegaInventarioEquipo.query
        .filter(
            or_(
                db.func.lower(BodegaInventarioEquipo.codigo) == valor_norm,
                db.func.lower(BodegaInventarioEquipo.numero_serie) == valor_norm
            )
        )
        .first()
    )


def _serialize_bodega_toma_escaneo(item: BodegaInventarioEscaneo):
    return {
        "id_escaneo": item.id_escaneo,
        "toma_id": item.toma_id,
        "bodega_equipo_id": item.bodega_equipo_id,
        "codigo": item.codigo,
        "numero_serie": item.numero_serie,
        "equipo_nombre": item.equipo_nombre,
        "categoria_seleccionada": item.categoria_seleccionada,
        "tipo_seleccionado": item.tipo_seleccionado,
        "ubicacion_sistema": item.ubicacion_sistema,
        "estado_sistema": item.estado_sistema,
        "resultado": item.resultado,
        "escaneado_por_id": item.escaneado_por_id,
        "escaneado_por_nombre": item.escaneado_por_nombre,
        "observacion": item.observacion,
        "created_at": item.created_at.isoformat() if item.created_at else None,
    }


def _escaneo_pertenece_tipo(item, tipo_equipo):
    tipo = _normalizar_tipo_equipo(tipo_equipo)
    if not tipo:
        return True
    return (
        str(item.tipo_seleccionado or "").strip().lower() == tipo.lower()
        or str(item.equipo_nombre or "").strip().lower() == tipo.lower()
    )


def _resumen_bodega_toma(toma: BodegaInventarioToma, include_detalle=False, tipo_equipo=None):
    esperados = _equipos_esperados_bodega(tipo_equipo=tipo_equipo)
    esperados_ids = {item.id_bodega_equipo for item in esperados}
    escaneos = [
        item for item in list(toma.escaneos or [])
        if _escaneo_pertenece_tipo(item, tipo_equipo)
    ]
    encontrados_ids = {
        item.bodega_equipo_id for item in escaneos
        if item.bodega_equipo_id and item.bodega_equipo_id in esperados_ids and item.resultado in {"encontrado", "duplicado"}
    }
    manuales = [item for item in escaneos if item.resultado == "manual"]
    faltantes = [item for item in esperados if item.id_bodega_equipo not in encontrados_ids]
    no_esperados = [item for item in escaneos if item.resultado == "no_esperado"]
    duplicados = [item for item in escaneos if item.resultado == "duplicado"]
    no_corresponden = [item for item in escaneos if item.resultado == "no_corresponde"]
    total_esperado = len(esperados)
    porcentaje = round((len(encontrados_ids) / total_esperado) * 100, 1) if total_esperado else 0
    resumen = {
        "total_esperado": total_esperado,
        "total_escaneos": len(escaneos),
        "encontrados": len(encontrados_ids) + len(manuales),
        "manuales": len(manuales),
        "faltantes": len(faltantes),
        "no_esperados": len(no_esperados),
        "duplicados": len(duplicados),
        "no_corresponden": len(no_corresponden),
        "cumplimiento": porcentaje,
    }
    if include_detalle:
        resumen["faltantes_detalle"] = [_serialize_bodega_equipo(item) for item in faltantes]
        resumen["no_esperados_detalle"] = [_serialize_bodega_toma_escaneo(item) for item in no_esperados]
        resumen["duplicados_detalle"] = [_serialize_bodega_toma_escaneo(item) for item in duplicados]
        resumen["no_corresponden_detalle"] = [_serialize_bodega_toma_escaneo(item) for item in no_corresponden]
        resumen["manuales_detalle"] = [_serialize_bodega_toma_escaneo(item) for item in manuales]
    return resumen


def _serialize_bodega_toma(item: BodegaInventarioToma, include_detalle=False, tipo_equipo=None):
    data = {
        "id_toma": item.id_toma,
        "nombre": item.nombre,
        "ubicacion": item.ubicacion,
        "estado": item.estado,
        "responsable_id": item.responsable_id,
        "responsable_nombre": item.responsable_nombre,
        "fecha_inicio": item.fecha_inicio.isoformat() if item.fecha_inicio else None,
        "fecha_cierre": item.fecha_cierre.isoformat() if item.fecha_cierre else None,
        "observacion": item.observacion,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        "resumen": _resumen_bodega_toma(item, include_detalle=include_detalle, tipo_equipo=tipo_equipo),
    }
    if include_detalle:
        escaneos = [
            escaneo for escaneo in list(item.escaneos or [])
            if _escaneo_pertenece_tipo(escaneo, tipo_equipo)
        ]
        data["escaneos"] = [
            _serialize_bodega_toma_escaneo(escaneo)
            for escaneo in sorted(escaneos, key=lambda x: x.created_at or datetime.min, reverse=True)
        ]
    return data


def _usuario_actual_desde_token():
    token = request.headers.get("Authorization") or ""
    if not token.startswith("Bearer "):
        return None
    try:
        payload = jwt.decode(token.split("Bearer ")[1], SECRET_KEY, algorithms=["HS256"])
        user_id = payload.get("user_id") or payload.get("id") or payload.get("sub")
        try:
            user_id = int(user_id)
        except Exception:
            return None
        return User.query.get(user_id)
    except Exception:
        return None


@inventarios_blueprint.route('/bodega_tomas', methods=['GET'])
def listar_bodega_tomas():
    try:
        estado = _normalizar_busqueda(request.args.get("estado"))
        query = BodegaInventarioToma.query
        if estado in {"abierto", "cerrado"}:
            query = query.filter(BodegaInventarioToma.estado == estado)
        rows = query.order_by(BodegaInventarioToma.fecha_inicio.desc(), BodegaInventarioToma.id_toma.desc()).all()
        return jsonify([_serialize_bodega_toma(item) for item in rows]), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_tipos', methods=['GET'])
def listar_bodega_tipos():
    try:
        resumen = {}
        for grupo in CATALOGO_INVENTARIO_GRUPOS:
            categoria = str(grupo.get("categoria") or "Sin categoria").strip()
            for nombre in grupo.get("items") or []:
                nombre = str(nombre or "").strip()
                if not nombre:
                    continue
                key = nombre.lower()
                resumen[key] = {
                    "categoria": categoria,
                    "equipo_nombre": nombre,
                    "total_esperado": 0,
                    "catalogo": True,
                }
        for item in _equipos_esperados_bodega():
            nombre = str(item.equipo_nombre or "").strip()
            if not nombre:
                continue
            key = nombre.lower()
            if key not in resumen:
                resumen[key] = {
                    "categoria": "Bodega",
                    "equipo_nombre": nombre,
                    "total_esperado": 0,
                    "catalogo": False,
                }
            resumen[key]["total_esperado"] += 1
        orden_categoria = {
            str(grupo.get("categoria") or "").strip().lower(): idx
            for idx, grupo in enumerate(CATALOGO_INVENTARIO_GRUPOS)
        }
        rows = sorted(
            resumen.values(),
            key=lambda x: (
                orden_categoria.get(str(x.get("categoria") or "").strip().lower(), 999),
                str(x.get("equipo_nombre") or "").lower(),
            )
        )
        return jsonify(rows), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_tomas', methods=['POST'])
def crear_bodega_toma():
    data = request.get_json() or {}
    actual = _usuario_actual_desde_token()
    nombre = str(data.get("nombre") or "").strip()
    if not nombre:
        nombre = f"Inventario bodega {datetime.utcnow().strftime('%d-%m-%Y')}"
    try:
        item = BodegaInventarioToma(
            nombre=nombre,
            ubicacion=str(data.get("ubicacion") or "Bodega central").strip() or "Bodega central",
            estado="abierto",
            responsable_id=getattr(actual, "id", None),
            responsable_nombre=getattr(actual, "name", None) or getattr(actual, "email", None),
            observacion=data.get("observacion"),
        )
        db.session.add(item)
        db.session.commit()
        return jsonify({"message": "Toma de inventario creada", "toma": _serialize_bodega_toma(item, include_detalle=True)}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_tomas/<int:id_toma>', methods=['GET'])
def obtener_bodega_toma(id_toma):
    item = BodegaInventarioToma.query.get(id_toma)
    if not item:
        return jsonify({"error": "Toma de inventario no encontrada"}), 404
    tipo_equipo = _normalizar_tipo_equipo(request.args.get("tipo_equipo"))
    return jsonify(_serialize_bodega_toma(item, include_detalle=True, tipo_equipo=tipo_equipo)), 200


@inventarios_blueprint.route('/bodega_tomas/<int:id_toma>/escaneos', methods=['POST'])
def registrar_bodega_toma_escaneo(id_toma):
    toma = BodegaInventarioToma.query.get(id_toma)
    if not toma:
        return jsonify({"error": "Toma de inventario no encontrada"}), 404
    if toma.estado != "abierto":
        return jsonify({"error": "La toma esta cerrada"}), 400

    data = request.get_json() or {}
    valor = str(data.get("valor") or data.get("codigo") or data.get("numero_serie") or "").strip()
    if not valor:
        return jsonify({"error": "Debes ingresar codigo o numero de serie"}), 400
    tipo_seleccionado = _normalizar_tipo_equipo(data.get("tipo_equipo") or data.get("tipo_seleccionado"))
    categoria_seleccionada = _normalizar_tipo_equipo(data.get("categoria") or data.get("categoria_seleccionada"))

    actual = _usuario_actual_desde_token()
    equipo = _buscar_equipo_bodega(valor)
    resultado = "no_esperado"
    codigo = valor
    numero_serie = str(data.get("numero_serie") or "").strip() or None
    equipo_nombre = str(data.get("equipo_nombre") or "").strip() or None
    ubicacion_sistema = None
    estado_sistema = None
    bodega_equipo_id = None

    if equipo:
        bodega_equipo_id = equipo.id_bodega_equipo
        codigo = equipo.codigo
        numero_serie = equipo.numero_serie
        equipo_nombre = equipo.equipo_nombre
        ubicacion_sistema = equipo.ubicacion
        estado_sistema = equipo.estado_equipo
        ya_escaneado = BodegaInventarioEscaneo.query.filter_by(
            toma_id=toma.id_toma,
            bodega_equipo_id=equipo.id_bodega_equipo
        ).first()
        if tipo_seleccionado and str(equipo.equipo_nombre or "").strip().lower() != tipo_seleccionado.lower():
            resultado = "no_corresponde"
        else:
            resultado = "duplicado" if ya_escaneado else "encontrado"
    else:
        equipo_nombre = tipo_seleccionado or equipo_nombre
        if tipo_seleccionado:
            resultado = "manual"
        ya_escaneado = BodegaInventarioEscaneo.query.filter(
            BodegaInventarioEscaneo.toma_id == toma.id_toma,
            or_(
                db.func.lower(BodegaInventarioEscaneo.codigo) == valor.lower(),
                db.func.lower(BodegaInventarioEscaneo.numero_serie) == valor.lower()
            )
        ).first()
        if ya_escaneado:
            resultado = "duplicado"

    try:
        escaneo = BodegaInventarioEscaneo(
            toma_id=toma.id_toma,
            bodega_equipo_id=bodega_equipo_id,
            codigo=codigo,
            numero_serie=numero_serie,
            equipo_nombre=equipo_nombre,
            categoria_seleccionada=categoria_seleccionada or None,
            tipo_seleccionado=tipo_seleccionado or None,
            ubicacion_sistema=ubicacion_sistema,
            estado_sistema=estado_sistema,
            resultado=resultado,
            escaneado_por_id=getattr(actual, "id", None),
            escaneado_por_nombre=getattr(actual, "name", None) or getattr(actual, "email", None),
            observacion=data.get("observacion"),
        )
        toma.updated_at = datetime.utcnow()
        db.session.add(escaneo)
        db.session.commit()
        return jsonify({
            "message": "Escaneo registrado",
            "escaneo": _serialize_bodega_toma_escaneo(escaneo),
            "toma": _serialize_bodega_toma(toma, include_detalle=True, tipo_equipo=tipo_seleccionado),
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_tomas/<int:id_toma>/cerrar', methods=['POST'])
def cerrar_bodega_toma(id_toma):
    item = BodegaInventarioToma.query.get(id_toma)
    if not item:
        return jsonify({"error": "Toma de inventario no encontrada"}), 404
    try:
        item.estado = "cerrado"
        item.fecha_cierre = datetime.utcnow()
        item.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"message": "Toma de inventario cerrada", "toma": _serialize_bodega_toma(item, include_detalle=True)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_tomas/escaneos/<int:id_escaneo>', methods=['DELETE'])
def eliminar_bodega_toma_escaneo(id_escaneo):
    escaneo = BodegaInventarioEscaneo.query.get(id_escaneo)
    if not escaneo:
        return jsonify({"error": "Escaneo no encontrado"}), 404
    if escaneo.toma and escaneo.toma.estado != "abierto":
        return jsonify({"error": "No se puede eliminar un escaneo de una toma cerrada"}), 400
    try:
        toma = escaneo.toma
        db.session.delete(escaneo)
        if toma:
            toma.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"message": "Escaneo eliminado"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

def is_allowed_file(filename):
    """Verifica si la extensión del archivo está permitida."""
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# Obtener todos los inventarios o filtrar por centro_id
#@inventarios_blueprint.route('/', methods=['GET'])
def obtener_inventarios_logic(centro_id=None):
    try:
        inventarios = Inventario.query.filter_by(centro_id=centro_id).all() if centro_id else Inventario.query.all()
        inventarios_data = [{"id_inventario": i.id_inventario, "centro_id": i.centro_id, "documento": i.documento} for i in inventarios]
        return inventarios_data, 200
    except Exception as e:
        return {"error": str(e)}, 400

# Crear un nuevo inventario
#@inventarios_blueprint.route('/', methods=['POST'])
def crear_inventario_logic(data, file):
    try:
        centro_id = data.get('centro_id')
        if not centro_id or not Centro.query.get(centro_id):
            return {"error": "Centro no encontrado"}, 404

        documento_path = None
        if file and is_allowed_file(file.filename):
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            documento_path = f"inventarios_docs/{filename}"
            file.save(os.path.join(UPLOAD_FOLDER, filename))

        nuevo_inventario = Inventario(centro_id=centro_id, documento=documento_path)
        db.session.add(nuevo_inventario)
        db.session.commit()

        return {"message": "Inventario creado exitosamente", "id_inventario": nuevo_inventario.id_inventario}, 201
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400
    
# Descargar el documento asociado a un inventario
@inventarios_blueprint.route('/<int:id_inventario>/documento', methods=['GET'])
def descargar_documento_inventario(id_inventario):
    try:
        inventario = Inventario.query.get_or_404(id_inventario)
        if not inventario.documento:
            return jsonify({"error": "El inventario no tiene un documento asociado"}), 404

        file_path = os.path.join(os.getcwd(), 'uploads', inventario.documento.replace('/', os.sep))
        if not os.path.exists(file_path):
            return jsonify({"error": "El archivo no existe"}), 404

        return send_file(
            file_path,
            as_attachment=True,
            download_name=os.path.basename(file_path),
            mimetype="application/octet-stream"
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Actualizar un inventario
#@inventarios_blueprint.route('/<int:id_inventario>', methods=['PUT'])
def actualizar_inventario_logic(id_inventario, data, file):
    try:
        inventario = Inventario.query.get_or_404(id_inventario)
        
        if data.get('centro_id'):
            centro_id = int(data.get('centro_id'))
            if not Centro.query.get(centro_id):
                return {"error": "Centro no encontrado"}, 404
            inventario.centro_id = centro_id

        if file and is_allowed_file(file.filename):
            if inventario.documento:
                existing_file_path = os.path.join(os.getcwd(), 'uploads', inventario.documento.replace('/', os.sep))
                if os.path.exists(existing_file_path):
                    os.remove(existing_file_path)

            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            relative_path = f"inventarios_docs/{filename}"
            absolute_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(absolute_path)
            inventario.documento = relative_path

        db.session.commit()
        return {"message": "Inventario actualizado exitosamente"}, 200
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400
    
# Eliminar un inventario
#@inventarios_blueprint.route('/<int:id_inventario>', methods=['DELETE'])
def eliminar_inventario_logic(id_inventario):
    try:
        inventario = Inventario.query.get_or_404(id_inventario)
        if inventario.documento:
            file_path = os.path.join(os.getcwd(), 'uploads', inventario.documento.replace('/', os.sep))
            if os.path.exists(file_path):
                os.remove(file_path)

        db.session.delete(inventario)
        db.session.commit()
        return {"message": "Inventario eliminado exitosamente"}, 200
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400
    
# Eliminar un inventario por centro
def eliminar_inventarios_por_centro(centro_id):
    try:
        # Obtener todos los inventarios asociados al centro_id
        inventarios = Inventario.query.filter_by(centro_id=centro_id).all()

        for inventario in inventarios:
            if inventario.documento:
                # Construir la ruta absoluta del archivo
                file_path = os.path.join(os.getcwd(), 'uploads', inventario.documento.replace('/', os.sep))
                
                # Verificar si el archivo existe y eliminarlo
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Archivo eliminado: {file_path}")
                else:
                    print(f"Archivo no encontrado: {file_path}")

        # Eliminar los registros de inventarios de la base de datos
        Inventario.query.filter_by(centro_id=centro_id).delete()
        db.session.commit()
        
        return jsonify({"message": "Todos los inventarios del centro eliminados exitosamente."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_equipos', methods=['GET'])
def listar_bodega_equipos():
    try:
        q = str(request.args.get('q', '')).strip().lower()
        rows = BodegaInventarioEquipo.query.order_by(BodegaInventarioEquipo.updated_at.desc(), BodegaInventarioEquipo.id_bodega_equipo.desc()).all()
        data = [_serialize_bodega_equipo(x) for x in rows]
        if q:
            data = [
                x for x in data
                if q in " ".join([
                    str(x.get("numero_serie") or ""),
                    str(x.get("codigo") or ""),
                    str(x.get("equipo_nombre") or ""),
                    str(x.get("modelo") or ""),
                    str(x.get("estado_equipo") or ""),
                    str(x.get("ubicacion") or ""),
                ]).lower()
            ]
        return jsonify(data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_equipos', methods=['POST'])
def crear_bodega_equipos():
    payload = request.get_json() or {}
    items = payload.get("items") if isinstance(payload.get("items"), list) else [payload]
    if not items:
        return jsonify({"error": "No hay items para crear"}), 400
    try:
        creados = []
        for raw in items:
            numero_serie = str(raw.get("numero_serie") or "").strip()
            codigo = str(raw.get("codigo") or "").strip()
            equipo_nombre = str(raw.get("equipo_nombre") or "").strip()
            if not numero_serie or not codigo or not equipo_nombre:
                return jsonify({"error": "numero_serie, codigo y equipo_nombre son obligatorios"}), 400

            existe_serie = BodegaInventarioEquipo.query.filter(db.func.lower(BodegaInventarioEquipo.numero_serie) == numero_serie.lower()).first()
            if existe_serie:
                return _duplicate_bodega_equipo_response(existe_serie)

            item = BodegaInventarioEquipo(
                numero_serie=numero_serie,
                codigo=codigo,
                equipo_nombre=equipo_nombre,
                descripcion_producto=raw.get("descripcion_producto"),
                fecha_ingreso=_parse_date(raw.get("fecha_ingreso")),
                orden_compra=raw.get("orden_compra"),
                valor=Decimal(str(raw.get("valor"))) if raw.get("valor") not in (None, "") else None,
                modelo=raw.get("modelo"),
                estado_equipo=str(raw.get("estado_equipo") or "Operativo"),
                ubicacion=str(raw.get("ubicacion") or "Bodega central"),
                imagen_base64=raw.get("imagen_base64"),
                imagen_nombre=raw.get("imagen_nombre"),
                estado_asignacion="en_bodega",
            )
            db.session.add(item)
            creados.append(item)

        db.session.commit()
        return jsonify({"message": "Equipos creados", "items": [_serialize_bodega_equipo(x) for x in creados]}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_equipos/<int:id_bodega_equipo>', methods=['PUT'])
def actualizar_bodega_equipo(id_bodega_equipo):
    data = request.get_json() or {}
    item = BodegaInventarioEquipo.query.get(id_bodega_equipo)
    if not item:
        return jsonify({"error": "Equipo no encontrado"}), 404
    try:
        if "numero_serie" in data:
            serie = str(data.get("numero_serie") or "").strip()
            if not serie:
                return jsonify({"error": "numero_serie es obligatorio"}), 400
            dup = BodegaInventarioEquipo.query.filter(
                db.func.lower(BodegaInventarioEquipo.numero_serie) == serie.lower(),
                BodegaInventarioEquipo.id_bodega_equipo != item.id_bodega_equipo
            ).first()
            if dup:
                return _duplicate_bodega_equipo_response(dup)
            item.numero_serie = serie

        if "codigo" in data:
            codigo = str(data.get("codigo") or "").strip()
            if not codigo:
                return jsonify({"error": "codigo es obligatorio"}), 400
            item.codigo = codigo

        if "equipo_nombre" in data:
            equipo_nombre = str(data.get("equipo_nombre") or "").strip()
            if not equipo_nombre:
                return jsonify({"error": "equipo_nombre es obligatorio"}), 400
            item.equipo_nombre = equipo_nombre

        if "descripcion_producto" in data:
            item.descripcion_producto = data.get("descripcion_producto")
        if "fecha_ingreso" in data:
            item.fecha_ingreso = _parse_date(data.get("fecha_ingreso"))
        if "orden_compra" in data:
            item.orden_compra = data.get("orden_compra")
        if "valor" in data:
            item.valor = Decimal(str(data.get("valor"))) if data.get("valor") not in (None, "") else None
        if "modelo" in data:
            item.modelo = data.get("modelo")
        if "estado_equipo" in data:
            item.estado_equipo = str(data.get("estado_equipo") or "Operativo")
        if "ubicacion" in data:
            item.ubicacion = str(data.get("ubicacion") or "Bodega central")
        if "imagen_base64" in data:
            item.imagen_base64 = data.get("imagen_base64")
        if "imagen_nombre" in data:
            item.imagen_nombre = data.get("imagen_nombre")
        if "estado_asignacion" in data:
            estado_asignacion = str(data.get("estado_asignacion") or "en_bodega").strip().lower()
            if estado_asignacion not in {"en_bodega", "asignado_tecnico", "asignado_armado"}:
                return jsonify({"error": "estado_asignacion invalido"}), 400
            item.estado_asignacion = estado_asignacion
            if estado_asignacion == "en_bodega":
                item.tecnico_asignado_id = None
                item.tecnico_asignado_nombre = None

        if "tecnico_asignado_id" in data:
            raw_id = data.get("tecnico_asignado_id")
            if raw_id in (None, "", 0, "0"):
                item.tecnico_asignado_id = None
            else:
                try:
                    tid = int(raw_id)
                except Exception:
                    return jsonify({"error": "tecnico_asignado_id invalido"}), 400
                user = User.query.get(tid)
                if not user:
                    return jsonify({"error": "Tecnico no encontrado"}), 404
                item.tecnico_asignado_id = tid
                item.tecnico_asignado_nombre = user.name

        if "tecnico_asignado_nombre" in data:
            item.tecnico_asignado_nombre = str(data.get("tecnico_asignado_nombre") or "").strip() or None
        if "asignado_por_id" in data:
            item.asignado_por_id = int(data.get("asignado_por_id")) if data.get("asignado_por_id") not in (None, "", 0, "0") else None
        if "asignado_por_nombre" in data:
            item.asignado_por_nombre = str(data.get("asignado_por_nombre") or "").strip() or None
        if "fecha_asignacion" in data:
            try:
                item.fecha_asignacion = datetime.fromisoformat(str(data.get("fecha_asignacion")).replace("Z", "+00:00")) if data.get("fecha_asignacion") else None
            except Exception:
                item.fecha_asignacion = datetime.utcnow() if data.get("fecha_asignacion") else None
        if "fecha_devolucion" in data:
            try:
                item.fecha_devolucion = datetime.fromisoformat(str(data.get("fecha_devolucion")).replace("Z", "+00:00")) if data.get("fecha_devolucion") else None
            except Exception:
                item.fecha_devolucion = datetime.utcnow() if data.get("fecha_devolucion") else None
        if "observacion_asignacion" in data:
            item.observacion_asignacion = data.get("observacion_asignacion")
        if "observacion_devolucion" in data:
            item.observacion_devolucion = data.get("observacion_devolucion")

        db.session.commit()
        return jsonify({"message": "Equipo actualizado", "item": _serialize_bodega_equipo(item)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_equipos/<int:id_bodega_equipo>', methods=['DELETE'])
def eliminar_bodega_equipo(id_bodega_equipo):
    item = BodegaInventarioEquipo.query.get(id_bodega_equipo)
    if not item:
        return jsonify({"error": "Equipo no encontrado"}), 404
    try:
        db.session.delete(item)
        db.session.commit()
        return jsonify({"message": "Equipo eliminado"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_equipos/<int:id_bodega_equipo>/asignar_tecnico', methods=['POST'])
def asignar_bodega_equipo_tecnico(id_bodega_equipo):
    data = request.get_json() or {}
    item = BodegaInventarioEquipo.query.get(id_bodega_equipo)
    if not item:
        return jsonify({"error": "Equipo no encontrado"}), 404
    try:
        tecnico_id = data.get("tecnico_id")
        if tecnico_id in (None, "", 0, "0"):
            return jsonify({"error": "tecnico_id es obligatorio"}), 400
        try:
            tecnico_id = int(tecnico_id)
        except Exception:
            return jsonify({"error": "tecnico_id invalido"}), 400

        tecnico = User.query.get(tecnico_id)
        if not tecnico:
            return jsonify({"error": "Tecnico no encontrado"}), 404

        actual = _usuario_actual_desde_token()
        item.estado_asignacion = "asignado_tecnico"
        item.tecnico_asignado_id = tecnico.id
        item.tecnico_asignado_nombre = tecnico.name or tecnico.email
        item.asignado_por_id = getattr(actual, "id", None)
        item.asignado_por_nombre = getattr(actual, "name", None) or getattr(actual, "email", None)
        item.fecha_asignacion = datetime.utcnow()
        item.fecha_devolucion = None
        item.observacion_asignacion = data.get("observacion") or item.observacion_asignacion

        db.session.commit()
        return jsonify({"message": "Equipo asignado a tecnico", "item": _serialize_bodega_equipo(item)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@inventarios_blueprint.route('/bodega_equipos/<int:id_bodega_equipo>/devolver_bodega', methods=['POST'])
def devolver_bodega_equipo(id_bodega_equipo):
    data = request.get_json() or {}
    item = BodegaInventarioEquipo.query.get(id_bodega_equipo)
    if not item:
        return jsonify({"error": "Equipo no encontrado"}), 404
    try:
        item.estado_asignacion = "en_bodega"
        item.tecnico_asignado_id = None
        item.tecnico_asignado_nombre = None
        item.fecha_devolucion = datetime.utcnow()
        item.observacion_devolucion = data.get("observacion") or item.observacion_devolucion
        if "ubicacion" in data and str(data.get("ubicacion") or "").strip():
            item.ubicacion = str(data.get("ubicacion")).strip()

        db.session.commit()
        return jsonify({"message": "Equipo devuelto a bodega", "item": _serialize_bodega_equipo(item)}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


