from datetime import datetime, timezone
import json
import re
import unicodedata

import pytz


def hoy_chile():
    return datetime.now(pytz.timezone('America/Santiago')).date()


def clave_bulto(value):
    nombre = ''.join(c for c in unicodedata.normalize('NFD', str(value or '').strip().lower()) if unicodedata.category(c) != 'Mn')
    if nombre in {'', 'pendiente de caja', 'pendiente de bulto', 'sin caja', 'sin bulto', 'pendiente', 'n/a'}:
        return None
    match = re.match(r'^(?:caja|bulto)\s*(\d+)', nombre)
    return 'caja_' + str(int(match.group(1))) if match else nombre


def resumen_despacho(guias, cajas, total_manual=0, hoy=None):
    hoy = hoy or hoy_chile()
    esperadas = {clave for clave in (clave_bulto(caja) for caja in cajas) if clave}
    total = len(esperadas) or max(0, int(total_manual or 0))
    enviadas, recibidas = set(), set()
    fechas_recepcion = {}
    primera, ultima, completo = None, None, None
    validas = [guia for guia in guias if str(guia.estado or '').strip().lower() in {'en_transito_centro', 'recepcionado_en_centro'}
               and guia.fecha_salida and guia.fecha_salida <= hoy]
    for guia in sorted(validas, key=lambda item: (item.fecha_salida, item.id_guia_salida or 0)):
        try:
            cajas_guia = json.loads(guia.cajas_json or '[]')
        except (ValueError, TypeError):
            cajas_guia = []
        if not isinstance(cajas_guia, list):
            continue
        claves = {clave for clave in (clave_bulto(caja) for caja in cajas_guia) if clave}
        if esperadas:
            claves &= esperadas
        if not claves:
            continue
        enviadas.update(claves)
        primera = primera or guia.fecha_salida
        ultima = guia.fecha_salida
        if str(guia.estado or '').strip().lower() == 'recepcionado_en_centro':
            instante = getattr(guia, 'fecha_recepcion_centro', None)
            if instante and instante.tzinfo is None:
                instante = instante.replace(tzinfo=timezone.utc)
            fecha = instante.astimezone(pytz.timezone('America/Santiago')).date() if instante else None
            if fecha is None or fecha <= hoy:
                recibidas.update(claves)
                for clave in claves:
                    if fecha and (clave not in fechas_recepcion or fecha < fechas_recepcion[clave]):
                        fechas_recepcion[clave] = fecha
        if total > 0 and len(enviadas) >= total and completo is None:
            completo = guia.fecha_salida
    recepcion_completa = total > 0 and len(recibidas) >= total
    inicio_recepcion = min(fechas_recepcion.values()) if fechas_recepcion else None
    # Legacy received guides may have no timestamp; never invent their receipt date.
    fin_recepcion = (max(fechas_recepcion.values())
                     if recepcion_completa and len(fechas_recepcion) == len(recibidas) else None)
    return {
        'total_bultos': total,
        'bultos_enviados': min(len(enviadas), total) if total else len(enviadas),
        'bultos_recibidos': min(len(recibidas), total) if total else len(recibidas),
        'completo': total > 0 and len(enviadas) >= total,
        'fecha_inicio': primera.isoformat() if primera else None,
        'fecha_ultima_salida': ultima.isoformat() if ultima else None,
        'fecha_completo': completo.isoformat() if completo else None,
        'recepcion_completa': recepcion_completa,
        'fecha_recepcion_inicio': inicio_recepcion.isoformat() if inicio_recepcion else None,
        'fecha_recepcion_completa': fin_recepcion.isoformat() if fin_recepcion else None,
    }


def normalizar_estado(value):
    return ''.join(c for c in unicodedata.normalize('NFD', str(value or '').strip().lower())
                   if unicodedata.category(c) != 'Mn')


def actividad_instalacion_vigente(armado, vinculos):
    actividades = [item.actividad for item in vinculos if item.actividad
                   and item.actividad.centro_id == armado.centro_id
                   and normalizar_estado(item.actividad.area) == 'instalacion'
                   and normalizar_estado(item.actividad.estado) not in {'cancelado', 'cancelada', 'anulado', 'anulada'}]
    return max(actividades, key=lambda item: item.id_actividad or 0) if actividades else None


