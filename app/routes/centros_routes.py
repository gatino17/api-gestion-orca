from datetime import datetime, date
from flask import Blueprint, request, jsonify
from sqlalchemy import asc, desc
from ..models import Centro,  Cliente, RazonSocial, EquiposIP, ConexionesEspeciales, InstalacionNueva
from ..database import db

centros_blueprint = Blueprint('centros', __name__)


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _sincronizar_instalacion(centro_id, fecha):
    if not fecha:
        return
    instalacion = (
        InstalacionNueva.query.filter_by(centro_id=centro_id)
        .order_by(InstalacionNueva.id_instalacion.asc())
        .first()
    )
    if instalacion:
        instalacion.fecha_instalacion = fecha
        if not instalacion.inicio_monitoreo:
            instalacion.inicio_monitoreo = fecha
    else:
        nueva = InstalacionNueva(
            centro_id=centro_id,
            fecha_instalacion=fecha,
            inicio_monitoreo=fecha,
            documento_acta=None,
            observacion="Sincronizado automaticamente desde Centros"
        )
        db.session.add(nueva)
    db.session.commit()

# Ruta para obtener todos los centros
@centros_blueprint.route('/', methods=['GET'])
def get_centros():
    # Filtros
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 30, type=int)
    search_cliente = request.args.get('cliente', '', type=str)
    search_centro = request.args.get('centro', '', type=str)
    sort_by = request.args.get('sort_by', 'created_at', type=str)
    sort_order = request.args.get('sort_order', 'asc', type=str)

    query = Centro.query

    # Filtro por cliente
    if search_cliente:
        query = query.join(Centro.cliente).filter(Centro.cliente.has(nombre=search_cliente))

    # Filtro por centro
    if search_centro:
        query = query.filter(Centro.nombre.ilike(f"%{search_centro}%"))

    # Ordenamiento por fecha u otros campos
    if sort_by in ['created_at', 'fecha_activacion', 'fecha_termino']:
        if sort_order == 'asc':
            query = query.order_by(asc(getattr(Centro, sort_by)))
        else:
            query = query.order_by(desc(getattr(Centro, sort_by)))

    # Verificar si per_page es 0, lo que significa que no se quiere paginación
    if per_page == 0:
        # Obtener todos los centros sin paginación
        centros = query.all()
        total = len(centros)
        page = 1
        pages = 1
    else:
        # Aplicar paginación
        paginated_result = query.paginate(page=page, per_page=per_page, error_out=False)
        centros = paginated_result.items
        total = paginated_result.total
        page = paginated_result.page
        pages = paginated_result.pages

    # Construcción de la respuesta JSON
    centros_data = [{
        'id': centro.id_centro,
        'nombre': centro.nombre,
        'estado': centro.estado,
        'fecha_instalacion': centro.fecha_instalacion,
        'fecha_activacion': centro.fecha_activacion,
        'fecha_termino': centro.fecha_termino,
        'cliente': centro.cliente.nombre if centro.cliente else "N/A",
        'razon_social': centro.razon_social.razon_social if centro.razon_social else "N/A",
        'nombre_ponton': centro.nombre_ponton,
        'ubicacion': centro.ubicacion,
        'correo_centro': centro.correo_centro,
        'area': centro.area,
        'telefono': centro.telefono,
        'cantidad_radares': centro.cantidad_radares,
        'cantidad_camaras': centro.cantidad_camaras,
        'base_tierra': "Sí" if centro.base_tierra else "No",
        'respaldo_adicional': "Sí" if centro.respaldo_adicional else "No",
        'valor_contrato': str(centro.valor_contrato),
        'created_at': centro.created_at
    } for centro in centros]

    # Respuesta JSON
    return jsonify({
        'centros': centros_data,
        'total': total,
        'page': page,
        'pages': pages
    })

