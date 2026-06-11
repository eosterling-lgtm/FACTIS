#!/usr/bin/env python3
"""
test_solum_regression.py
Tests de regresión para las 4 funciones core de SOLUM.
Uso: python3 test_solum_regression.py

Approach: extrae las funciones relevantes con AST (sin importar solum.py completo,
evitando las dependencias Streamlit/Anthropic/Supabase a nivel módulo).
"""

import sys
import os
import ast
import math
import logging
import datetime
import traceback

# ─── Silenciar warnings del logging de solum ───────────────────────────────
logging.basicConfig(level=logging.CRITICAL)

SOLUM_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "solum.py")
TOLERANCIA = 0.03  # ±3%


# ─── Extractor AST ──────────────────────────────────────────────────────────

def _extract_functions(source: str, names: list[str]) -> str:
    """Extrae el código fuente de las funciones listadas usando AST."""
    tree = ast.parse(source)
    segments = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in names:
            # get_source_segment requiere Python 3.8+
            seg = ast.get_source_segment(source, node)
            if seg:
                segments.append(seg)
    return "\n\n".join(segments)


def _build_namespace() -> dict:
    """Namespace mínimo para ejecutar las funciones core."""
    import math as _math
    import datetime as _dt
    import logging as _logging

    _log = _logging.getLogger("solum_test")

    # MERCADO mínimo — solo Jesús María (necesario para calcular_financiero)
    _MERCADO = {
        "Jesús María": {
            "precio_1br": 2415, "precio_2br": 2285, "precio_3br": 2110,
            "precio_estac": 9000, "precio_deposito": 3200,
            "costo_construccion": 880,
            "velocidad_venta": 1.30, "duracion_base_meses": 24,
            "alquiler_m2_mes": 9.5, "yield_mercado_pct": 5.2, "variacion_anual_pct": 7.4,
        },
    }

    return {
        "math": _math,
        "datetime": _dt,
        "logging": _logging,
        "_log": _log,
        "MERCADO": _MERCADO,
        "__builtins__": __builtins__,
    }


# ─── Carga de funciones ──────────────────────────────────────────────────────

def load_functions() -> dict:
    """Lee solum.py, extrae las 5 funciones necesarias, las ejecuta en namespace limpio."""
    with open(SOLUM_PATH, "r", encoding="utf-8") as f:
        source = f.read()

    targets = [
        "_irr_bisect",
        "_s_curve_weights",
        "calcular_oficinas",
        "calcular_retail",
        "calcular_industrial",
        "calcular_financiero",
    ]

    code = _extract_functions(source, targets)
    ns = _build_namespace()
    exec(compile(code, "<solum_functions>", "exec"), ns)

    return ns


# ─── Helpers de assert ───────────────────────────────────────────────────────