def instaladores_actividad(actividad):
    if not actividad:
        return []
    resultado, vistos = [], set()
    for encargado in [actividad.encargado_principal, actividad.encargado_ayudante, *(actividad.encargados or [])]:
        if encargado and encargado.id_encargado not in vistos:
            vistos.add(encargado.id_encargado)
            resultado.append(encargado)
    return resultado


def serializar_asignacion(actividad):
    if not actividad:
        return None
    tecnicos = instaladores_actividad(actividad)
    return {
        'actividad_id': actividad.id_actividad, 'nombre': actividad.nombre_actividad,
        'fecha_inicio': actividad.fecha_inicio.isoformat() if actividad.fecha_inicio else None,
        'fecha_termino': actividad.fecha_termino.isoformat() if actividad.fecha_termino else None,
        'estado': actividad.estado,
        'asignada': bool(tecnicos and actividad.fecha_inicio),
        'instaladores': [{'id_encargado': item.id_encargado, 'nombre': item.nombre_encargado} for item in tecnicos],
    }


def puede_confirmar_instalacion(usuario, actividad):
    if not usuario:
        return False
    rol = str(usuario.rol or '').strip().lower()
    if rol in {'admin', 'operaciones'}:
        return True
    return rol == 'tecnico' and any(item.user_id == usuario.id for item in instaladores_actividad(actividad))


def serializar_instalacion(registro):
    if not registro:
        return None
    instante = registro.confirmado_at
    if instante and instante.tzinfo is None:
        instante = instante.replace(tzinfo=timezone.utc)
    return {
        'armado_id': registro.armado_id,
        'fecha_instalacion': registro.fecha_instalacion.isoformat(),
        'acta_entrega_id': registro.acta_entrega_id,
        'confirmado_por_nombre': registro.confirmado_por_nombre,
        'confirmado_at': instante.isoformat() if instante else None,
        'observacion': registro.observacion,
    }


def instalacion_desde_informe(armado, acta, permiso):
    if (permiso.acta_entrega_id != acta.id_acta_entrega or permiso.centro_id != acta.centro_id
            or (armado and (acta.armado_id != armado.id_armado or acta.centro_id != armado.centro_id))
            or normalizar_estado(acta.tipo_instalacion) != 'instalacion'):
        return None
    fecha = permiso.fecha_salida
    fechas_previas = [valor for valor in (permiso.fecha_ingreso, acta.fecha_registro,
                     getattr(armado, 'fecha_asignacion', None), getattr(armado, 'fecha_inicio', None),
                     getattr(armado, 'fecha_cierre', None)) if valor]
    if not fecha or fecha > hoy_chile() or any(fecha < valor for valor in fechas_previas):
        return None

    def campo(nombre):
        return str(getattr(permiso, nombre, None) or getattr(acta, nombre, None) or '').strip()

    if not all(campo(nombre) for nombre in ('tecnico_1', 'firma_tecnico_1', 'recepciona_nombre', 'firma_recepciona')):
        return None
    if campo('tecnico_2') and not campo('firma_tecnico_2'):
        return None
    extras = permiso.firmas_tecnicos_adicionales or acta.firmas_tecnicos_adicionales
    try:
        extras = json.loads(extras) if isinstance(extras, str) else extras or []
    except (TypeError, ValueError):
        return None
    if not isinstance(extras, list) or any(not isinstance(item, dict) or
            (str(item.get('nombre') or '').strip() and not str(item.get('firma') or '').strip()) for item in extras):
        return None
    if not str(permiso.descripcion_trabajo or '').strip():
        return None
    actualizaciones = [valor.replace(tzinfo=timezone.utc) if valor.tzinfo is None else valor
                       for valor in (acta.updated_at, permiso.updated_at) if valor]
    fecha_registro = (max(actualizaciones).astimezone(pytz.timezone('America/Santiago')).date()
                      if actualizaciones else fecha)
    return {
        'armado_id': acta.armado_id,
        'fecha_instalacion': fecha.isoformat(),
        'acta_entrega_id': acta.id_acta_entrega,
        'permiso_trabajo_id': permiso.id_permiso_trabajo,
        'origen': 'informe_instalacion',
        'tecnicos': list(dict.fromkeys(nombre for nombre in [campo('tecnico_1'), campo('tecnico_2'),
                         *(str(item.get('nombre') or '').strip() for item in extras)] if nombre)),
        'fecha_registro_seguimiento': fecha_registro.isoformat(),
        'confirmado_por_nombre': None,
        'confirmado_at': None,
        'observacion': permiso.descripcion_trabajo,
    }


