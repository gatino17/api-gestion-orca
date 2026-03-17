from app import create_app
from app.socketio_ext import socketio


app = create_app()


if __name__ == "__main__":
    host = "0.0.0.0"
    port = 5000
    print(f"[backend] iniciando en http://{host}:{port}")
    # log_output fuerza trazas de requests cuando usa eventlet/gevent.
    socketio.run(app, host=host, port=port, debug=False, log_output=True)
