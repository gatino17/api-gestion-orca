import os
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
from ..models import ServiciosAdicionales, RazonSocial, db

# Crear el blueprint
servicios_blueprint = Blueprint('servicios_adicionales', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/servicios_docs')

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def is_allowed_file(filename):
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# Obtener todos los servicios adicionales o filtrar por id_razon_social
@servicios_blueprint.route('/', methods=['GET'])
def get_servicios():
    try:
        id_razon_social = request.args.get('id_razon_social', type=int)

        if id_razon_social:
            servicios = ServiciosAdicionales.query.filter_by(id_razon_social=id_razon_social).all()
        else:
            servicios = ServiciosAdicionales.query.all()

        servicios_data = [
            {
                "id_servicio": s.id_servicio,
                "id_razon_social": s.id_razon_social,
                "fecha_instalacion": s.fecha_instalacion.strftime('%Y-%m-%d'),
                "documento_asociado": s.documento_asociado,
                "observaciones": s.observaciones
            } for s in servicios
        ]
        return jsonify(servicios_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Crear un nuevo servicio adicional
@servicios_blueprint.route('/', methods=['POST'])
def create_servicio():
    try:
        data = request.form
        file = request.files.get('documento_asociado')

        # Validar id_razon_social
        id_razon_social = data.get('id_razon_social')
        if not id_razon_social or not RazonSocial.query.get(id_razon_social):
            return jsonify({"error": "Razón social no encontrada"}), 404

        # Validar fecha_instalacion
        fecha_instalacion = data.get('fecha_instalacion')
        if not fecha_instalacion:
            return jsonify({"error": "El campo 'fecha_instalacion' es obligatorio"}), 400
        fecha_instalacion = datetime.strptime(fecha_instalacion, '%Y-%m-%d').date()

        
        # Guardar el archivo si está presente
        documento_path = None
        if file and is_allowed_file(file.filename):
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            documento_path = f"servicios_docs/{filename}"
            file.save(os.path.join(UPLOAD_FOLDER, filename))

        # Crear el servicio adicional
        nuevo_servicio = ServiciosAdicionales(
            id_razon_social=id_razon_social,
            fecha_instalacion=fecha_instalacion,
            documento_asociado=documento_path,
            observaciones=data.get('observaciones')
        )
        db.session.add(nuevo_servicio)
        db.session.commit()

        return jsonify({"message": "Servicio adicional creado exitosamente", "id_servicio": nuevo_servicio.id_servicio}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Descargar el documento asociado a un servicio adicional
@servicios_blueprint.route('/<int:id_servicio>/documento', methods=['GET'])
def descargar_documento_servicio(id_servicio):
    try:
        servicio = ServiciosAdicionales.query.get_or_404(id_servicio)
        if not servicio.documento_asociado:
            return jsonify({"error": "El servicio no tiene un documento asociado"}), 404

        file_path = os.path.join(os.getcwd(), 'uploads', servicio.documento_asociado.replace('/', os.sep))
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

# Actualizar un servicio adicional
@servicios_blueprint.route('/<int:id_servicio>', methods=['PUT'])
def update_servicio(id_servicio):
    try:
        servicio = ServiciosAdicionales.query.get_or_404(id_servicio)
        data = request.form
        file = request.files.get('documento_asociado')

        # Actualizar campos
        if data.get('id_razon_social'):
            id_razon_social = int(data.get('id_razon_social'))
            if not RazonSocial.query.get(id_razon_social):
                return jsonify({"error": "Razón social no encontrada"}), 404
            servicio.id_razon_social = id_razon_social

        if data.get('fecha_instalacion'):
            try:
                servicio.fecha_instalacion = datetime.strptime(data.get('fecha_instalacion'), '%Y-%m-%d').date()
            except ValueError:
                return jsonify({"error": "Formato incorrecto en 'fecha_instalacion'. Formato esperado: YYYY-MM-DD"}), 400

        
        # Observaciones no requiere formato especial, solo asegurarse que no es None
        if 'observaciones' in data:
            servicio.observaciones = data.get('observaciones') or None

        # Reemplazar el archivo si se sube uno nuevo
        if file and is_allowed_file(file.filename):
            if servicio.documento_asociado:
                existing_file_path = os.path.join(os.getcwd(), 'uploads', servicio.documento_asociado.replace('/', os.sep))
                if os.path.exists(existing_file_path):
                    os.remove(existing_file_path)

            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            relative_path = f"servicios_docs/{filename}"
            absolute_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(absolute_path)
            servicio.documento_asociado = relative_path

        db.session.commit()
        return jsonify({"message": "Servicio adicional actualizado exitosamente"}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400


# Eliminar un servicio adicional
@servicios_blueprint.route('/<int:id_servicio>', methods=['DELETE'])
def delete_servicio(id_servicio):
    try:
        servicio = ServiciosAdicionales.query.get_or_404(id_servicio)
        if servicio.documento_asociado:
            file_path = os.path.join(os.getcwd(), 'uploads', servicio.documento_asociado.replace('/', os.sep))
            if os.path.exists(file_path):
                os.remove(file_path)

        db.session.delete(servicio)
        db.session.commit()
        return jsonify({"message": "Servicio adicional eliminado exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
