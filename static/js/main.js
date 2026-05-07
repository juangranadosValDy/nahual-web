/* =============================================
   NAHUAL STUDIO — main.js
   ============================================= */

// ==================== PARTÍCULAS REACTIVAS ====================
(function () {
    const canvas = document.getElementById('particulas');
    const ctx = canvas.getContext('2d');
    let W, H, particulas;
    let mouse = { x: -9999, y: -9999 };
    const RADIO_MOUSE = 150;
    const NUM_PARTICULAS = 140;
    const DIST_LINEA = 130;

    function resize() {
        W = canvas.width = window.innerWidth;
        H = canvas.height = window.innerHeight;
    }

    function crearParticulas() {
        particulas = [];
        for (let i = 0; i < NUM_PARTICULAS; i++) {
            particulas.push({
                x: Math.random() * W,
                y: Math.random() * H,
                vx: (Math.random() - 0.5) * 0.3,
                vy: (Math.random() - 0.5) * 0.3,
                r: Math.random() * 1.5 + 0.5,
                brillo: 0, // brillo actual interpolado
            });
        }
    }

    function distancia(a, b) {
        return Math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2);
    }

    // Easing suave: curva cúbica
    function easeOut(t) {
        return 1 - Math.pow(1 - t, 3);
    }

    function dibujar() {
        ctx.clearRect(0, 0, W, H);

        particulas.forEach(p => {
            // Movimiento
            p.x += p.vx;
            p.y += p.vy;
            if (p.x < 0 || p.x > W) p.vx *= -1;
            if (p.y < 0 || p.y > H) p.vy *= -1;

            // Calcular brillo objetivo según distancia al mouse
            const dm = distancia(p, mouse);
            const influencia = dm < RADIO_MOUSE
                ? easeOut(1 - dm / RADIO_MOUSE)
                : 0;

            // Interpolar brillo actual hacia el objetivo (suave)
            p.brillo += (influencia - p.brillo) * 0.06;

            // Alpha y radio basados en brillo interpolado
            const alpha = 0.1 + p.brillo * 0.55;
            const radio = p.r + p.brillo * 1.4;

            // Glow suave proporcional al brillo
            if (p.brillo > 0.05) {
                ctx.shadowBlur = p.brillo * 10;
                ctx.shadowColor = `rgba(63,224,208,${p.brillo * 0.6})`;
            } else {
                ctx.shadowBlur = 0;
            }

            // Color: mezcla entre azul (lejos) y cyan (cerca)
            const r = Math.round(0 + p.brillo * 63);
            const g = Math.round(128 + p.brillo * 96);
            const b2 = Math.round(255 - p.brillo * 25);
            ctx.fillStyle = `rgba(${r},${g},${b2},${alpha})`;

            ctx.beginPath();
            ctx.arc(p.x, p.y, radio, 0, Math.PI * 2);
            ctx.fill();
        });

        ctx.shadowBlur = 0;

        // Líneas entre partículas cercanas
        for (let i = 0; i < particulas.length; i++) {
            for (let j = i + 1; j < particulas.length; j++) {
                const d = distancia(particulas[i], particulas[j]);
                if (d < DIST_LINEA) {
                    const brilloMax = Math.max(particulas[i].brillo, particulas[j].brillo);
                    const alphaBase = 0.03 * (1 - d / DIST_LINEA);
                    const alphaBrillo = brilloMax * 0.15 * (1 - d / DIST_LINEA);
                    const alpha = alphaBase + alphaBrillo;

                    const r = Math.round(0 + brilloMax * 63);
                    const g = Math.round(128 + brilloMax * 96);
                    const b2 = 255;

                    ctx.beginPath();
                    ctx.moveTo(particulas[i].x, particulas[i].y);
                    ctx.lineTo(particulas[j].x, particulas[j].y);
                    ctx.strokeStyle = `rgba(${r},${g},${b2},${alpha})`;
                    ctx.lineWidth = 0.5;
                    ctx.stroke();
                }
            }
        }

        requestAnimationFrame(dibujar);
    }

    window.addEventListener('resize', () => { resize(); crearParticulas(); });
    window.addEventListener('mousemove', e => { mouse.x = e.clientX; mouse.y = e.clientY; });
    window.addEventListener('mouseleave', () => { mouse.x = -9999; mouse.y = -9999; });

    resize();
    crearParticulas();
    dibujar();
})();

