# MEJORAS DE DISEÑO Y UX — SOLUM
## Sugerencias priorizadas para implementación
### Generado: junio 2026

---

## PRINCIPIO GUÍA

El diseño visual (paleta oscura + dorado, splash screen, identidad) está resuelto y NO se cambia.
El problema es de **flujo de usuario**, no de estética.
Un usuario nuevo debe entender en 10 segundos: *¿por dónde empiezo? ¿qué sigue? ¿terminé?*

---

## BLOQUE 1 — FLUJO PRINCIPAL (impacto máximo)

### Mejora 1.1 — Colapsar 8 tabs en 3 pasos visuales progresivos

**Problema actual:**
El módulo residencial tiene 8 tabs planas (Parámetros, Cabida, Financiero, Flujo de Caja, Legal, Resumen, Propuesta, Renta/Holding). El usuario no sabe el orden, no sabe si tiene que completarlas todas, no sabe cuáles dependen de otras.

**Solución propuesta — Wizard de 3 pasos:**

```
┌─────────────────────────────────────────────────────────┐
│  ① DATOS DEL TERRENO  →  ② ANÁLISIS IA  →  ③ REPORTES  │
│  ████████████░░░░░░░░░    Paso actual                   │
└─────────────────────────────────────────────────────────┘
```

**Agrupación de tabs actuales:**
- **Paso 1 — Datos del terreno:** Parámetros (inputs del usuario + documentos)
- **Paso 2 — Análisis IA:** Cabida + Financiero + Flujo de Caja + Legal
- **Paso 3 — Reportes:** Resumen + Propuesta + Renta/Holding

**Implementación CSS/Python (no requiere cambio de lógica):**
```python
# Reemplazar st.tabs([...8 tabs...]) por wizard con st.columns para el header
# y mantener las tabs internas dentro de cada paso
col1, col2, col3 = st.columns(3)
paso_actual = st.session_state.get("paso_wizard", 1)

with col1:
    done1 = paso_actual > 1
    st.markdown(f"""
    <div style="padding:12px;border-bottom:3px solid {'#B8904A' if paso_actual==1 else '#2A3A2A' if done1 else '#1A1A1A'};text-align:center;">
        <div style="font-size:10px;letter-spacing:0.2em;color:{'#B8904A' if paso_actual==1 else '#555'}">{'✓' if done1 else '01'}</div>
        <div style="font-size:13px;font-weight:600;color:{'#E8E8E8' if paso_actual==1 else '#555'}">Datos del Terreno</div>
    </div>
    """, unsafe_allow_html=True)
```

---

### Mejora 1.2 — Indicador de progreso por tab con estado visual

**Problema actual:** No hay feedback de qué tabs están completas.

**Solución — Tab con estado:**
```python
# Definir estado de cada tab basado en session_state
def _tab_label(nombre, completado, activo):
    icon = "✓" if completado else "○"
    color = "#B8904A" if completado else "#555"
    return f"{icon} {nombre}"

tabs = st.tabs([
    _tab_label("Parámetros", bool(st.session_state.get("params")), True),
    _tab_label("Cabida", bool(st.session_state.get("cabida")), False),
    _tab_label("Financiero", bool(st.session_state.get("financ")), False),
    # ...
])
```

---

### Mejora 1.3 — Botón "Siguiente paso →" al final de cada sección

**Problema actual:** El usuario no sabe cuándo una sección está lista para avanzar.

**Solución:**
```python
# Al final del Tab de Parámetros, mostrar botón prominente:
if st.session_state.get("params") and st.session_state.get("cabida"):
    st.divider()
    col_a, col_b, col_c = st.columns([2, 1, 2])
    with col_b:
        if st.button("Ir a Financiero →", type="primary", use_container_width=True):
            # Activar tab Financiero programáticamente
            st.session_state["tab_activa"] = "financiero"
            st.rerun()
```

---

## BLOQUE 2 — FEEDBACK DURANTE ANÁLISIS IA

### Mejora 2.1 — Loading states detallados durante llamadas a Claude

**Problema actual:** El spinner genérico de Streamlit aparece 30-90 segundos sin contexto.

