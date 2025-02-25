from flask import Blueprint, jsonify, request, send_file
from ..models import Cliente, Centro, Levantamiento, InstalacionNueva, Mantencion, Traslado, Cese, Retiro, EquiposIP, Soporte, Inventario
from ..database import db


from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from io import BytesIO
from datetime import datetime



# Declarar la URL base
BASE_URL = "http://localhost:5000"
consultascentro_historial_bp = Blueprint('consultascentro_historial', __name__)

# Ruta para obtener todos los clientes
@consultascentro_historial_bp.route('/clientes', methods=['GET'])
def obtener_clientes():
    try:
        clientes = Cliente.query.all()
        resultado = [
            {"id_cliente": cliente.id_cliente, "nombre": cliente.nombre} for cliente in clientes
        ]
        return jsonify(resultado), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ruta para obtener centros asociados a un cliente
@consultascentro_historial_bp.route('/centros/<int:cliente_id>', methods=['GET'])
def obtener_centros_por_cliente(cliente_id):
    try:
        centros = Centro.query.filter_by(cliente_id=cliente_id).all()
        resultado = [
            {
                "id_centro": centro.id_centro,
                "nombre": centro.nombre,
                "ubicacion": centro.ubicacion,
                "nombre_ponton": centro.nombre_ponton,
                "estado": centro.estado
            } for centro in centros
        ]
        return jsonify(resultado), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Ruta para obtener información detallada de un centro
