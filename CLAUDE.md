# SOLUM — Contexto de proyecto para Claude Code

## PROTOCOLO DE INICIO DE SESIÓN (OBLIGATORIO)

Al comenzar cualquier sesión en este proyecto, ANTES de responder cualquier pregunta:

1. Confirmar que `app.py` existe en este directorio (archivo único ~19,900 líneas)
2. Tener presente que la carpeta `normativas/` contiene **80 archivos** de texto con toda la normativa activa — **LEER `CONOCIMIENTO_INDUSTRIAL_SOLUM.md` para cualquier consulta industrial**
3. El conocimiento normativo, de mercado y financiero ya está embebido en los prompts del API de Claude — NO preguntar al usuario por datos que deberían conocerse
4. Aplicar directamente: RINs, normas, benchmarks, precios de mercado, lógica financiera

**Si el usuario pregunta por estacionamientos en San Isidro → aplicar RIN San Isidro directamente (sin preguntar).**
**Si el usuario menciona un distrito → buscar en normativas/ el RIN correspondiente.**
**Si el usuario pregunta precios → usar MERCADO dict en app.py línea ~3602 o mercado_residencial_lima_urbania_2025.txt.**

---

## Quién es el usuario

**Enrique (Kike) Osterling** — advisory inmobiliario, Osterling Advisory.
- Especialización: activos comerciales, industriales y proyectos de desarrollo en Lima.
- Clientes: fondos de inversión, compañías de seguros, grupos económicos, empresas de renombre.
- Interlocución directa con C-level y gerencias de adquisiciones.
- Todo output debe ser ejecutivo, profesional, orientado a criterios financieros/riesgo institucional.
- **No hacer preguntas que el propio conocimiento normativo/financiero ya puede responder.**

---

## Qué es SOLUM

App Streamlit de pre-factibilidad inmobiliaria. Archivo único: `app.py` (~19,900 líneas).

**Propósito:** Evaluar terrenos en 15 minutos — cabida arquitectónica + análisis financiero + análisis legal. Lleva al promotor a reunirse con arquitecto/estructurista/banco con números ya trabajados, no reemplaza el expediente técnico.

**Principio de diseño:** La app hace el 90% del trabajo de pre-factibilidad. No busca exactitud milimétrica. Números deben ser defendibles y coherentes con la realidad del mercado limeño.

**Flujo:** Certificado de parámetros → cabida arquitectónica (IA) → modelo financiero con banco → reporte PDF/Excel para C-level/banco.

**Filosofía de conocimiento:** El conocimiento adicional (negociación, valorización, due diligence, normativa) se integra como contexto IA (prompts + archivos normativas/), NO como nuevas pestañas en la UI. App igual por fuera → IA mucho más inteligente por dentro.

---

## Arquitectura del código

| Función | Propósito |
|---|---|
| `extract_parameters(cert_bytes, norm_docs)` | Extrae parámetros del certificado urbanístico vía Claude API → dict |
| `generate_cabida(params, config)` | Genera programa arquitectónico por distrito → dict |
| `calcular_financiero(cabida, fin, zona)` | Análisis financiero residencial → dict |
| `calcular_oficinas(r)` | Análisis financiero oficinas (Alquiler/Compra/Desarrollo) → dict |
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
| `_load_norm(filename)` (~línea 4291) | Carga archivos normativas/ cacheados por sesión Streamlit |

**Cliente Anthropic:** `max_retries=0, timeout=120.0`, modelo `claude-sonnet-4-6`

**Dependencias clave:** streamlit, anthropic, plotly, pandas, openpyxl, reportlab, shapely, ezdxf, supabase

---

## Distritos con RIN integrado en generate_cabida (27 distritos)

San Isidro · Miraflores · Jesús María · Cercado de Lima · San Borja · Santa Anita · Surco · Surquillo · Villa El Salvador · San Juan de Lurigancho · Lince · Magdalena del Mar · La Victoria · Lurín · Lurigancho (Huachipa) · San Juan de Miraflores · San Martín de Porres · San Luis · San Miguel · La Molina · Barranco · Chorrillos · Ate · Breña · Pueblo Libre · Callao · Independencia