**Solución — Progress steps durante el análisis:**
```python
# En lugar del spinner genérico, mostrar progreso paso a paso:
def _analizar_con_progreso(cert_bytes, norm_docs):
    progress_placeholder = st.empty()
    
    pasos = [
        ("🔍", "Leyendo certificado de parámetros..."),
        ("🏛️", "Identificando normativa aplicable..."),
        ("📐", "Calculando cabida arquitectónica..."),
        ("💰", "Generando modelo financiero..."),
        ("✅", "Análisis completado"),
    ]
    
    for i, (icon, msg) in enumerate(pasos[:-1]):
        with progress_placeholder.container():
            st.markdown(f"""
            <div style="padding:20px;background:#0E1A0E;border:1px solid #1A3A1A;border-radius:4px;">
                <div style="font-size:11px;letter-spacing:0.2em;color:#4A7A4A;margin-bottom:12px">
                    SOLUM · ANÁLISIS EN PROGRESO
                </div>
                {''.join([f'<div style="color:{"#B8904A" if j==i else "#2A4A2A"};margin:6px 0;font-size:13px">{pasos[j][0]} {pasos[j][1]}</div>' for j in range(i+2)])}
            </div>
            """, unsafe_allow_html=True)
        # La llamada real ocurre aquí entre pasos
    
    return resultado
```

---

### Mejora 2.2 — Mensaje de error específico cuando Claude falla

**Problema actual:** Errores de API muestran mensajes técnicos genéricos.

**Solución:**
```python
ERROR_MESSAGES = {
    "json_parse_error": "El documento no pudo ser procesado. Verifique que el certificado sea legible y no esté protegido.",
    "400": "El documento es demasiado extenso. Comprima el PDF o use solo las páginas con parámetros.",
    "429": "Límite de uso alcanzado. Intente en 60 segundos.",
    "timeout": "El análisis tardó más de lo esperado. Intente con un documento más pequeño.",
}

# En _run_with_retry():
error_key = next((k for k in ERROR_MESSAGES if k in str(e)), None)
msg = ERROR_MESSAGES.get(error_key, "Error inesperado. Contacte soporte.")
st.error(f"⚠️ {msg}")
```

---

## BLOQUE 3 — SIDEBAR

### Mejora 3.1 — Simplificar sidebar a una sola responsabilidad

**Problema actual:** El sidebar contiene: módulo activo, info usuario, cerrar sesión, descripción del módulo, flujo de análisis, y botones de acción. Demasiada información.

**Estructura propuesta:**
```
SIDEBAR
├── Logo + "Osterling Advisory" [header fijo]
├── ─────────────────────────
├── MÓDULO DE ANÁLISIS [sección]
│   ├── ● Proyecto Inmobiliario [activo]
│   ├── ○ Proyecto Industrial
│   ├── ○ Proyecto de Oficinas
│   ├── ○ Inmueble Residencial
│   └── ○ Portfolio
├── ─────────────────────────
├── PROYECTO ACTUAL [sección - solo si hay análisis activo]
│   ├── Nombre del proyecto
│   ├── Distrito · Zona
│   └── [Guardar] [Compartir]
└── ─────────────────────────
    [Usuario] · [Cerrar sesión]  [footer discreto]
```

```python
# "Cerrar sesión" debe ser pequeño y discreto, no un botón prominente:
st.sidebar.markdown("""
<div style="position:absolute;bottom:16px;left:0;right:0;padding:0 16px;
display:flex;justify-content:space-between;align-items:center;">
    <span style="font-size:10px;color:#333;letter-spacing:0.15em">
        {usuario}
    </span>
    <span style="font-size:10px;color:#222;cursor:pointer" onclick="...">
        Salir
    </span>
</div>
""".format(usuario=st.session_state.get("_username","")), unsafe_allow_html=True)
```

---

### Mejora 3.2 — Sidebar colapsable en pantallas pequeñas

```css
/* Agregar al bloque CSS existente: */
@media (max-width: 768px) {
    [data-testid="stSidebar"] {
        width: 0 !important;
        min-width: 0 !important;
        transform: translateX(-100%);
        transition: transform 0.3s ease;
    }
    [data-testid="stSidebar"][aria-expanded="true"] {
        width: 280px !important;
        transform: translateX(0);
    }
}
```

