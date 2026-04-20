from .models import Role, RolePage


AVAILABLE_PAGES = [
    {"key": "inicio", "label": "Inicio", "route": "/"},
    {"key": "consulta_centro", "label": "Consulta de centros", "route": "/consulta-centro"},
    {"key": "soporte", "label": "Soporte", "route": "/soporte"},
    {"key": "soporte_detalle", "label": "Detalle de soporte", "route": "/soporte/detalle"},
    {"key": "mantencion_preventiva", "label": "Mantencion preventiva", "route": "/mantencion-preventiva"},
    {"key": "informes_centros", "label": "Informes centros", "route": "/informes-centros"},
    {"key": "bodega_retiros", "label": "Bodega retiros", "route": "/bodega-retiros"},
    {"key": "armados", "label": "Armado tecnico", "route": "/armados"},
    {"key": "calendario", "label": "Calendario", "route": "/calendario"},
    {"key": "historial_trabajos", "label": "Historial de trabajos", "route": "/historial-trabajos"},
    {"key": "historial_centro", "label": "Historial por centro", "route": "/historial-centro"},
    {"key": "datos_ip", "label": "Datos IP", "route": "/datos-ip"},
    {"key": "clientes", "label": "Clientes", "route": "/clientes"},
    {"key": "centros", "label": "Centros", "route": "/centros"},
    {"key": "registrosdocumentos", "label": "Registro de actas", "route": "/registrosdocumentos"},
    {"key": "usuarios", "label": "Usuarios", "route": "/usuarios"},
    {"key": "tecnicos", "label": "Tecnicos", "route": "/tecnicos"},
]


DEFAULT_ROLE_PAGES = {
    "admin": [item["key"] for item in AVAILABLE_PAGES],
    "tecnico": ["inicio", "consulta_centro", "armados"],
    "soporte": [
        "inicio",
        "consulta_centro",
        "soporte",
        "soporte_detalle",
        "mantencion_preventiva",
        "informes_centros",
        "calendario",
        "historial_trabajos",
        "datos_ip",
    ],
    "operaciones": [
        "inicio",
        "consulta_centro",
        "soporte",
        "soporte_detalle",
        "mantencion_preventiva",
        "informes_centros",
        "bodega_retiros",
        "armados",
        "calendario",
        "historial_trabajos",
        "historial_centro",
        "datos_ip",
        "clientes",
        "centros",
        "registrosdocumentos",
        "tecnicos",
    ],
    "finanzas": ["inicio", "consulta_centro", "historial_centro"],
}


def get_pages_for_role_name(role_name):
    role_name = (role_name or "").strip().lower()
    if not role_name:
        return []
    role = Role.query.filter(Role.nombre.ilike(role_name)).first()
    if role:
        return sorted({(row.page_key or "").strip() for row in (role.pages or []) if row.page_key})
    return DEFAULT_ROLE_PAGES.get(role_name, [])


def seed_default_roles(db):
    for role_name, pages in DEFAULT_ROLE_PAGES.items():
        role = Role.query.filter(Role.nombre.ilike(role_name)).first()
        if not role:
            role = Role(nombre=role_name)
            db.session.add(role)
            db.session.flush()
        existing_pages = {p.page_key for p in (role.pages or [])}
        for key in pages:
            if key not in existing_pages:
                db.session.add(RolePage(role_id=role.id_role, page_key=key))
