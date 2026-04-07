import os
from flask import Flask
from flask_cors import CORS
from sqlalchemy import text
from .config import Config
from .database import db
from flask import send_from_directory
from .socketio_ext import socketio

from .routes.status_routes import status_blueprint

from .routes.clientes_routes import clientes_blueprint
from .routes.user_routes import user_blueprint
from .routes.auth_routes import auth_blueprint
from .routes.razones_sociales_routes import razones_sociales_blueprint
from .routes.centros_routes import centros_blueprint

from .routes.equipos_routes import equipos_bp
from .routes.conexiones_especiales_routes import conexiones_bp

from .routes.encargados_routes import encargados_bp
from .routes.actividades_routes import actividades_blueprint

from .routes.retiros_routes import retiros_blueprint
from .routes.ceses_routes import ceses_blueprint
from .routes.inventarios_routes import inventarios_blueprint
from .routes.traslados_routes import traslados_blueprint
from .routes.mantenciones_routes import mantenciones_blueprint
from .routes.mantencion_preventiva_routes import mantencion_preventiva_blueprint
from .routes.levantamientos_routes import levantamientos_blueprint
from .routes.instalaciones_routes import instalaciones_blueprint
from .routes.servicios_adicionales_routes import servicios_blueprint
from .routes.filtro_routes import filtro_blueprint

from .routes.actas_routes import actas_blueprint
from .routes.soporte_routes import soporte_blueprint
from .routes.consultascentro_historial_routes import consultascentro_historial_bp
from .routes.armados_routes import armados_blueprint
from .routes.actas_entrega_routes import actas_entrega_blueprint
from .routes.permisos_trabajo_routes import permisos_trabajo_blueprint



def create_folders():
    """
    Crear carpetas necesarias para almacenar imágenes o documentos
    """
    folders = ['uploads/retiros_img',
                'uploads/inventarios_docs',
                  'uploads/ceses_docs',
                  'uploads/traslados_docs',
                  'uploads/mantenciones_docs',
                  'uploads/levantamientos_docs',
                  'uploads/instalaciones_docs',
                  'uploads/servicios_docs']

    for folder in folders:
        if not os.path.exists(folder):
            os.makedirs(folder)
            print(f"Carpeta creada: {folder}")

def create_app():

    
    
        
    create_folders()
# Crear carpetas antes de iniciar la app
    app = Flask(__name__)
    app.config.from_object(Config)

     # Habilitar CORS específicamente para las rutas que empiezan con /api
    CORS(app, resources={r"/api/*": {"origins": "*"}})

    db.init_app(app)
    socketio.init_app(app, cors_allowed_origins="*")

    # Registrar rutas
    app.register_blueprint(user_blueprint, url_prefix='/api/users')
    app.register_blueprint(auth_blueprint, url_prefix='/api/auth')
    app.register_blueprint(clientes_blueprint, url_prefix='/api/clientes')
    app.register_blueprint(razones_sociales_blueprint, url_prefix='/api/razones_sociales')
    app.register_blueprint(centros_blueprint, url_prefix='/api/centros')

    app.register_blueprint(status_blueprint, url_prefix='/api/status') 

        # Nuevas rutas para equipos y conexiones especiales
    app.register_blueprint(equipos_bp, url_prefix='/api/equipos')
    app.register_blueprint(conexiones_bp, url_prefix='/api/conexiones')

    app.register_blueprint(encargados_bp, url_prefix='/api/encargados')
    app.register_blueprint(actividades_blueprint, url_prefix='/api/actividades')

    # Registrar el blueprint de retiros
    app.register_blueprint(retiros_blueprint, url_prefix='/api/retiros')
    app.register_blueprint(ceses_blueprint, url_prefix='/api/ceses')
    app.register_blueprint(inventarios_blueprint, url_prefix='/api/inventarios') 
    app.register_blueprint(traslados_blueprint, url_prefix='/api/traslados')
    app.register_blueprint(mantenciones_blueprint, url_prefix='/api/mantenciones')
    app.register_blueprint(mantencion_preventiva_blueprint, url_prefix='/api/mantencion_preventiva')
    app.register_blueprint(levantamientos_blueprint, url_prefix='/api/levantamientos')
    app.register_blueprint(instalaciones_blueprint, url_prefix='/api/instalaciones')
    app.register_blueprint(servicios_blueprint, url_prefix='/api/servicios_adicionales')

    app.register_blueprint(filtro_blueprint, url_prefix='/api/filtro')
    app.register_blueprint(actas_blueprint, url_prefix='/api/actas')

    app.register_blueprint(soporte_blueprint, url_prefix='/api/soporte')
    app.register_blueprint(consultascentro_historial_bp, url_prefix='/api/consultas_centro')
    app.register_blueprint(armados_blueprint, url_prefix='/api/armados')
    app.register_blueprint(actas_entrega_blueprint, url_prefix='/api/actas_entrega')
    app.register_blueprint(permisos_trabajo_blueprint, url_prefix='/api/permisos_trabajo')
      
    
  # Ruta para servir archivos desde la carpeta `uploads`
    @app.route('/api/uploads/<path:filename>')
    def serve_uploads(filename):
        """
        Servir archivos estáticos desde la carpeta uploads.
        """
        uploads_dir = os.path.join(app.root_path, 'uploads')  # Asegura la ruta completa
        return send_from_directory(uploads_dir, filename)

    with app.app_context():
        db.create_all()
        # Compat de esquema: snapshot de numero_serie por movimiento de caja.
        db.session.execute(
            text(
                """
                ALTER TABLE armado_caja_movimientos
                ADD COLUMN IF NOT EXISTS numero_serie VARCHAR(60)
                """
            )
        )
        db.session.execute(
            text(
                """
                ALTER TABLE armados
                ADD COLUMN IF NOT EXISTS total_cajas_manual INTEGER
                """
            )
        )
        db.session.execute(
            text(
                """
                ALTER TABLE centros
                ADD COLUMN IF NOT EXISTS es_central BOOLEAN DEFAULT FALSE
                """
            )
        )
        db.session.execute(
            text(
                """
                UPDATE centros
                SET es_central = FALSE
                WHERE es_central IS NULL
                """
            )
        )
        db.session.execute(
            text(
                """
                ALTER TABLE actas_entrega
                ADD COLUMN IF NOT EXISTS firma_tecnico_1 VARCHAR(255)
                """
            )
        )
        db.session.execute(
            text(
                """
                ALTER TABLE actas_entrega
                ADD COLUMN IF NOT EXISTS firma_tecnico_2 VARCHAR(255)
                """
            )
        )
        db.session.execute(
            text(
                """
                ALTER TABLE actas_entrega
                ADD COLUMN IF NOT EXISTS firma_recepciona VARCHAR(255)
                """
            )
        )
        # Firmas en base64 pueden superar 255 caracteres; asegurar columnas tipo TEXT.
        db.session.execute(
            text(
                """
                ALTER TABLE actas_entrega
                ALTER COLUMN firma_tecnico_1 TYPE TEXT
                """
            )
        )
        db.session.execute(
            text(
                """
                ALTER TABLE actas_entrega
                ALTER COLUMN firma_tecnico_2 TYPE TEXT
                """
            )
        )
        db.session.execute(
            text(
                """
                ALTER TABLE actas_entrega
                ALTER COLUMN firma_recepciona TYPE TEXT
                """
            )
        )
        db.session.commit()

    return app