---

## Índice completo de normativas/ (80 archivos)

### RINs por distrito — 29 archivos / 27 distritos (estacionamientos + parámetros locales)
| Archivo | Contenido |
|---|---|
| `rin_san_isidro.txt` | RIN San Isidro (resumen operativo) |
| `rin_san_isidro_523_2020.txt` | RIN San Isidro — Ord. 523-MSI texto base |
| `rin_san_isidro_completo.txt` | Ord. 523-MSI completa (343k chars) — FUENTE PRIMARIA |
| `rin_miraflores.txt` | RIN Miraflores |
| `rin_jesus_maria.txt` | RIN Jesús María |
| `rin_cercado_lima.txt` | RIN Cercado de Lima |
| `rin_san_borja.txt` | RIN San Borja |
| `rin_santa_anita.txt` | RIN Santa Anita |
| `rin_surco.txt` | RIN Santiago de Surco |
| `rin_surquillo.txt` | RIN Surquillo |
| `rin_villa_el_salvador.txt` | RIN Villa El Salvador |
| `rin_san_juan_lurigancho.txt` | RIN San Juan de Lurigancho |
| `rin_lince.txt` | RIN Lince |
| `rin_magdalena.txt` | RIN Magdalena del Mar |
| `rin_la_victoria.txt` | RIN La Victoria |
| `rin_lurin.txt` | RIN Lurín (I3/I2/RDA/RDM — MacrOpolis, Lechucero Bajo) |
| `rin_lurigancho.txt` | RIN Lurigancho-Chosica / Huachipa (IE — ATN IV) |
| `rin_san_juan_miraflores.txt` | RIN San Juan de Miraflores (CZ/I2/RDA — ATN I) |
| `rin_san_martin_de_porres.txt` | RIN San Martín de Porres |
| `rin_san_luis.txt` | RIN San Luis |
| `rin_san_miguel.txt` | RIN San Miguel |
| `rin_la_molina.txt` | RIN La Molina |
| `rin_barranco.txt` | RIN Barranco |
| `rin_chorrillos.txt` | RIN Chorrillos |
| `rin_ate.txt` | RIN Ate |
| `rin_breña.txt` | RIN Breña |
| `rin_pueblo_libre.txt` | RIN Pueblo Libre |
| `rin_callao.txt` | RIN Callao |
| `rin_independencia.txt` | RIN Independencia |

### RNE — Reglamento Nacional de Edificaciones
| Archivo | Norma | Contenido |
|---|---|---|
| `rne_g010_consideraciones.txt` | G.010 | Consideraciones generales |
| `rne_g040_definiciones.txt` | G.040 | Definiciones técnicas (51k chars) |
| `rne_a010_condiciones.txt` | A.010 | Condiciones generales de diseño (79k chars) |
| `rne_a011_criterios_eiv.txt` | A.011 | Estudio de Impacto Vial — obligatorio gran/mediana industria |
| `rne_a020_vivienda.txt` | A.020 | Norma de vivienda (48k chars) |
| `rne_a060_industria.txt` | A.060 | Industria (resumen) |
| `rne_a060_industria_full.txt` | A.060 | Industria completa — SSHH, agua, ruido, alturas, estac. |
| `rne_a070_comercio.txt` | A.070 | Comercio (resumen) |
| `rne_a070_comercio_full.txt` | A.070 | Comercio completo |
| `rne_a080_oficinas.txt` | A.080 | Oficinas (resumen) |
| `rne_a080_oficinas_full.txt` | A.080 | Oficinas completo |
| `rne_a120_accesibilidad.txt` | A.120 | Accesibilidad — obligatorio >1,000 m² (RM 075-2023) |
| `rne_a130_seguridad.txt` | A.130 | Seguridad en uso — evacuación, señalética (3,298 chars) |
| `rne_e030_sismico.txt` | E.030 | Diseño sismorresistente |
| `rne_e050_suelos.txt` | E.050 | Mecánica de suelos — obligatorio >3 pisos en VES |
| `rne_em070_elevadores.txt` | EM.070 | Instalaciones de transporte vertical |
| `rne_gh010_hab_urbana.txt` | GH.010 | Habilitaciones urbanas generales |
| `rne_gh020_diseno_urbano.txt` | GH.020 | Diseño urbano (26k chars) |
| `rne_is010_sanitarias.txt` | IS.010 | Instalaciones sanitarias — dotaciones industriales (0.5 L/m²/turno) |
| `rne_nacional.txt` | RNE general | Reglamento Nacional síntesis |
| `rne_th010_hab_residencial.txt` | TH.010 | Habilitaciones residenciales (13k chars) |
| `rne_th010_hab_residencial_full.txt` | TH.010 | Habilitaciones residenciales completo |
| `rne_th020_hab_comercial.txt` | TH.020 | Habilitaciones comerciales |
| `rne_th030_ind_habilitacion.txt` | TH.030 | Habilitaciones industriales (resumen) |
| `rne_th030_hab_industrial_full.txt` | TH.030 | Habilitaciones industriales completo — lotes, frentes, aportes |
| `vis_vivienda_interes_social.txt` | VIS | Vivienda de interés social |

