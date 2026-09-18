import argparse
import datetime
import hid
import re
import sys
import time
from collections import deque
import http.server
import socketserver
import json
import webbrowser
import threading
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# константы для датчика
OD_VID = 0x0483
OD_IOT_PID = 0xA26A
HID_DATA_REPORT_ID = 1
HID_EVENT_REPORT_ID = 2
HID_FW_REPORT_ID = 3
HID_CMD_REPORT_ID = 4

SENSOR_STATES = {
    0: "NORMAL",
    1: "ACCEPTABLE",
    2: "CRITICAL",
    3: "INTERROR",
    4: "CUSTOM",
}

# константы для почты
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "почта отправитель уведомлений"
SENDER_PASSWORD = "пароль_почты_отправителя"
RECEIVER_EMAIL = "почта получателль"
TEMP_THRESHOLD = 28.0

# глобальные переменные
current_temperature = 0.0
temperature_history = deque(maxlen=100)
time_history = deque(maxlen=100)
monitor_active = False
alert_sent = False

# функии для датчика
def now_str() -> str:
    return datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")

def available_devices():
    devices = hid.enumerate(OD_VID, OD_IOT_PID)
    found_devices = []
    iot_product = re.compile(r"IOT\s+(.+?)(?:\s+HID)?$", re.IGNORECASE)
    
    for idx, d in enumerate(devices):
        vendor = d.get("manufacturer_string") or ""
        product = d.get("product_string") or ""
        serial_raw = d.get("serial_number") or ""
        serial_show = serial_raw or "S/N"
        path = d.get("path")
        
        match = iot_product.match(product.strip()) if product else None
        if vendor == "Open Development" and match and path:
            found_devices.append({
                "index": idx,
                "device_type": match.group(1).strip(),
                "serial": serial_raw,
                "serial_show": serial_show,
                "path": path,
                "vendor": vendor,
                "product": product,
            })
    return found_devices

def choose_device(devices, serial_number=None, index=None):
    if not devices:
        return None
    if serial_number:
        for d in devices:
            if d["serial"] == serial_number or d["serial_show"] == serial_number:
                return d
    if index is not None and 0 <= index < len(devices):
        return devices[index]
    return devices[0]

def open_device(device_info):
    try:
        dev = hid.Device(vid=OD_VID, pid=OD_IOT_PID)
        return dev
    except Exception as e:
        print(f"Ошибка открытия устройства: {e}")
        return None

def parse_data_report(payload):
    if len(payload) < 2:
        return None
    temp_raw = int.from_bytes(payload[0:2], byteorder="little", signed=True)
    temp = temp_raw / 100.0
    return {"temperature": temp}

# функция для отправки почты
def send_email_alert(temp):
    global alert_sent
    
    if alert_sent:
        return
    
    try:
        msg = MIMEMultipart()
        msg["From"] = SENDER_EMAIL
        msg["To"] = RECEIVER_EMAIL
        msg["Subject"] = f"ПРЕДУПРЕЖДЕНИЕ: Перегрев! {temp:.1f}°C"
        
        body = f"""ВНИМАНИЕ! Зафиксирован перегрев!

Температура: {temp:.1f}°C
Время: {now_str()}
Порог: {TEMP_THRESHOLD}°C

Пожалуйста, примите меры немедленно!
"""
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.send_message(msg)
        
        alert_sent = True
        print(f"[{now_str()}] Письмо отправлено на {RECEIVER_EMAIL}")
        
    except Exception as e:
        print(f"[{now_str()}] Ошибка отправки письма: {e}")

