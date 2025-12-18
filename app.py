import smbus2
import time
import RPi.GPIO as GPIO
import threading
import multiprocessing # IMPORTANTE: Sustituye en gran parte a threading
from collections import deque
from flask import Flask, render_template, jsonify
# from flask_cors import CORS # Opcional: Recomendado para producción

# Importar librerías de OLED
from luma.oled.device import ssd1306
from luma.core.interface.serial import i2c
from luma.core.render import canvas

# --- CONFIGURACIÓN HARDWARE (Constantes) ---
I2C_BUS = 1
ADC_ADDRESS = 0x50
OLED_ADDRESS = 0x3C
ADC_REG_CONVERSION = 0x00
LED_NORMAL_PIN = 17
LED_ALERTA_PIN = 27
MAX_ADC_RAW = 4095
DELTA_MINIMO = 40
DELTA_POSITIVO = 100
RAW_TO_MGL = 0.25 / 150

# Variable global para la linea base (solo usada en el proceso de hardware)
hardware_baseline_raw = 1380

# --- FUNCIONES HARDWARE (Se ejecutarán en el Proceso HW) ---

def setup_hardware_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LED_NORMAL_PIN, GPIO.OUT)
    GPIO.setup(LED_ALERTA_PIN, GPIO.OUT)

def get_oled_device():
    try:
        bus = smbus2.SMBus(I2C_BUS) # Bus local al proceso/hilo
        serial = i2c(port=I2C_BUS, address=OLED_ADDRESS, bus=bus)
        return ssd1306(serial, width=128, height=64)
    except:
        return None

def read_adc_raw(bus):
    try:
        data = bus.read_i2c_block_data(ADC_ADDRESS, ADC_REG_CONVERSION, 2)
        return ((data[0] & 0x0F) << 8) | data[1]
    except IOError:
        return 0

def calibrate_sensor(bus, oled):
    global hardware_baseline_raw
    print("HW PROC: Calibrando sensor... (No soplar)")
    if oled:
        with canvas(oled) as draw:
            draw.text((10, 20), "CALIBRANDO...", fill="white")
            draw.text((10, 40), "Espere...", fill="white")

    readings = []
    for _ in range(30):
        val = read_adc_raw(bus)
        if val > 0: readings.append(val)
        time.sleep(0.1)
    
    if len(readings) > 0:
        hardware_baseline_raw = int(sum(readings) / len(readings))
        print(f"HW PROC: Base establecida: {hardware_baseline_raw}")
    else:
        hardware_baseline_raw = 1380
        print("HW PROC: Fallo calibración, usando default.")

def get_alcohol_level(diff):
    if diff < DELTA_MINIMO: return "Normal", 0
    elif diff < DELTA_POSITIVO: return "Traza", 1
    else: return "ALCOHOL", 2

def update_leds(level):
    if level == 2: # Alcohol
        GPIO.output(LED_NORMAL_PIN, GPIO.LOW)
        GPIO.output(LED_ALERTA_PIN, GPIO.HIGH)
    else: # Normal o Traza
        GPIO.output(LED_NORMAL_PIN, GPIO.HIGH)
        GPIO.output(LED_ALERTA_PIN, GPIO.LOW)

def draw_progress_bar(draw, value, max_value, y_pos):
    width = 120
    height = 8
    fill_width = int((min(value, max_value) / max_value) * width)
    draw.rectangle((0, y_pos, width, y_pos + height), outline="white", fill="black")
    draw.rectangle((0, y_pos, fill_width, y_pos + height), outline="white", fill="white")

# --- HILOS INTERNOS DEL PROCESO HARDWARE ---

def hardware_sensor_loop(shared_data_dict, shared_history_list, bus_lock):
    """Hilo interno HW: Lee sensor y actualiza memoria compartida"""
    bus = smbus2.SMBus(I2C_BUS) # Cada hilo debe tener su propia instancia del bus o usar lock
    
    while True:
        # Usamos un lock para el bus I2C si varios hilos acceden a él
        with bus_lock:
             raw = read_adc_raw(bus)
        
        diff = max(0, hardware_baseline_raw - raw)
        conc = diff * RAW_TO_MGL
        status_text, level = get_alcohol_level(diff)
        timestamp = time.strftime("%H:%M:%S")

        # --- ACTUALIZACIÓN DE MEMORIA COMPARTIDA ENTRE PROCESOS ---
        # El Manager de multiprocessing se encarga del bloqueo interno
        shared_data_dict['raw'] = raw
        shared_data_dict['baseline'] = hardware_baseline_raw
        shared_data_dict['diff'] = diff
        shared_data_dict['concentration'] = conc
        shared_data_dict['status_text'] = status_text
        shared_data_dict['level'] = level

        # Gestionar el historial (limitado a 60)
        shared_history_list.append({"time": timestamp, "val": conc})
        if len(shared_history_list) > 60:
             shared_history_list.pop(0)
        # ----------------------------------------------------------

        time.sleep(0.5)

