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
            recibidas.update(claves)
        if total > 0 and len(enviadas) >= total and completo is None:
            completo = guia.fecha_salida
    return {
        'total_bultos': total,
        'bultos_enviados': min(len(enviadas), total) if total else len(enviadas),
        'bultos_recibidos': min(len(recibidas), total) if total else len(recibidas),
        'completo': total > 0 and len(enviadas) >= total,
        'fecha_inicio': primera.isoformat() if primera else None,
        'fecha_ultima_salida': ultima.isoformat() if ultima else None,
        'fecha_completo': completo.isoformat() if completo else None,
    }


def puede_confirmar_instalacion(usuario, armado, tecnicos_activos):
    if not usuario:
        return False
    rol = str(usuario.rol or '').strip().lower()
    if rol in {'admin', 'operaciones'}:
        return True
    return rol == 'tecnico' and (usuario.id == armado.tecnico_id or usuario.id in tecnicos_activos)


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
