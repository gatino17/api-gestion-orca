from flask import Blueprint, jsonify
from sqlalchemy import text
from ..database import db

status_blueprint = Blueprint('status', __name__)

@status_blueprint.route('/', methods=['GET'])
def status():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        print("Conexión interrumpida a la base de datos.")
        return jsonify({"status": "error"}), 500