// ==================== INICIALIZACIÓN AL CARGAR ====================
window.addEventListener('load', async () => {
    // Lottie shutter
    try {
        const LottiePlayer = window.DotLottie || (window.dotLottieWeb && window.dotLottieWeb.DotLottie);
        if (LottiePlayer) {
            new LottiePlayer({
                autoplay: true,
                loop: true,
                canvas: document.getElementById('lottieShutter'),
                src: '/static/animations/Cam_Shutter.lottie',
            });
        } else {
            console.log('DotLottie no encontrado en window');
        }
    } catch (e) { console.log('Lottie error:', e); }

    // Verificar sesión
    try {
        const res = await fetch('/sesion');
        const data = await res.json();
        if (data.logueado) actualizarNavUsuario(data);
    } catch (e) {}
});

// ==================== UPLOAD Y PROCESAMIENTO ====================
let archivoSeleccionado = null;
let accionSeleccionada = 'restaurar';
let resultadoId = null;

const zona = document.getElementById('uploadZone');
zona.addEventListener('dragover', e => { e.preventDefault(); zona.classList.add('drag-over'); });
zona.addEventListener('dragleave', () => zona.classList.remove('drag-over'));
zona.addEventListener('drop', e => {
    e.preventDefault();
    zona.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file) manejarArchivo(file);
});

document.getElementById('fileInput').addEventListener('change', e => {
    if (e.target.files[0]) manejarArchivo(e.target.files[0]);
});

function manejarArchivo(file) {
    const tipos = ['image/jpeg', 'image/png', 'image/webp'];
    if (!tipos.includes(file.type)) {
        mostrarError('// Formato no soportado. Usa JPG, PNG o WEBP.');
        return;
    }
    if (file.size > 20 * 1024 * 1024) {
        mostrarError('// La imagen supera el límite de 20MB.');
        return;
    }
    archivoSeleccionado = file;
    ocultarError();
    ocultarResultado();
    const reader = new FileReader();
    reader.onload = e => {
        document.getElementById('previewImg').src = e.target.result;
        document.getElementById('previewNombre').textContent = '// ' + file.name;
        document.getElementById('previewWrap').style.display = 'block';
        document.getElementById('acciones').style.display = 'grid';
        document.getElementById('btnProcesar').style.display = 'block';
    };
    reader.readAsDataURL(file);
}

function seleccionarAccion(btn) {
    document.querySelectorAll('.btn-accion').forEach(b => b.classList.remove('activo'));
    btn.classList.add('activo');
    accionSeleccionada = btn.dataset.accion;
}

async function procesar() {
    if (!archivoSeleccionado) return;
    const btn = document.getElementById('btnProcesar');
    btn.disabled = true;
    ocultarError();
    ocultarResultado();
    document.getElementById('progressWrap').style.display = 'block';
    const formData = new FormData();
    formData.append('foto', archivoSeleccionado);
    formData.append('accion', accionSeleccionada);
    try {
        const res = await fetch('/procesar', { method: 'POST', body: formData });
        const data = await res.json();
        document.getElementById('progressWrap').style.display = 'none';
        if (data.status === 'error') {
            mostrarError('// ' + data.msg);
        } else {
            resultadoId = data.resultado_id;
            document.getElementById('resultadoImg').src = `data:image/jpeg;base64,${data.preview}`;
            document.getElementById('btnDescargar').href = `/descargar/${resultadoId}`;
            document.getElementById('resultadoWrap').style.display = 'block';
            document.getElementById('resultadoWrap').scrollIntoView({ behavior: 'smooth' });
            // Actualizar tokens en tiempo real
            const sesRes = await fetch('/sesion');
            const sesData = await sesRes.json();
            if (sesData.logueado) document.getElementById('navTokens').textContent = `◆ ${sesData.tokens} tokens`;
        }
    } catch (e) {
        document.getElementById('progressWrap').style.display = 'none';
        mostrarError('// Error de conexión. Intenta de nuevo.');
    }
    btn.disabled = false;
}

