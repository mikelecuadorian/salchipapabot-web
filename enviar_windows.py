#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
enviar_windows.py — Escribe un mensaje en el buzón que lee el Hermes de Windows.

Uso (desde la tablet):
  python3 enviar_windows.py --asunto "Ficha contrato" --cuerpo "Adjunto la ficha"
  python3 enviar_windows.py --asunto "Aviso" --cuerpo "..." --archivo /ruta/x.pdf

El mensaje queda en el buzón JSONL que Windows lee por:
  GET https://ecosistema.salchipapabot.cc.cd/api/buzon?desde=N

Con --archivo, el archivo se copia a public_html/buzon_archivos/ y el mensaje
incluye una URL pública para que Windows lo descargue.
"""
import argparse
import json
import os
import shutil
import sys
import time

BUZON = "/data/data/com.termux/files/home/.config/buzon_windows.jsonl"
PUBLIC = "/data/data/com.termux/files/home/public_html"
ARCH_DIR = os.path.join(PUBLIC, "buzon_archivos")
BASE_URL = "https://ecosistema.salchipapabot.cc.cd"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asunto", required=True)
    ap.add_argument("--cuerpo", default="")
    ap.add_argument("--archivo", action="append", default=[],
                    help="ruta de archivo a publicar (repetible)")
    ap.add_argument("--de", default="tablet")
    a = ap.parse_args()

    adjuntos = []
    if a.archivo:
        os.makedirs(ARCH_DIR, exist_ok=True)
        for ruta in a.archivo:
            if not os.path.exists(ruta):
                print(f"⚠️ no existe: {ruta}", file=sys.stderr)
                continue
            # nombre único para no pisar
            base = os.path.basename(ruta)
            sello = time.strftime("%Y%m%d_%H%M%S")
            destino = os.path.join(ARCH_DIR, f"{sello}_{base}")
            shutil.copy2(ruta, destino)
            os.chmod(destino, 0o644)
            adjuntos.append({
                "nombre": base,
                "url": f"{BASE_URL}/buzon_archivos/{os.path.basename(destino)}",
                "bytes": os.path.getsize(destino),
            })

    entrada = {
        "de": a.de,
        "asunto": a.asunto,
        "cuerpo": a.cuerpo,
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    if adjuntos:
        entrada["adjuntos"] = adjuntos

    os.makedirs(os.path.dirname(BUZON), exist_ok=True)
    with open(BUZON, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entrada, ensure_ascii=False) + "\n")

    # contar total para informar el id
    with open(BUZON, encoding="utf-8") as fh:
        n = sum(1 for _ in fh)
    print(f"✅ mensaje #{n} en el buzón")
    print(f"   asunto: {a.asunto}")
    if adjuntos:
        for x in adjuntos:
            print(f"   📎 {x['nombre']} ({x['bytes']} bytes)")
            print(f"      {x['url']}")


if __name__ == "__main__":
    main()
