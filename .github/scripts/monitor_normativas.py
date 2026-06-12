"""
SOLUM — Monitor diario de normativas Lima
Corre cada día a las 8:00 AM Lima vía GitHub Actions.
Fuentes: El Peruano · MVCS · IMP Lima

Flujo completo:
  1. Scraping 3 fuentes → pre-filtrado por entidad/tipo/keyword
     El Peruano: descarga PDF de Índice Quincenal (diariooficial.elperuano.pe/Normas/Indices)
                 → parsea con pdfminer → filtra secciones relevantes
  2. Claude evalúa relevancia + genera resumen (1 llamada batch)
  3. Para relevancia=alta: Claude fetcha texto completo + genera borrador SOLUM
  4. Supabase alertas_normativas ← guardar (con texto_procesado si disponible)
  5. GitHub Issue ← notificación con borrador incluido
"""

import os
import re
import io
import json
import logging
import datetime
import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateparser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("monitor_log.txt", encoding="utf-8"),
    ],
)
log = logging.getLogger("solum_monitor")

# ── Credenciales desde environment ───────────────────────────────────────────
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY", "")
GITHUB_TOKEN   = os.environ.get("GITHUB_TOKEN", "")
GITHUB_REPO    = os.environ.get("GITHUB_REPOSITORY", "eosterling-lgtm/FACTIS")
RESEND_KEY     = os.environ.get("RESEND_API_KEY", "")
NOTIFY_EMAIL   = "eosterling@grupoosterling.com"

HOY  = datetime.date.today()
AYER = HOY - datetime.timedelta(days=1)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SOLUM-Monitor/1.0; "
        "+https://github.com/eosterling-lgtm/FACTIS)"
    )
}

# ── Entidades relevantes ──────────────────────────────────────────────────────
ENTIDADES_OBJETIVO = [
    "VIVIENDA, CONSTRUCCION Y SANEAMIENTO",
    "MUNICIPALIDAD METROPOLITANA DE LIMA",
    "MUNICIPALIDAD DISTRITAL DE MIRAFLORES",
    "MUNICIPALIDAD DISTRITAL DE SAN ISIDRO",
    "MUNICIPALIDAD DISTRITAL DE SANTIAGO DE SURCO",
    "MUNICIPALIDAD DISTRITAL DE SAN BORJA",
    "MUNICIPALIDAD DISTRITAL DE JESUS MARIA",
    "MUNICIPALIDAD DISTRITAL DE LA VICTORIA",
    "MUNICIPALIDAD DISTRITAL DE VILLA EL SALVADOR",
    "MUNICIPALIDAD DISTRITAL DE SAN JUAN DE LURIGANCHO",
    "MUNICIPALIDAD DISTRITAL DE LURIN",
    "MUNICIPALIDAD DISTRITAL DE LINCE",
    "MUNICIPALIDAD DISTRITAL DE MAGDALENA DEL MAR",
    "MUNICIPALIDAD DISTRITAL DE SURQUILLO",
    "MUNICIPALIDAD DISTRITAL DE CALLAO",
    "MUNICIPALIDAD DISTRITAL DE SAN MARTIN DE PORRES",
    "MUNICIPALIDAD DISTRITAL DE ATE",
    "MUNICIPALIDAD DISTRITAL DE LA MOLINA",
    "SUNARP",
    "MINISTERIO DE TRANSPORTES Y COMUNICACIONES",
    "INSTITUTO METROPOLITANO DE PLANIFICACION",
]

TIPOS_NORMA_OBJETIVO = [
    "ORDENANZA", "DECRETO SUPREMO", "RESOLUCION MINISTERIAL",
    "DECRETO DE ALCALDIA", "RESOLUCION DE ALCALDIA", "RESOLUCION DIRECTORAL",
]

KEYWORDS_RELEVANTES = [
    "edificacion", "urbanistic", "zonificac", "habilitacion urbana",
    "parametros urbanisticos", "reglamento nacional", "retiros", "estacionamiento",
    "altura", "coeficiente de edificacion", "uso de suelo", "indice de usos",
    "licencia de edificacion", "licencia de construccion", "industrial",
    "logistic", "almacen", "costos de construccion", "valor unitario",
    "plan de desarrollo urbano", "planmet", "impacto vial", "seguridad en edificaciones",
    "accesibilidad", "sismorresistente", "suelos y cimentaciones",
]


# ══════════════════════════════════════════════════════════════════════════════
# FASE 1 — SCRAPING
# ══════════════════════════════════════════════════════════════════════════════

# Secciones del Índice El Peruano que interesan a SOLUM
# Estas cadenas aparecen como encabezados de sección en el PDF del índice
SECCIONES_OBJETIVO = [
    "VIVIENDA",
    "VIVIENDA, CONSTRUCCION Y SANEAMIENTO",
    "MUNICIPALIDAD METROPOLITANA DE LIMA",
    "INSTITUTO METROPOLITANO DE PLANIFICACION",
    "MUNICIPALIDAD DISTRITAL DE MIRAFLORES",
    "MUNICIPALIDAD DISTRITAL DE SAN ISIDRO",
    "MUNICIPALIDAD DISTRITAL DE SANTIAGO DE SURCO",
    "MUNICIPALIDAD DISTRITAL DE SAN BORJA",
    "MUNICIPALIDAD DISTRITAL DE JESUS MARIA",
    "MUNICIPALIDAD DISTRITAL DE LA VICTORIA",
    "MUNICIPALIDAD DISTRITAL DE VILLA EL SALVADOR",
    "MUNICIPALIDAD DISTRITAL DE SAN JUAN DE LURIGANCHO",
    "MUNICIPALIDAD DISTRITAL DE LURIN",
    "MUNICIPALIDAD DISTRITAL DE LINCE",
    "MUNICIPALIDAD DISTRITAL DE MAGDALENA DEL MAR",
    "MUNICIPALIDAD DISTRITAL DE SURQUILLO",
    "MUNICIPALIDAD DISTRITAL DE CALLAO",
    "MUNICIPALIDAD DISTRITAL DE SAN MARTIN DE PORRES",
    "MUNICIPALIDAD DISTRITAL DE ATE",
    "MUNICIPALIDAD DISTRITAL DE LA MOLINA",
    "SUNARP",
    "MINISTERIO DE TRANSPORTES",
]

