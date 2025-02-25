from flask import Blueprint, request, jsonify
from ..models import RazonSocial, Cliente
from ..database import db

razones_sociales_blueprint = Blueprint('razones_sociales', __name__)

# Ruta para obtener las razones sociales con paginación y orden, incluyendo el nombre del cliente
@razones_sociales_blueprint.route('/', methods=['GET'])
def get_razones_sociales():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 5, type=int)
    razones_sociales_query = RazonSocial.query.join(Cliente, RazonSocial.cliente_id == Cliente.id_cliente).order_by(RazonSocial.id_razon_social.asc())
    paginated_razones_sociales = razones_sociales_query.paginate(page=page, per_page=per_page, error_out=False)

    razones_sociales_data = [{
        'id_razon_social': razon.id_razon_social,
        'cliente_id': razon.cliente_id,
        'razon_social': razon.razon_social,
        'cliente_nombre': razon.cliente.nombre  # Incluimos el nombre del cliente
    } for razon in paginated_razones_sociales.items]

    return jsonify({
        'razones_sociales': razones_sociales_data,
        'total': paginated_razones_sociales.total,
        'page': paginated_razones_sociales.page,
        'pages': paginated_razones_sociales.pages
    })

# Ruta para crear una nueva razón social
@razones_sociales_blueprint.route('/', methods=['POST'])
def create_razon_social():
    data = request.get_json()
    cliente_id = data.get('cliente_id')
    razon_social = data.get('razon_social')
    
    if not cliente_id or not razon_social:
        return jsonify({'message': 'Faltan datos: cliente_id y/o razon_social'}), 400

    try:
        nueva_razon = RazonSocial(cliente_id=cliente_id, razon_social=razon_social)
        db.session.add(nueva_razon)
        db.session.commit()

        return jsonify({'message': 'Razón social creada exitosamente', 'razon_social': {
            'id_razon_social': nueva_razon.id_razon_social,
            'cliente_id': nueva_razon.cliente_id,
            'razon_social': nueva_razon.razon_social
        }}), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Ruta para editar una razón social existente
@razones_sociales_blueprint.route('/<int:id_razon_social>', methods=['PUT'])
def update_razon_social(id_razon_social):
    data = request.get_json()
    razon = RazonSocial.query.get(id_razon_social)

    if razon is None:
        return jsonify({'message': 'Razón social no encontrada'}), 404

    try:
        razon.cliente_id = data.get('cliente_id', razon.cliente_id)
        razon.razon_social = data.get('razon_social', razon.razon_social)

        db.session.commit()
        return jsonify({'message': 'Razón social actualizada exitosamente', 'razon_social': {
            'id_razon_social': razon.id_razon_social,
            'cliente_id': razon.cliente_id,
            'razon_social': razon.razon_social
        }}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Ruta para eliminar una razón social
@razones_sociales_blueprint.route('/<int:id_razon_social>', methods=['DELETE'])
def delete_razon_social(id_razon_social):
    razon = RazonSocial.query.get(id_razon_social)
    if razon is None:
        return jsonify({'message': 'Razón social no encontrada'}), 404

    try:
        db.session.delete(razon)
        db.session.commit()
        return jsonify({'message': 'Razón social eliminada exitosamente'}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500

# Ruta para mostrar todos los datos sin filtro
@razones_sociales_blueprint.route('/all', methods=['GET'])
def get_all_razones_sociales():
    try:
        razones_sociales_query = RazonSocial.query.join(Cliente, RazonSocial.cliente_id == Cliente.id_cliente).order_by(RazonSocial.id_razon_social.asc())
        razones_sociales_data = [{
            'id_razon_social': razon.id_razon_social,
            'cliente_id': razon.cliente_id,
            'razon_social': razon.razon_social,
            'cliente_nombre': razon.cliente.nombre
        } for razon in razones_sociales_query.all()]

        return jsonify({'razones_sociales': razones_sociales_data}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
