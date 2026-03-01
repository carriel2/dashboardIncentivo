# Uses an official lightweight Python image
FROM python:3.11-slim

# Sets the working directory
WORKDIR /app

# Sets the timezone to ensure correct billing dates and execution times
ENV TZ=America/Sao_Paulo
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Copies requirements and installs them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copies the rest of the application code
COPY . .

# Exposes the Streamlit port
EXPOSE 8501