---

## BLOQUE 4 — LEGIBILIDAD Y CONTRASTE

### Mejora 4.1 — Mejorar contraste en cards oscuros dentro del dashboard

**Problema actual:** Los 3 cards (CABIDA, FINANZAS, LEGAL) son dark-on-dark, difíciles de leer en proyector o luz intensa.

**Solución:**
```python
# En lugar de cards oscuros sobre fondo oscuro:
# ACTUAL:
st.markdown("""
<div style="background:#1E2D3D;padding:20px;border-radius:8px;">
    <h3 style="color:#B8904A">CABIDA</h3>
    ...
</div>
""", unsafe_allow_html=True)

# PROPUESTO — borde dorado sutil + fondo ligeramente más claro:
st.markdown("""
<div style="background:#162230;padding:20px;border-radius:4px;
border:1px solid #B8904A40;border-top:2px solid #B8904A;">
    <div style="font-size:10px;letter-spacing:0.25em;color:#B8904A;margin-bottom:8px">CABIDA</div>
    <div style="font-size:13px;color:#C8D8E8">Programa óptimo según normativa vigente</div>
</div>
""", unsafe_allow_html=True)
```

---

### Mejora 4.2 — KPIs financieros más legibles

**Problema actual:** Los números financieros clave (TIR, VAN, Margen) compiten visualmente con mucho texto.

**Solución — KPI cards con jerarquía clara:**
```python
def _kpi_card(label, valor, subtexto, color_valor="#E8E8E8", alerta=False):
    borde = "#C44A4A" if alerta else "#B8904A40"
    return f"""
    <div style="background:#0E1A26;border:1px solid {borde};padding:20px 24px;text-align:center;">
        <div style="font-size:9px;letter-spacing:0.25em;color:#555;text-transform:uppercase;margin-bottom:8px">{label}</div>
        <div style="font-size:32px;font-weight:700;color:{color_valor};letter-spacing:-0.02em;line-height:1">{valor}</div>
        <div style="font-size:11px;color:#3A5A6A;margin-top:6px">{subtexto}</div>
    </div>
    """

# Uso:
cols = st.columns(4)
with cols[0]:
    st.markdown(_kpi_card("TIR sobre Equity", "24.3%", "Retorno anualizado", "#4A9A66"), unsafe_allow_html=True)
with cols[1]:
    st.markdown(_kpi_card("VAN del Proyecto", "USD 420K", "Tasa desc. 15%"), unsafe_allow_html=True)
with cols[2]:
    st.markdown(_kpi_card("Margen sobre Ventas", "18.2%", "Después de impuestos"), unsafe_allow_html=True)
with cols[3]:
    st.markdown(_kpi_card("Punto de Equilibrio", "72%", "Unidades vendidas"), unsafe_allow_html=True)
```

---

## BLOQUE 5 — ONBOARDING

### Mejora 5.1 — Estado vacío con guía de primeros pasos

**Problema actual:** Cuando el usuario no ha hecho ningún análisis, ve el dashboard vacío sin saber qué hacer.

**Solución — Empty state con call-to-action claro:**
```python
if not st.session_state.get("params") and not st.session_state.get("cabida"):
    st.markdown("""
    <div style="text-align:center;padding:80px 40px;max-width:600px;margin:0 auto;">
        <div style="font-size:48px;margin-bottom:24px">📐</div>
        <div style="font-family:'Inter',sans-serif;font-size:24px;font-weight:600;
        color:#E8E8E8;margin-bottom:12px">
            Comienza tu primer análisis
        </div>
        <div style="font-size:14px;color:#555;line-height:1.7;margin-bottom:32px">
            Ingresa los datos del terreno o sube el certificado de parámetros
            para que SOLUM calcule la cabida, el modelo financiero y el análisis legal.
        </div>
        <div style="display:flex;gap:16px;justify-content:center;flex-wrap:wrap;">
            <div style="background:#1A2A1A;border:1px solid #2A4A2A;padding:16px 24px;
            border-radius:4px;font-size:12px;color:#4A8A4A">
                ① Sube el certificado de parámetros
            </div>
            <div style="background:#1A1A2A;border:1px solid #2A2A4A;padding:16px 24px;
            border-radius:4px;font-size:12px;color:#4A4A8A">
                ② SOLUM extrae los parámetros con IA
            </div>
            <div style="background:#2A1A0A;border:1px solid #4A3A1A;padding:16px 24px;
            border-radius:4px;font-size:12px;color:#8A6A2A">
                ③ Obtén cabida, financiero y reporte
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)
```

