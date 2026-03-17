import os

from flask_socketio import SocketIO


# CORS abierto para mantener compatibilidad con web/mobile en desarrollo.
socketio = SocketIO(
    cors_allowed_origins=os.getenv("SOCKET_CORS_ORIGINS", "*"),
    async_mode=os.getenv("SOCKET_ASYNC_MODE") or None,
    logger=os.getenv("SOCKET_LOGGER", "1") == "1",
    engineio_logger=os.getenv("SOCKET_ENGINEIO_LOGGER", "1") == "1",
)


def emit_armado_event(event_name, payload):
    """Emite eventos de armado sin romper flujo HTTP si Socket.IO falla."""
    try:
        socketio.emit(event_name, payload or {})
    except Exception:
        # No interrumpir requests REST por errores de realtime.
        pass
