from flask import Blueprint, request, jsonify
from ..models import  Actividad, Centro, Encargado
from ..database import db
from datetime import datetime
actividades_blueprint = Blueprint('actividades', __name__)

# Crear nueva actividad
@actividades_blueprint.route('/', methods=['POST'])
def crear_actividad():
    data = request.json
    nueva_actividad = Actividad(
        nombre_actividad=data.get('nombre_actividad'),
        fecha_reclamo=data.get('fecha_reclamo'),
        fecha_inicio=data.get('fecha_inicio'),
        fecha_termino=data.get('fecha_termino'),
        area=data.get('area'),
        prioridad=data.get('prioridad'),
        tecnico_encargado=data.get('tecnico_encargado'),  # ID del encargado principal (opcional)
        tecnico_ayudante=data.get('tecnico_ayudante'),    # ID del ayudante (opcional)
        tiempo_en_dar_solucion=data.get('tiempo_en_dar_solucion'),
        estado=data.get('estado'),
        centro_id=data.get('centro_id')  # ID del centro (opcional)
    )

    db.session.add(nueva_actividad)
    db.session.commit()
    return jsonify({"message": "Actividad creada exitosamente", "id_actividad": nueva_actividad.id_actividad}), 201

# Listar todas las actividades
@actividades_blueprint.route('/', methods=['GET'])
def obtener_actividades():
    actividades = Actividad.query.all()
    resultado = []
    for actividad in actividades:
        resultado.append({
            "id_actividad": actividad.id_actividad,
            "nombre_actividad": actividad.nombre_actividad,
            "fecha_reclamo": actividad.fecha_reclamo,
            "fecha_inicio": actividad.fecha_inicio,
            "fecha_termino": actividad.fecha_termino,
            "area": actividad.area,
            "prioridad": actividad.prioridad,
            "tiempo_en_dar_solucion": actividad.tiempo_en_dar_solucion,
            "estado": actividad.estado,
            "centro": {
                "id_centro": actividad.centro.id_centro if actividad.centro else None,
                "nombre": actividad.centro.nombre if actividad.centro else None,
                "cliente": actividad.centro.cliente.nombre if actividad.centro and actividad.centro.cliente else None,
                "estado_del_centro": actividad.centro.estado if actividad.centro else None
            },
            "encargado_principal": {
                "id_encargado": actividad.encargado_principal.id_encargado if actividad.encargado_principal else None,
                "nombre_encargado": actividad.encargado_principal.nombre_encargado if actividad.encargado_principal else None
            },
            "encargado_ayudante": {
                "id_encargado": actividad.encargado_ayudante.id_encargado if actividad.encargado_ayudante else None,
                "nombre_encargado": actividad.encargado_ayudante.nombre_encargado if actividad.encargado_ayudante else None
            }
        })
    return jsonify(resultado), 200

# Actualizar actividad
@actividades_blueprint.route('/<int:id_actividad>', methods=['PUT'])
def actualizar_actividad(id_actividad):
    data = request.json
    actividad = Actividad.query.get_or_404(id_actividad)

    actividad.nombre_actividad = data.get('nombre_actividad', actividad.nombre_actividad)
    actividad.fecha_reclamo = data.get('fecha_reclamo', actividad.fecha_reclamo)
    actividad.fecha_inicio = data.get('fecha_inicio', actividad.fecha_inicio)
    actividad.fecha_termino = data.get('fecha_termino', actividad.fecha_termino)
    actividad.area = data.get('area', actividad.area)
    actividad.prioridad = data.get('prioridad', actividad.prioridad)
    actividad.tecnico_encargado = data.get('tecnico_encargado', actividad.tecnico_encargado)
    actividad.tecnico_ayudante = data.get('tecnico_ayudante', actividad.tecnico_ayudante)
    actividad.tiempo_en_dar_solucion = data.get('tiempo_en_dar_solucion', actividad.tiempo_en_dar_solucion)
    actividad.estado = data.get('estado', actividad.estado)
    actividad.centro_id = data.get('centro_id', actividad.centro_id)

    db.session.commit()
    return jsonify({"message": "Actividad actualizada exitosamente"}), 200

# Eliminar actividad
@actividades_blueprint.route('/<int:id_actividad>', methods=['DELETE'])
def eliminar_actividad(id_actividad):
    actividad = Actividad.query.get_or_404(id_actividad)
    db.session.delete(actividad)
    db.session.commit()
    return jsonify({"message": "Actividad eliminada exitosamente"}), 200