---

### Mejora 5.2 — Tooltip en campos complejos

**Problema actual:** Campos como "Velocidad de absorción", "LTV", "DSCR" no tienen explicación para usuarios nuevos.

**Solución:**
```python
# Usar st.help o tooltip inline:
vel = st.number_input(
    "Velocidad de absorción (und/mes)",
    min_value=0.5, max_value=10.0, value=1.5, step=0.5,
    help="Número de unidades vendidas por mes. Mercado Lima 2025: 2.1 und/mes promedio. VIS: 3-4 und/mes."
)

tasa = st.number_input(
    "Tasa crédito promotor (% anual)",
    min_value=8.0, max_value=20.0, value=14.0, step=0.5,
    help="Tasa del crédito bancario para la línea promotor. BBVA ~15% TEA, rango mercado 12-16% TEA en soles."
)
```

---

## BLOQUE 6 — DOCUMENTOS (PDF / EXCEL)

### Mejora 6.1 — Preview del reporte antes de descargar

**Problema actual:** El usuario descarga el PDF sin saber qué contiene exactamente.

**Solución — Thumbnail o resumen del reporte:**
```python
st.markdown("""
<div style="background:#0A1018;border:1px solid #1E2D3D;padding:20px;margin-bottom:16px;">
    <div style="font-size:10px;color:#555;letter-spacing:0.2em;margin-bottom:12px">REPORTE INCLUYE</div>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
        <div style="font-size:12px;color:#778899">✓ Portada ejecutiva</div>
        <div style="font-size:12px;color:#778899">✓ Ficha del proyecto</div>
        <div style="font-size:12px;color:#778899">✓ Cabida arquitectónica</div>
        <div style="font-size:12px;color:#778899">✓ Massing 3D</div>
        <div style="font-size:12px;color:#778899">✓ Modelo financiero</div>
        <div style="font-size:12px;color:#778899">✓ Análisis de sensibilidad</div>
        <div style="font-size:12px;color:#778899">✓ Due diligence legal</div>
        <div style="font-size:12px;color:#778899">✓ Recomendación ejecutiva</div>
    </div>
</div>
""", unsafe_allow_html=True)

col1, col2 = st.columns(2)
with col1:
    st.download_button("⬇ Descargar PDF Ejecutivo", data=pdf_bytes, 
                       file_name=f"SOLUM_{proyecto}_{fecha}.pdf",
                       mime="application/pdf", use_container_width=True)
with col2:
    st.download_button("⬇ Descargar Excel Financiero", data=excel_bytes,
                       file_name=f"SOLUM_{proyecto}_{fecha}.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                       use_container_width=True)
```

---

### Mejora 6.2 — Logo institucional en encabezado y pie de todos los documentos

**Verificar que en generar_pdf_factis(), generar_informe_industrial_pdf() y generar_propuesta_pdf():**
```python
# El logo debe aparecer en:
# 1. Portada (logo grande centrado)
# 2. Header de cada página interior (logo pequeño + nombre del proyecto)
# 3. Footer de cada página (logo + número de página + confidencialidad)

# Footer template:
def _footer(canvas_obj, doc):
    canvas_obj.saveState()
    # Logo pequeño
    if _LOGO_B64:
        from reportlab.lib.utils import ImageReader
        import io, base64
        img_data = base64.b64decode(_LOGO_B64)
        img = ImageReader(io.BytesIO(img_data))
        canvas_obj.drawImage(img, 40, 20, width=60, height=20, preserveAspectRatio=True, mask='auto')
    # Línea separadora
    canvas_obj.setStrokeColor(colors.HexColor("#1E2D3D"))
    canvas_obj.line(40, 40, doc.pagesize[0]-40, 40)
    # Número de página
    canvas_obj.setFont("Helvetica", 8)
    canvas_obj.setFillColor(colors.HexColor("#999999"))
    canvas_obj.drawRightString(doc.pagesize[0]-40, 25, f"Página {doc.page}")
    # Confidencialidad
    canvas_obj.drawString(120, 25, "CONFIDENCIAL — Osterling Advisory · SOLUM")
    canvas_obj.restoreState()
```

