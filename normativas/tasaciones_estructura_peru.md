# TASACIONES INMOBILIARIAS PERÚ — ESTRUCTURA Y CRITERIOS DE ANÁLISIS

## 1. Marco Normativo

- **Reglamento Nacional de Tasaciones:** R.M. Nº 172-2016-VIVIENDA y modificatoria R.M. N° 424-2017-VIVIENDA
- **Valor de Realización en el Mercado:** Resolución SBS Nº 11356-2008
- **Metodología:** Art. 3, Inciso 3.1.5 del RNT — Métodos Directos (Comparación y Costos) + Indirectos (Capitalización de Renta)
- **Vigencia del informe:** 1 año desde la fecha de expedición (no 6 meses)
- **Validación bancaria:** Informe con código QR / código de verificación expedido por tasadora registrada en SBS

---

## 2. Estructura del Informe de Tasación Bancaria

### Hoja Resumen (Portada)
Contiene todos los datos clave en una sola página. Es la primera referencia en due diligence.

**Campos obligatorios:**
| Campo | Descripción |
|---|---|
| N° Solicitud / N° Servicio Tasadora | Código único del encargo |
| Fecha de Inspección | Fecha visita al inmueble |
| Fecha de Expedición | Inicio de vigencia |
| Fecha última de Vigencia | 1 año después — informe caduca |
| Tipo de Tasación | Comercial / Hipotecaria / Liquidación |
| Cliente / Propietario | Pueden ser distintos (banco vs. dueño) |
| Dirección RRPP | Según Partida Electrónica |
| Distrito / Provincia / Departamento | Ubicación registral |
| Georreferencia | Latitud / Longitud (Google Maps) |
| Ocupante | Propietario / Arrendatario / Desocupado |
| Zonificación | Según CPUE o planos municipales |
| Declaratoria de Fábrica | Sí tiene / No tiene — dato crítico |
| Cargas | Sí/No |
| Gravámenes | Sí/No (hipotecas, embargos) |
| Tipo de Cambio Aplicado | S/./USD usado en el informe |

### Cuadro Comparativo de Áreas (DATO CRÍTICO para Due Diligence)
Cruza tres fuentes para detectar discrepancias:

| Fuente | Área Terreno | Área Construida | Uso |
|---|---|---|---|
| Según Registros Públicos (Partida) | — | — | — |
| Según Autoavalúo (HR/PU) | — | — | — |
| Según Inspección Ocular | — | — | — |
| **Diferencia** | — | — | — |

**Interpretación de diferencias:**
- Área terreno: diferencia RRPP vs. inspección → indica posible afectación vial o error registral (observación: "recomendar regularización ante RRPP")
- Área construida: HR mucho mayor que RRPP → construcción sin declaratoria de fábrica inscrita (hallazgo legal ALTO)
- Área construida: HR igual a RRPP = 0 → predio sin construir o declaratoria actualizada

**Ejemplo real — CELIMA SJL (2025):**
- RRPP: 70,000m² terreno, 7,548m² construcción
- HR/Autoavalúo: 68,433m² terreno, 35,700m² construcción
- **Diferencia:** -1,567m² terreno (afectación vial) + 28,152m² construcción no inscrita
- **Observación del tasador:** "Se recomienda regularizar ante Registros Públicos"

---

## 3. Metodología de Valorización

### 3.1 Método Comparativo (Mercado) — para Terreno

**Proceso:**
1. Identificar mínimo 3 comparables en el mercado (oferta activa)
2. Registrar: ubicación, fuente, teléfono, área, zonificación, precio ofertado
3. Aplicar **factores de homologación** para hacer comparables al inmueble tasado
4. Calcular Valor Unitario Terreno Homologado promedio (VUT, en US$/m²)

**Factores de Homologación estándar:**
| Factor | Símbolo | Descripción | Valor típico |
|---|---|---|---|
| Ubicación | Ub. | Acceso, vías, entorno | 0.85–1.15 |
| Topografía | Top. | Plano=1.00, con pendiente<1 | 0.90–1.00 |
| Superficie | Sup. | Lote grande descuenta vs. pequeño | 0.60–0.99 |
| Servicios | Ser. | Agua/luz/desagüe completos=1.00 | 0.90–1.00 |
| Zonificación | Zon. | I2=I2=1.00; CZ vs I2 ajusta | 0.90–1.10 |
| Factor Negociación | F.N. | Descuento por tratarse de oferta | **0.80–0.90** |

**Factor Resultante = Ub × Top × Sup × Ser × Zon × F.N.**

**Factor de Negociación (FN):** Reconoce que los precios de oferta aún no se han realizado. En Lima se aplica 0.80–0.90 sistemáticamente (10–20% de descuento sobre precio pedido).

**Ejemplo real — Ventanilla IG (2021):**
- Comparables ofertados: $391–426/m²
- VUT homologado: $300/m²
- Descuento implícito: ~26%

**Ejemplo real — SJL I2/CZ (2025):**
- Comparables ofertados: $600–1,700/m²
- VUT homologado: $560/m² (promedio, lotes grandes 68,000m²)
- Factor superficie: 0.60–0.80 (lotes grandes descuentan significativamente)

### 3.2 Método de Costos o Reposición — para Edificaciones

**Componentes del valor:**

| Componente | Descripción |
|---|---|
| VT — Valor Terreno | Según método comparativo |
| VSNE — Valor Similar a Nuevo de Edificación | Costo de reconstrucción × área techada |
| VE — Valor de Edificación | VSNE × FD (factor depreciación) |
| VOC — Valor Obras Complementarias | Cercos, patios, cisternas, etc. |
| **VTP = VT + VE + VOC** | **Valor Total del Predio** |

