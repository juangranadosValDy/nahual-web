"""
auth.py — Sistema de autenticación y tokens de Nahual Studio
"""

import os
import sqlite3
from datetime import datetime
from functools import wraps
from flask import Blueprint, request, jsonify, session, render_template_string

auth_bp = Blueprint('auth', __name__)

DB_PATH = "/tmp/nahual_users.db"

# ==================== BASE DE DATOS ====================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER,
            accion TEXT,
            tokens_usados INTEGER DEFAULT 1,
            fecha TEXT,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        )
    ''')

    # Crear admin por defecto si no existe
    admin_email = os.environ.get("ADMIN_EMAIL", "admin@nahualstudio.com")
    admin_pass = os.environ.get("ADMIN_PASS", "nahual2026")
    
    cursor.execute("SELECT id FROM usuarios WHERE email = ?", (admin_email,))
    if not cursor.fetchone():
        cursor.execute('''
            INSERT INTO usuarios (email, password, nombre, tokens, es_admin, fecha_registro)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (admin_email, admin_pass, "Admin", 9999, 1, datetime.now().isoformat()))
    
    conn.commit()
    conn.close()

# ==================== HELPERS ====================

def login_requerido(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if 'usuario_id' not in session:
            return jsonify({"status": "error", "msg": "Sesión requerida.", "redirect": "/login"}), 401
        return f(*args, **kwargs)
    return decorador

def admin_requerido(f):
    @wraps(f)
    def decorador(*args, **kwargs):
        if 'usuario_id' not in session:
            return jsonify({"status": "error", "msg": "No autorizado."}), 401
        conn = get_db()
        usuario = conn.execute("SELECT es_admin FROM usuarios WHERE id = ?", (session['usuario_id'],)).fetchone()
        conn.close()
        if not usuario or not usuario['es_admin']:
            return jsonify({"status": "error", "msg": "Acceso restringido."}), 403
        return f(*args, **kwargs)
    return decorador

def get_usuario_actual():
    if 'usuario_id' not in session:
        return None
    conn = get_db()
    usuario = conn.execute(
        "SELECT id, email, nombre, tokens, es_admin FROM usuarios WHERE id = ?",
        (session['usuario_id'],)
    ).fetchone()
    conn.close()
    return dict(usuario) if usuario else None

def tiene_tokens():
    usuario = get_usuario_actual()
    if not usuario:
        return False
    return usuario['tokens'] > 0

def descontar_token(usuario_id, accion="restaurar"):
    conn = get_db()
    conn.execute("UPDATE usuarios SET tokens = tokens - 1 WHERE id = ? AND tokens > 0", (usuario_id,))
    conn.execute('''
        INSERT INTO historial (usuario_id, accion, tokens_usados, fecha)
        VALUES (?, ?, 1, ?)
    ''', (usuario_id, accion, datetime.now().isoformat()))
    conn.commit()
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
        conn.execute('''
            INSERT INTO usuarios (email, password, nombre, tokens, fecha_registro)
            VALUES (?, ?, ?, 0, ?)
        ''', (email, password, nombre, datetime.now().isoformat()))
        conn.commit()
        
        usuario = conn.execute("SELECT id, nombre, tokens FROM usuarios WHERE email = ?", (email,)).fetchone()
        conn.close()
        
        session['usuario_id'] = usuario['id']
        session['usuario_nombre'] = usuario['nombre'] or email.split('@')[0]
        
        return jsonify({
            "status": "ok",
            "msg": f"Bienvenido, {session['usuario_nombre']}. Tu cuenta fue creada.",
            "tokens": usuario['tokens']
        })
    except sqlite3.IntegrityError:
        return jsonify({"status": "error", "msg": "Este email ya está registrado."})
    except Exception as e:
        return jsonify({"status": "error", "msg": str(e)})

@auth_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    password = data.get('password', '').strip()

    conn = get_db()
    usuario = conn.execute(
        "SELECT * FROM usuarios WHERE email = ? AND password = ?", (email, password)
    ).fetchone()
    
    if not usuario:
        conn.close()
        return jsonify({"status": "error", "msg": "Email o contraseña incorrectos."})
    
    conn.execute("UPDATE usuarios SET ultimo_acceso = ? WHERE id = ?",
                 (datetime.now().isoformat(), usuario['id']))
    conn.commit()
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
    usuarios = conn.execute(
        "SELECT id, email, nombre, tokens, fecha_registro, ultimo_acceso FROM usuarios ORDER BY fecha_registro DESC"
    ).fetchall()
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
    conn.execute("UPDATE usuarios SET tokens = tokens + ? WHERE id = ?", (tokens, usuario_id))
    conn.commit()
    
    usuario = conn.execute("SELECT email, tokens FROM usuarios WHERE id = ?", (usuario_id,)).fetchone()
    conn.close()
    
    return jsonify({
        "status": "ok",
        "msg": f"Se asignaron {tokens} tokens a {usuario['email']}. Total: {usuario['tokens']}"
    })