### Ordenanzas MML y zonificación Lima
| Archivo | Contenido |
|---|---|
| `ord_mml_893.txt` | Ord. 893-MML — Reajuste Integral Zonificación Cercado de Lima (2005) |
| `ord_mml_933.txt` | Ord. 933-MML — zonificación general Lima ATN I (254k chars) — base para VES, SJL, SMP, Lurín |
| `ord_mml_1012.txt` | Ord. 1012-MML — Índice de Usos Miraflores (ATN III) |
| `ord_mml_1015.txt` | Ord. 1015-MML — parámetros urbanísticos ATN II/III (325k chars) |
| `ord_mml_1144.txt` | Ord. 1144-MML — La Molina y zona sur (287k chars) |
| `ord_mml_indice_usos_area1.txt` | Índice de Usos ATN-I (230k chars, notación 0-5) |
| `indice_usos_atni.txt` | Índice de Usos ATN-I COMPLETO (392k chars, 6,349 actividades, P/H notation) — **FUENTE PRIMARIA** |
| `referencias_lima.txt` | Marco normativo general Lima — parámetros por zona/distrito |
| `certificados_parametros_lima.txt` | Colección de CPUEs reales — San Luis CZ, Miraflores CM, Callao I2, SJL I2, SMP I2, VES CZ, Lurín I2 |
| `imp_planos_zonificacion.txt` | Nota sobre mapas de zonificación (no integrables como texto) |

### Mercado e Industrial
| Archivo | Contenido |
|---|---|
| `CONOCIMIENTO_INDUSTRIAL_SOLUM.md` | **BASE DE CONOCIMIENTO INDUSTRIAL COMPLETA** — zonificación I1-I4, A.060, EIV, índice usos, parámetros por distrito, benchmarks mercado 2025, transacciones reales, operadores Lurín, perspectivas 2025-2028 |
| `mercado_residencial_lima_urbania_2025.txt` | Urbania INDEX Lima Nov 2025 — precios venta/alquiler/rentabilidad por distrito |
| `benchmarks_industrial.txt` | Parque Logístico 47 ($291.5/m² all-in, 13.6m, payback 3.74 años) + costos nave + rentas + métricas Lurín 2025 + transacciones reales VES Aldea 8/9/10 |
| `CONOCIMIENTO_RETAIL_MIXEDUSE.md` | Formatos retail Lima, métricas GLA/OCR/cap rate, mixed-use, tendencias 2025-2028 |
| `CONOCIMIENTO_NEGOCIACION_TACTICA.md` | LOI, procesos competitivos, tácticas por perfil vendedor, criterios walk-away, arbitraje |

