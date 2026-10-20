#!/data/data/com.termux/files/usr/bin/bash

# Script agnóstico para servidores (Termux / Linux convencional)
# Detecta dinámicamente el entorno y arranca en segundo plano con Gunicorn y Caddy si están disponibles.

# Obtener la ruta absoluta del directorio donde reside este script
BASE_DIR="$(cd "$(dirname "${BASH_SOURCE}")" && pwd)"
cd "$BASE_DIR"

# Colores para salida
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

show_help() {
    echo "Uso: ./run.sh [opción]"
    echo ""
    echo "Opciones:"
    echo "  start     Iniciar la aplicación (en segundo plano si Gunicorn/Caddy existen)"
    echo "  stop      Detener todos los servicios en segundo plano"
    echo "  install   Instalar o reparar el entorno virtual y dependencias"
    echo "  help      Mostrar esta ayuda"
}

install_dependencies() {
    echo -e "${BLUE}Configurando entorno virtual de forma agnóstica...${NC}"
    
    # Si existe un venv corrupto (por rutas absolutas viejas), lo reparamos
    if [ -d "venv" ]; then
        echo -e "${BLUE}Detectado entorno virtual previo. Recreando para asegurar rutas correctas...${NC}"
        rm -rf venv
    fi
    
    python -m venv venv --system-site-packages
    
    echo -e "${BLUE}Instalando dependencias del sistema...${NC}"
    ./venv/bin/python -m pip install --upgrade pip
    ./venv/bin/python -m pip install Flask
    
    if [ -f "requirements.txt" ]; then
        ./venv/bin/python -m pip install -r requirements.txt
    fi
    
    # Intentar instalar gunicorn dentro del venv de forma automática
    ./venv/bin/python -m pip install gunicorn &> /dev/null
    
    echo -e "${GREEN}Entorno preparado correctamente.${NC}"
}

run_app() {
    if [ ! -d "venv" ]; then
        install_dependencies
    fi

    if command -v termux-wake-lock &> /dev/null; then
        termux-wake-lock
        echo -e "${BLUE}[Termux] Wake-lock activado.${NC}"
    fi

    if [ -f "./venv/bin/gunicorn" ]; then
        echo -e "${GREEN}Gunicorn detectado.${NC} Inciando Flask en segundo plano..."
        pkill -f "gunicorn.*5000" &> /dev/null
        ./venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app --daemon --timeout 300
        echo -e "${GREEN}¡Aplicación Flask corriendo en segundo plano en el puerto 5000!${NC}"
    else
        echo -e "${RED}Gunicorn no detectado.${NC} Iniciando en modo desarrollo..."
        ./venv/bin/python app.py
    fi
}

stop_all() {
    echo -e "${BLUE}Deteniendo servicios en segundo plano...${NC}"
    
    if command -v caddy &> /dev/null; then
        caddy stop &> /dev/null
        echo -e "-> Caddy detenido."
    fi
    
    pkill -f "gunicorn.*5000" &> /dev/null
    echo -e "-> Gunicorn/Flask detenido."
    
    if command -v termux-wake-unlock &> /dev/null; then
        termux-wake-unlock
        echo -e "-> Wake-lock liberado."
    fi
    
    echo -e "${GREEN}Todos los servicios se han detenido.${NC}"
}

if [ $# -eq 0 ]; then
    run_app
    exit 0
fi

case $1 in
    start)   run_app ;;
    stop)    stop_all ;;
    install) install_dependencies ;;
    help)    show_help ;;
    *)       echo -e "${RED}Opción no válida: $1${NC}"; show_help; exit 1 ;;
esac
