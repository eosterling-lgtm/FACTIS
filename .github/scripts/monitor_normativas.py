"""
SOLUM — Monitor diario de normativas Lima
Corre cada día a las 8:00 AM Lima vía GitHub Actions.
Fuentes Fase A: El Peruano · MVCS · IMP Lima
"""

import os
import re
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

HOY = datetime.date.today()
AYER = HOY - datetime.timedelta(days=1)

# ── Entidades relevantes para SOLUM ──────────────────────────────────────────
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
    "SUNARP",
    "MINISTERIO DE TRANSPORTES Y COMUNICACIONES",
    "INSTITUTO METROPOLITANO DE PLANIFICACION",
]

TIPOS_NORMA_OBJETIVO = [
    "ORDENANZA", "DECRETO SUPREMO", "RESOLUCION MINISTERIAL",
    "DECRETO DE ALCALDIA", "RESOLUCION DE ALCALDIA", "RESOLUCION DIRECTORAL",
]

KEYWORDS_RELEVANTES = [
    "edificacion", "edificaciones", "urbanistic", "zonificac",
    "habilitacion urbana", "parametros urbanisticos", "reglamento nacional",
    "retiros", "estacionamiento", "altura", "coeficiente de edificacion",
    "uso de suelo", "indice de usos", "licencia de edificacion",
    "licencia de construccion", "industrial", "logistic", "almacen",
    "costos de construccion", "valor unitario", "plan de desarrollo urbano",
    "planmet", "impacto vial", "seguridad en edificaciones",
    "accesibilidad", "sismorresistente", "suelos y cimentaciones",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; SOLUM-Monitor/1.0; "
        "+https://github.com/eosterling-lgtm/FACTIS)"
    )
}


# ── FUENTE 1: El Peruano ──────────────────────────────────────────────────────
def buscar_el_peruano() -> list[dict]:
    """Consulta el buscador de El Peruano filtrando por entidad y fecha."""
    resultados = []
    fecha_str = AYER.strftime("%d/%m/%Y")
    log.info(f"[El Peruano] Buscando publicaciones del {fecha_str}")

    base_url = "https://busquedas.elperuano.pe/normaslegales/"
    params = {
        "k":     "",
        "fini":  fecha_str,
        "ffin":  fecha_str,
        "p":     1,
    }

    try:
        resp = requests.get(base_url, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # El Peruano lista normas en elementos con clase "itemsNorma" o similar
        items = soup.find_all("div", class_=re.compile(r"item.*norma|norma.*item", re.I))
        if not items:
            # Fallback: buscar filas de tabla
            items = soup.find_all("tr", class_=re.compile(r"norma|row", re.I))

        log.info(f"[El Peruano] {len(items)} ítems encontrados en la página")

        for item in items:
            texto = item.get_text(" ", strip=True).upper()
            titulo_tag = item.find(["h3", "h4", "a", "strong"])
            titulo = titulo_tag.get_text(strip=True) if titulo_tag else texto[:200]
            link_tag = item.find("a", href=True)
            url = link_tag["href"] if link_tag else ""
            if url and not url.startswith("http"):
                url = "https://busquedas.elperuano.pe" + url

            # Filtro capa 1: entidad
            entidad_match = any(e in texto for e in ENTIDADES_OBJETIVO)
            # Filtro capa 2: tipo de norma
            tipo_match = any(t in texto for t in TIPOS_NORMA_OBJETIVO)

            if entidad_match or tipo_match:
                resultados.append({
                    "fuente":           "el_peruano",
                    "titulo":           titulo,
                    "url":              url,
                    "fecha_publicacion": str(AYER),
                    "entidad":          _extraer_entidad(texto),
                    "tipo_norma":       _extraer_tipo(texto),
                    "texto_raw":        texto[:500],
                })

    except Exception as e:
        log.warning(f"[El Peruano] Error: {e}")

    log.info(f"[El Peruano] {len(resultados)} normas pre-filtradas")
    return resultados


# ── FUENTE 2: MVCS ────────────────────────────────────────────────────────────
def buscar_mvcs() -> list[dict]:
    """Revisa la sección de normativas del MVCS."""
    resultados = []
    log.info("[MVCS] Revisando normativas recientes")

    urls_mvcs = [
        "https://www.gob.pe/institucion/vivienda/normas-legales",
        "https://www.gob.pe/institucion/vivienda/decretos",
    ]

    for url in urls_mvcs:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for item in soup.find_all(["article", "li", "div"],
                                       class_=re.compile(r"norma|decreto|resolucion|item", re.I)):
                texto = item.get_text(" ", strip=True)
                fecha_encontrada = _extraer_fecha(texto)
                if not fecha_encontrada:
                    continue
                # Solo publicaciones de ayer o hoy
                try:
                    if dateparser.parse(fecha_encontrada).date() < AYER:
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
                    "texto_raw":         texto[:500],
                })

        except Exception as e:
            log.warning(f"[MVCS] Error en {url}: {e}")

    log.info(f"[MVCS] {len(resultados)} normas pre-filtradas")
    return resultados


