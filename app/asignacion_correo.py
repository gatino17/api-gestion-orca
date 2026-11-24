import hashlib
import json
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path

from flask import current_app
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from sqlalchemy.exc import IntegrityError

from .database import db
from .models import AsignacionAvisoCorreo
from .permissions import get_pages_for_role_name
from .soporte_correo import AvisoCorreoError, _email, configuracion_correo, enviar_email


_templates = Environment(loader=FileSystemLoader(Path(__file__).resolve().parent / 'templates' / 'correo'),
                         autoescape=select_autoescape(['html']), undefined=StrictUndefined)


def usuario_para_aviso(data, obtener_usuario, paginas):
    solicitado = data.get('notificar_por_correo', False)
    if type(solicitado) is not bool:
        return None, ({'message': 'Notificar por correo debe ser verdadero o falso.'}, 400)
    if not solicitado:
        return None, None
    usuario = obtener_usuario()
    if not usuario:
        return None, ({'message': 'Inicia sesion para notificar por correo.'}, 401)
    if not set(paginas).intersection(get_pages_for_role_name(usuario.rol)):
        return None, ({'message': 'No tienes permiso para notificar esta asignacion.'}, 403)
    return usuario, None


def _fecha(value):
    return value.strftime('%d/%m/%Y') if value else 'Por definir'


def preparar_asignacion(registro, tipo):
    centro = registro.centro
    if tipo == 'actividad':
        perfiles = {enc.id_encargado: enc for enc in
                    [registro.encargado_principal, registro.encargado_ayudante, *(registro.encargados or [])] if enc}
        personas = [(enc.nombre_encargado, enc.user) for enc in perfiles.values()]
        numero, titulo, trabajo = registro.id_actividad, registro.area or 'Actividad', registro.nombre_actividad
        inicio, termino = registro.fecha_inicio, registro.fecha_termino
    else:
        usuarios = {p.tecnico_id: p.tecnico for p in registro.participaciones if not p.fecha_fin}
        if not usuarios and registro.tecnico:
            usuarios[registro.tecnico.id] = registro.tecnico
        personas = [(user.name, user) for user in usuarios.values() if user]
        numero, titulo, trabajo = registro.id_armado, 'Armado', registro.observacion or 'Armado del centro asignado.'
        inicio, termino = registro.fecha_inicio or registro.fecha_asignacion, registro.fecha_cierre
    destinatarios, sin_correo = {}, []
    for nombre, user in sorted(personas, key=lambda p: p[0].casefold()):
        correo = str(user.email or '').strip() if user else ''
        if _email(correo):
            destinatarios.setdefault(correo.casefold(), correo)
        else:
            sin_correo.append(nombre)
    contenido = dict(tipo=tipo, numero=numero, titulo=titulo,
                     centro=centro.nombre if centro else 'Sin centro',
                     cliente=centro.cliente.nombre if centro and centro.cliente else 'Sin cliente',
                     inicio=_fecha(inicio), termino=_fecha(termino),
                     estado=registro.estado or 'Pendiente',
                     prioridad=(registro.prioridad or 'Sin prioridad') if tipo == 'actividad' else 'No aplica',
                     trabajo=trabajo or 'Sin descripcion', asignados=[p[0] for p in sorted(personas, key=lambda p: p[0].casefold())])
    return contenido, sorted(destinatarios.values(), key=str.casefold), sin_correo


def crear_mensaje(contenido, config, mensaje_id, enviado_por):
    message = EmailMessage()
    centro = ' '.join(contenido['centro'].splitlines())
    titulo = ' '.join(contenido['titulo'].splitlines())
    message['Subject'] = f"[OrcaGest] Asignacion de {titulo} - {centro} - #{contenido['numero']}"
    message['From'] = config['sender']
    message['To'] = ', '.join(config['recipients'])
    message['Date'] = format_datetime(datetime.now(timezone.utc))
    message['Message-ID'] = mensaje_id
    message.set_content('\n'.join([
        'ORCAGEST - ASIGNACION DE TRABAJO', '',
        f"{'Actividad' if contenido['tipo'] == 'actividad' else 'Armado'}: #{contenido['numero']}",
        f"Tipo de trabajo: {contenido['titulo']}", f"Cliente: {contenido['cliente']}",
        f"Centro: {contenido['centro']}", f"Inicio: {contenido['inicio']}",
        f"Termino: {contenido['termino']}", f"Estado: {contenido['estado']}",
        f"Prioridad: {contenido['prioridad']}", f"Asignados: {', '.join(contenido['asignados'])}", '',
        'TRABAJO ASIGNADO', contenido['trabajo'], '', f'Notificado por: {enviado_por}',
        'Consulta el detalle y registra los avances en OrcaGest o en la app movil.',
    ]))
    message.add_alternative(_templates.get_template('asignacion.html').render(
        aviso=contenido, enviado_por=enviado_por), subtype='html')
    return message