### Normativa Legal Inmobiliaria Perú
| Archivo | Contenido |
|---|---|
| `legal_tributacion_inmobiliaria.md` | Alcabala (3%), IR ganancias capital (5% PN / 29.5% PJ), IGV primera venta, Impuesto Predial, renta arrendamiento |
| `legal_contratos_compraventa.md` | CC Arts. 1529-1601, opción de compra, arras, minuta privada, escritura pública, saneamiento, poderes |
| `legal_arrendamiento_peru.md` | CC Arts. 1666-1712, desalojo express D.Leg. 1177, garantías, resolución, mejoras, benchmarks Lima |
| `legal_derecho_registral_avanzado.md` | Anotaciones preventivas, bloqueo registral, tracto sucesivo/abreviado, impenetrabilidad, fe pública profunda, inmovilización de partida, nulidad de inscripciones — fuente: Gonzales Barrón |
| `legal_saneamiento_area_linderos.md` | Diferencia de cabida, 3 vías de saneamiento (Ley 27333 notarial / Ley 26662 no contencioso / CPC 504 judicial), plazos y costos reales, implicancias para pre-factibilidad — fuente: Gonzales Loli |
| `legal_inmatriculacion_saneamiento_avanzado.md` | Prescripción adquisitiva (judicial 18-36m / notarial 3-4m), Ley 30313 anti-fraude registral, reserva e independización de aires, habilitación urbana inscripción, COFOPRI — fuente: Huerta Ayala |
| `legal_venta_bien_futuro.md` | Contrato promotor–comprador en planos: Arts. 1534–1541 CC, cuándo transfiere la propiedad, condición suspensiva, hipoteca del promotor y carta de rescate, tipos de contrato (separación/anticipo/escritura), cláusulas abusivas, checklist comprador |
| `legal_contrato_obra_construccion.md` | Relación promotor–constructor: suma alzada vs. precios unitarios, adicionales, riesgo, garantías (carta fianza 10%, fondo retención, Art. 1784 5 años estructural), resolución, supervisión, recepción y liquidación |
| `legal_fideicomiso_inmobiliario.md` | Estructura fiduciaria D.Leg. 861: patrimonio fideicometido inembargable, hitos de desembolso, fideicomiso vs. hipoteca, liberación individual de unidades, costo en modelo financiero (0.5–1.5% anual) |
| `legal_sunarp_predios.md` | Partida registral, fe pública, prioridad, hipotecas, embargos, servidumbres, checklist DUE diligence |
| `legal_garantias_comprador_planos.md` | Ley 29571, INDECOPI, Ley 29090 licencias, Art. 1784 garantía 5 años, póliza buen uso, red flags preventa |

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

### Referencia: Parque Logístico 47 (proyecto real llave en mano)
- Área nave: 14,315m², terreno: 18,789m², ocupación: 76.2%
- Costo construcción (sin terreno): $291.5/m² nave
- Renta: $6.5/m²/mes — Yield bruto: 26.8%
- Plazo construcción: 120 días (estructura metálica prefabricada)

### Costos de nave por tipo (Lima, USD/m² nave construida)
| Tipo | Rango mercado | Referencia real |
|---|---|---|
| Almacén básico (<10m clara) | $180–325/m² | — |
| Estándar (10–12m) | $220–430/m² | — |
| Clase A (12–15m, Lurín estándar) | $430–650/m² | Simétrica: $909/m² all-in (incl. terreno) |
| Clase A (12–15m, VES/otros) | $270–310/m² | Parque Logístico 47: $291.5/m² all-in |
| Cross-docking (múltiples docks) | $380–500/m² | — |
| Manufactura (losa reforzada) | $350–450/m² | — |
| Cámara frigorífica (con equipos) | $675–1,215/m² | — |
| Patios/maniobras (losa forklift) | $60–90/m² | — |

