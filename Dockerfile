# Imagen para desplegar ÚNICAMENTE el servidor MCP remoto (no el chatbot).
# El chatbot sigue ejecutándose en tu máquina y consume este servidor por HTTP.
FROM python:3.12-slim

# PYTHONUNBUFFERED: que los print() salgan de inmediato en los logs de Cloud Run.
# PHARMACY_DATA: en Cloud Run el disco de la app es efímero; /tmp es escribible.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PHARMACY_DATA=/tmp/pharmacy_data.json

WORKDIR /app

# Solo se copian los 3 archivos que necesita el servidor remoto. El resto del
# proyecto (chatbot, frontend, pruebas) no viaja a la nube.
COPY pharmacy_core.py mcp_protocol.py remote_server.py ./

# Buena práctica: no ejecutar como root.
RUN useradd --create-home --uid 1000 appuser
USER appuser

# Cloud Run inyecta la variable PORT; remote_server.py la respeta (8080 por defecto).
EXPOSE 8080

CMD ["python", "remote_server.py"]
