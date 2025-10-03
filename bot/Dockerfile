FROM python:3.11-slim

# Устанавливаем зависимости для psycopg2
RUN apt-get update && apt-get install -y gcc libpq-dev && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Скопируем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем проект
COPY . .

# Создаем директорию для файлов лабораторных работ
RUN mkdir -p /app/lab_files

CMD ["python", "main.py"]