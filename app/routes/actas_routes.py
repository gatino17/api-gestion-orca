from flask import Blueprint, request, jsonify
from sqlalchemy import and_, literal, func, case
from .levantamientos_routes import crear_levantamiento_logic, actualizar_levantamiento_logic, eliminar_levantamiento_logic, obtener_levantamientos_logic
from .ceses_routes import  crear_cese_logic, eliminar_ceses_por_centro
from .retiros_routes import crear_retiro_logic, eliminar_retiros_por_centro
from .traslados_routes import crear_traslado_logic, eliminar_traslados_por_centro
from .instalaciones_routes import crear_instalacion_logic, eliminar_instalaciones_por_centro
from .mantenciones_routes import obtener_mantenciones_por_centro, crear_mantencion_logic, eliminar_mantenciones_por_centro, eliminar_mantencion_por_id, descargar_documento_mantencion
from .inventarios_routes import crear_inventario_logic, actualizar_inventario_logic, eliminar_inventario_logic, obtener_inventarios_logic,eliminar_inventarios_por_centro
from ..models import (
    Cese,
    Levantamiento,
    InstalacionNueva,
    Retiro,
    Traslado,
    Mantencion,
    ServiciosAdicionales,
    Inventario,
    Centro,
    Cliente,
    RazonSocial,
    db
)
# Declarar la URL base

actas_blueprint = Blueprint('actas', __name__)

