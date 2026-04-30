"""
app.py — Nahual Studio Web Service
Servicio de restauración fotográfica con IA
"""

import os
import io
import uuid
import base64
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from PIL import Image, ImageFilter
from google import genai
from google.genai import types
import urllib.request
import numpy as np

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20MB máximo

# --- CONFIGURACIÓN ---
API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODELO = "gemini-3-pro-image-preview"
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'webp'}
UPLOAD_FOLDER = "/tmp/nahual_uploads"
OUTPUT_FOLDER = "/tmp/nahual_outputs"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# --- MODELO SR ---
MODELS_DIR = "/tmp/nahual_sr_models"
FSRCNN_URL = "https://raw.githubusercontent.com/Saafke/FSRCNN_Tensorflow/master/models/FSRCNN_x4.pb"
FSRCNN_PATH = os.path.join(MODELS_DIR, "FSRCNN_x4.pb")
os.makedirs(MODELS_DIR, exist_ok=True)

# --- PROMPTS ---
PROMPTS = {
    "restaurar": (
        "Hola, por favor ayudame a restaurar esta fotografía, necesito que se vea como si fuera recién tomada con cámara profesional. "
        "Ajustando color e iluminación, pero sin añadir absolutamente ningún detalle que pueda alterar el resultado y que deje de parecerse al original. "
        "Pero por sobre todo, respeta los rasgos faciales, para que la persona no se deje de parecer a la original. "
        "El resultado final debe parecer la misma fotografía pero tomada con una cámara de alta gama, sin que se note que ha sido editada digitalmente. "
        "En el caso de la piel, analiza la apariencia de la persona, edad, género, etnia y condiciones de iluminación para aplicar una mejora personalizada que mantenga su identidad visual única, evitando cualquier resultado genérico o artificial."
    ),
    "colorizar": (
        "Aplica color a esta imagen de forma histórica y fotográficamente precisa. "
        "Utiliza una paleta de colores orgánicos, prestando especial atención a los tonos de piel con subtonos cálidos y naturales. "
        "Asegúrate de que la ropa, el fondo y los objetos tengan variaciones tonales lógicas basadas en la iluminación original "
        "y coherentes con la época de la fotografía. "
        "No permitas que el color sature los detalles; la textura de la imagen original debe seguir siendo la protagonista. "
        "El objetivo es que parezca una foto a color original, no pintada digitalmente."
    ),
    "mejorar": (
        "Mejora la calidad general de esta fotografía. "
        "Aumenta el detalle y la nitidez en toda la imagen, incluyendo fondos, ropa y texturas. "
        "Mejora los rostros sin alterarlos, la persona debe seguir siendo idéntica al original. "
        "No cambies la composición ni los colores base de la imagen. "
        "El resultado debe verse como la misma fotografía pero tomada con una cámara de mayor calidad."
    ),
}


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def leer_metadatos(ruta):
    try:
        with Image.open(ruta) as img:
            ancho, alto = img.size
            dpi_info = img.info.get("dpi", None)
            if dpi_info:
                dpi_x, dpi_y = float(dpi_info[0]), float(dpi_info[1])
            else:
                dpi_x, dpi_y = 72.0, 72.0
            formato = img.format or "JPEG"
        return {"ancho": ancho, "alto": alto, "dpi_x": dpi_x, "dpi_y": dpi_y, "formato": formato}
    except:
        return {"ancho": None, "alto": None, "dpi_x": 72.0, "dpi_y": 72.0, "formato": "JPEG"}


def asegurar_modelo_sr():
    if os.path.exists(FSRCNN_PATH):
        return True
    try:
        urllib.request.urlretrieve(FSRCNN_URL, FSRCNN_PATH)
        return True
    except:
        return False


def upscale_imagen(img_pil, ancho_obj, alto_obj):
    try:
        import cv2
        from cv2 import dnn_superres
        if not asegurar_modelo_sr():
            raise RuntimeError("Modelo SR no disponible")
        img_rgb = img_pil.convert("RGB")
        img_np = np.array(img_rgb)
        img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
        sr = dnn_superres.DnnSuperResImpl_create()
        sr.readModel(FSRCNN_PATH)
        sr.setModel("fsrcnn", 4)
        img_up = sr.upsample(img_bgr)
        img_out = Image.fromarray(cv2.cvtColor(img_up, cv2.COLOR_BGR2RGB))
        if img_out.size != (ancho_obj, alto_obj):
            img_out = img_out.resize((ancho_obj, alto_obj), Image.LANCZOS)
        return img_out
    except:
        img_out = img_pil.resize((ancho_obj, alto_obj), Image.LANCZOS)
        img_out = img_out.filter(ImageFilter.UnsharpMask(radius=2.0, percent=180, threshold=2))
        img_out = img_out.filter(ImageFilter.UnsharpMask(radius=0.5, percent=80, threshold=1))
        return img_out


