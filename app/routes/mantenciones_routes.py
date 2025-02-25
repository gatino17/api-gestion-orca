import os
import  mimetypes 
from flask import Response

from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
from ..models import Mantencion, Centro, db

# Crear el blueprint
mantenciones_blueprint = Blueprint('mantenciones', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/mantenciones_docs')

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def is_allowed_file(filename):
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# Obtener todas las mantenciones o filtrar por centro_id
#@mantenciones_blueprint.route('/', methods=['GET'])
def obtener_mantenciones_por_centro(centro_id):
    """Obtiene todas las mantenciones filtradas por centro_id."""
    try:
        mantenciones = Mantencion.query.filter_by(centro_id=centro_id).all()
        mantenciones_data = [
            {
                "id_mantencion": m.id_mantencion,
                "centro_id": m.centro_id,
                "fecha_mantencion": m.fecha_mantencion.strftime('%Y-%m-%d'),
                "responsable": m.responsable,
                "documento_mantencion": m.documento_mantencion,
                "observacion": m.observacion
            } for m in mantenciones
        ]
        return mantenciones_data, 200
    except Exception as e:
        return {"error": str(e)}, 400

# Crear una nueva mantención
#@mantenciones_blueprint.route('/', methods=['POST'])
def crear_mantencion_logic(data, file):
    """Crea una mantención y la guarda en la base de datos."""
    try:
        centro_id = data.get('centro_id')
        if not centro_id or not Centro.query.get(centro_id):
            return {"error": "Centro no encontrado"}, 404

        fecha_mantencion = data.get('fecha_mantencion')
        if not fecha_mantencion:
            return {"error": "El campo 'fecha_mantencion' es obligatorio"}, 400
        fecha_mantencion = datetime.strptime(fecha_mantencion, '%Y-%m-%d').date()

        documento_path = None
        if file and is_allowed_file(file.filename):
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            documento_path = f"mantenciones_docs/{filename}"
            file.save(os.path.join(UPLOAD_FOLDER, filename))

        nueva_mantencion = Mantencion(
            centro_id=centro_id,
            fecha_mantencion=fecha_mantencion,
            responsable=data.get('responsable'),
            documento_mantencion=documento_path,
            observacion=data.get('observacion')
        )
        db.session.add(nueva_mantencion)
        db.session.commit()
        return {"message": "Mantención creada exitosamente", "id_mantencion": nueva_mantencion.id_mantencion}, 201
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400

# Descargar el documento asociado a una mantención
#@mantenciones_blueprint.route('/<int:id_mantencion>/documento', methods=['GET'])
def descargar_documento_mantencion(id_mantencion):
    try:
        mantencion = Mantencion.query.get_or_404(id_mantencion)
        if not mantencion.documento_mantencion:
            return jsonify({"error": "La mantención no tiene un documento asociado"}), 404

        # Ruta absoluta del archivo
        file_path = os.path.join(os.getcwd(), 'uploads', mantencion.documento_mantencion.replace('/', os.sep))
        
        if not os.path.exists(file_path):
            return jsonify({"error": "El archivo no existe"}), 404

        # Determinar el tipo de archivo
        mimetype = "application/octet-stream"
        if file_path.endswith(".pdf"):
            mimetype = "application/pdf"
        elif file_path.endswith(".jpg") or file_path.endswith(".jpeg"):
            mimetype = "image/jpeg"
        elif file_path.endswith(".png"):
            mimetype = "image/png"

        with open(file_path, "rb") as file:
            file_content = file.read()

        response = Response(file_content, content_type=mimetype)
        response.headers["Content-Disposition"] = f"inline; filename={os.path.basename(file_path)}"
        return response

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Actualizar una mantención
#@mantenciones_blueprint.route('/<int:id_mantencion>', methods=['PUT'])
def update_mantencion(id_mantencion):
    try:
        mantencion = Mantencion.query.get_or_404(id_mantencion)
        data = request.form
        file = request.files.get('documento_mantencion')

        # Actualizar campos
        if data.get('centro_id'):
            centro_id = int(data.get('centro_id'))
            if not Centro.query.get(centro_id):
                return jsonify({"error": "Centro no encontrado"}), 404
            mantencion.centro_id = centro_id

        if data.get('fecha_mantencion'):
            mantencion.fecha_mantencion = datetime.strptime(data.get('fecha_mantencion'), '%Y-%m-%d').date()
        if data.get('responsable'):
            mantencion.responsable = data.get('responsable')
        if data.get('observacion'):
            mantencion.observacion = data.get('observacion')

        # Reemplazar el archivo si se sube uno nuevo
        if file and is_allowed_file(file.filename):
            if mantencion.documento_mantencion:
                existing_file_path = os.path.join(os.getcwd(), 'uploads', mantencion.documento_mantencion.replace('/', os.sep))
                if os.path.exists(existing_file_path):
                    os.remove(existing_file_path)

            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            relative_path = f"mantenciones_docs/{filename}"
            absolute_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(absolute_path)
            mantencion.documento_mantencion = relative_path

        db.session.commit()
        return jsonify({"message": "Mantención actualizada exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Eliminar una mantención
#@mantenciones_blueprint.route('/<int:id_mantencion>', methods=['DELETE'])
def eliminar_mantencion_por_id(id_mantencion):
    try:
        mantencion = Mantencion.query.get_or_404(id_mantencion)
        if mantencion.documento_mantencion:
            file_path = os.path.join(os.getcwd(), 'uploads', mantencion.documento_mantencion.replace('/', os.sep))
            if os.path.exists(file_path):
                os.remove(file_path)

        db.session.delete(mantencion)
        db.session.commit()
        return jsonify({"message": "Mantención eliminada exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    
  # Eliminar  mantención  por centro
def eliminar_mantenciones_por_centro(centro_id):
    """Elimina todas las mantenciones asociadas a un centro."""
    try:
        mantenciones = Mantencion.query.filter_by(centro_id=centro_id).all()
        for mantencion in mantenciones:
            if mantencion.documento_mantencion:
                file_path = os.path.join(os.getcwd(), 'uploads', mantencion.documento_mantencion.replace('/', os.sep))
                if os.path.exists(file_path):
                    os.remove(file_path)
            db.session.delete(mantencion)

        db.session.commit()
        return {"message": "Mantenciones eliminadas exitosamente"}, 200
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400
