from datetime import date, datetime, time, timezone
import re

import jwt
import pytz
from flask import Blueprint, g, jsonify, request
from sqlalchemy.exc import IntegrityError

from ..database import db
from ..models import TicketISO, TicketISOContador, TicketISOPlanAccion, User
from ..permissions import get_pages_for_role_name
from .auth_routes import SECRET_KEY

ticket_iso_blueprint = Blueprint('ticket_iso', __name__)
ESTADOS = {'pendiente', 'en_seguimiento', 'resuelto'}
ORIGENES = {
    'auditoria': 'Auditoria', 'ticket_iso': 'Ticket ISO',
    'revision_direccion': 'Revision por la direccion', 'reclamo_cliente_ticket': 'Reclamo de cliente ticket',
    'salida_no_conforme': 'Salida no conforme', 'sugerencia_mejora': 'Sugerencia de mejora', 'otros': 'Otros',
}
CATEGORIAS_PROCEDIMIENTO = {
    '001_gestion_comercial': '001 Gestion comercial', '002_levantamiento': '002 Levantamiento',
    'armado_sistema': '003 Armado sistema', 'instalacion_sistema': '004 Instalacion de sistema',
    'soporte_posventa': '005 Soporte y posventa', 'bodega': '006 Bodega',
    'mantencion_reacondicionamiento': '007 Mantencion y reacondicionamiento', 'retiro': '008 Retiro', 'otros': '009 Otros',
}
CHILE = pytz.timezone('America/Santiago')


@ticket_iso_blueprint.before_request
def verificar_acceso():
    if request.method == 'OPTIONS':
        return None
    authorization = request.headers.get('Authorization', '')
    if not authorization.startswith('Bearer '):
        return jsonify({'error': 'Inicia sesion para acceder a Ticket ISO.'}), 401
    try:
        payload = jwt.decode(authorization[7:], SECRET_KEY, algorithms=['HS256'])
        usuario = db.session.get(User, payload.get('user_id'))
    except (jwt.InvalidTokenError, TypeError, ValueError):
        usuario = None
    if not usuario:
        return jsonify({'error': 'Sesion invalida o expirada.'}), 401
    if 'ticket_iso' not in get_pages_for_role_name(usuario.rol):
        return jsonify({'error': 'No tienes permiso para acceder a Ticket ISO.'}), 403
    g.ticket_iso_usuario = usuario
    return None


def _iso(fecha):
    if not fecha:
        return None
    return fecha.replace(tzinfo=timezone.utc).isoformat() if fecha.tzinfo is None else fecha.isoformat()


def _serializar(ticket):
    resultado = {
        'id_ticket': ticket.id_ticket,
        'numero_ticket': ticket.numero_ticket,
        'fecha_recepcion': datetime.fromisoformat(_iso(ticket.fecha_recepcion)).astimezone(CHILE).date().isoformat(),
        'asunto_procedimiento': ticket.asunto_procedimiento,
        'origen': ticket.origen,
        'categoria_procedimiento': ticket.categoria_procedimiento,
        'observaciones': ticket.observaciones,
        'resultado_plan_accion': ticket.resultado_plan_accion,
        'fecha_control': ticket.fecha_control.isoformat() if ticket.fecha_control else None,
        'planes_accion': [{
            'id_plan': plan.id_plan,
            'numero': len(ticket.planes_accion) - index,
            'resultado_plan_accion': plan.resultado_plan_accion,
            'fecha_control': plan.fecha_control.isoformat() if plan.fecha_control else None,
            'created_at': _iso(plan.created_at),
            **({'creado_por_nombre': plan.creado_por_nombre}
               if str(g.ticket_iso_usuario.rol or '').strip().lower() == 'admin' else {}),
        } for index, plan in enumerate(ticket.planes_accion)],
        'cliente_id': ticket.cliente_id,
        'centro_id': ticket.centro_id,
        'cliente': ticket.cliente_nombre,
        'centro': ticket.centro_nombre,
        'area': ticket.area,
        'equipo_afectado': ticket.equipo_afectado,
        'problema': ticket.problema,
        'responsable_id': ticket.responsable_id,
        'responsable': ticket.responsable_nombre,
        'prioridad': ticket.prioridad,
        'estado': ticket.estado,
        'solucion': ticket.solucion,
        'fecha_cierre': _iso(ticket.fecha_cierre),
        'created_at': _iso(ticket.created_at),
        'updated_at': _iso(ticket.updated_at),
    }
    if str(g.ticket_iso_usuario.rol or '').strip().lower() == 'admin':
        resultado['creado_por_nombre'] = ticket.creado_por_nombre
    return resultado