**Nota:** El rango $430-650/m² es el costo de CONSTRUCCIÓN de nave en Lurín 2024-2025 (investigación Cushman & Wakefield + Colliers mayo 2026). El $291.5/m² de Parque Logístico 47 corresponde a un proyecto llave en mano VES 2024 con datos verificados de constructora. Ambos son válidos; la diferencia refleja calidad de acabados, especificaciones estructurales y zona.

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

---

## Zonas industriales Lima — Parámetros por distrito (2025)

### Lurín — Hub logístico líder Lima Sur
| KPI | Valor |
|---|---|
| Precio terreno (MacrOpolis / parque) | $140–200/m² |
| Precio terreno (lotización fuera parque) | $120–187/m² |
| Renta nave Clase A (h>12m, sprinklers) | $5.5–8.5/m²/mes |
| Renta promedio mercado 2025 | $6.1–6.4/m²/mes |
| Vacancia (Q3 2025) | 11.9% |
| Participación demanda Lima | 54% |
| Cap rate / Yield Clase A | 8–10% |
| Zonificación habitual | I2 (lote mín 1,000m²) |
| Normativa base | Ord. 933-MML-2006 + Ord. 1814-MML (plano feb.2024) |

**Operadores instalados:** Ransa, Mercado Libre (CD 3,000m²), Cirion Data Center LIM2 (12,000m²), Alicorp, Molitalia, Natura, Yanbal, Ecolab, MacrOpolis (350+ empresas, 1.1M m² ocupados)  
**Proyectos 2025:** Simétrica 22,381m² Clase A ($20M, entregado abr.2025), MacrOpolis Fase 3 (75,000m² en 2 fases)

### Villa El Salvador (VES) — Hub consolidado, escasez de suelo
| KPI | Valor |
|---|---|
| Precio terreno lotes grandes (~30,000m²) | $140–175/m² |
| Precio terreno lotes pequeños/residencial | $300–400/m² |
| Renta nave industrial | $5.0–7.0/m²/mes |
| Vacancia | Saturado / oferta limitada |
| Participación demanda Lima | 27% |
| Zonificación CZ (Certificado N°137-2025) | 4 PISOS FIJOS — no usa fórmula 1.5(a+r) |
| Retiro frontal CZ | 1.50 ml |
| Almacenes logísticos en CZ | PERMITIDOS (Índice Usos ATN-I) |
| Geotécnico | Obligatorio >3 pisos (suelo arenoso) |

**Transacciones reales verificadas (Aldea Logística, 2023-2024):**
- Aldea 8: 32,992m² — $5,278,741 — **$160/m²** — Ex: Fam. Wong — 2023
- Aldea 9: 32,785m² — $5,650,000 — **$172/m²** — Ex: Autorex — 2023
- Aldea 10: 35,000m² — $4,900,000 — **$140/m²** — Ex: Celima — 2024
- **Conclusión: lotes industriales grandes VES = $140–172/m². El rango $300-400/m² es para lotes pequeños.**

**Vecinos Aldea:** BSF Almacenes del Perú, DINET S.A., CD Saga Falabella, Aldea Logística Global

### Chilca — Próximo frontier logístico Lima Sur
| KPI | Valor |
|---|---|
| Precio terreno | $65–120/m² |
| Renta nave | $3.5–5.5/m²/mes |
| Vacancia | 34.1% (alta oferta disponible) |
| Participación demanda Lima | 19% |
| Perspectiva | Desplaza a Lurín y Huachipa en oferta disponible (Cushman & Wakefield nov.2025) |

### Comparativo rápido Lurín vs. Chilca vs. VES
| Zona | Terreno | Renta | Vacancia | Demanda |
|---|---|---|---|---|
| Lurín | $140-200/m² | $5.5-8.5 | 11.9% | 54% |
| Chilca | $65-120/m² | $3.5-5.5 | 34.1% | 19% |
| VES | $140-175/m² (lotes grandes) | $5.0-7.0 | Saturado | 27% |
| Huachipa | $130-135/m² | $4.5-6.0 | — | — |

