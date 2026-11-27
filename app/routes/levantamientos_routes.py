import os
from pathlib import Path
from uuid import uuid4
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
from ..models import Levantamiento, Centro, db

# Crear el blueprint
levantamientos_blueprint = Blueprint('levantamientos', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf', '.ppt', '.pptx'}
MAX_DOCUMENTO_BYTES = 25 * 1024 * 1024
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/levantamientos_docs')

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def is_allowed_file(filename):
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def _guardar_documento(file):
    if not is_allowed_file(file.filename):
        raise ValueError('Adjunta un PowerPoint (.ppt o .pptx), PDF, JPG o PNG.')
    contenido = file.stream.read(MAX_DOCUMENTO_BYTES + 1)
    if not contenido or len(contenido) > MAX_DOCUMENTO_BYTES:
        raise ValueError('El documento debe tener contenido y pesar como maximo 25 MB.')
    nombre = secure_filename(file.filename)
    base, extension = os.path.splitext(nombre)
    nombre = '{}_{}{}'.format(uuid4().hex, base[:170], extension)
    ruta = Path(UPLOAD_FOLDER) / nombre
    ruta.parent.mkdir(parents=True, exist_ok=True)
    try:
        ruta.write_bytes(contenido)
    except Exception:
        ruta.unlink(missing_ok=True)
        raise
    return 'levantamientos_docs/' + nombre, ruta


def _limpiar_anterior(documento):
    if not documento or not documento.startswith('levantamientos_docs/'):
        return
    carpeta = Path(UPLOAD_FOLDER).resolve()
    ruta = (carpeta / Path(documento).name).resolve()
    if ruta.parent == carpeta:
        try:
            ruta.unlink(missing_ok=True)
        except OSError:
            # El registro ya se confirmo: un fallo de limpieza no invalida el guardado.
            pass

# Obtener todos los levantamientos o filtrar por centro_id
@levantamientos_blueprint.route('/', methods=['GET'])
def get_levantamientos():
    try:
        centro_id = request.args.get('centro_id', type=int)

        if centro_id:
            levantamientos = Levantamiento.query.filter_by(centro_id=centro_id).all()
        else:
            levantamientos = Levantamiento.query.all()

        levantamientos_data = [
            {
                "id_levantamiento": l.id_levantamiento,
                "centro_id": l.centro_id,
                "fecha_levantamiento": l.fecha_levantamiento.strftime('%Y-%m-%d'),
                "documento_asociado": l.documento_asociado,
            } for l in levantamientos
        ]
        return jsonify(levantamientos_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Crear un nuevo levantamiento
#@levantamientos_blueprint.route('/', methods=['POST'])
def crear_levantamiento_logic(data, file):
    nuevo_archivo = None
    try:
        # Validar centro_id
        centro_id = data.get('centro_id')
        if not centro_id or not Centro.query.get(centro_id):
            return {"error": "Centro no encontrado"}, 404

        # Validar fecha_levantamiento
        fecha_levantamiento = data.get('fecha_levantamiento')
        if not fecha_levantamiento:
            return {"error": "El campo 'fecha_levantamiento' es obligatorio"}, 400
        fecha_levantamiento = datetime.strptime(fecha_levantamiento, '%Y-%m-%d').date()

        # Guardar el archivo si está presente
        documento_path = None
        if file:
            documento_path, nuevo_archivo = _guardar_documento(file)

        # Crear el levantamiento
        nuevo_levantamiento = Levantamiento(
            centro_id=centro_id,
            fecha_levantamiento=fecha_levantamiento,
            documento_asociado=documento_path,
        )
        db.session.add(nuevo_levantamiento)
        db.session.commit()

        return {"message": "Levantamiento creado exitosamente", "id_levantamiento": nuevo_levantamiento.id_levantamiento}, 201
    except Exception as e:
        db.session.rollback()
        if nuevo_archivo:
            nuevo_archivo.unlink(missing_ok=True)
        return {"error": str(e)}, 400


def obtener_levantamientos_logic(centro_id=None):
    try:
        if centro_id:
            levantamientos = Levantamiento.query.filter_by(centro_id=centro_id).all()
        else:
            levantamientos = Levantamiento.query.all()

        levantamientos_data = [
            {
                "id_levantamiento": l.id_levantamiento,
                "centro_id": l.centro_id,
                "fecha_levantamiento": l.fecha_levantamiento.strftime('%Y-%m-%d'),
                "documento_asociado": l.documento_asociado,
            } for l in levantamientos
        ]
        return levantamientos_data, 200
    except Exception as e:
        return {"error": str(e)}, 400


# Descargar el documento asociado a un levantamiento
@levantamientos_blueprint.route('/<int:id_levantamiento>/documento', methods=['GET'])
def descargar_documento_levantamiento(id_levantamiento):
    try:
        levantamiento = Levantamiento.query.get_or_404(id_levantamiento)
        if not levantamiento.documento_asociado:
            return jsonify({"error": "El levantamiento no tiene un documento asociado"}), 404

        file_path = os.path.join(os.getcwd(), 'uploads', levantamiento.documento_asociado.replace('/', os.sep))
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

# Actualizar un levantamiento
#@levantamientos_blueprint.route('/<int:id_levantamiento>', methods=['PUT'])
def actualizar_levantamiento_logic(id_levantamiento, data, file):
    nuevo_archivo = None
    archivo_anterior = None
    try:
        levantamiento = db.session.get(Levantamiento, id_levantamiento)
        if not levantamiento:
            return {"error": "Levantamiento no encontrado"}, 404

        # Actualizar campos
        if data.get('centro_id'):
            centro_id = int(data.get('centro_id'))
            if not Centro.query.get(centro_id):
                return {"error": "Centro no encontrado"}, 404
            levantamiento.centro_id = centro_id

        if data.get('fecha_levantamiento'):
            levantamiento.fecha_levantamiento = datetime.strptime(data.get('fecha_levantamiento'), '%Y-%m-%d').date()

        # Reemplazar el archivo si se sube uno nuevo
        if file:
            documento_path, nuevo_archivo = _guardar_documento(file)
            archivo_anterior = levantamiento.documento_asociado
            levantamiento.documento_asociado = documento_path

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        if nuevo_archivo:
            nuevo_archivo.unlink(missing_ok=True)
        return {"error": str(e)}, 400
    if nuevo_archivo:
        _limpiar_anterior(archivo_anterior)
    return {"message": "Levantamiento actualizado exitosamente"}, 200

# Eliminar un levantamiento
#@levantamientos_blueprint.route('/<int:id_levantamiento>', methods=['DELETE'])
def eliminar_levantamiento_logic(id_levantamiento):
    try:
        levantamiento = Levantamiento.query.get_or_404(id_levantamiento)
        if levantamiento.documento_asociado:
            file_path = os.path.join(os.getcwd(), 'uploads', levantamiento.documento_asociado.replace('/', os.sep))
            if os.path.exists(file_path):
                os.remove(file_path)

        db.session.delete(levantamiento)
        db.session.commit()
        return {"message": "Levantamiento eliminado exitosamente"}, 200
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400
    
# Eliminar un levantamientos por centro
#@levantamientos_blueprint.route('/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_levantamientos_por_centro(centro_id):
    try:
        # Obtener todos los levantamientos asociados al centro_id
        levantamientos = Levantamiento.query.filter_by(centro_id=centro_id).all()

        # Eliminar los archivos asociados a cada levantamiento
        for levantamiento in levantamientos:
            if levantamiento.documento_asociado:
                file_path = os.path.join(os.getcwd(), 'uploads', levantamiento.documento_asociado.replace('/', os.sep))
                if os.path.exists(file_path):
                    os.remove(file_path)
                    print(f"Archivo eliminado: {file_path}")
                else:
                    print(f"Archivo no encontrado para eliminar: {file_path}")

        # Después de eliminar los archivos, eliminar los registros de la base de datos
        Levantamiento.query.filter_by(centro_id=centro_id).delete()
        db.session.commit()

        return jsonify({"message": "Todos los levantamientos y archivos del centro eliminados exitosamente."}), 200

    except Exception as e:
        db.session.rollback()
        print(f"Error al eliminar levantamientos: {e}")
        return jsonify({"error": str(e)}), 500
