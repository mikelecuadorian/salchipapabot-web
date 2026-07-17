#!/usr/bin/env python3
"""
Servidor API + Estático para dashboards del Consorcio ART
Sirve archivos estáticos y endpoints JSON que leen de SQLite en tiempo real
"""
import json
import sqlite3
import os
import sys
import time
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from datetime import datetime, timedelta

DB_PATH = "/data/data/com.termux/files/home/salchipapabot/gestion_medidores.db"
STATIC_DIR = os.path.dirname(os.path.abspath(__file__))
SERVER_START = time.time()  # momento en que arrancó el servidor web


def query_db(sql, params=None):
    """Ejecuta SQL y retorna lista de dicts"""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        if params:
            c.execute(sql, params)
        else:
            c.execute(sql)
        rows = [dict(row) for row in c.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        return {"error": str(e)}


def get_ordenes_sap_data():
    """Retorna todos los datos para el dashboard de órdenes SAP"""
    
    # 1. Estados actuales
    estados = query_db("SELECT estado, COUNT(*) as total FROM ordenes_sap GROUP BY estado")
    estado_map = {r["estado"]: r["total"] for r in estados}
    
    # 2. Capturas por día
    capturas_por_dia = query_db("""
        SELECT date(capturado_en) as dia, COUNT(*) as total 
        FROM ordenes_sap GROUP BY dia ORDER BY dia
    """)
    
    # 3. Estados por día de captura
    estado_por_dia = query_db("""
        SELECT estado, date(capturado_en) as dia, COUNT(*) as total 
        FROM ordenes_sap GROUP BY estado, dia ORDER BY dia
    """)
    
    # 4. Cambios de estado por día
    cambios_por_dia = query_db("""
        SELECT date(fecha_cambio) as dia, COUNT(*) as total 
        FROM historial_ordenes GROUP BY dia ORDER BY dia
    """)
    
    # 5. Cantones
    cantones_all = query_db("""
        SELECT canton, COUNT(*) as total FROM ordenes_sap 
        GROUP BY canton ORDER BY total DESC
    """)
    cantones_por_dia = query_db("""
        SELECT canton, date(capturado_en) as dia, COUNT(*) as total 
        FROM ordenes_sap GROUP BY canton, dia ORDER BY dia
    """)
    
    # 6. Últimas actividades
    ultimas_actividades = query_db("""
        SELECT numero_orden_sap, estado_anterior, estado_nuevo, fecha_cambio 
        FROM historial_ordenes ORDER BY fecha_cambio DESC, id DESC LIMIT 8
    """)
    
    # 7. Capturadas hoy
    hoy = query_db("""
        SELECT COUNT(*) as total FROM ordenes_sap 
        WHERE date(capturado_en) = date('now', 'localtime')
    """)
    capturadas_hoy = hoy[0]["total"] if hoy else 0
    
    # 8. Total general
    total = sum(r["total"] for r in estados)
    
    # Construir arrays por día para el JS
    dias = [r["dia"] for r in capturas_por_dia]
    labels = []
    for d in dias:
        dt = datetime.strptime(d, "%Y-%m-%d")
        labels.append(dt.strftime("%d %b"))
    
    day_total = [r["total"] for r in capturas_por_dia]
    
    day_asignar = [0] * len(dias)
    day_tratamiento = [0] * len(dias)
    day_cierre = [0] * len(dias)
    for r in estado_por_dia:
        idx = dias.index(r["dia"]) if r["dia"] in dias else -1
        if idx >= 0:
            if r["estado"] == "POR_ASIGNAR":
                day_asignar[idx] = r["total"]
            elif r["estado"] == "EN_TRATAMIENTO":
                day_tratamiento[idx] = r["total"]
            elif r["estado"] == "CIERRE_TECNICO":
                day_cierre[idx] = r["total"]
    
    day_cambios = [0] * len(dias)
    for r in cambios_por_dia:
        idx = dias.index(r["dia"]) if r["dia"] in dias else -1
        if idx >= 0:
            day_cambios[idx] = r["total"]
    
    # Cantones por día
    cantones_dia = {}
    for d in dias:
        cantones_dia[d] = []
    for r in cantones_por_dia:
        d = r["dia"]
        if d in cantones_dia:
            cantones_dia[d].append({"nom": r["canton"], "tot": r["total"]})
    cantones_dia["all"] = [{"nom": r["canton"], "tot": r["total"]} for r in cantones_all]
    
    # Formatear actividades
    actividades = []
    for r in ultimas_actividades:
        try:
            dt = datetime.strptime(r["fecha_cambio"], "%Y-%m-%d %H:%M:%S")
            hora = dt.strftime("%d %b %H:%M")
        except:
            hora = r["fecha_cambio"]
        actividades.append({
            "orden": r["numero_orden_sap"],
            "cambio": f"{r['estado_anterior']} → {r['estado_nuevo']}",
            "cuando": hora
        })
    
    return {
        "dias": dias,
        "labels": labels,
        "dayTotal": day_total,
        "dayPorAsignar": day_asignar,
        "dayEnTratamiento": day_tratamiento,
        "dayCierreTecnico": day_cierre,
        "dayCambios": day_cambios,
        "cantonesDia": cantones_dia,
        "actividades": actividades,
        "capturadasHoy": capturadas_hoy,
        "total": total,
        "estados": {r["estado"]: r["total"] for r in estados}
    }


def get_tramites_aciis_data():
    """Retorna todos los datos para el dashboard de trámites ACIIS"""
    
    # 1. Totales globales
    total_asignados = query_db("SELECT COUNT(*) as total FROM recorrido_cuadrillas")
    total_ejecutados = query_db("SELECT COUNT(*) as total FROM gestion_tramites")
    total_pendientes = query_db("""
        SELECT COUNT(*) as total FROM recorrido_cuadrillas
        WHERE numero_tramite NOT IN (
            SELECT numero_tramite FROM gestion_tramites WHERE numero_tramite IS NOT NULL
        )
    """)
    tot_asig = total_asignados[0]["total"] if total_asignados else 0
    tot_eje = total_ejecutados[0]["total"] if total_ejecutados else 0
    tot_pen = total_pendientes[0]["total"] if total_pendientes else 0
    
    # 2. Datos mensuales (últimos 22 meses)
    # Asignados: fecha_analisis en recorrido_cuadrillas
    # Ejecutados: fecha_ejecucion en gestion_tramites
    mensual_asignados = query_db("""
        SELECT strftime('%Y-%m', fecha_analisis) as mes, COUNT(*) as total
        FROM recorrido_cuadrillas 
        WHERE fecha_analisis IS NOT NULL AND fecha_analisis != ''
        GROUP BY mes ORDER BY mes DESC LIMIT 22
    """)
    mensual_ejecutados = query_db("""
        SELECT strftime('%Y-%m', fecha_ejecucion) as mes, COUNT(*) as total
        FROM gestion_tramites 
        WHERE fecha_ejecucion IS NOT NULL
        GROUP BY mes ORDER BY mes DESC LIMIT 22
    """)
    mensual_pendientes = query_db("""
        SELECT strftime('%Y-%m', rc.fecha_analisis) as mes, COUNT(*) as total
        FROM recorrido_cuadrillas rc
        WHERE rc.numero_tramite NOT IN (
            SELECT numero_tramite FROM gestion_tramites WHERE numero_tramite IS NOT NULL
        )
        AND rc.fecha_analisis IS NOT NULL AND rc.fecha_analisis != ''
        GROUP BY mes ORDER BY mes DESC LIMIT 22
    """)
    
    # Reconstruir series ordenadas cronológicamente
    meses_set = set()
    for r in mensual_asignados + mensual_ejecutados + mensual_pendientes:
        if r["mes"]:
            meses_set.add(r["mes"])
    meses = sorted(meses_set)
    
    asig_map = {r["mes"]: r["total"] for r in mensual_asignados if r["mes"]}
    eje_map = {r["mes"]: r["total"] for r in mensual_ejecutados if r["mes"]}
    pen_map = {r["mes"]: r["total"] for r in mensual_pendientes if r["mes"]}
    
    labels = []
    data_asig = []
    data_eje = []
    data_pen = []
    for m in meses:
        dt = datetime.strptime(m + "-01", "%Y-%m-%d")
        labels.append(dt.strftime("%b %y").replace(".", "").capitalize())
        a = asig_map.get(m, 0)
        e = eje_map.get(m, 0)
        data_asig.append(a)
        data_eje.append(e)
        data_pen.append(pen_map.get(m, 0))
    
    # 3. Últimos 7 días
    weekly = query_db("""
        SELECT date(fecha_ejecucion) as dia, COUNT(*) as total
        FROM gestion_tramites
        WHERE fecha_ejecucion >= date('now', 'localtime', '-7 days')
        GROUP BY dia ORDER BY dia
    """)
    weekly_asig = query_db("""
        SELECT date(fecha_analisis) as dia, COUNT(*) as total
        FROM recorrido_cuadrillas
        WHERE fecha_analisis >= date('now', 'localtime', '-7 days')
        GROUP BY dia ORDER BY dia
    """)
    
    weekly_dates = []
    weekly_labels = []
    weekly_asig_data = []
    weekly_eje_data = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        weekly_dates.append(d)
        dt = datetime.strptime(d, "%Y-%m-%d")
        weekly_labels.append(dt.strftime("%d %b"))
        a = 0
        e = 0
        for r in weekly_asig:
            if r["dia"] == d:
                a = r["total"]
                break
        for r in weekly:
            if r["dia"] == d:
                e = r["total"]
                break
        weekly_asig_data.append(a)
        weekly_eje_data.append(e)
    
    # 4. Top cuadrillas
    cuadrillas = query_db("""
        SELECT cuadrilla, COUNT(*) as total FROM recorrido_cuadrillas 
        WHERE cuadrilla IS NOT NULL AND cuadrilla != ''
        GROUP BY cuadrilla ORDER BY total DESC LIMIT 8
    """)
    
    # 4b. Cuadrillas por mes (para filtro)
    c_mensual_raw = query_db("""
        SELECT strftime('%Y-%m', rc.fecha_analisis) as mes, rc.cuadrilla, COUNT(*) as total
        FROM recorrido_cuadrillas rc
        WHERE rc.cuadrilla IS NOT NULL AND rc.cuadrilla != ''
        AND rc.fecha_analisis IS NOT NULL AND rc.fecha_analisis != ''
        GROUP BY mes, rc.cuadrilla
        ORDER BY mes, total DESC
    """)
    cuadrillas_mensual = {}
    for r in c_mensual_raw:
        m = r["mes"]
        if m not in cuadrillas_mensual:
            cuadrillas_mensual[m] = []
        cuadrillas_mensual[m].append({"nom": r["cuadrilla"], "tot": r["total"]})
    
    # 5. Tipos de solicitud
    tipos = query_db("""
        SELECT tipo_solicitud, COUNT(*) as total FROM gestion_tramites
        WHERE tipo_solicitud IS NOT NULL AND tipo_solicitud != ''
        GROUP BY tipo_solicitud ORDER BY total DESC LIMIT 8
    """)
    
    # 5b. Tipos por mes (para filtro)
    t_mensual_raw = query_db("""
        SELECT strftime('%Y-%m', gt.fecha_ejecucion) as mes, gt.tipo_solicitud, COUNT(*) as total
        FROM gestion_tramites gt
        WHERE gt.tipo_solicitud IS NOT NULL AND gt.tipo_solicitud != ''
        AND gt.fecha_ejecucion IS NOT NULL
        GROUP BY mes, gt.tipo_solicitud
        ORDER BY mes, total DESC
    """)
    tipos_mensual = {}
    for r in t_mensual_raw:
        m = r["mes"]
        if m not in tipos_mensual:
            tipos_mensual[m] = []
        tipos_mensual[m].append({"nom": r["tipo_solicitud"], "tot": r["total"]})
    
    # 6. Tipos de orden (cod_motivo_solicitud de recorrido_cuadrillas)
    to_mensual_raw = query_db("""
        SELECT strftime('%Y-%m', rc.fecha_analisis) as mes, rc.cod_motivo_solicitud, COUNT(*) as total
        FROM recorrido_cuadrillas rc
        WHERE rc.cod_motivo_solicitud IS NOT NULL AND rc.cod_motivo_solicitud != ''
        AND rc.fecha_analisis IS NOT NULL AND rc.fecha_analisis != ''
        GROUP BY mes, rc.cod_motivo_solicitud
        ORDER BY mes, total DESC
    """)
    codtipos_mensual = {}
    for r in to_mensual_raw:
        m = r["mes"]
        if m not in codtipos_mensual:
            codtipos_mensual[m] = []
        codtipos_mensual[m].append({"nom": r["cod_motivo_solicitud"], "tot": r["total"]})
    
    return {
        "totalAsignados": tot_asig,
        "totalEjecutados": tot_eje,
        "totalPendientes": tot_pen,
        "porcentajeEjecucion": round((tot_eje / tot_asig * 100), 1) if tot_asig > 0 else 0,
        "meses": meses,
        "labels": labels,
        "dataAsignados": data_asig,
        "dataEjecutados": data_eje,
        "dataPendientes": data_pen,
        "weeklyLabels": weekly_labels,
        "weeklyAsignados": weekly_asig_data,
        "weeklyEjecutados": weekly_eje_data,
        "cuadrillas": [{"nom": r["cuadrilla"], "tot": r["total"]} for r in cuadrillas],
        "tipos": [{"nom": r["tipo_solicitud"], "tot": r["total"]} for r in tipos],
        "cuadrillas_mensual": cuadrillas_mensual,
        "tipos_mensual": tipos_mensual,
        "tipos_orden_mensual": codtipos_mensual
    }


def get_reclamos_data():
    """Retorna todos los datos para el dashboard de RECL"""
    where_extra = "AND codigo_cliente = 'RECL'"

    # 1. KPIs
    total = query_db(f"SELECT COUNT(*) as total FROM gestion_tramites WHERE codigo_cliente = 'RECL'")
    ejecutados = query_db(f"SELECT COUNT(*) as total FROM gestion_tramites WHERE codigo_cliente = 'RECL' AND fecha_ejecucion IS NOT NULL AND fecha_ejecucion != ''")
    pendientes = query_db(f"SELECT COUNT(*) as total FROM gestion_tramites WHERE codigo_cliente = 'RECL' AND (fecha_ejecucion IS NULL OR fecha_ejecucion = '')")
    dias_prom = query_db(f"SELECT round(avg(dias_transcurridos),1) as prom FROM gestion_tramites WHERE codigo_cliente = 'RECL' AND dias_transcurridos IS NOT NULL")

    tot = total[0]["total"] if total else 0
    eje = ejecutados[0]["total"] if ejecutados else 0
    pen = pendientes[0]["total"] if pendientes else 0
    prom = dias_prom[0]["prom"] if dias_prom and dias_prom[0]["prom"] else 0

    # 2. Cuadrillas disponibles (para filtro)
    cuadrillas = query_db(f"""
        SELECT cuadrilla, COUNT(*) as total FROM gestion_tramites
        WHERE codigo_cliente = 'RECL' AND cuadrilla IS NOT NULL AND cuadrilla != ''
        GROUP BY cuadrilla ORDER BY total DESC
    """)
    cuadrillas_list = [{"nom": r["cuadrilla"], "tot": r["total"]} for r in cuadrillas]

    # 3. Días disponibles (para filtro) - incluir hoy siempre
    dias = query_db(f"""
        SELECT date(fecha_ejecucion) as dia, COUNT(*) as total
        FROM gestion_tramites WHERE codigo_cliente = 'RECL'
        AND fecha_ejecucion IS NOT NULL AND fecha_ejecucion != ''
        GROUP BY dia ORDER BY dia DESC
    """)
    dias_list = [{"dia": r["dia"], "tot": r["total"]} for r in dias]
    
    # Asegurar que hoy aparezca en el listado aunque no tenga registros
    hoy_str = datetime.now().strftime("%Y-%m-%d")
    if not any(d["dia"] == hoy_str for d in dias_list):
        dias_list.insert(0, {"dia": hoy_str, "tot": 0})

    # 4. Tendencia mensual (ejecutados por mes)
    mensual = query_db(f"""
        SELECT strftime('%Y-%m', fecha_ejecucion) as mes, COUNT(*) as total
        FROM gestion_tramites WHERE codigo_cliente = 'RECL'
        AND fecha_ejecucion IS NOT NULL AND fecha_ejecucion != ''
        GROUP BY mes ORDER BY mes
    """)
    meses_labels = []
    meses_data = []
    for r in mensual:
        dt = datetime.strptime(r["mes"] + "-01", "%Y-%m-%d")
        meses_labels.append(dt.strftime("%b %y").capitalize())
        meses_data.append(r["total"])

    # 5. Tendencia mensual analizados
    mensual_anal = query_db(f"""
        SELECT strftime('%Y-%m', fecha_analisis) as mes, COUNT(*) as total
        FROM gestion_tramites WHERE codigo_cliente = 'RECL'
        AND fecha_analisis IS NOT NULL AND fecha_analisis != ''
        GROUP BY mes ORDER BY mes
    """)
    meses_anal_labels = []
    meses_anal_data = []
    for r in mensual_anal:
        dt = datetime.strptime(r["mes"] + "-01", "%Y-%m-%d")
        meses_anal_labels.append(dt.strftime("%b %y").capitalize())
        meses_anal_data.append(r["total"])

    # 6. Últimos 7 días
    weekly = query_db(f"""
        SELECT date(fecha_ejecucion) as dia, COUNT(*) as total
        FROM gestion_tramites WHERE codigo_cliente = 'RECL'
        AND fecha_ejecucion >= date('now', 'localtime', '-7 days')
        GROUP BY dia ORDER BY dia
    """)
    weekly_anal = query_db(f"""
        SELECT date(fecha_analisis) as dia, COUNT(*) as total
        FROM gestion_tramites WHERE codigo_cliente = 'RECL'
        AND fecha_analisis >= date('now', 'localtime', '-7 days')
        GROUP BY dia ORDER BY dia
    """)
    weekly_dates = []
    weekly_labels = []
    weekly_eje = []
    weekly_ana = []
    for i in range(6, -1, -1):
        d = (datetime.now() - timedelta(days=i)).strftime("%Y-%m-%d")
        weekly_dates.append(d)
        dt = datetime.strptime(d, "%Y-%m-%d")
        weekly_labels.append(dt.strftime("%d %b"))
        e = next((r["total"] for r in weekly if r["dia"] == d), 0)
        a = next((r["total"] for r in weekly_anal if r["dia"] == d), 0)
        weekly_eje.append(e)
        weekly_ana.append(a)

    # 7. Tipos de reclamo
    tipos = query_db(f"""
        SELECT tipo_solicitud, COUNT(*) as total FROM gestion_tramites
        WHERE codigo_cliente = 'RECL' AND tipo_solicitud IS NOT NULL
        GROUP BY tipo_solicitud ORDER BY total DESC
    """)
    tipos_list = [{"nom": r["tipo_solicitud"], "tot": r["total"]} for r in tipos]

    # 8. Parroquias
    parroquias = query_db(f"""
        SELECT parroquia, COUNT(*) as total FROM gestion_tramites
        WHERE codigo_cliente = 'RECL' AND parroquia IS NOT NULL AND parroquia != ''
        GROUP BY parroquia ORDER BY total DESC
    """)
    parroquias_list = [{"nom": r["parroquia"], "tot": r["total"]} for r in parroquias]

    # 9. Estado instalación
    estado_inst = query_db(f"""
        SELECT estado_instalacion, COUNT(*) as total FROM gestion_tramites
        WHERE codigo_cliente = 'RECL' AND estado_instalacion IS NOT NULL AND estado_instalacion != ''
        GROUP BY estado_instalacion ORDER BY total DESC
    """)
    estado_inst_list = [{"nom": r["estado_instalacion"], "tot": r["total"]} for r in estado_inst]

    # 10. Zona
    zona = query_db(f"""
        SELECT zona, COUNT(*) as total FROM gestion_tramites
        WHERE codigo_cliente = 'RECL' AND zona IS NOT NULL AND zona != ''
        GROUP BY zona ORDER BY total DESC
    """)
    zona_list = [{"nom": r["zona"], "tot": r["total"]} for r in zona]

    # 11. Estado general
    estados = query_db(f"""
        SELECT estado, COUNT(*) as total FROM gestion_tramites
        WHERE codigo_cliente = 'RECL'
        GROUP BY estado ORDER BY total DESC
    """)
    estados_list = [{"nom": r["estado"], "tot": r["total"]} for r in estados]

    return {
        "total": tot,
        "ejecutados": eje,
        "pendientes": pen,
        "porcentajeEjecucion": round((eje / tot * 100), 1) if tot > 0 else 0,
        "diasPromedio": prom,
        "numCuadrillas": len(cuadrillas_list),
        "numParroquias": len(parroquias_list),
        "cuadrillas": cuadrillas_list,
        "dias": dias_list,
        "mesesLabels": meses_labels,
        "mesesData": meses_data,
        "mesesAnalLabels": meses_anal_labels,
        "mesesAnalData": meses_anal_data,
        "weeklyLabels": weekly_labels,
        "weeklyEjecutados": weekly_eje,
        "weeklyAnalizados": weekly_ana,
        "tipos": tipos_list,
        "parroquias": parroquias_list,
        "estadosInstalacion": estado_inst_list,
        "zonas": zona_list,
        "estados": estados_list
    }


def get_reclamos_detalle(dia=None, cuadrilla=None):
    """Retorna la lista detallada de trámites RECL con observacion_gestion, filtrable"""
    where = ["gt.codigo_cliente = 'RECL'"]

    if dia:
        where.append(f"date(gt.fecha_ejecucion) = '{dia}'")
    if cuadrilla:
        # Escape simple para SQL
        c = cuadrilla.replace("'", "''")
        where.append(f"gt.cuadrilla = '{c}'")

    where_clause = " AND ".join(where)

    rows = query_db(f"""
        SELECT gt.numero_tramite,
               rc.fecha_analisis,
               rc.fecha_planificacion,
               gt.fecha_ejecucion,
               gt.cuadrilla, gt.tipo_solicitud,
               gt.observacion_gestion, gt.estado, gt.cliente, gt.direccion,
               gt.parroquia, gt.dias_transcurridos
        FROM gestion_tramites gt
        INNER JOIN recorrido_cuadrillas rc ON gt.numero_tramite = rc.numero_tramite
        WHERE {where_clause}
        ORDER BY rc.fecha_analisis DESC, gt.fecha_ejecucion DESC
        LIMIT 200
    """)
    return {"tramites": rows}


# ═══════════════════════════════════════════════
# BODEGA — Dashboard de materiales
# ═══════════════════════════════════════════════

# Columnas de materiales instalados en gestion_tramites con su nombre legible
MATERIAL_COLS = {
    'kit_conector_ranuras_u': 'Kit conector ranuras',
    'kit_separador_u': 'Kit separador',
    'kit_conector_estanco_u': 'Kit conector estanco',
    'kit_cartucho_fusible_u': 'Kit cartucho fusible',
    'kit_porta_fusible_u': 'Kit porta fusible',
    'kit_derivador_term_u': 'Kit derivador termomagnético',
    'kit_mensula_poste_u': 'Kit ménsula poste',
    'kit_mensula_fachada_u': 'Kit ménsula fachada',
    'kit_pinza_termoplasticas_u': 'Kit pinza termoplástica',
    'kit_precintos_plasticos_u': 'Kit precintos plásticos',
    'pt_varilla_u': 'PT varilla',
    'pt_conector_varilla_u': 'PT conector varilla',
    'pt_cable_cobre_u': 'PT cable cobre',
    'pt_tubo_pvc_u': 'PT tubo PVC',
    'pt_conector_tubo_u': 'PT conector tubo',
    'pt_grapas_emt_u': 'PT grapas EMT',
    'pt_taco_f6_u': 'PT taco F6',
    'pt_tornillo_taco_f6_u': 'PT tornillo taco F6',
    'pt_canaleta_u': 'PT canaleta',
    'grapa_2': 'Grapa #2',
    'grapa_5': 'Grapa #5',
    'grapa_6': 'Grapa #6',
    'conector_puerto_gel': 'Conector puerto gel',
    'conector_tipo_barraje': 'Conector tipo barraje',
    'breaker_u': 'Breaker',
    'cinta_aislante': 'Cinta aislante',
    'tubo_poste_cantidad': 'Tubo poste',
    'acometida_mts': 'Acometida (mts)',
    'alimentador_salida_mts': 'Alimentador salida (mts)',
    'caja_dist_mts': 'Caja distribución (mts)',
    'med_ret_cant_caja': 'Caja medidor retirado',
    'sello_caja_prot_u': 'Sello caja protección',
    'sello_cuarto_transf_u': 'Sello cuarto transformador',
}
MAX_VALID = 100000  # valores mayores a esto son placeholders (INT_MAX, etc.)


def unpivot_materiales(desde=None, hasta=None, cuadrilla=None):
    """Despivota las columnas de materiales de gestion_tramites.
    Retorna lista de dicts: {material, cantidad, cuadrilla, fecha, cliente, tramite}
    """
    where = ["1=1"]
    params = []

    if desde:
        where.append("date(fecha_ejecucion) >= ?")
        params.append(desde)
    if hasta:
        where.append("date(fecha_ejecucion) <= ?")
        params.append(hasta)
    if cuadrilla:
        where.append("cuadrilla = ?")
        params.append(cuadrilla)

    where_clause = " AND ".join(where)

    # Traer datos base
    rows = query_db(f"""
        SELECT numero_tramite, cuadrilla, fecha_ejecucion, cliente, parroquia,
               med_nue_caja,
               {', '.join(MATERIAL_COLS.keys())}
        FROM gestion_tramites
        WHERE {where_clause}
          AND fecha_ejecucion IS NOT NULL AND fecha_ejecucion != ''
    """, params)

    # Despivotar
    materiales = []
    for r in rows:
        # Primero: materiales estándar (columnas numéricas)
        for col, nombre in MATERIAL_COLS.items():
            val = r.get(col)
            if val is not None and val != '':
                if isinstance(val, (int, float)) and 0 < val < MAX_VALID:
                    cantidad = int(val)
                else:
                    continue
                materiales.append({
                    "material": nombre,
                    "columna": col,
                    "cantidad": cantidad,
                    "tipo": "Instalado",
                    "cuadrilla": r.get("cuadrilla", ""),
                    "fecha": r.get("fecha_ejecucion", ""),
                    "cliente": r.get("cliente", ""),
                    "tramite": r.get("numero_tramite", ""),
                    "parroquia": r.get("parroquia", ""),
                })

        # Segundo: med_nue_caja (tipo de caja instalada)
        caja_tipo = r.get("med_nue_caja")
        if caja_tipo is not None and str(caja_tipo).strip():
            materiales.append({
                "material": f"Caja medidor: {str(caja_tipo).strip()}",
                "columna": "med_nue_caja",
                "cantidad": 1,
                "tipo": "Instalado",
                "cuadrilla": r.get("cuadrilla", ""),
                "fecha": r.get("fecha_ejecucion", ""),
                "cliente": r.get("cliente", ""),
                "tramite": r.get("numero_tramite", ""),
                "parroquia": r.get("parroquia", ""),
            })
    return materiales


def get_bodega_instalados(desde, hasta, cuadrilla):
    """API: materiales instalados con filtros"""
    materiales = unpivot_materiales(desde, hasta, cuadrilla)

    # Agrupar por material
    agrupado = {}
    for m in materiales:
        nom = m["material"]
        if nom not in agrupado:
            agrupado[nom] = {"material": nom, "cantidad": 0, "tramites": set()}
        agrupado[nom]["cantidad"] += m["cantidad"]
        agrupado[nom]["tramites"].add(m["tramite"])

    lista = sorted(
        [{"material": k, "cantidad": v["cantidad"], "tramites": len(v["tramites"])}
         for k, v in agrupado.items()],
        key=lambda x: x["cantidad"], reverse=True
    )

    total_materiales = sum(m["cantidad"] for m in materiales)
    total_tramites = len(set(m["tramite"] for m in materiales))

    # Cuadrillas en el filtro
    cuadrillas_list = sorted(set(m["cuadrilla"] for m in materiales if m["cuadrilla"]))

    return {
        "materiales": lista,
        "totalMateriales": total_materiales,
        "totalTramites": total_tramites,
        "cuadrillas": cuadrillas_list,
        "filtro": {"desde": desde, "hasta": hasta, "cuadrilla": cuadrilla}
    }


def get_bodega_retirados(desde, hasta, cuadrilla):
    """API: materiales retirados (de materiales_tramite) con filtros"""
    where = ["1=1"]
    params = []

    if desde:
        where.append("date(fecha_ejecucion) >= ?")
        params.append(desde)
    if hasta:
        where.append("date(fecha_ejecucion) <= ?")
        params.append(hasta)
    if cuadrilla:
        where.append("cuadrilla = ?")
        params.append(cuadrilla)

    where_clause = " AND ".join(where)

    rows = query_db(f"""
        SELECT material, SUM(cantidad) as cantidad, COUNT(DISTINCT numero_tramite) as tramites
        FROM materiales_tramite
        WHERE {where_clause}
        GROUP BY material
        ORDER BY cantidad DESC
    """, params)

    rows = [r for r in rows if r.get("material") is not None] if rows and not isinstance(rows, dict) else rows
    total_materiales = sum(r["cantidad"] for r in rows if r["cantidad"] is not None) if rows and not isinstance(rows, dict) else 0

    # Total de trámites distintos
    tramites_rows = query_db(f"""
        SELECT COUNT(DISTINCT numero_tramite) as total
        FROM materiales_tramite
        WHERE {where_clause}
    """, params)
    total_tramites = tramites_rows[0]["total"] if tramites_rows else 0

    # Cuadrillas
    cuad_rows = query_db(f"""
        SELECT DISTINCT cuadrilla FROM materiales_tramite
        WHERE {where_clause} AND cuadrilla IS NOT NULL AND cuadrilla != ''
        ORDER BY cuadrilla
    """, params)
    cuadrillas_list = [r["cuadrilla"] for r in cuad_rows]

    return {
        "materiales": rows if rows else [],
        "totalMateriales": total_materiales,
        "totalTramites": total_tramites,
        "cuadrillas": cuadrillas_list,
        "filtro": {"desde": desde, "hasta": hasta, "cuadrilla": cuadrilla}
    }


def get_bodega_cuadrillas(desde, hasta):
    """API: materiales agrupados por cuadrilla"""
    instalados = unpivot_materiales(desde, hasta, None)

    # Agrupar instalados por cuadrilla
    inst_por_cuad = {}
    for m in instalados:
        c = m["cuadrilla"] or "Sin cuadrilla"
        if c not in inst_por_cuad:
            inst_por_cuad[c] = {"total": 0, "tramites": set(), "materiales": {}}
        inst_por_cuad[c]["total"] += m["cantidad"]
        inst_por_cuad[c]["tramites"].add(m["tramite"])
        mat = m["material"]
        inst_por_cuad[c]["materiales"][mat] = inst_por_cuad[c]["materiales"].get(mat, 0) + m["cantidad"]

    # Retirados por cuadrilla
    where = ["1=1"]
    params = []
    if desde:
        where.append("date(fecha_ejecucion) >= ?")
        params.append(desde)
    if hasta:
        where.append("date(fecha_ejecucion) <= ?")
        params.append(hasta)

    ret_rows = query_db(f"""
        SELECT cuadrilla, SUM(cantidad) as total, COUNT(DISTINCT numero_tramite) as tramites
        FROM materiales_tramite
        WHERE {' AND '.join(where)} AND cuadrilla IS NOT NULL AND cuadrilla != ''
        GROUP BY cuadrilla
        ORDER BY total DESC
    """, params)

    ret_por_cuad = {r["cuadrilla"]: {"total": r["total"], "tramites": r["tramites"]} for r in ret_rows}

    # Combinar
    todas_cuads = set(list(inst_por_cuad.keys()) + list(ret_por_cuad.keys()))
    resultado = []
    for c in sorted(todas_cuads):
        inst = inst_por_cuad.get(c, {})
        ret = ret_por_cuad.get(c, {})
        resultado.append({
            "cuadrilla": c,
            "instalados": inst.get("total", 0),
            "retirados": ret.get("total", 0),
            "tramitesInst": len(inst.get("tramites", set())),
            "tramitesRet": ret.get("tramites", 0),
        })

    return {"cuadrillas": resultado}


def get_bodega_resumen(desde, hasta):
    """API: resumen diario/semanal/mensual de materiales"""
    materiales = unpivot_materiales(desde, hasta, None)

    # Agrupar instalados por fecha
    por_dia_inst = {}
    for m in materiales:
        dia = (m["fecha"] or "")[:10]
        if dia not in por_dia_inst:
            por_dia_inst[dia] = 0
        por_dia_inst[dia] += m["cantidad"]

    # Agrupar retirados por fecha
    where = ["1=1"]
    params = []
    if desde:
        where.append("date(fecha_ejecucion) >= ?")
        params.append(desde)
    if hasta:
        where.append("date(fecha_ejecucion) <= ?")
        params.append(hasta)

    ret_dias = query_db(f"""
        SELECT date(fecha_ejecucion) as dia, SUM(cantidad) as total
        FROM materiales_tramite
        WHERE {' AND '.join(where)}
        GROUP BY dia ORDER BY dia
    """, params)

    por_dia_ret = {r["dia"]: r["total"] for r in ret_dias}

    # Unir todos los días
    todos_dias = sorted(set(list(por_dia_inst.keys()) + list(por_dia_ret.keys())))
    timeline = []
    for d in todos_dias:
        timeline.append({
            "dia": d,
            "instalados": por_dia_inst.get(d, 0),
            "retirados": por_dia_ret.get(d, 0),
        })

    # Totales generales
    total_inst = sum(m["cantidad"] for m in materiales)
    total_ret = sum(r["total"] for r in ret_dias) if ret_dias else 0
    total_tramites_inst = len(set(m["tramite"] for m in materiales))

    return {
        "timeline": timeline,
        "totalInstalados": total_inst,
        "totalRetirados": total_ret,
        "totalTramitesInst": total_tramites_inst,
    }


def get_bodega_catalogos():
    """API: catálogos para filtros (cuadrillas, fechas mín/máx)"""
    # Fechas disponibles (instalados)
    fechas_inst = query_db("""
        SELECT MIN(date(fecha_ejecucion)) as min, MAX(date(fecha_ejecucion)) as max
        FROM gestion_tramites
        WHERE fecha_ejecucion IS NOT NULL AND fecha_ejecucion != ''
    """)
    fechas_ret = query_db("""
        SELECT MIN(date(fecha_ejecucion)) as min, MAX(date(fecha_ejecucion)) as max
        FROM materiales_tramite
        WHERE fecha_ejecucion IS NOT NULL AND fecha_ejecucion != ''
    """)

    # Cuadrillas
    cuad_inst = query_db("""
        SELECT DISTINCT cuadrilla FROM gestion_tramites
        WHERE cuadrilla IS NOT NULL AND cuadrilla != ''
        ORDER BY cuadrilla
    """)
    cuad_ret = query_db("""
        SELECT DISTINCT cuadrilla FROM materiales_tramite
        WHERE cuadrilla IS NOT NULL AND cuadrilla != ''
        ORDER BY cuadrilla
    """)

    todas_cuads = set()
    for r in cuad_inst + cuad_ret:
        todas_cuads.add(r["cuadrilla"])

    return {
        "fechaMin": fechas_inst[0]["min"] if fechas_inst else None,
        "fechaMax": fechas_inst[0]["max"] if fechas_inst else None,
        "cuadrillas": sorted(todas_cuads),
    }


class APIHandler(SimpleHTTPRequestHandler):
    """Manejador que sirve estáticos + API JSON"""
    
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        
        if path == "/api/ordenes-sap":
            self.send_json(get_ordenes_sap_data())
        elif path == "/api/tramites-aciis":
            self.send_json(get_tramites_aciis_data())
        elif path == "/api/reclamos":
            self.send_json(get_reclamos_data())
        elif path == "/api/reclamos-detalle":
            qs = urllib.parse.parse_qs(parsed.query)
            dia = qs.get("dia", [None])[0]
            cuadrilla = qs.get("cuadrilla", [None])[0]
            self.send_json(get_reclamos_detalle(dia, cuadrilla))
        elif path == "/api/bodega/instalados":
            qs = urllib.parse.parse_qs(parsed.query)
            d = qs.get("desde", [None])[0]
            h = qs.get("hasta", [None])[0]
            c = qs.get("cuadrilla", [None])[0]
            self.send_json(get_bodega_instalados(d, h, c))
        elif path == "/api/bodega/retirados":
            qs = urllib.parse.parse_qs(parsed.query)
            d = qs.get("desde", [None])[0]
            h = qs.get("hasta", [None])[0]
            c = qs.get("cuadrilla", [None])[0]
            self.send_json(get_bodega_retirados(d, h, c))
        elif path == "/api/bodega/cuadrillas":
            qs = urllib.parse.parse_qs(parsed.query)
            d = qs.get("desde", [None])[0]
            h = qs.get("hasta", [None])[0]
            self.send_json(get_bodega_cuadrillas(d, h))
        elif path == "/api/bodega/resumen":
            qs = urllib.parse.parse_qs(parsed.query)
            d = qs.get("desde", [None])[0]
            h = qs.get("hasta", [None])[0]
            self.send_json(get_bodega_resumen(d, h))
        elif path == "/api/bodega/catalogos":
            self.send_json(get_bodega_catalogos())
        elif path == "/api/system":
            self.send_json(self.get_system_info())
        else:
            # Servir archivos estáticos desde STATIC_DIR
            super().do_GET()
    
    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def get_system_info(self):
        import subprocess, os
        info = {}
        # Uptimes
        try:
            # CLOCK_BOOTTIME da el uptime real del dispositivo
            uptime_sec = time.clock_gettime(time.CLOCK_BOOTTIME)
            days = int(uptime_sec // 86400)
            hours = int((uptime_sec % 86400) // 3600)
            mins = int((uptime_sec % 3600) // 60)
            info["uptime"] = f"{days}d {hours}h {mins}m"
        except Exception as e:
            # Fallback a /proc/uptime
            try:
                with open("/proc/uptime") as f:
                    uptime_sec = float(f.read().split()[0])
                    days = int(uptime_sec // 86400)
                    hours = int((uptime_sec % 86400) // 3600)
                    mins = int((uptime_sec % 3600) // 60)
                    info["uptime"] = f"{days}d {hours}h {mins}m"
            except:
                info["uptime"] = "N/A"
        # Android uptime
        try:
            import subprocess
            r = subprocess.run(["getprop", "sys.system_server.start_uptime"], capture_output=True, text=True, timeout=3)
            if r.returncode == 0 and r.stdout.strip():
                sec = int(r.stdout.strip())
                d = int(sec // 86400)
                h = int((sec % 86400) // 3600)
                m = int((sec % 3600) // 60)
                info["android_uptime"] = f"{d}d {h}h {m}m"
            else:
                info["android_uptime"] = "N/A"
        except:
            info["android_uptime"] = "N/A"
        # Server uptime
        try:
            sec = time.time() - SERVER_START
            d = int(sec // 86400)
            h = int((sec % 86400) // 3600)
            m = int((sec % 3600) // 60)
            info["server_uptime"] = f"{d}d {h}h {m}m"
        except:
            info["server_uptime"] = "N/A"
        # Carga CPU
        try:
            with open("/proc/loadavg") as f:
                parts = f.read().split()
                info["load_1m"] = parts[0]
                info["load_5m"] = parts[1]
                info["load_15m"] = parts[2]
            ncpu = os.cpu_count() or 1
            info["cpu_pct"] = round(float(parts[0]) / ncpu * 100, 1)
        except:
            info["cpu_pct"] = 0
            info["load_1m"] = "0"
        # RAM
        try:
            with open("/proc/meminfo") as f:
                mem = {}
                for line in f:
                    for k in ["MemTotal", "MemFree", "MemAvailable", "Buffers", "Cached"]:
                        if line.startswith(k + ":"):
                            mem[k.lower()] = int(line.split()[1]) // 1024
                info["ram_total_mb"] = mem.get("memtotal", 0)
                info["ram_free_mb"] = mem.get("memfree", 0)
                info["ram_avail_mb"] = mem.get("memavailable", 0)
                info["ram_buffers_mb"] = mem.get("buffers", 0) + mem.get("cached", 0)
                used = info["ram_total_mb"] - info["ram_avail_mb"]
                info["ram_used_mb"] = used
                info["ram_pct"] = round(used / info["ram_total_mb"] * 100, 1) if info["ram_total_mb"] else 0
        except:
            pass
        # Disco
        try:
            st = os.statvfs("/data/data/com.termux/files/home/")
            total = st.f_blocks * st.f_frsize
            free = st.f_bfree * st.f_frsize
            avail = st.f_bavail * st.f_frsize
            used = total - free
            info["disk_total_gb"] = round(total / (1024**3), 1)
            info["disk_used_gb"] = round(used / (1024**3), 1)
            info["disk_avail_gb"] = round(avail / (1024**3), 1)
            info["disk_pct"] = round(used / total * 100, 1) if total else 0
        except:
            pass
        # Servicios runsv - leer directo de supervise/stat + verificar PID
        try:
            SVDIR = "/data/data/com.termux/files/usr/var/service"
            svcs = ["salchipapabot", "papafritabot", "burgerbot", "servidor_web", "sshd_custom", "cloudflared", "hermes"]
            servicios = []
            for s in svcs:
                stat_path = f"{SVDIR}/{s}/supervise/stat"
                pid_path = f"{SVDIR}/{s}/supervise/pid"
                estado = "down"
                pid = ""
                try:
                    with open(stat_path) as f:
                        raw = f.read().strip()
                    with open(pid_path) as f:
                        pid = f.read().strip()
                    # Verificar que el PID realmente esté vivo
                    if pid and raw == "run":
                        try:
                            os.kill(int(pid), 0)
                            estado = "up"
                        except OSError:
                            estado = "down"
                except:
                    pass
                servicios.append({"name": s, "status": estado, "pid": pid})
            info["servicios"] = servicios
        except:
            info["servicios"] = []
        # BD
        try:
            db_size = os.path.getsize("/data/data/com.termux/files/home/salchipapabot/gestion_medidores.db")
            info["db_size_mb"] = round(db_size / (1024*1024), 1)
        except:
            info["db_size_mb"] = 0
        # Hostname
        try:
            info["hostname"] = os.uname().nodename
        except:
            info["hostname"] = "unknown"
        # Cron jobs
        try:
            r = subprocess.run(["/usr/local/lib/hermes-agent/venv/bin/hermes", "cron", "list"], capture_output=True, text=True, timeout=10)
            crons = []
            current = {}
            for line in r.stdout.split("\n"):
                line_stripped = line.strip()
                if line_stripped.startswith("Name:"):
                    current["name"] = line_stripped.split(":", 1)[1].strip()
                elif line_stripped.startswith("Schedule:"):
                    current["schedule"] = line_stripped.split(":", 1)[1].strip()
                elif line_stripped.startswith("Next run:"):
                    current["next_run"] = line_stripped.split(":", 1)[1].strip()
                elif line_stripped.startswith("Last run:"):
                    current["last_run"] = line_stripped.split(":", 1)[1].strip()
                elif line_stripped.startswith("Mode:"):
                    current["mode"] = line_stripped.split(":", 1)[1].strip()
                elif line_stripped.startswith("Script:"):
                    current["script"] = line_stripped.split(":", 1)[1].strip()
                elif line_stripped.startswith("Deliver:"):
                    current["deliver"] = line_stripped.split(":", 1)[1].strip()
                elif "active" in line_stripped or "paused" in line_stripped:
                    if current.get("name"):
                        crons.append(current)
                    current = {}
            if current.get("name"):
                crons.append(current)
            info["crons"] = crons
            info["_cron_debug"] = f"parsed={len(crons)} lines={len(r.stdout.split(chr(10)))} rc={r.returncode}"
        except Exception as e:
            info["crons"] = []
            info["_cron_debug"] = f"error: {e}"
        # Batería (Termux:API) - cacheado 60s con timeout
        try:
            now = time.time()
            if not hasattr(self, '_battery_cache_time') or now - self._battery_cache_time > 60:
                self._battery_cache = {"battery": "N/A"}
                r = subprocess.run(["timeout", "3", "termux-battery-status"], capture_output=True, text=True, timeout=5)
                if r.returncode == 0 and r.stdout.strip():
                    bat = json.loads(r.stdout)
                    self._battery_cache = {
                        "battery_pct": bat.get("percentage", 0),
                        "battery_status": bat.get("status", "N/A"),
                        "battery_temp": bat.get("temperature", 0),
                        "battery_plugged": bat.get("plugged", "N/A"),
                    }
                self._battery_cache_time = now
            info.update(self._battery_cache)
        except:
            info["battery"] = "N/A"
        return info
    
    def translate_path(self, path):
        # Forzar que los archivos se sirvan desde STATIC_DIR
        path = super().translate_path(path)
        relpath = os.path.relpath(path, os.getcwd())
        return os.path.join(STATIC_DIR, relpath)
    
    def log_message(self, format, *args):
        sys.stderr.write("[API] %s - %s\n" % (self.log_date_time_string(), format % args))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("0.0.0.0", port), APIHandler)
    print(f"🚀 API + Estáticos sirviendo en puerto {port}")
    print(f"📁 Directorio: {STATIC_DIR}")
    print(f"🗄️  BD: {DB_PATH}")
    print(f"📡 Endpoints:")
    print(f"   GET /api/ordenes-sap")
    print(f"   GET /api/tramites-aciis")
    print(f"   GET /api/reclamos")
    print(f"   GET /api/reclamos-detalle?dia=X&cuadrilla=Y")
    print(f"   GET /api/bodega/instalados?desde=X&hasta=Y&cuadrilla=Z")
    print(f"   GET /api/bodega/retirados?desde=X&hasta=Y&cuadrilla=Z")
    print(f"   GET /api/bodega/cuadrillas?desde=X&hasta=Y")
    print(f"   GET /api/bodega/resumen?desde=X&hasta=Y")
    print(f"   GET /api/bodega/catalogos")
    print(f"   GET /api/system (estado del servidor)")
    print(f"   GET /dashboard.html (todo-en-uno)")
    print(f"   GET / (archivos estáticos)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Servidor detenido")
        server.server_close()


if __name__ == "__main__":
    main()