### SJL / SMP (nodos emergentes)
- **SJL (San Juan de Lurigancho):** Corredor Huachipa-Lurigancho. Renta $4.5–6.0/m²/mes. Suelo más económico, acceso en desarrollo.
- **SMP (San Martín de Porres):** Zona Av. Tomás Valle. Uso mixto CZ/I2. Distancias cortas a Puerto Callao.

### Métricas macro Lima industrial (2025)
- Absorción neta anual: 83,000–95,000 m²/año
- Pipeline 2025: +500,000 m² proyectados (88% Lima Sur + Callao)
- Anillo Vial Periférico: construcción desde 2026 → reduce distancia Lurín-Callao significativamente
- Cold chain: mercado US$510M en 2025, proyectado US$625M en 2026
- E-commerce Perú: gasto digital $37B en 2024, proyectado $60B en 2027

---

## Precios de mercado residencial Lima — Noviembre 2025 (Urbania INDEX)

**Tipo de cambio referencial: ~3.75 S/./USD (referencial); TC app: 3.45 S/./USD**

### Venta (S/./m²)
| Distrito | S/./m² |
|---|---|
| San Isidro | 9,231 |
| Barranco | 9,161 |
| Miraflores | 8,670 |
| Jesús María | 7,574 |
| Lince | 7,318 |
| San Borja | 7,147 |
| Magdalena del Mar | 6,908 |
| Surquillo | 6,807 |
| Lima Index | 6,806 |
| Santiago de Surco | 6,690 |
| Pueblo Libre | 6,279 |
| San Miguel | 6,147 |
| Chorrillos | 5,718 |
| La Molina | 5,337 |

### Alquiler (S/./mes, 100m², 3 hab)
| Distrito | S/./mes |
|---|---|
| Barranco | 4,098 |
| San Isidro | 3,847 |
| Miraflores | 3,587 |
| Lima Index | 3,185 |
| San Borja | 2,757 |
| Santiago de Surco | 2,732 |
| La Molina | 2,566 |

### Rentabilidad bruta (top)
La Molina 6.3% · Surquillo 6.1% · Chorrillos 5.7% · Lima Index 5.25% · San Isidro 5.0%

---

## RIN San Isidro — Lógica de aplicación (Ord. 523-MSI)

### Deduce el Ámbito desde las áreas de las unidades:
- Unidades 40–80m² → Ámbito A (densidad alta, zona Javier Prado)
- Unidades 80–150m² → Ámbito B (densidad media, zona Basadre, Pezet, Golf)
- Unidades 150m²+ → Ámbito C (densidad baja, zona Orrantia, Monterrico)

### Ratios de estacionamiento (residencial, Ord. 523-MSI Anexo 02):
| Ámbito | Residentes | Visitas |
|---|---|---|
| A (≤80m²) | 2 cada 1 und | 25% del total |
| B (80–160m²) | 2 cada 1 und | 15% del total |
| C (>160m²) | 2 cada 1 und | 15% del total |
| D (unifamiliar) | 1 cada 1 und | 10% del total |

### Cálculo de sótanos (app):
- 25m² por cochera (incluye circulaciones)
- `c_obra_sotanos = estac_total × 25 × costo_sotano_m2 (default $450/m²)`

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
- pdfminer (NO poppler) para extracción de PDFs — poppler falla en macOS 13 Tier 3
- `--server.headless true` al lanzar Streamlit (evita prompt de email)

---

## Instrucciones de desarrollo

- Respetar la estructura de funciones existente
- No sobrecomplicar cálculos buscando precisión imposible sin datos de campo
- Cuando algo es estimación, documentarlo en observaciones para que el usuario lo sepa
- Priorizar números defendibles y coherentes con mercado limeño
- No agregar features, refactors ni abstracciones más allá de lo solicitado
- El conocimiento nuevo (negociación, due diligence, valorización) va en normativas/ como .txt, NO como tabs de UI

---

## GitHub

Repositorio: https://github.com/eosterling-lgtm/FACTIS.git (branch: main)
Para sincronizar a otra máquina: `git clone https://github.com/eosterling-lgtm/FACTIS.git`