**Valores Unitarios de Edificación (VUE) — Lima 2025:**
| Tipo de estructura | VUE (US$/m²) |
|---|---|
| Nave concreto Clase A (losa aligerada/placas) | $295–440/m² |
| Nave metálica / Estructura de acero | $250/m² |
| Edificio administrativo ladrillo (oficinas) | $440/m² |
| Obras complementarias (patios losa) | $25/m² |
| Cerco perimétrico ladrillo | $120/ml |

**Factor de Depreciación (FD) por edad:**
| Edad | FD típico | Estado Conservación |
|---|---|---|
| 0–5 años | 0.91–1.00 | Bueno |
| 8–10 años | 0.83–0.91 | Bueno |
| 25–30 años | 0.62–0.72 | Bueno |
| 40–45 años | 0.50–0.60 | Bueno |

### 3.3 Método de Capitalización de Renta (Indirecto)

Usado como referencia secundaria. Formula: **Valor = Renta Anual / Cap Rate**

**Ejemplo real — Puente Piedra I2 (2017):**
- Renta de mercado: $26,400/año ($11/m²/mes para 200m² → muy bajo, dato antiguo)
- Método principal usado: Costos ($3.88M)

---

## 4. Valor de Realización

**Fórmula:** Valor Realización = Valor Comercial × (1 − % Deducciones)

**Deducciones estándar:**
| Concepto | % |
|---|---|
| Comisión de ventas | 5.00% |
| Gastos de publicidad | 2.00% |
| Gastos de tasación para realización | 0.20% |
| Mantenimiento (periodo de venta) | 2.00% |
| Factor tiempo (venta en 60 días) | variable |
| **Total deducciones típicas** | **10.8–30%** |

**Referencia:** Factor 30% → terrenos industriales en zona de baja liquidez (Ventanilla IG, 2021). Factor 10.8% → local industrial consolidado con demanda media (Puente Piedra I2, 2017).

**Regla práctica:**
- Zona prime / alta liquidez: deducciones 10–15%
- Zona secundaria / activo especializado: deducciones 20–30%

---

## 5. Benchmarks de Valor por Zona (USD/m² terreno, verificados en tasaciones reales)

| Zona | Zonificación | Año | VUT Homologado | Observaciones |
|---|---|---|---|---|
| Ventanilla (Zona Industrial) | IG | 2021 | $300/m² | Lotes 3,100–3,700m², frente 40ml |
| SJL (Av. Santa Rosa / Canto Grande) | CZ / I2 | 2025 | $560/m² | Lotes grandes 68,000m²; FD superficie 0.60 |
| Puente Piedra (Av. San Juan de Dios) | I2 | 2017 | Incluido en método costos | Local construido $3.88M, 5,890m² terreno |

**Nota SJL 2025:** Los comparables ofertados en SJL I2 van de $600 a $1,700/m² para lotes de 2,500–22,000m². El VUT homologado de $560/m² para un lote de 68,000m² refleja el descuento por superficie grande (factor 0.60) aplicado sistemáticamente.

---

## 6. Checklist de Análisis Legal × Tasación en Due Diligence

| Verificación | Fuente | Alerta si... |
|---|---|---|
| Fecha de vigencia del informe | Portada | Informe caduco (>1 año) |
| Tasadora registrada en SBS | N° REPEV del perito | Sin REPEV o vencido |
| Cuadro comparativo áreas — terreno | Hoja Resumen | RRPP ≠ HR: regularizar |
| Cuadro comparativo áreas — construcción | Hoja Resumen | HR >> RRPP: obra sin inscribir |
| Declaratoria de Fábrica | Hoja Resumen | "No Tiene" + construcción existente |
| Gravámenes declarados | Hoja Resumen | Hipoteca inscrita (cruzar con SUNARP) |
| Valor tasación vs. precio de compra | Ambos | Precio > 120% del tasado: riesgo bancario |
| Precio < 70% del tasado | Ambos | Posible distress / problema título |
| Zonificación en tasación vs. CPUE | Ambos | Discrepancia → verificar vigencia CPUE |
| Tipo de cambio aplicado | Portada | TC muy distinto al actual: ajustar valores |

---

## 7. Uso en SOLUM — Protocolo de Análisis

Cuando el usuario suba una tasación como documento adicional al análisis legal:

1. **Extraer cuadro comparativo de áreas** → cruzar con partida SUNARP (si disponible)
2. **Verificar vigencia** → fecha de expedición + 1 año = fecha límite
3. **Extraer VUT** (valor unitario terreno homologado en US$/m²) → comparar con benchmarks SOLUM
4. **Extraer valor comercial total** y tipo de cambio → convertir a S/. y USD actual
5. **Verificar declaratoria de fábrica** → "No Tiene" con construcción = hallazgo legal
6. **Reportar gravámenes** del informe → cruzar con asientos D de la partida
7. **Factor de negociación:** el VUT ya descuenta ~10–20% sobre oferta — es precio de cierre realista

**Texto modelo para hallazgo positivo:**
"Tasación hipotecaria VANET/TINSA vigente hasta [fecha]. Valor comercial US$[X] ($[Y]/m²). Cuadro comparativo sin discrepancias: RRPP = HR = Inspección. Sin declaratoria de fábrica no inscrita. Gravámenes: [descripción]."

**Texto modelo para hallazgo con alerta:**
"Tasación con vigencia hasta [fecha] — [CADUCADA si aplica]. ALERTA: construcción de [Xm²] según HR no inscrita en RRPP (diferencia +[Y]m²). Recomendado: regularizar declaratoria de fábrica antes del cierre."
