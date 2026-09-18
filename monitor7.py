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
