from flask import has_request_context, request

from .models import Armado, ArmadoObservacionImagen, db
from .permissions import get_pages_for_role_name


def puede_consultar_respaldos():
    if not has_request_context() or not request.headers.get('Authorization', '').startswith('Bearer '):
        return False
    from .routes.armados_routes import usuario_actual_desde_token
    usuario = usuario_actual_desde_token()
    return bool(usuario and {'armados', 'registrosdocumentos', 'consulta_centro'}
                .intersection(get_pages_for_role_name(usuario.rol)))


def respaldos_por_centro(centro_ids=None):
    if not puede_consultar_respaldos():
        return {}
    query = db.session.query(ArmadoObservacionImagen, Armado).join(Armado)
    if centro_ids is not None:
        ids = list(set(centro_ids))
        if not ids:
            return {}
        query = query.filter(Armado.centro_id.in_(ids))
    resultado = {}
    for adjunto, armado in query.order_by(Armado.id_armado.desc(), ArmadoObservacionImagen.posicion).all():
        resultado.setdefault(armado.centro_id, []).append({
            'origen': 'armado', 'solo_lectura': True,
            'historial_key': 'armado-respaldo-{}'.format(adjunto.id_imagen),
            'id_respaldo_armado': adjunto.id_imagen, 'id_armado': armado.id_armado,
            'centro_id': armado.centro_id, 'nombre': adjunto.nombre,
            'tipo_documento': 'pdf' if adjunto.archivo.endswith('.pdf') else 'imagen',
            # Es la fecha de referencia del armado, no una fecha de carga inventada.
            'fecha_levantamiento': armado.fecha_asignacion,
            'fecha_armado': armado.fecha_asignacion,
            'documento': '/api/actas/levantamientos/armado/{}/documento'.format(adjunto.id_imagen),
        })
    return resultado
