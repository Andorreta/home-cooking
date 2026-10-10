from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import json
import os
import glob
import re

# Paleta de colores para distinguir menús en el calendario
MENU_COLORS = ['#4e79a7', '#e15759', '#59a14f', '#f28e2b', '#b07aa1', '#76b7b2', '#edc948', '#ff9da7']

app = Flask(__name__)

# Ruta a los archivos JSON
DATA_DIR = 'data'

def parse_quantity(qty_str):
    """Parsea una cantidad de ingrediente"""
    if not qty_str:
        return {"val": 0, "unit": ""}
    
    qty_str = str(qty_str).lower().strip()
    
    # Manejar fracciones
    if '/' in qty_str:
        parts = qty_str.split('/')
        if len(parts) == 2:
            try:
                num = float(parts[0])
                den = float(parts[1])
                val = num / den
                unit = qty_str.replace(f"{num}/{den}", "").strip()
                return {"val": val, "unit": unit}
            except:
                pass
    
    # Manejar cantidades con unidades (g, ml, etc.)
    match = re.match(r'^([\d.]+)\s*(.*)$', qty_str)
    if match:
        val = float(match.group(1))
        unit = match.group(2).strip()
        # Si la unidad está en la parte final y es g o ml, usarla
        if unit.endswith(('g', 'ml', 'kg', 'l', 'unidad', 'unidades', 'pizca', 'cucharada', 'cucharadita')):
            return {"val": val, "unit": unit}
        else:
            return {"val": val, "unit": ""}
    
    return {"val": 0, "unit": qty_str}

def normalize_ingredient(key, value):
    """
    Normaliza un ingrediente:
    - "aceite_de_oliva_ml": 10 -> "aceite de oliva": {"val": 10, "unit": "ml"}
    - "Pasta fresca": "100 gr" -> "Pasta fresca": {"val": 100, "unit": "gr"}
    """
    # 1. Caso: llave con sufijo de unidad (ej: aceite_de_oliva_ml)
    match = re.match(r'^(.*)_([a-z]+)$', key)
    if match:
        new_key = match.group(1).replace('_', ' ')
        unit_from_key = match.group(2)
        
        if isinstance(value, (int, float)):
            return new_key, {"val": float(value), "unit": unit_from_key}
        
        if isinstance(value, str):
            parsed = parse_quantity(value)
            # Si el string tiene su propia unidad, la priorizamos, si no, usamos la de la llave
            return new_key, {"val": parsed['val'], "unit": parsed['unit'] if parsed['unit'] else unit_from_key}
        
        if isinstance(value, dict):
            qty_str = value.get('cantidad', '')
            parsed = parse_quantity(qty_str)
            new_val = {"val": parsed['val'], "unit": parsed['unit']}
            if value.get('opcional') in [True, "yes", "sí"]:
                new_val['opcional'] = True
            return new_key, new_val

    # 2. Caso: valor es string tipo "100 gr"
    if isinstance(value, str):
        parsed = parse_quantity(value)
        if parsed['val'] > 0:
            return key, parsed

    # 3. Caso: valor es un diccionario (formato antiguo)
    if isinstance(value, dict):
        qty_str = value.get('cantidad', '')
        if qty_str:
            parsed = parse_quantity(qty_str)
            new_val = {"val": parsed['val'], "unit": parsed['unit']}
            if value.get('opcional') in [True, "yes", "sí"]:
                new_val['opcional'] = True
            return key, new_val

    return key, value

