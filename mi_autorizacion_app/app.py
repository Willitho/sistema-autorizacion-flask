from flask import Flask, render_template, request, redirect, url_for, flash
from datetime import datetime
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SECRET_KEY'] = 'SUPER_SECRETO_Y_COMPLEJO_DEBES_CAMBIAR_ESTO' # Clave de seguridad
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///solicitudes.db' # Base de datos local
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 
login_manager.login_message = "Por favor, inicie sesión para acceder a esta página."

# --- MODELO DE USUARIO ---
class Usuario(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128))
    rol = db.Column(db.String(80), nullable=False) 

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    return Usuario.query.get(int(user_id))


# --- MODELO DE SOLICITUDES PERSISTENTES (SolicitudDB) ---
class SolicitudDB(db.Model):
    # ID real de la base de datos (clave primaria)
    id = db.Column(db.Integer, primary_key=True)
    
    # Datos de la solicitud
    solicitante = db.Column(db.String(100), nullable=False)
    fecha_inicio_str = db.Column(db.String(10), nullable=False) # Formato YYYY-MM-DD
    fecha_fin_str = db.Column(db.String(10), nullable=False)
    direccion = db.Column(db.String(200))
    comisaria_cercana = db.Column(db.String(100))
    contacto = db.Column(db.String(50))
    
    # Datos de gestión
    estado = db.Column(db.String(15), default="PENDIENTE") 
    autorizador = db.Column(db.String(80), nullable=True) 

    # Métodos de utilidad para el formato de fecha (DD/MM/YYYY)
    def get_fecha_inicio(self):
        # Usamos datetime para parsear la cadena ISO (YYYY-MM-DD) y formatear
        return datetime.strptime(self.fecha_inicio_str, '%Y-%m-%d').strftime('%d/%m/%Y')

    def get_fecha_fin(self):
        return datetime.strptime(self.fecha_fin_str, '%Y-%m-%d').strftime('%d/%m/%Y')

    
# --- Creación de Base de Datos y Usuarios Iniciales ---
with app.app_context():
    db.create_all() # Esto creará las tablas Usuario y SolicitudDB

    if not Usuario.query.filter_by(username='victor_admin').first():
        admin = Usuario(username='victor_admin', rol='Administrador')
        admin.set_password('admin123') 
        db.session.add(admin)
        db.session.commit()
        print("✅ Usuario Administrador inicial creado: victor_admin / admin123")


# --- LÓGICA DE AUTORIZACIÓN ---
ROLES = {
    "Administrador": ["autorizar_solicitud", "gestionar_usuarios"],
    "Ventas": ["ver_informe"],
    "Editor": ["editar_producto"]
}

def tiene_permiso(permiso_requerido):
    """Verifica si el usuario logueado (current_user) tiene un permiso específico."""
    if not current_user.is_authenticated:
        return False
    rol_del_usuario = current_user.rol
    permisos_del_rol = ROLES.get(rol_del_usuario, [])
    return permiso_requerido in permisos_del_rol

# Nota: Las funciones de gestión ya no usan la lista en memoria, sino que actualizan SolicitudDB.

# --- RUTAS DE FLASK (CONTROLADOR) ---

