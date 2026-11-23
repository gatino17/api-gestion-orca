import jwt
from flask import Blueprint, jsonify, request
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from ..database import db
from ..models import Actividad, Centro, Mantencion, MantencionTerreno, Soporte, SoporteDocumentoMantencion, User
from ..mantencion_intervenciones import intervenciones_por_centro
from ..permissions import get_pages_for_role_name
from .auth_routes import SECRET_KEY

mantencion_intervenciones_bp = Blueprint('mantencion_intervenciones', __name__)


def _autorizar():
    try:
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return None
        payload = jwt.decode(auth[7:], SECRET_KEY, algorithms=['HS256'])
        return db.session.get(User, payload.get('user_id'))
    except (jwt.InvalidTokenError, TypeError, ValueError):
        return None


def autorizar_documentos():
    usuario = _autorizar()
    if not usuario:
        return None, ({'error': 'Sesion invalida o expirada.'}, 401)
    if not {'registrosdocumentos', 'soporte', 'informes_centros'}.intersection(get_pages_for_role_name(usuario.rol)):
        return None, ({'error': 'No tienes permiso para vincular documentos.'}, 403)
    return usuario, None


@mantencion_intervenciones_bp.route('/centros/<int:centro_id>', methods=['GET'])
def listar(centro_id):
    if not db.session.get(Centro, centro_id):
        return jsonify({'error': 'Centro no encontrado.'}), 404
    return jsonify(intervenciones_por_centro([centro_id])[centro_id])


@mantencion_intervenciones_bp.route('/soportes/<int:soporte_id>/documentos', methods=['POST'])
@mantencion_intervenciones_bp.route('/soportes/<int:soporte_id>/documentos/<int:vinculo_id>', methods=['DELETE'])
def vincular(soporte_id, vinculo_id=None):
    usuario, error = autorizar_documentos()
    if error:
        return jsonify(error[0]), error[1]
    try:
        soporte = Soporte.query.filter_by(id_soporte=soporte_id).with_for_update().first()
        if not soporte:
            return jsonify({'error': 'Soporte no encontrado.'}), 404
        if request.method == 'POST' and (soporte.tipo or '').strip().lower() != 'terreno':
            return jsonify({'error': 'Solo se pueden vincular documentos a soportes de terreno.'}), 400
        if request.method == 'DELETE':
            vinculo = SoporteDocumentoMantencion.query.filter_by(id=vinculo_id, soporte_id=soporte_id).first()
            if not vinculo:
                return jsonify({'error': 'Vinculo no encontrado.'}), 404
            db.session.delete(vinculo)
        else:
            data = request.get_json(silent=True)
            if not isinstance(data, dict) or set(data) != {'tipo', 'documento_id'}:
                return jsonify({'error': 'Indica tipo y documento_id.'}), 400
            tipo, did = data['tipo'], data['documento_id']
            if tipo not in ('manual', 'sistema') or type(did) is not int or did <= 0:
                return jsonify({'error': 'Documento invalido.'}), 400
            model, campo = (Mantencion, 'mantencion_id') if tipo == 'manual' else (MantencionTerreno, 'mantencion_terreno_id')
            pk = model.id_mantencion if tipo == 'manual' else model.id_mantencion_terreno
            doc = model.query.filter(pk == did).with_for_update().first()
            if not doc or doc.centro_id != soporte.centro_id:
                return jsonify({'error': 'El documento debe pertenecer al mismo centro del soporte.'}), 400
            if tipo == 'sistema' and doc.actividad_id:
                actividad = db.session.get(Actividad, doc.actividad_id)
                if actividad and actividad.soporte_id and actividad.soporte_id != soporte_id:
                    return jsonify({'error': 'El informe ya corresponde a otro soporte por su actividad.'}), 409
                if actividad and actividad.soporte_id == soporte_id and actividad.centro_id == doc.centro_id:
                    return jsonify({'message': 'El informe ya esta vinculado por su actividad.'}), 200
            anterior = SoporteDocumentoMantencion.query.filter_by(**{campo: did}).first()
            if anterior:
                if anterior.soporte_id != soporte_id:
                    return jsonify({'error': 'El documento ya esta asociado a otra intervencion.'}), 409
                return jsonify({'message': 'El documento ya estaba asociado.'}), 200
            db.session.add(SoporteDocumentoMantencion(soporte_id=soporte_id, creado_por_id=usuario.id, **{campo: did}))
        db.session.commit()
        return jsonify({'message': 'Vinculo actualizado.'})
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'El documento ya fue vinculado. Actualiza el listado.'}), 409
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify({'error': 'No se pudo guardar el vinculo.'}), 500
