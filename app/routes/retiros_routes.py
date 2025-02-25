import os
from flask import Blueprint, request, jsonify, send_file
from flask import current_app
from datetime import datetime
from werkzeug.utils import secure_filename
from ..models import Retiro, Centro, db

# Crear el blueprint
retiros_blueprint = Blueprint('retiros', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/retiros_img')

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def is_allowed_file(filename):
    """Verifica si la extensión del archivo está permitida."""
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# Obtener todos los retiros o filtrar por centro_id
@retiros_blueprint.route('/', methods=['GET'])
def get_retiros():
    try:
        centro_id = request.args.get('centro_id', type=int)

        if centro_id:
            retiros = Retiro.query.filter_by(centro_id=centro_id).all()
        else:
            retiros = Retiro.query.all()

        retiros_data = [
            {
                "id_retiro": retiro.id_retiro,
                "centro_id": retiro.centro_id,
                "fecha_de_retiro": retiro.fecha_de_retiro.strftime('%Y-%m-%d'),
                "observacion": retiro.observacion,
                "precio": str(retiro.precio) if retiro.precio else None,
                "documento": retiro.documento  # Ruta del archivo
            } for retiro in retiros
        ]

        return jsonify(retiros_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Crear un nuevo retiro
@retiros_blueprint.route('/', methods=['POST'])
def create_retiro():
    try:
        data = request.form
        file = request.files.get('documento')

        # Validar centro_id
        centro_id = data.get('centro_id')
        if not centro_id or not Centro.query.get(centro_id):
            return jsonify({"error": "Centro no encontrado"}), 404

        # Validar fecha_de_retiro
        fecha_de_retiro = data.get('fecha_de_retiro')
        if not fecha_de_retiro:
            return jsonify({"error": "El campo 'fecha_de_retiro' es obligatorio"}), 400
        try:
            fecha_de_retiro = datetime.strptime(fecha_de_retiro, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({"error": "El formato de fecha debe ser YYYY-MM-DD"}), 400

        # Validar precio
        precio = data.get('precio')
        try:
            precio = float(precio) if precio else None
        except ValueError:
            return jsonify({"error": "El campo 'precio' debe ser un número válido"}), 400

        # Guardar el archivo si está presente
        documento_path = None
        if file:
            if not is_allowed_file(file.filename):
                return jsonify({"error": "El archivo debe ser una imagen (.png, .jpg, .jpeg) o un PDF (.pdf)"}), 400

            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            documento_path = f"retiros_img/{filename}"  # Ruta relativa
            file.save(os.path.join(UPLOAD_FOLDER, filename))  # Ruta absoluta

        # Crear el retiro
        nuevo_retiro = Retiro(
            centro_id=centro_id,
            documento=documento_path,
            fecha_de_retiro=fecha_de_retiro,
            observacion=data.get('observacion'),
            precio=precio
        )
        db.session.add(nuevo_retiro)
        db.session.commit()

        return jsonify({"message": "Retiro creado exitosamente", "id_retiro": nuevo_retiro.id_retiro}), 201
    except Exception as e:
        db.session.rollback()
        print(f"Error al crear retiro: {e}")
        return jsonify({"error": str(e)}), 400


# Descargar el documento asociado a un retiro
@retiros_blueprint.route('/<int:id_retiro>/documento', methods=['GET'])
def descargar_documento(id_retiro):
    """
    Descarga el documento asociado a un retiro.
    """
    try:
        # Buscar el retiro en la base de datos
        retiro = Retiro.query.get_or_404(id_retiro)
        if not retiro.documento:
            print("Documento no asociado en la base de datos.")
            return jsonify({"error": "El retiro no tiene un documento asociado"}), 404

        # Ruta base explícita para 'uploads'
        base_uploads_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'uploads')
        file_path = os.path.abspath(os.path.join(base_uploads_dir, retiro.documento.replace('/', os.sep)))

        print(f"Ruta almacenada en la base de datos: {retiro.documento}")
        print(f"Ruta absoluta generada: {file_path}")

        # Verificar si el archivo existe
        if not os.path.exists(file_path):
            print(f"El archivo no existe: {file_path}")
            if os.path.exists(os.path.dirname(file_path)):
                print("Archivos disponibles en el directorio:")
                print(os.listdir(os.path.dirname(file_path)))
            else:
                print(f"El directorio {os.path.dirname(file_path)} no existe.")
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
        return jsonify({"error": "Error interno al intentar descargar el documento"}), 500



@retiros_blueprint.route('/test_download', methods=['GET'])
def test_download():
    file_path = os.path.join(os.getcwd(), 'uploads/retiros_img/20241201120000_documento.pdf')
    return send_file(file_path, as_attachment=True)


# Actualizar un retiro
#@retiros_blueprint.route('/<int:id_retiro>', methods=['PUT'])
def update_retiro(id_retiro):
    """
    Actualiza un retiro existente.
    """
    try:
        # Buscar el retiro en la base de datos
        retiro = Retiro.query.get_or_404(id_retiro)
        data = request.form
        file = request.files.get('documento')

        # Actualizar campos
        if data.get('fecha_de_retiro'):
            retiro.fecha_de_retiro = datetime.strptime(data.get('fecha_de_retiro'), '%Y-%m-%d').date()
        if data.get('observacion'):
            retiro.observacion = data.get('observacion')
        if data.get('precio'):
            retiro.precio = float(data.get('precio'))

        # Reemplazar el archivo si se sube uno nuevo
        if file:
            if retiro.documento:
                # Eliminar el archivo existente
                existing_file_path = os.path.join(os.getcwd(), retiro.documento.replace('/', os.sep))
                if os.path.exists(existing_file_path):
                    os.remove(existing_file_path)

            # Guardar el nuevo archivo
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            relative_path = f"retiros_img/{filename}"  # Ruta relativa
            absolute_path = os.path.join(UPLOAD_FOLDER, filename)  # Ruta absoluta
            file.save(absolute_path)

            # Actualizar la base de datos con la ruta relativa
            retiro.documento = relative_path

        # Confirmar cambios
        db.session.commit()
        return jsonify({"message": "Retiro actualizado exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error al actualizar el retiro: {e}")
        return jsonify({"error": str(e)}), 400

def crear_retiro_logic(data, file):
    try:
        # Validar centro_id
        centro_id = data.get('centro_id')
        if not centro_id or not Centro.query.get(centro_id):
            return {"error": "Centro no encontrado"}, 404

        # Validar fecha_de_retiro
        fecha_de_retiro = data.get('fecha_de_retiro')
        if not fecha_de_retiro:
            return {"error": "El campo 'fecha_de_retiro' es obligatorio"}, 400
        try:
            fecha_de_retiro = datetime.strptime(fecha_de_retiro, '%Y-%m-%d').date()
        except ValueError:
            return {"error": "El formato de fecha debe ser YYYY-MM-DD"}, 400

        # Validar precio
        precio = data.get('precio')
        try:
            precio = float(precio) if precio else None
        except ValueError:
            return {"error": "El campo 'precio' debe ser un número válido"}, 400

        # Guardar el archivo si está presente
        documento_path = None
        if file and is_allowed_file(file.filename):
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            documento_path = f"retiros_img/{filename}"  # Ruta relativa
            file.save(os.path.join(UPLOAD_FOLDER, filename))  # Ruta absoluta
        elif file and not is_allowed_file(file.filename):
            return {"error": "El archivo debe ser .png, .jpg, .jpeg o .pdf"}, 400

        # Crear el retiro
        nuevo_retiro = Retiro(
            centro_id=centro_id,
            documento=documento_path,
            fecha_de_retiro=fecha_de_retiro,
            observacion=data.get('observacion'),
            precio=precio
        )
        db.session.add(nuevo_retiro)
        db.session.commit()

        return {"message": "Retiro creado exitosamente", "id_retiro": nuevo_retiro.id_retiro}, 201

    except Exception as e:
        db.session.rollback()
        print(f"Error al crear retiro: {e}")
        return {"error": str(e)}, 400


# Eliminar un retiro
# Eliminar un retiro
@retiros_blueprint.route('/<int:id_retiro>', methods=['DELETE'])
def delete_retiro(id_retiro):
    try:
        # Buscar el retiro en la base de datos
        retiro = Retiro.query.get_or_404(id_retiro)
        if retiro.documento:
            # Construir la ruta absoluta del archivo
            base_uploads_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'uploads')
            file_path = os.path.abspath(os.path.join(base_uploads_dir, retiro.documento.replace('/', os.sep)))

            # Verificar si el archivo existe y eliminarlo
            if os.path.exists(file_path):
                os.remove(file_path)
                print(f"Archivo eliminado: {file_path}")
            else:
                print(f"El archivo no existe: {file_path}")

        # Eliminar el retiro de la base de datos
        db.session.delete(retiro)
        db.session.commit()
        return jsonify({"message": "Retiro eliminado exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error al eliminar retiro: {e}")
        return jsonify({"error": str(e)}), 400
    

# Eliminar retiro por centro   
def eliminar_retiros_por_centro(centro_id):
    try:
        retiros = Retiro.query.filter_by(centro_id=centro_id).all()
        
        for retiro in retiros:
            if retiro.documento:
                file_path = os.path.join(os.getcwd(), 'uploads', retiro.documento.replace('/', os.sep))
                if os.path.exists(file_path):
                    os.remove(file_path)
        
        # Eliminar los retiros de la base de datos
        Retiro.query.filter_by(centro_id=centro_id).delete()
        db.session.commit()
        
        return jsonify({"message": "Todos los retiros del centro eliminados exitosamente."}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


