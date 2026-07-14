# SalchipapaBot Web 🖥️

Servidor web y dashboards para el ecosistema **SalchipapaBot**. Proporciona APIs REST y visualizaciones en tiempo real de la base de datos de gestión de medidores.

## 🌐 Dashboards

Accesibles desde [`ecosistema.salchipapabot.cc.cd`](https://ecosistema.salchipapabot.cc.cd):

| Dashboard | Ruta | Descripción |
|-----------|------|-------------|
| 🏠 **Principal** | `/` | Estado general del ecosistema |
| 🏭 **Bodega** | `/bodega.html` | Materiales instalados/retirados por cuadrilla |
| 🏗️ **SAP** | `/ordenes-sap.html` | Órdenes extraídas del SAP |
| 📋 **ACIIS** | `/tramites-aciis.html` | Trámites del portal ACIIS |
| 📞 **RECL** | `/reclamos.html` | Reclamos diarios por cuadrilla |
| 🖥️ **Servidores** | `/server-ecosystem.html` | Estado de servicios y servidores |

## 🔌 APIs

El servidor expone endpoints JSON para consumo interno:

| Endpoint | Descripción |
|----------|-------------|
| `GET /api/ordenes-sap` | Órdenes SAP activas |
| `GET /api/tramites-aciis` | Trámites ACIIS pendientes |
| `GET /api/reclamos` | Resumen de reclamos |
| `GET /api/reclamos-detalle?dia=YYYY-MM-DD&cuadrilla=X` | Detalle filtrado |
| `GET /api/bodega/instalados` | Materiales instalados |
| `GET /api/bodega/retirados` | Materiales retirados |
| `GET /api/bodega/cuadrillas` | Cuadrillas activas |
| `GET /api/bodega/resumen` | Resumen de bodega |
| `GET /api/bodega/catalogos` | Catálogos de materiales |

## 🏗️ Arquitectura

```
┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│  Cloudflare   │────▶│  api_server  │────▶│ gestion_medidores.db │
│   Tunnel      │     │  (Python)    │     │      (SQLite)        │
└──────────────┘     └──────┬───────┘     └──────────────────────┘
                            │
                    ┌───────▼────────┐
                    │  HTML/JS/CSS   │
                    │  Dashboards    │
                    └────────────────┘
```

## 🚀 Despliegue

Corre en **Termux + PRoot** sobre Android con **runsv** (puerto 8080):

```bash
# Iniciar
sv start servidor_web

# Ver logs
sv status servidor_web
tail -f /data/data/com.termux/files/usr/var/log/servidor_web.log
```

### Requisitos

- Python 3.10+
- `pandas`, `numpy`, `openpyxl`

### Configuración

No requiere `.env` propio — lee directamente de `gestion_medidores.db` en la ruta configurada dentro de `api_server.py`.

## 📂 Estructura

```
📁 public_html/
 ┣━ api_server.py           ← 🚀 Servidor HTTP + APIs
 ┣━ index.html              ← 🏠 Página principal
 ┣━ bodega.html             ← 🏭 Dashboard bodega
 ┣━ ordenes-sap.html        ← 🏗️ Dashboard SAP
 ┣━ tramites-aciis.html     ← 📋 Dashboard ACIIS
 ┣━ reclamos.html           ← 📞 Dashboard RECL
 ┗━ server-ecosystem.html   ← 🖥️ Estado servidores
```

## 🔗 Relacionados

- **Bot principal:** [`salchipapabot`](https://github.com/mikelecuadorian/salchipapabot)
- **Infraestructura:** Tablet Android + Termux + Cloudflare Tunnel
- **Exposición pública:** Cloudflare Tunnel (`ecosistema.salchipapabot.cc.cd` → `localhost:8080`)

---

*Proyecto personal — LaCostaTech 🇪🇨*
