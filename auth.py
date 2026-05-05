"""
auth.py — Sistema de autenticación y tokens de Nahual Studio
Base de datos: PostgreSQL (persistente)
"""

import os
import psycopg2
import psycopg2.extras
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, session

auth_bp = Blueprint('auth', __name__)

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# ==================== BASE DE DATOS ====================

def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id SERIAL PRIMARY KEY,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            nombre TEXT,
            tokens INTEGER DEFAULT 0,
            es_admin INTEGER DEFAULT 0,
            fecha_registro TEXT,
            ultimo_acceso TEXT
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS historial (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER,
            accion TEXT,
            tokens_usados INTEGER DEFAULT 1,
            fecha TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        )
    ''')

    # Crear admin desde variables de entorno
    admin_email = os.environ.get("ADMIN_EMAIL", "")
    admin_pass = os.environ.get("ADMIN_PASS", "")

    if admin_email and admin_pass:
        cursor.execute("SELECT id FROM usuarios WHERE email = %s", (admin_email,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO usuarios (email, password, nombre, tokens, es_admin, fecha_registro)
                VALUES (%s, %s, %s, %s, %s, %s)
            ''', (admin_email, admin_pass, "Admin", 9999, 1, datetime.now().isoformat()))

    conn.commit()
    cursor.close()
    conn.close()

# ==================== HELPERS ====================

def admin_requerido(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if 'usuario_id' not in session:
            return jsonify({"status": "error", "msg": "No autorizado."}), 401
        conn = get_db()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute("SELECT es_admin FROM usuarios WHERE id = %s", (session['usuario_id'],))
        usuario = cursor.fetchone()
        cursor.close()
        conn.close()
        if not usuario or not usuario['es_admin']:
            return jsonify({"status": "error", "msg": "Acceso restringido."}), 403
        return f(*args, **kwargs)
    return decorador

def get_usuario_actual():
    if 'usuario_id' not in session:
        return None
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT id, email, nombre, tokens, es_admin FROM usuarios WHERE id = %s",
        (session['usuario_id'],)
    )
    usuario = cursor.fetchone()
    cursor.close()
    conn.close()
    return dict(usuario) if usuario else None

def tiene_tokens():
    usuario = get_usuario_actual()
    if not usuario:
        return False
    return usuario['tokens'] > 0

def descontar_token(usuario_id, accion="restaurar"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE usuarios SET tokens = tokens - 1 WHERE id = %s AND tokens > 0",
        (usuario_id,)
    )
    cursor.execute('''
        INSERT INTO historial (usuario_id, accion, tokens_usados, fecha)
        VALUES (%s, %s, 1, %s)
    ''', (usuario_id, accion, datetime.now().isoformat()))
    conn.commit()
    cursor.close()
    conn.close()

# ==================== RUTAS AUTH ====================

@auth_bp.route('/registro', methods=['POST'])
def registro():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()
    nombre = data.get('nombre', '').strip()

    if not email or not password:
        return jsonify({"status": "error", "msg": "Email y contraseña son requeridos."})
    if len(password) < 6:
        return jsonify({"status": "error", "msg": "La contraseña debe tener al menos 6 caracteres."})

    try:
        conn = get_db()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cursor.execute('''
            INSERT INTO usuarios (email, password, nombre, tokens, fecha_registro)
            VALUES (%s, %s, %s, 1, %s)
            RETURNING id, nombre, tokens
        ''', (email, password, nombre, datetime.now().isoformat()))
        usuario = cursor.fetchone()
        conn.commit()
        cursor.close()
        conn.close()

        session['usuario_id'] = usuario['id']
        session['usuario_nombre'] = usuario['nombre'] or email.split('@')[0]

        return jsonify({
            "status": "ok",
            "msg": f"Bienvenido, {session['usuario_nombre']}. Tu cuenta fue creada.",
            "tokens": usuario['tokens']
        })
    except psycopg2.errors.UniqueViolation:
        return jsonify({"status": "error", "msg": "Este email ya está registrado."})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT * FROM usuarios WHERE email = %s AND password = %s", (email, password)
    )
    usuario = cursor.fetchone()

    if not usuario:
        cursor.close()
        conn.close()
        return jsonify({"status": "error", "msg": "Email o contraseña incorrectos."})

    cursor.execute(
        "UPDATE usuarios SET ultimo_acceso = %s WHERE id = %s",
        (datetime.now().isoformat(), usuario['id'])
    )
    conn.commit()
    cursor.close()
    conn.close()

    session['usuario_id'] = usuario['id']
    session['usuario_nombre'] = usuario['nombre'] or email.split('@')[0]
    session['es_admin'] = bool(usuario['es_admin'])

    return jsonify({
        "status": "ok",
        "msg": f"Bienvenido de vuelta, {session['usuario_nombre']}.",
        "tokens": usuario['tokens'],
        "es_admin": bool(usuario['es_admin'])
    })

@auth_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({"status": "ok"})

@auth_bp.route('/sesion', methods=['GET'])
def sesion():
    usuario = get_usuario_actual()
    if not usuario:
        return jsonify({"logueado": False})
    return jsonify({"logueado": True, **usuario})

# ==================== RUTAS ADMIN ====================

@auth_bp.route('/admin/usuarios', methods=['GET'])
@admin_requerido
def listar_usuarios():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "SELECT id, email, nombre, tokens, es_admin, fecha_registro, ultimo_acceso FROM usuarios ORDER BY fecha_registro DESC"
    )
    usuarios = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({"status": "ok", "usuarios": [dict(u) for u in usuarios]})

@auth_bp.route('/admin/asignar_tokens', methods=['POST'])
@admin_requerido
def asignar_tokens():
    data = request.get_json()
    usuario_id = data.get('usuario_id')
    tokens = data.get('tokens', 0)

    if not usuario_id or tokens <= 0:
        return jsonify({"status": "error", "msg": "Datos inválidos."})

    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute(
        "UPDATE usuarios SET tokens = tokens + %s WHERE id = %s",
        (tokens, usuario_id)
    )
    conn.commit()
    cursor.execute("SELECT email, tokens FROM usuarios WHERE id = %s", (usuario_id,))
    usuario = cursor.fetchone()
    cursor.close()
    conn.close()

    return jsonify({
        "status": "ok",
        "msg": f"Se asignaron {tokens} tokens a {usuario['email']}. Total: {usuario['tokens']}"
    })

@auth_bp.route('/admin/historial', methods=['GET'])
@admin_requerido
def historial():
    conn = get_db()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute('''
        SELECT h.*, u.email
        FROM historial h
        LEFT JOIN usuarios u ON h.usuario_id = u.id
        ORDER BY h.fecha DESC
        LIMIT 50
    ''')
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    return jsonify({"status": "ok", "historial": [dict(i) for i in items]})
