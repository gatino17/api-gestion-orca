import os
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
from ..models import Cese, Centro, db

# Crear el blueprint
ceses_blueprint = Blueprint('ceses', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/ceses_docs')

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def is_allowed_file(filename):
    """Verifica si la extensión del archivo está permitida."""
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# Obtener todos los ceses o filtrar por centro_id
@ceses_blueprint.route('/', methods=['GET'])
def get_ceses():
    try:
        centro_id = request.args.get('centro_id', type=int)

        if centro_id:
            ceses = Cese.query.filter_by(centro_id=centro_id).all()
        else:
            ceses = Cese.query.all()

        ceses_data = [
            {
                "id_cese": cese.id_cese,
                "centro_id": cese.centro_id,
                "fecha_cese": cese.fecha_cese.strftime('%Y-%m-%d'),
                "documento_cese": cese.documento_cese
            } for cese in ceses
        ]

        return jsonify(ceses_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Crear un nuevo cese
#@ceses_blueprint.route('/', methods=['POST'])
def crear_cese_logic(data, file):
    try:
        centro_id = data.get('centro_id')
        fecha_cese = data.get('fecha_cese')

        if not centro_id or not fecha_cese:
            return {"error": "Faltan datos obligatorios"}, 400

        if not Centro.query.get(centro_id):
            return {"error": "Centro no encontrado"}, 404

        fecha_cese = datetime.strptime(fecha_cese, '%Y-%m-%d').date()
        documento_path = None

        if file and is_allowed_file(file.filename):
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            documento_path = f"ceses_docs/{filename}"
            file.save(os.path.join(UPLOAD_FOLDER, filename))

        nuevo_cese = Cese(
            centro_id=centro_id,
            fecha_cese=fecha_cese,
            documento_cese=documento_path
        )

        db.session.add(nuevo_cese)
        db.session.commit()
        return {"message": "Cese creado exitosamente", "id_cese": nuevo_cese.id_cese}, 201

    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 500

# Descargar el documento asociado a un cese
@ceses_blueprint.route('/<int:id_cese>/documento', methods=['GET'])
def descargar_documento_cese(id_cese):
    """
    Descarga el documento asociado a un cese.
    """
    try:
        # Buscar el cese en la base de datos
        cese = Cese.query.get_or_404(id_cese)
        if not cese.documento_cese:
            return jsonify({"error": "El cese no tiene un documento asociado"}), 404

        # Construir la ruta absoluta del archivo
        file_path = os.path.join(os.getcwd(), 'uploads', cese.documento_cese.replace('/', os.sep))

        print(f"Ruta almacenada en la base de datos: {cese.documento_cese}")
        print(f"Ruta absoluta generada: {file_path}")

        # Verificar si el archivo existe
        if not os.path.exists(file_path):
            print(f"Archivo no encontrado: {file_path}")
            return jsonify({"error": "El archivo no existe"}), 404

        # Servir el archivo para su descarga
        return send_file(
            file_path,
            as_attachment=True,
            download_name=os.path.basename(file_path),
            mimetype="application/octet-stream"
        )
    except Exception as e:
        print(f"Error inesperado: {e}")
        return jsonify({"error": "Error al intentar descargar el documento"}), 500

    
# Actualizar un cese
@ceses_blueprint.route('/<int:id_cese>', methods=['PUT'])
def actualizar_cese_logic(id_cese, data, file):
    """
    Actualiza un cese existente.
    """
    try:
        # Buscar el cese en la base de datos
        cese = Cese.query.get_or_404(id_cese)
        data = request.form
        file = request.files.get('documento_cese')

        # Actualizar campos
        if data.get('fecha_cese'):
            cese.fecha_cese = datetime.strptime(data.get('fecha_cese'), '%Y-%m-%d').date()
        if data.get('centro_id'):
            centro_id = int(data.get('centro_id'))
            if not Centro.query.get(centro_id):
                return jsonify({"error": "Centro no encontrado"}), 404
            cese.centro_id = centro_id

        # Reemplazar el archivo si se sube uno nuevo
        if file:
            if cese.documento_cese:
                # Eliminar el archivo existente
                existing_file_path = os.path.join(os.getcwd(), 'uploads', cese.documento_cese.replace('/', os.sep))
                if os.path.exists(existing_file_path):
                    os.remove(existing_file_path)
                    print(f"Archivo anterior eliminado: {existing_file_path}")
                else:
                    print(f"Archivo anterior no encontrado para eliminar: {existing_file_path}")

            # Guardar el nuevo archivo
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            relative_path = f"ceses_docs/{filename}"  # Ruta relativa
            absolute_path = os.path.join(os.getcwd(), 'uploads', relative_path)  # Ruta absoluta
            file.save(absolute_path)

            # Actualizar la base de datos con la ruta relativa
            cese.documento_cese = relative_path
            print(f"Nuevo archivo guardado: {absolute_path}")

        # Confirmar cambios
        db.session.commit()
        return jsonify({"message": "Cese actualizado exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error al actualizar el cese: {e}")
        return jsonify({"error": str(e)}), 400

# Eliminar un cese
@ceses_blueprint.route('/<int:id_cese>', methods=['DELETE'])
def delete_cese(id_cese):
    """
    Elimina un cese existente junto con su documento asociado.
    """
    try:
        # Buscar el cese en la base de datos
        cese = Cese.query.get_or_404(id_cese)

        # Verificar si el cese tiene un documento asociado y eliminarlo
        if cese.documento_cese:
            file_path = os.path.join(os.getcwd(), 'uploads', cese.documento_cese.replace('/', os.sep))
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Archivo eliminado: {file_path}")
            else:
                print(f"Archivo no encontrado para eliminar: {file_path}")

        # Eliminar el registro del cese de la base de datos
        db.session.delete(cese)
        db.session.commit()
        return jsonify({"message": "Cese eliminado exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error al eliminar el cese: {e}")
        return jsonify({"error": str(e)}), 400
    
# Eliminar ceses por centro 
def eliminar_ceses_por_centro(centro_id):
    try:
        # Obtener todos los ceses asociados al centro_id
        ceses = Cese.query.filter_by(centro_id=centro_id).all()

        # Eliminar los archivos asociados a cada cese
        for cese in ceses:
            if cese.documento_cese:
                file_path = os.path.join(os.getcwd(), 'uploads', cese.documento_cese.replace('/', os.sep))
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Archivo de cese eliminado: {file_path}")
                else:
                    print(f"Archivo de cese no encontrado para eliminar: {file_path}")

        # Después de eliminar los archivos, eliminar los registros de la base de datos
        Cese.query.filter_by(centro_id=centro_id).delete()
        db.session.commit()

        return jsonify({"message": "Todos los ceses y archivos del centro eliminados exitosamente."}), 200

    except Exception as e:
        db.session.rollback()
        print(f"Error al eliminar ceses: {e}")
        return jsonify({"error": str(e)}), 500
