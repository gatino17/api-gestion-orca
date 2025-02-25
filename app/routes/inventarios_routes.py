import os
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
from ..models import Inventario, Centro, db

# Crear el blueprint
inventarios_blueprint = Blueprint('inventarios', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/inventarios_docs')

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

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