# поток чтения для датчика
def read_sensor_loop():
    global current_temperature, temperature_history, time_history, monitor_active, alert_sent
    
    devices = available_devices()
    if not devices:
        print("Устройства не найдены")
        return
    
    device_info = choose_device(devices)
    print(f"Открываем устройство: {device_info['device_type']}")
    dev = open_device(device_info)
    if not dev:
        print("Не удалось открыть устройство")
        return
    
    last_data_time = time.time()
    print("Мониторинг запущен")
    
    while monitor_active:
        try:
            report = dev.read(64, 100)
            if report:
                report = bytes(report)
                if len(report) > 1 and report[0] == 0 and report[1] == HID_DATA_REPORT_ID:
                    report = report[1:]
                
                report_id = report[0]
                payload = report[1:]
                last_data_time = time.time()
                
                if report_id == HID_DATA_REPORT_ID:
                    value = parse_data_report(payload)
                    if value:
                        temp = value["temperature"]
                        current_temperature = temp
                        
                        temperature_history.append(temp)
                        time_history.append(datetime.datetime.now().strftime("%H:%M:%S"))
                        
                        if temp > TEMP_THRESHOLD:
                            print(f"[{now_str()}] ПЕРЕГРЕВ! {temp:.1f}°C")
                            send_email_alert(temp)
                        else:
                            alert_sent = False
                
                elif report_id == HID_EVENT_REPORT_ID:
                    if payload:
                        state = SENSOR_STATES.get(payload[0], f"UNKNOWN({payload[0]})")
                        print(f"[{now_str()}] Состояние сенсора: {state}")
                
                elif report_id == HID_FW_REPORT_ID:
                    if payload:
                        length = payload[0]
                        fw = payload[1:1+length].decode("latin1", errors="replace")
                        print(f"[{now_str()}] Версия прошивки: {fw}")
            
            if (time.time() - last_data_time) > 10.0:
                print(f"[{now_str()}] Устройство не отвечает более 10 секунд")
                break
                
        except IOError as e:
            print(f"[{now_str()}] Ошибка чтения: {e}")
            time.sleep(0.5)
        except Exception as e:
            print(f"[{now_str()}] Ошибка: {e}")
            time.sleep(0.5)
    
    dev.close()
    print("Датчик отключен")

