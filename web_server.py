"""Lifecycle management for the optional web interface embedded in the desktop app."""
import threading
import time


class WebServerManager:
    def __init__(self):
        self._server = None
        self._thread = None
        self._error = None

    @property
    def running(self):
        return bool(self._thread and self._thread.is_alive() and self._server and self._server.started)

    def start(self, host, port):
        if self.running:
            return
        if self._thread and self._thread.is_alive():
            raise RuntimeError("El servidor web todavía está iniciando o cerrándose.")

        try:
            import uvicorn
            from web_app import app
        except ImportError as exc:
            raise RuntimeError(
                "No están instalados los componentes web. Reinstale la aplicación o ejecute "
                "'pip install -r requirements.txt'."
            ) from exc

        self._error = None
        self._server = uvicorn.Server(uvicorn.Config(
            app,
            host=host,
            port=port,
            log_level="warning",
            access_log=False,
        ))

        def serve():
            try:
                self._server.run()
            except Exception as exc:
                self._error = exc

        self._thread = threading.Thread(target=serve, name="DGCuadres-Web", daemon=True)
        self._thread.start()
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if self._server.started:
                return
            if not self._thread.is_alive():
                detail = f": {self._error}" if self._error else ""
                self._server = None
                self._thread = None
                raise RuntimeError(f"No se pudo iniciar el servidor web{detail}")
            time.sleep(0.05)

        self._server.should_exit = True
        self._thread.join(timeout=2)
        self._server = None
        self._thread = None
        raise RuntimeError("El servidor web no respondió durante el inicio. Revise la dirección y el puerto.")

    def stop(self):
        if not self._thread:
            return
        if self._server:
            self._server.should_exit = True
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise RuntimeError("El servidor web sigue atendiendo solicitudes y no pudo detenerse.")
        self._server = None
        self._thread = None
