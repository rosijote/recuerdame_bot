import json
import os
import sys
import requests
from datetime import datetime
from playwright.sync_api import sync_playwright

URL = "https://gestiona.comunidad.madrid/ctac_cita/registro#"
SERVICIO = "Preparación Trámites Jura de Nacionalidad"
MAX_MESES = 36
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]

VER = len(sys.argv) > 1 and sys.argv[1] == "ver"

# Token y chat id: primero variables de entorno (GitHub Actions), si no config.json (PC local)
if os.environ.get("TELEGRAM_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"):
    cfg = {"token": os.environ["TELEGRAM_TOKEN"], "chat_id": os.environ["TELEGRAM_CHAT_ID"]}
else:
    with open("config.json", encoding="utf-8") as f:
        cfg = json.load(f)


def telegram(texto):
    r = requests.post(
        f"https://api.telegram.org/bot{cfg['token']}/sendMessage",
        data={"chat_id": cfg["chat_id"], "text": texto},
        timeout=30,
    )
    print("Telegram:", r.status_code)
    if r.status_code != 200:
        print(r.text)


def leer_estado():
    try:
        with open("estado.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"disponibles": {}, "fallos": 0}


def guardar_estado(e):
    with open("estado.json", "w", encoding="utf-8") as f:
        json.dump(e, f, ensure_ascii=False, indent=2)


def es_disponible(d):
    return d["title"].strip().lower() == "día disponible"


JS_DIAS = """els => els.map(e => ({
    cls: e.className, title: e.title || "",
    dia: (e.querySelector('a') || e).textContent.trim(),
    mes: e.dataset.month, anio: e.dataset.year}))"""


def revisar():
    disponibles = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not VER)
        page = browser.new_context().new_page()
        page.set_default_timeout(30000)
        page.goto(URL)
        page.get_by_role("link", name="SOLICITAR CITA").click()
        page.select_option("#combo1", "705")
        page.select_option("#combo2", "1202")
        page.wait_for_timeout(1500)
        try:
            page.select_option("#comboServicios", label=SERVICIO)
        except Exception:
            pass
        page.get_by_role("button", name="Continuar").click()
        page.wait_for_selector("#datepicker .ui-datepicker-calendar")

        for i in range(MAX_MESES):
            dias = page.eval_on_selector_all("#datepicker td.diaCalendario", JS_DIAS)
            if VER:
                tipos = {}
                for d in dias:
                    k = (d["cls"].strip(), d["title"])
                    tipos[k] = tipos.get(k, 0) + 1
                titulo = page.inner_text("#datepicker .ui-datepicker-title").replace("\n", " ")
                print(f"\n== {titulo} ==")
                for k, n in tipos.items():
                    print(f"  {n:2d} x clase='{k[0]}' | title='{k[1]}'")

            libres = [d for d in dias if es_disponible(d)]
            for d in libres:
                clave = f"{MESES[int(d['mes'])].capitalize()} {d['anio']}"
                disponibles.setdefault(clave, []).append(int(d["dia"]))

            if i > 0 and dias and all("fuera" in d["title"].lower() for d in dias):
                break  # fin del rango de calendario

            siguiente = page.locator("#datepicker .ui-datepicker-next")
            if siguiente.count() == 0 or "ui-state-disabled" in (siguiente.get_attribute("class") or ""):
                break
            siguiente.click()
            page.wait_for_timeout(700)

        browser.close()
    return disponibles


def main():
    estado = leer_estado()
    try:
        disponibles = revisar()
    except Exception as e:
        estado["fallos"] = estado.get("fallos", 0) + 1
        print("Error:", e)
        if estado["fallos"] == 3:
            telegram("⚠️ El vigilante de citas ha fallado 3 veces seguidas. Puede que la página haya cambiado o que bloquee las conexiones.")
        guardar_estado(estado)
        return

    estado["fallos"] = 0
    anteriores = estado.get("disponibles", {})
    print(datetime.now().strftime("%d/%m/%Y %H:%M"), "-> disponibles:", disponibles or "ninguno")

    nuevos = {m: [x for x in dias if x not in anteriores.get(m, [])] for m, dias in disponibles.items()}
    nuevos = {m: d for m, d in nuevos.items() if d}
    if nuevos:
        lineas = [f"{mes}: {', '.join(str(x) for x in sorted(dias))}" for mes, dias in nuevos.items()]
        telegram("📅 Nuevas citas de Jura de Nacionalidad:\n" + "\n".join(lineas) + "\n\n" + URL)

    estado["disponibles"] = disponibles
    guardar_estado(estado)


main()
