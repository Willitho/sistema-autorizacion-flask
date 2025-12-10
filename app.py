import os
from flask import Flask, render_template, request, redirect, url_for, flash, Response
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from io import BytesIO

# --- ReportLab Imports ---
from reportlab.lib.pagesizes import letter, landscape
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle

# 1. INICIALIZAR APP
app = Flask(__name__)

# 2. CONFIGURACIÓN DE BASE DE DATOS (Detecta si es Render o PC Local)
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # Corrección para Render (postgres:// -> postgresql://)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
else:
    # Configuración Local (SQLite)
    basedir = os.path.abspath(os.path.dirname(__file__))
    database_url = 'sqlite:///' + os.path.join(basedir, 'solicitudes.db')

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or 'CLAVE_SECRETA_SUPER_SEGURA'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 3. INICIALIZAR DB (ESTA ES LA ÚNICA VEZ QUE DEBE APARECER)
db = SQLAlchemy(app)

# 4. INICIALIZAR LOGIN MANAGER
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = "Por favor, inicie sesión para acceder a esta página."

# --- MODELOS ---
class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    rol = db.Column(db.String(80), nullable=False) 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash: return False
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))

class SolicitudDB(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    solicitante = db.Column(db.String(100), nullable=False)
    fecha_inicio_str = db.Column(db.String(10), nullable=False)
    fecha_fin_str = db.Column(db.String(10), nullable=False)
    direccion = db.Column(db.String(200))
    comisaria_cercana = db.Column(db.String(100))
    contacto = db.Column(db.String(50))
    servicio = db.Column(db.String(200), nullable=False) 
    estado = db.Column(db.String(15), default="PENDIENTE") 
    autorizador = db.Column(db.String(80), nullable=True) 

    def get_fecha_inicio(self):
        try:
            return datetime.strptime(self.fecha_inicio_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        except:
            return self.fecha_inicio_str

    def get_fecha_fin(self):
        try:
            return datetime.strptime(self.fecha_fin_str, '%Y-%m-%d').strftime('%d/%m/%Y')
        except:
            return self.fecha_fin_str

# --- CREACIÓN DE TABLAS Y ADMIN INICIAL ---
with app.app_context():
    db.create_all()
    # Crear admin por defecto si no existe
    if not Usuario.query.filter_by(username='victor_admin').first():
        admin = Usuario(username='victor_admin', rol='Administrador')
        admin.set_password('admin123') 
        db.session.add(admin)
        db.session.commit()
    
    # Crear guardia por defecto
    if not Usuario.query.filter_by(username='GUARDIA').first():
        guardia = Usuario(username='GUARDIA', rol='Guardia')
        guardia.set_password('guardia123') 
        db.session.add(guardia)
        db.session.commit()

# --- PERMISOS ---
ROLES = {
    "Administrador": ["ver_panel", "generar_pdf", "gestionar_solicitud", "gestionar_usuarios"],
    "Guardia":       ["ver_panel", "generar_pdf"], 
    "Ventas":        ["ver_informe"],
    "Editor":        ["editar_producto"]
}

def tiene_permiso(permiso_requerido):
    if not current_user.is_authenticated:
        return False
    return permiso_requerido in ROLES.get(current_user.rol, [])

def gestionar_solicitud_db(usuario_autorizador, solicitud_id, nueva_estado):
    if not tiene_permiso("gestionar_solicitud"):
        return False
    solicitud = SolicitudDB.query.get(solicitud_id)
    if solicitud:
        solicitud.estado = nueva_estado
        solicitud.autorizador = usuario_autorizador
        db.session.commit()
        return True
    return False

# --- GENERADOR PDF ---
def generar_pdf_historial(lista_solicitudes=None, titulo_reporte="Historial General"):
    if lista_solicitudes is None:
        solicitudes = SolicitudDB.query.all()
    else:
        solicitudes = lista_solicitudes
    
    data = [['ID', 'Solicitante', 'Servicio', 'Período', 'Dirección', 'Estado', 'Autorizador', 'Contacto']]
    
    for sol in solicitudes:
        periodo = f"{sol.get_fecha_inicio()} - {sol.get_fecha_fin()}"
        direccion_completa = f"{sol.direccion}\n(Com.: {sol.comisaria_cercana})"
        autorizador_str = sol.autorizador if sol.autorizador else 'N/A'
        data.append([
            str(sol.id), sol.solicitante, sol.servicio, periodo,
            direccion_completa, sol.estado,
            autorizador_str, sol.contacto
        ])

    buffer = BytesIO() 
    p = canvas.Canvas(buffer, pagesize=landscape(letter))
    width, height = landscape(letter)

    p.setFont("Helvetica-Bold", 16)
    p.drawString(30, height - 30, titulo_reporte)
    
    p.setFont("Helvetica", 10)
    usuario_actual = current_user.username if current_user.is_authenticated else "Sistema"
    p.drawString(30, height - 50, f"Generado por: {usuario_actual} | {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    p.drawString(30, height - 65, f"Total registros: {len(solicitudes)}")

    col_widths = [20, 120, 120, 100, 170, 60, 100, 40] 
    table = Table(data, colWidths=col_widths)
    
    style = TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d6efd')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), 
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ])

    for i in range(1, len(data)):
        estado = data[i][5] 
        color = colors.white
        if estado == "APROBADA": color = colors.lightgreen
        elif estado == "RECHAZADA": color = colors.lightcoral
        elif estado == "PENDIENTE": color = colors.yellow
        style.add('BACKGROUND', (5, i), (5, i), color)
    
    table.setStyle(style)
    # Manejo básico de desbordamiento si la tabla es muy larga
    table.wrapOn(p, width, height)
    table.drawOn(p, 30, height - 100 - (len(data)*20))
    
    p.showPage()
    p.save()
    buffer.seek(0)
    return buffer

# --- RUTAS ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('panel_admin'))
    if request.method == 'POST':
        user = Usuario.query.filter_by(username=request.form.get('username')).first()
        if user and user.check_password(request.form.get('password')):
            login_user(user)
            return redirect(url_for('panel_admin'))
        flash('Credenciales inválidas.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/', methods=['GET', 'POST'])
def formulario_solicitud():
    # Permite acceso anónimo para crear solicitudes, pero si está logueado muestra menú
    if request.method == 'POST':
        d = request.form
        nueva = SolicitudDB(
            solicitante=d['solicitante'], fecha_inicio_str=d['inicio'],
            fecha_fin_str=d['fin'], direccion=d['direccion'],
            comisaria_cercana=d['comisaria'], contacto=d['contacto'],
            servicio=d['servicio']
        )
        db.session.add(nueva)
        db.session.commit()
        return redirect(url_for('confirmacion', id=nueva.id))
    return render_template('solicitud.html', current_user=current_user)

@app.route('/confirmacion/<int:id>')
def confirmacion(id):
    sol = SolicitudDB.query.get_or_404(id) 
    return render_template('confirmacion.html', solicitud=sol, current_user=current_user)

@app.route('/admin')
@login_required
def panel_admin():
    if not tiene_permiso("ver_panel"): return "Acceso Denegado", 403
    pendientes = SolicitudDB.query.filter_by(estado="PENDIENTE").all()
    return render_template('administrador.html', solicitudes=pendientes, current_user=current_user)

@app.route('/gestionar_autorizacion', methods=['POST'])
@login_required
def gestionar():
    gestionar_solicitud_db(current_user.username, request.form['solicitud_id'], request.form['accion'])
    return redirect(url_for('panel_admin'))

@app.route('/solicitudes')
def lista_general_solicitudes():
    modo = request.args.get('modo', 'hoy')
    hoy_str = datetime.now().strftime('%Y-%m-%d')
    
    if modo == 'hoy':
        # Muestra solo las vigentes HOY (Inicio <= Hoy <= Fin)
        solicitudes = SolicitudDB.query.filter(
            SolicitudDB.fecha_inicio_str <= hoy_str,
            SolicitudDB.fecha_fin_str >= hoy_str
        ).all()
        titulo = "Vigentes HOY"
    else:
        solicitudes = SolicitudDB.query.all()
        titulo = "Historial Completo"

    return render_template('principal.html', solicitudes=solicitudes, current_user=current_user, modo=modo, titulo=titulo)

@app.route('/gestionar_usuarios', methods=['GET', 'POST'])
@login_required
def gestionar_usuarios():
    if not tiene_permiso("gestionar_usuarios"): return "Acceso Denegado", 403
    if request.method == 'POST':
        if not Usuario.query.filter_by(username=request.form.get('username')).first():
            u = Usuario(username=request.form.get('username'), rol=request.form.get('rol'))
            u.set_password(request.form.get('password'))
            db.session.add(u)
            db.session.commit()
            flash('Usuario creado.', 'success')
        else:
            flash('Usuario ya existe.', 'error')
    return render_template('gestionar_usuarios.html', usuarios=Usuario.query.all(), roles=list(ROLES.keys()), current_user=current_user)

@app.route('/eliminar_solicitud/<int:id>', methods=['POST'])
@login_required
def eliminar_solicitud(id):
    if tiene_permiso("gestionar_solicitud"):
        sol = SolicitudDB.query.get(id)
        if sol:
            db.session.delete(sol)
            db.session.commit()
            flash('Eliminada.', 'success')
    return redirect(url_for('lista_general_solicitudes'))

# --- RUTAS DE PDF ---
@app.route('/descargar_historial_pdf')
@login_required
def descargar_historial_pdf():
    if not tiene_permiso("generar_pdf"):
        return redirect(url_for('panel_admin'))
    pdf_buffer = generar_pdf_historial(titulo_reporte="Historial Completo")
    return Response(pdf_buffer, mimetype='application/pdf',
                    headers={'Content-Disposition': 'attachment; filename="Historial_Completo.pdf"'})

@app.route('/descargar_pdf_hoy')
@login_required
def descargar_pdf_hoy():
    if not tiene_permiso("generar_pdf"):
        flash("No tienes permiso", "error")
        return redirect(url_for('panel_admin'))

    hoy_str = datetime.now().strftime('%Y-%m-%d')
    fecha_bonita = datetime.now().strftime('%d/%m/%Y')

    solicitudes_hoy = SolicitudDB.query.filter(
        SolicitudDB.fecha_inicio_str <= hoy_str,
        SolicitudDB.fecha_fin_str >= hoy_str
    ).all()
    
    pdf_buffer = generar_pdf_historial(lista_solicitudes=solicitudes_hoy, titulo_reporte=f"Bitácora Diaria - {fecha_bonita}")
    return Response(pdf_buffer, mimetype='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="Reporte_Diario_{hoy_str}.pdf"'})

if __name__ == '__main__':
    app.run(debug=True)