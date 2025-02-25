import psycopg2

def test_connection():
    try:
        conn = psycopg2.connect(
            host='179.57.170.61',
            port='24301',
            database='bdorcagest',
            user='orca',
            password='estadoscam.'
        )
        cursor = conn.cursor()
        cursor.execute('SELECT 1')
        print("Conexión exitosa a la base de datos.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error al conectar con la base de datos: {e}")

if __name__ == '__main__':
    test_connection()  # Primero prueba la conexión a la base de datos
    from app import create_app  # Importa la aplicación después de probar la conexión

    app = create_app()
    app.run(debug=True)  # Activa el modo debug y ejecuta la aplicación