# Ruta para crear un nuevo centro
@centros_blueprint.route('/', methods=['POST'])
def crear_centro():
    data = request.get_json()
    # Validaciones basicas
    if not data.get('nombre') or not data.get('cliente_id') or not data.get('razon_social_id'):
        return jsonify({"message": "Datos incompletos"}), 400

    fecha_instalacion = _parse_date(data.get('fecha_instalacion'))
    fecha_activacion = _parse_date(data.get('fecha_activacion'))
    fecha_termino = _parse_date(data.get('fecha_termino'))

    try:
        nuevo_centro = Centro(
            nombre=data.get('nombre'),
            nombre_ponton=data.get('nombre_ponton'),
            ubicacion=data.get('ubicacion'),
            correo_centro=data.get('correo_centro'),
            area=data.get('area'),
            telefono=data.get('telefono'),
            cliente_id=data.get('cliente_id'),
            razon_social_id=data.get('razon_social_id'),
            fecha_instalacion=fecha_instalacion,
            fecha_activacion=fecha_activacion,
            fecha_termino=fecha_termino,
            cantidad_radares=data.get('cantidad_radares'),
            cantidad_camaras=data.get('cantidad_camaras'),
            base_tierra=data.get('base_tierra'),
            respaldo_adicional=data.get('respaldo_adicional'),
            valor_contrato=data.get('valor_contrato'),
            estado=data.get('estado', 'activo')  # Por defecto es 'activo'
        )

        db.session.add(nuevo_centro)
        db.session.commit()
        _sincronizar_instalacion(nuevo_centro.id_centro, fecha_instalacion)
        return jsonify({"message": "Centro creado exitosamente"}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({"message": f"Error al crear el centro: {str(e)}"}), 500

@centros_blueprint.route('/<int:id_centro>', methods=['PUT'])
def actualizar_centro(id_centro):
    data = request.get_json()
    centro = Centro.query.get(id_centro)

    if not centro:
        return jsonify({"message": "Centro no encontrado"}), 404

    # Validacion de cliente_id y razon_social_id
    try:
        if data.get('cliente_id'):
            cliente_existente = Cliente.query.get(data['cliente_id'])
            if not cliente_existente:
                return jsonify({"message": "Cliente no encontrado"}), 404
            centro.cliente_id = data['cliente_id']

        if data.get('razon_social_id'):
            razon_social_existente = RazonSocial.query.get(data['razon_social_id'])
            if not razon_social_existente:
                return jsonify({"message": "Razon social no encontrada"}), 404
            centro.razon_social_id = data['razon_social_id']

        # Actualizacion de los demas campos
        centro.nombre = data.get('nombre', centro.nombre)
        centro.nombre_ponton = data.get('nombre_ponton', centro.nombre_ponton)
        centro.ubicacion = data.get('ubicacion', centro.ubicacion)
        centro.correo_centro = data.get('correo_centro', centro.correo_centro)
        centro.area = data.get('area', centro.area)
        centro.telefono = data.get('telefono', centro.telefono)
        nueva_fecha_instalacion = _parse_date(data.get('fecha_instalacion'))
        centro.fecha_instalacion = nueva_fecha_instalacion or centro.fecha_instalacion
        centro.fecha_activacion = _parse_date(data.get('fecha_activacion')) or centro.fecha_activacion
        centro.fecha_termino = _parse_date(data.get('fecha_termino')) or centro.fecha_termino
        centro.cantidad_radares = data.get('cantidad_radares', centro.cantidad_radares)
        centro.cantidad_camaras = data.get('cantidad_camaras', centro.cantidad_camaras)
        centro.base_tierra = data.get('base_tierra', centro.base_tierra)
        centro.respaldo_adicional = data.get('respaldo_adicional', centro.respaldo_adicional)
        centro.valor_contrato = data.get('valor_contrato', centro.valor_contrato)
        centro.estado = data.get('estado', centro.estado)

        # Guardado en la base de datos
        db.session.commit()
        fecha_sync = nueva_fecha_instalacion or centro.fecha_instalacion
        if fecha_sync:
            _sincronizar_instalacion(centro.id_centro, fecha_sync)
        return jsonify({"message": "Centro actualizado exitosamente"}), 200

    except Exception as e:
        db.session.rollback()
        print(f"Error al actualizar el centro {id_centro}: {e}")
        return jsonify({"message": f"Error al actualizar el centro: {str(e)}"}), 500

# Ruta para eliminar un centro
@centros_blueprint.route('/<int:id_centro>', methods=['DELETE'])
def eliminar_centro(id_centro):
    centro = Centro.query.get(id_centro)

    if not centro:
        return jsonify({"message": "Centro no encontrado"}), 404

    db.session.delete(centro)
    db.session.commit()

    return jsonify({"message": "Centro eliminado exitosamente"}), 200

# Ruta para buscar detalle un centro equipos y team any
@centros_blueprint.route('/detalles', methods=['GET'])
def obtener_detalles_centro():
    nombre_centro = request.args.get('nombre')
    if not nombre_centro:
        return jsonify({"error": "Nombre del centro es requerido"}), 400

    centro = Centro.query.filter(Centro.nombre.ilike(f'%{nombre_centro}%')).first()
    if not centro:
        return jsonify({"error": "Centro no encontrado"}), 404

    # Si el centro existe, devuelve sus datos
    equipos = EquiposIP.query.filter_by(centro_id=centro.id_centro).all()
    conexiones = ConexionesEspeciales.query.filter_by(centro_id=centro.id_centro).all()
    
    centro_data = {
        "id_centro": centro.id_centro,
        "nombre": centro.nombre,
        "nombre_ponton": centro.nombre_ponton,
        "cliente": centro.cliente.nombre if centro.cliente else None,
        "estado": centro.estado,
        "equipos": [
            {
                "id_equipo": equipo.id_equipo,
                "nombre": equipo.nombre,
                "ip": equipo.ip,
                "observacion": equipo.observacion,
                "codigo": equipo.codigo,
                "numero_serie": equipo.numero_serie,
                "estado": equipo.estado
            } for equipo in equipos
        ],
        "conexiones": [
            {
                "id": conexion.id,
                "nombre": conexion.nombre,
                "numero_conexion": conexion.numero_conexion
            } for conexion in conexiones
        ]
    }
    return jsonify(centro_data), 200
