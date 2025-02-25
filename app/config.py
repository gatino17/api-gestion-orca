import os



class Config:

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')  # Carpeta para almacenar archivos
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf'}  # Tipos de archivo permitidos
    
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', 'postgresql://orca:estadoscam.@179.57.170.61:24301/bdorcagest')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY', 'your_secret_key')
