import io
import re
import warnings
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, request, send_file
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.utils import secure_filename

from ..database import db
from ..models import Armado, ArmadoObservacionImagen
from ..permissions import get_pages_for_role_name
from ..socketio_ext import emit_armado_event


armado_observacion_blueprint = Blueprint('armado_observacion', __name__)
MAX_IMAGEN = 5 * 1024 * 1024


def _autorizar():
    from .armados_routes import usuario_actual_desde_token
    usuario = usuario_actual_desde_token()
    if not usuario:
        return jsonify(message='Debes iniciar sesion.'), 401
    if (usuario.rol or '').strip().lower() == 'tecnico' or 'armados' not in get_pages_for_role_name(usuario.rol):
        return jsonify(message='No tienes permiso para gestionar la observacion del armado.'), 403
    return None


def _directorio():
    return Path(current_app.config.get('ARMADO_OBSERVACIONES_UPLOAD_FOLDER',
                                     Path.cwd() / 'uploads' / 'armado_observaciones')).resolve()


def _ruta(nombre):
    if not re.fullmatch(r'[a-f0-9]{32}\.jpg', nombre):
        raise ValueError('Archivo invalido.')
    directorio = _directorio()
    ruta = (directorio / nombre).resolve()
    if not ruta.is_relative_to(directorio):
        raise ValueError('Archivo invalido.')
    return ruta


def limpiar_archivos_observacion(nombres):
    for nombre in nombres:
        try:
            _ruta(nombre).unlink(missing_ok=True)
        except (OSError, ValueError):
            current_app.logger.warning('No se pudo limpiar una imagen de observacion del armado.')


def _serializar(armado):
    imagenes = ArmadoObservacionImagen.query.filter_by(armado_id=armado.id_armado).order_by(ArmadoObservacionImagen.posicion).all()
    return dict(id_armado=armado.id_armado, observacion=armado.observacion or '',
                imagenes=[dict(id_imagen=i.id_imagen, posicion=i.posicion, nombre=i.nombre) for i in imagenes])


def _normalizar_imagen(file):
    if Path(file.filename).suffix.lower() not in ('.jpg', '.jpeg', '.png', '.webp'):
        raise ValueError('Adjunta imagenes JPG, PNG o WebP.')
    contenido = file.stream.read(MAX_IMAGEN + 1)
    if len(contenido) > MAX_IMAGEN:
        raise ValueError('Cada imagen puede pesar hasta 5 MB.')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(contenido)) as origen:
                if origen.format not in ('JPEG', 'PNG', 'WEBP'):
                    raise ValueError('El archivo no es una imagen JPG, PNG o WebP valida.')
                if origen.width * origen.height > 20_000_000:
                    raise ValueError('Usa una imagen de hasta 20 megapixeles.')
                origen.verify()
            with Image.open(io.BytesIO(contenido)) as origen:
                imagen = ImageOps.exif_transpose(origen)
                imagen.thumbnail((2000, 2000))
                # Normalizar y volver a codificar elimina metadatos y contenido ajeno a la imagen.
                rgba = imagen.convert('RGBA')
                fondo = Image.new('RGB', rgba.size, 'white')
                fondo.paste(rgba, mask=rgba.getchannel('A'))
                salida = io.BytesIO()
                fondo.save(salida, format='JPEG', quality=88)
                return salida.getvalue()
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('No se pudo leer la imagen. Adjunta un JPG, PNG o WebP valido.') from None