@actas_blueprint.route('/listar', methods=['GET'])
def listar_actas():
    try:
        # Obtener filtros
        cliente_id = request.args.get('cliente_id', type=int)
        nombre_centro = request.args.get('nombre_centro', type=str) 
        if nombre_centro:
           nombre_centro = nombre_centro.strip()  # ✅ Elimina espacios extras
        id_centro = request.args.get('id_centro', type=int)
        
        print("📌 Filtros recibidos:", cliente_id, nombre_centro, id_centro)


        # Filtros base
        filtros_base = []
        if cliente_id:
            filtros_base.append(Cliente.id_cliente == cliente_id)

        if id_centro:
            filtros_base.append(Centro.id_centro == id_centro)
        elif nombre_centro:
             filtros_base.append(func.lower(Centro.nombre).ilike(f"%{nombre_centro.lower()}%"))


        
        # Subconsultas para actividades
        instalaciones_subq = db.session.query(
            InstalacionNueva.centro_id.label("cid"),
            case(
                (InstalacionNueva.documento_acta.is_not(None),
                 func.concat("http://localhost:5000/api/filtro/documento/Instalaciones/", InstalacionNueva.id_instalacion)),
                else_=None
            ).label("documento_instalacion"),
            InstalacionNueva.fecha_instalacion.label("fecha_instalacion")
        ).join(Centro, InstalacionNueva.centro_id == Centro.id_centro).subquery()

        levantamientos_subq = db.session.query(
            Levantamiento.centro_id.label("cid"),
            Levantamiento.id_levantamiento.label("id_levantamiento"),  # Aquí agregas el ID
            case(
                (Levantamiento.documento_asociado.is_not(None),
                 func.concat("http://localhost:5000/api/filtro/documento/Levantamientos/", Levantamiento.id_levantamiento)),
                else_=None
            ).label("documento_levantamiento"),
            Levantamiento.fecha_levantamiento.label("fecha_levantamiento")
        ).join(Centro, Levantamiento.centro_id == Centro.id_centro).subquery()

        mantenciones_subq = db.session.query(
            Mantencion.centro_id.label("cid"),
            case(
                (Mantencion.documento_mantencion.is_not(None),
                 func.concat("http://localhost:5000/api/filtro/documento/Mantenciones/", Mantencion.id_mantencion)),
                else_=None
            ).label("documento_mantencion"),
            Mantencion.fecha_mantencion.label("fecha_mantencion")
        ).join(Centro, Mantencion.centro_id == Centro.id_centro).subquery()

        retiros_subq = db.session.query(
            Retiro.centro_id.label("cid"),
            case(
                (Retiro.documento.is_not(None),
                 func.concat("http://localhost:5000/api/filtro/documento/Retiros/", Retiro.id_retiro)),
                else_=None
            ).label("documento_retiro"),
            Retiro.fecha_de_retiro.label("fecha_retiro")
        ).join(Centro, Retiro.centro_id == Centro.id_centro).subquery()

        traslados_subq = db.session.query(
            Traslado.centro_origen_id.label("cid"),
            case(
                (Traslado.documento_asociado.is_not(None),
                 func.concat("http://localhost:5000/api/filtro/documento/Traslados/", Traslado.id_traslado)),
                else_=None
            ).label("documento_traslado"),
            Traslado.fecha_traslado.label("fecha_traslado")
        ).join(Centro, Traslado.centro_origen_id == Centro.id_centro).subquery()

        ceses_subq = db.session.query(
            Cese.centro_id.label("cid"),
            case(
                (Cese.documento_cese.is_not(None),
                 func.concat("http://localhost:5000/api/filtro/documento/Ceses/", Cese.id_cese)),
                else_=None
            ).label("documento_cese"),
            Cese.fecha_cese.label("fecha_cese")
        ).join(Centro, Cese.centro_id == Centro.id_centro).subquery()

        inventarios_subq = db.session.query(
            Inventario.centro_id.label("cid"),
            case(
                (Inventario.documento.is_not(None),
                 func.concat("http://localhost:5000/api/filtro/documento/Inventarios/", Inventario.id_inventario)),
                else_=None
            ).label("documento_inventario")
        ).join(Centro, Inventario.centro_id == Centro.id_centro).subquery()

        actividades_query = db.session.query(
            Centro.id_centro.label("id_centro"),
            Centro.nombre.label("nombre_centro"),
            Centro.area.label("area"),
            Centro.ubicacion.label("ubicacion"),
            Centro.estado.label("estado"),
            Centro.fecha_instalacion.label("centro_fecha_instalacion"),
            Cliente.nombre.label("nombre_cliente"),
            instalaciones_subq.c.documento_instalacion,
            instalaciones_subq.c.fecha_instalacion,
            levantamientos_subq.c.documento_levantamiento,
            levantamientos_subq.c.fecha_levantamiento,
            mantenciones_subq.c.documento_mantencion,
            mantenciones_subq.c.fecha_mantencion,
            retiros_subq.c.documento_retiro,
            retiros_subq.c.fecha_retiro,
            traslados_subq.c.documento_traslado,
            traslados_subq.c.fecha_traslado,
            ceses_subq.c.documento_cese,
            ceses_subq.c.fecha_cese,
            inventarios_subq.c.documento_inventario
        ).join(Cliente, Cliente.id_cliente == Centro.cliente_id)\
         .outerjoin(instalaciones_subq, instalaciones_subq.c.cid == Centro.id_centro)\
         .outerjoin(levantamientos_subq, levantamientos_subq.c.cid == Centro.id_centro)\
         .outerjoin(mantenciones_subq, mantenciones_subq.c.cid == Centro.id_centro)\
         .outerjoin(retiros_subq, retiros_subq.c.cid == Centro.id_centro)\
         .outerjoin(traslados_subq, traslados_subq.c.cid == Centro.id_centro)\
         .outerjoin(ceses_subq, ceses_subq.c.cid == Centro.id_centro)\
         .outerjoin(inventarios_subq, inventarios_subq.c.cid == Centro.id_centro)\
         .filter(*filtros_base) 
                
        actividades_rows = actividades_query.all()

        actividades_result = []
        for row in actividades_rows:
            actividades_result.append({
                "id_centro": row.id_centro,
                "nombre_centro": row.nombre_centro,
                "area": row.area,
                "ubicacion": row.ubicacion,
                "estado": row.estado,
                "nombre_cliente": row.nombre_cliente,
                "centro_fecha_instalacion": row.centro_fecha_instalacion,
                "instalacion_fecha": row.fecha_instalacion,
                "instalacion_documento": row.documento_instalacion,
                "levantamiento_fecha": row.fecha_levantamiento,
                "levantamiento_documento": row.documento_levantamiento,
                "mantencion_fecha": row.fecha_mantencion,
                "mantencion_documento": row.documento_mantencion,
                "retiro_fecha": row.fecha_retiro,
                "retiro_documento": row.documento_retiro,
                "traslado_fecha": row.fecha_traslado,
                "traslado_documento": row.documento_traslado,
                "cese_fecha": row.fecha_cese,
                "cese_documento": row.documento_cese,
                "inventario_documento": row.documento_inventario
            })

        servicios_adicionales_query = db.session.query(
        ServiciosAdicionales.id_servicio.label("id"),
        Cliente.nombre.label("nombre_cliente"),  # ✅ Cliente correcto
        RazonSocial.razon_social.label("nombre_empresa"),  # ✅ Razón Social correcta
        ServiciosAdicionales.fecha_instalacion.label("fecha"),
        ServiciosAdicionales.inicio_monitoreo.label("fecha_inicio_monitoreo"),
        case(
            (ServiciosAdicionales.documento_asociado.is_not(None),
            func.concat("http://localhost:5000/api/filtro/documento/Servicios_Adicionales/", ServiciosAdicionales.id_servicio)),
            else_=None
        ).label("documento"),
        ServiciosAdicionales.observaciones.label("observacion")
        ).join(RazonSocial, ServiciosAdicionales.id_razon_social == RazonSocial.id_razon_social)  \
        .join(Cliente, RazonSocial.cliente_id == Cliente.id_cliente) \
        .all()
        servicios_adicionales_result = [dict(row._mapping) for row in servicios_adicionales_query]

        return jsonify({
            "actividades": actividades_result,
            "servicios_adicionales": servicios_adicionales_result
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@actas_blueprint.route('/editar/<int:id>', methods=['PUT'])
def editar_acta(id):
    try:
        # Obtener los datos del cuerpo de la solicitud
        data = request.json
        
        # Identificar el tipo de acta (Instalación, Levantamiento, etc.)
        tipo = data.get('tipo')  # Ejemplo: 'instalacion', 'levantamiento', etc.
        documento = data.get('documento')  # Documento asociado al acta
        fecha = data.get('fecha')  # Fecha asociada al acta

        # Manejo según el tipo de acta
        if tipo == 'instalacion':
            acta = InstalacionNueva.query.get(id)
            if not acta:
                return jsonify({"error": "Acta de instalación no encontrada"}), 404
            acta.documento_acta = documento
            acta.fecha_instalacion = fecha

        elif tipo == 'levantamiento':
            acta = Levantamiento.query.get(id)
            if not acta:
                return jsonify({"error": "Acta de levantamiento no encontrada"}), 404
            acta.documento_asociado = documento
            acta.fecha_levantamiento = fecha
           # acta.inicio_monitoreo = inicio_monitoreo
            #acta.observacion = observacion

        elif tipo == 'mantencion':
            acta = Mantencion.query.get(id)
            if not acta:
                return jsonify({"error": "Acta de mantención no encontrada"}), 404
            acta.documento_mantencion = documento
            acta.fecha_mantencion = fecha

        elif tipo == 'retiro':
            acta = Retiro.query.get(id)
            if not acta:
                return jsonify({"error": "Acta de retiro no encontrada"}), 404
            acta.documento = documento
            acta.fecha_de_retiro = fecha

        elif tipo == 'traslado':
            acta = Traslado.query.get(id)
            if not acta:
                return jsonify({"error": "Acta de traslado no encontrada"}), 404
            acta.documento_asociado = documento
            acta.fecha_traslado = fecha

        elif tipo == 'cese':
            acta = Cese.query.get(id)
            if not acta:
                return jsonify({"error": "Acta de cese no encontrada"}), 404
            acta.documento_cese = documento
            acta.fecha_cese = fecha

        elif tipo == 'servicio_adicional':
            acta = ServiciosAdicionales.query.get(id)
            if not acta:
                return jsonify({"error": "Acta de servicio adicional no encontrada"}), 404
            acta.documento_asociado = documento
            acta.fecha_instalacion = fecha

        else:
            return jsonify({"error": "Tipo de acta no válido"}), 400

        # Guardar cambios en la base de datos
        db.session.commit()
        return jsonify({"message": "Acta editada correctamente"}), 200

    except Exception as e:
        # Manejo de errores genéricos
        return jsonify({"error": str(e)}), 500

    

# Endpoint para crear un levantamiento
@actas_blueprint.route('/levantamientos', methods=['POST'])
def crear_levantamiento_desde_actas():
    try:
        data = request.form
        file = request.files.get('documento_asociado')
        response, status_code = crear_levantamiento_logic(data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Endpoint para editar un levantamiento
@actas_blueprint.route('/levantamientos/<int:id_levantamiento>', methods=['PUT'])
def editar_levantamiento_desde_actas(id_levantamiento):
    try:
        data = request.form
        file = request.files.get('documento_asociado')
        response, status_code = actualizar_levantamiento_logic(id_levantamiento, data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# Endpoint para eliminar un levantamiento
@actas_blueprint.route('/levantamientos/<int:id_levantamiento>', methods=['DELETE'])
def eliminar_levantamiento_desde_actas(id_levantamiento):
    try:
        levantamiento = Levantamiento.query.get(id_levantamiento)
        if not levantamiento:
            return jsonify({"error": "Levantamiento no encontrado"}), 404

        db.session.delete(levantamiento)
        db.session.commit()
        return jsonify({"message": "Levantamiento eliminado exitosamente"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
    # Endpoint para eliminar todos los levantamientos por centro_id
@actas_blueprint.route('/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_levantamientos_por_centro_desde_actas(centro_id):
    try:
        # Llama a la lógica definida en levantamientos_routes.py
        from .levantamientos_routes import eliminar_levantamientos_por_centro
        return eliminar_levantamientos_por_centro(centro_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    
########### endpoint inventario #############
    
# Endpoint para listar inventarios
@actas_blueprint.route('/inventarios', methods=['GET'])
def obtener_inventarios_desde_actas():
    try:
        centro_id = request.args.get('centro_id', type=int)
        response, status_code = obtener_inventarios_logic(centro_id)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Endpoint para crear un inventario
@actas_blueprint.route('/inventarios', methods=['POST'])
def crear_inventario_desde_actas():
    try:
        data = request.form
        file = request.files.get('documento')
        response, status_code = crear_inventario_logic(data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Endpoint para actualizar un inventario
@actas_blueprint.route('/inventarios/<int:id_inventario>', methods=['PUT'])
def actualizar_inventario_desde_actas(id_inventario):
    try:
        data = request.form
        file = request.files.get('documento')
        response, status_code = actualizar_inventario_logic(id_inventario, data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Endpoint para eliminar un inventario
@actas_blueprint.route('/inventarios/<int:id_inventario>', methods=['DELETE'])
def eliminar_inventario_desde_actas(id_inventario):
    try:
        response, status_code = eliminar_inventario_logic(id_inventario)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
# Endpoint para eliminar un inventario por centro  
@actas_blueprint.route('/inventarios/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_inventarios_centro(centro_id):
    return eliminar_inventarios_por_centro(centro_id)

############################## Endpoint ceses ######################################
# Endpoint para crear un cese
@actas_blueprint.route('/ceses', methods=['POST'])
def crear_cese_desde_actas():
    try:
        data = request.form
        file = request.files.get('documento_cese')
        response, status_code = crear_cese_logic(data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Endpoint para eliminar todos los ceses de un centro
@actas_blueprint.route('/ceses/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_ceses_por_centro_desde_actas(centro_id):
    try:
        return eliminar_ceses_por_centro(centro_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
############################## Endpoint retiros######################################

@actas_blueprint.route('/retiros', methods=['POST'])
def crear_retiro_desde_actas():
    try:
        data = request.form
        file = request.files.get('documento')
        response, status_code = crear_retiro_logic(data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@actas_blueprint.route('/retiros/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_retiros_por_centro_desde_actas(centro_id):
    try:
        return eliminar_retiros_por_centro(centro_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
############################## Endpoint traslados ######################################

@actas_blueprint.route('/traslados', methods=['POST'])
def crear_traslado_desde_actas():
    try:
        data = request.form
        file = request.files.get('documento_asociado')
        response, status_code = crear_traslado_logic(data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@actas_blueprint.route('/traslados/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_traslados_por_centro_desde_actas(centro_id):
    try:
        return eliminar_traslados_por_centro(centro_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

############################## Endpoint instalaciones ######################################

# Endpoint para crear una instalación
@actas_blueprint.route('/instalaciones', methods=['POST'])
def crear_instalacion_desde_actas():
    try:
        data = request.form
        file = request.files.get('documento_acta')
        response, status_code = crear_instalacion_logic(data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Endpoint para eliminar todas las instalaciones de un centro
@actas_blueprint.route('/instalaciones/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_instalaciones_por_centro_desde_actas(centro_id):
    try:
        return eliminar_instalaciones_por_centro(centro_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

############################## Endpoint mantenciones ######################################

# Endpoint para obtener mantencion
@actas_blueprint.route('/mantenciones', methods=['GET'])
def obtener_mantenciones_desde_actas():
    try:
        centro_id = request.args.get('centro_id', type=int)
        response, status_code = obtener_mantenciones_por_centro(centro_id)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Endpoint para obtener mantencion
@actas_blueprint.route('/mantenciones', methods=['POST'])
def crear_mantencion_desde_actas():
    try:
        data = request.form
        file = request.files.get('documento_mantencion')
        response, status_code = crear_mantencion_logic(data, file)
        return jsonify(response), status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# Endpoint para eliminar mantencion
@actas_blueprint.route('/mantenciones/eliminar_por_centro/<int:centro_id>', methods=['DELETE'])
def eliminar_mantenciones_por_centro_desde_actas(centro_id):
    try:
        return jsonify(eliminar_mantenciones_por_centro(centro_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@actas_blueprint.route('/mantenciones/<int:id_mantencion>', methods=['DELETE'])
def eliminar_mantencion_desde_actas(id_mantencion):
    try:
        return eliminar_mantencion_por_id(id_mantencion)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@actas_blueprint.route('/mantenciones/<int:id_mantencion>/documento', methods=['GET'])
def descargar_documento_mantencion_desde_actas(id_mantencion):
    try:
        return descargar_documento_mantencion(id_mantencion)
    except Exception as e:
        return jsonify({"error": str(e)}), 500