# ── FUENTE 3: IMP Lima ────────────────────────────────────────────────────────
def buscar_imp() -> list[dict]:
    """Revisa publicaciones del IMP (zonificación, PLANMET)."""
    resultados = []
    log.info("[IMP] Revisando publicaciones recientes")

    url_imp = "https://imp.gob.pe/normativas/"

    try:
        resp = requests.get(url_imp, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for item in soup.find_all(["article", "li", "div", "tr"]):
            texto = item.get_text(" ", strip=True)
            if len(texto) < 20:
                continue
            fecha_encontrada = _extraer_fecha(texto)
            es_reciente = False
            if fecha_encontrada:
                try:
                    es_reciente = dateparser.parse(fecha_encontrada).date() >= AYER
                except Exception:
                    pass

            kw_match = any(kw in texto.lower() for kw in KEYWORDS_RELEVANTES)
            if not (es_reciente or kw_match):
                continue

            titulo_tag = item.find(["h3", "h4", "a", "strong"])
            titulo = titulo_tag.get_text(strip=True) if titulo_tag else texto[:200]
            link_tag = item.find("a", href=True)
            item_url = link_tag["href"] if link_tag else url_imp
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
                    "texto_raw":         texto[:500],
                })

    except Exception as e:
        log.warning(f"[IMP] Error: {e}")

    # Deduplicar por título
    vistos = set()
    unicos = []
    for r in resultados:
        if r["titulo"] not in vistos:
            vistos.add(r["titulo"])
            unicos.append(r)

    log.info(f"[IMP] {len(unicos)} normas pre-filtradas")
    return unicos


# ── CAPA 3: Claude evalúa relevancia ─────────────────────────────────────────
def evaluar_relevancia_claude(normas: list[dict]) -> list[dict]:
    """Claude lee cada título y clasifica relevancia para SOLUM."""
    if not normas or not ANTHROPIC_KEY:
        log.warning("Sin normas o sin API key — omitiendo evaluación Claude")
        return normas

    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY, max_retries=0, timeout=60.0)

    titulos_json = json.dumps(
        [{"id": i, "titulo": n["titulo"], "entidad": n.get("entidad", "")}
         for i, n in enumerate(normas)],
        ensure_ascii=False
    )

    prompt = f"""Eres experto en normativa urbanística y edificatoria de Lima, Perú.

Evalúa cada norma y determina si es relevante para una herramienta de pre-factibilidad inmobiliaria que analiza:
- Parámetros urbanísticos (altura, retiros, COS, CUS, estacionamiento)
- Zonificación y usos de suelo (residencial, industrial, comercial)
- Reglamento Nacional de Edificaciones (RNE)
- Habilitaciones urbanas
- Normativa de edificaciones industriales y logísticas
- Costos de construcción oficiales
- Impacto vial (EIV)
- Registros SUNARP relacionados a edificaciones

Para cada norma responde con este JSON exacto:
{{"resultados": [{{"id": 0, "relevante": true/false, "relevancia": "alta/media/baja", "categorias": ["zonificacion","rne","costos","industrial","residencial","registral","vial"], "resumen": "una línea explicando qué cambia"}}]}}

Normas a evaluar:
{titulos_json}"""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.content[0].text
        # Extraer JSON
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            data = json.loads(match.group())
            evaluaciones = {r["id"]: r for r in data.get("resultados", [])}
            for i, norma in enumerate(normas):
                ev = evaluaciones.get(i, {})
                norma["relevante"]  = ev.get("relevante", False)
                norma["relevancia"] = ev.get("relevancia", "baja")
                norma["categorias"] = ev.get("categorias", [])
                norma["resumen"]    = ev.get("resumen", "")
        log.info(f"[Claude] Evaluación completada para {len(normas)} normas")
    except Exception as e:
        log.warning(f"[Claude] Error en evaluación: {e}")
        for norma in normas:
            norma["relevante"]  = True   # conservador: si falla Claude, guarda todo
            norma["relevancia"] = "media"
            norma["categorias"] = []
            norma["resumen"]    = ""

    return [n for n in normas if n.get("relevante", False)]


# ── Guardar en Supabase ───────────────────────────────────────────────────────
def guardar_alertas(normas: list[dict]) -> int:
    """Inserta las normas relevantes en alertas_normativas."""
    if not normas or not SUPABASE_URL or not SUPABASE_KEY:
        return 0

    from supabase import create_client
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)
    guardadas = 0

    for n in normas:
        # Evitar duplicados por título + fecha
        exist = (sb.table("alertas_normativas")
                   .select("id")
                   .eq("titulo", n["titulo"][:500])
                   .eq("fecha_publicacion", n["fecha_publicacion"])
                   .execute())
        if exist.data:
            log.info(f"Ya existe: {n['titulo'][:60]}")
            continue

        try:
            sb.table("alertas_normativas").insert({
                "fecha_publicacion": n["fecha_publicacion"],
                "entidad":           n.get("entidad", "")[:200],
                "tipo_norma":        n.get("tipo_norma", "")[:100],
                "titulo":            n["titulo"][:500],
                "resumen":           n.get("resumen", "")[:500],
                "url":               n.get("url", "")[:500],
                "fuente":            n.get("fuente", "")[:50],
                "relevancia":        n.get("relevancia", "media"),
                "categorias":        n.get("categorias", []),
                "procesado":         False,
            }).execute()
            guardadas += 1
            log.info(f"✓ Guardada: {n['titulo'][:80]}")
        except Exception as e:
            log.warning(f"Error guardando '{n['titulo'][:60]}': {e}")

    return guardadas


