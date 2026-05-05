import os
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from decimal import Decimal
from werkzeug.utils import secure_filename
from ..models import Inventario, Centro, BodegaInventarioEquipo, db

# Crear el blueprint
inventarios_blueprint = Blueprint('inventarios', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/inventarios_docs')

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
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }

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

            existe_codigo = BodegaInventarioEquipo.query.filter(db.func.lower(BodegaInventarioEquipo.codigo) == codigo.lower()).first()
            if existe_codigo:
                return jsonify({"error": f"El código ya existe: {codigo}"}), 400

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
            item.numero_serie = serie

        if "codigo" in data:
            codigo = str(data.get("codigo") or "").strip()
            if not codigo:
                return jsonify({"error": "codigo es obligatorio"}), 400
            dup = BodegaInventarioEquipo.query.filter(
                db.func.lower(BodegaInventarioEquipo.codigo) == codigo.lower(),
                BodegaInventarioEquipo.id_bodega_equipo != item.id_bodega_equipo
            ).first()
            if dup:
                return jsonify({"error": f"El código ya existe: {codigo}"}), 400
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