---

## BLOQUE 7 — MOBILE Y ACCESIBILIDAD

### Mejora 7.1 — Breakpoints básicos para tablet/mobile

```css
/* Agregar al bloque CSS existente (líneas 993-1884): */

/* Tablet (768px - 1024px) */
@media (max-width: 1024px) {
    [data-testid="stSidebar"] > div:first-child {
        padding: 16px !important;
    }
    .block-container {
        padding: 16px !important;
    }
}

/* Mobile (< 768px) */
@media (max-width: 768px) {
    [data-testid="stSidebar"] {
        display: none !important;
    }
    /* Botón hamburguesa para abrir sidebar */
    .mobile-menu-btn {
        display: block !important;
        position: fixed;
        top: 16px; left: 16px;
        z-index: 999;
        background: #1E2D3D;
        border: 1px solid #B8904A;
        color: #B8904A;
        padding: 8px 12px;
        font-size: 16px;
        cursor: pointer;
    }
    /* Columnas en mobile van a una sola columna */
    [data-testid="column"] {
        width: 100% !important;
        flex: none !important;
    }
}
```

---

## PRIORIDAD DE IMPLEMENTACIÓN

| # | Mejora | Impacto UX | Esfuerzo | Prioridad |
|---|---|---|---|---|
| 1.1 | Wizard 3 pasos (colapsar 8 tabs) | ★★★★★ | Alto (1 semana) | 🔴 Alta |
| 2.1 | Loading states detallados durante IA | ★★★★★ | Medio (2 días) | 🔴 Alta |
| 4.2 | KPI cards más legibles | ★★★★☆ | Bajo (4 horas) | 🟡 Media |
| 5.1 | Empty state con guía primeros pasos | ★★★★☆ | Bajo (4 horas) | 🟡 Media |
| 5.2 | Tooltips en campos complejos | ★★★★☆ | Bajo (3 horas) | 🟡 Media |
| 3.1 | Simplificar sidebar | ★★★☆☆ | Medio (1 día) | 🟡 Media |
| 2.2 | Mensajes de error específicos | ★★★☆☆ | Bajo (2 horas) | 🟡 Media |
| 6.1 | Preview antes de descargar | ★★★☆☆ | Bajo (3 horas) | 🟡 Media |
| 6.2 | Logo en footer de documentos | ★★★☆☆ | Bajo (2 horas) | 🟡 Media |
| 1.2 | Tab con estado visual (checkmarks) | ★★★☆☆ | Bajo (3 horas) | 🟢 Baja |
| 1.3 | Botón "Siguiente paso →" | ★★★☆☆ | Bajo (2 horas) | 🟢 Baja |
| 4.1 | Contraste en cards oscuros | ★★☆☆☆ | Bajo (2 horas) | 🟢 Baja |
| 7.1 | Breakpoints mobile | ★★★☆☆ | Medio (1 día) | 🟢 Baja |

---

## NOTA IMPORTANTE PARA EL DESARROLLADOR

- **NO cambiar** la paleta de colores (oscuro + dorado). Decisión tomada.
- **NO cambiar** el splash screen ni el login. Funcionan bien.
- **NO tocar** el modelo financiero ni la lógica de cabida en este sprint de UX.
- Las mejoras de UX son **aditivas** — se agregan encima del flujo existente sin romper nada.
- Priorizar **Mejora 1.1 (wizard)** y **Mejora 2.1 (loading states)** — son las que más impactan la primera experiencia de un usuario nuevo.

---

*Documento generado: junio 2026*
*Archivo: /FACTIS/UX_MEJORAS_SOLUM_2026.md*
