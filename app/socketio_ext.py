from flask_socketio import SocketIO


# CORS abierto para mantener compatibilidad con web/mobile en desarrollo.
socketio = SocketIO(cors_allowed_origins="*", async_mode="threading")


def emit_armado_event(event_name, payload):
    """Emite eventos de armado sin romper flujo HTTP si Socket.IO falla."""
    try:
        socketio.emit(event_name, payload or {})
    except Exception:
        # No interrumpir requests REST por errores de realtime.
        pass

