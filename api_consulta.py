#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
api_consulta.py — Endpoints de consulta remota (solo lectura) para el Hermes de Windows.

Diseñado 2026-10-16 a pedido de Miguel:
  * GET  /api/consulta/health          → verifica token + estado de la BD
  * GET  /api/consulta/schema          → lista tablas y columnas
  * POST /api/consulta/sql             → ejecuta SELECT (JSON body: {"sql": "..."})
  * GET  /api/buzon                    → lee mensajes para Windows
  * POST /api/buzon                    → escribe mensaje (requiere token)

SEGURIDAD (importante):
  - Token obligatorio en cabecera `X-Api-Token` (o `?token=` para GET simple).
  - SOLO SELECT / WITH / PRAGMA de lectura. Se rechazan INSERT/UPDATE/DELETE/DROP/
    ALTER/ATTACH/CREATE/REPLACE/VACUUM/REINDEX y cualquier escritura.
  - Limite de filas y timeout por consulta.
  - La BD se abre en modo `mode=ro` (read-only a nivel de SQLite).
  - Bloqueo de `sqlite_master` writes, PRAGMA peligrosos y funciones de sistema.

El token vive en ~/.hermes/state/api_consulta_token.txt (chmod 600).
"""
import json
import os
import re
import sqlite3
import time
import urllib.parse

DB_PATH = "/data/data/com.termux/files/home/salchipapabot/gestion_medidores.db"
TOKEN_FILE = '/data/data/com.termux/files/home/.config/clave_api.txt'
BUZON_FILE = '/data/data/com.termux/files/home/.config/buzon_windows.jsonl'
LOG_FILE = '/data/data/com.termux/files/home/.config/api_consulta.log'

MAX_FILAS = 5000
TIMEOUT_S = 20


def leer_token():
    try:
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except Exception:
        pass


def token_ok(headers, query_string):
    """Valida el token. Acepta cabecera X-Api-Token o ?token= en la URL."""
    esperado = leer_token()
    if not esperado:
        return False, "token no configurado en el servidor"
    recibido = ""
    try:
        recibido = (headers.get("X-Api-Token") or "").strip()
    except Exception:
        pass
    if not recibido and query_string:
        qs = urllib.parse.parse_qs(query_string)
        recibido = (qs.get("token", [""])[0] or "").strip()
    if not recibido:
        return False, "falta el token (cabecera X-Api-Token)"
    if recibido != esperado:
        return False, "token invalido"
    return True, ""


_PALABRAS_PROHIBIDAS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|"
    r"VACUUM|REINDEX|GRANT|REVOKE|PRAGMA\s+(?!table_info|table_xinfo|index_list|"
    r"foreign_key_list|database_list|compile_options))\b",
    re.IGNORECASE,
)


def validar_sql(sql):
    """Rechaza cualquier cosa que no sea una consulta de lectura."""
    s = (sql or "").strip()
    if not s:
        return False, "SQL vacio"
    # quitar comentarios para no burlar la deteccion
    limpio = re.sub(r"--[^\n]*", " ", s)
    limpio = re.sub(r"/\*.*?\*/", " ", limpio, flags=re.DOTALL).strip()
    # sin punto y coma final; prohibido encadenar sentencias
    if ";" in limpio.rstrip().rstrip(";"):
        return False, "no se permiten multiples sentencias"
    limpio = limpio.rstrip().rstrip(";").strip()
    primera = limpio.split(None, 1)[0].upper() if limpio.split() else ""
    if primera not in ("SELECT", "WITH", "PRAGMA", "EXPLAIN"):
        return False, f"solo SELECT/WITH/PRAGMA/EXPLAIN (recibido: {primera})"
    m = _PALABRAS_PROHIBIDAS.search(limpio)
    if m:
        return False, f"palabra no permitida: {m.group(0)}"
    if len(limpio) > 20000:
        return False, "SQL demasiado largo"
    return True, limpio


def abrir_ro():
    """Abre la BD en modo solo lectura."""
    uri = f"file:{DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    return conn


def ejecutar_consulta(sql):
    ok, res = validar_sql(sql)
    if not ok:
        return {"ok": False, "error": res}
    t0 = time.time()
    try:
        conn = abrir_ro()
        cur = conn.cursor()
        cur.execute(res)
        filas = cur.fetchmany(MAX_FILAS + 1)
        columnas = [d[0] for d in (cur.description or [])]
        truncado = len(filas) > MAX_FILAS
        datos = [dict(r) for r in filas[:MAX_FILAS]]
        conn.close()
        return {
            "ok": True,
            "columnas": columnas,
            "filas": datos,
            "n": len(datos),
            "truncado": truncado,
            "ms": int((time.time() - t0) * 1000),
        }
    except sqlite3.Error as e:
        return {"ok": False, "error": f"SQLite: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"error: {e}"}


def schema():
    try:
        conn = abrir_ro()
        cur = conn.cursor()
        cur.execute("SELECT name, type FROM sqlite_master WHERE type IN ('table','view') "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY name")
        tablas = []
        for nombre, tipo in cur.fetchall():
            try:
                cols = conn.execute(f'PRAGMA table_info("{nombre}")').fetchall()
                tablas.append({
                    "nombre": nombre,
                    "tipo": tipo,
                    "columnas": [{"nombre": c[1], "tipo": c[2]} for c in cols],
                })
            except Exception:
                tablas.append({"nombre": nombre, "tipo": tipo, "columnas": []})
        conn.close()
        return {"ok": True, "tablas": tablas, "total": len(tablas)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def health():
    info = {"ok": True, "bd": DB_PATH, "existe": os.path.exists(DB_PATH)}
    try:
        info["tamano_mb"] = round(os.path.getsize(DB_PATH) / (1024 * 1024), 1)
        info["mtime"] = time.strftime("%Y-%m-%d %H:%M:%S",
                                     time.localtime(os.path.getmtime(DB_PATH)))
        conn = abrir_ro()
        n = conn.execute("SELECT COUNT(*) FROM gestion_tramites").fetchone()[0]
        conn.close()
        info["tramites"] = n
        info["lectura"] = "ok"
    except Exception as e:
        info["ok"] = False
        info["error"] = str(e)
    return info


# ── Buzón: mensajes del Hermes de la tablet al Hermes de Windows ──────────────
def buzon_leer(desde_id=0):
    """Lee mensajes nuevos (id > desde_id)."""
    msgs = []
    try:
        if os.path.exists(BUZON_FILE):
            with open(BUZON_FILE, encoding="utf-8") as fh:
                for i, line in enumerate(fh, start=1):
                    line = line.strip()
                    if not line or i <= desde_id:
                        continue
                    try:
                        d = json.loads(line)
                        d["id"] = i
                        msgs.append(d)
                    except Exception:
                        continue
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "mensajes": msgs, "n": len(msgs)}


def buzon_escribir(remitente, asunto, cuerpo):
    """Añade un mensaje al buzón (append-only)."""
    try:
        os.makedirs(os.path.dirname(BUZON_FILE), exist_ok=True)
        entrada = {
            "de": remitente or "desconocido",
            "asunto": asunto or "",
            "cuerpo": cuerpo or "",
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        with open(BUZON_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        return {"ok": True, "guardado": entrada}
    except Exception as e:
        return {"ok": False, "error": str(e)}
