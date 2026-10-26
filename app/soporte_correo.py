import hashlib
import json
import os
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid

from flask import current_app
from sqlalchemy.exc import IntegrityError

from .database import db
from .models import SoporteAvisoTerreno
from .soporte_plantilla import renderizar_aviso_terreno


class AvisoCorreoError(Exception):
    def __init__(self, message, estado='error'):
        super().__init__(message)
        self.estado = estado


def elegible_aviso(soporte):
    return (str(soporte.tipo or '').lower() == 'terreno'
            and str(soporte.estado or '').lower() in ('pendiente', 'en_proceso')
            and not soporte.fecha_cierre)


def _setting(name, default=None):
    return current_app.config.get(name, os.environ.get(name, default))


def _boolean(value):
    return str(value).lower() in ('1', 'true', 'yes', 'si')


def _email(value):
    return bool(re.fullmatch(r'[^\s<>@,;]+@[^\s<>@,;]+\.[^\s<>@,;]+', value))


def configuracion_correo():
    recipients = list(dict.fromkeys(part.strip() for part in str(
        _setting('SOPORTE_TERRENO_DESTINATARIOS', 'soporte@orcatecnologia.cl')
    ).replace(';', ',').split(',') if part.strip()))
    sender = str(_setting('SMTP_FROM') or _setting('SMTP_USERNAME') or '').strip()
    host = str(_setting('SMTP_HOST') or '').strip()
    use_ssl = _boolean(_setting('SMTP_USE_SSL', False))
    use_tls = _boolean(_setting('SMTP_USE_TLS', not use_ssl))
    if not host or not _email(sender) or not recipients or not all(map(_email, recipients)):
        raise AvisoCorreoError('El envio de correo no esta configurado. Solicita al administrador configurar SMTP.')
    if _setting('SMTP_USERNAME') and not _setting('SMTP_PASSWORD'):
        raise AvisoCorreoError('Falta configurar la credencial SMTP en el servidor. En Gmail usa una contrasena de aplicacion.')
    if not use_ssl and not use_tls:
        raise AvisoCorreoError('El servidor de correo debe utilizar TLS o SSL.')
    try:
        port = int(_setting('SMTP_PORT', 465 if use_ssl else 587))
        if not 1 <= port <= 65535:
            raise ValueError()
    except (TypeError, ValueError):
        raise AvisoCorreoError('El puerto SMTP configurado no es valido.') from None
    return dict(host=host, port=port, sender=sender, recipients=recipients, use_ssl=use_ssl,
                use_tls=use_tls, username=_setting('SMTP_USERNAME'), password=_setting('SMTP_PASSWORD'))


def enviar_mensaje(contenido, config, mensaje_id, enviado_por):
    message = EmailMessage()
    center = ' '.join(str(contenido['centro']).splitlines())
    message['Subject'] = f"[OrcaGest] Soporte en terreno pendiente - {center} - #{contenido['id_soporte']}"
    message['From'] = config['sender']
    message['To'] = ', '.join(config['recipients'])
    message['Date'] = format_datetime(datetime.now(timezone.utc))
    message['Message-ID'] = mensaje_id
    message.set_content('\n'.join([
        'SOPORTE EN TERRENO PENDIENTE', '',
        f"Soporte: #{contenido['id_soporte']}", f"Cliente: {contenido['cliente']}",
        f"Centro: {contenido['centro']}", f"Area: {contenido['area']}",
        f"Fecha de registro: {contenido['fecha']}", f"Prioridad: {contenido['prioridad']}",
        f"Estado: {'Pendiente' if contenido['estado'] == 'pendiente' else 'En seguimiento'}", f"Registrado por: {contenido['creado_por']}",
        f'Notificado por: {enviado_por}', '', 'PROBLEMA', contenido['problema'], '',
        'SUGERENCIA PARA REVISION EN TERRENO', contenido['sugerencia'], '',
        'La sugerencia orienta la visita; no representa una reparacion ya realizada.',
    ]))
    message.add_alternative(renderizar_aviso_terreno(contenido, enviado_por), subtype='html')
    sending = False
    try:
        context = ssl.create_default_context()
        server = (smtplib.SMTP_SSL(config['host'], config['port'], timeout=15, context=context)
                  if config['use_ssl'] else smtplib.SMTP(config['host'], config['port'], timeout=15))
        with server:
            server.ehlo()
            if config['use_tls'] and not config['use_ssl']:
                server.starttls(context=context)
                server.ehlo()
            if config['username']:
                server.login(config['username'], config['password'] or '')
            sending = True
            refused = server.send_message(message)
            if refused:
                raise AvisoCorreoError('El servidor rechazo parte de los destinatarios. Verifica el buzon antes de reenviar.', 'parcial')
    except AvisoCorreoError:
        raise
    except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
            smtplib.SMTPDataError, smtplib.SMTPNotSupportedError) as exc:
        current_app.logger.warning('Aviso terreno rechazado por SMTP (%s)', type(exc).__name__)
        raise AvisoCorreoError('El servidor de correo rechazo el envio. Revisa la configuracion y reintenta.') from None
    except (OSError, smtplib.SMTPException) as exc:
        current_app.logger.warning('Fallo de conexion SMTP en aviso terreno (%s)', type(exc).__name__)
        if sending:
            raise AvisoCorreoError('No se pudo confirmar el envio. Verifica el buzon de soporte antes de reenviar.', 'incierto') from None
        raise AvisoCorreoError('No se pudo conectar con el servidor de correo. Puedes reintentar.') from None


