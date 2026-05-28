# SOLUM — Contexto de proyecto para Claude Code

## Quién es el usuario

**Enrique (Kike) Osterling** — advisory inmobiliario, Osterling Advisory.
- Especialización: activos comerciales, industriales y proyectos de desarrollo en Lima.
- Clientes: fondos de inversión, compañías de seguros, grupos económicos, empresas de renombre.
- Interlocución directa con C-level y gerencias de adquisiciones.
- Todo output debe ser ejecutivo, profesional, orientado a criterios financieros/riesgo institucional.

---

## Qué es SOLUM

App Streamlit de pre-factibilidad inmobiliaria. Archivo único: `app.py` (~15,000 líneas).

**Propósito:** Evaluar terrenos en 15 minutos — cabida arquitectónica + análisis financiero + análisis legal. Lleva al promotor a reunirse con arquitecto/estructurista/banco con números ya trabajados, no reemplaza el expediente técnico.

**Principio de diseño:** La app hace el 90% del trabajo de pre-factibilidad. No busca exactitud milimétrica. Números deben ser defendibles y coherentes con la realidad del mercado limeño.

**Flujo:** Certificado de parámetros → cabida arquitectónica (IA) → modelo financiero con banco → reporte PDF/Excel para C-level/banco.

---

## Arquitectura del código

| Función | Propósito |
|---|---|
| `extract_parameters(cert_bytes, norm_docs)` | Extrae parámetros del certificado urbanístico vía Claude API → dict |
| `generate_cabida(params, config)` | Genera programa arquitectónico por distrito → dict |
| `calcular_financiero(cabida, fin, zona)` | Análisis financiero residencial → dict |
| `calcular_industrial(inp)` | Análisis financiero industrial → dict |
| `calcular_terreno_maximo(inp)` | Calculadora inversa de precio máximo de terreno |
| `_run_with_retry(fn, max_retries=3)` | Ejecuta con reintentos en json_parse_error |
| `generar_excel_factis(...)` | Reporte Excel residencial |
| `generar_pdf_factis(...)` | Reporte PDF residencial |
| `generar_informe_industrial_pdf(...)` | Reporte PDF industrial |
| `generar_propuesta_pdf(...)` | Propuesta comercial PDF |
| `generar_dcf_excel(...)` | Flujo de caja DCF en Excel |
| `_geo_poligono_tabular/dxf(...)` | Polígono Shapely desde medidas o DXF |
| `_geo_aplicar_retiros(...)` | Aplica retiros al polígono del lote |
| `_gen_massing_3d_solid(...)` | Massing 3D sólido con tipologías por piso (Plotly) |

**Cliente Anthropic:** `max_retries=0, timeout=120.0`, modelo `claude-sonnet-4-6`

**Dependencias clave:** streamlit, anthropic, plotly, pandas, openpyxl, reportlab, shapely, ezdxf, supabase

---

## Distritos con RIN integrado en generate_cabida

San Isidro · Miraflores · Jesús María · Cercado de Lima · San Borja · Santa Anita · Surco · Surquillo · Villa El Salvador · San Juan de Lurigancho

---

## Modelo financiero residencial

- **Tasa financiamiento bancario default: 9%**
- **Estructura A — Estándar:** terreno 100% equity → banco financia solo obra en armadas
- **Estructura B — Con track record:** promotor aporta X% en minuta, banco paga saldo terreno + obra
- **Preventa:** `pct_preventa_banco` default 30%, meses calculados automáticamente = ⌈(n_und × pct_preventa) / vel_absorción⌉ (mín 1 mes)
- Flujo: construcción arranca en mes `meses_preventa`, no mes 2 hardcoded

## Modelo financiero industrial

- **Dos créditos separados:** terreno (DP% propio, tasa, plazo) + construcción (DP% propio, tasa, plazo)
- Crédito terreno: default DP 40%, tasa 8%, plazo 10 años
- Crédito construcción: default DP 30%, tasa 9%, plazo 8 años
- Output incluye desglose de cada crédito + totales combinados

---

## Expertise industrial Lima — benchmarks clave

### Renta de mercado Prime Lima
- Rango: $5.50–$7.50/m²/mes
- Hubs: Villa El Salvador, Lurín, SJL, Callao, Cercado de Lima

### Precio máximo de terreno (orientativo)
| Propósito | VES/Lurín | Lógica |
|---|---|---|
| Build-to-rent | ~$180/m² | Debe generar yield |
| Uso propio | ~$300/m² | Reemplaza costo de arriendo |

