import React, { useState, useEffect, useCallback } from 'react';
import DataTable from 'react-data-table-component';
import { cargarActas } from '../controllers/actasControllers';
import { agregarServicio, modificarServicio, borrarServicio } from '../controllers/servicios_adicionalesControllers';
import { cargarTodasRazonesSociales } from '../controllers/razonSocialControllers';

import ModalActividad from '../modales/ModalActividad';



function RegistrosDocumentos() {

    // Estados
    const [actividades, setActividades] = useState([]);

    const [serviciosAdicionales, setServiciosAdicionales] = useState([]);
    const [servicioEditar, setServicioEditar] = useState(null);
    const [razonesSociales, setRazonesSociales] = useState([]);

    // Campos del formulario
    const [razonSocialId, setRazonSocialId] = useState('');
    const [fechaInstalacion, setFechaInstalacion] = useState('');
    const [observaciones, setObservacion] = useState('');
    const [documento, setDocumento] = useState(null);    
    const [errorFechaInstalacion, setErrorFechaInstalacion] = useState(false);

    const [loading, setLoading] = useState(false);

    const [modalVisible, setModalVisible] = useState(false);  // Controla la visibilidad del modal
    const [actividadSeleccionada, setActividadSeleccionada] = useState(null);  // Almacena la actividad seleccionada

        
    const handleDetallesActividad = (actividad) => {
        console.log("Actividad seleccionada:", actividad);  // Verifica si el `id_centro` está presente
    
        if (!actividad || !actividad.id_centro) {
            console.error("Error: Actividad no válida o falta `id_centro`", actividad);
            alert("No se puede abrir el modal porque faltan datos de la actividad.");
            return;  // Evita abrir el modal si no hay `id_centro`
        }
    
        setActividadSeleccionada(actividad);
        setModalVisible(true);
    };
    
    const [filtros, setFiltros] = useState({
        id_cliente: '',
        id_centro: '',
        fecha_inicio: '',
        fecha_fin: '',
    });

        
        
    
    // Función para cargar datos
    const cargarDatos = useCallback(async () => {
        try {
            setLoading(true);
            console.log("Filtros enviados:", filtros);
            await cargarActas(
                (datosActividades) => {
                    console.log("Actividades cargadas:", datosActividades);
                    setActividades(datosActividades);
                },
                (datosServicios) => {
                    console.log("Servicios adicionales cargados:", datosServicios);
                    setServiciosAdicionales(datosServicios);
                },
                filtros
            );
        } catch (error) {
            console.error('Error al cargar los datos:', error);
        } finally {
            setLoading(false);
        }
    }, [filtros]);

    // Cargar datos iniciales al montar el componente: Sin [cargarDatos]:
//Es como abrir la app de tareas y solo ver las tareas una vez. Si agregas una tarea nueva, no se actualiza automáticamente.
//Con [cargarDatos]:
//Es como abrir la app de tareas y cada vez que agregas o editas una tarea, la app actualiza automáticamente la lista para mostrarte los cambios.
    useEffect(() => {
        cargarDatos();
        cargarTodasRazonesSociales(setRazonesSociales);
    }, [cargarDatos]);

    // Manejar cambios en los filtros
    const handleFilterChange = (e) => {
        const { name, value } = e.target;
        setFiltros((prevFiltros) => ({ ...prevFiltros, [name]: value }));
    };

    const aplicarFiltros = () => {
        cargarDatos();
    };

    //inicio servicios adicionales//
    // Guardar o actualizar un servicio
    const handleGuardarServicio = async () => {
         // Solo validar la fecha si es un nuevo servicio
        if (!servicioEditar && !fechaInstalacion) {
            setErrorFechaInstalacion(true);
            return;  // Detiene la función si falta la fecha en creación
        }
        const datosServicio = {
            id_razon_social: razonSocialId || servicioEditar?.id_razon_social,  // Aseguramos que siempre haya un valor
            fecha_instalacion: fechaInstalacion || servicioEditar?.fecha_instalacion,
            observaciones: observaciones !== undefined ? observaciones : servicioEditar?.observacion,
            documento_asociado: documento || servicioEditar?.documento_asociado  // Asegura que si no hay nuevo documento, se mantenga el anterior
        };    
        console.log("Datos enviados:", datosServicio);  // Para depuración
    
        try {
            if (servicioEditar) {
                await modificarServicio(servicioEditar.id, datosServicio);
                alert('Servicio actualizado exitosamente');
            } else {
                await agregarServicio(datosServicio);
                alert('Servicio creado exitosamente');
            }
    
            await cargarDatos();  // Recargar datos
            window.$('#modalServicio').modal('hide');  // Cerrar modal
            resetForm();  // Limpiar formulario
        } catch (error) {
            alert('Error al guardar el servicio');
            console.error('Error al guardar el servicio:', error.response ? error.response.data : error);
        }
    };  
            
    // Manejar la edición de un servicio
    const handleEditarServicio = (servicio) => {
        setRazonSocialId(servicio.id_razon_social);
        setFechaInstalacion(servicio.fecha_instalacion); 
        setObservacion(servicio.observacion);
        setDocumento(null);  // Solo actualizar si suben uno nuevo
    
        setServicioEditar(servicio);  // Guardamos el servicio en edición
    
        window.$('#modalServicio').modal('show');  // Abrimos el modal para editar
    };    

    // Manejar la eliminación de un servicio
    const handleEliminarServicio = async (id) => {
        if (window.confirm('¿Estás seguro de que quieres eliminar este centro?')) {
                        borrarServicio(id, () => {
                            cargarDatos();
                        });
                    }
                };

    const resetForm = () => {
                    setRazonSocialId('');
                    setFechaInstalacion('');
                    setObservacion('');
                    setDocumento(null);
                    setServicioEditar(null);  // Salir del modo de edición
                    setErrorFechaInstalacion(false); 
    };     
    //final servicios adicionales//
    const formatearFechaConDia = (fecha) => {
        if (!fecha) return '';
        const fechaObj = new Date(fecha);
        fechaObj.setMinutes(fechaObj.getMinutes() + fechaObj.getTimezoneOffset());
        const opciones = { weekday: 'long', day: '2-digit', month: '2-digit', year: 'numeric' };
        return new Intl.DateTimeFormat('es-ES', opciones).format(fechaObj).replace(',', '');
    };

    // Columnas de las tablas
    const columnasActividades = [
        { name: 'Centro', selector: row => row.nombre_centro, sortable: true },
        { name: 'Área', selector: row => row.area, sortable: true },
        { name: 'Ubicación', selector: row => row.ubicacion, sortable: true },
        { name: 'Estado', selector: row => row.estado, sortable: true },
        
        { name: 'Levantamiento (Fecha)', selector: row => formatearFechaConDia(row.levantamiento_fecha), sortable: true },
        { 
            name: 'Levantamiento (Documento)',
            cell: row => row.levantamiento_documento ? (
                <a href={row.levantamiento_documento} target="_blank" rel="noopener noreferrer">Ver Documento</a>
            ) : <span style={{ color: 'red', fontWeight: 'bold' }}>No Disponible</span>
        },
        { name: 'Instalación (Fecha)', selector: row => formatearFechaConDia(row.instalacion_fecha), sortable: true },
        { 
            name: 'Instalación (Documento)',
            cell: row => row.instalacion_documento ? (
                <a href={row.instalacion_documento} target="_blank" rel="noopener noreferrer">Ver Documento</a>
            ) : <span style={{ color: 'red', fontWeight: 'bold' }}>No Disponible</span>
        },
        
        { name: 'Mantención (Fecha)', selector: row => formatearFechaConDia(row.mantencion_fecha), sortable: true, width: '157px' },
        { 
            name: 'Mantención (Documento)',
            cell: row => row.mantencion_documento ? (
                <a href={row.mantencion_documento} target="_blank" rel="noopener noreferrer">Ver Documento</a>
            ) : <span style={{ color: 'red', fontWeight: 'bold' }}>No Disponible</span>
        },
        
        { name: 'Traslado (Fecha)', selector: row => formatearFechaConDia(row.traslado_fecha), sortable: true },
        { 
            name: 'Traslado (Documento)',
            cell: row => row.traslado_documento ? (
                <a href={row.traslado_documento} target="_blank" rel="noopener noreferrer">Ver Documento</a>
            ) : 'No Disponible'
        },
        { name: 'Cese (Fecha)', selector: row => formatearFechaConDia(row.cese_fecha), sortable: true },
        { 
            name: 'Cese (Documento)',
            cell: row => row.cese_documento ? (
                <a href={row.cese_documento} target="_blank" rel="noopener noreferrer">Ver Documento</a>
            ) : <span style={{ color: 'red', fontWeight: 'bold' }}>No Disponible</span>
        },
        { name: 'Retiro (Fecha)', selector: row => formatearFechaConDia(row.retiro_fecha), sortable: true, width: '157px' },
        { 
            name: 'Retiro (Documento)',
            cell: row => row.retiro_documento ? (
                <a href={row.retiro_documento} target="_blank" rel="noopener noreferrer">Ver Documento</a>
            ) : <span style={{ color: 'red', fontWeight: 'bold' }}>No Disponible</span>
        },
        { 
            name: 'Inventario (Documento)',
            cell: row => row.inventario_documento ? (
                <a href={row.inventario_documento} target="_blank" rel="noopener noreferrer">Ver Documento</a>
            ) : <span style={{ color: 'red', fontWeight: 'bold' }}>No Disponible</span>
        },
        {
            name: 'Acciones',
            cell: (row) => (
                <button className="btn btn-info btn-sm" onClick={() => handleDetallesActividad(row)}>
                <i className="fas fa-info-circle"></i> Detalles
            </button>
            ),
        },
        
    ];

    const columnasServiciosAdicionales = [
        { name: 'ID', selector: row => row.id, sortable: true }, 
        { name: 'Cliente', selector: row => row.nombre_cliente, sortable: true },
        { name: 'Razon social', selector: row => row.nombre_empresa, sortable: true },
        { name: 'Fecha Instalación', selector: row => formatearFechaConDia(row.fecha), sortable: true },        
        { 
            name: 'Documento',
            cell: row => row.documento ? (
                <a href={row.documento} target="_blank" rel="noopener noreferrer">Ver Documento</a>
            ) : 'No Disponible'
        },
        { name: 'Observaciones', selector: row => row.observacion, wrap: true },
        {
            name: 'Acciones',
            cell: (row) => (
                <div>
                    <button className="btn btn-warning btn-sm mr-2" onClick={() => handleEditarServicio(row)}>
                        <i className="fas fa-edit"></i>
                    </button>
                    <button className="btn btn-danger btn-sm" onClick={() => handleEliminarServicio(row.id)}>
                        <i className="fas fa-trash-alt"></i>
                    </button>
                </div>
            ),
        },
        
    ];

    return (
        <div>
            <section className="content-header">
                <div className="container-fluid">
                    <div className="row mb-2">
                        <div className="col-sm-6">
                            <h1>Registros de Documentos</h1>
                        </div>
                    </div>
                </div>
            </section>

            <section className="content">
                <div className="container-fluid">
                    {/* Filtros */}
                    <div className="row mb-3">
                        <div className="col-md-3">
                            <input
                                type="text"
                                className="form-control"
                                name="id_cliente"
                                placeholder="Buscar por Cliente"
                                onChange={handleFilterChange}
                            />
                        </div>
                        <div className="col-md-3">
                            <input
                                type="text"
                                className="form-control"
                                name="id_centro"
                                placeholder="Buscar por Centro"
                                onChange={handleFilterChange}
                            />
                        </div>
                        <div className="col-md-3">
                            <input
                                type="date"
                                className="form-control"
                                name="fecha_inicio"
                                placeholder="Fecha Inicio"
                                onChange={handleFilterChange}
                            />
                        </div>
                        <div className="col-md-3">
                            <input
                                type="date"
                                className="form-control"
                                name="fecha_fin"
                                placeholder="Fecha Fin"
                                onChange={handleFilterChange}
                            />
                        </div>
                        <div className="col-md-12 mt-3">
                            <button className="btn btn-primary" onClick={aplicarFiltros}>Aplicar Filtros</button>
                        </div>
                    </div>

                    {/* Tabla de Actividades */}
                    <div className="card">
                        <div className="card-header">
                            <h3 className="card-title">Actividades</h3>
                        </div>
                        <div className="card-body">
                            <DataTable
                                columns={columnasActividades}
                                data={actividades}
                                progressPending={loading}
                                pagination
                                highlightOnHover
                                pointerOnHover
                                responsive
                                noDataComponent="No hay actividades disponibles"
                            />
                        </div>
                    </div>

                    {/* Tabla de Servicios Adicionales */}
                    <div className="card mt-4">
                        <div className="card-header">
                            <h3 className="card-title">Servicios Adicionales</h3>
                            <button className="btn btn-success float-right" onClick={() => {
                                resetForm();
                                window.$('#modalServicio').modal('show');
                            }}>
                                <i className="fas fa-plus"></i> Agregar Servicio
                            </button>                    
                        </div>
                        <div className="card-body">
                            <DataTable
                                columns={columnasServiciosAdicionales}
                                data={serviciosAdicionales}
                                progressPending={loading}
                                pagination
                                highlightOnHover
                                pointerOnHover
                                responsive
                                noDataComponent="No hay servicios adicionales disponibles"
                            />
                        </div>
                    </div>
                </div>
            </section>

              {/* MODAL PARA AGREGAR O EDITAR SERVICIO ADICIONAL */}
              <div className="modal fade" id="modalServicio" tabIndex="-1" role="dialog" aria-labelledby="modalServicioLabel" aria-hidden="true">
                    <div className="modal-dialog" role="document">
                        <div className="modal-content">
                            <div className="modal-header">
                                <h5 className="modal-title" id="modalServicioLabel">
                                    {servicioEditar ? 'Editar Servicio' : 'Crear Servicio'}
                                </h5>
                                <button type="button" className="close" data-dismiss="modal" aria-label="Close">
                                    <span aria-hidden="true">&times;</span>
                                </button>
                            </div>
                            <div className="modal-body">
                                <form>
                                    <div className="form-group">
                                        <label>Razón Social</label>
                                        <select
                                                className="form-control"
                                                value={razonSocialId}  // Esto asegura que se seleccione la razón social correcta
                                                onChange={(e) => setRazonSocialId(e.target.value)}  // Permite cambios si el usuario selecciona otra
                                            >
                                                <option value="">Seleccione una razón social</option>  {/* Esta opción solo aparece si no hay razón seleccionada */}
                                                {razonesSociales.map((razon) => (
                                                    <option key={razon.id_razon_social} value={String(razon.id_razon_social)}>
                                                        {razon.razon_social}
                                                    </option>
                                                ))}
                                            </select>
                                    </div>
                                    <div className="form-group">
                                    <label>
                                        Fecha de Instalación {!servicioEditar && <span className="text-danger">*</span>} {/* Asterisco solo en creación */}
                                    </label>
                                    <input
                                        type="date"
                                        className={`form-control ${errorFechaInstalacion ? 'is-invalid' : ''}`}
                                        value={fechaInstalacion}
                                        onChange={(e) => {
                                            setFechaInstalacion(e.target.value);
                                            if (e.target.value) setErrorFechaInstalacion(false);  // Quitar el error si el usuario llena el campo
                                        }}
                                        required={!servicioEditar}
                                    />
                                    {!servicioEditar && errorFechaInstalacion && (
                                        <small className="text-danger">La fecha de instalación es obligatoria.</small>
                                    )}
                                    </div>
                                    
                                    <div className="form-group">
                                        <label>Observación</label>
                                        <textarea
                                            className="form-control"
                                            value={observaciones}
                                            onChange={(e) => setObservacion(e.target.value)}
                                        ></textarea>
                                    </div>
                                    <div className="form-group">
                                        <label>Documento</label>
                                        <input
                                            type="file"
                                            className="form-control"
                                            onChange={(e) => setDocumento(e.target.files[0])}
                                        />
                                    </div>
                                </form>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" data-dismiss="modal">
                                    Cerrar
                                </button>
                                <button type="button" className="btn btn-primary" onClick={handleGuardarServicio}>
                                    {servicioEditar ? 'Actualizar Servicio' : 'Guardar Servicio'}
                                </button>
                            </div>
                        </div>
                    </div>
              </div>

              {/* MODAL PARA ACTIVIDADES */}
              {modalVisible && (
                    <ModalActividad
                        actividad={actividadSeleccionada}
                        onClose={() => setModalVisible(false)}
                        recargarDatos={cargarDatos}  // Aquí pasamos la función que recarga los datos
                        onSave={async (datosActividad) => {
                            console.log("Datos a guardar:", datosActividad);
                            setModalVisible(false);  // Cerramos el modal después de guardar
                        }}
                    />
                )}

        </div>

    );
}

export default RegistrosDocumentos;