def restaurar_imagen(bytes_ia, metadatos, ruta_salida):
    try:
        ancho = metadatos.get("ancho")
        alto = metadatos.get("alto")
        dpi_x = metadatos.get("dpi_x", 72.0)
        dpi_y = metadatos.get("dpi_y", 72.0)

        img = Image.open(io.BytesIO(bytes_ia))
        if img.mode != "RGB":
            img = img.convert("RGB")

        if ancho and alto and img.size != (ancho, alto):
            img = upscale_imagen(img, ancho, alto)

        ext = os.path.splitext(ruta_salida)[1].lower()
        if ext in (".jpg", ".jpeg"):
            img.save(ruta_salida, format="JPEG", dpi=(dpi_x, dpi_y), quality=97, subsampling=0)
        else:
            img.save(ruta_salida, format="PNG", dpi=(dpi_x, dpi_y))
        return True
    except Exception as e:
        print(f"[ERROR restaurar]: {e}")
        return False


def procesar_con_gemini(ruta_imagen, accion):
    if not API_KEY:
        return None, "API Key no configurada en el servidor."

    prompt = PROMPTS.get(accion)
    if not prompt:
        return None, f"Acción desconocida: {accion}"

    try:
        client = genai.Client(api_key=API_KEY)
        metadatos = leer_metadatos(ruta_imagen)

        with open(ruta_imagen, "rb") as f:
            img_data = f.read()

        ext = os.path.splitext(ruta_imagen)[1].lower()
        mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"

        parts = [
            types.Part.from_bytes(data=img_data, mime_type=mime),
            types.Part.from_text(text=prompt)
        ]

        response = client.models.generate_content(
            model=MODELO,
            contents=[types.Content(role="user", parts=parts)]
        )

        bytes_resultado = None
        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    bytes_resultado = part.inline_data.data
                    break

        if not bytes_resultado:
            return None, "Gemini no devolvió imagen."

        # Guardar con upscaling
        nombre_out = f"{uuid.uuid4().hex}_resultado.jpg"
        ruta_out = os.path.join(OUTPUT_FOLDER, nombre_out)
        exito = restaurar_imagen(bytes_resultado, metadatos, ruta_out)

        if exito:
            return ruta_out, None
        else:
            # Respaldo sin upscaling
            with open(ruta_out, "wb") as f:
                f.write(bytes_resultado)
            return ruta_out, None

    except Exception as e:
        return None, str(e)


# ==================== RUTAS ====================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/procesar", methods=["POST"])
def procesar():
    if "foto" not in request.files:
        return jsonify({"status": "error", "msg": "No se recibió ninguna imagen."})

    archivo = request.files["foto"]
    accion = request.form.get("accion", "restaurar")

    if archivo.filename == "":
        return jsonify({"status": "error", "msg": "Nombre de archivo vacío."})

    if not allowed_file(archivo.filename):
        return jsonify({"status": "error", "msg": "Formato no soportado. Usa JPG, PNG o WEBP."})

    # Guardar archivo temporalmente
    nombre_seguro = f"{uuid.uuid4().hex}_{secure_filename(archivo.filename)}"
    ruta_entrada = os.path.join(UPLOAD_FOLDER, nombre_seguro)
    archivo.save(ruta_entrada)

    # Procesar
    ruta_resultado, error = procesar_con_gemini(ruta_entrada, accion)

    # Limpiar entrada
    try:
        os.remove(ruta_entrada)
    except:
        pass

    if error:
        return jsonify({"status": "error", "msg": error})

    # Devolver preview en base64 + ID para descarga
    resultado_id = os.path.basename(ruta_resultado)
    try:
        img_preview = Image.open(ruta_resultado)
        img_preview.thumbnail((800, 800))
        buf = io.BytesIO()
        img_preview.convert("RGB").save(buf, format="JPEG", quality=85)
        preview_b64 = base64.b64encode(buf.getvalue()).decode()
    except:
        preview_b64 = ""

    return jsonify({
        "status": "ok",
        "preview": preview_b64,
        "resultado_id": resultado_id
    })


@app.route("/descargar/<resultado_id>")
def descargar(resultado_id):
    # Validar que el ID no contenga rutas maliciosas
    if ".." in resultado_id or "/" in resultado_id or "\\" in resultado_id:
        return "Solicitud inválida.", 400

    ruta = os.path.join(OUTPUT_FOLDER, resultado_id)
    if not os.path.exists(ruta):
        return "Archivo no encontrado o expirado.", 404

    return send_file(
        ruta,
        as_attachment=True,
        download_name="nahual_studio_restauracion.jpg"
    )


@app.route("/health")
def health():
    return jsonify({"status": "ok", "servicio": "Nahual Studio"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)