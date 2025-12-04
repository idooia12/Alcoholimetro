import smbus2
import time
import RPi.GPIO as GPIO
import threading
from flask import Flask, render_template, jsonify

# Importar librerías de OLED
from luma.oled.device import ssd1306
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from PIL import ImageDraw, ImageFont

# --- CONFIGURACIÓN FLASK ---
app = Flask(__name__)

# --- CONFIGURACIÓN HARDWARE ---
I2C_BUS = 1
BUS = smbus2.SMBus(I2C_BUS)
ADC_ADDRESS = 0x50   # ADC121C021
OLED_ADDRESS = 0x3C  # SSD1306
ADC_REG_CONVERSION = 0x00

LED_NORMAL_PIN = 17
LED_ALERTA_PIN = 27

MAX_ADC_RAW = 4095
DELTA_MINIMO = 40 
DELTA_POSITIVO = 100 

# --- VARIABLES GLOBALES COMPARTIDAS ---
baseline_raw = 0 
global_raw_value = 0
global_rs_ro_ratio = 0.0 
running = True
value_lock = threading.Lock() # Para evitar conflictos entre Flask y el Sensor
oled_device = None

# --- FUNCIONES HARDWARE ---

def read_adc_raw():
    try:
        data = BUS.read_i2c_block_data(ADC_ADDRESS, ADC_REG_CONVERSION, 2)
        return ((data[0] & 0x0F) << 8) | data[1]
    except IOError:
        return 0

def calibrate_sensor():
    global baseline_raw
    print("Calibrando sensor... (No soplar)")
    if oled_device:
        with canvas(oled_device) as draw:
            draw.text((10, 20), "CALIBRANDO...", fill="white")
            draw.text((10, 40), "Espere...", fill="white")

    readings = []
    for _ in range(30): 
        val = read_adc_raw()
        if val > 0: readings.append(val)
        time.sleep(0.1)
    
    if len(readings) > 0:
        baseline_raw = int(sum(readings) / len(readings))
        print(f"Base establecida: {baseline_raw}")
    else:
        baseline_raw = 1380
        print("Fallo calibración, usando default.")

def calculate_rs_ro_ratio(current_raw):
    if current_raw == 0 or baseline_raw == 0: return 0.0
    if current_raw >= MAX_ADC_RAW: return 0.0
    rs_gas = float(current_raw) / (MAX_ADC_RAW - current_raw)
    rs_air = float(baseline_raw) / (MAX_ADC_RAW - baseline_raw)
    if rs_air == 0: return 0.0
    return rs_gas / rs_air

def setup_hardware():
    global oled_device
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(LED_NORMAL_PIN, GPIO.OUT)
    GPIO.setup(LED_ALERTA_PIN, GPIO.OUT)
    try:
        serial = i2c(port=I2C_BUS, address=OLED_ADDRESS)
        oled_device = ssd1306(serial, width=128, height=64)
        return True
    except:
        return False

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

# --- RUTAS WEB (FLASK) ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/data')
def get_data_json():
    # Accedemos a las variables globales de forma segura
    with value_lock:
        raw = global_raw_value
        ratio = global_rs_ro_ratio
        base = baseline_raw

    # Lógica de cálculo (Idéntica a la UI local)
    diff = max(0, base - raw)
    raw_to_mgl = 0.25 / 150 
    conc = diff * raw_to_mgl
    status_text, level = get_alcohol_level(diff)

    return jsonify({
        'raw': raw,
        'baseline': base,
        'diff': diff,
        'ratio': ratio,
        'concentration': conc,
        'status_text': status_text,
        'level': level
    })

# --- HILOS DE EJECUCIÓN ---

def sensor_loop():
    global global_raw_value, global_rs_ro_ratio
    while running:
        raw = read_adc_raw()
        ratio = calculate_rs_ro_ratio(raw)
        with value_lock:
            global_raw_value = raw
            global_rs_ro_ratio = ratio
        time.sleep(0.1)

def ui_local_loop():
    """Controla la pantalla OLED y LEDs locales"""
    raw_to_mgl = 0.25 / 150 
    while running:
        with value_lock:
            raw = global_raw_value
            base = baseline_raw

        diff = max(0, base - raw)
        conc = diff * raw_to_mgl
        status_text, level = get_alcohol_level(diff)
        
        update_leds(level)

        if oled_device:
            with canvas(oled_device) as draw:
                draw.text((0, 0), "Alcoholimetro Web", fill="white")
                draw.text((0, 16), status_text, fill="white")
                draw.text((60, 16), f"{conc:.2f} mg/L", fill="white")
                draw_progress_bar(draw, diff, 250, 32)
                draw.text((0, 48), f"IP: Ver consola", fill="white")
        
        time.sleep(0.2)

# --- MAIN ---

def main():
    global running
    if not setup_hardware():
        print("Error Hardware - Revisar conexiones I2C")
        return
    
    calibrate_sensor()

    # 1. Hilo Sensor (Lee datos constantemente)
    t_sensor = threading.Thread(target=sensor_loop)
    t_sensor.start()

    # 2. Hilo UI Local (OLED y LEDs)
    t_ui = threading.Thread(target=ui_local_loop)
    t_ui.start()

    # 3. Hilo Servidor Web (Flask)
    # Flask bloquea la ejecución, por eso lo lanzamos en un hilo aparte
    print("Iniciando servidor web...")
    t_flask = threading.Thread(target=lambda: app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False))
    t_flask.daemon = True # Se cerrará si el programa principal muere
    t_flask.start()

    print("SISTEMA LISTO.")
    print("Accede vía web en: http://<IP-DE-TU-RASPBERRY>:5000")

    try:
        while True: time.sleep(1)
    except KeyboardInterrupt:
        print("\nApagando...")
        running = False
        t_sensor.join()
        t_ui.join()
        GPIO.cleanup()
        print("Bye")

if __name__ == "__main__":
    main()