def _texto(data, campo, maximo, obligatorio=False):
    valor = data.get(campo)
    if valor is not None and not isinstance(valor, str):
        raise ValueError(f'El campo {campo} debe ser texto.')
    valor = (valor or '').strip()
    if obligatorio and not valor:
        raise ValueError(f'Completa el campo {campo}.')
    if len(valor) > maximo:
        raise ValueError(f'El campo {campo} admite hasta {maximo} caracteres.')
    return valor or None


def _fecha_dia(valor, mensaje):
    try:
        if not isinstance(valor, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', valor):
            raise ValueError()
        dia = date.fromisoformat(valor)
        # El mediodia evita horas inexistentes en cambios de horario; el formulario usa solo el dia.
        return CHILE.localize(datetime.combine(dia, time(12))).astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(mensaje)


def _validar(data, ticket=None):
    if not isinstance(data, dict):
        raise ValueError('Los datos del ticket no son validos.')
    if 'numero_automatico' in data and not isinstance(data['numero_automatico'], bool):
        raise ValueError('La opcion de numeracion automatica no es valida.')
    numero = (_texto(data, 'numero_ticket', 120) or '').upper()
    if len(numero) > 120:
        raise ValueError('El numero de ticket admite hasta 120 caracteres.')
    estado = _texto(data, 'estado', 30) or 'pendiente'
    if estado not in ESTADOS:
        raise ValueError('Selecciona un estado valido.')
    origen = _texto(data, 'origen', 50, obligatorio=True)
    categoria = _texto(data, 'categoria_procedimiento', 60, obligatorio=True)
    if origen not in ORIGENES:
        raise ValueError('Selecciona un origen valido.')
    if categoria not in CATEGORIAS_PROCEDIMIENTO:
        raise ValueError('Selecciona una categoria de procedimiento valida.')
    recepcion = _fecha_dia(data.get('fecha_recepcion'), 'Indica una fecha de recepcion valida.')
    if ticket and any(plan.fecha_control and plan.fecha_control < recepcion.astimezone(CHILE).date() for plan in ticket.planes_accion):
        raise ValueError('La recepcion no puede ser posterior a la fecha de control del plan de accion.')
    responsable_id = ticket.responsable_id if ticket else None
    responsable_nombre = ticket.responsable_nombre if ticket else None
    if 'responsable' in data:
        responsable_id = None
        responsable_nombre = _texto(data, 'responsable', 100)
    elif 'responsable_id' in data:
        valor = data['responsable_id']
        responsable_id, responsable_nombre = None, None
        if valor not in (None, ''):
            if isinstance(valor, bool) or not re.fullmatch(r'[0-9]{1,10}', str(valor)) or not 0 < int(valor) <= 2147483647:
                raise ValueError('Selecciona un responsable valido.')
            responsable = db.session.get(User, int(valor))
            if not responsable:
                raise ValueError('El responsable seleccionado ya no existe.')
            responsable_id, responsable_nombre = responsable.id, responsable.name
    cierre = None
    if estado == 'resuelto':
        if 'fecha_cierre' in data:
            cierre = _fecha_dia(data['fecha_cierre'], 'Indica una fecha de cierre valida.')
            if ticket and ticket.fecha_cierre and datetime.fromisoformat(_iso(ticket.fecha_cierre)).astimezone(CHILE).date() == cierre.astimezone(CHILE).date():
                cierre = ticket.fecha_cierre
        else:
            cierre = ticket.fecha_cierre if ticket and ticket.fecha_cierre else datetime.now(timezone.utc)
    elif 'fecha_cierre' in data and data['fecha_cierre'] not in (None, ''):
        cierre = _fecha_dia(data['fecha_cierre'], 'Indica una fecha de cierre valida.')
    elif 'fecha_cierre' not in data and ticket and ticket.estado != 'resuelto':
        cierre = ticket.fecha_cierre
    if cierre and datetime.fromisoformat(_iso(cierre)).astimezone(CHILE).date() < recepcion.astimezone(CHILE).date():
        raise ValueError('El cierre no puede ser anterior a la recepcion del ticket.')
    return {
        'numero_ticket': numero or (ticket.numero_ticket if ticket else None),
        'fecha_recepcion': recepcion,
        'asunto_procedimiento': _texto(data, 'asunto_procedimiento', 250) if 'asunto_procedimiento' in data else (ticket.asunto_procedimiento if ticket else None),
        'origen': origen,
        'categoria_procedimiento': categoria,
        'observaciones': _texto(data, 'observaciones', 10000) if 'observaciones' in data else (ticket.observaciones if ticket else None),
        'responsable_id': responsable_id,
        'responsable_nombre': responsable_nombre,
        'problema': _texto(data, 'problema', 10000, obligatorio=True),
        'estado': estado,
        'fecha_cierre': cierre,
    }


def _secuencia_numero(numero):
    coincidencia = re.fullmatch(r'ISO-\d{4}-([0-9]{1,18})', numero)
    if coincidencia:
        return int(coincidencia.group(1))
    return int(numero) if len(numero) <= 18 and numero.isascii() and numero.isdigit() else 0


def _formato_numero(numero):
    anio = datetime.now(CHILE).year
    return f'ISO-{anio}-{numero:03d}'


def _proximo_numero(reservando=False):
    contador = db.session.get(TicketISOContador, 1)
    numeros = [_secuencia_numero(numero) for (numero,) in db.session.query(TicketISO.numero_ticket).all()]
    return max([contador.valor - int(reservando) if contador else 0, *numeros]) + 1


def _reservar_numero(numero):
    # El contador se bloquea en la misma transaccion que guarda el ticket.
    dialecto = db.engine.dialect.name
    if dialecto == 'postgresql':
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    db.session.execute(insert(TicketISOContador).values(id=1, valor=0).on_conflict_do_nothing(index_elements=['id']))
    db.session.execute(db.update(TicketISOContador).where(TicketISOContador.id == 1).values(valor=TicketISOContador.valor + 1))
    db.session.expire_all()
    siguiente = _proximo_numero(reservando=True)
    if numero:
        siguiente = max(siguiente, _secuencia_numero(numero))
    db.session.execute(db.update(TicketISOContador).where(TicketISOContador.id == 1).values(valor=siguiente))
    return numero or _formato_numero(siguiente)


@ticket_iso_blueprint.route('/catalogos', methods=['GET'])
def catalogos():
    return jsonify({'proximo_numero': _formato_numero(_proximo_numero()),
                    'responsables': [{'id': usuario.id, 'nombre': usuario.name} for usuario in User.query.order_by(User.name).all()],
                    'origenes': ORIGENES, 'categorias_procedimiento': CATEGORIAS_PROCEDIMIENTO}), 200


@ticket_iso_blueprint.route('/', methods=['GET'])
def listar_tickets():
    tickets = TicketISO.query.order_by(TicketISO.fecha_recepcion.desc(), TicketISO.id_ticket.desc()).all()
    return jsonify({'tickets': [_serializar(ticket) for ticket in tickets]}), 200


@ticket_iso_blueprint.route('/<int:ticket_id>', methods=['GET'])
def detalle_ticket(ticket_id):
    ticket = db.session.get(TicketISO, ticket_id)
    if not ticket:
        return jsonify({'error': 'El ticket ya no existe.'}), 404
    return jsonify({'ticket': _serializar(ticket)}), 200


def _guardar(ticket=None):
    try:
        data = request.get_json(silent=True)
        valores = _validar(data, ticket)
        nuevo = ticket is None
        if nuevo:
            # La vista previa no reserva el numero; se asigna atomicamente al guardar.
            valores['numero_ticket'] = _reservar_numero(None if data.get('numero_automatico', False) else valores['numero_ticket'])
        duplicado = TicketISO.query.filter_by(numero_ticket=valores['numero_ticket']).first()
        if duplicado and (ticket is None or duplicado.id_ticket != ticket.id_ticket):
            db.session.rollback()
            return jsonify({'error': 'Ese numero de ticket ya esta registrado.'}), 409
        if nuevo:
            usuario = g.ticket_iso_usuario
            ticket = TicketISO(cliente_nombre='', centro_nombre='', creado_por_id=usuario.id, creado_por_nombre='Admin' if str(usuario.rol or '').strip().lower() == 'admin' else usuario.name)
            db.session.add(ticket)
        for campo, valor in valores.items():
            setattr(ticket, campo, valor)
        db.session.commit()
        return jsonify({'ticket': _serializar(ticket), 'message': 'Ticket registrado.' if nuevo else 'Ticket actualizado.'}), 201 if nuevo else 200
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400
    except IntegrityError as exc:
        db.session.rollback()
        codigo = getattr(exc.orig, 'pgcode', None)
        if codigo == '23505' or 'numero_ticket' in str(exc.orig).lower():
            return jsonify({'error': 'Ese numero de ticket ya esta registrado.'}), 409
        raise


@ticket_iso_blueprint.route('/', methods=['POST'])
def crear_ticket():
    return _guardar()


@ticket_iso_blueprint.route('/<int:ticket_id>', methods=['PUT'])
def editar_ticket(ticket_id):
    ticket = db.session.get(TicketISO, ticket_id)
    if not ticket:
        return jsonify({'error': 'El ticket ya no existe.'}), 404
    return _guardar(ticket)


@ticket_iso_blueprint.route('/<int:ticket_id>/planes-accion', methods=['POST'])
def guardar_plan_accion(ticket_id):
    ticket = db.session.get(TicketISO, ticket_id)
    if not ticket:
        return jsonify({'error': 'El ticket ya no existe.'}), 404
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Los datos del plan de accion no son validos.')
        if 'fecha_cierre' in data:
            raise ValueError('El cierre del caso se registra por separado, no en un plan de accion.')
        resultado = _texto(data, 'resultado_plan_accion', 2000, obligatorio=True)
        valor_control = data.get('fecha_control')
        control = None if valor_control in (None, '') else _fecha_dia(valor_control, 'Indica una fecha de control valida.').astimezone(CHILE).date()
        recepcion = datetime.fromisoformat(_iso(ticket.fecha_recepcion)).astimezone(CHILE).date()
        if control and control < recepcion:
            raise ValueError('La fecha de control no puede ser anterior a la recepcion del ticket.')
        usuario = g.ticket_iso_usuario
        plan = TicketISOPlanAccion(ticket=ticket, resultado_plan_accion=resultado, fecha_control=control,
            creado_por_nombre='Admin' if str(usuario.rol or '').strip().lower() == 'admin' else usuario.name)
        db.session.add(plan)
        ticket.updated_at = datetime.now(timezone.utc)
        db.session.commit()
        return jsonify({'ticket': _serializar(ticket), 'message': 'Plan de accion agregado.'}), 201
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@ticket_iso_blueprint.route('/<int:ticket_id>/cierre', methods=['PATCH'])
def cerrar_ticket(ticket_id):
    ticket = db.session.get(TicketISO, ticket_id)
    if not ticket:
        return jsonify({'error': 'El ticket ya no existe.'}), 404
    try:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValueError('Los datos de cierre no son validos.')
        cierre = _fecha_dia(data.get('fecha_cierre'), 'Indica una fecha de cierre valida.')
        if cierre.astimezone(CHILE).date() < datetime.fromisoformat(_iso(ticket.fecha_recepcion)).astimezone(CHILE).date():
            raise ValueError('El cierre no puede ser anterior a la recepcion del ticket.')
        if not ticket.fecha_cierre or datetime.fromisoformat(_iso(ticket.fecha_cierre)).astimezone(CHILE).date() != cierre.astimezone(CHILE).date():
            ticket.fecha_cierre = cierre
        ticket.estado = 'resuelto'
        db.session.commit()
        return jsonify({'ticket': _serializar(ticket), 'message': 'Caso cerrado correctamente.'}), 200
    except ValueError as exc:
        db.session.rollback()
        return jsonify({'error': str(exc)}), 400


@ticket_iso_blueprint.route('/<int:ticket_id>', methods=['DELETE'])
def eliminar_ticket(ticket_id):
    if str(g.ticket_iso_usuario.rol or '').strip().lower() != 'admin':
        return jsonify({'error': 'Solo el admin puede eliminar tickets ISO.'}), 403
    ticket = db.session.get(TicketISO, ticket_id)
    if not ticket:
        return jsonify({'error': 'El ticket ya no existe.'}), 404
    db.session.delete(ticket)
    db.session.commit()
    return jsonify({'message': 'Ticket eliminado correctamente.'}), 200
