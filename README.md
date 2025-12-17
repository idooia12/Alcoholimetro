# 🍺 Alcoholímetro IoT con Raspberry Pi 5

![Python](https://img.shields.io/badge/Python-3.11-blue?style=for-the-badge&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-Web_Server-green?style=for-the-badge&logo=flask&logoColor=white)
![Raspberry Pi](https://img.shields.io/badge/Raspberry_Pi-5-C51A4A?style=for-the-badge&logo=raspberry-pi&logoColor=white)
![Status](https://img.shields.io/badge/Status-Terminado-success?style=for-the-badge)

Este proyecto implementa un sistema de medición de concentración de alcohol en aire (mg/L) en tiempo real utilizando una **Raspberry Pi 5**.



## 📋 Características Principales

* **Monitorización en Tiempo Real:** Lectura continua del sensor de gas MQ303A.
* **Doble Interfaz:**
    * **Local:** Pantalla OLED y LEDs indicadores de estado (Normal/Alerta).
    * **Remota:** Web App (Flask) con medidor tipo "gauge" y gráfica histórica interactiva.
* **Arquitectura Robusta:** Uso de `multiprocessing` para superar las limitaciones del GIL de Python.
* **Calibración Automática:** Ajuste de línea base de aire limpio al inicio.



## 🛠️ Hardware Necesario

* **Procesador:** Raspberry Pi 5.
* **Sensor:** Grove Alcohol Sensor v1.2 (MQ303A).
* **ADC:** Grove I2C ADC v1.2 (Conversor Analógico-Digital).
* **Pantalla:** Grove OLED Display 0.96" (SSD1306).
* **Actuadores:** 2 LEDs (Verde/Rojo) + Resistencias.
* **Conexión:** Grove Base Hat o cableado I2C directo.

## 🚀 Instalación y Ejecución

### Requisitos
* Raspberry Pi 5 con Raspberry Pi OS
* Python 3.10+
* I2C habilitado
* Componentes conectados (sensor, ADC, OLED, LEDs)

### Instalación
* Clonar el repositorio:  
  ```
  git clone https://github.com/idooia12/Alcoholimetro.git  
  cd Alcoholimetro
  ```
* Crear entorno virtual e instalar dependencias:
  ```
  python3 -m venv venv  
  source venv/bin/activate  
  pip install flask smbus2 luma.oled RPi.GPIO  
  ```

### Ejecución
* Lanzar el sistema: `sudo python3 alcoholimetro.py`
* Durante el arranque se realiza una **calibración automática** (no soplar).

### Interfaz Web
* Accesible desde cualquier dispositivo en la misma red: `http://<IP_RASPBERRY>:5000`

### Apagado
* Detener el programa: `Ctrl + C`
* Apagar la Raspberry Pi: `sudo shutdown -h now`