@armado_observacion_blueprint.route('/<int:armado_id>/observacion', methods=['GET', 'PUT'])
def observacion(armado_id):
    error = _autorizar()
    if error:
        return error
    query = Armado.query.filter_by(id_armado=armado_id)
    armado = (query.with_for_update() if request.method == 'PUT' else query).first_or_404()
    if request.method == 'GET':
        return jsonify(_serializar(armado))
    if request.content_length and request.content_length > 12 * 1024 * 1024:
        return jsonify(message='El adjunto es demasiado grande. Usa hasta dos imagenes de 5 MB cada una.'), 413
    nuevos, antiguos = [], []
    try:
        if request.mimetype != 'multipart/form-data':
            raise ValueError('Envia la observacion y sus imagenes como formulario.')
        if set(request.form) - {'observacion', 'eliminar_1', 'eliminar_2', 'titulo_1', 'titulo_2'} or set(request.files) - {'imagen_1', 'imagen_2'}:
            raise ValueError('Solo puedes adjuntar hasta dos imagenes a esta observacion.')
        if any(len(request.form.getlist(k)) != 1 for k in request.form) or any(len(request.files.getlist(k)) != 1 for k in request.files):
            raise ValueError('Los campos de la observacion no pueden repetirse.')
        texto = request.form.get('observacion', armado.observacion or '')
        if len(texto) > 10000:
            raise ValueError('La observacion admite hasta 10000 caracteres.')
        cambios, titulos = {}, {}
        for posicion in (1, 2):
            if f'titulo_{posicion}' in request.form:
                titulo = ' '.join(request.form[f'titulo_{posicion}'].split())
                if len(titulo) > 200:
                    raise ValueError('Cada titulo admite hasta 200 caracteres.')
                titulos[posicion] = titulo
            quitar = request.form.get(f'eliminar_{posicion}', 'false')
            if quitar not in ('true', 'false'):
                raise ValueError('Indica correctamente las imagenes que deseas quitar.')
            file = request.files.get(f'imagen_{posicion}')
            if file and file.filename:
                if quitar == 'true':
                    raise ValueError('No puedes quitar y reemplazar la misma imagen a la vez.')
                cambios[posicion] = (_normalizar_imagen(file), secure_filename(file.filename)[:200] or 'Imagen.jpg')
            elif quitar == 'true':
                cambios[posicion] = None
        guardadas = {i.posicion: i for i in armado.imagenes_observacion}
        for posicion, titulo in titulos.items():
            if posicion not in guardadas and not cambios.get(posicion) and titulo:
                raise ValueError('Adjunta la imagen antes de asignarle un titulo.')
            if posicion in guardadas and posicion not in cambios:
                guardadas[posicion].nombre = titulo or f'Imagen {posicion}'
        for posicion, contenido in cambios.items():
            imagen = guardadas.get(posicion)
            if imagen:
                antiguos.append(imagen.archivo)
            if contenido is None:
                if imagen:
                    db.session.delete(imagen)
                continue
            archivo = uuid4().hex + '.jpg'
            _directorio().mkdir(parents=True, exist_ok=True)
            nuevos.append(archivo)
            _ruta(archivo).write_bytes(contenido[0])
            if not imagen:
                imagen = ArmadoObservacionImagen(armado_id=armado_id, posicion=posicion)
                db.session.add(imagen)
            # El nombre descriptivo es editable; el archivo fisico mantiene su identificador seguro.
            imagen.archivo, imagen.nombre = archivo, titulos.get(posicion) or contenido[1]
        armado.observacion = texto
        db.session.commit()
    except ValueError as exc:
        db.session.rollback()
        limpiar_archivos_observacion(nuevos)
        return jsonify(message=str(exc)), 400
    except (OSError, SQLAlchemyError):
        db.session.rollback()
        limpiar_archivos_observacion(nuevos)
        current_app.logger.exception('No se pudo guardar la observacion del armado #%s', armado_id)
        return jsonify(message='No se pudo guardar la observacion. Los cambios anteriores se conservaron.'), 500
    limpiar_archivos_observacion(antiguos)
    try:
        emit_armado_event('armado_updated', {'armado_id': armado_id, 'tipo': 'observacion'})
    except Exception:
        current_app.logger.warning('Observacion guardada; no se pudo emitir la actualizacion en tiempo real.')
    return jsonify(_serializar(armado))


@armado_observacion_blueprint.route('/<int:armado_id>/observacion/imagenes/<int:imagen_id>', methods=['GET'])
def imagen_observacion(armado_id, imagen_id):
    error = _autorizar()
    if error:
        return error
    imagen = ArmadoObservacionImagen.query.filter_by(armado_id=armado_id, id_imagen=imagen_id).first_or_404()
    try:
        ruta = _ruta(imagen.archivo)
    except ValueError:
        return jsonify(message='Imagen no disponible.'), 404
    if not ruta.is_file():
        return jsonify(message='Imagen no disponible.'), 404
    response = send_file(ruta, mimetype='image/jpeg', download_name='observacion.jpg', etag=False, max_age=0)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response