# веб-сервер
HTML = '''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>График температуры</title>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <style>
        body { margin: 0; padding: 20px; font-family: Arial; }
        #graph { width: 100%; height: 60vh; }
        .controls { margin-bottom: 20px; padding: 10px; background: #f0f0f0; border-radius: 10px; }
        select, button { padding: 10px; margin: 5px; font-size: 16px; }
        .status { margin-top: 10px; padding: 10px; border-radius: 5px; }
        .normal { background: #44ff44; color: black; }
        .warning { background: #ff8800; color: white; }
        .temp-display {
            text-align: center;
            font-size: 36px;
            margin: 10px 0;
            padding: 20px;
            border-radius: 10px;
        }
        .modal {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: black;
            z-index: 1000;
            text-align: center;
        }
        .modal-content {
            margin-top: 20%;
        }
        .modal-text {
            font-size: 48px;
            color: red;
            font-weight: bold;
            margin: 20px;
        }
        .modal-temp {
            font-size: 72px;
            color: red;
            font-weight: bold;
        }
        .modal-button {
            margin-top: 50px;
            padding: 15px 30px;
            font-size: 20px;
            background: red;
            color: white;
            border: none;
            border-radius: 10px;
            cursor: pointer;
        }
    </style>
</head>
<body>
    <div class="controls">
        <h3>Мониторинг температуры серверной</h3>
        <select id="deviceSelect">
            <option>Загрузка списка устройств...</option>
        </select>
        <button onclick="startMonitor()">Запустить мониторинг</button>
        <button onclick="stopMonitor()">Остановить</button>
        <div id="status" class="status normal">Готов к работе</div>
        <div id="tempDisplay" class="temp-display" style="background:#cccccc;">Температура: --°C</div>
    </div>
    <div id="graph"></div>
    
    <div id="warningModal" class="modal">
        <div class="modal-content">
            <div class="modal-text">ПЕРЕГРЕВ СЕРВЕРНОЙ!</div>
            <div class="modal-text">Температура превысила 28°C</div>
            <div class="modal-temp" id="warningTemp">--°C</div>
            <button class="modal-button" onclick="closeWarning()">ПОНЯЛ, ПРИНИМАЮ МЕРЫ</button>
        </div>
    </div>
    
    <script>
        let updateInterval = null;
        let warningShown = false;
        
        async function loadDevices() {
            const response = await fetch('/devices');
            const devices = await response.json();
            const select = document.getElementById('deviceSelect');
            select.innerHTML = '';
            for (let i = 0; i < devices.length; i++) {
                const option = document.createElement('option');
                option.value = i;
                option.textContent = devices[i];
                select.appendChild(option);
            }
        }
        
        function showWarning(temp) {
            if (!warningShown) {
                warningShown = true;
                document.getElementById('warningTemp').innerHTML = temp.toFixed(2) + '°C';
                document.getElementById('warningModal').style.display = 'block';
            }
        }
        
        function closeWarning() {
            document.getElementById('warningModal').style.display = 'none';
            warningShown = false;
        }
        
        async function startMonitor() {
            const select = document.getElementById('deviceSelect');
            const index = select.value;
            const response = await fetch('/start?index=' + index);
            const result = await response.json();
            document.getElementById('status').innerHTML = result.message;
            
            if (updateInterval) clearInterval(updateInterval);
            updateInterval = setInterval(loadData, 1000);
        }
        
        async function stopMonitor() {
            const response = await fetch('/stop');
            const result = await response.json();
            document.getElementById('status').innerHTML = result.message;
            if (updateInterval) {
                clearInterval(updateInterval);
                updateInterval = null;
            }
        }
        
        async function loadData() {
            const response = await fetch('/data');
            const data = await response.json();
            
            if (data.temps && data.temps.length > 0) {
                const currentTemp = data.temps[data.temps.length - 1];
                const tempDisplay = document.getElementById('tempDisplay');
                
                tempDisplay.innerHTML = 'Текущая температура: ' + currentTemp.toFixed(2) + '°C';
                
                if (currentTemp > 28) {
                    tempDisplay.style.background = '#ff0000';
                    tempDisplay.style.color = 'white';
                    document.getElementById('status').innerHTML = 'ВНИМАНИЕ! Температура ' + currentTemp.toFixed(2) + '°C превысила 28°C!';
                    document.getElementById('status').className = 'status warning';
                    showWarning(currentTemp);
                } else {
                    tempDisplay.style.background = '#44ff44';
                    tempDisplay.style.color = 'black';
                    document.getElementById('status').innerHTML = 'Температура в норме: ' + currentTemp.toFixed(2) + '°C';
                    document.getElementById('status').className = 'status normal';
                    warningShown = false;
                }
                
                const x = data.times;
                const y = data.temps;
                
                Plotly.newPlot('graph', [{
                    x: x,
                    y: y,
                    type: 'scatter',
                    mode: 'lines+markers',
                    name: 'Температура',
                    line: { color: 'red', width: 2 },
                    marker: { size: 4 }
                }], {
                    title: 'Мониторинг температуры (ODTEMP-1, 1 sec)',
                    xaxis: { title: 'Время' },
                    yaxis: { title: 'Температура (°C)', range: [20, 35] },
                    shapes: [{
                        type: 'line',
                        x0: x[0],
                        x1: x[x.length-1],
                        y0: 28,
                        y1: 28,
                        line: { color: 'red', width: 2, dash: 'dash' }
                    }]
                });
            }
        }
        
        loadDevices();
    </script>
</body>
</html>'''

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
    
    def do_GET(self):
        global monitor_active
        
        if self.path == '/':
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(HTML.encode())
            
        elif self.path == '/devices':
            devices = ["ODTEMP-1 (SN: 001) - Температура"]
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(devices).encode())
            
        elif self.path.startswith('/start'):
            if not monitor_active:
                monitor_active = True
                sensor_thread = threading.Thread(target=read_sensor_loop, daemon=True)
                sensor_thread.start()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'running', 'message': 'Мониторинг запущен'}).encode())
            
        elif self.path == '/stop':
            monitor_active = False
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'stopped', 'message': 'Мониторинг остановлен'}).encode())
            
        elif self.path == '/data':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            data = {
                'temp': current_temperature,
                'temps': list(temperature_history),
                'times': list(time_history)
            }
            self.wfile.write(json.dumps(data).encode())
        else:
            self.send_response(404)
            self.end_headers()

# запуск
if __name__ == "__main__":
    PORT = 5003
    webbrowser.open(f'http://localhost:{PORT}')
    
    print(f"Сервер запущен на http://localhost:{PORT}")
    print("Нажмите Ctrl+C для остановки")
    print("Нажмите кнопку 'Запустить мониторинг' для начала сбора данных")
    
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nОстановка...")
            monitor_active = False
            httpd.shutdown()
