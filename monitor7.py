import datetime
import hid
import re
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
import state
import database
from logger import logger

# константы_для_датчика
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
load_dotenv("data.env")

# константы для почты
SMTP_SERVER = os.environ.get("SMTP_SERVER")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")
SENDER_PASSWORD = os.environ.get("SENDER_PASSWORD")
RECEIVER_EMAIL = os.environ.get("RECEIVER_EMAIL")
TEMP_THRESHOLD = float(os.environ.get("TEMP_THRESHOLD", 28.0))


# функии для датчика
def now_str():
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


def open_device():
    try:
        dev = hid.Device(vid=OD_VID, pid=OD_IOT_PID)
        return dev
    except Exception as e:
        logger.error(f"Ошибка открытия устройства: {e}")
        return None


def parse_data_report(payload):
    if len(payload) < 2:
        return None
    temp_raw = int.from_bytes(payload[0:2], byteorder="little", signed=True)
    temp = temp_raw / 100.0
    return {"temperature": temp}


# функция для отправки почты
def send_email_alert(temp):
    if state.alert_sent:
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

        state.alert_sent = True
        logger.info(f"Письмо отправлено на {RECEIVER_EMAIL}")

    except Exception as e:
        logger.error(f"Ошибка отправки письма: {e}")


# поток чтения для датчика
def read_sensor_loop():

    devices = available_devices()

    if not devices:
        logger.warning("Устройства не найдены")
        return

    device_info = choose_device(devices)
    logger.info(f"Открываем устройство: {device_info['device_type']}")
    dev = open_device()
    if not dev:
        logger.error("Не удалось открыть устройство")
        return

    last_data_time = time.time()
    logger.info("Мониторинг запущен")

    while state.monitor_active:
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
                        state.current_temperature = temp

                        state.temperature_history.append(temp)
                        state.time_history.append(datetime.datetime.now().strftime("%H:%M:%S"))
                        database.log_temperature(temp)

                        if temp > TEMP_THRESHOLD:
                            logger.warning(f"ПЕРЕГРЕВ! {temp:.1f}°C")
                            send_email_alert(temp)
                        else:
                            state.alert_sent = False

                elif report_id == HID_EVENT_REPORT_ID:
                    if payload:
                        sensor_state = SENSOR_STATES.get(payload[0], f"UNKNOWN({payload[0]})")
                        logger.info(f"Состояние сенсора: {sensor_state}")

                elif report_id == HID_FW_REPORT_ID:
                    if payload:
                        length = payload[0]
                        fw = payload[1:1 + length].decode("latin1", errors="replace")
                        logger.info(f"Версия прошивки: {fw}")

            if (time.time() - last_data_time) > 10.0:
                logger.error("Устройство не отвечает более 10 секунд")
                break

        except IOError as e:
            logger.error(f"Ошибка чтения: {e}")
            time.sleep(0.5)
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            time.sleep(0.5)

    dev.close()
    logger.info("Датчик отключен")


# запуск
if __name__ == "__main__":
    database.init_db()
    from web_server import start_server
    start_server(5003)
