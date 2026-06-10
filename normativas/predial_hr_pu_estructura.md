# HOJA DE RESUMEN (HR) Y PREDIO URBANO (PU) — ESTRUCTURA Y CRITERIOS DE ANÁLISIS

## 1. Qué son estos documentos

El sistema de Impuesto Predial en Lima genera dos documentos complementarios, ambos emitidos por la Municipalidad Distrital del predio:

| Documento | Código | Función |
|---|---|---|
| **PU — Predio Urbano** (Declaración Jurada) | Nº de DJ | Detalle técnico del predio: terreno, construcción por secciones, otras instalaciones y valor de autoavalúo |
| **HR — Hoja de Resumen** | Nº de DJ | Consolida todos los predios del contribuyente en el distrito + base imponible + impuesto anual determinado |
| **Cuponera de Pago** | — | Cronograma de cuotas trimestrales del ejercicio en curso |

**Emisor:** Municipalidad Distrital (cada municipio tiene su sistema: MUNISJL, SAT, etc.)
**Vigencia:** Ejercicio fiscal anual (enero–diciembre). El documento se emite cada año o cuando hay variación.
**Código del Contribuyente:** Identificador único del propietario en esa municipalidad (ej: 540898)

---

## 2. Estructura del PU (Predio Urbano) — Campos por Sección

### Datos del Contribuyente
```
Código Contribuyente: XXXXXX (único por municipalidad)
Nombre / Razón Social: (coincide con titular registral SUNARP)
Domicilio Fiscal: (puede ser distinto al predio — especialmente personas jurídicas)
Nº Doc. Identidad: DNI / RUC
Representante Legal: nombre + DNI (para personas jurídicas)
```

### Datos del Predio
```
Código del Predio: XXXXX (distinto al código de contribuyente)
Código de Ubicación: XXXXXX
Condición de Propiedad: Propietario único / Copropietario
Tipo Adquisición: Otros / Compraventa / Herencia / etc.
Dirección del Predio: (puede diferir de la dirección en RRPP — usar RRPP como fuente primaria)
Tipo Declaración: Masiva (actualización municipal) / Voluntaria
% de Propiedad: 100.00% o fracción si hay copropiedad
Fecha de Adquisición: fecha de inscripción o transferencia
Frente: en metros lineales
```

### Características del Terreno
```
Uso del Predio: Industria / Comercio / Vivienda / etc.
Área Uso (m²): área con ese uso
Área del Terreno (m²): área total del lote (DATO CRÍTICO)
Área Común del Terreno (m²): en propiedad horizontal
Arancel (S/.): valor oficial por m² de terreno según plano arancelario municipal
```

### Características de la Construcción (por sección)
Cada sección es un bloque o nivel con características propias:

| Campo | Descripción |
|---|---|
| Nivel | 0=sótano, 1=primer piso, 2=segundo piso, etc. |
| Sección | Letra identificadora (A, B, C... AA, AB...) |
| Año Cons. | Año de construcción de esa sección |
| Antigüedad | Años al ejercicio fiscal actual |
| Clasif. Depre. | Tabla de depreciación aplicada (4 = uso industrial) |
| Mat. Pred. | Material predominante: Co=Concreto, La=Ladrillo, Ot=Otro |
| Est. Cons. | Estado de conservación: Bueno/Regular/Malo |
| Categorías M T Pi Pu R B I | Muros, Techos, Pisos, Puertas/Ventanas, Revestimientos, Baños, Instalaciones |
| Valor Unitario (S/.) | Costo de reposición por m² según tablas MVCS |
| % Depreciación | Factor por antigüedad y estado |
| Valor Dep./Inc. (S/.) | Valor unitario × (1 − depreciación/100) |
| Área Construida (m²) | Área techada de esa sección |
| Valor de Construcción (S/.) | Valor Dep. × Área Construida |

### Características de Otras Instalaciones
Obras complementarias valoradas individualmente:
- Muros de ladrillo (m²) — ej: S/.383.77/m²
- Portones de fierro (m²)
- Losa de concreto (m²) — ej: S/.136.11/m²
- Muros de contención (m³)
- Cercos perimétricos (m²)
- Cisternas, balanzas, canchas, torres de vigilancia

### Valor de Autoavalúo
```
Valor Total Terreno (S/.) = Área × Arancel municipal
Valor Total Construcción (S/.) = Suma de todas las secciones
Valor Otras Instalaciones (S/.)
─────────────────────────────────
Valor de Autoavalúo (S/.) = Suma de los tres anteriores
```