def load_json_files(directory):
    """Carga todos los archivos JSON de un directorio"""
    data = {}
    if os.path.exists(directory):
        for filename in os.listdir(directory):
            if filename.endswith('.json'):
                filepath = os.path.join(directory, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        key = filename.replace('.json', '')
                        data[key] = json.load(f)
                except Exception as e:
                    print(f"Error cargando {filename}: {e}")
    return data

def get_shopping_list(menus_data, recetas_data):
    """Genera la lista de la compra agrupada por ingredientes"""
    mandatory_ingredients = {}
    optional_ingredients = {}
    
    for menu_name, menu in menus_data.items():
        if 'dias' in menu:
            for day in menu['dias']:
                # Procesar comida y cena
                for meal_type in ['comida', 'cena']:
                    if f'id_{meal_type}' in day and day[f'id_{meal_type}'] and day[f'id_{meal_type}'] != "sobras":
                        receta_id = day[f'id_{meal_type}']
                        if receta_id in recetas_data:
                            receta = recetas_data[receta_id]
                            if 'ingredientes' in receta:
                                for ingrediente, data in receta['ingredientes'].items():
                                    process_ingredient(ingrediente, data, mandatory_ingredients, optional_ingredients)
    
    return mandatory_ingredients, optional_ingredients

def process_ingredient(ingrediente, data, mandatory_map, optional_map):
    """Procesa un ingrediente para la lista de la compra"""
    # Normalizamos primero el ingrediente y su valor
    ingrediente, data = normalize_ingredient(ingrediente, data)
    
    if not ingrediente:
        return

    is_optional = False
    val = 0
    unit = ""

    if isinstance(data, dict):
        val = data.get('val', 0)
        unit = data.get('unit', '')
        is_optional = data.get('opcional', False)
    elif isinstance(data, (int, float)):
        val = float(data)
    elif isinstance(data, str):
        parsed = parse_quantity(data)
        val = parsed['val']
        unit = parsed['unit']

    target_map = optional_map if is_optional else mandatory_map
    
    if val > 0:
        if ingrediente not in target_map:
            target_map[ingrediente] = {}
        
        unit_key = unit or ''
        current_val = target_map[ingrediente].get(unit_key, 0)
        target_map[ingrediente][unit_key] = current_val + val

# Ruta principal
@app.route('/')
def index():
    return render_template('index.html')

def get_menu_range(menu_name, menu):
    """Devuelve (fecha_inicio, fecha_fin) del menú.
    Usa los campos explícitos del JSON y, si no existen, los deriva
    del nombre del archivo (semana_YYYYMMDD) y del número de días."""
    ini = menu.get('fecha_inicio')
    if ini:
        try:
            d_ini = datetime.strptime(ini, '%Y-%m-%d')
            fin = menu.get('fecha_fin')
            if fin:
                d_fin = datetime.strptime(fin, '%Y-%m-%d')
            else:
                d_fin = d_ini + timedelta(days=max(len(menu.get('dias', [])), 1) - 1)
            return d_ini, d_fin
        except ValueError:
            pass
    match = re.match(r'^semana_(\d{8})$', menu_name)
    if not match:
        return None, None
    d_ini = datetime.strptime(match.group(1), '%Y%m%d')
    d_fin = d_ini + timedelta(days=max(len(menu.get('dias', [])), 1) - 1)
    return d_ini, d_fin

# Ruta para obtener menús
@app.route('/api/menus')
def get_menus():
    menus_data = load_json_files(os.path.join(DATA_DIR, 'menus'))
    resultado = []
    for i, name in enumerate(sorted(menus_data.keys())):
        menu = menus_data[name]
        d_ini, d_fin = get_menu_range(name, menu)
        resultado.append({
            'id': name,
            'titulo': menu.get('titulo', name),
            'fecha_inicio': d_ini.strftime('%Y-%m-%d') if d_ini else None,
            'fecha_fin': d_fin.strftime('%Y-%m-%d') if d_fin else None,
            'color': menu.get('color') or MENU_COLORS[i % len(MENU_COLORS)],
        })
    resultado.sort(key=lambda m: (m['fecha_inicio'] or '9999-99-99', m['id']))
    return jsonify(resultado)

# Ruta para obtener datos de un menú específico
@app.route('/api/menu/<menu_name>')
def get_menu(menu_name):
    menus_data = load_json_files(os.path.join(DATA_DIR, 'menus'))
    recetas_data = load_json_files(os.path.join(DATA_DIR, 'recetas'))
    
    if menu_name in menus_data:
        menu = menus_data[menu_name]
        
        # Generar lista de la compra
        mandatory_ingredients, optional_ingredients = get_shopping_list({menu_name: menu}, recetas_data)
        
        # Preparar datos para la respuesta
        menu_data = {
            'menu': menu,
            'mandatory_ingredients': mandatory_ingredients,
            'optional_ingredients': optional_ingredients,
            'recetas': recetas_data
        }
        return jsonify(menu_data)
    else:
        return jsonify({'error': 'Menú no encontrado'}), 404

# Ruta para obtener datos de una receta específica
@app.route('/api/receta/<receta_id>')
def get_receta(receta_id):
    recetas_data = load_json_files(os.path.join(DATA_DIR, 'recetas'))
    
    if receta_id in recetas_data:
        # Normalizar receta antes de devolverla
        receta = recetas_data[receta_id].copy()
        if 'ingredientes' in receta:
            new_ing = {}
            for k, v in receta['ingredientes'].items():
                nk, nv = normalize_ingredient(k, v)
                new_ing[nk] = nv
            receta['ingredientes'] = new_ing
        return jsonify(receta)
    else:
        return jsonify({'error': 'Receta no encontrada'}), 404

# Ruta para obtener todas las recetas
@app.route('/api/recetas')
def get_recetas():
    recetas_data = load_json_files(os.path.join(DATA_DIR, 'recetas'))
    return jsonify(list(recetas_data.keys()))

if __name__ == '__main__':
    # Crear directorios de datos si no existen
    os.makedirs(os.path.join(DATA_DIR, 'menus'), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, 'recetas'), exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)