@consultascentro_historial_bp.route('/centro_historial/<int:centro_id>', methods=['GET'])
def obtener_historial_centro(centro_id):
    try:
        # Información del centro
        centro = Centro.query.get(centro_id)
        if not centro:
            return jsonify({"error": "Centro no encontrado"}), 404

        centro_info = {
            "id_centro": centro.id_centro,
            "nombre": centro.nombre,
            "ubicacion": centro.ubicacion,
            "nombre_ponton": centro.nombre_ponton,
            "estado": centro.estado,
            "valor_contrato": centro.valor_contrato,
            "cantidad_radares": centro.cantidad_radares,
            "cantidad_camaras": centro.cantidad_camaras,
            "base_tierra": centro.base_tierra,
            "fecha_instalacion": centro.fecha_instalacion,
            "fecha_activacion": centro.fecha_activacion,
            "fecha_termino": centro.fecha_termino,
            "correo_centro": centro.correo_centro,
            "telefono": centro.telefono
        }

        # Historial del centro
        historial = {
            "levantamientos": [
                {
                    "id_levantamiento": l.id_levantamiento,
                    "fecha_levantamiento": l.fecha_levantamiento,
                    "documento": f"{BASE_URL}/api/filtro/documento/Levantamientos/{l.id_levantamiento}" if l.documento_asociado else None,
                } for l in Levantamiento.query.filter_by(centro_id=centro_id).all()
            ],
            "instalaciones": [
                {
                    "id_instalacion": i.id_instalacion,
                    "fecha_instalacion": i.fecha_instalacion,
                    "documento": f"{BASE_URL}/api/filtro/documento/Instalaciones/{i.id_instalacion}" if i.documento_acta else None,
                    "observacion":i.observacion
                } for i in InstalacionNueva.query.filter_by(centro_id=centro_id).all()
            ],
            "mantenciones": [
                {
                    "id_mantencion": m.id_mantencion,
                    "fecha_mantencion": m.fecha_mantencion,
                    "responsable": m.responsable,
                    "documento": f"{BASE_URL}/api/filtro/documento/Mantenciones/{m.id_mantencion}" if m.documento_mantencion else None,
                    "observacion": m.observacion
                } for m in Mantencion.query.filter_by(centro_id=centro_id).all()
            ],
            "traslados": [
                {
                    "id_traslado": t.id_traslado,
                    "centro_destino_id": t.centro_destino_id,
                    "centro_destino_nombre": destino.nombre if destino else "No especificado",  
                    "fecha_traslado": t.fecha_traslado,
                    "documento": f"{BASE_URL}/api/filtro/documento/Traslados/{t.id_traslado}" if t.documento_asociado else None,
                    "observacion":t.observacion
                }  for t, destino in db.session.query(Traslado, Centro).filter(
                    Traslado.centro_origen_id == centro_id,
                    Traslado.centro_destino_id == Centro.id_centro).all()
            ],
            "ceses": [
                {
                    "id_cese": c.id_cese,
                    "fecha_cese": c.fecha_cese,
                    "documento": f"{BASE_URL}/api/filtro/documento/Ceses/{c.id_cese}" if c.documento_cese else None
                } for c in Cese.query.filter_by(centro_id=centro_id).all()
            ],
            "retiros": [
                {
                    "id_retiro": r.id_retiro,
                    "fecha_retiro": r.fecha_de_retiro,
                    "documento": f"{BASE_URL}/api/filtro/documento/Retiros/{r.id_retiro}" if r.documento else None,
                    "observacion":r.observacion
                } for r in Retiro.query.filter_by(centro_id=centro_id).all()
            ],
            "soportes": [  # Nuevo soporte agregado
                {
                    "id_soporte": s.id_soporte,
                    "problema": s.problema,
                    "tipo": s.tipo,
                    "fecha_soporte": s.fecha_soporte,
                    "solucion": s.solucion,
                    "cambio_equipo": s.cambio_equipo,
                    "equipo_cambiado": s.equipo_cambiado
                } for s in Soporte.query.filter_by(centro_id=centro_id).all()
            ]
        }

        # Datos IP
        datos_ip = [
            {
                "id_equipo": e.id_equipo,
                "nombre": e.nombre,
                "ip": e.ip,
                "estado": e.estado
            } for e in EquiposIP.query.filter_by(centro_id=centro_id).all()
        ]
           # 📌 Agregar Inventario
        inventario = [
            {
                "id_inventario": inv.id_inventario,
                "documento": f"{BASE_URL}/api/inventarios/{inv.id_inventario}/documento"
            } for inv in Inventario.query.filter_by(centro_id=centro_id).all()
        ]

        return jsonify({"centro": centro_info, "historial": historial, "equipos_ip": datos_ip, "inventario": inventario}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500



# Configuración de colores y estilo
COLOR_CABECERA = colors.HexColor("#007ACC")
COLOR_FONDO = colors.HexColor("#F5F5F5")
COLOR_TEXTO = colors.black
COLOR_LINEA = colors.HexColor("#E0E0E0")

# Función para agregar pie de página
def agregar_pie_pagina(pdf, numero_pagina, total_paginas):
    pdf.setFont("Helvetica-Oblique", 9)
    pdf.setFillColor(colors.grey)
    pdf.drawString(450, 30, f"Página {numero_pagina} de {total_paginas}")
    pdf.drawString(100, 30, "Sistema de Gestión Empresarial - Orcagest")

# Ruta para generar el PDF del historial del centro
@consultascentro_historial_bp.route('/centro_historial/<int:centro_id>/pdf', methods=['GET'])
def generar_historial_pdf(centro_id):
    try:
        centro = Centro.query.get(centro_id)
        if not centro:
            return jsonify({"error": "Centro no encontrado"}), 404

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=letter)
        pdf.setTitle(f"Historial_Centro_{centro.nombre}.pdf")

        # ➤ Función para configurar la página
        def configurar_pagina(numero_pagina, total_paginas, mostrar_info_centro=True):
            # ➤ Título Orcagest centrado
            pdf.setFont("Helvetica-Bold", 28)
            pdf.setFillColor(COLOR_CABECERA)
            pdf.drawCentredString(150, 760, "Orcagest")  # Centrado en la parte superior

            # ➤ Título del documento
            pdf.setFont("Helvetica-Bold", 16)
            pdf.setFillColor(COLOR_CABECERA)
            pdf.drawString(100, 730, f"Historial del Centro: {centro.nombre}")
            pdf.setFont("Helvetica", 10)
            pdf.setFillColor(COLOR_TEXTO)
            pdf.drawString(400, 730, f"Fecha: {datetime.now().strftime('%d/%m/%Y')}")

            # ➤ Información del centro SOLO en la primera página
            y_position = 710
            if mostrar_info_centro:
                pdf.drawString(100, y_position, f"Ubicación: {centro.ubicacion} | Estado: {centro.estado}")
                y_position -= 20
                pdf.drawString(100, y_position, f"Cantidad de Radares: {centro.cantidad_radares or 0}")
                y_position -= 20
                pdf.drawString(100, y_position, f"Cantidad de Cámaras: {centro.cantidad_camaras or 0}")
                y_position -= 20
                pdf.drawString(100, y_position, f"Base Tierra: {'Sí' if centro.base_tierra else 'No'}")
                y_position -= 20
                pdf.drawString(100, y_position, f"Correo Centro: {centro.correo_centro or 'No disponible'}")
                y_position -= 20
                pdf.drawString(100, y_position, f"Teléfono: {centro.telefono or 'No disponible'}")
                y_position -= 30  # Espacio debajo de la información del centro

            agregar_pie_pagina(pdf, numero_pagina, total_paginas)

        # ➤ Inicializar número de página
        numero_pagina = 1
        total_paginas = 1
        configurar_pagina(numero_pagina, total_paginas, mostrar_info_centro=True)
        y_position = 580

        # 📌 Sección de documentos - Definición dinámica
        secciones = {
            "Levantamientos": Levantamiento.query.filter_by(centro_id=centro_id).all(),
            "Instalaciones": InstalacionNueva.query.filter_by(centro_id=centro_id).all(),
            "Mantenciones": Mantencion.query.filter_by(centro_id=centro_id).all(),
            "Soportes": Soporte.query.filter_by(centro_id=centro_id).all(),
            "Traslados": Traslado.query.filter(
                (Traslado.centro_origen_id == centro_id) | (Traslado.centro_destino_id == centro_id)
            ).all(),
            "Ceses": Cese.query.filter_by(centro_id=centro_id).all(),
            "Retiros": Retiro.query.filter_by(centro_id=centro_id).all(),
        }

        # ➤ Especificar qué campos mostrar de cada tabla
        campos_a_mostrar = {
            "Levantamientos": ["fecha_levantamiento"],
            "Instalaciones": ["fecha_instalacion", "inicio_monitoreo", "observacion"],
            "Mantenciones": ["fecha_mantencion", "responsable", "observacion"],
            "Soportes": ["problema", "tipo", "fecha_soporte", "solucion", "cambio_equipo", "equipo_cambiado"],
            "Traslados": ["fecha_traslado", "tipo_traslado", "observacion"],
            "Ceses": ["fecha_cese"],
            "Retiros": ["fecha_de_retiro", "observacion"],
        }

        # ➤ Ordenar y mostrar las tablas
        for seccion, documentos in secciones.items():
            if documentos:
                pdf.setFont("Helvetica-Bold", 14)
                pdf.setFillColor(COLOR_CABECERA)
                pdf.setFillColorRGB(0.8, 0.9, 1)  # Color celeste claro
                pdf.rect(95, y_position - 5, 450, 20, fill=True, stroke=False)
                pdf.setFillColor(COLOR_CABECERA)
                pdf.drawString(100, y_position, seccion)

                y_position -= 25
                pdf.setFont("Helvetica", 12)
                pdf.setFillColor(COLOR_TEXTO)

                for doc in documentos:
                    campos = campos_a_mostrar.get(seccion, [])
                    for campo in campos:
                        # 📌 Ajuste aquí para evitar "None" y mostrar vacío en su lugar
                        valor = getattr(doc, campo, '') or 'No disponible'
                        # ✅ Reemplaza guiones bajos con espacios y capitaliza el nombre del campo
                        nombre_campo = campo.replace('_', ' ').capitalize()
                        # ✅ Solo dibuja la línea si hay valor (evita líneas en blanco innecesarias)
                        if valor:
                            pdf.drawString(120, y_position, f"{nombre_campo}: {valor}")
                            y_position -= 20

                    y_position -= 10  # Espacio entre registros

                y_position -= 20  # Espacio entre secciones

            # ➤ Verificar si hay suficiente espacio antes de la siguiente sección
            if y_position < 100:
                numero_pagina += 1
                pdf.showPage()
                configurar_pagina(numero_pagina, total_paginas, mostrar_info_centro=False)
                y_position = 700

        pdf.showPage()
        pdf.save()
        buffer.seek(0)

        return send_file(buffer, as_attachment=True, download_name=f"Historial_Centro_{centro.nombre}.pdf", mimetype='application/pdf')

    except Exception as e:
        return jsonify({"error": str(e)}), 500
