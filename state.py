from collections import deque

current_temperature = 0.0
temperature_history = deque(maxlen=100)
time_history = deque(maxlen=100)
monitor_active = False
alert_sent = False