def notificar_asignacion(registro, tipo, usuario):
    """Se ejecuta despues de guardar; un fallo SMTP no revierte la asignacion."""
    sin_correo = []
    try:
        contenido, destinatarios, sin_correo = preparar_asignacion(registro, tipo)
        if not destinatarios:
            return dict(estado='sin_destinatarios', sin_correo=sin_correo, destinatarios=[],
                        mensaje='No se envio el correo: los asignados no tienen una cuenta vinculada con correo valido.')
        config = configuracion_correo(destinatarios)
        snapshot = json.dumps(contenido, sort_keys=True, ensure_ascii=True)
        clave = hashlib.sha256((snapshot + json.dumps(destinatarios)).encode('utf8')).hexdigest()
        aviso = AsignacionAvisoCorreo.query.filter_by(clave=clave).first()
        if not aviso:
            aviso = AsignacionAvisoCorreo(clave=clave, contenido=snapshot,
                destinatarios=', '.join(destinatarios), enviado_por=usuario.name,
                mensaje_id=make_msgid(domain=config['sender'].split('@')[1]),
                **{tipo + '_id': contenido['numero']})
            db.session.add(aviso)
            try:
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                aviso = AsignacionAvisoCorreo.query.filter_by(clave=clave).one()
        # Solo un proceso puede enviar este mismo contenido a los mismos destinatarios.
        claimed = AsignacionAvisoCorreo.query.filter_by(id_aviso=aviso.id_aviso).filter(
            AsignacionAvisoCorreo.estado.in_(('pendiente', 'error'))
        ).update(dict(estado='enviando', error=None, fecha_intento=datetime.now(timezone.utc),
                      enviado_por=usuario.name), synchronize_session=False)
        db.session.commit()
        db.session.refresh(aviso)
        if claimed:
            try:
                enviar_email(crear_mensaje(json.loads(aviso.contenido), config, aviso.mensaje_id, usuario.name), config)
                aviso.estado, aviso.fecha_envio = 'enviado', datetime.now(timezone.utc)
            except AvisoCorreoError as exc:
                aviso.estado, aviso.error = exc.estado, str(exc)
            except Exception:
                current_app.logger.exception('No se pudo confirmar el aviso de asignacion #%s', aviso.id_aviso)
                aviso.estado, aviso.error = 'incierto', 'No se pudo confirmar el envio. Verifica los buzones antes de reenviar.'
            db.session.commit()
        if aviso.estado == 'enviado':
            mensaje = 'Correo enviado.' if claimed else 'Este aviso ya fue enviado; no se duplico el correo.'
        else:
            mensaje = aviso.error or {
                'parcial': 'El servidor rechazo parte de los destinatarios. Verifica los buzones antes de reenviar.',
                'incierto': 'No se pudo confirmar el envio. Verifica los buzones antes de reenviar.',
            }.get(aviso.estado, 'El envio esta en curso. No vuelvas a crear la asignacion.')
        if sin_correo:
            mensaje += ' Sin correo valido o cuenta vinculada: ' + ', '.join(sin_correo) + '.'
        return dict(id_aviso=aviso.id_aviso, estado=aviso.estado, destinatarios=destinatarios,
                    sin_correo=sin_correo, mensaje=mensaje, duplicado=not bool(claimed))
    except AvisoCorreoError as exc:
        return dict(estado='error', mensaje=str(exc), sin_correo=sin_correo)
    except Exception:
        db.session.rollback()
        current_app.logger.exception('Fallo al preparar el correo de asignacion')
        return dict(estado='error', sin_correo=sin_correo,
                    mensaje='La asignacion esta guardada, pero no se pudo confirmar el correo. Verifica los buzones antes de reenviar.')
