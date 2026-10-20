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