---

## 3. Estructura del HR (Hoja de Resumen) — Campos Clave

### Relación de Predios del Contribuyente (en ese distrito)
Lista TODOS los predios del propietario en el distrito con:
- Código de predio
- Dirección
- % de Propiedad
- Fecha de Adquisición
- **Valor de Autoavalúo** por predio
- Valor Exonerado (Ley 27616 u otras)
- **Valor Afecto** (base para impuesto)

### Determinación del Impuesto Predial
```
Total Predios: N
Año: XXXX
UIT: S/. 5,500 (2026)
Base Imponible: suma de todos los autoavalúos afectos
Base Exonerada: predios exonerados
Base Afecta: base imponible − exonerada

ESCALA PROGRESIVA (Art. 13 Ley 27616):
- Hasta 15 UIT: 0.20%
- Más de 15 hasta 60 UIT: 0.60%
- Más de 60 UIT: 1.00%

Impuesto Predial Anual: S/. XXXX
Cuota Trimestral: Anual / 4
```

---

## 4. Datos Reales — Ejemplos Verificados (SJL, 2026)

### Planta Celima — Av. Santa Rosa Lima Norte 1300 (predio industrial mayor)
| Dato | Valor |
|---|---|
| Propietario | Inversiones y Propiedades S.A. — RUC 20546009417 |
| Código Predio | 23559 |
| Dirección | Av. Santa Rosa de Lima Num. 1300-98, Urb. Las Flores Industrial |
| Frente | 1,261 ml |
| Área Terreno (HR/PU) | **68,433.34 m²** |
| Área Terreno (RRPP) | **70,000.00 m²** — diferencia: 1,567m² (afectación vial) |
| Área Construida (HR) | **35,700.66 m²** (33 secciones, pisos 0–3) |
| Área Construida (RRPP) | **7,548 m²** — diferencia: 28,152m² SIN DECLARATORIA |
| Uso | Industria |
| Arancel | S/. 197/m² |
| Valor Total Terreno | S/. 13,481,368 |
| Valor Total Construcción | S/. 29,845,748 |
| Valor Otras Instalaciones | S/. 1,978,279 |
| **Valor Autoavalúo** | **S/. 45,305,395** (~USD 12.3M a TC 3.68) |
| Impuesto Predial 2026 | S/. 518,127/año (cuota trimestral: S/. 129,532) |
| Años de construcción | 1983–2017 (múltiples etapas) |
| Material predominante | Concreto + algunos bloques en Ladrillo |

### Planta Camelias — Av. Los Claveles (predio industrial menor)
| Dato | Valor |
|---|---|
| Código Predio | 23557 |
| Dirección | Av. Los Claveles Mz. E, Lotes 6,7,8,9,10 acumulados |
| Frente | 95 ml |
| Área Terreno | 4,722.50 m² |
| Área Construida | 1,374.65 m² (13 secciones, 2 pisos) |
| Arancel | S/. 93/m² |
| Valor Autoavalúo | S/. 1,810,141 |
| Años construcción | 1996, 2015 |

### Portfolio completo Inversiones y Propiedades S.A. en SJL (HR 2026)
| Predio | Dirección | Valor Autoavalúo | Valor Afecto |
|---|---|---|---|
| 23559 | Av. Santa Rosa 1300 (planta principal) | S/. 45,305,395 | S/. 45,305,395 |
| 23557 | Av. Los Claveles (planta menor) | S/. 1,810,141 | S/. 1,810,141 |
| 23558 | Av. Los Claveles 636-632 | S/. 457,067 | S/. 457,067 |
| 23556 | Otros — Urb. Los Jardines | S/. 59,148 | S/. 59,148 |
| 188700 | Av. Próceres 5348 | S/. 2,055,684 | S/. 2,055,684 |
| 11354 | Av. Los Jardines Este 188 | S/. 2,290,239 | S/. 2,290,239 |
| **TOTAL** | | **S/. 51,977,674** | **S/. 51,977,674** |
| Impuesto Anual | | | **S/. 518,127** |

---

## 5. Análisis de Discrepancias HR/PU × SUNARP — Casos Tipo