def serializar_aviso(aviso):
    if not aviso:
        return None
    return dict(id_aviso=aviso.id_aviso, estado=aviso.estado, error=aviso.error,
                destinatarios=aviso.destinatarios, enviado_por=aviso.enviado_por,
                fecha_envio=aviso.fecha_envio.isoformat() if aviso.fecha_envio else None)


def notificar_terreno(soporte, usuario):
    config = configuracion_correo()
    centro = soporte.centro
    contenido = dict(id_soporte=soporte.id_soporte,
        cliente=centro.cliente.nombre if centro and centro.cliente else '-',
        centro=centro.nombre if centro else '-', area=(centro.area or '-') if centro else '-',
        fecha=soporte.fecha_soporte.isoformat() if soporte.fecha_soporte else '-',
        prioridad=soporte.prioridad or 'media', estado=soporte.estado,
        creado_por=soporte.creado_por_nombre or 'Sin registro',
        problema=soporte.problema.strip(), sugerencia=soporte.sugerencia.strip())
    snapshot = json.dumps(contenido, sort_keys=True, ensure_ascii=True)
    recipients = ', '.join(config['recipients'])
    clave = hashlib.sha256((snapshot + recipients).encode('utf8')).hexdigest()
    aviso = SoporteAvisoTerreno.query.filter_by(clave=clave).first()
    if not aviso:
        aviso = SoporteAvisoTerreno(soporte_id=soporte.id_soporte, clave=clave, contenido=snapshot,
            destinatarios=recipients, mensaje_id=make_msgid(domain=config['sender'].split('@')[1]),
            estado='pendiente', enviado_por=usuario.name)
        db.session.add(aviso)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            aviso = SoporteAvisoTerreno.query.filter_by(clave=clave).one()
    # Atomic claim across workers: a double click or concurrent retry must not send twice.
    claimed = SoporteAvisoTerreno.query.filter_by(id_aviso=aviso.id_aviso).filter(
        SoporteAvisoTerreno.estado.in_(('pendiente', 'error'))
    ).update(dict(estado='enviando', error=None, fecha_intento=datetime.now(timezone.utc),
                  enviado_por=usuario.name), synchronize_session=False)
    db.session.commit()
    db.session.refresh(aviso)
    if not claimed:
        return serializar_aviso(aviso), 200 if aviso.estado == 'enviado' else 409
    try:
        enviar_mensaje(json.loads(aviso.contenido), config, aviso.mensaje_id, usuario.name)
        aviso.estado = 'enviado'
        aviso.fecha_envio = datetime.now(timezone.utc)
    except AvisoCorreoError as exc:
        aviso.estado, aviso.error = exc.estado, str(exc)
    except Exception:
        current_app.logger.exception('No se pudo confirmar el aviso terreno #%s', aviso.id_aviso)
        aviso.estado = 'incierto'
        aviso.error = 'No se pudo confirmar el envio. Verifica el buzon antes de reenviar.'
    db.session.commit()
    return serializar_aviso(aviso), 200 if aviso.estado == 'enviado' else 502
