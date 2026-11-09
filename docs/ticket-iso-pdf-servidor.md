# PDF de Ticket ISO en el servidor

El PDF se genera en el backend. El frontend no necesita recompilarse para
corregir las dependencias del generador.

## Error de compatibilidad con Python 3.8

Si el registro muestra:

```text
TypeError: 'usedforsecurity' is an invalid keyword argument for openssl_md5()
```

comprobar la version instalada con el mismo Python que utiliza Gunicorn:

```bash
cd /home/orcagest/api-gestion-orca
./venv/bin/python -c "import sys, reportlab; print(sys.version); print(reportlab.Version); print(reportlab.__file__)"
```

Instalar la version fijada en `requirements.txt`, no una version sin especificar
ni paquetes en el Python global. ReportLab 4.3.1 no utiliza ese argumento en la
creacion del documento:

```bash
./venv/bin/python -m pip install --no-deps --force-reinstall "reportlab==4.3.1"
./venv/bin/python -m unittest discover -s tests -p test_ticket_iso_pdf.py -q
```

Las pruebas del PDF no inician Flask ni acceden a la base de datos. Si terminan
correctamente, reiniciar el servicio y probar nuevamente desde Ticket ISO:

```bash
sudo systemctl restart api-gestion-orca.service
sudo systemctl is-active api-gestion-orca.service
```

Si el problema persiste, consultar el nuevo traceback:

```bash
sudo journalctl -u api-gestion-orca.service -n 120 --no-pager
```

No modificar `hashlib`, OpenSSL ni los archivos de ReportLab manualmente.
