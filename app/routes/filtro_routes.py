from flask import Blueprint, request, jsonify, send_file
from sqlalchemy import and_, literal, func, case
from sqlalchemy.orm import aliased
import os
from ..models import (
    Cliente,
    Cese,
    Levantamiento,
    InstalacionNueva,
    Retiro,
    Traslado,
    Mantencion,
    ServiciosAdicionales,
    Centro,
    RazonSocial,
    Inventario,
    db
)
# Alias para Centro Destino
CentroDestino = aliased(Centro)

# Declarar la URL base
BASE_URL = "http://localhost:5000"

# Crear el blueprint
filtro_blueprint = Blueprint('filtro', __name__)

@filtro_blueprint.route('/filtrar', methods=['GET'])
def filtrar_por_fecha_y_cliente():
    try:
        # Obtener los parámetros de fecha y cliente
        fecha_inicio = request.args.get('fecha_inicio')
        fecha_fin = request.args.get('fecha_fin')
        cliente_id = request.args.get('cliente_id')

        if not fecha_inicio or not fecha_fin:
            return jsonify({"error": "Se requieren los parámetros 'fecha_inicio' y 'fecha_fin'"}), 400

        # Validar y convertir cliente_id a entero
        if cliente_id:
            try:
                cliente_id = int(cliente_id)  # Convertir a número
            except ValueError:
                return jsonify({"error": "El cliente_id debe ser un número válido"}), 400

        # Filtro básico por rango de fechas
        filtro_fecha = and_(
            Cese.fecha_cese >= fecha_inicio, 
            Cese.fecha_cese <= fecha_fin
        )
        
        # Agregar filtro por cliente si está presente
        filtro_cliente = True  # Por defecto no filtra por cliente
        if cliente_id:
            filtro_cliente = RazonSocial.cliente_id  == cliente_id

        # Consultas ajustadas con ambos filtros
        ceses = db.session.query(
            Cese.id_cese.label("id"),
            Centro.area.label("area"),
            Centro.nombre.label("nombre_centro"),
            RazonSocial.razon_social.label("nombre_empresa"),
            Cese.fecha_cese.label("fecha"),
            literal(None).label("fecha_inicio_monitoreo"),
            case(
                (Cese.documento_cese != None, func.concat(BASE_URL +"/api/filtro/documento/Ceses/", Cese.id_cese)),
                else_=None
            ).label("documento"),
            literal(None).label("responsable"),
            literal(None).label("observacion"),
            literal("Ceses").label("tipo")
        ).join(Centro, Cese.centro_id == Centro.id_centro).join(
            RazonSocial, Centro.razon_social_id == RazonSocial.id_razon_social
        ).filter(
            filtro_fecha, filtro_cliente
        ).distinct().all()

        levantamientos = db.session.query(
            Levantamiento.id_levantamiento.label("id"),
            Centro.area.label("area"),
            Centro.nombre.label("nombre_centro"),
            RazonSocial.razon_social.label("nombre_empresa"),
            Levantamiento.fecha_levantamiento.label("fecha"),
            literal(None).label("fecha_inicio_monitoreo"),
            case(
                (Levantamiento.documento_asociado != None, func.concat(BASE_URL +"/api/filtro/documento/Levantamientos/", Levantamiento.id_levantamiento)),
                else_=None
            ).label("documento"),
            literal(None).label("responsable"),
            literal(None).label("observacion"),
            literal("Levantamientos").label("tipo")
        ).join(Centro, Levantamiento.centro_id == Centro.id_centro).join(
            RazonSocial, Centro.razon_social_id == RazonSocial.id_razon_social
        ).filter(
            filtro_fecha, filtro_cliente
        ).distinct().all()

        instalaciones = db.session.query(
            InstalacionNueva.id_instalacion.label("id"),
            Centro.area.label("area"),
            Centro.nombre.label("nombre_centro"),
            RazonSocial.razon_social.label("nombre_empresa"),
            InstalacionNueva.fecha_instalacion.label("fecha"),
            InstalacionNueva.inicio_monitoreo.label("fecha_inicio_monitoreo"),
            case(
                (InstalacionNueva.documento_acta != None, func.concat(BASE_URL +"/api/filtro/documento/Instalaciones/", InstalacionNueva.id_instalacion)),
                else_=None
            ).label("documento"),           
            literal(None).label("responsable"),
            InstalacionNueva.observacion.label("observacion"),
            literal("Instalaciones").label("tipo")
        ).join(Centro, InstalacionNueva.centro_id == Centro.id_centro).join(
            RazonSocial, Centro.razon_social_id == RazonSocial.id_razon_social
        ).filter(
            filtro_fecha, filtro_cliente
        ).distinct().all()

        retiros = db.session.query(
            Retiro.id_retiro.label("id"),
            Centro.area.label("area"),
            Centro.nombre.label("nombre_centro"),
            RazonSocial.razon_social.label("nombre_empresa"),
            Retiro.fecha_de_retiro.label("fecha"),
            literal(None).label("fecha_inicio_monitoreo"),
            case(
                (Retiro.documento != None, func.concat(BASE_URL +"/api/filtro/documento/Retiros/", Retiro.id_retiro)),
                else_=None
            ).label("documento"),
            literal(None).label("responsable"),
            Retiro.observacion.label("observacion"),
            literal("Retiros").label("tipo")
        ).join(Centro, Retiro.centro_id == Centro.id_centro).join(
            RazonSocial, Centro.razon_social_id == RazonSocial.id_razon_social
        ).filter(
            filtro_fecha, filtro_cliente
        ).distinct().all()

        traslados = db.session.query(
            Traslado.id_traslado.label("id"),
            Centro.area.label("area"),
            Centro.nombre.label("nombre_centro"),
            RazonSocial.razon_social.label("nombre_empresa"),
            Traslado.fecha_traslado.label("fecha"),
            Traslado.fecha_monitoreo.label("fecha_inicio_monitoreo"),
            case(
                (Traslado.documento_asociado != None, func.concat(BASE_URL +"/api/filtro/documento/Traslados/", Traslado.id_traslado)),
                else_=None
            ).label("documento"),
            literal(None).label("responsable"),
            Traslado.observacion.label("observacion"),
            literal("Traslados").label("tipo"),
            Traslado.tipo_traslado.label("tipo_traslado"), 
            CentroDestino.nombre.label("centro_destino")  
            
        ).join(
            Centro, Traslado.centro_origen_id == Centro.id_centro  # Join con el Centro Origen
        ).join(
            CentroDestino, Traslado.centro_destino_id == CentroDestino.id_centro  # Join con el Centro Destino
        ).join(
            RazonSocial, Centro.razon_social_id == RazonSocial.id_razon_social
        ).filter(
            filtro_fecha, filtro_cliente
        ).distinct().all()

        mantenciones = db.session.query(
            Mantencion.id_mantencion.label("id"),
            Centro.area.label("area"),
            Centro.nombre.label("nombre_centro"),
            RazonSocial.razon_social.label("nombre_empresa"),
            Mantencion.fecha_mantencion.label("fecha"),
            literal(None).label("fecha_inicio_monitoreo"),
            case(
                (Mantencion.documento_mantencion != None, func.concat(BASE_URL +"/api/filtro/documento/Mantenciones/", Mantencion.id_mantencion)),
                else_=None
            ).label("documento"),
            Mantencion.responsable.label("responsable"),
            Mantencion.observacion.label("observacion"),
            literal("Mantenciones").label("tipo")
        ).join(Centro, Mantencion.centro_id == Centro.id_centro).join(
            RazonSocial, Centro.razon_social_id == RazonSocial.id_razon_social
        ).filter(
            filtro_fecha, filtro_cliente
        ).distinct().all()

        servicios_adicionales = db.session.query(
            ServiciosAdicionales.id_servicio.label("id"),
            literal(None).label("area"),
            literal(None).label("nombre_centro"),
            RazonSocial.razon_social.label("nombre_empresa"),
            ServiciosAdicionales.fecha_instalacion.label("fecha"),
            ServiciosAdicionales.inicio_monitoreo.label("fecha_inicio_monitoreo"),
            case(
                (ServiciosAdicionales.documento_asociado != None, func.concat(BASE_URL +"/api/filtro/documento/Servicios_Adicionales/", ServiciosAdicionales.id_servicio)),
                else_=None
            ).label("documento"),
            literal(None).label("responsable"),
            ServiciosAdicionales.observaciones.label("observacion"),
            literal("Servicios_Adicionales").label("tipo")
        ).join(
            RazonSocial, ServiciosAdicionales.id_razon_social == RazonSocial.id_razon_social
        ).filter(
            filtro_fecha, filtro_cliente
        ).distinct().all()

        # Combinar resultados
        resultados = ceses + levantamientos + instalaciones + retiros + traslados + mantenciones
        resultados_json = [dict(row._mapping) for row in resultados]

        # Incluir servicios adicionales como una tabla separada
        servicios_json = [dict(row._mapping) for row in servicios_adicionales]

        return jsonify({"resultados": resultados_json, "servicios_adicionales": servicios_json}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@filtro_blueprint.route('/documento/<string:tipo>/<int:id>', methods=['GET'])
def descargar_documento(tipo, id):
    try:
        # Seleccionar el modelo y la columna de documento correspondiente
        modelos = {
            "Ceses": (Cese, "documento_cese"),
            "Levantamientos": (Levantamiento, "documento_asociado"),
            "Instalaciones": (InstalacionNueva, "documento_acta"),
            "Retiros": (Retiro, "documento"),
            "Traslados": (Traslado, "documento_asociado"),
            "Mantenciones": (Mantencion, "documento_mantencion"),
            "Servicios_Adicionales": (ServiciosAdicionales, "documento_asociado"),
            "Inventarios": (Inventario, "documento")       
        }

        modelo, columna = modelos.get(tipo, (None, None))
        if not modelo or not columna:
            return jsonify({"error": "Tipo de documento no válido"}), 400

        # Buscar el registro
        registro = modelo.query.get_or_404(id)
        documento = getattr(registro, columna)

        if not documento:
            return jsonify({"error": "No hay documento asociado"}), 404

        # Ruta completa del archivo
        documento_path = os.path.join(os.getcwd(), 'uploads', documento.replace('/', os.sep))
        if not os.path.exists(documento_path):
            return jsonify({"error": "El archivo no existe"}), 404

        # Determinar el tipo MIME basado en la extensión del archivo
        mimetype = "application/octet-stream"
        if documento.endswith(('.png', '.jpg', '.jpeg')):
            mimetype = "image/jpeg"
        elif documento.endswith('.pdf'):
            mimetype = "application/pdf"

        # Enviar el archivo como respuesta
        return send_file(documento_path, mimetype=mimetype)
    except Exception as e:
        return jsonify({"error": f"Error al servir el documento: {str(e)}"}), 500


@filtro_blueprint.route('/clientes', methods=['GET'])
def obtener_clientes():
    try:
        clientes = db.session.query(Cliente.id_cliente, Cliente.nombre).all()
        resultado = [{"id": cliente.id_cliente, "nombre": cliente.nombre} for cliente in clientes]
        return jsonify(resultado), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500