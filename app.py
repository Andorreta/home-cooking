from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
import json
import os
import glob
import re
import urllib.request
import urllib.error

# Paleta de colores para distinguir menús en el calendario
MENU_COLORS = ['#4e79a7', '#e15759', '#59a14f', '#f28e2b', '#b07aa1', '#76b7b2', '#edc948', '#ff9da7']

DIAS_SEMANA = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']

app = Flask(__name__)

# Ruta a los archivos JSON
DATA_DIR = 'data'

def load_llm_config():
    """Config del LLM (Strata, API compatible OpenAI): config_local.json o variables de entorno."""
    cfg = {
        'url': os.environ.get('STRATA_URL', 'http://192.168.1.12:9931'),
        'api_key': os.environ.get('STRATA_API_KEY', ''),
        'model': os.environ.get('STRATA_MODEL', ''),
    }
    if os.path.exists('config_local.json'):
        try:
            with open('config_local.json', 'r', encoding='utf-8') as f:
                local = json.load(f)
            cfg['url'] = local.get('strata_url', cfg['url'])
            cfg['api_key'] = local.get('strata_api_key', cfg['api_key'])
            cfg['model'] = local.get('strata_model', cfg['model'])
        except Exception as e:
            print(f"Error leyendo config_local.json: {e}")
    return cfg