@app.route('/login', methods=['GET', 'POST'])
# ... (ruta de login omitida por simplicidad, se mantiene igual) ...
def login():
    if current_user.is_authenticated:
        return redirect(url_for('panel_admin'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user = Usuario.query.filter_by(username=username).first()
        
        if user is None or not user.check_password(password):
            flash('Usuario o contraseña inválidos.', 'error')
            return redirect(url_for('login'))
        
        login_user(user)
        return redirect(url_for('panel_admin'))
        
    return render_template('login.html') 

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


# Ruta 1: Formulario para el Solicitante (Persona X)
@app.route('/', methods=['GET', 'POST'])
def formulario_solicitud():
    if request.method == 'POST':
        datos = request.form
        
        # Guardamos en la Base de Datos (DB)
        nueva_solicitud_db = SolicitudDB(
            solicitante=datos['solicitante'], 
            fecha_inicio_str=datos['inicio'],
            fecha_fin_str=datos['fin'],
            direccion=datos['direccion'],
            comisaria_cercana=datos['comisaria'],
            contacto=datos['contacto']
        )
        
        db.session.add(nueva_solicitud_db)
        db.session.commit()
        
        # Redirigimos al ID de la DB
        return redirect(url_for('confirmacion', id=nueva_solicitud_db.id))
    
    return render_template('solicitud.html', current_user=current_user)

# Ruta 2: Pantalla de Espera/Confirmación
@app.route('/confirmacion/<int:id>')
def confirmacion(id):
    # Consultamos la DB por el ID
    solicitud = SolicitudDB.query.get_or_404(id) 
    return render_template('confirmacion.html', solicitud=solicitud, id=id, current_user=current_user)

# Ruta 3: Panel del Administrador (Muestra PENDIENTES)
@app.route('/admin')
@login_required
def panel_admin():
    
    if not tiene_permiso("autorizar_solicitud"):
         return "Acceso Denegado. No tienes permiso de Administrador.", 403

    # CONSULTA: Solo solicitudes PENDIENTES de la DB
    solicitudes = SolicitudDB.query.filter_by(estado="PENDIENTE").all()
    
    # NOTA: 'solicitudes' ahora es una lista de objetos SolicitudDB, no diccionarios.
    return render_template('administrador.html', solicitudes=solicitudes, current_user=current_user)

# Ruta 4: Manejar la Aprobación/Rechazo
@app.route('/gestionar_autorizacion', methods=['POST'])
@login_required
def gestionar():
    autorizador_user = current_user.username 
    solicitud_id = request.form['solicitud_id'] # El ID es una cadena al venir del formulario
    nueva_accion = request.form['accion'] 
    
    solicitud = SolicitudDB.query.get(solicitud_id)
    
    if solicitud and tiene_permiso("autorizar_solicitud"):
        solicitud.estado = nueva_accion
        solicitud.autorizador = autorizador_user
        db.session.commit()
    else:
        flash('Error al gestionar la solicitud o no tienes permisos.', 'error')
    
    return redirect(url_for('panel_admin'))

# Ruta 5: Pantalla principal que muestra todas las solicitudes con su estado.
@app.route('/solicitudes')
def lista_general_solicitudes():
    # Consultamos TODAS las solicitudes de la DB
    solicitudes = SolicitudDB.query.all() 
    return render_template('principal.html', solicitudes=solicitudes, current_user=current_user)

# Ruta 6: Panel de Gestión de Usuarios
@app.route('/gestionar_usuarios', methods=['GET', 'POST'])
@login_required
def gestionar_usuarios():
    # ... (código de gestión de usuarios omitido, se mantiene igual) ...
    if not tiene_permiso("gestionar_usuarios"):
         return "Acceso Denegado. No tienes permiso para gestionar usuarios.", 403

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        rol = request.form.get('rol')
        
        if Usuario.query.filter_by(username=username).first():
            flash(f'❌ Error: El usuario "{username}" ya existe.', 'error')
        else:
            nuevo_usuario = Usuario(username=username, rol=rol)
            nuevo_usuario.set_password(password)
            
            db.session.add(nuevo_usuario)
            db.session.commit()
            flash(f'✅ Usuario {username} creado exitosamente con el rol: {rol}.', 'success')
            return redirect(url_for('gestionar_usuarios'))
            
    usuarios_existentes = Usuario.query.all()
    roles_disponibles = sorted(ROLES.keys()) 
    
    return render_template('gestionar_usuarios.html', 
                           usuarios=usuarios_existentes, 
                           roles=roles_disponibles,
                           current_user=current_user)

# Ruta 7: Eliminar Solicitud
@app.route('/eliminar_solicitud/<int:id>', methods=['POST'])
@login_required
def eliminar_solicitud(id):
    # 1. Verificar permiso de Administrador
    if not tiene_permiso("autorizar_solicitud"):
        flash("🚫 No tienes permiso para eliminar solicitudes.", 'error')
        return redirect(url_for('lista_general_solicitudes'))

    # 2. Buscar y eliminar la solicitud por su ID en la DB
    solicitud = SolicitudDB.query.get(id)

    if solicitud:
        solicitante_nombre = solicitud.solicitante
        db.session.delete(solicitud)
        db.session.commit()
        flash(f"🗑️ Solicitud ID {id} de {solicitante_nombre} eliminada correctamente.", 'success')
    else:
        flash("❌ Error: Solicitud no encontrada.", 'error')

    # Redirigir de nuevo al resumen general
    return redirect(url_for('lista_general_solicitudes'))


if __name__ == '__main__':
    app.run(debug=True)