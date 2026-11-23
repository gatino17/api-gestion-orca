from sqlalchemy import func
from .models import Actividad, Mantencion, MantencionTerreno, Soporte, SoporteDocumentoMantencion


def intervenciones_por_centro(centro_ids):
    """Agrupa por soporte; solo une documentos con una referencia explicita."""
    ids = list(set(centro_ids))
    resultado = {cid: {'items': [], 'disponibles': [], 'resumen': {}} for cid in ids}
    if not ids:
        return resultado
    soportes = Soporte.query.filter(Soporte.centro_id.in_(ids), func.lower(func.trim(Soporte.tipo)) == 'terreno').all()
    manuales = Mantencion.query.filter(Mantencion.centro_id.in_(ids)).all()
    sistemas = MantencionTerreno.query.filter(MantencionTerreno.centro_id.in_(ids)).all()
    vinculos = SoporteDocumentoMantencion.query.join(Soporte).filter(Soporte.centro_id.in_(ids)).all()
    actividad_ids = {s.actividad_id for s in sistemas if s.actividad_id}
    actividades = {a.id_actividad: a for a in Actividad.query.filter(Actividad.id_actividad.in_(actividad_ids)).all()} if actividad_ids else {}
    soporte_map = {s.id_soporte: s for s in soportes}
    vinculo_map = {}
    for v in vinculos:
        tipo, did = ('manual', v.mantencion_id) if v.mantencion_id else ('sistema', v.mantencion_terreno_id)
        vinculo_map[(tipo, did)] = (v.soporte_id, v.id)
    documentos = []
    for tipo, rows in [('manual', manuales), ('sistema', sistemas)]:
        for row in rows:
            manual = tipo == 'manual'
            did = row.id_mantencion if manual else row.id_mantencion_terreno
            fecha = row.fecha_mantencion if manual else row.fecha_ingreso
            soporte_id, vinculo_id = vinculo_map.get((tipo, did), (None, None))
            actividad = actividades.get(row.actividad_id) if not manual else None
            # La actividad tambien debe pertenecer al mismo centro.
            if not soporte_id and actividad and actividad.centro_id == row.centro_id:
                soporte_id = actividad.soporte_id
            soporte = soporte_map.get(soporte_id)
            if not soporte or soporte.centro_id != row.centro_id:
                soporte_id = vinculo_id = None
            documentos.append({
                'tipo': tipo, 'id': did, 'centro_id': row.centro_id,
                'fecha': fecha.isoformat() if fecha else None,
                'responsable': row.responsable if manual else ' / '.join(filter(None, [row.tecnico_1, row.tecnico_2])),
                'observacion': row.observacion if manual else row.descripcion_trabajo,
                'disponible': bool(row.documento_mantencion) if manual else True,
                'soporte_id': soporte_id, 'vinculo_id': vinculo_id,
                'por_actividad': bool(soporte_id and not vinculo_id),
            })
    docs_por_soporte = {}
    for documento in documentos:
        docs_por_soporte.setdefault(documento['soporte_id'], []).append(documento)
    for soporte in soportes:
        docs = docs_por_soporte.get(soporte.id_soporte, [])
        resultado[soporte.centro_id]['items'].append({
            'historial_key': 'soporte-' + str(soporte.id_soporte), 'es_soporte_terreno': True,
            'id_soporte': soporte.id_soporte, 'tipo': soporte.tipo,
            'fecha_mantencion': soporte.fecha_soporte.isoformat() if soporte.fecha_soporte else None,
            'problema': soporte.problema, 'solucion': soporte.solucion, 'estado': soporte.estado,
            'cambio_equipo': soporte.cambio_equipo, 'equipo_cambiado': soporte.equipo_cambiado,
            'documentos': docs, 'falta_documento': not any(d['disponible'] for d in docs),
        })
    for doc in documentos:
        if doc['soporte_id']:
            continue
        centro = resultado[doc['centro_id']]
        centro['disponibles'].append(doc)
        centro['items'].append({
            'historial_key': doc['tipo'] + '-' + str(doc['id']),
            'fecha_mantencion': doc['fecha'], 'responsable': doc['responsable'],
            'observacion': doc['observacion'], 'documentos': [doc],
            'falta_documento': not doc['disponible'],
        })
    for centro in resultado.values():
        centro['items'].sort(key=lambda i: i['fecha_mantencion'] or '')
        casos = [i for i in centro['items'] if i.get('es_soporte_terreno')]
        centro['resumen'] = {
            'intervenciones': len(centro['items']), 'soportes': len(casos),
            'sin_documento': sum(i['falta_documento'] for i in casos),
            'documentados': sum(not i['falta_documento'] for i in casos),
            'ultima_fecha': max((i['fecha_mantencion'] for i in centro['items'] if i['fecha_mantencion']), default=None),
        }
    return resultado
