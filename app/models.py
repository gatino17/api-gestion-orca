from .database import db
from datetime import datetime
from sqlalchemy import Enum
from sqlalchemy import LargeBinary
from werkzeug.security import generate_password_hash, check_password_hash



class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    rol = db.Column(db.String(50), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Método para hashear la contraseña
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    # Método para verificar la contraseña
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Cliente(db.Model):
    __tablename__ = 'clientes'
    
    id_cliente = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(20))
    correo = db.Column(db.String(100))
    contacto = db.Column(db.String(100))
    ubicacion = db.Column(db.String(200))
    imagen = db.Column(db.LargeBinary, nullable=True)
    # Relación con las razones sociales
    razones_sociales = db.relationship('RazonSocial', backref='cliente', lazy=True)

class RazonSocial(db.Model):
    __tablename__ = 'razones_sociales'
    
    id_razon_social = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey('clientes.id_cliente'), nullable=False)
    razon_social = db.Column(db.String(100), nullable=False)

    def __init__(self, cliente_id, razon_social):
        self.cliente_id = cliente_id
        self.razon_social = razon_social

# Obtener centros
class Centro(db.Model):
    __tablename__ = 'centros'

    id_centro = db.Column(db.BigInteger, primary_key=True)  # Identificador único de cada centro
    nombre = db.Column(db.String(100), nullable=False)  # Nombre del centro
    nombre_ponton = db.Column(db.String(100), nullable=True)  # Nombre del pontón del centro
    ubicacion = db.Column(db.String(255), nullable=True)  # Ubicación del centro
    correo_centro = db.Column(db.String(100), nullable=True)  # Correo electrónico del centro
    area = db.Column(db.String(50), nullable=True)  # Área del centro
    telefono = db.Column(db.String(20), nullable=True)  # Teléfono de contacto del centro
    cliente_id = db.Column(db.BigInteger, db.ForeignKey('clientes.id_cliente'), nullable=False)  # ID del cliente asociado
    razon_social_id = db.Column(db.BigInteger, db.ForeignKey('razones_sociales.id_razon_social'), nullable=False)  # ID de la razón social asociada
    created_at = db.Column(db.DateTime, default=db.func.now())  # Fecha y hora de creación automática al momento de insertar
    fecha_instalacion = db.Column(db.Date, nullable=True)
    fecha_activacion = db.Column(db.Date, nullable=True)  # Fecha en que se activa el centro
    fecha_termino = db.Column(db.Date, nullable=True)  # Fecha en que se termina el contrato
    cantidad_radares = db.Column(db.Integer, nullable=True)  # Cantidad de radares en el centro
    cantidad_camaras = db.Column(db.Integer, nullable=True)  # Cantidad de cámaras en el centro
    base_tierra = db.Column(db.Boolean, nullable=True)  # Indica si el centro tiene una base en tierra
    respaldo_adicional = db.Column(db.Boolean, nullable=True)  # Indica si el centro tiene respaldo adicional
    valor_contrato = db.Column(db.Numeric(10, 2), nullable=True)  # Valor del contrato, almacenado con dos decimales
    estado = db.Column(db.String(10), default='activo')  # Estado del centro ('activo', 'traslado', 'cese', 'retirado')

    # Relación con otras tablas (opcional, para facilitar consultas)
    cliente = db.relationship('Cliente', backref='centros', lazy='joined')
    razon_social = db.relationship('RazonSocial', backref='centros', lazy='joined')

    def __repr__(self):
        return f"<Centro {self.nombre}>"
    