function resetear() {
    archivoSeleccionado = null;
    resultadoId = null;
    document.getElementById('fileInput').value = '';
    document.getElementById('previewWrap').style.display = 'none';
    document.getElementById('acciones').style.display = 'none';
    document.getElementById('btnProcesar').style.display = 'none';
    ocultarResultado();
    ocultarError();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

function mostrarError(msg) {
    const el = document.getElementById('msgError');
    el.textContent = msg;
    el.style.display = 'block';
}

function ocultarError() { document.getElementById('msgError').style.display = 'none'; }
function ocultarResultado() { document.getElementById('resultadoWrap').style.display = 'none'; }

// ==================== CARRUSEL ====================
let slideActual = 0;
const totalSlides = 4;
let autoCarrusel;

function irASlide(n) {
    const slides = document.querySelectorAll('.carrusel-slide');
    const dots = document.querySelectorAll('.carrusel-dot');
    slides[slideActual].classList.remove('activo');
    dots[slideActual].classList.remove('activo');
    slideActual = (n + totalSlides) % totalSlides;
    slides[slideActual].classList.add('activo');
    dots[slideActual].classList.add('activo');
}

function moverCarrusel(dir) {
    clearInterval(autoCarrusel);
    irASlide(slideActual + dir);
    iniciarAutoCarrusel();
}

function iniciarAutoCarrusel() {
    autoCarrusel = setInterval(() => irASlide(slideActual + 1), 5000);
}

document.querySelectorAll('.carrusel-slide')[0].classList.add('activo');
iniciarAutoCarrusel();

// ==================== SCROLL REVEAL ====================
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            const delay = parseInt(entry.target.dataset.delay || 0);
            setTimeout(() => entry.target.classList.add('visible'), delay);
            observer.unobserve(entry.target);
        }
    });
}, { threshold: 0.2 });

document.querySelectorAll('.prox-item').forEach(el => observer.observe(el));

// ==================== AUTH ====================
function abrirModal() { document.getElementById('modalAuth').style.display = 'flex'; }

function cerrarModal() {
    document.getElementById('modalAuth').style.display = 'none';
    document.getElementById('authMsg').textContent = '';
}

function cambiarTab(tab) {
    const esLogin = tab === 'login';
    document.getElementById('formLogin').style.display = esLogin ? 'block' : 'none';
    document.getElementById('formRegistro').style.display = esLogin ? 'none' : 'block';
    document.getElementById('tabLogin').style.borderBottomColor = esLogin ? 'var(--azul)' : 'transparent';
    document.getElementById('tabLogin').style.color = esLogin ? 'var(--azul)' : 'var(--blanco-muted)';
    document.getElementById('tabRegistro').style.borderBottomColor = esLogin ? 'transparent' : 'var(--azul)';
    document.getElementById('tabRegistro').style.color = esLogin ? 'var(--blanco-muted)' : 'var(--azul)';
    document.getElementById('authMsg').textContent = '';
}

function mostrarAuthMsg(msg, error = false) {
    const el = document.getElementById('authMsg');
    el.textContent = msg;
    el.style.color = error ? '#FF6B6B' : 'var(--cyan)';
}

function actualizarNavUsuario(datos) {
    document.getElementById('btnAbrirLogin').style.display = 'none';
    const navU = document.getElementById('navUsuario');
    navU.style.display = 'flex';
    document.getElementById('navTokens').textContent = `◆ ${datos.tokens} tokens`;
    if (datos.es_admin && !document.getElementById('btnAdmin')) {
        const btnAdmin = document.createElement('a');
        btnAdmin.id = 'btnAdmin';
        btnAdmin.href = '/admin';
        btnAdmin.textContent = 'ADMIN';
        btnAdmin.style.cssText = 'background:transparent;border:1px solid var(--cyan);color:var(--cyan);padding:0.4rem 0.8rem;font-family:Orbitron,monospace;font-size:0.55rem;letter-spacing:0.15em;text-decoration:none;';
        navU.insertBefore(btnAdmin, navU.firstChild);
    }
}

async function iniciarSesion() {
    const email = document.getElementById('loginEmail').value.trim();
    const pass = document.getElementById('loginPass').value.trim();
    if (!email || !pass) { mostrarAuthMsg('Completa todos los campos.', true); return; }
    const res = await fetch('/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: pass })
    });
    const data = await res.json();
    if (data.status === 'ok') {
        mostrarAuthMsg(data.msg);
        actualizarNavUsuario(data);
        setTimeout(cerrarModal, 1200);
    } else {
        mostrarAuthMsg(data.msg, true);
    }
}

async function registrarse() {
    const nombre = document.getElementById('regNombre').value.trim();
    const email = document.getElementById('regEmail').value.trim();
    const pass = document.getElementById('regPass').value.trim();
    if (!email || !pass) { mostrarAuthMsg('Email y contraseña son requeridos.', true); return; }
    const res = await fetch('/registro', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password: pass, nombre })
    });
    const data = await res.json();
    if (data.status === 'ok') {
        mostrarAuthMsg(data.msg);
        actualizarNavUsuario(data);
        setTimeout(cerrarModal, 1500);
    } else {
        mostrarAuthMsg(data.msg, true);
    }
}

async function cerrarSesion() {
    await fetch('/logout', { method: 'POST' });
    document.getElementById('navUsuario').style.display = 'none';
    document.getElementById('btnAbrirLogin').style.display = 'block';
}
