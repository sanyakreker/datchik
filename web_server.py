import http.server
import socketserver
import json
import threading
import webbrowser
import state
from monitor7 import read_sensor_loop
from logger import logger

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_GET(self):
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            with open("vizual.html", "r", encoding="utf-8") as f:
                html = f.read()
            self.wfile.write(html.encode("utf-8"))

        elif self.path == '/devices':
            devices = ["ODTEMP-1 (SN: 001) - Температура"]
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(devices).encode())

        elif self.path.startswith('/start'):
            if not state.monitor_active:
                state.monitor_active = True
                sensor_thread = threading.Thread(target=read_sensor_loop, daemon=True)
                sensor_thread.start()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'running', 'message': 'Мониторинг запущен'}).encode())

        elif self.path == '/stop':
            state.monitor_active = False
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'stopped', 'message': 'Мониторинг остановлен'}).encode())

        elif self.path == '/data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            data = {
                'temp': state.current_temperature,
                'temps': list(state.temperature_history),
                'times': list(state.time_history)
            }
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()

def open_browser(port):
    webbrowser.open(f'http://localhost:{port}')
    

def start_server(port=5003):
    logger.info(f"Сервер запущен на http://localhost:{port}")
    logger.info("Нажмите Ctrl+C для остановки")
    logger.info("Нажмите кнопку 'Запустить мониторинг' для начала сбора данных")

    threading.Timer(1.0, open_browser, args=[port]).start()

    with socketserver.TCPServer(("", port), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Остановка...")
            state.monitor_active = False
            httpd.shutdown()