### Tipo 1: Área de terreno HR < Área RRPP (Afectación Vial)
- **Ejemplo:** RRPP 70,000m² vs. HR 68,433m² → diferencia 1,567m²
- **Causa:** El municipio ya refleja afectación vial en sus planos, pero RRPP aún no se ha actualizado
- **Implicancia:** El predio real es menor al inscrito. Riesgo de rectificación de área en SUNARP
- **Severidad:** Amarillo — verificar plano de afectación municipal antes del cierre

### Tipo 2: Área construida HR >> Área inscrita RRPP (Obras sin Declaratoria)
- **Ejemplo:** HR 35,701m² vs. RRPP 7,548m² → diferencia 28,152m² SIN INSCRIBIR
- **Causa:** El propietario declaró las construcciones ante la municipalidad (para pagar predial) pero no inscribió declaratoria de fábrica en SUNARP
- **Implicancia:** Obras no inscritas no son garantía hipotecaria bancaria. El banco solo financia sobre lo inscrito
- **Severidad:** Rojo — requiere regularización de declaratoria de fábrica antes de hipotecar

### Tipo 3: Área construida RRPP >> HR (Obra Inscrita No Declarada)
- **Causa:** Declaratoria inscrita pero contribuyente no actualiza PU ante municipio
- **Implicancia:** Menor frecuente. Verificar si hay deuda predial subestimada
- **Severidad:** Amarillo

### Tipo 4: Propietario HR ≠ Propietario RRPP
- **Causa:** Transferencia inscrita pero municipalidad no fue notificada
- **Implicancia:** El vendedor puede seguir recibiendo cuponeras y tener deuda predial a su nombre
- **Severidad:** Amarillo — solicitar certificado de no adeudo predial a nombre del propietario actual

---

## 6. Impuesto Predial como Holding Cost en el Modelo Financiero

**Fórmula rápida para proyectos en pre-factibilidad:**

```
Base Afecta estimada = Área terreno × Arancel municipal × 1.3 (factor construcción estimada)
Impuesto anual ≈ Base Afecta × 0.60% (tramo más común en propiedades industriales/comerciales)
```

**Benchmarks reales:**
| Tipo de predio | Impuesto Predial |
|---|---|
| Planta industrial grande SJL (autoavalúo S/. 45M) | S/. 518K/año (~1.15%) |
| Local comercial mediano | ~0.60% del autoavalúo |
| Residencial (< 15 UIT de autoavalúo) | 0.20% |

**Nota:** El impuesto predial es un costo operativo real que debe incluirse en el DCF de holding. Para activos industriales Lima, rango típico: **0.50–1.20% del autoavalúo anual**.

---

## 7. Checklist Due Diligence HR/PU

| Verificación | Fuente | Alerta si... |
|---|---|---|
| Propietario HR = Titular RRPP | Ambos | Discrepancia → transferencia pendiente de notificar |
| Área terreno HR = Área RRPP | Ambos | HR < RRPP: afectación vial probable |
| Área construida HR = Área RRPP | Ambos | HR >> RRPP: obra sin declaratoria (ROJO) |
| Certificado de no adeudo predial | Municipalidad | Deuda predial pendiente → retención en precio |
| Uso declarado en HR | PU | Discrepancia con zonificación CPUE |
| Fecha de adquisición HR = RRPP | Ambos | Discrepancia → actualizar municipalidad |
| Representante Legal = apoderado activo | HR + Vigencia Poder | Representante con poder revocado |

---

## 8. Uso en SOLUM — Protocolo de Análisis

Cuando el usuario suba HR/PU como documento:
1. **Extraer área terreno HR** → cruzar con área partida RRPP
2. **Extraer área construida HR** → cruzar con declaratoria RRPP
3. **Verificar propietario** → debe coincidir con titular registral
4. **Reportar autoavalúo** → referencia de valor fiscal (generalmente 20–40% del valor de mercado)
5. **Calcular impuesto predial estimado** → costo holding para modelo financiero
6. **Detectar copropiedad** (% propiedad < 100%) → riesgo de consenso para venta

**Texto modelo hallazgo positivo:**
"HR/PU ejercicio [año], Municipalidad [distrito]. Área terreno HR [X m²] coincide con RRPP. Área construida HR [Y m²] coincide con declaratoria inscrita. Autoavalúo S/. [Z]. Sin adeudo predial reportado."

**Texto modelo hallazgo con alerta:**
"HR/PU [año]. ALERTA: Área construida HR [X m²] supera en [Y m²] lo inscrito en RRPP — obras sin declaratoria de fábrica. Impuesto Predial: S/. [Z]/año como costo de holding."
