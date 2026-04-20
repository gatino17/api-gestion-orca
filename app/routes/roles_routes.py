from flask import Blueprint, jsonify, request

from ..database import db
from ..models import Role, RolePage
from ..permissions import AVAILABLE_PAGES


roles_blueprint = Blueprint("roles", __name__)


def _serialize_role(role):
    return {
        "id_role": role.id_role,
        "nombre": role.nombre,
        "descripcion": role.descripcion,
        "paginas": sorted([(p.page_key or "").strip() for p in (role.pages or []) if p.page_key]),
    }


@roles_blueprint.route("/pages", methods=["GET"])
def list_pages():
    return jsonify(AVAILABLE_PAGES), 200


@roles_blueprint.route("/", methods=["GET"])
def list_roles():
    roles = Role.query.order_by(Role.nombre.asc()).all()
    return jsonify([_serialize_role(r) for r in roles]), 200


@roles_blueprint.route("/", methods=["POST"])
def create_role():
    data = request.get_json() or {}
    nombre = (data.get("nombre") or "").strip().lower()
    descripcion = (data.get("descripcion") or "").strip() or None
    paginas = data.get("paginas") or []
    if not nombre:
        return jsonify({"message": "nombre es requerido"}), 400
    if Role.query.filter(Role.nombre.ilike(nombre)).first():
        return jsonify({"message": "El rol ya existe"}), 400

    valid_keys = {p["key"] for p in AVAILABLE_PAGES}
    pages_clean = sorted({str(x).strip() for x in paginas if str(x).strip() in valid_keys})

    role = Role(nombre=nombre, descripcion=descripcion)
    db.session.add(role)
    db.session.flush()
    for key in pages_clean:
        db.session.add(RolePage(role_id=role.id_role, page_key=key))
    db.session.commit()
    return jsonify({"message": "Rol creado", "rol": _serialize_role(role)}), 201


@roles_blueprint.route("/<int:id_role>", methods=["PUT"])
def update_role(id_role):
    role = Role.query.get(id_role)
    if not role:
        return jsonify({"message": "Rol no encontrado"}), 404

    data = request.get_json() or {}
    nombre = data.get("nombre")
    descripcion = data.get("descripcion")
    paginas = data.get("paginas")

    if isinstance(nombre, str) and nombre.strip():
        nombre_clean = nombre.strip().lower()
        dup = Role.query.filter(Role.nombre.ilike(nombre_clean), Role.id_role != role.id_role).first()
        if dup:
            return jsonify({"message": "Ya existe otro rol con ese nombre"}), 400
        role.nombre = nombre_clean
    if descripcion is not None:
        role.descripcion = (str(descripcion).strip() or None)

    if isinstance(paginas, list):
        valid_keys = {p["key"] for p in AVAILABLE_PAGES}
        pages_clean = sorted({str(x).strip() for x in paginas if str(x).strip() in valid_keys})
        RolePage.query.filter_by(role_id=role.id_role).delete()
        for key in pages_clean:
            db.session.add(RolePage(role_id=role.id_role, page_key=key))

    db.session.commit()
    return jsonify({"message": "Rol actualizado", "rol": _serialize_role(role)}), 200


@roles_blueprint.route("/<int:id_role>", methods=["DELETE"])
def delete_role(id_role):
    role = Role.query.get(id_role)
    if not role:
        return jsonify({"message": "Rol no encontrado"}), 404
    db.session.delete(role)
    db.session.commit()
    return jsonify({"message": "Rol eliminado"}), 200
