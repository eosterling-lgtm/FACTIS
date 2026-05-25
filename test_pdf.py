#!/usr/bin/env python3
"""Script de prueba — genera un PDF de muestra de Factis con datos simulados."""
import ast, datetime, pathlib, sys

# ── Extraer generar_pdf_factis de app.py sin ejecutar Streamlit ──
src = open("app.py").read()
lines = src.splitlines()

tree = ast.parse(src)
func_node = next(
    n for n in ast.walk(tree)
    if isinstance(n, ast.FunctionDef) and n.name == "generar_pdf_factis"
)
func_src = "\n".join(lines[func_node.lineno - 1 : func_node.end_lineno])

_g = {"datetime": datetime}
exec(func_src, _g)
generar_pdf_factis = _g["generar_pdf_factis"]

# ── Datos mock ───────────────────────────────────────────────────
result = {
    "resumen": {
        "ingresos_brutos":          4_500_000,
        "costo_total_sin_financ":   3_580_000,
        "costo_total":              3_580_000,
        "utilidad_bruta":             920_000,
        "margen_bruto_pct":            20.4,
        "costo_ir":                   271_000,
        "utilidad_neta":              649_000,
        "margen_pct":                  14.4,
        "tir_anual_pct":               16.8,
        "roi_pct":                     18.1,   # utilidad_neta / costo_total * 100
        "tit_pct":                     21.1,
        "costo_financiero":            92_000,
        "margen_sin_f_pct":            16.5,
        "ir_pct":                      29.5,
        # Máximos de terreno (para clasificación zona de valor)
        "max_terreno_20pct":          900_000,  # ing_brutos * 0.20
        "max_terreno_15pct":          675_000,  # ing_brutos * 0.15
        "max_terreno_12pct":          540_000,  # ing_brutos * 0.12
    },
    "detalle_costos": {
        "Terreno":                          950_000,
        "Alcabala (3%)":                     28_500,
        "Notariales":                         2_850,
        "Registrales":                        1_425,
        "Due Diligence":                     11_500,
        "Construcción departamentos":     1_380_000,
        "Sótanos":                          285_000,
        "Arquitectura":                      69_000,
        "Especialidades":                    55_200,
        "Supervisión técnica (0.5%)":         8_970,
        "Gerenciamiento (6%)":              270_000,
        "Publicidad y marketing (2.5%)":    112_500,
        "Gestión comercial (0.5%)":          22_500,
        "Comisiones de venta (3%)":         135_000,
        "Post-venta (0.5%)":                 22_500,
        "Legales y contabilidad (0.5%)":     17_000,
        "Permisos y licencias":              18_000,
        "Impuesto a la Renta (29.5%)":      271_000,
    },
    "detalle_ingresos": {
        "Departamentos 2 dormitorios":    2_700_000,
        "Departamentos 3 dormitorios":    1_500_000,
        "Estacionamientos":                 180_000,
        "Depósitos":                        120_000,
    },
}

cabida = {
    "num_pisos":           10,
    "num_sotanos":          2,
    "total_unidades":      40,
    "area_techada_total_m2": 3_200,
    "area_vendible_m2":    2_400,
    "area_libre_m2":         135,
    "estac_residentes":      32,
    "estac_visitas":          4,
    "depositos_total":       20,
    "observaciones": [
        "Retiro frontal 5 m (avenida ≥25 m de ancho)",
        "Área libre mínima 30% — cumple con parámetros RDA",
        "Colindante derecha 8 pisos — regla colindancia aplica",
    ],
    "unidades": [
        {"tipo": "2 Dormitorios", "cantidad": 30, "area_m2": 75,  "area_total_m2": 2_250},
        {"tipo": "3 Dormitorios", "cantidad":  8, "area_m2": 100, "area_total_m2":   800},
        {"tipo": "Dúplex 3D",     "cantidad":  2, "area_m2": 120, "area_total_m2":   240},
    ],
}

params = {
    "ubicacion":               "Av. Salaverry 2450, Jesús María",
    "distrito":                "Jesús María",
    "area_terreno_m2":         450,
    "frente_ml":               15,
    "zonificacion":            "RDA",
    "uso_suelo":               "Residencial Densidad Alta",
    "pisos_max":               10,
    "area_libre_min":          "30%",
    "retiro_frontal":          "5 m (avenida)",
    "coeficiente_edificacion": 7.1,
    "densidad_neta":           "2,200 hab/ha",
}

fin_inputs = {
    "nombre_proyecto":      "Torres Salaverry — Jesús María",
    "costo_terreno":        950_000,
    "precio_venta_m2":      1_875,
    "costo_construccion_m2": 920,
}

zona = "Jesús María"

legal = {
    "semaforo": "amarillo",
    "resumen_legal": (
        "El inmueble se encuentra inscrito a nombre de dos copropietarios en partes iguales. "
        "No registra hipotecas activas; sin embargo, presenta una medida cautelar de no innovar "
        "vigente derivada de proceso judicial entre los copropietarios. Se recomienda verificar "
        "el estado del proceso antes de formalizar la adquisición."
    ),
    "propietario":          "Carlos Mendoza Quispe (50%) y Ana Ríos de Mendoza (50%)",
    "area_registral":       "452.60 m²",
    "partida":              "11045872",
    "cargas":               "Ninguna",
    "hipotecas":            "Sin hipotecas activas",
    "medidas_cautelares":   "Medida cautelar de no innovar — Exp. N° 04521-2023 (Juzgado Civil Lima Norte)",
    "consistencia_area":    "Área registral 452.60 m² vs catastral 450.00 m² — diferencia 2.60 m² (0.57%)",
    "alertas": [
        "Medida cautelar de no innovar vigente: bloquea cualquier acto de disposición del inmueble "
        "hasta resolución judicial. Requiere levantamiento previo a la firma de compraventa.",
        "Copropiedad al 50%: ambos titulares deben suscribir el contrato. "
        "Verificar estado civil y poderes notariales de ser necesario.",
        "Diferencia menor de 2.60 m² entre área registral y catastral. "
        "Recomendable levantamiento topográfico antes de firmar minuta.",
    ],
    "recomendacion": (
        "Proceder con la adquisición únicamente una vez que la medida cautelar sea levantada "
        "judicialmente. El proceso puede tomar entre 60 y 120 días. Se sugiere negociar una "
        "cláusula de condición suspensiva sujeta al levantamiento de la medida y al "
        "otorgamiento de poderes notariales por ambos copropietarios."
    ),
}

# ── Generar PDF ──────────────────────────────────────────────────
pdf_bytes = generar_pdf_factis(
    result=result,
    cabida=cabida,
    params=params,
    fin_inputs=fin_inputs,
    zona=zona,
    legal=legal,
)

out = pathlib.Path("test_output_factis.pdf")
out.write_bytes(pdf_bytes)
print(f"PDF generado: {out.resolve()}  ({len(pdf_bytes):,} bytes)")