def load_preferencias():
    """Preferencias y restricciones del usuario para el prompt de generación."""
    defaults = {
        'restricciones': [],
        'platos_habituales': [],
        'favoritas': [],
        'evitar_repetir_de_semanas': 4,
    }
    path = os.path.join(DATA_DIR, 'preferencias.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                prefs = json.load(f)
            defaults.update(prefs)
        except Exception as e:
            print(f"Error leyendo preferencias.json: {e}")
    return defaults

# Utensilios que NO se permiten (el usuario solo tiene una cazuela, una sartén y un microondas con grill)
UTENSILIOS_PERMITIDOS = ('cazuela', 'sartén', 'sarten', 'microondas', 'cuchillo', 'varillas', 'tupper', 'recipiente', 'plato apto')

def utensilios_compatibles(receta):
    """True si la receta se puede hacer solo con cazuela, sartén y microondas con grill."""
    for u in receta.get('utensilios', []):
        u_low = u.lower()
        if not any(p in u_low for p in UTENSILIOS_PERMITIDOS):
            return False
    return True

def get_recetas_usadas_recently(menus_data, fecha_inicio, semanas):
    """Ids de recetas usadas en menús que empezaron dentro de las últimas `semanas`."""
    usados = set()
    try:
        limite = datetime.strptime(fecha_inicio, '%Y-%m-%d') - timedelta(weeks=semanas)
    except ValueError:
        return usados
    for name, menu in menus_data.items():
        d_ini, d_fin = get_menu_range(name, menu)
        if d_ini and limite <= d_ini < datetime.strptime(fecha_inicio, '%Y-%m-%d'):
            for dia in menu.get('dias', []):
                for clave in ('id_comida', 'id_cena'):
                    rid = dia.get(clave)
                    if rid and rid != 'sobras':
                        usados.add(rid)
    return usados

def call_llm(cfg, messages, max_tokens=2500, temperature=0.8):
    """Llamada a /v1/chat/completions (Strata/llama.cpp). Devuelve el content del asistente."""
    body = json.dumps({
        'model': cfg['model'],
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }).encode('utf-8')
    req = urllib.request.Request(
        cfg['url'].rstrip('/') + '/v1/chat/completions',
        data=body,
        headers={'Content-Type': 'application/json', 'Authorization': f"Bearer {cfg['api_key']}"},
    )
    with urllib.request.urlopen(req, timeout=240) as resp:
        data = json.load(resp)
    choice = (data.get('choices') or [{}])[0]
    content = (choice.get('message') or {}).get('content')
    if not content:
        raise ValueError("El modelo no devolvió contenido (¿max_tokens agotado por el razonamiento?)")
    return content

def parse_llm_json(text):
    """Extrae el JSON de la respuesta, tolerando cercas ```json ... ``` o texto alrededor."""
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if not match:
        raise ValueError('La respuesta no contiene JSON')
    return json.loads(match.group(0))

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

# Ruta de la vista de recetas
@app.route('/recetas')
def recetas():
    return render_template('recetas.html')

# Ruta de la vista de generación de menús
@app.route('/generar')
def generar():
    return render_template('generar.html')

# Ruta para consultar las preferencias usadas al generar
@app.route('/api/preferencias')
def api_preferencias():
    return jsonify(load_preferencias())

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

# Ruta para obtener todas las recetas (id + nombre, ordenadas alfabéticamente)
@app.route('/api/recetas')
def get_recetas():
    recetas_data = load_json_files(os.path.join(DATA_DIR, 'recetas'))
    resultado = [
        {'id': key, 'nombre': receta.get('nombre', key)}
        for key, receta in recetas_data.items()
    ]
    resultado.sort(key=lambda r: r['nombre'].lower())
    return jsonify(resultado)

# Ruta para generar un menú con el LLM (Strata) y guardarlo
@app.route('/api/generar', methods=['POST'])
def api_generar():
    datos = request.get_json(silent=True) or {}
    fecha_inicio = datos.get('fecha_inicio', '')
    fecha_fin = datos.get('fecha_fin', '')

    try:
        d_ini = datetime.strptime(fecha_inicio, '%Y-%m-%d')
        d_fin = datetime.strptime(fecha_fin, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'Fechas inválidas (formato AAAA-MM-DD)'}), 400
    n_dias = (d_fin - d_ini).days + 1
    if not (1 <= n_dias <= 14):
        return jsonify({'error': 'El rango debe ser de 1 a 14 días'}), 400

    cfg = load_llm_config()
    if not cfg['api_key'] or not cfg['model']:
        return jsonify({'error': 'Falta la configuración del LLM (config_local.json: strata_api_key/strata_model)'}), 500

    recetas_data = load_json_files(os.path.join(DATA_DIR, 'recetas'))
    catalogo = {
        rid: r.get('nombre', rid)
        for rid, r in recetas_data.items()
        if utensilios_compatibles(r)
    }
    if len(catalogo) < n_dias:
        return jsonify({'error': f'No hay suficientes recetas compatibles con tus utensilios ({len(catalogo)})'}), 400

    prefs = load_preferencias()
    menus_data = load_json_files(os.path.join(DATA_DIR, 'menus'))
    usados = get_recetas_usadas_recently(menus_data, fecha_inicio, prefs.get('evitar_repetir_de_semanas', 4))
    favoritas = set(prefs.get('favoritas', []))

    rango_dias = ', '.join(DIAS_SEMANA[(d_ini + timedelta(days=i)).weekday()] for i in range(n_dias))
    catalogo_txt = '\n'.join(f'{rid}: {nombre}' for rid, nombre in sorted(catalogo.items(), key=lambda x: x[1].lower()))
    habituales_txt = ', '.join(prefs.get('platos_habituales', [])) or '(sin lista)'
    usados_txt = ', '.join(
        f'{rid} ({catalogo.get(rid, "?")})' + (' ★favorita' if rid in favoritas else '')
        for rid in sorted(usados)
    ) or '(ninguna)'
    favoritas_txt = ', '.join(f'{rid} ({catalogo.get(rid, "?")})' for rid in sorted(favoritas) if rid in catalogo) or '(sin lista)'

    system = ('Eres el planificador de comidas de un usuario con hipersensibilidad sensorial (autismo). '
              'Respetas estrictamente sus restricciones. Respondes SOLO con JSON válido, sin explicaciones ni cercas de código.')
    user_prompt = f"""Genera un menú de {n_dias} días, del {fecha_inicio} al {fecha_fin} (días: {rango_dias}).

RESTRICCIONES OBLIGATORIAS:
{chr(10).join('- ' + r for r in prefs.get('restricciones', []))}

CATÁLOGO DE RECETAS DISPONIBLES (ya filtradas por utensilios; elige SOLO ids exactos de esta lista; id: nombre):
{catalogo_txt}

RECETAS YA USADAS EN LAS ÚLTIMAS {prefs.get('evitar_repetir_de_semanas', 4)} SEMANAS (procura NO repetir estas, PERO las marcadas con ★favorita sí se pueden repetir aunque sean recientes: uno nunca se cansa de lo que le gusta):
{usados_txt}

RECETAS FAVORITAS (pueden repetirse siempre, incluso si ya salieron hace poco; si encajan, alguna puede aparecer en el menú):
{favoritas_txt}

PLATOS QUE SUELE COMER (referencia de sus gustos; si existe una receta parecida en el catálogo, priorízala; si un plato de esta lista incumple las restricciones, IGNÓRALO):
{habituales_txt}

REGLAS DE COMPOSICIÓN:
- {n_dias} elementos en "dias", en orden: {rango_dias}.
- Cada día: "comida" (plato principal) y "cena" (más ligero), con ids del catálogo.
- No repetir la misma receta en toda la semana.
- Variar el tipo de plato entre días (no pasta dos días seguidos, por ejemplo).

DEVUELVE EXACTAMENTE este JSON:
{{"titulo": "título corto y descriptivo del menú", "dias": [{{"comida": "<id>", "cena": "<id>"}}{', ...' if n_dias > 1 else ''}]}}"""

    messages = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user_prompt}]

    error_anterior = None
    for intento in range(2):
        try:
            contenido = call_llm(cfg, messages)
            generado = parse_llm_json(contenido)
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            return jsonify({'error': f'No se pudo contactar con el LLM ({cfg["url"]}): {e}'}), 502
        except (ValueError, json.JSONDecodeError) as e:
            error_anterior = f'JSON inválido: {e}'
            messages.append({'role': 'user', 'content': f'Error: {error_anterior}. Repite la respuesta SOLO con el JSON correcto.'})
            continue

        dias = generado.get('dias', [])
        problemas = []
        if len(dias) != n_dias:
            problemas.append(f'se esperaban {n_dias} días y vienen {len(dias)}')
        ids_del_menu = []
        for i, dia in enumerate(dias):
            for clave in ('comida', 'cena'):
                rid = str(dia.get(clave, ''))
                if rid not in catalogo:
                    problemas.append(f'día {i + 1}: id "{rid}" no está en el catálogo')
                else:
                    ids_del_menu.append(rid)
        if len(set(ids_del_menu)) != len(ids_del_menu):
            problemas.append('hay recetas repetidas en el menú')
        if problemas:
            error_anterior = '; '.join(problemas)
            messages.append({'role': 'user', 'content': 'Error en tu JSON: ' + error_anterior + '. Repite SOLO el JSON corrigiéndolo, usando ids exactos del catálogo.'})
            continue

        menu = {
            'titulo': generado.get('titulo') or f'Semana {d_ini.strftime("%d %b")} - {d_fin.strftime("%d %b %Y")}',
            'fecha_inicio': fecha_inicio,
            'fecha_fin': fecha_fin,
            'dias': [
                {
                    'dia': DIAS_SEMANA[(d_ini + timedelta(days=i)).weekday()],
                    'comida': catalogo[dia['comida']],
                    'id_comida': dia['comida'],
                    'cena': catalogo[dia['cena']],
                    'id_cena': dia['cena'],
                }
                for i, dia in enumerate(dias)
            ],
        }

        os.makedirs(os.path.join(DATA_DIR, 'menus'), exist_ok=True)
        archivo = f'semana_{d_ini.strftime("%Y%m%d")}.json'
        ruta = os.path.join(DATA_DIR, 'menus', archivo)
        existente = os.path.exists(ruta)
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(menu, f, ensure_ascii=False, indent=2)
            f.write('\n')

        return jsonify({'ok': True, 'archivo': archivo, 'sobrescrito': existente, 'menu': menu})

    return jsonify({'error': f'El modelo generó un menú inválido tras 2 intentos: {error_anterior}'}), 502

if __name__ == '__main__':
    # Crear directorios de datos si no existen
    os.makedirs(os.path.join(DATA_DIR, 'menus'), exist_ok=True)
    os.makedirs(os.path.join(DATA_DIR, 'recetas'), exist_ok=True)
    
    app.run(debug=True, host='0.0.0.0', port=5000)