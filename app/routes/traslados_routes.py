import os
from flask import Blueprint, request, jsonify, send_file
from datetime import datetime
from werkzeug.utils import secure_filename
from ..models import Traslado, Centro, db

# Crear el blueprint
traslados_blueprint = Blueprint('traslados', __name__)

# Configuración para archivos
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.pdf'}
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'uploads/traslados_docs')

# Crear el directorio de uploads si no existe
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

def is_allowed_file(filename):
    """Verifica si la extensión del archivo está permitida."""
    return '.' in filename and os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS

# Obtener todos los traslados o filtrar por centro_id
@traslados_blueprint.route('/', methods=['GET'])
def get_traslados():
    try:
        traslados = Traslado.query.all()
        traslados_data = [
            {
                "id_traslado": traslado.id_traslado,
                "centro_origen_id": traslado.centro_origen_id,
                "centro_destino_id": traslado.centro_destino_id,
                "fecha_traslado": traslado.fecha_traslado.strftime('%Y-%m-%d'),
                "fecha_monitoreo": traslado.fecha_monitoreo.strftime('%Y-%m-%d') if traslado.fecha_monitoreo else None,
                "documento_asociado": traslado.documento_asociado,
                "tipo_traslado": traslado.tipo_traslado,
                "observacion": traslado.observacion
            } for traslado in traslados
        ]
        return jsonify(traslados_data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# Crear un nuevo traslado
#@traslados_blueprint.route('/', methods=['POST'])
def crear_traslado_logic(data, file):
    try:
        # Validar campos obligatorios
        centro_origen_id = data.get('centro_origen_id')
        centro_destino_id = data.get('centro_destino_id')
        fecha_traslado = data.get('fecha_traslado')

        if not centro_origen_id or not Centro.query.get(centro_origen_id):
            return {"error": "Centro de origen no encontrado"}, 404
        if not centro_destino_id or not Centro.query.get(centro_destino_id):
            return {"error": "Centro de destino no encontrado"}, 404
        if not fecha_traslado:
            return {"error": "El campo 'fecha_traslado' es obligatorio"}, 400
        fecha_traslado = datetime.strptime(fecha_traslado, '%Y-%m-%d').date()

        # Guardar el archivo si está presente
        documento_path = None
        if file:
            if not is_allowed_file(file.filename):
                return {"error": "El archivo debe ser una imagen (.png, .jpg, .jpeg) o un PDF (.pdf)"}, 400

            filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
            documento_path = f"traslados_docs/{filename}"
            file.save(os.path.join(UPLOAD_FOLDER, filename))

        # Crear el traslado
        nuevo_traslado = Traslado(
            centro_origen_id=centro_origen_id,
            centro_destino_id=centro_destino_id,
            fecha_traslado=fecha_traslado,
            fecha_monitoreo=data.get('fecha_monitoreo'),
            documento_asociado=documento_path,
            tipo_traslado=data.get('tipo_traslado'),
            observacion=data.get('observacion')
        )
        db.session.add(nuevo_traslado)
        db.session.commit()

        return {"message": "Traslado creado exitosamente", "id_traslado": nuevo_traslado.id_traslado}, 201
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 400


# Eliminar un traslado
@traslados_blueprint.route('/<int:id_traslado>', methods=['DELETE'])
def delete_traslado(id_traslado):
    try:
        traslado = Traslado.query.get_or_404(id_traslado)
        if traslado.documento_asociado:
            file_path = os.path.join(os.getcwd(), 'uploads', traslado.documento_asociado.replace('/', os.sep))
            if os.path.exists(file_path):
                os.remove(file_path)
        db.session.delete(traslado)
        db.session.commit()
        return jsonify({"message": "Traslado eliminado exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    
    # Actualizar un traslado
@traslados_blueprint.route('/<int:id_traslado>', methods=['PUT'])
def update_traslado(id_traslado):
    try:
        traslado = Traslado.query.get_or_404(id_traslado)
        data = request.form
        file = request.files.get('documento_asociado')

        # Actualizar campos obligatorios
        if data.get('centro_origen_id'):
            centro_origen_id = int(data.get('centro_origen_id'))
            if not Centro.query.get(centro_origen_id):
                return jsonify({"error": "Centro de origen no encontrado"}), 404
            traslado.centro_origen_id = centro_origen_id

        if data.get('centro_destino_id'):
            centro_destino_id = int(data.get('centro_destino_id'))
            if not Centro.query.get(centro_destino_id):
                return jsonify({"error": "Centro de destino no encontrado"}), 404
            traslado.centro_destino_id = centro_destino_id

        if data.get('fecha_traslado'):
            traslado.fecha_traslado = datetime.strptime(data.get('fecha_traslado'), '%Y-%m-%d').date()

        if data.get('fecha_monitoreo'):
            traslado.fecha_monitoreo = datetime.strptime(data.get('fecha_monitoreo'), '%Y-%m-%d').date()
        else:
            traslado.fecha_monitoreo = None

        if data.get('tipo_traslado'):
            traslado.tipo_traslado = data.get('tipo_traslado')

        if data.get('observacion'):
            traslado.observacion = data.get('observacion')

        # Manejar el archivo asociado
        if file:
            # Eliminar el archivo anterior si existe
            if traslado.documento_asociado:
                existing_file_path = os.path.join(os.getcwd(), 'uploads', traslado.documento_asociado.replace('/', os.sep))
                if os.path.exists(existing_file_path):
                    os.remove(existing_file_path)

            # Guardar el nuevo archivo
            if is_allowed_file(file.filename):
                filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(file.filename)}"
                documento_path = f"traslados_docs/{filename}"
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                traslado.documento_asociado = documento_path
            else:
                return jsonify({"error": "El archivo debe ser una imagen (.png, .jpg, .jpeg) o un PDF (.pdf)"}), 400

        # Confirmar los cambios
        db.session.commit()
        return jsonify({"message": "Traslado actualizado exitosamente"}), 200
    except Exception as e:
        db.session.rollback()
        print(f"Error al actualizar traslado: {e}")
        return jsonify({"error": str(e)}), 400

def eliminar_traslados_por_centro(centro_id):
    try:
        traslados = Traslado.query.filter_by(centro_origen_id=centro_id).all()
        if not traslados:
            return {"message": "No se encontraron traslados para este centro"}, 404

        for traslado in traslados:
            if traslado.documento_asociado:
                file_path = os.path.join(os.getcwd(), 'uploads', traslado.documento_asociado.replace('/', os.sep))
                if os.path.exists(file_path):
                    os.remove(file_path)
            db.session.delete(traslado)

        db.session.commit()
        return {"message": "Todos los traslados del centro eliminados exitosamente"}, 200
    except Exception as e:
        db.session.rollback()
        return {"error": str(e)}, 500