def fechas_termino_instalacion(actividades):
    from sqlalchemy import or_
    from sqlalchemy.orm import joinedload, selectinload
    from .models import ActaEntrega, ArmadoInstalacionConfirmada

    elegibles = {item.id_actividad: item for item in actividades
                 if item.id_actividad and not item.fecha_termino and not item.soporte_id
                 and normalizar_estado(item.area) == 'instalacion'
                 and normalizar_estado(item.estado) not in {'cancelado', 'cancelada', 'anulado', 'anulada'}}
    if not elegibles:
        return {}
    por_armado = {item.vinculo_instalacion.armado_id: item for item in elegibles.values()
                  if item.vinculo_instalacion and item.vinculo_instalacion.armado
                  and item.vinculo_instalacion.armado.centro_id == item.centro_id}
    fechas = {}
    for registro in ArmadoInstalacionConfirmada.query.filter(ArmadoInstalacionConfirmada.armado_id.in_(por_armado)).all():
        actividad = por_armado[registro.armado_id]
        if not actividad.fecha_inicio or registro.fecha_instalacion >= actividad.fecha_inicio:
            fechas[actividad.id_actividad] = registro.fecha_instalacion

    manuales = set(fechas)
    actas = ActaEntrega.query.populate_existing().options(joinedload(ActaEntrega.armado), selectinload(ActaEntrega.permisos_trabajo)).filter(
        ActaEntrega.tipo_instalacion == 'instalacion',
        or_(ActaEntrega.actividad_id.in_(elegibles), ActaEntrega.armado_id.in_(por_armado)),
    ).all()
    for acta in actas:
        # Prefer the report's explicit activity; never associate by center alone.
        actividad = elegibles.get(acta.actividad_id) if acta.actividad_id else por_armado.get(acta.armado_id)
        if not actividad or actividad.centro_id != acta.centro_id or actividad.id_actividad in manuales:
            continue
        vinculo = actividad.vinculo_instalacion
        if vinculo and vinculo.armado_id != acta.armado_id:
            continue
        completos = [dato for permiso in acta.permisos_trabajo
                     for dato in [instalacion_desde_informe(acta.armado, acta, permiso)] if dato]
        fechas_validas = [datetime.strptime(item['fecha_instalacion'], '%Y-%m-%d').date() for item in completos]
        fechas_validas = [fecha for fecha in fechas_validas if not actividad.fecha_inicio or fecha >= actividad.fecha_inicio]
        if fechas_validas:
            fecha = max(fechas_validas)
            fechas[actividad.id_actividad] = max(fecha, fechas.get(actividad.id_actividad, fecha))
    return fechas


def completar_termino_desde_informe(acta):
    from sqlalchemy.orm import joinedload
    from .database import db
    from .models import Actividad, ArmadoActividadInstalacion

    if not acta or (not acta.actividad_id and not acta.armado_id):
        return []
    db.session.flush()
    query = Actividad.query.options(joinedload(Actividad.vinculo_instalacion).joinedload(ArmadoActividadInstalacion.armado))
    if acta.actividad_id:
        query = query.filter_by(id_actividad=acta.actividad_id)
    else:
        query = query.filter(Actividad.vinculo_instalacion.has(armado_id=acta.armado_id))
    actividades = query.all()
    fechas = fechas_termino_instalacion(actividades)
    for actividad in actividades:
        if actividad.id_actividad in fechas:
            actividad.fecha_termino = fechas[actividad.id_actividad]
    return list(fechas)


def notificar_cambio_informe(armado_ids, actividad_ids=()):
    from .socketio_ext import emit_armado_event, emit_actividad_event

    for armado_id in set(armado_ids) - {None}:
        emit_armado_event('armado_updated', {
            'armado_id': armado_id, 'tipo': 'informe_instalacion',
            'ts': datetime.now(timezone.utc).isoformat(),
        })
    for actividad_id in set(actividad_ids):
        emit_actividad_event('actividad_updated', {'action': 'updated', 'id_actividad': actividad_id})