def check(label: str, valor, esperado_min, esperado_max) -> bool:
    """Verifica que valor esté en [esperado_min, esperado_max]."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        print(f"  ❌ FAIL {label}: valor no numérico ({valor!r})")
        return False
    ok = esperado_min <= v <= esperado_max
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {status} {label}: {v:.4g} (esperado {esperado_min:.4g}–{esperado_max:.4g})")
    return ok


def check_positive(label: str, valor) -> bool:
    try:
        v = float(valor)
    except (TypeError, ValueError):
        print(f"  ❌ FAIL {label}: valor no numérico ({valor!r})")
        return False
    ok = v > 0
    status = "✅ PASS" if ok else "❌ FAIL"
    print(f"  {status} {label}: {v:.4g} (esperado > 0)")
    return ok


# ─── TEST 1: calcular_industrial ─────────────────────────────────────────────

INP_IND_LURIN = {
    "area_terreno": 15000,
    "costo_terreno": 2400000,   # $160/m²
    "tipo_nave": "Almacén Logístico",
    "zonificacion": "I2",
    "ubicacion": "Lurín",
    "pct_techada": 75,
    "uso": "Alquiler",
    "renta_m2_mes": 6.5,
    "vacancia_pct": 10,
    "dp_terreno_pct": 40,
    "tasa_terreno": 8.0,
    "plazo_terreno": 10,
    "dp_const_pct": 30,
    "tasa_const": 9.0,
    "plazo_const": 8,
    "include_alcabala": True,
    "pct_indirectos": 5.0,
}


def test_industrial(ns: dict) -> list[bool]:
    print("\n=== TEST 1: calcular_industrial — Lurín Almacén 15,000m² ===")
    results = []
    try:
        fn = ns["calcular_industrial"]
        r = fn(INP_IND_LURIN)
        assert r is not None and isinstance(r, dict), "Output es None o no es dict"

        # area_nave = 15000 * 0.75 = 11,250m²
        results.append(check("area_nave", r.get("area_nave"), 10000, 13000))

        # costo_total: terreno ~$2.4M + alcabala ~$72k + nave $480×11250 ~$5.4M + pisos $80×3750 ~$300k + soft 5% ~$285k
        # ≈ $8.46M; rango razonable 7M–11M
        results.append(check("costo_total (USD)", r.get("costo_total"), 7_000_000, 11_000_000))

        # yield_bruto: renta_total_mes = 6.5 × 11250 × 0.9 = $65,812/mes → $789k/año
        # costo ~$8.5M → yield ~9.3%; rango 7–14%
        results.append(check("yield_bruto_pct", r.get("yield_bruto"), 7.0, 14.0))

        print(f"  → costo_total: ${r.get('costo_total'):,.0f} | area_nave: {r.get('area_nave'):,.0f}m² | yield_bruto: {r.get('yield_bruto'):.1f}%")
    except Exception as e:
        print(f"  ❌ EXCEPCIÓN: {e}")
        traceback.print_exc()
        results.append(False)
    return results


# ─── TEST 2: calcular_oficinas ────────────────────────────────────────────────

INP_OFI_ALQ = {
    "modo": "Alquiler",
    "area": 500,
    "distrito": "San Isidro",
    "clase": "B",
    "alq_base": 6000,   # $12/m²/mes × 500m²
    "gastos_comunes": 2.0,
    "cocheras_n": 5,
    "cocheras_precio": 300,
    "igv": False,
    "duracion": 3,
    "garantia": 2,
    "reajuste": 3,
    "gracia": 1,
}


def test_oficinas(ns: dict) -> list[bool]:
    print("\n=== TEST 2: calcular_oficinas — San Isidro Alquiler Clase B 500m² ===")
    results = []
    try:
        fn = ns["calcular_oficinas"]
        r = fn(INP_OFI_ALQ)
        assert r is not None and isinstance(r, dict), "Output es None o no es dict"

        # pago_mensual_total = alq_base (6000) + gc (2*500=1000) + cocheras (5*300=1500) = 8500
        results.append(check("pago_mensual_total (USD)", r.get("pago_mensual_total"), 7_500, 10_000))

        # garantia_monto = alq_base × garantia_meses = 6000 × 2 = 12000
        results.append(check("garantia_monto (USD)", r.get("garantia_monto"), 10_000, 15_000))

        # costo_total_contrato > 0
        results.append(check_positive("costo_total_contrato", r.get("costo_total_contrato")))

        print(f"  → pago_mensual: ${r.get('pago_mensual_total'):,.0f} | garantia: ${r.get('garantia_monto'):,.0f} | costo_contrato: ${r.get('costo_total_contrato'):,.0f}")
    except Exception as e:
        print(f"  ❌ EXCEPCIÓN: {e}")
        traceback.print_exc()
        results.append(False)
    return results


# ─── TEST 3: calcular_retail ──────────────────────────────────────────────────

INP_RET_INV = {
    "modo": "Inversión",
    "area_gla": 2000,
    "area_total": 2500,
    "distrito": "Villa El Salvador",
    "renta_m2_mes": 18,          # S/./m²/mes — ~$5.2/m²/mes
    "vacancia_pct": 8,
    "opex_pct": 20,
    "cap_rate_mercado_pct": 8.0,
    "costo_construccion_m2": 800,
    "costo_terreno": 600000,
    "include_alcabala": True,
    "pct_indirectos": 8.0,
    "dp_terreno_pct": 40,
    "tasa_terreno": 8.0,
    "plazo_terreno": 10,
    "dp_const_pct": 30,
    "tasa_const": 9.0,
    "plazo_const": 8,
}


def test_retail(ns: dict) -> list[bool]:
    print("\n=== TEST 3: calcular_retail — Inversión VES 2,000m² GLA ===")
    results = []
    try:
        fn = ns["calcular_retail"]
        r = fn(INP_RET_INV)
        assert r is not None and isinstance(r, dict), "Output es None o no es dict"

        # noi > 0: renta_bruta_anual = 18 × 2000 × 12 × 0.92 = 397,440; opex 20% → noi ~317,952
        results.append(check_positive("noi", r.get("noi")))

        # valor_por_cap_rate = noi / (cap_rate/100) = ~317952 / 0.08 ≈ $3.97M → rango 1M–10M
        results.append(check("valor_por_cap_rate", r.get("valor_por_cap_rate"), 1_000_000, 10_000_000))

        # cap_rate (yield neto) — debe estar entre 5 y 25%
        # costo_total = 600k + 18k(alcabala) + 2000(800) = 600k+18k+2M+soft = ~2.8M
        # noi ~317k / 2.8M ~11% — rango 5–25%
        results.append(check("cap_rate (yield_neto %)", r.get("cap_rate"), 5.0, 25.0))

        print(f"  → noi: {r.get('noi'):,.0f} | valor_cap_rate: {r.get('valor_por_cap_rate'):,.0f} | cap_rate: {r.get('cap_rate'):.1f}%")
    except Exception as e:
        print(f"  ❌ EXCEPCIÓN: {e}")
        traceback.print_exc()
        results.append(False)
    return results


# ─── TEST 4: calcular_financiero ──────────────────────────────────────────────

# calcular_financiero usa claves distintas a calcular_industrial para la cabida:
# area_vendible_m2, area_techada_total_m2, total_unidades, num_pisos, estac_total, depositos_total, estac_residentes
CABIDA_TEST = {
    "area_vendible_m2": 1800,
    "area_techada_total_m2": 2500,
    "total_unidades": 15,
    "num_pisos": 5,
    "estac_total": 20,
    "estac_residentes": 15,
    "depositos_total": 15,
    "unidades": [],
}

FIN_TEST = {
    "precio_venta_m2": 7000,        # S/./m²  (≈ $2,029/m² a TC 3.45)
    "costo_construccion": 900,      # USD/m²
    "costo_terreno": 1_500_000,     # USD
    "tasa_financ": 9.0,
    "pct_preventa_banco": 30,
    "meses_obra_override": None,
    "include_alcabala": True,
    "include_dd": True,
    "tasa_ir": 29.5,
    "fee_constructora": 10.0,
    "costo_sotano_m2": 450,
}

ZONA_TEST = "Jesús María"


def test_financiero(ns: dict) -> list[bool]:
    print("\n=== TEST 4: calcular_financiero — Residencial Jesús María 15 unidades ===")
    results = []
    try:
        fn = ns["calcular_financiero"]
        r = fn(CABIDA_TEST, FIN_TEST, ZONA_TEST)
        assert r is not None and isinstance(r, dict), "Output es None o no es dict"

        res = r.get("resumen", {})

        # ingresos_ventas / ingresos_brutos > 0
        # ing_dptos = av_std * precio_m2 = 1800 × 2285 (precio_2br de Jesús María) ≈ $4.1M
        # (precio_venta_m2=7000 en FIN_TEST override al mercado → 1800×7000 = $12.6M — precio en S/. ¿?)
        # Nota: en el código precio_m2 viene de fin.get("precio_venta_m2") si >0, que aquí es 7000 (USD/m²... o S/./m²)
        # El modelo lo trata como valor directo sin conversión → ing ~$12.6M → rango amplio
        results.append(check_positive("ingresos_brutos", res.get("ingresos_brutos")))

        # margen_pct entre -50 y 100
        results.append(check("margen_neto_pct", res.get("margen_pct"), -50, 100))

        # tir_anual_pct > 0 (proyecto con precio 7000 debe ser rentable)
        results.append(check_positive("tir_anual_pct", res.get("tir_anual_pct")))

        # costo_total > 0
        results.append(check_positive("costo_total", res.get("costo_total")))

        print(f"  → ingresos_brutos: ${res.get('ingresos_brutos'):,.0f} | margen: {res.get('margen_pct'):.1f}% | TIR: {res.get('tir_anual_pct')}%")
    except Exception as e:
        print(f"  ❌ EXCEPCIÓN: {e}")
        traceback.print_exc()
        results.append(False)
    return results


# ─── Runner principal ─────────────────────────────────────────────────────────

def run_tests() -> bool:
    print("=" * 60)
    print("SOLUM — Tests de regresión funciones core")
    print(f"Archivo: {SOLUM_PATH}")
    print("=" * 60)

    try:
        print("\nCargando funciones desde solum.py via AST...")
        ns = load_functions()
        loaded = [k for k in ["calcular_industrial", "calcular_oficinas", "calcular_retail", "calcular_financiero"] if k in ns]
        print(f"  Funciones cargadas: {loaded}")
    except Exception as e:
        print(f"❌ Error cargando funciones: {e}")
        traceback.print_exc()
        return False

    all_results = []
    all_results.extend(test_industrial(ns))
    all_results.extend(test_oficinas(ns))
    all_results.extend(test_retail(ns))
    all_results.extend(test_financiero(ns))

    total  = len(all_results)
    passed = sum(all_results)

    print("\n" + "=" * 60)
    print(f"RESULTADO: {passed}/{total} tests pasaron")
    if passed == total:
        print("✅ TODOS LOS TESTS PASARON")
    else:
        failed = total - passed
        print(f"❌ {failed} test(s) fallaron")
    print("=" * 60)

    return passed == total


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
