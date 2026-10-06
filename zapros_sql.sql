
-- Примеры SQL-запросов к базе monitor.db
-- Таблица: temperature (id, timestamp, temperature)


-- 1. Все записи за последний час
SELECT *
FROM temperature
WHERE timestamp >= datetime('now', '-1 hour', 'localtime')
ORDER BY timestamp DESC;

-- 2. Все записи за сегодня
SELECT *
FROM temperature
WHERE date(timestamp) = date('now', 'localtime')
ORDER BY timestamp DESC;

-- 3. Все записи за конкретный период (вручную)
SELECT *
FROM temperature
WHERE timestamp BETWEEN '2026-10-02 14:00:00' AND '2026-10-02 15:00:00'
ORDER BY timestamp;

-- 4. Средняя температура за сутки
SELECT
    date(timestamp) AS day,
    AVG(temperature) AS avg_temp
FROM temperature
WHERE timestamp >= datetime('now', '-1 day')
GROUP BY date(timestamp);

-- 5. Максимальная температура за неделю
SELECT
    MAX(temperature) AS max_temp,
    timestamp
FROM temperature
WHERE timestamp >= datetime('now', '-7 days');

-- 6. Минимальная и максимальная температура за всё время
SELECT
    MIN(temperature) AS min_temp,
    MAX(temperature) AS max_temp,
    AVG(temperature) AS avg_temp,
    COUNT(*) AS total_records
FROM temperature;

-- 7. Записи, где температура превысила порог 28°C
SELECT *
FROM temperature
WHERE temperature > 28.0
ORDER BY timestamp DESC;

-- 8. Средняя температура по часам за последние 24 часа
SELECT
    strftime('%Y-%m-%d %H:00:00', timestamp) AS hour,
    AVG(temperature) AS avg_temp
FROM temperature
WHERE timestamp >= datetime('now', '-1 day')
GROUP BY strftime('%Y-%m-%d %H:00:00', timestamp)
ORDER BY hour;