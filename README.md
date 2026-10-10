# Gestor de Menús - Aplicación Web con JSON

Esta aplicación es una herramienta para gestionar menús semanales basada en recetas almacenadas en archivos JSON. Permite visualizar los menús, ver los ingredientes necesarios y las recetas completas.

## Características

- Interfaz web responsive usando Flask y Bootstrap
- Carga de datos desde archivos JSON organizados en carpetas
- Visualización de menús semanales con recetas
- Lista de la compra agrupada por ingredientes
- Visualización detallada de recetas con ingredientes, utensilios y pasos

## Estructura del Proyecto

```
.
├── app.py              # Punto de entrada de la aplicación
├── requirements.txt    # Dependencias del proyecto
├── templates/          # Plantillas HTML
│   ├── base.html       # Plantilla base
│   └── index.html      # Página principal
├── data/               # Directorio para archivos JSON (se crea automáticamente)
│   ├── menus/          # Archivos de menús semanales
│   └── recetas/        # Archivos de recetas
└── run.sh              # Script para ejecutar la aplicación
```

## Requisitos

- Python 3.6+
- Flask

## Instalación

1. Clona este repositorio
2. Crea un entorno virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate  # En Windows: venv\Scripts\activate
   ```
3. Instala las dependencias:
   ```bash
   pip install -r requirements.txt
   ```

## Ejecución

Para ejecutar la aplicación:

```bash
python app.py
```

O usando el script de ejecución:

```bash
./run.sh
```

La aplicación se ejecutará en http://localhost:5000

## Funcionalidades

- Visualización de menús semanales
- Lista de la compra agrupada por ingredientes
- Visualización detallada de recetas
- Carga automática de datos desde archivos JSON

## Estructura de Datos

### Menús (en `data/menus/`)
Cada archivo JSON representa un menú semanal con:
- `titulo`: Título del menú
- `dias`: Array de días con comidas y cenas

### Recetas (en `data/recetas/`)
Cada archivo JSON representa una receta con:
- `nombre`: Nombre de la receta
- `utensilios`: Lista de utensilios necesarios
- `ingredientes`: Objeto con ingredientes y cantidades
- `pasos`: Lista de pasos de preparación

## Uso

1. Ejecuta la aplicación con `python app.py` o `./run.sh`
2. Abre tu navegador en http://localhost:5000
3. Selecciona un menú para ver los detalles