# ── Notificación por GitHub Issue ────────────────────────────────────────────
def crear_github_issue(normas: list[dict], total_revisadas: int):
    """Crea un GitHub Issue con el resumen de normas detectadas.
    GitHub envía email automático al owner del repositorio cuando se crea un issue.
    GITHUB_TOKEN está disponible de forma automática en GitHub Actions.
    """
    if not normas or not GITHUB_TOKEN:
        log.info("Sin normas nuevas o sin GITHUB_TOKEN — no se crea issue")
        return

    altas  = [n for n in normas if n.get("relevancia") == "alta"]
    medias = [n for n in normas if n.get("relevancia") == "media"]

    def _fila_md(n):
        cats = ", ".join(n.get("categorias", [])) or "—"
        url  = n.get("url", "")
        titulo_link = f"[{n['titulo'][:100]}]({url})" if url else n["titulo"][:100]
        entidad = n.get("entidad", "")[:60]
        resumen = n.get("resumen", "")[:120]
        return f"| {titulo_link} | {entidad} | {cats} | {resumen} |"

    tabla_header = "| Título | Entidad | Categorías | Resumen |\n|--------|---------|------------|---------|"

    seccion_altas = ""
    if altas:
        filas = "\n".join(_fila_md(n) for n in altas)
        seccion_altas = f"## 🔴 Relevancia Alta ({len(altas)})\n\n{tabla_header}\n{filas}\n"

    seccion_medias = ""
    if medias:
        filas = "\n".join(_fila_md(n) for n in medias)
        seccion_medias = f"## 🟡 Relevancia Media ({len(medias)})\n\n{tabla_header}\n{filas}\n"

    body = f"""# SOLUM Monitor — {len(normas)} normas relevantes detectadas

**Publicaciones del:** {AYER.strftime('%d/%m/%Y')}
**Total revisadas:** {total_revisadas} normas
**Relevantes:** {len(normas)} ({len(altas)} alta · {len(medias)} media)

---

{seccion_altas}
{seccion_medias}

---

> Para procesar estas normas y activarlas en SOLUM, ingresa al **Portfolio → Gestión de Normativas**.
> _Generado automáticamente por SOLUM Monitor_"""

    # Determinar label según relevancia
    label = "normativa-alta" if altas else "normativa-media"
    titulo_issue = (
        f"SOLUM Monitor — {len(normas)} normas detectadas — "
        f"{AYER.strftime('%d/%m/%Y')}"
    )

    try:
        resp = requests.post(
            f"https://api.github.com/repos/{GITHUB_REPO}/issues",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept":        "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"title": titulo_issue, "body": body, "labels": [label]},
            timeout=20,
        )
        if resp.status_code == 201:
            issue_url = resp.json().get("html_url", "")
            log.info(f"Issue creado: {issue_url}")
        else:
            log.warning(f"GitHub Issue error {resp.status_code}: {resp.text[:300]}")
    except Exception as e:
        log.warning(f"GitHub Issue exception: {e}")


# ── Helpers ───────────────────────────────────────────────────────────────────
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
    patrones = [
        r'\b\d{1,2}/\d{1,2}/\d{4}\b',
        r'\b\d{1,2}\s+de\s+\w+\s+de\s+\d{4}\b',
        r'\b\d{4}-\d{2}-\d{2}\b',
    ]
    for p in patrones:
        m = re.search(p, texto, re.IGNORECASE)
        if m:
            return m.group()
    return ""


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    log.info(f"{'='*60}")
    log.info(f"SOLUM Monitor — {HOY.strftime('%d/%m/%Y %H:%M UTC')}")
    log.info(f"Revisando publicaciones del {AYER.strftime('%d/%m/%Y')}")
    log.info(f"{'='*60}")

    # Recolectar de las 3 fuentes en paralelo
    todas = []
    todas += buscar_el_peruano()
    todas += buscar_mvcs()
    todas += buscar_imp()

    log.info(f"Total pre-filtradas: {len(todas)} normas")

    if not todas:
        log.info("Sin normas pre-filtradas hoy — proceso terminado sin alertas")
        return

    # Claude evalúa relevancia final
    relevantes = evaluar_relevancia_claude(todas)
    log.info(f"Relevantes tras evaluación Claude: {len(relevantes)}")

    # Guardar en Supabase
    guardadas = guardar_alertas(relevantes)
    log.info(f"Guardadas en Supabase: {guardadas} nuevas")

    # Notificación vía GitHub Issue
    crear_github_issue(relevantes, len(todas))

    log.info(f"{'='*60}")
    log.info(f"Proceso completado. {guardadas} alertas nuevas guardadas.")
    log.info(f"{'='*60}")


if __name__ == "__main__":
    main()