# Nombres de mes en español para construir fechas desde el índice (e.g. "Lun 4")
MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
    5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
    9: "setiembre", 10: "octubre", 11: "noviembre", 12: "diciembre",
}


def _descargar_pdf_indice(mes: int, anio: int, quincena: int) -> bytes | None:
    """
    Descarga el PDF del Índice Quincenal de El Peruano para el mes/año indicado.
    quincena=1 → primera quincena (días 1-15), quincena=2 → segunda (días 16-fin).

    Flujo:
    1. Obtiene la página de Índices y extrae los enlaces PDF del mes/año solicitado.
    2. Si no encuentra en HTML (sitio dinámico), intenta URL directa por convención
       de nombre de archivo del El Peruano: IN{YYYYMM}{15|DD_fin}.pdf
    """
    base = "https://diariooficial.elperuano.pe"
    indices_url = f"{base}/Normas/Indices"
    nombre_mes = MESES_ES.get(mes, "").lower()

    # ── Intento 1: scraping de la página de Índices ───────────────────────────
    try:
        resp = requests.get(indices_url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Buscar todos los enlaces que contengan el año, el mes y sean PDF
        for a in soup.find_all("a", href=True):
            href  = a["href"]
            texto = (a.get_text(" ", strip=True) + " " + href).lower()
            if (
                str(anio) in href
                and nombre_mes in texto
                and ".pdf" in href.lower()
            ):
                # Distinguir quincena por "primera" / "segunda" o por el día en el href
                es_primera = (
                    "primera" in texto
                    or re.search(r"IN\d{6}(0[1-9]|1[0-5])", href)
                )
                es_segunda = (
                    "segunda" in texto
                    or re.search(r"IN\d{6}(1[6-9]|[23]\d)", href)
                )
                if (quincena == 1 and es_primera) or (quincena == 2 and es_segunda):
                    pdf_url = href if href.startswith("http") else base + href
                    log.info(f"[El Peruano] PDF hallado en página: {pdf_url}")
                    r2 = requests.get(pdf_url, headers=HEADERS, timeout=60)
                    r2.raise_for_status()
                    return r2.content
    except Exception as e:
        log.debug(f"[El Peruano] Scraping índices: {e}")

    # ── Intento 2: URL directa por convención de nombre ──────────────────────
    # Primera quincena → día 15, segunda → último día del mes
    import calendar
    dia = 15 if quincena == 1 else calendar.monthrange(anio, mes)[1]
    candidatos = [
        f"{base}/pdf/0177/IN{anio:04d}{mes:02d}{dia:02d}.pdf",
        f"{base}/Ediciones/PDF/IN{anio:04d}{mes:02d}{dia:02d}.pdf",
        f"{base}/normas/indices/IN{anio:04d}{mes:02d}{dia:02d}.pdf",
    ]
    for pdf_url in candidatos:
        try:
            r = requests.get(pdf_url, headers=HEADERS, timeout=60)
            if r.status_code == 200 and r.headers.get("Content-Type", "").startswith("application/pdf"):
                log.info(f"[El Peruano] PDF directo OK: {pdf_url}")
                return r.content
        except Exception:
            pass

    log.warning(f"[El Peruano] No se pudo descargar PDF índice {mes}/{anio} Q{quincena}")
    return None


def _parsear_indice_pdf(pdf_bytes: bytes, mes: int, anio: int) -> list[dict]:
    """
    Parsea el PDF del Índice Quincenal y extrae las normas de las secciones objetivo.
    Retorna lista de dicts con campos estándar del monitor.

    Estructura del PDF (observada en IN20260515.pdf):
      - Encabezados de sección en MAYÚSCULAS (e.g. "vivienda, construccion...")
      - Bullet ● seguido del tipo, número y título de la norma
      - Línea termina con número de página y día abreviado + número (e.g. "Lun 4")
    """
    try:
        from pdfminer.high_level import extract_text
    except ImportError:
        log.error("[El Peruano] pdfminer.six no instalado")
        return []

    try:
        text = extract_text(io.BytesIO(pdf_bytes))
    except Exception as e:
        log.warning(f"[El Peruano] Error extrayendo texto del PDF: {e}")
        return []

    resultados = []
    seccion_actual = ""
    en_seccion_objetivo = False

    # Día abreviado → número (para construir fecha de publicación)
    dias_abrev = {
        "lun": "lunes", "mar": "martes", "mié": "miércoles", "mie": "miércoles",
        "jue": "jueves", "vie": "viernes", "sáb": "sábado", "sab": "sábado",
        "dom": "domingo",
    }

    def _fecha_desde_dia(dia_num: int) -> str:
        """Construye fecha YYYY-MM-DD a partir del día del mes."""
        try:
            return datetime.date(anio, mes, dia_num).isoformat()
        except Exception:
            return f"{anio}-{mes:02d}-{dia_num:02d}"

    # Normalizar texto: colapsar espacios, quitar guiones de quiebre de línea
    text = re.sub(r"-\s*\n\s*", "", text)
    text = re.sub(r"\s+", " ", text)

    # Dividir en "bloques" por cada bullet ●
    # Primero identificar la sección por encabezado (texto MAYÚSCULA sin bullet)
    # Patrón bullet: ● seguido del tipo de norma + número + título + página + día
    patron_bullet = re.compile(
        r"●\s*"
        r"((?:R\.M\.|R\.S\.|R\.D\.|R\.J\.|D\.S\.|D\.U\.|Ley|Ord\.|Acuerdo|Decreto|Resolución|Resolucion)"
        r"[^●]{10,400?})"
        r"\s+(\d{1,3})\s+"          # página
        r"([A-ZÁÉÍÓÚa-záéíóú]{3})\s+(\d{1,2})",  # día abrev + número
        re.IGNORECASE | re.DOTALL,
    )

    # Procesar línea a línea para detectar cambios de sección
    lineas = text.split("  ")  # el PDF usa espacios dobles como separador de bloques
    buffer = ""

    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue

        # Detectar cambio de sección: línea en MAYÚSCULAS sin bullet, sin números al inicio
        linea_upper = linea.upper()
        es_encabezado = (
            linea_upper == linea
            and len(linea) > 5
            and not linea.startswith("●")
            and not re.match(r"^\d", linea)
            and not linea.startswith("=")
        )
        if es_encabezado:
            seccion_actual = linea_upper.strip()
            en_seccion_objetivo = any(
                obj in seccion_actual for obj in SECCIONES_OBJETIVO
            )
            continue

        buffer += " " + linea

    # Ahora parsear el texto completo buscando secciones y bullets
    # Re-procesar el texto completo con context de sección
    secciones_encontradas: dict[str, str] = {}

    # Buscar todos los encabezados de sección objetivo en el texto completo
    for seccion in SECCIONES_OBJETIVO:
        idx = text.upper().find(seccion)
        if idx != -1:
            # Extraer texto desde este encabezado hasta el siguiente encabezado conocido
            fin = len(text)
            for otra in SECCIONES_OBJETIVO:
                if otra == seccion:
                    continue
                idx2 = text.upper().find(otra, idx + len(seccion))
                if 0 < idx2 < fin:
                    fin = idx2
            bloque = text[idx:fin]
            secciones_encontradas[seccion] = bloque
            log.info(f"[El Peruano] Sección '{seccion}': {len(bloque)} chars")

    # Parsear bullets de cada sección
    for seccion, bloque in secciones_encontradas.items():
        entidad = seccion.title()
        for m in patron_bullet.finditer(bloque):
            titulo_raw = m.group(1).strip()
            dia_abrev  = m.group(3).lower()[:3]
            dia_num    = int(m.group(4))

            # Limpiar título: quitar número de página final si quedó pegado
            titulo = re.sub(r"\s+\d{1,3}\s*$", "", titulo_raw).strip()
            titulo = re.sub(r"\s{2,}", " ", titulo)

            fecha_pub = _fecha_desde_dia(dia_num)
            tipo_norma = _extraer_tipo(titulo.upper())

            # URL de búsqueda como fallback (no tenemos URL directa desde el índice)
            num_match = re.search(r"N[°º\.]\s*([\d\-]+)", titulo)
            num_norma = num_match.group(1).replace("-", "") if num_match else ""
            url_busqueda = (
                f"https://busquedas.elperuano.pe/normaslegales/"
                + re.sub(r"\s+", "-", titulo[:60].lower())
                + f"-{num_norma}/"
                if num_norma else
                "https://diariooficial.elperuano.pe/Normas/Indices"
            )

            resultados.append({
                "fuente":            "el_peruano_indice",
                "titulo":            titulo,
                "url":               url_busqueda,
                "fecha_publicacion": fecha_pub,
                "entidad":           entidad,
                "tipo_norma":        tipo_norma,
                "texto_raw":         titulo[:800],
            })

    log.info(f"[El Peruano] {len(resultados)} normas parseadas del PDF")
    return resultados


def buscar_el_peruano() -> list[dict]:
    """
    Descarga y parsea los Índices Quincenales del Diario Oficial El Peruano.
    URL: https://diariooficial.elperuano.pe/Normas/Indices
    Revisa las dos quincenas del mes actual + la quincena que incluye AYER.
    """
    resultados: list[dict] = []
    mes_actual = HOY.month
    anio_actual = HOY.year
    mes_anterior = (HOY.replace(day=1) - datetime.timedelta(days=1)).month
    anio_anterior = (HOY.replace(day=1) - datetime.timedelta(days=1)).year

    # Determinar qué quincenas revisar según el día de hoy
    quincenas_a_revisar = []
    if HOY.day <= 16:
        # Primeros días del mes: revisar Q1 actual + Q2 mes anterior
        quincenas_a_revisar = [
            (mes_actual,   anio_actual,   1),
            (mes_anterior, anio_anterior, 2),
        ]
    else:
        # Segunda mitad: revisar Q1 y Q2 del mes actual
        quincenas_a_revisar = [
            (mes_actual, anio_actual, 1),
            (mes_actual, anio_actual, 2),
        ]

    normas_vistas: set[str] = set()  # dedup por título normalizado

    for mes, anio, quincena in quincenas_a_revisar:
        log.info(f"[El Peruano] Descargando índice {mes}/{anio} Q{quincena}")
        pdf_bytes = _descargar_pdf_indice(mes, anio, quincena)
        if not pdf_bytes:
            log.warning(f"[El Peruano] Sin PDF para {mes}/{anio} Q{quincena} — saltando")
            continue

        normas = _parsear_indice_pdf(pdf_bytes, mes, anio)
        for n in normas:
            key = re.sub(r"\s+", " ", n["titulo"][:100].upper())
            if key not in normas_vistas:
                normas_vistas.add(key)
                resultados.append(n)

    # Filtrar: solo normas publicadas ayer o hoy (evitar reprocesar todo el mes)
    fechas_validas = {str(AYER), str(HOY)}
    resultados = [r for r in resultados if r["fecha_publicacion"] in fechas_validas]

    log.info(f"[El Peruano] {len(resultados)} normas relevantes de ayer/hoy")
    return resultados


def buscar_mvcs() -> list[dict]:
    """Revisa la sección de normativas del MVCS."""
    resultados = []
    log.info("[MVCS] Revisando normativas recientes")

    for url in [
        "https://www.gob.pe/institucion/vivienda/normas-legales",
        "https://www.gob.pe/institucion/vivienda/decretos",
    ]:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for item in soup.find_all(
                ["article", "li", "div"],
                class_=re.compile(r"norma|decreto|resolucion|item", re.I)
            ):
                texto = item.get_text(" ", strip=True)
                fecha_enc = _extraer_fecha(texto)
                if not fecha_enc:
                    continue
                try:
                    if dateparser.parse(fecha_enc).date() < AYER:
                        continue
                except Exception:
                    continue

                titulo_tag = item.find(["h3", "h4", "h5", "a", "strong"])
                titulo = titulo_tag.get_text(strip=True) if titulo_tag else texto[:200]
                link_tag = item.find("a", href=True)
                item_url = link_tag["href"] if link_tag else url

                resultados.append({
                    "fuente":            "mvcs",
                    "titulo":            titulo,
                    "url":               item_url,
                    "fecha_publicacion": str(AYER),
                    "entidad":           "MVCS",
                    "tipo_norma":        _extraer_tipo(texto.upper()),
                    "texto_raw":         texto[:800],
                })
        except Exception as e:
            log.warning(f"[MVCS] Error en {url}: {e}")

    log.info(f"[MVCS] {len(resultados)} pre-filtradas")
    return resultados


def buscar_imp() -> list[dict]:
    """Revisa publicaciones del IMP (zonificación, PLANMET)."""
    resultados = []
    log.info("[IMP] Revisando publicaciones recientes")

    try:
        resp = requests.get("https://imp.gob.pe/normativas/", headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for item in soup.find_all(["article", "li", "div", "tr"]):
            texto = item.get_text(" ", strip=True)
            if len(texto) < 20:
                continue
            fecha_enc = _extraer_fecha(texto)
            es_reciente = False
            if fecha_enc:
                try:
                    es_reciente = dateparser.parse(fecha_enc).date() >= AYER
                except Exception:
                    pass
            kw_match = any(kw in texto.lower() for kw in KEYWORDS_RELEVANTES)
            if not (es_reciente or kw_match):
                continue

            titulo_tag = item.find(["h3", "h4", "a", "strong"])
            titulo = titulo_tag.get_text(strip=True) if titulo_tag else texto[:200]
            link_tag = item.find("a", href=True)
            item_url = link_tag["href"] if link_tag else "https://imp.gob.pe/normativas/"
            if item_url and not item_url.startswith("http"):
                item_url = "https://imp.gob.pe" + item_url

            if titulo and len(titulo) > 10:
                resultados.append({
                    "fuente":            "imp",
                    "titulo":            titulo,
                    "url":               item_url,
                    "fecha_publicacion": str(AYER),
                    "entidad":           "IMP Lima",
                    "tipo_norma":        _extraer_tipo(texto.upper()),
                    "texto_raw":         texto[:800],
                })
    except Exception as e:
        log.warning(f"[IMP] Error: {e}")

    # Deduplicar por título
    vistos: set = set()
    unicos = []
    for r in resultados:
        if r["titulo"] not in vistos:
            vistos.add(r["titulo"])
            unicos.append(r)

    log.info(f"[IMP] {len(unicos)} pre-filtradas")
    return unicos


# ══════════════════════════════════════════════════════════════════════════════
# FASE 2 — EVALUACIÓN CLAUDE (batch)
# ══════════════════════════════════════════════════════════════════════════════

def evaluar_relevancia_claude(normas: list[dict]) -> list[dict]:
    """Claude evalúa relevancia en batch. Retorna solo las relevantes."""
    if not normas or not ANTHROPIC_KEY:
        log.warning("Sin normas o sin API key — skip evaluación Claude")
        return normas

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, max_retries=0, timeout=90.0)

    titulos_json = json.dumps(
        [{"id": i, "titulo": n["titulo"], "entidad": n.get("entidad", "")}
         for i, n in enumerate(normas)],
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""Eres experto en normativa urbanística y edificatoria de Lima, Perú.

SOLUM es una herramienta de pre-factibilidad inmobiliaria que analiza:
- Parámetros urbanísticos: altura, retiros, COS, CUS, área libre, estacionamiento
- Zonificación y usos de suelo (residencial RDM/RDA, industrial I2/I3, comercial)
- RNE (A.010, A.020, A.060, E.030, E.050)
- Habilitaciones urbanas
- Costos de construcción (valores oficiales MVCS)
- Impacto vial (EIV) y accesibilidad
- Normativa registral SUNARP relacionada a edificaciones

Evalúa cada norma. Para cada una responde si es relevante y con qué nivel.

CRITERIOS:
- alta: cambia parámetros numéricos que SOLUM usa (estacionamientos, alturas, áreas libres, COS, CUS, retiros, costos oficiales, densidad, lote mínimo, usos permitidos)
- media: afecta procesos inmobiliarios (licencias, registros, habilitaciones, impacto vial)
- baja: marco general sin impacto en parámetros concretos de SOLUM
- irrelevante: no relacionado con edificaciones ni inmobiliario

JSON exacto de respuesta:
{{"resultados": [
  {{"id": 0, "relevante": true, "relevancia": "alta|media|baja",
    "categorias": ["zonificacion","rne","costos","industrial","residencial","registral","vial","urbanismo"],
    "resumen": "una línea concisa: qué parámetro cambia y en cuánto si es posible"}}
]}}

Normas a evaluar:
{titulos_json}"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            evaluaciones = {r["id"]: r for r in data.get("resultados", [])}
            for i, norma in enumerate(normas):
                ev = evaluaciones.get(i, {})
                norma["relevante"]  = ev.get("relevante", False)
                norma["relevancia"] = ev.get("relevancia", "baja")
                norma["categorias"] = ev.get("categorias", [])
                norma["resumen"]    = ev.get("resumen", "")
        log.info(f"[Claude-eval] {len(normas)} evaluadas")
    except Exception as e:
        log.warning(f"[Claude-eval] Error: {e} — modo conservador (guarda todo)")
        for norma in normas:
            norma["relevante"]  = True
            norma["relevancia"] = "media"
            norma["categorias"] = []
            norma["resumen"]    = ""

    return [n for n in normas if n.get("relevante", False)]


# ══════════════════════════════════════════════════════════════════════════════
# FASE 3 — GENERACIÓN DE BORRADOR NORMATIVO (solo relevancia=alta)
# ══════════════════════════════════════════════════════════════════════════════

def _fetch_full_text(url: str, max_chars: int = 10_000) -> str:
    """Fetcha texto completo de la URL del documento normativo."""
    if not url or not url.startswith("http"):
        return ""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        # Eliminar elementos no-textuales
        for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
            tag.decompose()
        text = soup.get_text(" ", strip=True)
        # Comprimir espacios múltiples
        text = re.sub(r"\s{3,}", "  ", text)
        return text[:max_chars]
    except Exception as e:
        log.debug(f"[fetch_full_text] No se pudo obtener {url}: {e}")
        return ""


def generar_borrador_normativo(norma: dict, full_text: str) -> tuple[str, str, str]:
    """
    Claude genera texto normativo SOLUM desde la norma detectada.
    Retorna (texto_procesado, codigo_propuesto, tipo_normativa_solum).
    Solo se llama para relevancia=alta.
    """
    if not ANTHROPIC_KEY:
        return "", "", ""

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, max_retries=0, timeout=120.0)

    fuente_texto = full_text.strip() if full_text else ""
    fuente_label = "TEXTO COMPLETO DEL DOCUMENTO" if fuente_texto else "RESUMEN DEL MONITOR"
    fuente_contenido = fuente_texto if fuente_texto else (
        f"Título: {norma['titulo']}\n"
        f"Entidad: {norma.get('entidad','')}\n"
        f"Tipo: {norma.get('tipo_norma','')}\n"
        f"Resumen: {norma.get('resumen','')}\n"
        f"Texto raw: {norma.get('texto_raw','')}"
    )

    prompt = f"""Eres el motor normativo de SOLUM, herramienta de pre-factibilidad inmobiliaria para Lima, Perú.

Se detectó esta nueva normativa de ALTA relevancia para SOLUM:
- Título: {norma['titulo']}
- Entidad: {norma.get('entidad', '')}
- Tipo: {norma.get('tipo_norma', '')}
- Fecha publicación: {norma.get('fecha_publicacion', '')}
- Categorías SOLUM: {', '.join(norma.get('categorias', []))}
- Resumen del monitor: {norma.get('resumen', '')}

{fuente_label}:
---
{fuente_contenido[:7000]}
---

TAREA: Genera el archivo de normativa SOLUM en formato .txt estructurado.
SOLUM carga este archivo y Claude lo usa directamente en sus prompts de análisis de cabida.

FORMATO EXACTO (respeta la estructura):

# [NOMBRE OFICIAL DE LA NORMA]
# Entidad: [entidad exacta]
# Tipo: [Ordenanza / Decreto Supremo / Resolución Ministerial / etc.]
# Fecha publicación: [YYYY-MM-DD]
# Fecha vigencia: [YYYY-MM-DD o "desde publicación"]
# Código SOLUM: [ver instrucciones abajo]
# Estado: ACTIVO

## ALCANCE

[Qué regula esta norma y a quién aplica — 2-4 líneas]

## PARÁMETROS URBANÍSTICOS

[Extraer TODOS los parámetros numéricos. Usar este formato por parámetro:
PARÁMETRO: valor — condición aplicable — artículo de referencia
Ejemplos:
ESTACIONAMIENTO RESIDENCIAL: 1 und/vivienda — zonas I2/I3 — Art. 8
ALTURA MÁXIMA: 1.5(a+r) — zona CM sin límite específico de pisos — Art. 5
ÁREA LIBRE MÍNIMA: 30% — uso residencial multifamiliar — Art. 12
Si no hay valor numérico, escribir: [VERIFICAR DOCUMENTO OFICIAL — Art. X]]

## ZONIFICACIONES APLICABLES

[Listar zonas: RDM, RDA, CZ, CE, CM, I2, I3, etc. Una por línea con descripción breve]

## DISTRITOS / ÁMBITO TERRITORIAL

[Distritos específicos o área metropolitana de Lima que cubre]

## USOS COMPATIBLES / INCOMPATIBLES

[Si la norma regula usos de suelo — dejar vacío con [NO APLICA] si no]

## MODIFICACIONES A NORMAS ANTERIORES

[Qué normas deroga o modifica. Formato: DEROGA: Ordenanza N°XXX (campo Y)]

## NOTAS ESPECIALES PARA SOLUM

[Fórmulas de cálculo especiales, excepciones, casos edge que Claude debe conocer]

## BASE LEGAL

[Artículos específicos más importantes con su contenido resumido]

---
Generado automáticamente por SOLUM Monitor — {norma.get('fecha_publicacion', '')}
REVISAR Y VALIDAR antes de activar en producción.

---

Para el código SOLUM:
- RIN distrital: rin_[distrito]_[año] (ej: rin_san_isidro_2024)
- Decreto Supremo MVCS: ds_[tema]_[año] (ej: ds_estacionamiento_2024)
- Ordenanza MML: ord_mml_[tema]_[año]
- RNE: rne_[seccion]_[año]

Para tipo_normativa_solum:
- "rin" si es reglamento interno de un distrito
- "ds" si es decreto supremo MVCS
- "rne" si modifica el RNE
- "ord" si es ordenanza municipal/metropolitana
- "config" si son parámetros de configuración general

Responde con este JSON:
{{"texto_procesado": "[CONTENIDO COMPLETO DEL ARCHIVO .txt]",
  "codigo_propuesto": "[codigo_solum]",
  "tipo_normativa_solum": "[rin|ds|rne|ord|config]"}}"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            texto  = data.get("texto_procesado", "").strip()
            codigo = data.get("codigo_propuesto", "").strip()
            tipo   = data.get("tipo_normativa_solum", "ord").strip()
            if texto:
                log.info(f"[generar_borrador] ✓ {len(texto)} chars | código: {codigo}")
                return texto, codigo, tipo
    except Exception as e:
        log.warning(f"[generar_borrador] Error: {e}")

    return "", "", ""


def enriquecer_normas_altas(normas: list[dict]) -> list[dict]:
    """
    Para normas de relevancia=alta: fetcha texto completo y genera borrador.
    Modifica las normas in-place añadiendo texto_procesado, codigo_propuesto.
    """
    altas = [n for n in normas if n.get("relevancia") == "alta"]
    if not altas:
        return normas

    log.info(f"[enriquecer] Generando borradores para {len(altas)} normas de alta relevancia")

    for norma in altas:
        url = norma.get("url", "")
        log.info(f"[enriquecer] Procesando: {norma['titulo'][:80]}")

        # 1. Intentar obtener texto completo
        full_text = _fetch_full_text(url)
        if full_text:
            log.info(f"[enriquecer] Texto obtenido: {len(full_text)} chars")
        else:
            log.info("[enriquecer] Sin texto completo — generando desde resumen")

        # 2. Generar borrador SOLUM
        texto, codigo, tipo = generar_borrador_normativo(norma, full_text)
        norma["texto_procesado"]     = texto
        norma["codigo_propuesto"]    = codigo
        norma["tipo_normativa_solum"] = tipo

    return normas


# ══════════════════════════════════════════════════════════════════════════════
# FASE 4 — PERSISTENCIA SUPABASE
# ══════════════════════════════════════════════════════════════════════════════

def guardar_alertas(normas: list[dict]) -> int:
    """Inserta normas relevantes en alertas_normativas. Evita duplicados."""
    if not normas or not SUPABASE_URL or not SUPABASE_KEY:
        return 0

    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    guardadas = 0

    for n in normas:
        # Dedup por título + fecha
        exist = (
            sb.table("alertas_normativas")
            .select("id")
            .eq("titulo", n["titulo"][:500])
            .eq("fecha_publicacion", n["fecha_publicacion"])
            .execute()
        )
        if exist.data:
            log.info(f"[guardar] Ya existe: {n['titulo'][:60]}")
            continue

        row = {
            "fecha_publicacion":   n["fecha_publicacion"],
            "entidad":             (n.get("entidad") or "")[:200],
            "tipo_norma":          (n.get("tipo_norma") or "")[:100],
            "titulo":              n["titulo"][:500],
            "resumen":             (n.get("resumen") or "")[:500],
            "url":                 (n.get("url") or "")[:500],
            "fuente":              (n.get("fuente") or "")[:50],
            "relevancia":          n.get("relevancia", "media"),
            "categorias":          n.get("categorias") or [],
            "procesado":           False,
            # Nuevos campos de borrador
            "texto_procesado":     n.get("texto_procesado") or None,
            "codigo_propuesto":    n.get("codigo_propuesto") or None,
            "tipo_normativa_solum": n.get("tipo_normativa_solum") or None,
        }

        try:
            sb.table("alertas_normativas").insert(row).execute()
            guardadas += 1
            tiene_borrador = "✓ borrador" if row["texto_procesado"] else "sin borrador"
            log.info(f"[guardar] ✓ {n['titulo'][:70]} [{tiene_borrador}]")
        except Exception as e:
            log.warning(f"[guardar] Error '{n['titulo'][:60]}': {e}")

    return guardadas


# ══════════════════════════════════════════════════════════════════════════════
# FASE 5 — NOTIFICACIÓN GITHUB ISSUE
# ══════════════════════════════════════════════════════════════════════════════

def crear_github_issue(normas: list[dict], total_revisadas: int) -> None:
    """
    Crea GitHub Issue con resumen de normas detectadas.
    Para normas de alta relevancia con borrador: incluye el texto procesado.
    GitHub envía email automático al owner del repositorio.
    """
    if not normas or not GITHUB_TOKEN:
        log.info("[issue] Sin normas nuevas o sin token — no se crea issue")
        return

    altas  = [n for n in normas if n.get("relevancia") == "alta"]
    medias = [n for n in normas if n.get("relevancia") == "media"]

    def _fila_md(n: dict) -> str:
        cats  = ", ".join(n.get("categorias") or []) or "—"
        url   = n.get("url", "")
        link  = f"[{n['titulo'][:90]}]({url})" if url else n["titulo"][:90]
        ent   = (n.get("entidad") or "")[:50]
        res   = (n.get("resumen") or "")[:120]
        borr  = "✅ Borrador listo" if n.get("texto_procesado") else "⬜ Requiere procesamiento manual"
        return f"| {link} | {ent} | {cats} | {res} | {borr} |"

    def _seccion_tabla(titulo: str, emoji: str, items: list[dict]) -> str:
        if not items:
            return ""
        header = (
            f"## {emoji} {titulo} ({len(items)})\n\n"
            "| Título | Entidad | Categorías | Resumen | Borrador SOLUM |\n"
            "|--------|---------|------------|---------|----------------|\n"
        )
        filas = "\n".join(_fila_md(n) for n in items)
        return header + filas + "\n"

    # Sección de borradores para activación rápida
    altas_con_borrador = [n for n in altas if n.get("texto_procesado")]
    seccion_borradores = ""
    if altas_con_borrador:
        borradores_md = ""
        for n in altas_con_borrador:
            borradores_md += f"""
<details>
<summary>📄 Borrador: {n['titulo'][:80]}</summary>

**Código propuesto:** `{n.get('codigo_propuesto','pendiente')}`
**Tipo:** `{n.get('tipo_normativa_solum','ord')}`

```
{n.get('texto_procesado','')[:3000]}
{'...(truncado)' if len(n.get('texto_procesado','')) > 3000 else ''}
```

> Para activar: Portfolio → Gestión de Normativas → botón **[✓ Activar en SOLUM]**

</details>
"""
        seccion_borradores = (
            f"\n## 🚀 Borradores listos para activación ({len(altas_con_borrador)})\n"
            + borradores_md
        )

    body = (
        f"# SOLUM Monitor — {len(normas)} normas relevantes\n\n"
        f"**Publicaciones del:** {AYER.strftime('%d/%m/%Y')}  \n"
        f"**Total revisadas:** {total_revisadas}  \n"
        f"**Relevantes:** {len(normas)} ({len(altas)} alta · {len(medias)} media)  \n"
        f"**Borradores SOLUM generados:** {len(altas_con_borrador)}\n\n"
        "---\n\n"
        + _seccion_tabla("Relevancia Alta", "🔴", altas)
        + _seccion_tabla("Relevancia Media", "🟡", medias)
        + seccion_borradores
        + "\n---\n\n"
        "> **Activar normativas:** Portfolio → Gestión de Normativas\n"
        "> _Generado automáticamente por SOLUM Monitor_"
    )

    label = "normativa-alta" if altas else "normativa-media"
    titulo_issue = (
        f"[SOLUM Monitor] {len(normas)} normas detectadas — "
        f"{len(altas_con_borrador)} borradores listos — "
        f"{AYER.strftime('%d/%m/%Y')}"
    )

    try:
        resp = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues",
            headers={
                "Authorization":       f"Bearer {GITHUB_TOKEN}",
                "Accept":              "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": titulo_issue, "body": body, "labels": [label]},
            timeout=20,
        )
        if resp.status_code == 201:
            log.info(f"[issue] Creado: {resp.json().get('html_url','')}")
        else:
            log.warning(f"[issue] Error {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        log.warning(f"[issue] Exception: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def enviar_email_resend(normas: list[dict], total_revisadas: int) -> None:
    """Envía email de alerta vía Resend API."""
    if not RESEND_KEY or not normas:
        log.info("[email] Sin key Resend o sin normas — no se envía email")
        return

    altas  = [n for n in normas if n.get("relevancia") == "alta"]
    medias = [n for n in normas if n.get("relevancia") == "media"]
    con_borrador = [n for n in altas if n.get("texto_procesado")]

    def _fila_html(n: dict) -> str:
        url   = n.get("url", "")
        titulo = n.get("titulo", "")[:100]
        titulo_html = f'<a href="{url}" style="color:#0D9488;">{titulo}</a>' if url else titulo
        entidad = (n.get("entidad") or "")[:50]
        cats = ", ".join(n.get("categorias") or []) or "—"
        resumen = (n.get("resumen") or "")[:120]
        borrador_badge = (
            '<span style="background:#D1FAE5;color:#065F46;padding:2px 6px;'
            'border-radius:4px;font-size:11px;font-weight:700;">BORRADOR LISTO</span>'
            if n.get("texto_procesado") else ""
        )
        return (
            f"<tr>"
            f'<td style="padding:8px 10px;border-bottom:1px solid #E2E8F0;font-size:13px;">'
            f"{titulo_html} {borrador_badge}</td>"
            f'<td style="padding:8px 10px;border-bottom:1px solid #E2E8F0;font-size:12px;color:#475569;">{entidad}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #E2E8F0;font-size:12px;color:#475569;">{cats}</td>'
            f'<td style="padding:8px 10px;border-bottom:1px solid #E2E8F0;font-size:12px;color:#475569;">{resumen}</td>'
            f"</tr>"
        )

    def _seccion_tabla(titulo: str, color: str, items: list[dict]) -> str:
        if not items:
            return ""
        filas = "".join(_fila_html(n) for n in items)
        return f"""
        <h3 style="color:{color};margin:24px 0 8px;">{titulo} ({len(items)})</h3>
        <table style="width:100%;border-collapse:collapse;font-family:Arial,sans-serif;">
          <thead>
            <tr style="background:#F8FAFC;">
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748B;border-bottom:2px solid #E2E8F0;">NORMA</th>
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748B;border-bottom:2px solid #E2E8F0;">ENTIDAD</th>
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748B;border-bottom:2px solid #E2E8F0;">CATEGORÍAS</th>
              <th style="padding:8px 10px;text-align:left;font-size:11px;color:#64748B;border-bottom:2px solid #E2E8F0;">RESUMEN</th>
            </tr>
          </thead>
          <tbody>{filas}</tbody>
        </table>"""

    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:900px;margin:0 auto;">
      <div style="background:#0D2137;padding:20px 28px;border-radius:8px 8px 0 0;">
        <div style="font-size:11px;color:#8AA8C0;letter-spacing:3px;text-transform:uppercase;">SOLUM · Monitor de Normativas</div>
        <div style="font-size:22px;font-weight:700;color:#FFFFFF;margin-top:4px;">
          {len(normas)} normas detectadas — {AYER.strftime('%d/%m/%Y')}
        </div>
      </div>
      <div style="background:#FFFFFF;padding:24px 28px;border:1px solid #E2E8F0;border-top:none;">
        <div style="display:flex;gap:16px;margin-bottom:24px;flex-wrap:wrap;">
          {''.join(
            f'<div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;padding:12px 18px;text-align:center;">'
            f'<div style="font-size:22px;font-weight:700;color:#0D2137;">{v}</div>'
            f'<div style="font-size:11px;color:#64748B;margin-top:2px;">{lbl}</div></div>'
            for v, lbl in [
                (total_revisadas, "revisadas"),
                (len(normas), "relevantes"),
                (len(altas), "alta relevancia"),
                (len(con_borrador), "borradores listos"),
            ]
          )}
        </div>
        {_seccion_tabla("🔴 Alta Relevancia", "#C44A4A", altas)}
        {_seccion_tabla("🟡 Media Relevancia", "#B8862E", medias)}
        <div style="margin-top:28px;padding:16px;background:#F0FDFA;border:1px solid #99F6E4;border-radius:8px;">
          <div style="font-size:12px;color:#0D9488;font-weight:700;margin-bottom:4px;">Para activar en SOLUM</div>
          <div style="font-size:12px;color:#134E4A;">
            Ingresa a SOLUM → Portfolio → sección <strong>Gestión de Normativas</strong>.
            Las normas con borrador listo pueden activarse con un clic.
          </div>
        </div>
      </div>
      <div style="background:#F8FAFC;padding:12px 28px;border:1px solid #E2E8F0;border-top:none;border-radius:0 0 8px 8px;">
        <div style="font-size:11px;color:#94A3B8;">Generado automáticamente por SOLUM Monitor · {HOY.strftime('%d/%m/%Y %H:%M')} · eosterling@grupoosterling.com</div>
      </div>
    </div>
    """

    asunto = (
        f"[SOLUM] {len(altas)} normas ALTA relevancia · {len(con_borrador)} borradores listos — {AYER.strftime('%d/%m/%Y')}"
        if altas else
        f"[SOLUM] {len(normas)} normas detectadas — {AYER.strftime('%d/%m/%Y')}"
    )

    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_KEY}",
                "Content-Type":  "application/json",
            },
            json={
                "from":    "SOLUM Monitor <onboarding@resend.dev>",
                "to":      [NOTIFY_EMAIL],
                "subject": asunto,
                "html":    html_body,
            },
            timeout=20,
        )
        if resp.status_code in (200, 201):
            log.info(f"[email] Enviado a {NOTIFY_EMAIL} — id: {resp.json().get('id','')}")
        else:
            log.warning(f"[email] Error {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        log.warning(f"[email] Exception: {e}")


def _extraer_entidad(texto: str) -> str:
    for e in ENTIDADES_OBJETIVO:
        if e in texto:
            return e.title()
    return "Desconocida"


def _extraer_tipo(texto: str) -> str:
    for t in TIPOS_NORMA_OBJETIVO:
        if t in texto:
            return t.title()
    return "Norma"


def _extraer_fecha(texto: str) -> str:
    for patron in [
        r"\b\d{1,2}/\d{1,2}/\d{4}\b",
        r"\b\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\b",
        r"\b\d{4}-\d{2}-\d{2}\b",
    ]:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            return m.group()
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    sep = "=" * 65
    log.info(sep)
    log.info(f"SOLUM Monitor — {HOY.strftime('%d/%m/%Y')} · revisando {AYER.strftime('%d/%m/%Y')}")
    log.info(sep)

    # Fase 1: scraping paralelo (secuencial por simplicidad en CI)
    todas: list[dict] = []
    todas += buscar_el_peruano()
    todas += buscar_mvcs()
    todas += buscar_imp()
    log.info(f"[fase1] {len(todas)} normas pre-filtradas")

    if not todas:
        log.info("Sin normas pre-filtradas — proceso terminado")
        return

    # Fase 2: evaluación Claude (batch)
    relevantes = evaluar_relevancia_claude(todas)
    log.info(f"[fase2] {len(relevantes)} normas relevantes")

    if not relevantes:
        log.info("Sin normas relevantes — proceso terminado sin alertas")
        return

    # Fase 3: enriquecer normas de alta relevancia con borrador
    relevantes = enriquecer_normas_altas(relevantes)
    con_borrador = sum(1 for n in relevantes if n.get("texto_procesado"))
    log.info(f"[fase3] {con_borrador} borradores generados")

    # Fase 4: persistir en Supabase
    guardadas = guardar_alertas(relevantes)
    log.info(f"[fase4] {guardadas} alertas nuevas en Supabase")

    # Fase 5: email Resend
    enviar_email_resend(relevantes, len(todas))

    # Fase 6: notificación GitHub Issue (respaldo)
    crear_github_issue(relevantes, len(todas))

    log.info(sep)
    log.info(f"Completado: {guardadas} alertas · {con_borrador} borradores SOLUM listos")
    log.info(sep)


if __name__ == "__main__":
    main()