#tabla equipos y conecxion especiales
class EquiposIP(db.Model):
    __tablename__ = 'equipos_ip'

    id_equipo = db.Column(db.Integer, primary_key=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro', ondelete="CASCADE"), nullable=False)
    nombre = db.Column(db.String(50), nullable=False)
    ip = db.Column(db.String(15), nullable=True)
    observacion = db.Column(db.Text, nullable=True)
    codigo = db.Column(db.String(20), nullable=True)
    numero_serie = db.Column(db.String(30), nullable=True)
    estado = db.Column(db.String(20), nullable=True)

    # Relación con Centro
    centro = db.relationship('Centro', backref=db.backref('equipos_ip', cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<EquiposIP {self.nombre} en centro {self.centro_id}>"


class ConexionesEspeciales(db.Model):
    __tablename__ = 'conexiones_especiales'

    id = db.Column(db.Integer, primary_key=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro', ondelete="CASCADE"), nullable=False)
    nombre = db.Column(db.String(50), nullable=False)
    numero_conexion = db.Column(db.String(20), nullable=False)

    # Relación con Centro
    centro = db.relationship('Centro', backref=db.backref('conexiones_especiales', cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<ConexionesEspeciales {self.nombre} en centro {self.centro_id}>"


# Modelo de Encargados
class Encargado(db.Model):
    __tablename__ = 'encargados'
    
    id_encargado = db.Column(db.Integer, primary_key=True)
    nombre_encargado = db.Column(db.String(100), nullable=False)
    telefono = db.Column(db.String(15), nullable=True)
    direccion = db.Column(db.String(255), nullable=True)
    especialidad = db.Column(db.String(100), nullable=True)
    licencia_conducir = db.Column(db.Boolean, nullable=True)
    
 # Tabla de asociación para la relación muchos a muchos
actividades_encargados = db.Table('actividades_encargados',
    db.Column('actividad_id', db.Integer, db.ForeignKey('actividades.id_actividad'), primary_key=True),
    db.Column('encargado_id', db.Integer, db.ForeignKey('encargados.id_encargado'), primary_key=True)
)

class Actividad(db.Model):
    __tablename__ = 'actividades'

    id_actividad = db.Column(db.Integer, primary_key=True)
    nombre_actividad = db.Column(db.String(100), nullable=False)
    fecha_reclamo = db.Column(db.Date)
    fecha_inicio = db.Column(db.Date)
    fecha_termino = db.Column(db.Date)
    area = db.Column(db.String(100))
    prioridad = db.Column(db.String(50))
    tecnico_encargado = db.Column(db.Integer, db.ForeignKey('encargados.id_encargado'))
    tecnico_ayudante = db.Column(db.Integer, db.ForeignKey('encargados.id_encargado'))
    tiempo_en_dar_solucion = db.Column(db.Integer)
    estado = db.Column(db.String(50))
    
    # Referencias a centros
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'))
    cliente = db.Column(db.String(100))
    estado_del_centro = db.Column(db.String(50))
    
    # Relaciones con Encargado
    encargado_principal = db.relationship('Encargado', foreign_keys=[tecnico_encargado], backref='actividades_asignadas_principal')
    encargado_ayudante = db.relationship('Encargado', foreign_keys=[tecnico_ayudante], backref='actividades_asignadas_ayudante')
    
    # Relación muchos a muchos con encargados mediante actividades_encargados
    encargados = db.relationship('Encargado', secondary=actividades_encargados, backref='actividades')

    # Relación con Centro
    centro = db.relationship('Centro', backref='actividades')

    def __repr__(self):
        return f"<Actividad {self.nombre_actividad} en centro {self.centro_id}>"



#tabla retiros
class Retiro(db.Model):
    __tablename__ = 'retiros'

    id_retiro = db.Column(db.Integer, primary_key=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    fecha_de_retiro = db.Column(db.Date, nullable=False)
    observacion = db.Column(db.Text, nullable=True)
    precio = db.Column(db.Numeric(10, 2), nullable=True)
    documento = db.Column(db.String(255), nullable=True)  # Ruta del archivo en el sistema de archivos

    centro = db.relationship('Centro', backref=db.backref('retiros', lazy=True))

    def __repr__(self):
        return f"<Retiro {self.id_retiro} del Centro {self.centro_id}>"

#tabla ceses
class Cese(db.Model):
    __tablename__ = 'ceses'

    id_cese = db.Column(db.Integer, primary_key=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    fecha_cese = db.Column(db.Date, nullable=False)
    documento_cese = db.Column(db.String(255), nullable=True)

    # Relación con la tabla centros
    centro = db.relationship('Centro', backref=db.backref('ceses', cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<Cese(id_cese={self.id_cese}, centro_id={self.centro_id}, fecha_cese={self.fecha_cese}, documento_cese={self.documento_cese})>"
    

#tabla inventarios

class Inventario(db.Model):
    __tablename__ = 'inventarios'

    id_inventario = db.Column(db.Integer, primary_key=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    documento = db.Column(db.String(255), nullable=True)

    # Relación con la tabla centros
    centro = db.relationship('Centro', backref=db.backref('inventarios', cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<Inventario(id_inventario={self.id_inventario}, centro_id={self.centro_id}, documento={self.documento})>"


#tabla traslado
class Traslado(db.Model):
    __tablename__ = 'traslados'

    id_traslado = db.Column(db.Integer, primary_key=True)
    centro_origen_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    centro_destino_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    fecha_traslado = db.Column(db.Date, nullable=False)
    fecha_monitoreo = db.Column(db.Date, nullable=True)
    documento_asociado = db.Column(db.String(255), nullable=True)
    tipo_traslado = db.Column(db.String(100), nullable=True)
    observacion = db.Column(db.Text, nullable=True)

    # Relación con la tabla centros
    centro_origen = db.relationship(
        'Centro',
        foreign_keys=[centro_origen_id],
        backref=db.backref('traslados_origen', cascade="all, delete-orphan")
    )
    centro_destino = db.relationship(
        'Centro',
        foreign_keys=[centro_destino_id],
        backref=db.backref('traslados_destino', cascade="all, delete-orphan")
    )

    def __repr__(self):
        return (f"<Traslado(id_traslado={self.id_traslado}, centro_origen_id={self.centro_origen_id}, "
                f"centro_destino_id={self.centro_destino_id}, fecha_traslado={self.fecha_traslado}, "
                f"fecha_monitoreo={self.fecha_monitoreo}, documento_asociado={self.documento_asociado}, "
                f"tipo_traslado={self.tipo_traslado}, observacion={self.observacion})>")


# Tabla levantamientos
class Levantamiento(db.Model):
    __tablename__ = 'levantamientos'

    id_levantamiento = db.Column(db.Integer, primary_key=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    fecha_levantamiento = db.Column(db.Date, nullable=False)
    documento_asociado = db.Column(db.String(255), nullable=True)

    # Relación con la tabla centros
    centro = db.relationship('Centro', backref=db.backref('levantamientos', cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<Levantamiento(id_levantamiento={self.id_levantamiento}, centro_id={self.centro_id}, fecha_levantamiento={self.fecha_levantamiento}, documento_asociado={self.documento_asociado})>"


# Tabla mantenciones
class Mantencion(db.Model):
    __tablename__ = 'mantenciones'

    id_mantencion = db.Column(db.Integer, primary_key=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    fecha_mantencion = db.Column(db.Date, nullable=False)
    responsable = db.Column(db.String(255), nullable=False)
    documento_mantencion = db.Column(db.String(255), nullable=True)
    observacion = db.Column(db.Text, nullable=True)

    # Relación con la tabla centros
    centro = db.relationship('Centro', backref=db.backref('mantenciones', cascade="all, delete-orphan"))

    def __repr__(self):
        return (
            f"<Mantencion(id_mantencion={self.id_mantencion}, centro_id={self.centro_id}, "
            f"fecha_mantencion={self.fecha_mantencion}, responsable='{self.responsable}', "
            f"documento_mantencion='{self.documento_mantencion}', observacion='{self.observacion}')>"
        )

# Tabla instalaciones nuevas
class InstalacionNueva(db.Model):
    __tablename__ = 'instalaciones_nuevas'

    id_instalacion = db.Column(db.Integer, primary_key=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    fecha_instalacion = db.Column(db.Date, nullable=False)
    inicio_monitoreo = db.Column(db.Date, nullable=False)
    documento_acta = db.Column(db.String(255), nullable=True)
    observacion = db.Column(db.Text, nullable=True)

    # Relación con la tabla centros
    centro = db.relationship('Centro', backref=db.backref('instalaciones_nuevas', cascade="all, delete-orphan"))

    def __repr__(self):
        return (
            f"<InstalacionNueva(id_instalacion={self.id_instalacion}, centro_id={self.centro_id}, "
            f"fecha_instalacion={self.fecha_instalacion}, inicio_monitoreo={self.inicio_monitoreo}, "
            f"documento_acta='{self.documento_acta}', observacion='{self.observacion}')>"
        )


# Tabla Servicios Adicionales
class ServiciosAdicionales(db.Model):
    __tablename__ = 'servicios_adicionales'

    id_servicio = db.Column(db.Integer, primary_key=True)
    id_razon_social = db.Column(db.Integer, db.ForeignKey('razones_sociales.id_razon_social'), nullable=False)
    fecha_instalacion = db.Column(db.Date, nullable=False)
    inicio_monitoreo = db.Column(db.Date, nullable=False)
    documento_asociado = db.Column(db.String(255), nullable=True)
    observaciones = db.Column(db.Text, nullable=True)

    # Relación con la tabla razones_sociales
    razon_social = db.relationship('RazonSocial', backref=db.backref('servicios_adicionales', cascade="all, delete-orphan"))

    def __repr__(self):
        return (
            f"<ServiciosAdicionales(id_servicio={self.id_servicio}, id_razon_social={self.id_razon_social}, "
            f"fecha_instalacion={self.fecha_instalacion}, inicio_monitoreo={self.inicio_monitoreo}, "
            f"documento_asociado='{self.documento_asociado}', observaciones='{self.observaciones}')>"
        )


# Tabla Soporte
class Soporte(db.Model):
    __tablename__ = 'soporte'

    id_soporte = db.Column(db.Integer, primary_key=True, autoincrement=True)
    centro_id = db.Column(db.Integer, db.ForeignKey('centros.id_centro'), nullable=False)
    problema = db.Column(db.Text, nullable=False)
    tipo = db.Column(db.String(10), nullable=False)  # 'terreno' o 'remoto'
    fecha_soporte = db.Column(db.Date, nullable=False)
    solucion = db.Column(db.Text, nullable=True)
    categoria_falla = db.Column(db.String(50), nullable=True)
    cambio_equipo = db.Column(db.Boolean, default=False)
    equipo_cambiado = db.Column(db.String(100), nullable=True)
    estado = db.Column(db.String(20), default='pendiente')  # <---
    fecha_cierre = db.Column(db.Date, nullable=True)  

    # Relación con la tabla centros
    centro = db.relationship('Centro', backref=db.backref('soportes', cascade="all, delete-orphan"))

    def __repr__(self):
        return (
            f"<Soporte(id_soporte={self.id_soporte}, centro_id={self.centro_id}, problema='{self.problema}', "
            f"tipo='{self.tipo}', fecha_soporte={self.fecha_soporte}, solucion='{self.solucion}', "
            f"categoria_falla='{self.categoria_falla}', cambio_equipo={self.cambio_equipo}, "
            f"equipo_cambiado='{self.equipo_cambiado}', estado='{self.estado}', fecha_cierre={self.fecha_cierre})>"
        )