### Estructura de costos nave (VES/Lurín)
| Componente | Referencia |
|---|---|
| Terreno (máx. build-to-rent) | $180/m² terreno |
| Implementación nave | $300/m² nave |
| Total | ~$480/m² |
| Equivalente renta (10 años) | ~$7.00/m²/mes |

### Alturas de nave por actividad (altura al hombro)
| Actividad | Altura típica |
|---|---|
| Almacén / 3PL / Centro distribución | 12–14m |
| Producción / Manufactura | 8–10m |
| Taller / Metalmecánica | 6–8m |
| Cámara frigorífica | 10–12m |
| Con puente grúa | 14–16m |

"Altura al hombro" = altura libre interior en punto más bajo (gotera), NO la cumbrera.

### Regla buy vs. rent
Si renta mercado = $7.00/m²/mes → costo efectivo compra debe ser < $7.00/m²/mes para justificar compra. Target optimizado: ~$6.00/m²/mes.

---

## Cabida arquitectónica — geometría de lotes

### Fuentes de medidas (orden de confiabilidad)
1. Levantamiento topográfico (distancias + ángulos)
2. Plano perimétrico AutoCAD/PDF
3. Partida SUNARP
4. Tabulación manual (frente/fondo/lado izq/lado der)

### Frentes mínimos para viabilidad
- **Residencial multifamiliar:** 13m absoluto, 15m ideal
- **Industrial/logístico:** 20m mínimo

### Formas de lote
- Regular (rectángulo), Irregular (4 lados no paralelos), Esquina (dos frentes, ochavo obligatorio)

---

## Financiamiento promotor Perú — mecánica bancaria

- **Un solo contrato, una hipoteca** que el banco amplía por avance de obra
- Banco inscribe hipoteca en SUNARP → amplía para construcción
- Armadas de construcción = desembolsos parciales condicionados a avance verificado por inspector
- Banco financia hasta 70–80% del **valor de tasación** (NO precio de compra)

### Preventa
- Exigencia bancaria promedio: **30% de unidades vendidas** antes del primer desembolso
- Costo marketing preventa: ~2% de costos de ventas/gerencia (sale de equity)
- Fórmula meses: `⌈(total_unidades × 30%) ÷ vel_absorción⌉` — vel típica Lima: 1.0–2.0 und/mes

---

## RNE — Normas clave para desarrollo en Lima

### A.010 — Condiciones Generales
- Altura libre mínima vivienda: 2.30m
- Elevadores: obligatorio sobre 12.00m
- Estacionamiento privado: 2.70m ancho (1 esp), 2.50m (2 adj), 2.40m (3+); altura libre 2.10m
- Rampa: pendiente máx 15%, radio giro mín 5.00m
- Acceso vehicular: 3.00m (≤40 veh), 6.00m (61–500 veh)

### A.020 — Vivienda
- Área mínima multifamiliar: 40.00m²
- Densidad: 1D=2 pers, 2D=3 pers, 3D=4 pers
- Pozos de luz (1–18m): Tipo A (dorm/sala) 30% altura opuesta, Tipo B (cocina) 25%
- Azotea: cobertura máx 50%, retiro fachada 2.50m
- Dúplex obligatorio en último piso (≥5 pisos), área azotea máx 50% del piso inferior

### Parámetros urbanísticos Lima (referencia)
| Zona | CUS | COS | Altura típica |
|---|---|---|---|
| RDM | 4.0–6.0 | 50–60% | 5–9 pisos |
| RDA | 2.5–3.5 | 40–50% | 4–6 pisos |
| RDB | 1.5–2.5 | 30–40% | 3–5 pisos |

- CUS: multiplicador área terreno → área máxima construible
- COS: % cobertura en nivel de suelo
- CZ = 1.5(a+r) en vías ≥20m (fórmula de altura)
- **Cada distrito tiene PDU propio que prevalece sobre RNE general**

---

## Fixes de robustez aplicados (no revertir)

- `response.content` vacío → raise ValueError("json_parse_error: ...") en 5 ubicaciones de API
- `st.session_state.get()` para `ind_tipo`, `ind_zona_ind`, `ind_uso` (evitar AttributeError)
- `tasa_ir` division by zero → `max(..., 0) / 100`
- HTML report division by zero → `_ct = r.get('costo_total') or 1`
- Depósitos: 1 por unidad (no 0.6)
- Loading messages en lenguaje natural

## Instrucciones de desarrollo

- Respetar la estructura de funciones existente
- No sobrecomplicar cálculos buscando precisión imposible sin datos de campo
- Cuando algo es estimación, documentarlo en observaciones para que el usuario lo sepa
- Priorizar números defendibles y coherentes con mercado limeño
- No agregar features, refactors ni abstracciones más allá de lo solicitado