def hardware_ui_loop(shared_data_dict):
    """Hilo interno HW: Lee memoria compartida y actualiza OLED/LEDs"""
    oled = get_oled_device()
    if not oled: print("HW PROC: Error OLED")

    while True:
        # Leemos del diccionario compartido (es seguro en multiproceso)
        data = shared_data_dict.copy() 
        
        update_leds(data.get('level', 0))

        if oled:
            with canvas(oled) as draw:
                draw.text((0, 0), "Alcoholimetro PRO", fill="white")
                draw.text((0, 16), data.get('status_text', 'Init'), fill="white")
                draw.text((60, 16), f"{data.get('concentration', 0.0):.2f} mg/L", fill="white")
                draw.text((0, 48), f"Modo: Multi-Proceso", fill="white")
        
        time.sleep(0.1)

# --- FUNCIÓN PRINCIPAL DEL PROCESO HARDWARE ---
def run_hardware_process(shared_data_dict, shared_history_list):
    print(">>> PROCESO HARDWARE INICIADO (PID: {})".format(multiprocessing.current_process().pid))
    setup_hardware_gpio()
    
    bus = smbus2.SMBus(I2C_BUS)
    oled_calib = get_oled_device()
    calibrate_sensor(bus, oled_calib)
    bus.close() # Cerramos este bus, los hilos abrirán los suyos

    # Lock para sincronizar acceso al bus I2C entre hilos del mismo proceso
    i2c_bus_lock = threading.Lock()

    # Lanzamos los hilos internos (sensor y UI)
    t_sensor = threading.Thread(target=hardware_sensor_loop, args=(shared_data_dict, shared_history_list, i2c_bus_lock))
    t_ui = threading.Thread(target=hardware_ui_loop, args=(shared_data_dict,))
    
    t_sensor.daemon = True
    t_ui.daemon = True
    t_sensor.start()
    t_ui.start()

    # El proceso principal de HW se queda vivo esperando a los hilos
    t_sensor.join()
    t_ui.join()


# --- FUNCIÓN PRINCIPAL DEL PROCESO FLASK ---
# Definimos la app Flask fuera para que las rutas la vean, 
# pero la ejecutaremos dentro de su función de proceso.
flask_app = Flask(__name__)
# CORS(flask_app) # Habilitar si es necesario

# Variables "globales" solo dentro del ámbito del proceso Flask
flask_shared_data = None
flask_shared_history = None

@flask_app.route('/')
def index(): return render_template('index.html')

@flask_app.route('/grafica')
def grafica(): return render_template('grafica.html')

@flask_app.route('/data')
def get_data_json():
    # Flask lee directamente del diccionario gestionado por el Manager
    return jsonify(flask_shared_data.copy())

@flask_app.route('/history')
def get_history_json():
    # Flask lee la lista del Manager
    return jsonify(list(flask_shared_history))

def run_flask_process(data_dict, history_list):
    print(">>> PROCESO WEB FLASK INICIADO (PID: {})".format(multiprocessing.current_process().pid))
    
    # Inyectamos las variables compartidas en el ámbito global de ESTE proceso
    global flask_shared_data, flask_shared_history
    flask_shared_data = data_dict
    flask_shared_history = history_list

    # Desactivamos el reloader y debug para evitar que Flask lance sub-procesos propios
    flask_app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)


# --- MAIN PRINCIPAL (LANZADOR) ---

if __name__ == "__main__":
    # Bloque crucial para multiprocessing en Linux/Windows
    multiprocessing.set_start_method('spawn', force=True) # 'spawn' es más seguro y limpio

    print("=== INICIANDO SISTEMA MULTI-PROCESO ===")

    # 1. Crear el Gestor de Memoria Compartida
    manager = multiprocessing.Manager()
    
    # Diccionario compartido para el estado actual (inicializado)
    shared_data_dict = manager.dict({
        "raw": 0, "diff": 0, "concentration": 0.0,
        "baseline": 0, "status_text": "INIT", "level": 0
    })
    # Lista compartida para el historial
    shared_history_list = manager.list()

    # 2. Definir los Procesos
    # Proceso HW: le pasamos los objetos compartidos para que ESCRIVA
    proc_hw = multiprocessing.Process(target=run_hardware_process, args=(shared_data_dict, shared_history_list))
    
    # Proceso Flask: le pasamos los objetos compartidos para que LEA
    proc_flask = multiprocessing.Process(target=run_flask_process, args=(shared_data_dict, shared_history_list))

    # 3. Iniciar los Procesos
    proc_hw.start()
    proc_flask.start()
    
    print(f"Sistema corriendo. HW PID: {proc_hw.pid}, Flask PID: {proc_flask.pid}")
    print("Presiona Ctrl+C para detener todo.")

    try:
        # El script principal espera aquí mientras los hijos trabajan
        proc_hw.join()
        proc_flask.join()
    except KeyboardInterrupt:
        print("\n¡Deteniendo sistema!")
        proc_hw.terminate()
        proc_flask.terminate()
        proc_hw.join()
        proc_flask.join()
        GPIO.cleanup()
        print("Sistema apagado correctamente.")
