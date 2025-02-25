import os
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
from ..models import InstalacionNueva, Centro, db

# Crear el blueprint
instalaciones_blueprint = Blueprint('instalaciones', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/instalaciones_docs')

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def is_allowed_file(filename):
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# Obtener todas las instalaciones o filtrar por centro_id
@instalaciones_blueprint.route('/', methods=['GET'])
def get_instalaciones():
    try:
        centro_id = request.args.get('centro_id', type=int)

        if centro_id:
            instalaciones = InstalacionNueva.query.filter_by(centro_id=centro_id).all()
        else:
            instalaciones = InstalacionNueva.query.all()

        instalaciones_data = [
            {
                "id_instalacion": i.id_instalacion,
                "centro_id": i.centro_id,
                "fecha_instalacion": i.fecha_instalacion.strftime('%Y-%m-%d'),
                "inicio_monitoreo": i.inicio_monitoreo.strftime('%Y-%m-%d') if i.inicio_monitoreo else None,
                "documento_acta": i.documento_acta,
                "observacion": i.observacion
            } for i in instalaciones
        ]
        return jsonify(instalaciones_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Crear una nueva instalación
#@instalaciones_blueprint.route('/', methods=['POST'])
def crear_instalacion_logic(data, file):
    try:
        # Validar centro_id
        centro_id = data.get('centro_id')
        if not centro_id or not Centro.query.get(centro_id):
            return {"error": "Centro no encontrado"}, 404

        # Validar fecha_instalacion
        fecha_instalacion = data.get('fecha_instalacion')
        if not fecha_instalacion:
            return {"error": "El campo 'fecha_instalacion' es obligatorio"}, 400
        fecha_instalacion = datetime.strptime(fecha_instalacion, '%Y-%m-%d').date()

        # Guardar el archivo si está presente
        documento_path = None
        if file and is_allowed_file(file.filename):
            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            documento_path = f"instalaciones_docs/{filename}"
            file.save(os.path.join(UPLOAD_FOLDER, filename))

        # Crear la instalación
        nueva_instalacion = InstalacionNueva(
            centro_id=centro_id,
            fecha_instalacion=fecha_instalacion,
            inicio_monitoreo=data.get('inicio_monitoreo'),
            documento_acta=documento_path,
            observacion=data.get('observacion')
        )
        db.session.add(nueva_instalacion)
        db.session.commit()

        return {"message": "Instalación creada exitosamente", "id_instalacion": nueva_instalacion.id_instalacion}, 201
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400


# Descargar el documento asociado a una instalación
#@instalaciones_blueprint.route('/<int:id_instalacion>/documento', methods=['GET'])
def descargar_documento_instalacion(id_instalacion):
    try:
        instalacion = InstalacionNueva.query.get_or_404(id_instalacion)
        if not instalacion.documento_acta:
            return jsonify({"error": "La instalación no tiene un documento asociado"}), 404

        file_path = os.path.join(os.getcwd(), 'uploads', instalacion.documento_acta.replace('/', os.sep))
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

# Actualizar una instalación
#@instalaciones_blueprint.route('/<int:id_instalacion>', methods=['PUT'])
def actualizar_instalacion_logic(id_instalacion):
    try:
        instalacion = InstalacionNueva.query.get_or_404(id_instalacion)
        data = request.form
        file = request.files.get('documento_acta')

        # Actualizar campos
        if data.get('centro_id'):
            centro_id = int(data.get('centro_id'))
            if not Centro.query.get(centro_id):
                return jsonify({"error": "Centro no encontrado"}), 404
            instalacion.centro_id = centro_id

        if data.get('fecha_instalacion'):
            instalacion.fecha_instalacion = datetime.strptime(data.get('fecha_instalacion'), '%Y-%m-%d').date()
        if data.get('inicio_monitoreo'):
            instalacion.inicio_monitoreo = datetime.strptime(data.get('inicio_monitoreo'), '%Y-%m-%d').date()
        if data.get('observacion'):
            instalacion.observacion = data.get('observacion')

        # Reemplazar el archivo si se sube uno nuevo
        if file and is_allowed_file(file.filename):
            if instalacion.documento_acta:
                existing_file_path = os.path.join(os.getcwd(), 'uploads', instalacion.documento_acta.replace('/', os.sep))
                if os.path.exists(existing_file_path):
                    os.remove(existing_file_path)

            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            relative_path = f"instalaciones_docs/{filename}"
            absolute_path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(absolute_path)
            instalacion.documento_acta = relative_path

        db.session.commit()
        return jsonify({"message": "Instalación actualizada exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Eliminar una instalación
#@instalaciones_blueprint.route('/<int:id_instalacion>', methods=['DELETE'])
def eliminar_instalacion_logic(id_instalacion):
    try:
        instalacion = InstalacionNueva.query.get_or_404(id_instalacion)
        if instalacion.documento_acta:
            file_path = os.path.join(os.getcwd(), 'uploads', instalacion.documento_acta.replace('/', os.sep))
            if os.path.exists(file_path):
                os.remove(file_path)

        db.session.delete(instalacion)
        db.session.commit()
        return jsonify({"message": "Instalación eliminada exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400

# Eliminar todas las instalaciones asociadas a un centro
#@instalaciones_blueprint.route('/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_instalaciones_por_centro(centro_id):
    try:
        instalaciones = InstalacionNueva.query.filter_by(centro_id=centro_id).all()
        
        if not instalaciones:
            return {"message": "No se encontraron instalaciones para este centro"}, 404

        for instalacion in instalaciones:
            if instalacion.documento_acta:
                file_path = os.path.join(os.getcwd(), 'uploads', instalacion.documento_acta.replace('/', os.sep))
                if os.path.exists(file_path):
                    os.remove(file_path)
            
            db.session.delete(instalacion)

        db.session.commit()
        return {"message": "Todas las instalaciones del centro eliminadas exitosamente"}, 200

    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 500
