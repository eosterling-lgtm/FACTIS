import streamlit as st
import anthropic
import base64
import hashlib
import json
import math
import os
import re
import uuid
import pathlib
import datetime
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

# Logo embebido como base64
_LOGO_PATH = pathlib.Path(__file__).parent / "logo.png"
_LOGO_B64 = base64.b64encode(_LOGO_PATH.read_bytes()).decode() if _LOGO_PATH.exists() else ""

# Wireframe imagen estado vacío
_WIRE_PATH = pathlib.Path(__file__).parent / "wireframe.png"
_WIRE_B64 = base64.b64encode(_WIRE_PATH.read_bytes()).decode() if _WIRE_PATH.exists() else ""

PROJECTS_DIR = pathlib.Path(__file__).parent / "projects"


class _Proyecto:
    """Lightweight reference to a saved project — works with Supabase or local files."""
    __slots__ = ("name", "_id", "_path")
    def __init__(self, name: str, id: str = None, path: pathlib.Path = None):
        self.name  = name
        self._id   = id
        self._path = path


def _get_supabase():
    if "_sb_client" not in st.session_state:
        try:
            from supabase import create_client
            _sb = st.secrets.get("supabase", {}) or {}
            _url = _sb.get("url", "")
            _key = _sb.get("key", "")
            st.session_state["_sb_client"] = create_client(_url, _key) if (_url and _key) else None
        except Exception:
            st.session_state["_sb_client"] = None
    return st.session_state.get("_sb_client")


def guardar_proyecto(nombre: str, estado: dict, tipo: str = "", zona: str = "") -> "_Proyecto":
    if not tipo:
        if "industrial_result" in estado:
            tipo = "industrial"
        elif "residencial_result" in estado:
            tipo = "residencial"
        else:
            tipo = "inmobiliario"
    if not zona:
        zona = str(estado.get("zona") or "")
    usuario = st.session_state.get("_username", "unknown")
    sb = _get_supabase()
    if sb:
        try:
            row = {
                "usuario": usuario,
                "nombre_proyecto": nombre.strip() or "sin_nombre",
                "tipo": tipo,
                "zona": zona,
                "datos": estado,
                "resumen": estado.get("resumen") or {},
            }
            resp = sb.table("proyectos").insert(row).execute()
            if resp.data:
                _id = resp.data[0]["id"]
                display = f"{nombre.strip() or 'sin_nombre'}  ·  {datetime.datetime.now().strftime('%d/%m/%Y')}"
                return _Proyecto(display, id=_id)
        except Exception:
            pass
    PROJECTS_DIR.mkdir(exist_ok=True)
    slug = re.sub(r"[^\w\-]", "_", nombre.strip())[:40]
    fp = PROJECTS_DIR / f"{slug}_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump({**estado, "nombre": nombre, "fecha": datetime.datetime.now().isoformat()}, f, ensure_ascii=False, indent=2)
    return _Proyecto(fp.name, path=fp)


def listar_proyectos() -> list:
    usuario = st.session_state.get("_username", "unknown")
    sb = _get_supabase()
    if sb:
        try:
            resp = (
                sb.table("proyectos")
                  .select("id, nombre_proyecto, tipo, zona, creado_en")
                  .eq("usuario", usuario)
                  .order("creado_en", desc=True)
                  .limit(50)
                  .execute()
            )
            result = []
            for row in (resp.data or []):
                fecha = (row.get("creado_en") or "")[:10]
                tipo_tag = row.get("tipo") or ""
                display = f"{row['nombre_proyecto']}  [{tipo_tag}  ·  {fecha}]"
                result.append(_Proyecto(display, id=row["id"]))
            return result
        except Exception:
            pass
    if not PROJECTS_DIR.exists():
        return []
    return [
        _Proyecto(fp.name, path=fp)
        for fp in sorted(PROJECTS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
    ]


def cargar_proyecto(ref) -> dict:
    if isinstance(ref, _Proyecto) and ref._id:
        sb = _get_supabase()
        if sb:
            try:
                resp = sb.table("proyectos").select("datos").eq("id", ref._id).single().execute()
                return (resp.data or {}).get("datos") or {}
            except Exception:
                pass
    if isinstance(ref, _Proyecto):
        path = ref._path
    elif isinstance(ref, pathlib.Path):
        path = ref
    else:
        path = pathlib.Path(str(ref))
    if path and path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _irr_bisect(flujos, lo=-0.9999, hi=10.0, tol=1e-7, max_iter=300):
    """Bisection method to find monthly IRR."""
    def npv(r):
        return sum(f / (1 + r) ** i for i, f in enumerate(flujos))
    try:
        v_lo, v_hi = npv(lo), npv(hi)
        if v_lo * v_hi > 0:
            return None
        for _ in range(max_iter):
            mid = (lo + hi) / 2
            if abs(hi - lo) < tol:
                return mid
            if npv(mid) * v_lo < 0:
                hi = mid
            else:
                lo = mid
                v_lo = npv(lo)
        return (lo + hi) / 2
    except Exception:
        return None


# ═══════════════════════════════════════════════════════
# ANÁLISIS LOGÍSTICO / INDUSTRIAL
# ═══════════════════════════════════════════════════════

def calcular_industrial(inp: dict) -> dict:
    area = inp.get("area_terreno", 0)
    costo_terreno = inp.get("costo_terreno", 0)
    tipo_nave = inp.get("tipo_nave", "Almacén Logístico")
    zonificacion = inp.get("zonificacion", "I2")
    uso = inp.get("uso", "Uso directo")

    # Área techada / libre según porcentaje definido por usuario
    pct_techada = max(min(inp.get("pct_techada", 75), 95), 30) / 100
    area_nave = area * pct_techada          # nave techada
    area_libre = area * (1 - pct_techada)   # patios, maniobras, circulación

    # Costos de construcción — usuario puede sobreescribir
    # Referencia: Parque Logístico 47 (Lima, ~14,300 m², Clase A, 13.6m clara) = $291/m² all-in
    # Industrial es 3-4x más barato que residencial: estructura metálica, sin acabados
    _DEFAULTS_NAVE = {
        "Almacén Logístico":        280,   # 12-14m clara, estructura metálica, losa industrial
        "Nave Industrial":          300,   # 10-14m, estructura metálica + concreto, uso mixto
        "Cross-docking":            420,   # docks múltiples, mayor complejidad MEP
        "Producción / Manufactura": 380,   # refuerzo de losa, instalaciones especiales
    }
    _default_nave = _DEFAULTS_NAVE.get(tipo_nave, 300)
    _cn = inp.get("costo_nave_m2")
    costo_nave_m2 = _cn if _cn is not None else _default_nave
    _cp = inp.get("costo_piso_libre_m2")
    costo_piso_libre_m2 = _cp if _cp is not None else 80

    costo_nave_total = area_nave * costo_nave_m2
    costo_pisos_libres = area_libre * costo_piso_libre_m2
    costo_construccion = costo_nave_total + costo_pisos_libres
    pct_indirectos = inp.get("pct_indirectos", 5.0) / 100
    soft_costs = costo_construccion * pct_indirectos
    alcabala = costo_terreno * 0.03 if inp.get("include_alcabala", True) else 0
    costo_total = costo_terreno + alcabala + costo_construccion + soft_costs
    costo_por_m2_nave = costo_total / area_nave if area_nave > 0 else 0

    pct_credito = min(inp.get("pct_credito", 0), 100) / 100
    tasa_anual = inp.get("tasa_anual", 8.0) / 100
    plazo_anos = max(inp.get("plazo_anos", 10), 1)
    monto_credito = costo_total * pct_credito
    capital_propio = costo_total - monto_credito

    cuota_mensual = 0.0
    if monto_credito > 0 and tasa_anual > 0:
        r = tasa_anual / 12
        n = plazo_anos * 12
        cuota_mensual = monto_credito * r * (1 + r)**n / ((1 + r)**n - 1)

    # Renta base sobre área techada (nave arrendable)
    renta_m2_mes = inp.get("renta_m2_mes", 0)
    renta_total_mes = renta_m2_mes * area_nave
    gastos_operacion = renta_total_mes * 12 * 0.08
    renta_neta_anual = max(renta_total_mes * 12 - gastos_operacion, 0)
    yield_bruto = (renta_total_mes * 12 / costo_total * 100) if costo_total > 0 else 0
    yield_neto = (renta_neta_anual / costo_total * 100) if costo_total > 0 else 0
    payback_anos = (costo_total / renta_neta_anual) if renta_neta_anual > 0 else None
    flujo_mensual = renta_total_mes - cuota_mensual if uso == "Inversión" else None
    dscr = (renta_total_mes / cuota_mensual) if cuota_mensual > 0 else None
    alquiler_vs_compra = renta_total_mes - cuota_mensual if uso == "Uso directo" else None

    # ── Indexación de renta por contrato plurianual ──
    tipo_contrato_ind    = inp.get("tipo_contrato", "Anual")
    ajuste_anual_ind_pct = inp.get("ajuste_anual_pct", 0.0) / 100
    inicio_ajuste_ind    = int(inp.get("inicio_ajuste_ano", 2))
    _es_plurianual_ind   = tipo_contrato_ind != "Anual" and ajuste_anual_ind_pct > 0

    def _renta_neta_ind(yr):
        """Renta neta anual del año yr con o sin ajuste contractual."""
        if not _es_plurianual_ind or yr < inicio_ajuste_ind:
            return renta_neta_anual
        factor = (1 + ajuste_anual_ind_pct) ** (yr - inicio_ajuste_ind + 1)
        return max(renta_total_mes * factor * 12 * (1 - 0.08), 0)

    # Proyecciones año 3 y 5 (renta mensual/m² y yield)
    _rn3 = _renta_neta_ind(3)
    _rn5 = _renta_neta_ind(5)
    renta_m2_ano3  = (_rn3 / 12 / area_nave) if area_nave > 0 else 0
    renta_m2_ano5  = (_rn5 / 12 / area_nave) if area_nave > 0 else 0
    yield_neto_ano3 = (_rn3 / costo_total * 100) if costo_total > 0 else 0
    yield_neto_ano5 = (_rn5 / costo_total * 100) if costo_total > 0 else 0

    # Payback indexado (años para recuperar inversión con renta creciente)
    payback_indexado_ind = None
    if _es_plurianual_ind and renta_neta_anual > 0:
        _acum = 0.0
        for _y in range(1, 41):
            _acum += _renta_neta_ind(_y)
            if _acum >= costo_total:
                payback_indexado_ind = _y
                break

    # ── Escudo fiscal por depreciación de la nave (Perú: 5%/año, 20 años, IR 29.5%) ──
    VIDA_UTIL_NAVE = 20        # años de vida útil tributaria (DS 122-94-EF)
    TASA_IR = 0.295            # Impuesto a la Renta corporativo Perú
    depreciacion_anual = costo_nave_total / VIDA_UTIL_NAVE   # base: solo la nave, no el terreno
    ahorro_fiscal_anual = depreciacion_anual * TASA_IR       # ahorro en IR por depreciación
    ahorro_fiscal_mensual = ahorro_fiscal_anual / 12
    # Costo efectivo mensual de compra para Uso directo (cuota – escudo fiscal)
    cuota_efectiva_mensual = max(cuota_mensual - ahorro_fiscal_mensual, 0)

    # ── IRR y flujo de caja anual (10 años, solo inversión) ──
    flujo_anual = []
    irr_anual = None
    van_10 = None
    tasa_desc = 0.10
    APRECIACION_IND = 0.03

    if uso == "Inversión" and renta_neta_anual > 0 and capital_propio > 0:
        flujo_anual = [-capital_propio]
        for yr in range(1, 11):
            cuota_yr = cuota_mensual * 12 if yr <= plazo_anos else 0
            flujo_yr = _renta_neta_ind(yr) - cuota_yr
            if yr == 10:
                saldo_deuda = 0
                if monto_credito > 0 and tasa_anual > 0 and yr <= plazo_anos:
                    r_m = tasa_anual / 12
                    n_p = yr * 12
                    saldo_deuda = max(
                        monto_credito * (1+r_m)**n_p - cuota_mensual * ((1+r_m)**n_p - 1) / r_m, 0)
                flujo_yr += costo_total * (1 + APRECIACION_IND)**10 - saldo_deuda
            flujo_anual.append(flujo_yr)
        irr_r = _irr_bisect(flujo_anual)
        irr_anual = round(irr_r * 100, 1) if irr_r is not None else None
        van_10 = sum(f / (1 + tasa_desc)**i for i, f in enumerate(flujo_anual))

    return {
        "area_terreno": area,
        "area_nave": area_nave, "area_libre": area_libre, "pct_techada": pct_techada * 100,
        "costo_terreno": costo_terreno, "alcabala": alcabala,
        "costo_nave_total": costo_nave_total, "costo_pisos_libres": costo_pisos_libres,
        "costo_construccion": costo_construccion, "soft_costs": soft_costs,
        "pct_indirectos": pct_indirectos * 100,
        "costo_total": costo_total, "costo_por_m2_nave": costo_por_m2_nave,
        "costo_nave_m2": costo_nave_m2, "costo_piso_libre_m2": costo_piso_libre_m2,
        "monto_credito": monto_credito, "capital_propio": capital_propio,
        "cuota_mensual": cuota_mensual, "pct_credito": pct_credito * 100, "plazo_anos": plazo_anos,
        "tasa_anual": tasa_anual * 100,
        "renta_m2_mes": renta_m2_mes, "renta_total_mes": renta_total_mes,
        "gastos_operacion": gastos_operacion, "renta_neta_anual": renta_neta_anual,
        "yield_bruto": yield_bruto, "yield_neto": yield_neto,
        "payback_anos": payback_anos, "flujo_mensual": flujo_mensual,
        "dscr": dscr, "alquiler_vs_compra": alquiler_vs_compra,
        "flujo_anual": flujo_anual, "irr_anual": irr_anual, "van_10": van_10,
        "tipo_nave": tipo_nave, "zonificacion": zonificacion, "uso": uso,
        # Escudo fiscal
        "depreciacion_anual": round(depreciacion_anual),
        "ahorro_fiscal_anual": round(ahorro_fiscal_anual),
        "ahorro_fiscal_mensual": round(ahorro_fiscal_mensual),
        "cuota_efectiva_mensual": round(cuota_efectiva_mensual),
        "APRECIACION_IND": APRECIACION_IND,
        # Indexación contractual
        "tipo_contrato": tipo_contrato_ind,
        "ajuste_anual_pct": round(ajuste_anual_ind_pct * 100, 2),
        "inicio_ajuste_ano": inicio_ajuste_ind,
        "renta_m2_ano3": round(renta_m2_ano3, 2),
        "renta_m2_ano5": round(renta_m2_ano5, 2),
        "yield_neto_ano3": round(yield_neto_ano3, 1),
        "yield_neto_ano5": round(yield_neto_ano5, 1),
        "payback_indexado": payback_indexado_ind,
    }


# ═══════════════════════════════════════════════════════
# ANÁLISIS RESIDENCIAL
# ═══════════════════════════════════════════════════════

def calcular_residencial(inp: dict) -> dict:
    precio = inp.get("precio", 0)
    pct_pie = max(min(inp.get("pct_pie", 20), 100), 0) / 100
    tasa_anual = inp.get("tasa_anual", 8.5) / 100
    plazo_anos = max(inp.get("plazo_anos", 20), 1)
    uso = inp.get("uso", "Vivienda propia")

    pie = precio * pct_pie
    monto_credito = precio * (1 - pct_pie)
    cuota_mensual = 0.0
    total_pagado = precio
    total_intereses = 0.0
    n_meses = plazo_anos * 12

    if monto_credito > 0 and tasa_anual > 0:
        r = tasa_anual / 12
        n = n_meses
        cuota_mensual = monto_credito * r * (1 + r)**n / ((1 + r)**n - 1)
        total_pagado = pie + cuota_mensual * n
        total_intereses = total_pagado - precio

    ingreso_minimo = cuota_mensual / 0.30 if cuota_mensual > 0 else 0

    alquiler_mes = inp.get("alquiler_mes", 0)
    gastos_mes = inp.get("gastos_mes", 0)
    renta_neta_mes = max(alquiler_mes - gastos_mes, 0)
    yield_bruto = (alquiler_mes * 12 / precio * 100) if precio > 0 else 0
    yield_neto = (renta_neta_mes * 12 / precio * 100) if precio > 0 else 0
    payback_anos = (precio / (renta_neta_mes * 12)) if renta_neta_mes > 0 else None
    flujo_mensual = renta_neta_mes - cuota_mensual if uso == "Inversión" else None
    alquiler_equilibrio = cuota_mensual + gastos_mes

    # ── Indexación de renta por contrato plurianual ──
    tipo_contrato_res    = inp.get("tipo_contrato", "Anual")
    ajuste_anual_res_pct = inp.get("ajuste_anual_pct", 0.0) / 100
    inicio_ajuste_res    = int(inp.get("inicio_ajuste_ano", 2))
    _es_plurianual_res   = tipo_contrato_res != "Anual" and ajuste_anual_res_pct > 0

    def _alquiler_ano_res(yr):
        if not _es_plurianual_res or yr < inicio_ajuste_res:
            return alquiler_mes
        return alquiler_mes * (1 + ajuste_anual_res_pct) ** (yr - inicio_ajuste_res + 1)

    def _renta_neta_ano_res(yr):
        return max(_alquiler_ano_res(yr) - gastos_mes, 0) * 12

    alquiler_ano3 = round(_alquiler_ano_res(3))
    alquiler_ano5 = round(_alquiler_ano_res(5))
    yield_neto_ano3_res = (_renta_neta_ano_res(3) / precio * 100) if precio > 0 else 0
    yield_neto_ano5_res = (_renta_neta_ano_res(5) / precio * 100) if precio > 0 else 0

    payback_indexado_res = None
    if _es_plurianual_res and renta_neta_mes > 0:
        _acum = 0.0
        for _y in range(1, 51):
            _acum += _renta_neta_ano_res(_y)
            if _acum >= precio:
                payback_indexado_res = _y
                break

    tasa_apreciacion = max(inp.get("variacion_anual_pct", 4.0), 0.0) / 100
    tasa_apreciacion = tasa_apreciacion if tasa_apreciacion > 0 else 0.04
    valor_5 = precio * ((1 + tasa_apreciacion)**5)
    valor_10 = precio * ((1 + tasa_apreciacion)**10)
    ganancia_capital_5 = valor_5 - precio
    ganancia_capital_10 = valor_10 - precio

    amort_tabla = []
    if cuota_mensual > 0 and monto_credito > 0:
        saldo = monto_credito
        r = tasa_anual / 12
        for yr in range(1, min(plazo_anos + 1, 11)):
            interes_yr = 0
            capital_yr = 0
            for _ in range(12):
                i = saldo * r
                k = cuota_mensual - i
                interes_yr += i
                capital_yr += k
                saldo = max(saldo - k, 0)
            amort_tabla.append({"año": yr, "capital": capital_yr, "interes": interes_yr, "saldo": saldo})

    return {
        "precio": precio, "pie": pie, "pct_pie": pct_pie * 100,
        "monto_credito": monto_credito, "cuota_mensual": cuota_mensual,
        "total_pagado": total_pagado, "total_intereses": total_intereses,
        "ingreso_minimo": ingreso_minimo, "plazo_anos": plazo_anos,
        "tasa_anual": tasa_anual * 100, "n_meses": n_meses,
        "alquiler_mes": alquiler_mes, "gastos_mes": gastos_mes,
        "renta_neta_mes": renta_neta_mes, "yield_bruto": yield_bruto,
        "yield_neto": yield_neto, "payback_anos": payback_anos,
        "flujo_mensual": flujo_mensual, "alquiler_equilibrio": alquiler_equilibrio,
        "valor_5": valor_5, "valor_10": valor_10,
        "ganancia_capital_5": ganancia_capital_5, "ganancia_capital_10": ganancia_capital_10,
        "amort_tabla": amort_tabla, "uso": uso,
        "tasa_apreciacion_pct": round(tasa_apreciacion * 100, 1),
        # Market / zone fields (populated by caller)
        "zona": inp.get("zona", ""),
        "dormitorios": inp.get("dormitorios", ""),
        "m2": inp.get("m2", 0),
        "antiguedad": inp.get("antiguedad", 0),
        "precio_m2": inp.get("precio_m2", 0),
        "precio_m2_mercado": inp.get("precio_m2_mercado", 0),
        "yield_mercado_pct": inp.get("yield_mercado_pct", 0),
        "alquiler_mercado_m2": inp.get("alquiler_mercado_m2", 0),
        "variacion_anual_pct": inp.get("variacion_anual_pct", 0),
        # Indexación contractual
        "tipo_contrato": tipo_contrato_res,
        "ajuste_anual_pct": round(ajuste_anual_res_pct * 100, 2),
        "inicio_ajuste_ano": inicio_ajuste_res,
        "alquiler_ano3": alquiler_ano3,
        "alquiler_ano5": alquiler_ano5,
        "yield_neto_ano3": round(yield_neto_ano3_res, 1),
        "yield_neto_ano5": round(yield_neto_ano5_res, 1),
        "payback_indexado": payback_indexado_res,
    }


# ═══════════════════════════════════════════════════════
# CALCULADORA INVERSA DE TERRENO
# ═══════════════════════════════════════════════════════

def calcular_terreno_maximo(inp: dict) -> dict:
    zona          = inp.get("zona", "")
    m             = MERCADO.get(zona, {})
    area_terreno  = inp.get("area_terreno", 0)
    area_vendible = inp.get("area_vendible", 0)
    area_techada  = inp.get("area_techada", 0)
    num_pisos     = max(inp.get("num_pisos", 7), 1)
    n_estac       = inp.get("n_estac", 0)
    n_depositos   = inp.get("n_depositos", 0)
    precio_m2     = inp.get("precio_m2", m.get("precio_2br", 0))
    costo_const   = inp.get("costo_construccion", 920)
    costo_sotano  = inp.get("costo_sotano", 450)
    fee_constr    = inp.get("fee_constructora", 10.0) / 100
    tasa_financ   = inp.get("tasa_financ", 7.0)
    tasa_ir       = inp.get("tasa_ir", 29.5) / 100

    ing_dptos    = area_vendible * precio_m2
    ing_estac    = n_estac * m.get("precio_estac", 0)
    ing_deposito = n_depositos * m.get("precio_deposito", 0)
    ing_brutos   = ing_dptos + ing_estac + ing_deposito

    c_obra_dptos   = area_techada * costo_const
    c_obra_sotanos = n_estac * 25 * costo_sotano
    c_construccion = (c_obra_dptos + c_obra_sotanos) * (1 + fee_constr)
    c_arq          = area_techada * 10.5
    c_esp          = area_techada * 4.4
    c_supervision  = c_construccion * 0.005
    c_permisos     = c_construccion * 0.005
    c_gerencia     = ing_brutos * 0.060
    c_gestion_com  = ing_brutos * 0.005
    c_publicidad   = ing_brutos * 0.025
    c_ventas       = ing_brutos * 0.030
    c_postventa    = ing_brutos * 0.005
    c_due_dilig    = 11500
    _meses_obra    = max(18, num_pisos * 2 + 8)
    c_financiero   = c_construccion * 0.40 * 0.50 * tasa_financ / 100 * (_meses_obra / 12)

    c_base_constr  = c_construccion + c_arq + c_esp
    c_legales_base = (c_due_dilig + c_base_constr) * 0.005
    # factor de transacción: alcabala 3% + notarial 0.3% + registral 0.15%
    factor_trans   = 1 + 0.03 + 0.003 + 0.0015  # 1.0345
    # c_legales también sube 0.5% del terreno: factor_trans * 0.005 extra por cada $ de terreno
    factor_terreno = factor_trans * 1.005

    C_fixed = (c_base_constr + c_supervision + c_legales_base + c_postventa + c_permisos
               + c_gerencia + c_gestion_com + c_publicidad + c_ventas
               + c_due_dilig + c_financiero)

    k = max(1 - tasa_ir, 0.01)

    resultados = {}
    for mg in [0.10, 0.12, 0.15, 0.18, 0.20]:
        target_c_total = ing_brutos * (1 - mg / k)
        T = (target_c_total - C_fixed) / factor_terreno
        resultados[mg] = max(0, round(T))

    tc = float((st.secrets.get("mercado") or {}).get("tipo_cambio", 3.45))

    return {
        "ing_brutos":    round(ing_brutos),
        "C_fixed":       round(C_fixed),
        "c_construccion": round(c_construccion),
        "c_financiero":  round(c_financiero),
        "area_terreno":  area_terreno,
        "area_vendible": area_vendible,
        "area_techada":  area_techada,
        "precio_m2":     precio_m2,
        "zona":          zona,
        "resultados":    resultados,
        "tipo_cambio":   tc,
    }


# ═══════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════

st.set_page_config(
    page_title="FACTIS — Osterling Advisory",
    page_icon="🏛",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ═══════════════════════════════════════════════════════
# LINK DE COMPARTIR — vista pública (sin login)
# ═══════════════════════════════════════════════════════

def _show_shared_view(token: str) -> None:
    logo_path = pathlib.Path(__file__).parent / "logo.png"
    logo_b64  = base64.b64encode(logo_path.read_bytes()).decode() if logo_path.exists() else ""
    st.markdown("""
    <style>
    html, body, .stApp { background: #F7F5F0 !important; }
    section[data-testid="stSidebar"], header[data-testid="stHeader"] { display:none !important; }
    .block-container { max-width:820px !important; margin:0 auto !important; padding-top:4vh !important; }
    </style>
    """, unsafe_allow_html=True)

    sb = _get_supabase()
    proyecto = None
    if sb:
        try:
            r = sb.table("proyectos").select("*").eq("share_token", token).single().execute()
            proyecto = r.data
        except Exception:
            pass

    if not proyecto:
        st.error("Este enlace no es válido o ya no está disponible.")
        return

    datos  = proyecto.get("datos") or {}
    tipo   = proyecto.get("tipo", "inmobiliario")
    nombre = proyecto.get("nombre_proyecto", "Análisis")
    zona   = proyecto.get("zona", "")
    fecha  = (proyecto.get("creado_en") or "")[:10]

    logo_html = (f'<img src="data:image/png;base64,{logo_b64}" style="height:30px;display:block;">'
                 if logo_b64 else "FACTIS")
    st.markdown(f"""
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:28px;
                padding-bottom:18px;border-bottom:2px solid #D4C9B4;">
        <div style="background:#1E2D3D;border-radius:8px;padding:8px 14px;">{logo_html}</div>
        <div>
            <div style="font-size:20px;font-weight:800;color:#1E2D3D;letter-spacing:-0.5px;">{nombre}</div>
            <div style="font-size:12px;color:#8A8070;margin-top:2px;">
                {tipo.capitalize()} · {zona} · {fecha}
            </div>
        </div>
        <div style="margin-left:auto;font-size:10px;color:#B0A090;background:#EDE9E2;
                    border-radius:20px;padding:4px 12px;font-weight:600;letter-spacing:1px;">
            SOLO LECTURA
        </div>
    </div>
    """, unsafe_allow_html=True)

    def _fmtv(v):
        try:
            return f"${float(v):,.0f}".replace(",","X").replace(".",",").replace("X",".")
        except Exception:
            return "—"
    def _fmtp(v):
        try:
            return f"{float(v):.1f}%"
        except Exception:
            return "—"

    if tipo == "inmobiliario":
        financ  = datos.get("financ") or {}
        resumen = financ.get("resumen") or {}
        cabida  = datos.get("cabida") or {}
        if resumen:
            st.markdown("#### Resumen Financiero")
            c1, c2, c3 = st.columns(3)
            c1.metric("Ingresos Brutos",   _fmtv(resumen.get("ingresos_brutos", 0)))
            c1.metric("Costo Total",        _fmtv(resumen.get("costo_total", 0)))
            c2.metric("Utilidad Neta",      _fmtv(resumen.get("utilidad_neta", 0)))
            c2.metric("Margen Neto",        _fmtp(resumen.get("margen_pct", 0)))
            c3.metric("TIR Anual",          _fmtp(resumen.get("tir_anual_pct", 0)))
            c3.metric("ROI",                _fmtp(resumen.get("roi_pct", 0)))
        if cabida:
            st.markdown("#### Cabida Arquitectónica")
            cc1, cc2, cc3 = st.columns(3)
            cc1.metric("Pisos",           cabida.get("num_pisos", "—"))
            cc2.metric("Unidades totales",cabida.get("total_unidades", "—"))
            cc3.metric("Área vendible",   f"{cabida.get('area_vendible_m2', 0):,.0f} m²")

    elif tipo == "industrial":
        r = datos.get("industrial_result") or {}
        if r:
            st.markdown("#### Análisis Industrial")
            c1, c2, c3 = st.columns(3)
            c1.metric("Costo Total",   _fmtv(r.get("costo_total", 0)))
            c1.metric("Área Nave",     f"{r.get('area_nave', 0):,.0f} m²")
            c2.metric("Yield Bruto",   _fmtp(r.get("yield_bruto", 0)))
            c2.metric("Yield Neto",    _fmtp(r.get("yield_neto", 0)))
            if r.get("irr_anual") is not None:
                c3.metric("TIR 10 años", _fmtp(r["irr_anual"]))
            if r.get("payback_anos") is not None:
                c3.metric("Payback",     f"{r['payback_anos']:.1f} años")

    elif tipo == "residencial":
        r = datos.get("residencial_result") or {}
        if r:
            st.markdown("#### Valorización del Inmueble")
            c1, c2 = st.columns(2)
            c1.metric("Valor estimado",  _fmtv(r.get("valor_mercado", 0)))
            c1.metric("Precio m²",       f"${r.get('precio_m2_mercado', 0):,.0f}/m²")
            c2.metric("Yield alquiler",  _fmtp(r.get("yield_alquiler_bruto", 0)))

    st.markdown("---")
    st.markdown(
        '<div style="text-align:center;font-size:11px;color:#8A8070;padding:10px 0;">'
        'Generado por <b>FACTIS</b> · Osterling Advisory · Este enlace es de solo lectura</div>',
        unsafe_allow_html=True)

# Verificar link compartido ANTES del login
_qt = st.query_params.get("share", "")
if _qt:
    _show_shared_view(str(_qt))
    st.stop()

# ═══════════════════════════════════════════════════════
# AUTENTICACIÓN
# ═══════════════════════════════════════════════════════

def _hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _get_users() -> dict:
    try:
        return dict(st.secrets.get("users", {}))
    except Exception:
        return {}

def _show_login() -> None:
    logo_path = pathlib.Path(__file__).parent / "logo.png"
    logo_b64  = base64.b64encode(logo_path.read_bytes()).decode() if logo_path.exists() else ""
    logo_html = (
        f'<div style="background:#FFFFFF;border-radius:10px;padding:12px 22px;display:inline-block;margin-bottom:14px;">'
        f'<img src="data:image/png;base64,{logo_b64}" style="height:38px;display:block;"></div>'
        if logo_b64 else
        '<div style="font-size:26px;font-weight:800;color:#FFFFFF;letter-spacing:-1px;margin-bottom:10px;">FACTIS</div>'
    )
    st.markdown(f"""
    <style>
    html, body, .stApp {{
        background: linear-gradient(160deg,#0A1628 0%,#131F2E 55%,#0F1C2A 100%) !important;
    }}
    section[data-testid="stSidebar"], header[data-testid="stHeader"] {{
        display: none !important;
    }}
    .block-container {{
        max-width: 400px !important;
        margin: 0 auto !important;
        padding-top: 7vh !important;
        padding-left: 0 !important;
        padding-right: 0 !important;
    }}
    /* Card visual via block-container background */
    .block-container > div:first-child {{
        background: rgba(255,255,255,0.045) !important;
        border: 1px solid rgba(255,255,255,0.10) !important;
        border-radius: 14px !important;
        padding: 32px 28px 28px !important;
    }}
    /* Labels above inputs */
    .stTextInput > label {{
        color: rgba(184,200,216,0.65) !important;
        font-size: 10px !important;
        font-weight: 700 !important;
        letter-spacing: 1.5px !important;
        text-transform: uppercase !important;
        margin-bottom: 4px !important;
    }}
    /* Input fields */
    .stTextInput input {{
        background: rgba(255,255,255,0.07) !important;
        border: 1px solid rgba(255,255,255,0.14) !important;
        color: #E8EDF2 !important;
        border-radius: 8px !important;
        font-size: 14px !important;
        padding: 10px 14px !important;
    }}
    .stTextInput input:focus {{
        border-color: rgba(184,144,74,0.60) !important;
        box-shadow: 0 0 0 2px rgba(184,144,74,0.15) !important;
    }}
    .stTextInput input::placeholder {{ color: rgba(184,200,216,0.30) !important; }}
    /* Login button */
    .stButton > button {{
        width: 100% !important;
        background: #B8904A !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 8px !important;
        font-weight: 700 !important;
        font-size: 13px !important;
        letter-spacing: 2px !important;
        padding: 13px !important;
        margin-top: 6px !important;
        text-transform: uppercase !important;
    }}
    .stButton > button:hover {{ background: #D4A853 !important; }}
    .stAlert {{ border-radius: 8px !important; font-size: 13px !important; }}
    </style>
    <div style="text-align:center;margin-bottom:28px;">
        {logo_html}
        <div style="font-size:8px;color:rgba(184,144,74,0.72);letter-spacing:4px;
                    text-transform:uppercase;font-weight:700;">Plataforma Analítica Inmobiliaria</div>
    </div>
    """, unsafe_allow_html=True)

    username = st.text_input("Usuario", placeholder="nombre de usuario", key="_login_user")
    password = st.text_input("Contraseña", type="password", placeholder="••••••••", key="_login_pw")
    if st.button("Ingresar →", key="_login_btn"):
        users = _get_users()
        user_cfg = users.get(username.strip().lower())
        if user_cfg and user_cfg.get("password") == _hash_pw(password):
            st.session_state["_authenticated"] = True
            st.session_state["_user_name"]     = user_cfg.get("name", username)
            st.session_state["_user_role"]     = user_cfg.get("role", "advisor")
            st.session_state["_username"]      = username.strip().lower()
            for _k in ("_login_pw", "_login_user", "_login_btn"):
                st.session_state.pop(_k, None)
            st.markdown('<style>body, .stApp, [data-testid] { visibility:hidden !important; }</style>',
                        unsafe_allow_html=True)
            st.rerun()
        else:
            st.error("Usuario o contraseña incorrectos.")
    st.markdown(
        '<div style="text-align:center;margin-top:22px;font-size:10px;'
        'color:rgba(184,200,216,0.28);">© Osterling Advisory · Acceso restringido</div>',
        unsafe_allow_html=True)

if not st.session_state.get("_authenticated"):
    _show_login()
    st.stop()

def _step_header(num: str, title: str) -> None:
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:10px;margin:18px 0 6px;">'
        f'<div style="background:#1E2D3D;color:#F5F2ED;font-size:10px;font-weight:700;'
        f'min-width:22px;height:22px;border-radius:50%;display:flex;align-items:center;'
        f'justify-content:center;">{num}</div>'
        f'<div style="font-size:10px;letter-spacing:2px;text-transform:uppercase;'
        f'font-weight:700;color:#1E2D3D;">{title}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');

    /* ── Base ── */
    html, body, [class*="css"], .stApp, .stMarkdown, .stMetric,
    section[data-testid="stSidebar"], .stTabs, button, input, select, textarea {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
    }

    .stApp { background-color: #F0EDE8; }

    /* ═══════════════════════════════════════
       SIDEBAR — dark navy, premium SaaS look
       ═══════════════════════════════════════ */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #131F2E 0%, #1A2D41 100%) !important;
        border-right: none !important;
        box-shadow: 4px 0 24px rgba(0,0,0,0.22) !important;
    }

    /* All sidebar text: light by default */
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] .stFileUploader label,
    section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span,
    section[data-testid="stSidebar"] small,
    section[data-testid="stSidebar"] div,
    section[data-testid="stSidebar"] .stSelectbox label,
    section[data-testid="stSidebar"] .stNumberInput label,
    section[data-testid="stSidebar"] .stTextInput label,
    section[data-testid="stSidebar"] .stTextArea label,
    section[data-testid="stSidebar"] [data-testid="stWidgetLabel"],
    section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
        color: #B8C8D8 !important;
    }

    /* Sidebar divider */
    section[data-testid="stSidebar"] hr {
        border-color: rgba(255,255,255,0.08) !important;
    }

    /* Sidebar markdown headers (h3) */
    section[data-testid="stSidebar"] h3 {
        color: #B8904A !important; font-size: 9px !important;
        letter-spacing: 2.5px !important; text-transform: uppercase !important;
        font-weight: 700 !important; padding-left: 10px !important;
        border-left: 2px solid #B8904A !important; line-height: 1.6 !important;
        margin-bottom: 8px !important;
    }

    /* Sidebar inputs — dark glass, cohesive with dark sidebar */
    /* Outer container: borde sutil, fondo oscuro, con padding para que el input no toque el borde */
    section[data-testid="stSidebar"] .stNumberInput > div,
    section[data-testid="stSidebar"] .stTextInput > div {
        background-color: rgba(255,255,255,0.08) !important;
        border: 1px solid rgba(255,255,255,0.14) !important;
        border-radius: 8px !important;
        overflow: hidden !important;
        padding: 0 !important;
        gap: 0 !important;
    }
    /* Input value area: sin separador interno — el borde del contenedor rodea todo */
    section[data-testid="stSidebar"] .stNumberInput input,
    section[data-testid="stSidebar"] .stTextInput input {
        background-color: transparent !important;
        color: #E8EDF2 !important;
        border: none !important;
        border-radius: 0 !important;
        margin: 0 !important;
        padding-left: 10px !important;
        font-size: 13px !important;
        font-weight: 500 !important;
        box-sizing: border-box !important;
    }
    section[data-testid="stSidebar"] textarea,
    section[data-testid="stSidebar"] .stTextArea textarea {
        background-color: rgba(255,255,255,0.08) !important;
        color: #E8EDF2 !important;
        border: 1px solid rgba(255,255,255,0.14) !important;
        border-radius: 8px !important;
        font-size: 13px !important;
        font-weight: 500 !important;
        padding: 8px 12px !important;
    }
    section[data-testid="stSidebar"] input::placeholder,
    section[data-testid="stSidebar"] textarea::placeholder {
        color: rgba(255,255,255,0.28) !important;
    }

    /* Number input +/− step buttons */
    section[data-testid="stSidebar"] .stNumberInput button,
    section[data-testid="stSidebar"] [data-testid="stNumberInput"] button {
        background-color: rgba(255,255,255,0.10) !important;
        color: #C8D8E8 !important;
        border: none !important;
        border-radius: 0 !important;
        font-weight: 700 !important;
        font-size: 15px !important;
        min-width: 30px !important;
        transition: background 0.15s !important;
        margin: 0 !important;
        align-self: stretch !important;
    }
    section[data-testid="stSidebar"] .stNumberInput button:hover,
    section[data-testid="stSidebar"] [data-testid="stNumberInput"] button:hover {
        background-color: rgba(184,144,74,0.28) !important;
        color: #E8C87A !important;
    }
    section[data-testid="stSidebar"] .stNumberInput button p,
    section[data-testid="stSidebar"] [data-testid="stNumberInput"] button p,
    section[data-testid="stSidebar"] .stNumberInput button span,
    section[data-testid="stSidebar"] [data-testid="stNumberInput"] button span {
        color: inherit !important;
    }

    /* Tooltip / help icon — fondo transparente, sin recuadro */
    section[data-testid="stSidebar"] [data-testid="stTooltipIcon"],
    section[data-testid="stSidebar"] [data-testid="stTooltipIcon"] button,
    section[data-testid="stSidebar"] button[aria-label*="Learn more"],
    section[data-testid="stSidebar"] button[data-testid*="tooltip"],
    section[data-testid="stSidebar"] .stTooltipIcon {
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    section[data-testid="stSidebar"] [data-testid="stTooltipIcon"] svg,
    section[data-testid="stSidebar"] [data-testid="stTooltipIcon"] button svg {
        color: rgba(255,255,255,0.30) !important;
        fill: rgba(255,255,255,0.30) !important;
    }

    /* Sidebar selectbox — dark glass */
    section[data-testid="stSidebar"] [data-baseweb="select"] > div,
    section[data-testid="stSidebar"] [data-baseweb="select"] div[class*="ValueContainer"],
    section[data-testid="stSidebar"] [data-baseweb="select"] div[class*="control"] {
        background-color: rgba(255,255,255,0.10) !important;
        border-color: rgba(255,255,255,0.16) !important;
        color: #E8EDF2 !important;
        border-radius: 6px !important;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] span,
    section[data-testid="stSidebar"] [data-baseweb="select"] div[class*="singleValue"] {
        color: #E8EDF2 !important;
        font-weight: 500 !important;
    }
    section[data-testid="stSidebar"] [data-baseweb="select"] svg {
        fill: #8AA8C8 !important;
    }

    /* Module selector radio — pill style on dark */
    section[data-testid="stSidebar"] [data-testid="stRadio"] > div {
        gap: 5px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label {
        border: 1px solid rgba(255,255,255,0.12) !important;
        border-radius: 7px !important;
        padding: 9px 14px 9px 10px !important;
        background: rgba(255,255,255,0.05) !important;
        transition: border-color 0.15s, background 0.15s !important;
        width: 100% !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {
        border-color: rgba(184,144,74,0.55) !important;
        background: rgba(184,144,74,0.10) !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label p,
    section[data-testid="stSidebar"] [data-testid="stRadio"] label span {
        font-size: 12px !important;
        font-weight: 500 !important;
        color: #A8B8C8 !important;
        letter-spacing: 0.2px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) {
        border-color: #B8904A !important;
        background: rgba(184,144,74,0.15) !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) p,
    section[data-testid="stSidebar"] [data-testid="stRadio"] label:has(input:checked) span {
        color: #E8C87A !important;
        font-weight: 700 !important;
    }
    /* Radio circle: force white border + transparent fill on dark bg */
    section[data-testid="stSidebar"] [data-testid="stRadio"] [data-baseweb="radio"] div[role="radio"],
    section[data-testid="stSidebar"] [data-testid="stRadio"] div[data-baseweb="radio"] > div {
        border-color: rgba(255,255,255,0.35) !important;
        background-color: transparent !important;
    }
    section[data-testid="stSidebar"] [data-testid="stRadio"] [aria-checked="true"] div[role="radio"],
    section[data-testid="stSidebar"] [data-testid="stRadio"] [aria-checked="true"] > div > div {
        border-color: #B8904A !important;
        background-color: #B8904A !important;
    }
    /* Hide native radio circle SVG that renders black */
    section[data-testid="stSidebar"] [data-testid="stRadio"] [data-baseweb="radio"] svg {
        display: none !important;
    }

    /* Sidebar primary buttons — gold */
    section[data-testid="stSidebar"] .stButton > button[kind="primary"],
    section[data-testid="stSidebar"] .stButton > button[kind="primary"] span,
    section[data-testid="stSidebar"] .stButton > button[kind="primary"] p {
        background: linear-gradient(135deg, #C8A050 0%, #A87830 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        box-shadow: 0 4px 12px rgba(184,144,74,0.35) !important;
        letter-spacing: 1.5px !important;
        font-size: 11px !important;
        font-weight: 700 !important;
        border-radius: 6px !important;
        transition: transform 0.15s ease, box-shadow 0.2s ease !important;
    }
    section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover,
    section[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover span {
        background: linear-gradient(135deg, #D4AC5C 0%, #B88838 100%) !important;
        color: #FFFFFF !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 24px rgba(184,144,74,0.45) !important;
    }

    /* Sidebar secondary buttons */
    section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]),
    section[data-testid="stSidebar"] .stButton > button[kind="secondary"] {
        background-color: rgba(255,255,255,0.08) !important;
        color: #B8C8D8 !important;
        border: 1px solid rgba(255,255,255,0.15) !important;
        border-radius: 6px !important;
    }
    section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]) span,
    section[data-testid="stSidebar"] .stButton > button[kind="secondary"] span {
        color: #B8C8D8 !important;
    }
    section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]):hover {
        border-color: rgba(184,144,74,0.5) !important;
        background-color: rgba(184,144,74,0.1) !important;
    }
    section[data-testid="stSidebar"] .stButton > button:not([kind="primary"]):hover span {
        color: #E8C87A !important;
    }

    /* Sidebar form submit */
    section[data-testid="stSidebar"] .stFormSubmitButton > button,
    section[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button {
        background: linear-gradient(135deg, #C8A050 0%, #A87830 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 6px !important;
        font-size: 11px !important;
        font-weight: 700 !important;
        letter-spacing: 1.5px !important;
    }
    section[data-testid="stSidebar"] .stFormSubmitButton > button span,
    section[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] > button span { color: #FFFFFF !important; }

    /* Sidebar file uploader */
    /* File uploader — sin borde punteado, solo botón limpio */
    [data-testid="stFileUploaderDropzone"],
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] {
        border: none !important;
        background: transparent !important;
        padding: 0 !important;
        min-height: unset !important;
        box-shadow: none !important;
    }
    /* Ocultar instrucciones de drag-drop */
    [data-testid="stFileUploaderDropzoneInstructions"],
    [data-testid="stFileUploaderDropzone"] [data-testid="stFileUploaderDropzoneInstructions"] {
        display: none !important;
    }
    /* Botón Upload — compacto, ancho automático */
    [data-testid="stFileUploaderDropzone"] button,
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
        padding: 5px 14px !important;
        font-size: 11px !important;
        font-weight: 600 !important;
        height: 30px !important;
        min-height: unset !important;
        border-radius: 6px !important;
        white-space: nowrap !important;
        width: auto !important;
        letter-spacing: 0.5px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button {
        background: rgba(255,255,255,0.10) !important;
        color: #C8D8E8 !important;
        border: 1px solid rgba(255,255,255,0.20) !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button:hover {
        background: rgba(184,144,74,0.20) !important;
        color: #E8C87A !important;
        border-color: rgba(184,144,74,0.45) !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderDropzone"] button span {
        color: inherit !important;
    }
    /* Archivo subido — pill dorado compacto */
    [data-testid="stFileUploaderFile"],
    section[data-testid="stSidebar"] [data-testid="stFileUploaderFile"] {
        padding: 4px 10px !important;
        border-radius: 5px !important;
        margin-top: 4px !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderFile"] {
        background-color: rgba(184,144,74,0.14) !important;
        border: 1px solid rgba(184,144,74,0.35) !important;
    }
    section[data-testid="stSidebar"] [data-testid="stFileUploaderFile"] span,
    section[data-testid="stSidebar"] [data-testid="stFileUploaderFile"] p { color: #E8C87A !important; }

    /* Sidebar expanders */
    [data-testid="stSidebar"] details,
    [data-testid="stSidebar"] details > summary,
    [data-testid="stSidebar"] [data-testid="stExpander"] {
        background-color: rgba(255,255,255,0.04) !important;
        border-color: rgba(255,255,255,0.10) !important;
        border-radius: 8px !important;
    }
    [data-testid="stSidebar"] details > summary {
        font-size: 12px !important; font-weight: 600 !important;
        letter-spacing: 0.3px !important; border-radius: 6px !important;
        padding: 9px 12px !important; color: #A8B8C8 !important;
    }
    [data-testid="stSidebar"] details > summary * { color: #A8B8C8 !important; }
    [data-testid="stSidebar"] details[open] > summary {
        border-bottom: 1px solid rgba(255,255,255,0.08) !important;
        color: #E8C87A !important;
    }
    [data-testid="stSidebar"] details[open] > summary * { color: #E8C87A !important; }

    /* Slider in sidebar */
    section[data-testid="stSidebar"] .stSlider label,
    section[data-testid="stSidebar"] .stSlider p,
    section[data-testid="stSidebar"] .stSlider span,
    section[data-testid="stSidebar"] [data-testid="stSlider"] p { color: #B8C8D8 !important; }

    /* Checkbox in sidebar */
    section[data-testid="stSidebar"] .stCheckbox label span { color: #B8C8D8 !important; }

    /* ── Header principal ── */
    .main-header {
        background: linear-gradient(135deg, #0F1C2A 0%, #1A2D41 50%, #0F1C2A 100%);
        padding: 24px 32px;
        border-radius: 12px;
        margin-bottom: 24px;
        box-shadow: 0 8px 32px rgba(10,20,35,0.28), 0 1px 0 rgba(184,144,74,0.2) inset;
        border-bottom: 2px solid rgba(184,144,74,0.25);
    }

    /* ── Cards de métricas ── */
    .metric-card {
        background: #FFFFFF;
        border: 1px solid #E4E0D8;
        border-top: 3px solid #B8904A;
        padding: 20px 20px 18px;
        border-radius: 10px;
        margin-bottom: 12px;
        box-shadow: 0 2px 12px rgba(30,45,61,0.07), 0 1px 3px rgba(30,45,61,0.05);
        transition: box-shadow 0.2s ease, transform 0.2s ease;
    }
    .metric-card:hover {
        box-shadow: 0 8px 24px rgba(30,45,61,0.12);
        transform: translateY(-2px);
    }
    .metric-card .label {
        font-size: 9px; color: #9A9080; letter-spacing: 2px;
        text-transform: uppercase; font-weight: 600;
    }
    .metric-card .value {
        font-size: 28px; color: #1E2D3D; font-weight: 800; margin-top: 8px;
        letter-spacing: -0.5px; font-variant-numeric: tabular-nums;
    }

    /* ── Sección titles ── */
    .section-title {
        color: #8A8078;
        font-size: 9px; font-weight: 700; letter-spacing: 3px;
        text-transform: uppercase;
        border-bottom: 1px solid #DDD9D0;
        padding-bottom: 8px; margin: 28px 0 16px 0;
        display: flex; align-items: center; gap: 8px;
    }
    .section-title::before {
        content: '';
        display: inline-block;
        width: 3px; height: 12px;
        background: #B8904A;
        border-radius: 2px;
        flex-shrink: 0;
    }

    /* ── KPI stat bar — rich metric display ── */
    .kpi-bar {
        display: grid; gap: 1px;
        background: #D8D4CC;
        border-radius: 10px; overflow: hidden;
        box-shadow: 0 2px 12px rgba(30,45,61,0.08);
        margin-bottom: 20px;
    }
    .kpi-cell {
        background: #FFFFFF; padding: 16px 18px;
        display: flex; flex-direction: column; gap: 4px;
    }
    .kpi-cell-label {
        font-size: 8px; color: #9A9080; letter-spacing: 2px;
        text-transform: uppercase; font-weight: 700;
    }
    .kpi-cell-value {
        font-size: 22px; color: #1E2D3D; font-weight: 800;
        letter-spacing: -0.5px; font-variant-numeric: tabular-nums;
        line-height: 1.1;
    }
    .kpi-cell-sub {
        font-size: 10px; color: #9A9080; font-weight: 500;
    }

    /* ── Alertas ── */
    .alert-gold {
        background: linear-gradient(135deg, #FFFBF3 0%, #FFF8EC 100%);
        border: 1px solid #DFC07A;
        border-left: 4px solid #B8904A; border-radius: 8px;
        padding: 14px 18px; color: #5C3D10; font-size: 13px;
        margin: 10px 0; line-height: 1.65;
        box-shadow: 0 2px 8px rgba(184,144,74,0.10);
    }
    .alert-legal {
        background: #F8F6F3; border: 1px solid #D0C8BC;
        border-left: 4px solid #8A9BAD; border-radius: 8px;
        padding: 14px 18px; color: #1E2D3D; font-size: 13px;
        margin: 10px 0; line-height: 1.65;
    }

    /* ── Tabs — underline style ── */
    .stTabs [data-baseweb="tab-list"] {
        background-color: transparent; gap: 0;
        border-bottom: 2px solid #D8D4CC;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: transparent; border: none;
        border-bottom: 3px solid transparent; margin-bottom: -2px;
        color: #8A8078; font-size: 10px; letter-spacing: 1.5px;
        text-transform: uppercase; padding: 12px 22px; font-weight: 600;
        transition: color 0.15s;
    }
    .stTabs [aria-selected="true"] {
        background-color: transparent !important;
        color: #B8904A !important;
        border-bottom: 3px solid #B8904A !important;
        font-weight: 800 !important;
    }

    /* ── Métricas nativas ── */
    div[data-testid="stMetricValue"],
    div[data-testid="stMetricValue"] > div {
        color: #1E2D3D !important; font-size: 24px !important;
        font-weight: 800 !important; letter-spacing: -0.5px !important;
        font-variant-numeric: tabular-nums !important;
    }
    div[data-testid="stMetricLabel"],
    div[data-testid="stMetricLabel"] > div,
    div[data-testid="stMetricLabel"] p,
    div[data-testid="stMetricLabel"] span,
    label[data-testid="stMetricLabel"] {
        color: #6A7888 !important; font-size: 9px !important;
        letter-spacing: 2px !important; text-transform: uppercase !important;
        font-weight: 700 !important;
    }
    div[data-testid="stMetricDelta"],
    div[data-testid="stMetricDelta"] > div {
        font-size: 11px !important;
        color: #7A8898 !important;
        background: transparent !important;
    }
    div[data-testid="stMetricDelta"] svg { display: none !important; }
    div[data-testid="stMetricDelta"] [data-testid="stMetricDeltaIcon"],
    div[data-testid="stMetricDelta"] span[class*="arrow"],
    div[data-testid="stMetricDelta"] span[class*="icon"] { display: none !important; }

    /* ── Metric container — add subtle card background ── */
    div[data-testid="metric-container"] {
        background: #FFFFFF !important;
        border: 1px solid #E8E4DC !important;
        border-radius: 10px !important;
        padding: 16px 20px !important;
        box-shadow: 0 1px 6px rgba(30,45,61,0.06) !important;
    }

    /* ── Botón primario ── */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #1E2D3D 0%, #243850 100%) !important;
        color: #FFFFFF !important;
        border: none !important; border-radius: 8px !important;
        letter-spacing: 1.5px; font-size: 11px; font-weight: 700;
        padding: 13px 22px; text-transform: uppercase;
        box-shadow: 0 4px 16px rgba(30,45,61,0.22);
        transition: background 0.2s ease, transform 0.15s ease, box-shadow 0.2s ease !important;
    }
    .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #B8904A 0%, #9A7030 100%) !important;
        transform: translateY(-2px) !important;
        box-shadow: 0 8px 24px rgba(184,144,74,0.40) !important;
    }
    .stButton > button[kind="primary"]:active {
        transform: translateY(0px) !important;
        box-shadow: 0 4px 16px rgba(30,45,61,0.22) !important;
    }
    /* Botón secundario */
    .stButton > button:not([kind="primary"]) {
        border: 1px solid #D8D4CC !important; color: #4A5568 !important;
        background: #FFFFFF !important; border-radius: 7px !important;
        font-size: 11px !important; font-weight: 600 !important;
        transition: border-color 0.15s, color 0.15s, background 0.15s !important;
    }
    .stButton > button:not([kind="primary"]):hover {
        border-color: #B8904A !important; color: #B8904A !important;
        background: #FDFAF6 !important;
    }

    /* ── Botón de descarga ── */
    [data-testid="stDownloadButton"] > button {
        background: linear-gradient(135deg, #1E2D3D 0%, #243850 100%) !important;
        color: #FFFFFF !important;
        border: none !important; border-radius: 8px !important;
        letter-spacing: 1px; font-size: 11px; font-weight: 700;
        padding: 13px 20px; width: 100%; opacity: 1 !important;
    }
    [data-testid="stDownloadButton"] > button:hover {
        background: linear-gradient(135deg, #B8904A 0%, #9A7030 100%) !important;
        opacity: 1 !important;
    }
    [data-testid="stDownloadButton"] > button:active,
    [data-testid="stDownloadButton"] > button:focus,
    [data-testid="stDownloadButton"] > button:disabled {
        background: linear-gradient(135deg, #1E2D3D 0%, #243850 100%) !important;
        color: #FFFFFF !important; opacity: 1 !important;
    }

    /* ── Spinner text ── */
    .stSpinner > div, .stSpinner p,
    [data-testid="stSpinner"] p,
    [data-testid="stSpinner"] > div { color: #1E2D3D !important; }

    /* ── Alertas nativas ── */
    [data-testid="stWarning"], [data-testid="stWarning"] p,
    [data-testid="stWarning"] span { color: #5C4000 !important; }
    div[data-testid="stInfo"], div[data-testid="stInfo"] p,
    div[data-testid="stInfo"] span, div[data-testid="stInfo"] div {
        background-color: #EEF4FB !important; color: #1E2D3D !important;
        border-color: #8AA8C0 !important;
    }
    div[data-testid="stSuccess"], div[data-testid="stSuccess"] p,
    div[data-testid="stSuccess"] span, div[data-testid="stSuccess"] div {
        background-color: #EEF8F2 !important; color: #1A4731 !important;
        border-color: #6BAE90 !important;
    }
    div[data-testid="stError"], div[data-testid="stError"] p,
    div[data-testid="stError"] span { color: #7A1A1A !important; }
    div[data-testid="stInfo"] svg path { stroke: #1E2D3D !important; fill: none !important; }
    div[data-testid="stSuccess"] svg path { stroke: #1A4731 !important; fill: none !important; }

    /* ── Dataframe ── */
    [data-testid="stDataFrame"] div[class*="dvn-scroller"],
    [data-testid="stDataFrame"] div[class*="cell-wrapper"],
    [data-testid="stDataFrame"] div[class*="cell"],
    [data-testid="stDataFrame"] span { color: #1E2D3D !important; background-color: #FFFFFF !important; }
    [data-testid="stDataFrame"] div[class*="header"],
    [data-testid="stDataFrame"] div[class*="columnHeader"] {
        background-color: #F5F2ED !important; color: #1E2D3D !important; font-weight: 700 !important;
    }
    .stDataFrame {
        border: 1px solid #D8D4CC; border-radius: 8px; overflow: hidden;
        box-shadow: 0 2px 8px rgba(30,45,61,0.06);
    }
    .stDataFrame [data-testid="stDataFrameResizable"],
    .stDataFrame iframe { background-color: #FFFFFF !important; }
    .stAlert { border-radius: 8px; }

    /* ── Inputs (main area) ── */
    .stNumberInput input, .stTextInput input,
    .stSelectbox select, .stTextArea textarea {
        background-color: #FFFFFF !important; color: #1E2D3D !important;
        border: 1px solid #D8D4CC !important; border-radius: 6px !important;
        font-size: 13px !important;
    }
    .stNumberInput input::placeholder, .stTextInput input::placeholder,
    .stTextArea textarea::placeholder { color: #9A9080 !important; }
    .stNumberInput > div, .stTextInput > div {
        background-color: #FFFFFF !important;
        border: 1px solid #D8D4CC !important; border-radius: 6px !important;
    }
    .stTextArea label, .stTextInput label, .stNumberInput label,
    .stSelectbox label, .stMultiSelect label, .stCheckbox label,
    .stRadio label, [data-testid="stWidgetLabel"] { color: #1E2D3D !important; }
    .stSlider [data-baseweb="slider"] { background-color: transparent !important; }
    .stSlider label, .stSlider p, .stSlider span,
    [data-testid="stSlider"] label, [data-testid="stSlider"] p { color: #1E2D3D !important; }

    /* ── Tablas markdown ── */
    .stMarkdown table { width:100%; border-collapse:collapse; background:#FFFFFF; border-radius:8px; overflow:hidden; }
    .stMarkdown thead th {
        background-color:#1E2D3D !important; color:#FFFFFF !important;
        padding:10px 14px; font-size:10px; letter-spacing:1.2px;
        text-transform:uppercase; border:none; font-weight:700;
    }
    .stMarkdown tbody td {
        background-color:#FFFFFF !important; color:#1E2D3D !important;
        padding:10px 14px; font-size:12px; border-bottom:1px solid #EEE;
    }
    .stMarkdown tbody tr:nth-child(even) td { background-color:#F9F7F4 !important; }
    .stMarkdown p, .stMarkdown li, .stMarkdown strong { color:#1E2D3D !important; }

    /* ── Score card ── */
    .score-card {
        border-radius: 12px; padding: 32px 36px; text-align: center;
        border: 1px solid; margin-bottom: 20px;
        box-shadow: 0 6px 24px rgba(30,45,61,0.12);
    }

    /* ── Ocultar chrome de Streamlit ── */
    header[data-testid="stHeader"]  { display: none !important; }
    [data-testid="stDecoration"]    { display: none !important; }
    [data-testid="stToolbar"]       { display: none !important; }
    #MainMenu                       { display: none !important; }
    footer                          { display: none !important; }
    [data-testid="stStatusWidget"]  { display: none !important; }
    [data-testid="stSkeleton"],
    .stSpinner > div[data-testid],
    [class*="StatusWidget"]         { display: none !important; }
    .block-container { padding-top: 1.5rem !important; }

    /* ── DataTable th/td ── */
    .stDataFrame th {
        background-color: #1E2D3D !important; color: #FFFFFF !important;
        font-size: 10px !important; font-weight: 700 !important; letter-spacing: 0.8px !important;
    }
    .stDataFrame td { background-color: #FFFFFF !important; color: #1E2D3D !important; font-size: 12px !important; }

    /* ═══════════════════════════════════════════
       RESPONSIVE — tablet (≤900px) y móvil (≤600px)
       ═══════════════════════════════════════════ */

    /* ── Tablet: iPad, laptop pequeño ── */
    @media (max-width: 900px) {
        /* Hero banner: menos padding */
        .main-header {
            padding: 18px 20px !important;
            border-radius: 10px !important;
            margin-bottom: 16px !important;
        }
        .main-header h1, .main-header .factis-title {
            font-size: 20px !important;
        }
        /* KPI bar: 2 columnas en tablet */
        .kpi-bar {
            grid-template-columns: 1fr 1fr !important;
        }
        /* Metric card value: más pequeño */
        .metric-card .value { font-size: 22px !important; }
        /* Contenido principal: menos margen lateral */
        .block-container {
            padding-left: 1.2rem !important;
            padding-right: 1.2rem !important;
        }
        /* Tabs: scroll horizontal si no caben */
        .stTabs [data-baseweb="tab-list"] {
            overflow-x: auto !important;
            flex-wrap: nowrap !important;
            -webkit-overflow-scrolling: touch;
        }
        /* DataFrames: scroll horizontal */
        .stDataFrame { overflow-x: auto !important; }
        [data-testid="stDataFrame"] { overflow-x: auto !important; }
    }

    /* ── Móvil: smartphones (≤600px) ── */
    @media (max-width: 600px) {
        /* Hero banner: compacto */
        .main-header {
            padding: 14px 16px !important;
            min-height: unset !important;
            border-radius: 8px !important;
        }
        .main-header h1, .main-header .factis-title {
            font-size: 17px !important;
            letter-spacing: -0.3px !important;
        }
        /* KPI bar: columna única en móvil */
        .kpi-bar {
            grid-template-columns: 1fr !important;
        }
        .kpi-cell {
            padding: 12px 14px !important;
            border-right: none !important;
            border-bottom: 1px solid rgba(30,45,61,0.10) !important;
        }
        /* Metric card */
        .metric-card { padding: 14px 16px !important; }
        .metric-card .value { font-size: 20px !important; }
        /* Contenido: mínimo padding lateral */
        .block-container {
            padding-left: 0.75rem !important;
            padding-right: 0.75rem !important;
            padding-top: 0.75rem !important;
        }
        /* Columnas Streamlit: apilar en móvil */
        [data-testid="column"] {
            min-width: 100% !important;
            width: 100% !important;
        }
        /* Inputs: 16px mínimo para evitar zoom en iOS */
        input, select, textarea,
        .stNumberInput input,
        .stTextInput input,
        .stSelectbox select {
            font-size: 16px !important;
        }
        /* Botones: tap target mínimo 44px */
        .stButton button {
            min-height: 44px !important;
            font-size: 13px !important;
        }
        /* Tabs: más compactos */
        .stTabs [data-baseweb="tab"] {
            padding: 8px 12px !important;
            font-size: 11px !important;
        }
        .stTabs [data-baseweb="tab-list"] {
            overflow-x: auto !important;
            flex-wrap: nowrap !important;
            -webkit-overflow-scrolling: touch;
        }
        /* Expanders: menos padding */
        .streamlit-expanderHeader {
            padding: 10px 12px !important;
            font-size: 12px !important;
        }
        /* Section titles: más compactos */
        .section-title { font-size: 8px !important; letter-spacing: 2px !important; }
        /* Plotly charts: full width */
        .js-plotly-plot, .plotly { width: 100% !important; }
        /* Ocultar sidebar overlay click area en móvil no afecta contenido */
        .stApp > header { display: none !important; }
    }

    /* ── Touch: hover effects off en táctil (evita estados pegados) ── */
    @media (hover: none) {
        .metric-card:hover {
            transform: none !important;
            box-shadow: 0 2px 12px rgba(30,45,61,0.07), 0 1px 3px rgba(30,45,61,0.05) !important;
        }
        .stButton button:hover { opacity: 1 !important; }
    }
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════
# AUTENTICACIÓN (legacy block — eliminado, ver _show_login() arriba)
# ═══════════════════════════════════════════════════════

if False:
    st.markdown("""
    <style>
    section[data-testid="stSidebar"] { display: none !important; }
    .stApp { background: linear-gradient(135deg, #1A2737 0%, #1E2D3D 60%, #1A2737 100%) !important; }

    /* ── Contenedor del input ── */
    [data-testid="stTextInput"] { background: transparent !important; }
    [data-testid="stTextInput"] > div,
    [data-testid="stTextInput"] > div > div,
    [data-testid="stTextInput"] > div > div > div {
        background: rgba(255,255,255,0.08) !important;
        border: 1px solid rgba(184,144,74,0.4) !important;
        border-radius: 6px !important;
    }
    [data-testid="stTextInput"] > div > div:focus-within,
    [data-testid="stTextInput"] > div > div > div:focus-within {
        border-color: #B8904A !important;
        box-shadow: 0 0 0 2px rgba(184,144,74,0.2) !important;
    }

    /* ── Texto escrito y puntos de contraseña ── */
    [data-testid="stTextInput"] input,
    [data-testid="stTextInput"] input[type="password"],
    [data-testid="stTextInput"] input[type="text"] {
        background: transparent !important;
        color: #FFFFFF !important;
        -webkit-text-fill-color: #FFFFFF !important;
        caret-color: #B8904A !important;
        font-size: 15px !important;
    }
    [data-testid="stTextInput"] input::placeholder {
        color: rgba(255,255,255,0.38) !important;
        -webkit-text-fill-color: rgba(255,255,255,0.38) !important;
    }

    /* ── Botón ojo de Streamlit ── */
    [data-testid="stTextInput"] button,
    [data-testid="stTextInput"] button:focus,
    [data-testid="stTextInput"] button:hover {
        background: transparent !important;
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    /* ── Div contenedor del botón ojo (quita el recuadro visible) ── */
    [data-testid="stTextInput"] div:has(> button),
    [data-testid="stTextInput"] > div > div > div > div,
    [data-testid="stTextInput"] > div > div > div > div:last-child {
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        outline: none !important;
    }
    [data-testid="stTextInput"] button svg,
    [data-testid="stTextInput"] button svg path,
    [data-testid="stTextInput"] button svg circle,
    [data-testid="stTextInput"] button svg line,
    [data-testid="stTextInput"] button svg polyline,
    [data-testid="stTextInput"] button svg ellipse {
        fill: none !important;
        stroke: #B8904A !important;
        color: #B8904A !important;
    }
    [data-testid="stTextInput"] button:hover svg path,
    [data-testid="stTextInput"] button:hover svg circle,
    [data-testid="stTextInput"] button:hover svg line,
    [data-testid="stTextInput"] button:hover svg ellipse {
        stroke: #FFFFFF !important;
    }

    /* ── Suprimir iconos del gestor de contraseñas del browser ── */
    input[type="password"]::-webkit-credentials-auto-fill-button,
    input[type="password"]::-webkit-strong-password-auto-fill-button,
    input[type="password"]::-webkit-contacts-auto-fill-button,
    input::-webkit-credentials-auto-fill-button {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
        width: 0 !important;
        height: 0 !important;
    }
    input[type="password"]::-ms-reveal,
    input[type="password"]::-ms-clear {
        display: none !important;
    }

    /* ── Label residual ── */
    [data-testid="stTextInput"] label {
        display: none !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
    }

    /* ── Suprimir "Press Enter to apply" ── */
    [data-testid="InputInstructions"],
    small[data-testid="InputInstructions"] {
        display: none !important;
        visibility: hidden !important;
        height: 0 !important;
        line-height: 0 !important;
        overflow: hidden !important;
    }

    /* ── Form sin borde ni padding extra ── */
    [data-testid="stForm"] {
        border: none !important;
        padding: 0 !important;
        background: transparent !important;
    }

    /* ── Botón ACCEDER ── */
    [data-testid="stFormSubmitButton"] > button {
        background: #B8904A !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 6px !important;
        font-size: 12px !important;
        font-weight: 700 !important;
        letter-spacing: 3px !important;
        padding: 12px 0 !important;
        width: 100% !important;
        margin-top: 4px !important;
        transition: background 0.2s ease !important;
    }
    [data-testid="stFormSubmitButton"] > button:hover {
        background: #C9A05A !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # Desactivar autocomplete del browser en el input de contraseña
    st.markdown("""
    <script>
    window.addEventListener('load', function() {
        const inputs = document.querySelectorAll('input[type="password"]');
        inputs.forEach(function(inp) {
            inp.setAttribute('autocomplete', 'new-password');
        });
    });
    </script>
    """, unsafe_allow_html=True)

    _l, _c, _r = st.columns([1, 1.1, 1])
    with _c:
        st.markdown("<div style='height:12vh'></div>", unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align:center;padding:44px 48px 36px;
                    background:rgba(255,255,255,0.04);
                    border:1px solid rgba(184,144,74,0.22);
                    border-radius:10px;">
            <div style="font-size:9px;color:#B8904A;letter-spacing:5px;text-transform:uppercase;
                        font-weight:600;margin-bottom:18px;">Osterling Advisory</div>
            <div style="font-size:30px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;">FACTIS</div>
            <div style="width:40px;height:2px;background:#B8904A;margin:16px auto 20px;"></div>
            <div style="font-size:12px;color:#8AA8C0;letter-spacing:0.3px;margin-bottom:8px;">
                Plataforma Analítica Inmobiliaria
            </div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)
        with st.form("login_form", border=False):
            _pwd = st.text_input("Contraseña", type="password", placeholder="Contraseña de acceso",
                                 label_visibility="collapsed", key="_login_pwd")
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)
            _submitted = st.form_submit_button("ACCEDER", use_container_width=True)
            if _submitted:
                if _pwd == _APP_PWD:
                    st.session_state._auth = True
                    st.rerun()
                else:
                    st.error("Contraseña incorrecta.")
    st.stop()

# ═══════════════════════════════════════════════════════
# DATOS DE MERCADO LIMA 2025-2026
# Fuente precios venta: Índice Urbania — Lima, Noviembre 2025
# Tipo de cambio: 3.42 S./USD (SUNAT cierre 24-may-2026)
# Base: mediana distrital S./m² convertida a USD/m²
# Ratios tipológicos (índice Urbania): 2br=+4%, 3br=-4%, 1br=+10% sobre mediana
# Estacionamientos / depósitos: estimados mercado 2024-2026
# ═══════════════════════════════════════════════════════

MERCADO = {
    # ── Fuente: Urbania Lima Index Nov-2025 · Tipo cambio: 3.45 S./USD
    # ── Tipología: 1br = base×1.10, 2br = base×1.04, 3br = base×0.96
    # ── Ordenado alfabéticamente por distrito
    "Ancón": {                                     # est. ~2,700 S./m² → $789/m²
        "precio_1br": 870,  "precio_2br": 820,  "precio_3br": 760,
        "precio_estac": 3500, "precio_deposito": 1000,
        "costo_construccion": 808,
        "velocidad_venta": 2.20, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.2, "yield_mercado_pct": 4.9, "variacion_anual_pct": 0.5,
    },
    "Ate": {                                       # Urbania: 4,531 S./m² → $1,313/m² (TC 3.45)
        "precio_1br": 1445, "precio_2br": 1365, "precio_3br": 1260,
        "precio_estac": 7000, "precio_deposito": 2500,
        "costo_construccion": 850,
        "velocidad_venta": 1.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 5.8, "yield_mercado_pct": 5.3, "variacion_anual_pct": -1.6,
    },
    "Barranco": {                                  # Urbania: 9,161 S./m² → $2,655/m² (TC 3.45)
        "precio_1br": 2920, "precio_2br": 2760, "precio_3br": 2550,
        "precio_estac": 14000, "precio_deposito": 5000,
        "costo_construccion": 1000,
        "velocidad_venta": 0.80, "duracion_base_meses": 30,
        "alquiler_m2_mes": 11.9, "yield_mercado_pct": 5.1, "variacion_anual_pct": -2.5,
    },
    "Breña": {                                     # Urbania: 5,222 S./m² → $1,514/m² (TC 3.45)
        "precio_1br": 1665, "precio_2br": 1575, "precio_3br": 1455,
        "precio_estac": 6000, "precio_deposito": 2000,
        "costo_construccion": 840,
        "velocidad_venta": 1.10, "duracion_base_meses": 26,
        "alquiler_m2_mes": 6.8, "yield_mercado_pct": 5.4, "variacion_anual_pct": 2.8,
    },
    "Callao": {                                    # Urbania: 3,239 S./m² → $939/m² (TC 3.45)
        "precio_1br": 1035, "precio_2br": 975,  "precio_3br": 900,
        "precio_estac": 5000, "precio_deposito": 1500,
        "costo_construccion": 820,
        "velocidad_venta": 1.30, "duracion_base_meses": 26,
        "alquiler_m2_mes": 4.1, "yield_mercado_pct": 5.3, "variacion_anual_pct": -9.1,
    },
    "Carabayllo": {                                # est. ~3,200 S./m² → $936/m²
        "precio_1br": 1030, "precio_2br": 975,  "precio_3br": 900,
        "precio_estac": 4000, "precio_deposito": 1400,
        "costo_construccion": 815,
        "velocidad_venta": 1.80, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.0, "yield_mercado_pct": 5.0, "variacion_anual_pct": 0.8,
    },
    "Cercado de Lima": {                           # Urbania: 6,253 S./m² → $1,813/m² (TC 3.45)
        "precio_1br": 1995, "precio_2br": 1885, "precio_3br": 1740,
        "precio_estac": 7000, "precio_deposito": 2500,
        "costo_construccion": 870,
        "velocidad_venta": 0.90, "duracion_base_meses": 28,
        "alquiler_m2_mes": 8.9, "yield_mercado_pct": 5.6, "variacion_anual_pct": 9.8,
    },
    "Chaclacayo": {                                # est. ~2,600 S./m² → $760/m²
        "precio_1br": 835,  "precio_2br": 790,  "precio_3br": 730,
        "precio_estac": 4000, "precio_deposito": 1200,
        "costo_construccion": 810,
        "velocidad_venta": 2.00, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.2, "yield_mercado_pct": 5.0, "variacion_anual_pct": 0.5,
    },
    "Chorrillos": {                                # Urbania: 5,718 S./m² → $1,658/m² (TC 3.45)
        "precio_1br": 1825, "precio_2br": 1725, "precio_3br": 1590,
        "precio_estac": 8500, "precio_deposito": 3000,
        "costo_construccion": 880,
        "velocidad_venta": 1.20, "duracion_base_meses": 26,
        "alquiler_m2_mes": 7.4, "yield_mercado_pct": 5.7, "variacion_anual_pct": -1.7,
    },
    "Cieneguilla": {                               # est. ~2,050 S./m² → $600/m²
        "precio_1br": 660,  "precio_2br": 625,  "precio_3br": 575,
        "precio_estac": 3500, "precio_deposito": 1000,
        "costo_construccion": 800,
        "velocidad_venta": 2.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 2.8, "yield_mercado_pct": 5.5, "variacion_anual_pct": 0.5,
    },
    "Comas": {                                     # est. ~3,490 S./m² → $1,020/m²
        "precio_1br": 1120, "precio_2br": 1060, "precio_3br": 980,
        "precio_estac": 4500, "precio_deposito": 1500,
        "costo_construccion": 820,
        "velocidad_venta": 1.70, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.5, "yield_mercado_pct": 5.1, "variacion_anual_pct": 1.0,
    },
    "El Agustino": {                               # est. ~3,933 S./m² → $1,150/m²
        "precio_1br": 1265, "precio_2br": 1195, "precio_3br": 1105,
        "precio_estac": 5000, "precio_deposito": 1700,
        "costo_construccion": 840,
        "velocidad_venta": 1.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 5.5, "yield_mercado_pct": 5.5, "variacion_anual_pct": 1.5,
    },
    "Independencia": {                             # est. ~3,762 S./m² → $1,100/m²
        "precio_1br": 1210, "precio_2br": 1145, "precio_3br": 1055,
        "precio_estac": 4500, "precio_deposito": 1500,
        "costo_construccion": 820,
        "velocidad_venta": 1.70, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.5, "yield_mercado_pct": 5.1, "variacion_anual_pct": 1.0,
    },
    "Jesús María": {                               # Urbania: 7,574 S./m² → $2,196/m² (TC 3.45)
        "precio_1br": 2415, "precio_2br": 2285, "precio_3br": 2110,
        "precio_estac": 9000, "precio_deposito": 3200,
        "costo_construccion": 880,
        "velocidad_venta": 1.30, "duracion_base_meses": 24,
        "alquiler_m2_mes": 9.5, "yield_mercado_pct": 5.2, "variacion_anual_pct": 7.4,
    },
    "La Molina": {                                 # Urbania: 5,337 S./m² → $1,547/m² (TC 3.45)
        "precio_1br": 1700, "precio_2br": 1610, "precio_3br": 1485,
        "precio_estac": 9000, "precio_deposito": 3200,
        "costo_construccion": 870,
        "velocidad_venta": 1.40, "duracion_base_meses": 24,
        "alquiler_m2_mes": 7.4, "yield_mercado_pct": 6.3, "variacion_anual_pct": -3.6,
    },
    "La Victoria": {                               # Urbania: 6,882 S./m² → $1,995/m² (TC 3.45) · +14.9%
        "precio_1br": 2195, "precio_2br": 2075, "precio_3br": 1915,
        "precio_estac": 6500, "precio_deposito": 2200,
        "costo_construccion": 860,
        "velocidad_venta": 1.00, "duracion_base_meses": 26,
        "alquiler_m2_mes": 10.5, "yield_mercado_pct": 6.3, "variacion_anual_pct": 14.9,
    },
    "Lince": {                                     # Urbania: 7,318 S./m² → $2,121/m² (TC 3.45)
        "precio_1br": 2335, "precio_2br": 2205, "precio_3br": 2035,
        "precio_estac": 8500, "precio_deposito": 3000,
        "costo_construccion": 875,
        "velocidad_venta": 1.20, "duracion_base_meses": 26,
        "alquiler_m2_mes": 9.9, "yield_mercado_pct": 5.6, "variacion_anual_pct": -1.4,
    },
    "Los Olivos": {                                # Urbania: 3,557 S./m² → $1,031/m² (TC 3.45)
        "precio_1br": 1135, "precio_2br": 1070, "precio_3br": 990,
        "precio_estac": 5000, "precio_deposito": 1600,
        "costo_construccion": 820,
        "velocidad_venta": 1.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.5, "yield_mercado_pct": 5.2, "variacion_anual_pct": -3.1,
    },
    "Lurigancho": {                                # est. ~3,078 S./m² → $900/m²
        "precio_1br": 990,  "precio_2br": 935,  "precio_3br": 865,
        "precio_estac": 4000, "precio_deposito": 1300,
        "costo_construccion": 810,
        "velocidad_venta": 1.90, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.8, "yield_mercado_pct": 5.0, "variacion_anual_pct": 0.5,
    },
    "Lurín": {                                     # est. ~2,736 S./m² → $800/m²
        "precio_1br": 880,  "precio_2br": 830,  "precio_3br": 770,
        "precio_estac": 4000, "precio_deposito": 1200,
        "costo_construccion": 810,
        "velocidad_venta": 2.00, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.5, "yield_mercado_pct": 5.0, "variacion_anual_pct": 0.0,
    },
    "Magdalena del Mar": {                         # Urbania: 6,908 S./m² → $2,002/m² (TC 3.45)
        "precio_1br": 2200, "precio_2br": 2080, "precio_3br": 1920,
        "precio_estac": 8500, "precio_deposito": 3000,
        "costo_construccion": 870,
        "velocidad_venta": 1.10, "duracion_base_meses": 26,
        "alquiler_m2_mes": 9.1, "yield_mercado_pct": 5.3, "variacion_anual_pct": 3.4,
    },
    "Miraflores": {                                # Urbania: 8,670 S./m² → $2,513/m² (TC 3.45)
        "precio_1br": 2765, "precio_2br": 2615, "precio_3br": 2415,
        "precio_estac": 15000, "precio_deposito": 5500,
        "costo_construccion": 1050,
        "velocidad_venta": 0.80, "duracion_base_meses": 30,
        "alquiler_m2_mes": 10.4, "yield_mercado_pct": 5.0, "variacion_anual_pct": -0.5,
    },
    "Pachacámac": {                                # est. ~2,905 S./m² → $850/m²
        "precio_1br": 935,  "precio_2br": 885,  "precio_3br": 815,
        "precio_estac": 4000, "precio_deposito": 1200,
        "costo_construccion": 810,
        "velocidad_venta": 2.00, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.5, "yield_mercado_pct": 5.0, "variacion_anual_pct": 0.0,
    },
    "Pueblo Libre": {                              # Urbania: 6,279 S./m² → $1,820/m² (TC 3.45)
        "precio_1br": 2000, "precio_2br": 1895, "precio_3br": 1750,
        "precio_estac": 8500, "precio_deposito": 3000,
        "costo_construccion": 880,
        "velocidad_venta": 1.20, "duracion_base_meses": 26,
        "alquiler_m2_mes": 8.6, "yield_mercado_pct": 5.7, "variacion_anual_pct": 1.3,
    },
    "Pucusana": {                                  # costa sur, balneario → est. $720/m²
        "precio_1br": 790,  "precio_2br": 750,  "precio_3br": 690,
        "precio_estac": 3500, "precio_deposito": 1000,
        "costo_construccion": 800,
        "velocidad_venta": 2.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.0, "yield_mercado_pct": 5.0, "variacion_anual_pct": 0.5,
    },
    "Puente Piedra": {                             # est. ~2,907 S./m² → $850/m²
        "precio_1br": 935,  "precio_2br": 885,  "precio_3br": 815,
        "precio_estac": 4500, "precio_deposito": 1500,
        "costo_construccion": 820,
        "velocidad_venta": 1.80, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.0, "yield_mercado_pct": 5.5, "variacion_anual_pct": 1.0,
    },
    "Punta Hermosa": {                             # balneario premium → est. $1,200/m²
        "precio_1br": 1320, "precio_2br": 1250, "precio_3br": 1150,
        "precio_estac": 6000, "precio_deposito": 2000,
        "costo_construccion": 850,
        "velocidad_venta": 1.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 5.5, "yield_mercado_pct": 5.3, "variacion_anual_pct": 1.5,
    },
    "Punta Negra": {                               # balneario costa sur → est. $950/m²
        "precio_1br": 1045, "precio_2br": 990,  "precio_3br": 910,
        "precio_estac": 5000, "precio_deposito": 1500,
        "costo_construccion": 830,
        "velocidad_venta": 1.80, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.0, "yield_mercado_pct": 5.1, "variacion_anual_pct": 1.0,
    },
    "La Perla": {                                  # Urbania: 4,393 S./m² → $1,274/m² (TC 3.45)
        "precio_1br": 1400, "precio_2br": 1325, "precio_3br": 1220,
        "precio_estac": 7000, "precio_deposito": 2500,
        "costo_construccion": 850,
        "velocidad_venta": 1.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 5.6, "yield_mercado_pct": 5.3, "variacion_anual_pct": 9.8,
    },
    "Bellavista": {                                # Urbania: 4,312 S./m² → $1,250/m² (TC 3.45)
        "precio_1br": 1375, "precio_2br": 1300, "precio_3br": 1200,
        "precio_estac": 7000, "precio_deposito": 2500,
        "costo_construccion": 850,
        "velocidad_venta": 1.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 5.5, "yield_mercado_pct": 5.3, "variacion_anual_pct": 3.6,
    },
    "Rímac": {                                     # est. ~4,959 S./m² → $1,450/m²
        "precio_1br": 1595, "precio_2br": 1510, "precio_3br": 1390,
        "precio_estac": 6000, "precio_deposito": 2000,
        "costo_construccion": 850,
        "velocidad_venta": 1.20, "duracion_base_meses": 26,
        "alquiler_m2_mes": 6.5, "yield_mercado_pct": 5.4, "variacion_anual_pct": 2.0,
    },
    "San Bartolo": {                               # balneario costa sur → est. $900/m²
        "precio_1br": 990,  "precio_2br": 935,  "precio_3br": 865,
        "precio_estac": 4500, "precio_deposito": 1300,
        "costo_construccion": 820,
        "velocidad_venta": 1.90, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.8, "yield_mercado_pct": 5.0, "variacion_anual_pct": 1.0,
    },
    "San Borja": {                                 # Urbania: 7,147 S./m² → $2,072/m² (TC 3.45)
        "precio_1br": 2280, "precio_2br": 2155, "precio_3br": 1990,
        "precio_estac": 13000, "precio_deposito": 4500,
        "costo_construccion": 960,
        "velocidad_venta": 0.90, "duracion_base_meses": 28,
        "alquiler_m2_mes": 8.0, "yield_mercado_pct": 4.9, "variacion_anual_pct": -2.1,
    },
    "San Isidro": {                                # Urbania: 9,231 S./m² → $2,676/m² (TC 3.45)
        "precio_1br": 2945, "precio_2br": 2785, "precio_3br": 2570,
        "precio_estac": 17000, "precio_deposito": 6000,
        "costo_construccion": 1100,
        "velocidad_venta": 0.65, "duracion_base_meses": 32,
        "alquiler_m2_mes": 11.2, "yield_mercado_pct": 5.0, "variacion_anual_pct": 0.7,
    },
    "San Juan de Lurigancho": {                    # est. ~3,600 S./m² → $1,053/m²
        "precio_1br": 1160, "precio_2br": 1095, "precio_3br": 1010,
        "precio_estac": 5500, "precio_deposito": 2000,
        "costo_construccion": 830,
        "velocidad_venta": 1.60, "duracion_base_meses": 24,
        "alquiler_m2_mes": 5.0, "yield_mercado_pct": 5.5, "variacion_anual_pct": 0.0,
    },
    "San Juan de Miraflores": {                    # Urbania: 3,684 S./m² → $1,068/m² (TC 3.45)
        "precio_1br": 1175, "precio_2br": 1110, "precio_3br": 1025,
        "precio_estac": 5500, "precio_deposito": 1800,
        "costo_construccion": 830,
        "velocidad_venta": 1.60, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.7, "yield_mercado_pct": 5.2, "variacion_anual_pct": -1.1,
    },
    "San Luis": {                                  # est. ~5,814 S./m² → $1,700/m²
        "precio_1br": 1870, "precio_2br": 1770, "precio_3br": 1630,
        "precio_estac": 8000, "precio_deposito": 2800,
        "costo_construccion": 870,
        "velocidad_venta": 1.10, "duracion_base_meses": 26,
        "alquiler_m2_mes": 8.0, "yield_mercado_pct": 5.5, "variacion_anual_pct": 2.0,
    },
    "San Martín de Porres": {                      # Urbania: 3,002 S./m² → $870/m² (TC 3.45)
        "precio_1br": 955,  "precio_2br": 905,  "precio_3br": 835,
        "precio_estac": 4500, "precio_deposito": 1400,
        "costo_construccion": 810,
        "velocidad_venta": 1.60, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.8, "yield_mercado_pct": 5.2, "variacion_anual_pct": -1.8,
    },
    "San Miguel": {                                # Urbania: 6,147 S./m² → $1,782/m² (TC 3.45)
        "precio_1br": 1960, "precio_2br": 1855, "precio_3br": 1710,
        "precio_estac": 9500, "precio_deposito": 3500,
        "costo_construccion": 900,
        "velocidad_venta": 1.20, "duracion_base_meses": 26,
        "alquiler_m2_mes": 8.1, "yield_mercado_pct": 5.4, "variacion_anual_pct": 2.8,
    },
    "Santa Anita": {                               # est. ~4,800 S./m² → $1,404/m²
        "precio_1br": 1545, "precio_2br": 1460, "precio_3br": 1350,
        "precio_estac": 6000, "precio_deposito": 2000,
        "costo_construccion": 840,
        "velocidad_venta": 1.40, "duracion_base_meses": 24,
        "alquiler_m2_mes": 6.5, "yield_mercado_pct": 5.4, "variacion_anual_pct": 2.8,
    },
    "Santa María del Mar": {                       # balneario pequeño costa sur → est. $800/m²
        "precio_1br": 880,  "precio_2br": 830,  "precio_3br": 770,
        "precio_estac": 3500, "precio_deposito": 1000,
        "costo_construccion": 800,
        "velocidad_venta": 2.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.0, "yield_mercado_pct": 4.8, "variacion_anual_pct": 0.5,
    },
    "Santa Rosa": {                                # costa norte lejana → est. $700/m²
        "precio_1br": 770,  "precio_2br": 730,  "precio_3br": 670,
        "precio_estac": 3500, "precio_deposito": 1000,
        "costo_construccion": 800,
        "velocidad_venta": 2.50, "duracion_base_meses": 24,
        "alquiler_m2_mes": 3.0, "yield_mercado_pct": 5.0, "variacion_anual_pct": 0.5,
    },
    "Santiago de Surco": {                         # Urbania: 6,690 S./m² → $1,939/m² (TC 3.45)
        "precio_1br": 2135, "precio_2br": 2015, "precio_3br": 1860,
        "precio_estac": 11000, "precio_deposito": 4000,
        "costo_construccion": 930,
        "velocidad_venta": 1.10, "duracion_base_meses": 26,
        "alquiler_m2_mes": 7.9, "yield_mercado_pct": 5.0, "variacion_anual_pct": -1.1,
    },
    "Surquillo": {                                 # Urbania: 6,807 S./m² → $1,973/m² (TC 3.45)
        "precio_1br": 2170, "precio_2br": 2050, "precio_3br": 1895,
        "precio_estac": 9000, "precio_deposito": 3200,
        "costo_construccion": 890,
        "velocidad_venta": 1.20, "duracion_base_meses": 26,
        "alquiler_m2_mes": 10.2, "yield_mercado_pct": 6.1, "variacion_anual_pct": 3.1,
    },
    "Villa El Salvador": {                         # est. ~3,400 S./m² → $994/m²
        "precio_1br": 1095, "precio_2br": 1035, "precio_3br": 955,
        "precio_estac": 5000, "precio_deposito": 1800,
        "costo_construccion": 820,
        "velocidad_venta": 1.80, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.5, "yield_mercado_pct": 5.1, "variacion_anual_pct": 0.0,
    },
    "Villa María del Triunfo": {                   # est. ~3,249 S./m² → $950/m²
        "precio_1br": 1045, "precio_2br": 990,  "precio_3br": 910,
        "precio_estac": 4200, "precio_deposito": 1400,
        "costo_construccion": 818,
        "velocidad_venta": 1.80, "duracion_base_meses": 24,
        "alquiler_m2_mes": 4.2, "yield_mercado_pct": 5.2, "variacion_anual_pct": 0.5,
    },
    "Otro": {                                      # promedio Lima Index ~$1,700/m²
        "precio_1br": 1870, "precio_2br": 1770, "precio_3br": 1630,
        "precio_estac": 7000, "precio_deposito": 2500,
        "costo_construccion": 850,
        "velocidad_venta": 1.00, "duracion_base_meses": 24,
        "alquiler_m2_mes": 7.0, "yield_mercado_pct": 5.25, "variacion_anual_pct": 1.1,
    },
}

# ═══════════════════════════════════════════════════════
# PRECIOS DE MERCADO — carga desde Google Sheet (con fallback)
# ═══════════════════════════════════════════════════════
_MERCADO_COLS = [
    "precio_1br","precio_2br","precio_3br",
    "precio_estac","precio_deposito","costo_construccion",
    "velocidad_venta","duracion_base_meses",
    "alquiler_m2_mes","yield_mercado_pct","variacion_anual_pct",
]
_MERCADO_INT_COLS  = {"precio_1br","precio_2br","precio_3br","precio_estac","precio_deposito",
                      "costo_construccion","duracion_base_meses"}
_MERCADO_FLOAT_COLS= {"velocidad_venta","alquiler_m2_mes","yield_mercado_pct","variacion_anual_pct"}

@st.cache_data(ttl=3600, show_spinner=False)
def _cargar_mercado_sheet() -> tuple:
    """Lee precios desde Google Sheet publicado como CSV. TTL 1 hora.
    Soporta dos formatos:
      - Nuevo (precio_m2_soles + alquiler_soles_100m2): convierte a USD usando tipo_cambio
      - Clásico (precio_1br, precio_2br, precio_3br en USD): usa directamente
    Fila especial CONFIG con columna tipo_cambio actualiza el tipo de cambio dinámicamente.
    Retorna (precios_dict, tipo_cambio).
    """
    _tc_secrets = float((st.secrets.get("mercado") or {}).get("tipo_cambio", 3.45))
    try:
        sheet_url = (st.secrets.get("mercado", {}) or {}).get("sheet_url", "")
        if not sheet_url:
            return {}, _tc_secrets
        import urllib.request, io as _io
        with urllib.request.urlopen(sheet_url, timeout=8) as resp:
            raw = resp.read().decode("utf-8")
        df = pd.read_csv(_io.StringIO(raw))
        df.columns = [c.strip().lower() for c in df.columns]
        if "distrito" not in df.columns:
            return {}, _tc_secrets
        # Leer tipo_cambio desde fila CONFIG
        tc = _tc_secrets
        if "tipo_cambio" in df.columns:
            cfg = df[df["distrito"].astype(str).str.strip().str.upper() == "CONFIG"]
            if not cfg.empty:
                try:
                    v = float(str(cfg.iloc[0]["tipo_cambio"]).replace(",","").strip())
                    if v > 0:
                        tc = v
                except (ValueError, TypeError):
                    pass
        use_soles = "precio_m2_soles" in df.columns
        out = {}
        for _, row in df.iterrows():
            distrito = str(row.get("distrito", "")).strip()
            if not distrito or distrito.lower() == "nan" or distrito.upper() == "CONFIG":
                continue
            entry = {}
            if use_soles:
                try:
                    base_s = float(str(row.get("precio_m2_soles","")).replace(",","").strip())
                    base_u = base_s / tc
                    entry["precio_1br"] = int(base_u * 1.10)
                    entry["precio_2br"] = int(base_u * 1.04)
                    entry["precio_3br"] = int(base_u * 0.96)
                except (ValueError, TypeError):
                    pass
                try:
                    alq = float(str(row.get("alquiler_soles_100m2","")).replace(",","").strip())
                    entry["alquiler_m2_mes"] = round(alq / 100 / tc, 2)
                except (ValueError, TypeError):
                    pass
                otros = ["precio_estac","precio_deposito","costo_construccion",
                         "velocidad_venta","duracion_base_meses",
                         "yield_mercado_pct","variacion_anual_pct"]
                for col in otros:
                    if col not in row:
                        continue
                    try:
                        val = float(str(row[col]).replace(",","").strip())
                        entry[col] = int(val) if col in _MERCADO_INT_COLS else round(val, 4)
                    except (ValueError, TypeError):
                        pass
            else:
                for col in _MERCADO_COLS:
                    if col not in row:
                        continue
                    try:
                        val = float(str(row[col]).replace(",","").strip())
                        entry[col] = int(val) if col in _MERCADO_INT_COLS else round(val, 4)
                    except (ValueError, TypeError):
                        pass
            if entry:
                out[distrito] = entry
        return out, tc
    except Exception:
        return {}, _tc_secrets

def get_mercado() -> dict:
    """MERCADO actualizado: Sheet > hardcoded. Fusiona para preservar distritos sin Sheet."""
    global TIPO_CAMBIO
    live, tc = _cargar_mercado_sheet()
    TIPO_CAMBIO = tc
    if not live:
        return MERCADO
    merged = dict(MERCADO)
    for distrito, datos in live.items():
        if distrito in merged:
            merged[distrito] = {**merged[distrito], **datos}
        else:
            merged[distrito] = datos
    return merged

# Tipo de cambio S./USD — se actualiza desde Sheet (fila CONFIG) o secrets.toml
TIPO_CAMBIO = float((st.secrets.get("mercado") or {}).get("tipo_cambio", 3.45))
# Sobrescribe MERCADO con versión live (Sheet > hardcoded, con fallback automático)
MERCADO = get_mercado()

# ═══════════════════════════════════════════════════════
# CLAUDE API
# ═══════════════════════════════════════════════════════

def _sanitize_api_key(raw: str) -> str:
    """Strips non-ASCII characters that macOS autocorrect can silently inject."""
    return raw.encode("ascii", errors="ignore").decode("ascii").strip()


def get_client():
    api_key = (
        os.environ.get("ANTHROPIC_API_KEY")
        or (st.secrets.get("anthropic", {}) or {}).get("api_key", "")
        or st.session_state.get("api_key_input", "")
    )
    if not api_key:
        st.error("⚠️ Clave API no configurada. Contacta al administrador.")
        st.stop()
    api_key = _sanitize_api_key(api_key)
    if not api_key.startswith("sk-"):
        st.error("🔑 Clave API inválida. Contacta al administrador.")
        st.stop()
    return anthropic.Anthropic(api_key=api_key, max_retries=0, timeout=120.0)


def _run_with_retry(fn, spinner_msg, max_attempts=3):
    """Ejecuta fn() reintentando en errores de red, servidor ocupado o rate limit."""
    import time
    _status = st.empty()
    last_err = ""
    for attempt in range(1, max_attempts + 1):
        label = spinner_msg if attempt == 1 else f"{spinner_msg} — intento {attempt}/{max_attempts}"
        with st.spinner(label):
            try:
                result = fn()
                _status.empty()
                return result
            except Exception as e:
                last_err = str(e)
                err_lower = last_err.lower()

                # Auth error: clave inválida → limpiar y pedir que la re-ingresen
                if "401" in last_err or "authentication_error" in err_lower or "invalid x-api-key" in err_lower or "invalid api key" in err_lower:
                    _status.empty()
                    st.session_state.pop("api_key_input", None)
                    st.error("🔑 Clave de acceso inválida. Ingresa una clave API de Anthropic válida en el panel izquierdo (⚙ Configuración) e inténtalo de nuevo.")
                    st.stop()

                is_rate_limit = "429" in last_err or "rate_limit" in err_lower or "rate limit" in err_lower
                is_retriable = (
                    is_rate_limit
                    or "529" in last_err
                    or "502" in last_err
                    or "overloaded" in err_lower
                    or "bad gateway" in err_lower
                    or "connection" in err_lower
                    or "connect" in err_lower
                    or "timeout" in err_lower
                    or "timed out" in err_lower
                    or "network" in err_lower
                    or "remotedisconnected" in err_lower
                    or "read timeout" in err_lower
                    or "eoferror" in err_lower
                    or "reset by peer" in err_lower
                    or "ssl" in err_lower
                    or "json_parse_error" in err_lower
                )
                if not is_retriable:
                    _status.empty()
                    st.error(f"Error inesperado: {last_err[:400]}")
                    st.stop()

        # sleep FUERA del spinner — rate limit espera 65s, resto 8s
        if attempt < max_attempts:
            wait = 65 if is_rate_limit else 8
            for s in range(wait, 0, -1):
                msg = (f"Límite de tokens/minuto alcanzado — esperando {s}s para reintentar ({attempt + 1}/{max_attempts})…"
                       if is_rate_limit else
                       f"Reintentando en {s}s… (intento {attempt + 1}/{max_attempts})")
                _status.info(msg)
                time.sleep(1)
            _status.empty()

    _status.empty()
    if "json_parse_error" in last_err.lower():
        st.error("El análisis no pudo completarse: Claude devolvió una respuesta incompleta. "
                 "Intenta con documentos más pequeños (máx. ~1MB cada uno) o reduce el número de archivos adjuntos.")
    elif "429" in last_err or "rate_limit" in last_err.lower():
        st.error("Se superó el límite de tokens por minuto de tu cuenta Anthropic. "
                 "Espera 1 minuto e inténtalo nuevamente, o reduce el número de documentos adjuntos.")
    else:
        st.error("No se pudo conectar con el servicio de análisis después de varios intentos. "
                 "Verifica tu conexión a internet e inténtalo nuevamente.")
    st.stop()


def parse_json_safe(text: str) -> dict:
    """Extrae y parsea JSON de la respuesta de Claude. Lanza ValueError si falla."""
    # 1. Intentar extraer de bloque markdown ```json ... ```
    md_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if md_match:
        raw = md_match.group(1)
    else:
        # 2. Extraer el bloque JSON más externo { ... }
        brace_match = re.search(r'\{.*\}', text, re.DOTALL)
        if not brace_match:
            raise ValueError(f"json_parse_error: respuesta sin JSON — '{text[:120]}'")
        raw = brace_match.group()

    # Limpiar problemas comunes
    raw = re.sub(r'//[^\n]*', '', raw)
    raw = re.sub(r'/\*.*?\*/', '', raw, flags=re.DOTALL)
    raw = re.sub(r',\s*([\}\]])', r'\1', raw)
    raw = raw.replace('“', '"').replace('”', '"')
    raw = raw.replace('‘', "'").replace('’', "'")

    try:
        result = json.loads(raw)
        if not isinstance(result, dict) or len(result) == 0:
            raise ValueError(f"json_parse_error: JSON vacío o no es objeto")
        return result
    except json.JSONDecodeError as e:
        raise ValueError(f"json_parse_error: {e} — '{raw[:120]}'")


def pdf_block(pdf_bytes: bytes) -> dict:
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf_bytes).decode("utf-8")
        }
    }


def image_block(img_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(img_bytes).decode("utf-8"),
        }
    }


def extraer_comparables_portal(api_key: str, texto: str = "", imagenes: list = None) -> list:
    """Lee texto pegado o capturas de portales inmobiliarios y extrae comparables."""
    client = anthropic.Anthropic(api_key=_sanitize_api_key(api_key), max_retries=0, timeout=60.0)

    content = []
    if imagenes:
        for img_bytes, media_type in imagenes:
            content.append(image_block(img_bytes, media_type))
    if texto.strip():
        content.append({"type": "text", "text": f"CONTENIDO DEL PORTAL:\n{texto}"})

    content.append({"type": "text", "text": """Eres un asistente especializado en análisis inmobiliario en Lima, Perú.
Del contenido del portal inmobiliario (texto o capturas), extrae TODOS los proyectos/inmuebles que puedas identificar.
Para cada uno devuelve un objeto JSON con exactamente estos campos:
- "proyecto": nombre del proyecto o dirección (string)
- "precio_m2": precio en USD por m² (number, si está en soles convierte a USD dividiendo entre 3.75)
- "pisos": número de pisos del edificio (number, 0 si no se menciona)
- "tipologia": tipologías disponibles como string, ej "2-3 Dorm." (string)
- "estado": "Preventa", "En construcción" o "En venta" (string)

Devuelve SOLO un array JSON válido, sin texto adicional, sin markdown, sin explicaciones.
Ejemplo: [{"proyecto":"Torres ABC","precio_m2":2800,"pisos":12,"tipologia":"2-3 Dorm.","estado":"Preventa"}]
Si no encuentras ningún proyecto, devuelve [].
"""})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": content}],
    )
    raw = response.content[0].text.strip() if response.content else "[]"
    # limpiar posible markdown
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    try:
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except json.JSONDecodeError:
        return []


# ── CARGA DE NORMATIVAS DESDE ARCHIVOS EXTERNOS ─────────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_norm(filename: str) -> str:
    """Carga un archivo de normativa desde la carpeta normativas/. Cacheado por sesión."""
    base = pathlib.Path(__file__).parent / "normativas"
    path = base / filename
    if path.exists():
        return path.read_text(encoding="utf-8")
    return f"[NORMATIVA NO ENCONTRADA: {filename}]"

RIN_SAN_ISIDRO = _load_norm("rin_san_isidro.txt")


# ── NORMATIVA ESPECÍFICA MIRAFLORES ──────────────────────────────────────────────────────────────
RIN_MIRAFLORES = _load_norm("rin_miraflores.txt")


# ── NORMATIVA ESPECÍFICA: LA VICTORIA ────────────────────────────────────────────────────────────
# Fuente: CPU N°000371-2021 (Av. Javier Prado/Palomar Norte), CPU N°000367-2021 (Av. Carlos Villarán/Palomar Norte),
#         CPU N°000132-2024 (Av. Javier Prado Este 1197-1199, caduca 01/04/2027)
RIN_LA_VICTORIA = _load_norm("rin_la_victoria.txt")


# ── NORMATIVA ESPECÍFICA: LINCE ───────────────────────────────────────────────────────────────────
# Fuente: CPU N°006-2021-MDL/GDU/SOPPUC (Av. Arequipa 2698 esq. Jr. Soledad, Ámbito C, caduca 14/01/2024)
RIN_LINCE = _load_norm("rin_lince.txt")


# ── NORMATIVA ESPECÍFICA: MAGDALENA DEL MAR ──────────────────────────────────────────────────────
# Fuente: CPU N°00377-2019 (Pque. Francisco Graña — RDB/Sector III), CPU N°00104-2020 (Jr. Flora Tristán — RDB/Sector IV),
#         CPU N°00100-2023 (Av. Javier Prado Oeste 2281-2291 — E3/Sector IV, caduca 29/03/2026)
RIN_MAGDALENA = _load_norm("rin_magdalena.txt")


# ── NORMATIVA ESPECÍFICA: JESÚS MARÍA ────────────────────────────────────────────────────────────
# Fuente: CPU N°391-2019-MDJM (Av. Garzón 550-572, RDA, caduca 03/10/2022)
#         CPU N°489-2018-MDJM (Av. Garzón 082, RDA+RDM, caduca 27/11/2021)
RIN_JESUS_MARIA = _load_norm("rin_jesus_maria.txt")

RIN_CERCADO_LIMA = _load_norm("rin_cercado_lima.txt")

RIN_SAN_BORJA = _load_norm("rin_san_borja.txt")

RIN_SANTA_ANITA = _load_norm("rin_santa_anita.txt")

RIN_SURCO = _load_norm("rin_surco.txt")

RIN_SURQUILLO = _load_norm("rin_surquillo.txt")

RIN_VILLA_EL_SALVADOR = _load_norm("rin_villa_el_salvador.txt")

RIN_SAN_JUAN_LURIGANCHO = _load_norm("rin_san_juan_lurigancho.txt")


# ── CONOCIMIENTO NORMATIVO: LIMA METROPOLITANA Y DISTRITOS ───────────────────────────────────────
REFERENCIAS_NORMATIVAS_LIMA = _load_norm("referencias_lima.txt")

# ── BENCHMARKS INDUSTRIALES (costos nave, Parque Logístico 47, retornos) ─────────────────────────
BENCHMARKS_INDUSTRIAL = _load_norm("benchmarks_industrial.txt")


# ── REGLAMENTO NACIONAL DE EDIFICACIONES (RNE) ───────────────────────────────────────────────────
# Norma A.010 (RM 191-2021-VIVIENDA) y Norma A.020 (RM 188-2021-VIVIENDA)
RNE_NACIONAL = _load_norm("rne_nacional.txt")


def extract_parameters(cert_bytes: bytes, norm_docs: list[bytes]) -> dict:
    client = get_client()

    content = [pdf_block(cert_bytes)]
    for doc in norm_docs:
        content.append(pdf_block(doc))

    docs_note = (
        f"\nAdemás del certificado, se adjuntan {len(norm_docs)} documento(s) normativos adicionales "
        f"(reglamentos, ordenanzas, cuadros de parámetros). Analízalos en conjunto para identificar "
        f"TODOS los beneficios, incentivos, mecanismos de densificación, excepciones o notas que puedan "
        f"incrementar la altura, reducir aportes, flexibilizar retiros u otorgar cualquier ventaja al proyecto."
        if norm_docs else ""
    )

    normativa_context = (
        f"\n\nREGLAMENTO NACIONAL DE EDIFICACIONES (RNE):\n{RNE_NACIONAL}\n\n"
        f"MARCO NORMATIVO LIMA METROPOLITANA Y DISTRITOS:\n{REFERENCIAS_NORMATIVAS_LIMA}\n\n"
        f"NORMATIVA ESPECÍFICA POR DISTRITO — aplica la que corresponda según el distrito del certificado:\n\n"
        f"SAN ISIDRO (Ord. N°523-MSI):\n{RIN_SAN_ISIDRO}\n\n"
        f"MIRAFLORES (Ord. N°342-MM y modificatorias):\n{RIN_MIRAFLORES}\n\n"
        f"JESÚS MARÍA:\n{RIN_JESUS_MARIA}\n\n"
        f"MAGDALENA DEL MAR:\n{RIN_MAGDALENA}\n\n"
        f"LINCE:\n{RIN_LINCE}\n\n"
        f"CERCADO DE LIMA (Ord. N°946-MML):\n{RIN_CERCADO_LIMA}\n\n"
        f"LA VICTORIA:\n{RIN_LA_VICTORIA}\n\n"
        f"SAN BORJA:\n{RIN_SAN_BORJA}\n\n"
        f"SANTA ANITA:\n{RIN_SANTA_ANITA}\n\n"
        f"SANTIAGO DE SURCO:\n{RIN_SURCO}\n\n"
        f"SURQUILLO (Ord. N°501-MDS):\n{RIN_SURQUILLO}\n\n"
        f"VILLA EL SALVADOR:\n{RIN_VILLA_EL_SALVADOR}\n\n"
        f"SAN JUAN DE LURIGANCHO (Ord. N°284-MDSJL):\n{RIN_SAN_JUAN_LURIGANCHO}\n\n"
        f"Los valores del certificado prevalecen sobre estas referencias normativas en caso de discrepancia."
    )

    prompt = f"""Eres un arquitecto especialista en desarrollo inmobiliario en Lima, Perú, con conocimiento experto en normativa municipal.{normativa_context}

Analiza este Certificado de Parámetros Urbanísticos y Edificatorios de Lima, Perú.{docs_note}

Devuelve ÚNICAMENTE el siguiente JSON, sin texto antes ni después, sin bloques de código markdown:

{{
  "zonificacion": "CZ",
  "distrito": "San Isidro",
  "ubicacion": "Ca. Las Camelias 180",
  "area_terreno_m2": 500.0,
  "frente_ml": 20.0,
  "pisos_max": 8,
  "pisos_por_via": [{{"via": "Ca. Las Camelias", "pisos": 8}}],
  "area_libre_min_pct": 30.0,
  "retiro_frontal_ml": 3.0,
  "retiro_lateral_ml": null,
  "retiro_posterior_ml": null,
  "coeficiente_edificacion": null,
  "usos_compatibles": ["Residencial", "Comercio"],
  "estacionamientos_norma": "2 est./vivienda (Ámbito B/C, Anexo N°02 RIN 523-2020)",
  "ambito_urbano": "B",
  "sector_urbano": "A",
  "fecha_caducidad": "2026-12-31",
  "notas_altura": ["Nota 12: lote esquina aplica promedio de alturas"],
  "ordenanzas_base": ["RIN 523-2020"],
  "beneficios_normativos": [
    {{
      "tipo": "mayor_altura",
      "descripcion": "Lote esquina permite promedio de alturas",
      "condicion": "Lote debe tener frente a dos vías",
      "impacto_estimado": "+2 pisos adicionales",
      "base_legal": "RIN 523-2020 Nota 12"
    }}
  ]
}}

IMPORTANTE: Reemplaza todos los valores del ejemplo con los datos reales del documento.
- area_libre_min_pct: si dice "no se exige área libre" usa 0
- pisos_max: el máximo entre todas las vías del certificado
- Si un dato no existe en el documento usa null
- ambito_urbano: identifica A, B, C o D según la ubicación del predio y el RIN del distrito correspondiente (San Isidro: Ámbitos A/B/C/D del Anexo N°02; otros distritos: usa null si no aplica)
- sector_urbano: si es Miraflores, extrae el Sector Urbano (A, B, C, D); para otros distritos usa null
- estacionamientos_norma: usa el ratio correcto según la normativa del distrito identificado — consulta el RIN correspondiente de la lista anterior; incluye la base legal (Ord./RIN y artículo)
- ordenanzas_base: cita las ordenanzas vigentes del certificado, no las derogadas
- beneficios_normativos: incluye lotes esquina, frente a parque o zona monumental, acumulación de lotes, bonificaciones de altura por vía, retiros compensados, usos mixtos, TDR, ATN, CZ, cualquier mecanismo que beneficie el proyecto según la normativa del distrito"""

    content.append({"type": "text", "text": prompt})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system="Eres un arquitecto experto en normativa urbanística de Lima, Perú. Respondes únicamente con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": content}]
    )

    if not response.content:
        raise ValueError("json_parse_error: API devolvió respuesta vacía")
    text = response.content[0].text.strip()
    return parse_json_safe(text)


def generate_cabida(params: dict, config: dict) -> dict:
    client = get_client()

    beneficios_txt = ""
    if params.get("beneficios_normativos"):
        beneficios_txt = "\n\nBENEFICIOS NORMATIVOS IDENTIFICADOS:\n" + json.dumps(
            params["beneficios_normativos"], ensure_ascii=False, indent=2
        )

    sugerencias_txt = f"\n\nNOTAS DEL ANALISTA:\n{config.get('sugerencias', '')}" if config.get("sugerencias") else ""

    # Regla de colindancia — calcular programáticamente y sobreescribir pisos_max
    colind_izq = config.get("colindante_izq_pisos")
    colind_der = config.get("colindante_der_pisos")
    colind_txt = ""
    params_cabida = dict(params)  # copia local — no mutar el original

    if colind_izq or colind_der:
        _colind_max  = max(colind_izq or 0, colind_der or 0)
        _base_pisos  = int(params_cabida.get("pisos_max") or 5)
        _pisos_calc  = math.ceil((_colind_max + _base_pisos) / 2)
        # Sobreescribir en la copia que recibe Claude — no es sugerencia, es valor fijo
        params_cabida["pisos_max"] = _pisos_calc
        partes = []
        if colind_izq: partes.append(f"izquierdo: {colind_izq} pisos")
        if colind_der: partes.append(f"derecho: {colind_der} pisos")
        colind_txt = (
            f"\n\nCOLINDANTES VERIFICADOS EN CAMPO: {' | '.join(partes)}.\n"
            f"REGLA DE COLINDANCIA APLICADA (cálculo determinístico):\n"
            f"  colindante más alto = {_colind_max} pisos | altura base norma = {_base_pisos} pisos\n"
            f"  pisos_max = ceil(({_colind_max} + {_base_pisos}) / 2) = {_pisos_calc} pisos\n"
            f"  *** pisos_max YA ha sido actualizado a {_pisos_calc} en los parámetros. "
            f"USA EXACTAMENTE {_pisos_calc} PISOS. NO uses la altura base original. ***"
        )
    else:
        params_cabida = params

    distrito = params.get("distrito", "")
    ambito = params.get("ambito_urbano", "")
    sector = params.get("sector_urbano", "")
    normativa_note = (
        f"\n\nREGLAMENTO NACIONAL DE EDIFICACIONES (RNE):\n{RNE_NACIONAL}\n\n"
        f"MARCO NORMATIVO LIMA METROPOLITANA Y DISTRITOS:\n{REFERENCIAS_NORMATIVAS_LIMA}"
    )
    if "san isidro" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA SAN ISIDRO (Ord. 523-MSI):\n{RIN_SAN_ISIDRO}"
        if ambito:
            normativa_note += f"\n\nÁMBITO IDENTIFICADO: {ambito} — aplica reglas de estacionamiento y áreas mínimas del ámbito correspondiente."
    elif "miraflores" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA MIRAFLORES (Ord. 342-MM y modificatorias):\n{RIN_MIRAFLORES}"
        if sector:
            normativa_note += (
                f"\n\nSECTOR URBANO IDENTIFICADO: {sector} — aplica altura normativa del sector según "
                f"Ord. 226-MM. Si el sector es A con RDMA y lote ≥ normativo, altura hasta 17 pisos "
                f"(condición: área edificable total ≤ 0.60 × área_terreno × 12 pisos, Ord. 342-MM Art. 6° literal g)."
            )
    elif "la victoria" in distrito.lower() or "lavictoria" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA LA VICTORIA (Ord. N°355-MLV + Ord. N°1082-MML):\n{RIN_LA_VICTORIA}"
        normativa_note += (
            "\n\nCLAVE PARA CZ LA VICTORIA: la altura CZ = 1.5×(a+r) donde a=ancho vía y r=suma retiros ambos lados. "
            "No hay tope fijo de pisos — calcular con datos del certificado. "
            "El uso residencial compatible (RDM o RDA) determina áreas mínimas y estacionamientos."
        )
    elif "lince" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA LINCE (Ord. N°235-MDL y modificatorias):\n{RIN_LINCE}"
        normativa_note += (
            "\n\nCLAVES PARA LINCE: (1) Altura CM = 1.5×(a+r) — sin tope fijo de pisos; calcular con ancho de vía y retiros del certificado. "
            "(2) Si el ámbito es C (Parque Castilla), aplicar alturas especiales: 10/15/20 pisos según tamaño de lote. "
            "(3) Estacionamiento residencial = 1 cada 2 viviendas (más restrictivo que otros distritos). "
            "(4) Máx 40% de unidades de 1 dormitorio."
        )
    elif "magdalena" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA MAGDALENA DEL MAR (Ord. N°950-MML + Ord. N°017-2016-MDMM):\n{RIN_MAGDALENA}"
        normativa_note += (
            "\n\nCLAVES PARA MAGDALENA: (1) Altura máxima FIJA = 4 pisos = 12.00 ml — no hay excepciones confirmadas. "
            "(2) Estacionamiento = 1 est por vivienda — el más restrictivo de todos los distritos. "
            "(3) Zona predominante RDB — no hay RDA ni CM confirmados. "
            "(4) Lotes E3 sobre Av. Javier Prado pueden reconvertirse a residencial sin cambio de zonificación."
        )
    elif "jes" in distrito.lower() and "mar" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA JESÚS MARÍA (Ord. N°1017-MML + Ord. N°1076-MML):\n{RIN_JESUS_MARIA}"
        normativa_note += (
            "\n\nCLAVES PARA JESÚS MARÍA: (1) ATN II — normativa MML directa. "
            "(2) Estacionamiento DIFERENCIADO: RDA = 1/1 viv; RDM = 1/1.5 viv (Ord. N°586-MDJM). "
            "(3) Av. Garzón (20m) activa bonificación: RDA lotes ≥450m² hasta 15p; RDM +1 piso. "
            "(4) Área mínima 3D = 75m². Frente a pasaje: máx 3 pisos."
        )
    elif "cercado" in distrito.lower() or ("lima" in distrito.lower() and "cercado" in distrito.lower()):
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA CERCADO DE LIMA (Ord. N°893-MML + N°946-MML + N°1229-MML + N°2635-MML):\n{RIN_CERCADO_LIMA}"
        normativa_note += (
            "\n\nCLAVES PARA CERCADO DE LIMA: "
            "(1) ATN II — administrado directamente por MML (GDU-SPHU o ICL). "
            "(2) Altura CM/CZ comercial = 1.5×(a+r); RDA multifamiliar = 7 pisos; RDM = 3-6 pisos. "
            "(3) EXCEPCIÓN CRÍTICA: lote CR ≥1,000 m² en Santa Beatriz/Parque La Reserva → hasta 20 pisos "
            "(Ord. N°946-MML Art. 3°, Plano PA-02), área libre 50%. "
            "(4) Estacionamiento MUY FAVORABLE: 1 est./3 viviendas (Ord. N°1229-MML) para CM y CZ. "
            "(5) Retiros: 3m calles / 5m avenidas (DA N°127-1983). "
            "(6) Áreas mínimas: 3D=75m², 2D=55m², 1D=40m²."
        )
    elif "san borja" in distrito.lower() or "sanborja" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA SAN BORJA (Ord. N°491-MSB + TUO D.Alc. N°002-2025-MSB-A):\n{RIN_SAN_BORJA}"
        normativa_note += (
            "\n\nCLAVES PARA SAN BORJA: "
            "(1) ATN III — reglamento propio MSB, 5 Áreas Diferenciadas (A/B/C/D/E). "
            "(2) Altura máxima GENERAL: 8 pisos = 25.5 ml. "
            "EXCEPCIÓN: lotes >600 m² frente a Av. Javier Prado → hasta 12 pisos = 37.5 ml. "
            "(3) Estacionamiento SEGÚN ÁREA: A y B = 2/viv; C = 1.5/viv; D = 1/viv + 5% visitas; E = 1/1.5 viv. "
            "(4) Área mínima vivienda (70% de unidades): A=140m² · B=100m² · C=90m² · D=80m² · E=70m². "
            "(5) Área libre: A=40% · B/C=35% · D/E=30% (−5% en esquina). "
            "(6) Retiros: 3m calles / 5m avenidas. "
            "(7) Identificar el Área Diferenciada del predio — es la clave de todos los parámetros."
        )
    elif "santa anita" in distrito.lower() or "santaanita" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA SANTA ANITA (Ord. N°1025-MML + Ord. N°341-MML):\n{RIN_SANTA_ANITA}"
        normativa_note += (
            "\n\nCLAVES PARA SANTA ANITA: "
            "(1) ATN I — distrito industrial/periférico, normativa MML base, sin reglamento premium propio. "
            "(2) Zona I3 (Gran Industria): lote ≥2,500 m², retiro Carretera Central 10m, estac. 1/6 personas, patio maniobras obligatorio. "
            "(3) Zona CM (Comercio Metropolitano reconvertido): altura = 1.5×(a+r), área libre 0% comercial / 40% residencial (lote >200m²), "
            "estac. 1/50m² comercial o 1/2 viv residencial. "
            "(4) CM permite 100% del lote para uso residencial (RDA compatible). "
            "(5) No hay zonas residenciales puras premium — el potencial está en reconversión CM→residencial."
        )
    elif "surco" in distrito.lower() or "santiago de surco" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA SANTIAGO DE SURCO (Ord. N°1076-MML + Ord. N°912-MML + D.A. N°04-2023-MSS):\n{RIN_SURCO}"
        normativa_note += (
            "\n\nCLAVES PARA SURCO: "
            "(1) Surco tiene DOS sectores: ATN II (Ord. N°1076-MML, zonas intermedias/Paseo de la República) "
            "y ATN III (D.A. N°04-2023-MSS, zonas premium: Monterrico, Camacho, Chacarilla). Verificar en CPU. "
            "(2) Zona CZ ATN II: altura = 1.5×(a+r), área libre 0% comercial / 40% residencial (lote >200m²), "
            "100% del lote puede ser residencial. "
            "(3) RDA frente a avenida >20m: altura = 1.5×(a+r). "
            "(4) Estacionamiento: 1/1.5 viv residencial · 1/50m² comercial. "
            "(5) Altura piso a piso máx 3.00 ml en multifamiliar (Ord. N°1076-MML Anexo N°04, Item A.9). "
            "(6) Área mínima 3D = 75 m². Retiros: 5m Paseo de la República / 3m calles / 0m algunas calles locales."
        )
    elif "surquillo" in distrito.lower():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA SURQUILLO (Ord. N°1076-MML + Ord. N°501-MDS + Ord. N°533-2023-MDS):\n{RIN_SURQUILLO}"
        normativa_note += (
            "\n\nCLAVES PARA SURQUILLO: "
            "(1) ATN II — Ord. N°1076-MML para zonificación, Ord. N°501-MDS para estacionamientos vigentes. "
            "(2) Zona CZ: altura = 1.5×(a+r) · retiro Av. Angamos Este y Av. Tomas Marsano = 5.00 ml. "
            "(3) 100% del lote CZ puede ser residencial (RDA/RDM compatible). "
            "(4) Estacionamiento residencial (Ord. N°501-MDS vigente desde 2022): verificar en CPU reciente. "
            "Referencia histórica Ord. N°391-MDS (derogada): 2-3D = 1/viv; 1D = 2 est./3 unidades. "
            "(5) Área libre: 0% comercial / según uso residencial compatible en pisos residenciales. "
            "(6) ⚠ CPUs anteriores a jun 2023 citan Ord. N°391-MDS derogada — estacionamiento desactualizado."
        )
    elif "villa el salvador" in distrito.lower() or "ves" == distrito.lower().strip():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA VILLA EL SALVADOR (Ord. N°933-MML y modificatorias):\n{RIN_VILLA_EL_SALVADOR}"
        normativa_note += (
            "\n\nCLAVES PARA VILLA EL SALVADOR: "
            "(1) ATN I — normativa base MML Ord. N°933-MML, sin reglamento premium propio. "
            "(2) Zona CZ: altura FIJA 4 pisos (NO fórmula 1.5(a+r)) · retiro 1.50 ml · 100% residencial permitido. "
            "(3) Compatible RDM únicamente (no RDA) — menor densidad que distritos intermedios. "
            "(4) ⚠ Suelo arenoso: Estudio Geotécnico OBLIGATORIO para edificaciones >3 pisos. "
            "(5) Zona Industrial (ZIVS): ~800,000 m² almacenes · estac. 1/6 trabajadores · patio de maniobras. "
            "(6) Estacionamiento comercial: 1/50 m² · residencial: según Ord. N°933-MML Anexo 2. "
            "(7) Doble zonificación CZ+I2 posible (Ord. N°2220-MML Sector V/Litoral) — verificar con Informe de Compatibilidad de Uso vía GDEL. "
            "(8) Oportunidad residencial: crecimiento sur Lima, factibilidad servicios en expansión — "
            "verificar factibilidad SEDAPAL y Luz del Sur por sector antes de análisis financiero."
        )
    elif "san juan de lurigancho" in distrito.lower() or "sjl" == distrito.lower().strip():
        normativa_note += f"\n\nNORMATIVA ESPECÍFICA SAN JUAN DE LURIGANCHO (Ord. N°933-MML + Ord. N°284-MDSJL):\n{RIN_SAN_JUAN_LURIGANCHO}"
        normativa_note += (
            "\n\nCLAVES PARA SAN JUAN DE LURIGANCHO: "
            "(1) ATN I — distrito más poblado de Lima (~1.2M hab.), mercado residencial masivo. "
            "(2) Zona I2: lote ≥1,000 m² · frente 20m · retiro 3m · altura según proyecto/entorno · estac. 1/6 personas. "
            "(3) Estudios OBLIGATORIOS I2: Impacto Vial + Impacto Ambiental + Seguridad Integral (NRE A.60). "
            "(4) Zona RDM: altura 1.5(a+r) en vías locales (Ord. N°284-MDSJL) · área libre 30-35%. "
            "(5) Vías principales: Av. Próceres de la Independencia, Av. Gran Chimú, Av. Wiese, Av. Canto Grande. "
            "(6) Conectividad: Línea 1 Metro (eje Próceres) — activa bonus de demanda en predios cercanos. "
            "(7) Mercado objetivo: segmento B/C · precios USD 1,200-1,800/m² · tipologías 2D y 3D."
        )

    prompt = f"""Eres un arquitecto especialista en desarrollo inmobiliario en Lima, Perú, con conocimiento experto de normativa municipal y el RNE.

PARÁMETROS NORMATIVOS (extraídos del Certificado de Parámetros):
{json.dumps(params_cabida, ensure_ascii=False, indent=2)}
{beneficios_txt}{colind_txt}{sugerencias_txt}{normativa_note}

CONFIGURACIÓN BASE:
- Uso: Residencial Multifamiliar (+ comercio en 1er piso si zonificación CZ/CM/CV)
- Sótanos para estacionamientos: determinar según normativa de estacionamientos del distrito

INSTRUCCIONES:
1. Usa el valor de pisos_max que figura en los parámetros normativos — ese valor ya incorpora la regla de colindancia y cualquier beneficio normativo calculado externamente. NO lo recalcules. Aplica adicionalmente beneficios normativos que NO estén ya incluidos (frente a parque, lote esquina, etc.).
2. Calcula el área techada por piso: (area_terreno − area_retiros) × (1 − area_libre_min/100)
3. Si zona CZ/CV/CM y área libre = 0: área techada por piso ≈ área del lote − retiros
4. Define el mix tipológico óptimo para el mercado del distrito. Si es San Isidro, respeta las áreas mínimas por vivienda del Anexo N°03 según el ámbito identificado, y el porcentaje de tipologías (50-100% de 3 dorm., máx 50% de 2 dorm., máx 20% de 1 dorm.).
5. Calcula la eficiencia vendible: AV/AT (área vendible / área techada total sobre rasante) objetivo 75-80%; AV/AT total (incluyendo sótanos) = 60-74% en proyectos reales de Lima. Ratio autos/vivienda de mercado ≈ 0.91 (no todos los proyectos llegan a 1 auto/viv). Incluye en observaciones la eficiencia AV/AT total calculada.
6. Calcula estacionamientos según normativa vigente. Si es San Isidro, usa el Anexo N°02 del RIN según el ámbito: Ámbito A = 2 est./viv., Ámbitos B/C = 2 est./viv., Ámbito D/CF = 1 est./viv. + porcentaje de visitas correspondiente.
7. Aplica todos los beneficios normativos identificados.
8. DÚPLEX EN ÚLTIMO PISO (obligatorio para proyectos ≥ 5 pisos): El último piso debe incluir obligatoriamente DOS unidades dúplex (práctica estándar del mercado residencial Lima). Cada dúplex ocupa la mitad del área del último piso más una zona de azotea/terraza en el nivel superior. La zona techada del nivel superior de cada dúplex no puede exceder el 50% del área del piso inferior (RNE A.010 Art. 9). Los dúplex se incluyen en el mix como tipología "Dúplex" con area_m2 = área del piso/2 + zona techada del nivel superior, cantidad = 2. Incluye en observaciones el área descubierta de terraza.
9. Si es San Isidro: la azotea puede usarse bajo régimen de propiedad exclusiva del último piso (30% del área utilizable después de retranques). Inclúyelo en observaciones.
10. Calcula depositos_total: número de depósitos/bodegas de almacenamiento del proyecto. En Lima el mercado compra depósitos como adicional, pero no todas las unidades incluyen uno. Usa: 40-50% de total_unidades en distritos premium (San Isidro, Miraflores, Barranco); 25-35% en distritos medios (San Borja, Surco, Jesús María, Magdalena, Lince, La Molina, San Miguel); 10-20% en distritos periféricos (SJL, VES, Santa Anita, La Victoria, Cercado); 0 si el mercado objetivo es económico. Redondea al entero más cercano.

Devuelve SOLO este JSON:
{{
  "area_techada_piso_m2": number,
  "area_techada_total_m2": number,
  "area_vendible_m2": number,
  "num_pisos": number,
  "num_sotanos": number,
  "unidades": [
    {{"tipo": "1 Dorm.", "cantidad": number, "area_m2": number, "area_total_m2": number}},
    {{"tipo": "2 Dorm.", "cantidad": number, "area_m2": number, "area_total_m2": number}},
    {{"tipo": "3 Dorm.", "cantidad": number, "area_m2": number, "area_total_m2": number}},
    {{"tipo": "Dúplex", "cantidad": number, "area_m2": number, "area_total_m2": number}}
  ],
  "total_unidades": number,
  "depositos_total": number,
  "estac_residentes": number,
  "estac_visitas": number,
  "estac_total": number,
  "area_libre_m2": number,
  "area_comunes_m2": number,
  "beneficios_aplicados": [{{"beneficio": "string", "impacto": "string"}}],
  "ordenanzas_mayor_altura": ["string"],
  "observaciones": ["string"],
  "metodologia": "string"
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        system="Eres un arquitecto experto en normativa urbanística de Lima, Perú. Respondes únicamente con JSON válido, sin texto adicional.",
        messages=[{"role": "user", "content": prompt}]
    )

    if not response.content:
        raise ValueError("json_parse_error: API devolvió respuesta vacía")
    text = response.content[0].text.strip()
    return parse_json_safe(text)


def analizar_legal(partida_bytes: bytes | None, puhr_bytes: bytes | None,
                   cert_params_bytes: bytes | None = None, planos_bytes: bytes | None = None) -> dict:
    client = get_client()

    content = []
    docs_desc = []
    if partida_bytes:
        content.append(pdf_block(partida_bytes))
        docs_desc.append("Documento 1: Partida Registral (SUNARP)")
    if puhr_bytes:
        content.append(pdf_block(puhr_bytes))
        docs_desc.append(f"Documento {len(docs_desc)+1}: PU/HR (Predio Urbano / Hoja de Resumen - SAT/Municipalidad)")
    if cert_params_bytes:
        content.append(pdf_block(cert_params_bytes))
        docs_desc.append(f"Documento {len(docs_desc)+1}: Certificado de Parámetros Urbanísticos")
    if planos_bytes:
        content.append(pdf_block(planos_bytes))
        docs_desc.append(f"Documento {len(docs_desc)+1}: Planos del Inmueble")

    prompt = f"""Eres un abogado especialista en derecho registral e inmobiliario peruano.
Analiza los siguientes documentos de un inmueble en Lima, Perú:
{chr(10).join(docs_desc)}

{'Compara y cruza la información entre todos los documentos disponibles.' if len(docs_desc) > 1 else 'Extrae toda la información relevante del documento disponible.'}

IMPORTANTE — DNI y documentos de identidad:
- En la Partida Registral, los propietarios aparecen con su DNI o RUC al lado del nombre. Extráelo con exactitud.
- En el PU/HR (Predio Urbano / Hoja de Resumen SAT), el campo "Propietario" incluye nombre y a veces DNI/RUC del contribuyente.
- Si el DNI no figura explícitamente, anota null — no inferir ni inventar.

IMPORTANTE — PU/HR (Predio Urbano / Hoja de Resumen):
- Extrae el valor de autoavalúo, el código de predio/contribuyente, la clasificación municipal y la condición del propietario.
- El PU/HR puede estar emitido por la Municipalidad o SAT (Servicio de Administración Tributaria).

Devuelve ÚNICAMENTE el siguiente JSON, sin texto antes ni después:

{{
  "propietarios_partida": [
    {{"nombre": "nombre completo tal como aparece", "dni": "8 dígitos o RUC 11 dígitos o null", "porcentaje": "50% o null", "tipo_doc": "DNI/RUC/null"}}
  ],
  "propietarios_puhr": [
    {{"nombre": "nombre completo tal como aparece en PU/HR", "dni": "8 dígitos o null", "condicion": "Propietario/Poseedor/null"}}
  ],
  "propietarios_coinciden": true/false/null,
  "diferencias_propietarios": "descripción detallada si no coinciden, null si coinciden o no aplica",
  "direccion_partida": "dirección completa de la partida",
  "direccion_puhr": "dirección del PU/HR, null si no disponible",
  "direcciones_coinciden": true/false/null,
  "diferencias_direccion": "descripción si no coinciden, null si coinciden",
  "area_registral_m2": null,
  "area_puhr_m2": null,
  "areas_coinciden": true/false/null,
  "discrepancia_area_m2": null,
  "partida_numero": "número de partida registral",
  "numero_predio": "número de predio/contribuyente del PU/HR, null si no disponible",
  "valor_autoavaluo": null,
  "moneda_autoavaluo": "PEN/null",
  "anio_autoavaluo": null,
  "clasificacion_municipal": "Casa Habitación / Departamento / Local Comercial / otro, null si no disponible",
  "condicion_propietario_sat": "Propietario/Poseedor/null",
  "uso_predio": "descripción del uso según PU/HR, null si no disponible",
  "cargas_vigentes": [
    {{"tipo": "embargo/hipoteca/servidumbre/otro", "descripcion": "...", "acreedor": "...", "monto_referencial": "...", "fecha_inscripcion": "...", "asiento": "..."}}
  ],
  "hipotecas_vigentes": [
    {{"acreedor": "...", "monto": "...", "fecha_inscripcion": "...", "asiento": "...", "estado": "vigente/cancelada"}}
  ],
  "medidas_cautelares": [
    {{"tipo": "...", "descripcion": "...", "expediente": "...", "fecha": "..."}}
  ],
  "anotaciones_diversas": ["lista de anotaciones adicionales relevantes"],
  "semaforo": "verde/amarillo/rojo",
  "alertas": ["lista de alertas ordenadas por importancia"],
  "resumen_legal": "Párrafo de 2-3 oraciones resumiendo el estado legal del inmueble y las principales observaciones."
}}

CRITERIOS PARA SEMÁFORO:
- VERDE: propietarios y direcciones coinciden entre documentos, sin cargas ni hipotecas vigentes, sin medidas cautelares, sin discrepancias de área material
- AMARILLO: discrepancias menores (ej. abreviaturas), cargas canceladas aún anotadas, diferencia de área ≤ 5%, información faltante en algún documento
- ROJO: hipotecas o embargos vigentes, medidas cautelares activas, discrepancia de propietarios, discrepancia de área > 5%, señales de doble inmatriculación u otros riesgos graves

Si un dato no existe en los documentos usa null. Sé preciso con los nombres y DNIs tal como aparecen literalmente."""

    content.append({"type": "text", "text": prompt})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": content}]
    )
    if not response.content:
        raise ValueError("json_parse_error: API devolvió respuesta vacía")
    return parse_json_safe(response.content[0].text.strip())


def _extraer_texto_zip(file_bytes: bytes, filename: str) -> str:
    """Extract plain text from DOCX or PPTX (both are ZIP-based XML)."""
    import zipfile, io, re as _re
    ext = filename.lower().rsplit(".", 1)[-1]
    try:
        with zipfile.ZipFile(io.BytesIO(file_bytes)) as z:
            if ext == "docx":
                xml = z.read("word/document.xml").decode("utf-8", errors="ignore")
                return _re.sub(r"<[^>]+>", " ", xml)
            elif ext in ("pptx", "ppt"):
                slides = sorted(n for n in z.namelist()
                                if n.startswith("ppt/slides/slide") and n.endswith(".xml"))
                parts = []
                for s in slides:
                    xml = z.read(s).decode("utf-8", errors="ignore")
                    parts.append(_re.sub(r"<[^>]+>", " ", xml))
                return "\n".join(parts)
    except Exception:
        pass
    return ""


def extraer_datos_desde_doc(file_bytes: bytes, filename: str, modulo: str) -> dict:
    """Send document to Claude and extract structured property data for the given module."""
    client = get_client()
    ext = filename.lower().rsplit(".", 1)[-1]

    content: list = []
    if ext == "pdf":
        content.append(pdf_block(file_bytes))
    else:
        texto = _extraer_texto_zip(file_bytes, filename)
        if not texto.strip():
            return {"_error": "No se pudo extraer texto del documento."}
        content.append({"type": "text", "text": f"Contenido del documento:\n\n{texto[:15000]}"})

    PROMPTS = {
        "cabida": """Eres un analista inmobiliario. Del documento adjunto extrae los datos del proyecto o terreno.
Devuelve ÚNICAMENTE este JSON, sin texto adicional:
{
  "nombre_proyecto": "nombre del proyecto o null",
  "distrito": "distrito de Lima o null",
  "area_terreno_m2": null,
  "frente_ml": null,
  "fondo_ml": null,
  "costo_terreno_usd": null,
  "precio_venta_m2_usd": null,
  "costo_construccion_m2_usd": null,
  "num_pisos": null,
  "zonificacion": "RDA/RDM/RDB/CM/I2/otro o null"
}
Si un dato no aparece usa null. Solo extrae lo que está explícito.""",

        "residencial": """Eres un analista inmobiliario. Del documento adjunto extrae los datos del inmueble residencial.
Devuelve ÚNICAMENTE este JSON, sin texto adicional:
{
  "distrito": "distrito de Lima o null",
  "area_m2": null,
  "antiguedad_anios": null,
  "dormitorios": "1 Dormitorio / 2 Dormitorios / 3 Dormitorios / Dúplex / Otro — o null",
  "precio_usd": null,
  "alquiler_mes_usd": null,
  "descripcion": "breve descripción del inmueble o null"
}
Si un dato no aparece usa null. Solo extrae lo que está explícito.""",

        "industrial": """Eres un analista inmobiliario. Del documento adjunto extrae los datos del inmueble o proyecto industrial/logístico.
Devuelve ÚNICAMENTE este JSON, sin texto adicional:
{
  "distrito": "distrito de Lima o null",
  "area_terreno_m2": null,
  "frente_ml": null,
  "fondo_ml": null,
  "costo_terreno_usd": null,
  "tipo_nave": "Almacén Logístico / Nave Industrial / Cross-docking / Producción - Manufactura o null",
  "area_nave_m2": null,
  "renta_usd_m2_mes": null,
  "zonificacion": "I1/I2/I3/OU o null"
}
Si un dato no aparece usa null. Solo extrae lo que está explícito.""",
    }

    content.append({"type": "text", "text": PROMPTS.get(modulo, PROMPTS["residencial"])})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": content}]
    )
    if not response.content:
        return {"_error": "Sin respuesta de la API."}
    return parse_json_safe(response.content[0].text.strip())


def extraer_precios_cierre(partidas_bytes: list) -> list:
    """Extrae precio de última compraventa inscrita de cada partida SUNARP."""
    client = get_client()
    resultados = []
    for i, pdf_bytes in enumerate(partidas_bytes):
        content = [
            pdf_block(pdf_bytes),
            {"type": "text", "text": """Eres un experto en derecho registral peruano.
Analiza esta partida registral SUNARP y extrae los datos de la ÚLTIMA compraventa (o transferencia onerosa) inscrita.

Devuelve ÚNICAMENTE este JSON, sin texto adicional:
{
  "partida_numero": "número de partida o null",
  "descripcion_predio": "dirección o descripción breve del inmueble",
  "area_m2": null,
  "ultima_transferencia": {
    "precio": null,
    "moneda": "USD o PEN o null",
    "fecha": "dd/mm/aaaa o null",
    "vendedor": "nombre completo o null",
    "comprador": "nombre completo o null",
    "tipo_acto": "Compraventa/Dación en pago/Adjudicación/Anticipo/otro"
  },
  "precio_m2_estimado": null,
  "observaciones": "nota si el precio no está explícito, si hay varios asientos, o si algo es relevante para la tasación"
}

Si el precio no figura explícitamente usa null en precio y explícalo en observaciones.
Si hay varias transferencias reporta solo la más reciente por fecha de inscripción."""},
        ]
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": content}]
        )
        if not response.content:
            raise ValueError("json_parse_error: API devolvió respuesta vacía en comparable")
        r = parse_json_safe(response.content[0].text.strip())
        r["_idx"] = i + 1
        resultados.append(r)
    return resultados


def analizar_factibilidad_industrial(
    partida_bytes: bytes | None,
    cert_params_bytes: bytes | None,
    cert_zon_bytes: bytes | None,
    tipo_nave: str = "Almacén Logístico",
    zonificacion_ref: str = "I2",
    uso: str = "Uso directo",
    planos_bytes: bytes | None = None,
) -> dict:
    client = get_client()

    content = []
    docs_desc = []
    if partida_bytes:
        content.append(pdf_block(partida_bytes))
        docs_desc.append(f"Documento {len(docs_desc)+1}: Partida Registral (SUNARP)")
    if cert_params_bytes:
        content.append(pdf_block(cert_params_bytes))
        docs_desc.append(f"Documento {len(docs_desc)+1}: Certificado de Parámetros Urbanísticos")
    if cert_zon_bytes:
        content.append(pdf_block(cert_zon_bytes))
        docs_desc.append(f"Documento {len(docs_desc)+1}: Certificado de Zonificación y Vías")
    if planos_bytes:
        content.append(pdf_block(planos_bytes))
        docs_desc.append(f"Documento {len(docs_desc)+1}: Planos del Inmueble")

    prompt = f"""Eres un especialista en derecho inmobiliario, derecho registral y normativa urbanística industrial peruana.

Analiza los siguientes documentos de un inmueble industrial/logístico en Lima, Perú:
{chr(10).join(docs_desc)}

Contexto del proyecto:
- Actividad a desarrollar: {tipo_nave}
- Zonificación de referencia declarada por el usuario: {zonificacion_ref}
- Propósito: {uso}

Realiza dos análisis complementarios:

A) FACTIBILIDAD TÉCNICA: Determina si la zonificación certificada es compatible con la actividad industrial/logística declarada. Identifica restricciones de altura, acceso vehicular pesado, vías de frente, condiciones especiales.

B) ANÁLISIS LEGAL: Verifica titularidad, cargas, hipotecas, medidas cautelares, consistencia de área registral. Si solo hay Partida, analiza solo ese documento.

Devuelve ÚNICAMENTE el siguiente JSON, sin texto antes ni después:

{{
  "docs_analizados": ["lista de documentos efectivamente analizados"],
  "semaforo_tecnico": "verde/amarillo/rojo",
  "semaforo_legal": "verde/amarillo/rojo",
  "semaforo_global": "verde/amarillo/rojo",
  "zonificacion_certificada": null,
  "compatible_actividad": null,
  "nota_compatibilidad": "explicación detallada de la compatibilidad o incompatibilidad",
  "actividades_permitidas": [],
  "actividades_condicionadas": [],
  "actividades_prohibidas": [],
  "restricciones_altura_m": null,
  "restricciones_especiales": [],
  "vias_frente": [{{"nombre": "nombre de vía", "tipo": "arterial/colectora/local", "ancho_ml": null}}],
  "acceso_vehiculos_pesados": null,
  "area_registral_m2": null,
  "alertas_tecnicas": [],
  "alertas_legales": [],
  "propietarios_partida": [],
  "direccion_partida": null,
  "partida_numero": null,
  "cargas_vigentes": [{{"tipo": "...", "descripcion": "...", "acreedor": "...", "monto_referencial": "..."}}],
  "hipotecas_vigentes": [{{"acreedor": "...", "monto": "...", "estado": "vigente/cancelada"}}],
  "medidas_cautelares": [{{"tipo": "...", "descripcion": "..."}}],
  "resumen_tecnico": "2-3 oraciones sobre compatibilidad de zonificación y restricciones técnicas.",
  "resumen_legal": "2-3 oraciones sobre estado registral y alertas legales."
}}

CRITERIOS SEMÁFORO TÉCNICO:
- VERDE: zonificación compatible con la actividad, sin restricciones de acceso relevantes, sin condicionantes críticos
- AMARILLO: zonificación condicionada o requiere tramitación adicional, restricciones de acceso moderadas
- ROJO: zonificación incompatible con la actividad, prohibiciones explícitas, sin acceso para vehículos pesados

CRITERIOS SEMÁFORO LEGAL:
- VERDE: sin cargas ni hipotecas vigentes, sin medidas cautelares, propietarios claros
- AMARILLO: cargas canceladas aún anotadas, información parcial, diferencia de área ≤5%
- ROJO: hipotecas o embargos vigentes, medidas cautelares activas, discrepancias de titularidad

SEMÁFORO GLOBAL: el más restrictivo entre técnico y legal.
Si un dato no existe en los documentos usa null."""

    content.append({"type": "text", "text": prompt})

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{"role": "user", "content": content}]
    )
    if not response.content:
        raise ValueError("json_parse_error: API devolvió respuesta vacía")
    return parse_json_safe(response.content[0].text.strip())


# ═══════════════════════════════════════════════════════
# MODELO FINANCIERO
# ═══════════════════════════════════════════════════════

def calcular_financiero(cabida: dict, fin: dict, zona: str) -> dict:
    m  = MERCADO[zona]
    av = cabida.get("area_vendible_m2", 0)
    at = cabida.get("area_techada_total_m2", 0)

    # ── Ingresos ────────────────────────────────────────
    precio_m2    = fin.get("precio_venta_m2") if fin.get("precio_venta_m2", 0) > 0 else m.get("precio_2br", 0)
    ing_dptos    = av * precio_m2
    ing_estac    = cabida.get("estac_residentes", 0) * m["precio_estac"]
    ing_deposito = cabida.get("depositos_total", 0) * m["precio_deposito"]
    ing_brutos   = ing_dptos + ing_estac + ing_deposito

    # ── Terreno ─────────────────────────────────────────
    c_terreno_base  = fin["costo_terreno"]
    c_alcabala      = c_terreno_base * 0.03 if fin.get("include_alcabala", True) else 0
    c_notarial      = c_terreno_base * 0.003     # Gastos notariales: 0.3%
    c_registral     = c_terreno_base * 0.0015    # Gastos registrales: 0.15%
    c_due_dilig     = 11500 if fin.get("include_dd", True) else 0
    c_terreno_total = c_terreno_base + c_alcabala + c_notarial + c_registral + c_due_dilig

    # ── Construcción ────────────────────────────────────
    c_obra_dptos   = at * fin["costo_construccion"]
    c_sotanos_area = cabida.get("estac_total", 0) * 25
    c_obra_sotanos = c_sotanos_area * fin.get("costo_sotano_m2", 450)
    c_constructora = (c_obra_dptos + c_obra_sotanos) * fin.get("fee_constructora", 10.0) / 100
    c_construccion = c_obra_dptos + c_obra_sotanos + c_constructora

    # ── Costos Inmobiliarios — BOE validado (U. del Pacífico / Boro Fleischmann) ─
    c_arq          = at * 10.5                   # Arquitectura: $10.5/m² construido
    c_esp          = at * 4.4                    # Especialidades: $4.4/m² construido
    c_supervision  = c_construccion * 0.005      # Supervisión técnica: 0.5% costo directo
    c_costos_base  = c_terreno_total + c_construccion + c_arq + c_esp
    c_legales      = c_costos_base * 0.005       # Legales y contabilidad: 0.5%
    c_permisos     = c_construccion * 0.005      # Permisos y licencias: 0.5%
    c_gerenciamiento = ing_brutos * 0.060        # Gerenciamiento inmobiliario: 6% ingresos
    c_gestion_com  = ing_brutos * 0.005          # Gestión comercial: 0.5% ingresos
    c_publicidad   = ing_brutos * 0.025          # Publicidad y marketing: 2.5% ingresos
    c_ventas_fee   = ing_brutos * 0.030          # Comisiones de venta: 3% ingresos
    c_postventa    = ing_brutos * 0.005          # Post venta: 0.5% ingresos

    # ── Financiamiento (línea bancaria: 40% del costo construcción) ─
    # Costo financiero = interés sobre saldo promedio (50% de la línea durante el período de obra)
    # meses_obra calculados abajo pero usamos estimado preliminar aquí
    _n_pisos_prelim  = cabida.get("num_pisos", 7)
    _meses_obra_prel = max(18, _n_pisos_prelim * 2 + 8)
    c_linea_banco  = c_construccion * 0.40
    c_financiero   = c_linea_banco * 0.50 * fin.get("tasa_financ", 7.0) / 100 * (_meses_obra_prel / 12)

    # ── Totales ─────────────────────────────────────────
    c_sin_financ = (c_terreno_total + c_construccion + c_arq + c_esp + c_supervision +
                    c_legales + c_postventa + c_permisos +
                    c_gerenciamiento + c_gestion_com + c_publicidad + c_ventas_fee)
    c_total      = c_sin_financ + c_financiero

    utilidad_bruta = ing_brutos - c_total
    tasa_ir        = max(fin.get("tasa_ir", 29.5), 0) / 100
    c_ir           = utilidad_bruta * tasa_ir if utilidad_bruta > 0 else 0
    utilidad_neta  = utilidad_bruta - c_ir

    margen_bruto   = (utilidad_bruta / ing_brutos * 100) if ing_brutos else 0
    margen_neto    = (utilidad_neta  / ing_brutos * 100) if ing_brutos else 0
    roi            = (utilidad_neta  / c_total      * 100) if c_total else 0

    # Escenario sin financiamiento
    util_sin_f      = ing_brutos - c_sin_financ
    ir_sin_f        = util_sin_f * tasa_ir if util_sin_f > 0 else 0
    util_neta_sin_f = util_sin_f - ir_sin_f
    margen_sin_f    = (util_neta_sin_f / ing_brutos * 100) if ing_brutos else 0

    # Métricas estratégicas
    be_precio_m2    = round(c_sin_financ / av) if av > 0 else 0
    _otros_costos = (c_construccion + c_arq + c_esp + c_supervision + c_legales + c_postventa
                     + c_permisos + c_gerenciamiento + c_gestion_com + c_publicidad
                     + c_ventas_fee + c_due_dilig + c_notarial + c_registral)
    _ir_factor      = max(1 - tasa_ir, 0.50)
    max_terreno_20  = max(0, round(ing_brutos * (1 - 0.20 / _ir_factor) - _otros_costos))
    max_terreno_15  = max(0, round(ing_brutos * (1 - 0.15 / _ir_factor) - _otros_costos))
    max_terreno_12  = max(0, round(ing_brutos * (1 - 0.12 / _ir_factor) - _otros_costos))
    ratio_terreno   = round(c_terreno_base / ing_brutos * 100, 1) if ing_brutos > 0 else 0

    # TIT: Tasa de Incidencia del Terreno (professional KPI)
    tit_pct         = round(c_terreno_base / ing_brutos * 100, 1) if ing_brutos > 0 else 0

    vel             = m.get("velocidad_venta", 1.0)
    n_unidades      = cabida.get("total_unidades", 0)
    meses_venta     = round(n_unidades / vel) if (vel and n_unidades) else 0
    n_pisos         = cabida.get("num_pisos", 7)
    meses_obra      = max(18, n_pisos * 2 + 8)
    meses_proyecto  = max(meses_obra + 9, meses_venta + 9)

    if c_total > 0 and utilidad_neta > 0 and meses_proyecto > 0:
        # Factor 0.65: capital no está 100% inmovilizado desde el día 0 (se desembolsa en S-curve
        # durante obra y se recupera gradualmente en ventas — período efectivo ≈ 65% del total)
        tir_aprox = round(((1 + utilidad_neta / c_total) ** (12 / (meses_proyecto * 0.65)) - 1) * 100, 1)
    else:
        tir_aprox = 0.0

    return {
        "resumen": {
            "departamentos":        cabida.get("total_unidades", 0),
            "estacionamientos":     cabida.get("estac_total", 0),
            "m2_construibles":      round(at),
            "m2_vendibles":         round(av),
            "ingresos_brutos":      round(ing_brutos),
            "costo_total_sin_financ": round(c_sin_financ),
            "utilidad_bruta":       round(utilidad_bruta),
            "margen_bruto_pct":     round(margen_bruto, 1),
            "ir_pct":               round(tasa_ir * 100, 1),
            "costo_ir":             round(c_ir),
            "utilidad_neta":        round(utilidad_neta),
            "margen_pct":           round(margen_neto, 1),
            "utilidad_neta_sin_f":  round(util_neta_sin_f),
            "margen_sin_f_pct":     round(margen_sin_f, 1),
            "costo_financiero":     round(c_financiero),
            "costo_total_con_financ": round(c_total),
            "utilidad_con_financ":  round(utilidad_neta),
            "margen_con_financ_pct": round(margen_neto, 1),
            "roi_pct":              round(roi, 1),
            "tir_anual_pct":        tir_aprox,
            "be_precio_m2":         be_precio_m2,
            "max_terreno_20pct":    max_terreno_20,
            "max_terreno_15pct":    max_terreno_15,
            "max_terreno_12pct":    max_terreno_12,
            "ratio_terreno_pct":    ratio_terreno,
            "tit_pct":              tit_pct,
            "meses_obra":           meses_obra,
            "meses_venta":          meses_venta,
            "meses_proyecto":       meses_proyecto,
        },
        "detalle_ingresos": {
            "Departamentos":        round(ing_dptos),
            "Estacionamientos":     round(ing_estac),
            "Depósitos":            round(ing_deposito),
            "TOTAL INGRESOS":       round(ing_brutos),
        },
        "detalle_costos": {
            "── TERRENO ──────────────────────": 0,
            "Precio del terreno":              round(c_terreno_base),
            "Alcabala (3%)":                   round(c_alcabala),
            "Gastos notariales (0.3%)":        round(c_notarial),
            "Gastos registrales (0.15%)":      round(c_registral),
            "Due diligence":                   round(c_due_dilig),
            "── CONSTRUCCIÓN ─────────────────": 0,
            "Obra civil":                      round(c_obra_dptos),
            "Sótanos":                         round(c_obra_sotanos),
            f"Fee constructora ({fin.get('fee_constructora', 10):.0f}%)": round(c_constructora),
            "── COSTOS TÉCNICOS ───────────────": 0,
            "Arquitectura ($10.5/m²)":          round(c_arq),
            "Especialidades ($4.4/m²)":         round(c_esp),
            "Supervisión técnica (0.5%)":        round(c_supervision),
            "Permisos y licencias (0.5%)":       round(c_permisos),
            "── COSTOS INMOBILIARIOS ──────────": 0,
            "Gerenciamiento (6%)":              round(c_gerenciamiento),
            "Gestión comercial (0.5%)":         round(c_gestion_com),
            "Publicidad y marketing (2.5%)":    round(c_publicidad),
            "Comisiones de venta (3%)":         round(c_ventas_fee),
            "Post venta (0.5%)":                round(c_postventa),
            "Legales y contabilidad (0.5%)":    round(c_legales),
            "SUBTOTAL SIN FINANCIAMIENTO":      round(c_sin_financ),
            "Gasto financiero (banco)":         round(c_financiero),
            "TOTAL EGRESOS":                    round(c_total),
            "── RESULTADO ────────────────────": 0,
            f"IR ({fin.get('tasa_ir', 29.5):.1f}%)": round(c_ir),
        },
        "_raw": {
            "c_terreno_base":    c_terreno_base,
            "c_alcabala":        c_alcabala,
            "c_notarial":        c_notarial,
            "c_registral":       c_registral,
            "c_due_dilig":       c_due_dilig,
            "c_terreno_total":   c_terreno_total,
            "c_obra_dptos":      c_obra_dptos,
            "c_obra_sotanos":    c_obra_sotanos,
            "c_constructora":    c_constructora,
            "c_arq":             c_arq,
            "c_esp":             c_esp,
            "c_supervision":     c_supervision,
            "c_legales":         c_legales,
            "c_postventa":       c_postventa,
            "c_permisos":        c_permisos,
            "c_gerenciamiento":  c_gerenciamiento,
            "c_gestion_com":     c_gestion_com,
            "c_publicidad":      c_publicidad,
            "c_ventas_fee":      c_ventas_fee,
            "c_financiero":      c_financiero,
            "c_ir":              c_ir,
            "ing_brutos":        ing_brutos,
        },
    }


# ═══════════════════════════════════════════════════════
# GENERADOR DE REPORTE PDF
# ═══════════════════════════════════════════════════════

def generar_pdf_factis(result: dict, cabida: dict, params: dict,
                       fin_inputs: dict, zona: str,
                       legal: dict | None = None) -> bytes:
    """Genera el reporte PDF ejecutivo de Factis."""
    from io import BytesIO
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm, cm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.platypus import (SimpleDocTemplate, Paragraph, Spacer, Table,
                                    TableStyle, HRFlowable, KeepTogether, PageBreak,
                                    NextPageTemplate, BaseDocTemplate, Frame, PageTemplate)
    from reportlab.pdfgen import canvas as pdfgen_canvas

    # ── Paleta ──────────────────────────────────────────────────
    NAV   = colors.HexColor("#1E2D3D")
    GOLD  = colors.HexColor("#B8904A")
    GRN   = colors.HexColor("#1A4731")
    GRN_L = colors.HexColor("#E8F5EE")
    AMB   = colors.HexColor("#7A5500")
    AMB_L = colors.HexColor("#FFF8E6")
    RED   = colors.HexColor("#7A1A1A")
    RED_L = colors.HexColor("#FDECEA")
    GREY  = colors.HexColor("#7A7268")
    LGREY = colors.HexColor("#F5F2ED")
    BORD  = colors.HexColor("#D8D4CC")
    WHITE = colors.white

    W, H = A4
    M = 20 * mm  # márgenes

    r   = result.get("resumen", {})
    det = result.get("detalle_costos", {})
    ing = result.get("detalle_ingresos", {})

    today  = datetime.date.today().strftime("%d/%m/%Y")
    distrito = zona
    direccion = params.get("ubicacion") or params.get("direccion") or "—"

    # ── Clasificación viabilidad ─────────────────────────────────
    _mg  = r.get("margen_pct", 0)
    _tir = r.get("tir_anual_pct", 0)
    _tit = r.get("tit_pct", 0)
    _nombre_proy = fin_inputs.get("nombre_proyecto", "") or zona
    if _mg >= 20 and _tir >= 15:
        _perfil_txt, _perfil_col = "VIABILIDAD ALTA", GRN
    elif _mg >= 12 and _tir >= 10:
        _perfil_txt, _perfil_col = "VIABILIDAD MEDIA", AMB
    else:
        _perfil_txt, _perfil_col = "VIABILIDAD BAJA", RED

    # ── Valor terreno clasificación ─────────────────────────────
    _pc = fin_inputs.get("costo_terreno", 0)
    _v20 = r.get("max_terreno_20pct", 0)
    _v15 = r.get("max_terreno_15pct", 0)
    _v12 = r.get("max_terreno_12pct", 0)
    if _pc <= _v20:
        _zona_v, _zona_c = "ZONA ÓPTIMA", GRN
    elif _pc <= _v15:
        _zona_v, _zona_c = "ZONA ACEPTABLE", AMB
    elif _pc <= _v12:
        _zona_v, _zona_c = "ZONA DE RIESGO", RED
    else:
        _zona_v, _zona_c = "PRECIO ELEVADO", RED

    # ── Buffer y canvas ─────────────────────────────────────────
    buf = BytesIO()

    # Número de página en el footer
    def _footer(canvas_obj, doc):
        canvas_obj.saveState()
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.setFillColor(GREY)
        canvas_obj.drawString(M, 10 * mm,
            f"FACTIS — Análisis de Cabida y Factibilidad Financiera  ·  {today}")
        canvas_obj.drawRightString(W - M, 10 * mm,
            f"Preparado por Osterling Advisory  ·  Pág. {doc.page}")
        canvas_obj.restoreState()

    def _cover_page(canvas_obj, doc):
        # Fondo navy completo
        canvas_obj.setFillColor(NAV)
        canvas_obj.rect(0, 0, W, H, fill=1, stroke=0)
        # Banda gold lateral
        canvas_obj.setFillColor(GOLD)
        canvas_obj.rect(0, 0, 6 * mm, H, fill=1, stroke=0)
        # Wordmark FACTIS
        canvas_obj.setFillColor(WHITE)
        canvas_obj.setFont("Helvetica-Bold", 52)
        canvas_obj.drawString(M + 6 * mm, H - 55 * mm, "FACTIS")
        # Línea dorada
        canvas_obj.setStrokeColor(GOLD)
        canvas_obj.setLineWidth(1.2)
        canvas_obj.line(M + 6 * mm, H - 63 * mm, W - M, H - 63 * mm)
        # Subtítulo
        canvas_obj.setFont("Helvetica", 13)
        canvas_obj.setFillColor(colors.HexColor("#B8C8D8"))
        canvas_obj.drawString(M + 6 * mm, H - 72 * mm,
                              "Análisis de Cabida y Factibilidad Financiera")
        # Datos del proyecto
        canvas_obj.setFillColor(GOLD)
        canvas_obj.setFont("Helvetica-Bold", 10)
        canvas_obj.drawString(M + 6 * mm, H * 0.52, "PROYECTO")
        canvas_obj.setFont("Helvetica", 9)
        canvas_obj.setFillColor(WHITE)
        canvas_obj.drawString(M + 6 * mm, H * 0.52 - 14, f"Proyecto:   {_nombre_proy}")
        canvas_obj.drawString(M + 6 * mm, H * 0.52 - 27, f"Distrito:    {distrito}")
        canvas_obj.drawString(M + 6 * mm, H * 0.52 - 40, f"Dirección:  {direccion}")
        canvas_obj.drawString(M + 6 * mm, H * 0.52 - 53, f"Fecha:       {today}")
        # KPIs grandes en portada
        _kpis = [
            ("MARGEN NETO", f"{_mg:.1f}%"),
            ("TIR ANUAL",   f"{_tir:.1f}%"),
            ("ROI",         f"{r.get('roi_pct',0):.1f}%"),
        ]
        _kx = M + 6 * mm
        for _lbl, _val in _kpis:
            canvas_obj.setFillColor(colors.HexColor("#2A3D4D"))
            canvas_obj.rect(_kx, H * 0.25, 52 * mm, 28 * mm, fill=1, stroke=0)
            canvas_obj.setFillColor(GOLD)
            canvas_obj.setFont("Helvetica-Bold", 7)
            canvas_obj.drawString(_kx + 4 * mm, H * 0.25 + 22 * mm, _lbl)
            canvas_obj.setFillColor(WHITE)
            canvas_obj.setFont("Helvetica-Bold", 22)
            canvas_obj.drawString(_kx + 4 * mm, H * 0.25 + 9 * mm, _val)
            _kx += 56 * mm
        # Perfil de inversión
        canvas_obj.setFillColor(colors.HexColor("#2A3D4D"))
        canvas_obj.rect(M + 6 * mm, H * 0.15, 160 * mm, 18 * mm, fill=1, stroke=0)
        canvas_obj.setFillColor(GOLD)
        canvas_obj.setFont("Helvetica-Bold", 7)
        canvas_obj.drawString(M + 10 * mm, H * 0.15 + 12 * mm, "PERFIL DE INVERSIÓN")
        canvas_obj.setFillColor(WHITE)
        canvas_obj.setFont("Helvetica-Bold", 14)
        canvas_obj.drawString(M + 10 * mm, H * 0.15 + 4 * mm, _perfil_txt)
        canvas_obj.setFillColor(colors.HexColor("#8A9BAD"))
        canvas_obj.setFont("Helvetica", 8)
        canvas_obj.drawString(M + 70 * mm, H * 0.15 + 4 * mm,
                              f"TIT terreno: {_tit:.1f}% · Utilidad neta: {_fmt(r.get('utilidad_neta',0))}")
        # Footer portada
        canvas_obj.setFillColor(GREY)
        canvas_obj.setFont("Helvetica", 7)
        canvas_obj.drawString(M + 6 * mm, 12 * mm,
                              "Preparado por Osterling Advisory  ·  factis.pe")
        canvas_obj.drawRightString(W - M, 12 * mm, "Confidencial")

    def _fmt(v):
        v = v or 0
        if abs(v) >= 1_000_000:
            return f"${v/1_000_000:.2f}M"
        return f"${v:,.0f}"

    # ── Estilos ──────────────────────────────────────────────────
    styles = getSampleStyleSheet()

    def _style(name, parent="Normal", **kw):
        s = ParagraphStyle(name, parent=styles[parent], **kw)
        return s

    S_TITLE   = _style("s_title",  fontSize=14, textColor=NAV,
                        fontName="Helvetica-Bold", spaceAfter=4)
    S_SECTION = _style("s_sec",    fontSize=8,  textColor=GOLD,
                        fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4,
                        letterSpacing=2)
    S_BODY    = _style("s_body",   fontSize=9,  textColor=NAV,
                        fontName="Helvetica", leading=13)
    S_SMALL   = _style("s_small",  fontSize=7.5, textColor=GREY,
                        fontName="Helvetica", leading=11)
    S_NUM     = _style("s_num",    fontSize=9,  textColor=NAV,
                        fontName="Helvetica-Bold", alignment=TA_RIGHT)
    S_CENTER  = _style("s_ctr",    fontSize=9,  textColor=NAV,
                        fontName="Helvetica", alignment=TA_CENTER)

    def _section(txt):
        return [Paragraph(txt.upper(), S_SECTION),
                HRFlowable(width="100%", thickness=0.5, color=BORD, spaceAfter=4)]

    def _kpi_table(items):
        """items = list of (label, value, ref) tuples — 4 columnas principales.
        Each KPI is a nested 3-row table to avoid paragraph overlap."""
        col_w = (W - 2 * M) / len(items)
        inner_w = col_w - 8  # subtract left+right padding

        def _kpi_shorten(v_str):
            """$649,000 → $649K to avoid line wrap in narrow cells."""
            if v_str.startswith("$") and "," in v_str and not v_str.endswith("M"):
                try:
                    num = float(v_str[1:].replace(",", ""))
                    if abs(num) >= 100_000:
                        return f"${num / 1_000:.0f}K"
                except ValueError:
                    pass
            return v_str

        cells = []
        for i, (l, v, ref) in enumerate(items):
            v_disp = _kpi_shorten(v)
            p_lbl = Paragraph(l, _style(f"kl{i}", fontSize=7, fontName="Helvetica-Bold",
                                         textColor=GOLD, alignment=TA_CENTER, leading=9))
            p_val = Paragraph(v_disp, _style(f"kv{i}", fontSize=20, fontName="Helvetica-Bold",
                                              textColor=NAV, alignment=TA_CENTER, leading=24))
            p_ref = Paragraph(ref, _style(f"kr{i}", fontSize=7, fontName="Helvetica",
                                           textColor=GREY, alignment=TA_CENTER, leading=9))
            inner = Table(
                [[p_lbl], [p_val], [p_ref]],
                colWidths=[inner_w],
                rowHeights=[10, 22, 9],   # total 41pt — fits in 16mm cell
            )
            inner.setStyle(TableStyle([
                ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
                ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",   (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
                ("LEFTPADDING",  (0, 0), (-1, -1), 2),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ]))
            cells.append(inner)

        t = Table([cells], colWidths=[col_w] * len(items), rowHeights=[16 * mm])
        t.setStyle(TableStyle([
            ("BACKGROUND",   (0, 0), (-1, -1), LGREY),
            ("GRID",         (0, 0), (-1, -1), 0.5, BORD),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",   (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 2),
            ("LEFTPADDING",  (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]))
        return t

    def _cost_table(rows_dict):
        """rows_dict from detalle_costos"""
        data, styles_ts = [], []
        row_idx = 0
        for k, v in rows_dict.items():
            if k.startswith("──"):
                lbl = k.replace("──", "").replace("─", "").strip()
                data.append([Paragraph(lbl, _style(f"sh{row_idx}", fontSize=7.5,
                              textColor=GOLD, fontName="Helvetica-Bold")), ""])
                styles_ts += [
                    ("BACKGROUND",  (0, row_idx), (-1, row_idx), NAV),
                    ("TEXTCOLOR",   (0, row_idx), (-1, row_idx), GOLD),
                    ("TOPPADDING",  (0, row_idx), (-1, row_idx), 5),
                    ("BOTTOMPADDING",(0, row_idx),(-1, row_idx), 5),
                ]
            elif "TOTAL" in k or "SUBTOTAL" in k:
                data.append([Paragraph(f"<b>{k}</b>",
                              _style(f"st{row_idx}", fontSize=9, textColor=NAV,
                                     fontName="Helvetica-Bold")),
                             Paragraph(f"<b>{_fmt(v)}</b>",
                              _style(f"sv{row_idx}", fontSize=9, textColor=NAV,
                                     fontName="Helvetica-Bold", alignment=TA_RIGHT))])
                styles_ts += [
                    ("BACKGROUND", (0, row_idx), (-1, row_idx), colors.HexColor("#E8EDF3")),
                    ("LINEABOVE",  (0, row_idx), (-1, row_idx), 0.8, NAV),
                ]
            else:
                data.append([Paragraph(k, S_BODY),
                             Paragraph(_fmt(v), S_NUM)])
                if row_idx % 2 == 0:
                    styles_ts.append(("BACKGROUND", (0, row_idx), (-1, row_idx),
                                      colors.HexColor("#FDFAF6")))
            row_idx += 1

        col_w = W - 2 * M
        t = Table(data, colWidths=[col_w * 0.68, col_w * 0.32])
        t.setStyle(TableStyle([
            ("GRID",         (0, 0), (-1, -1), 0.3, BORD),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",   (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("LEFTPADDING",  (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ] + styles_ts))
        return t

    # ── Documento con portada especial ───────────────────────────
    doc = BaseDocTemplate(buf, pagesize=A4,
                          leftMargin=M, rightMargin=M,
                          topMargin=M, bottomMargin=18 * mm)

    cover_frame   = Frame(0, 0, W, H, id="cover")
    content_frame = Frame(M, 18 * mm, W - 2 * M, H - M - 18 * mm, id="content")

    doc.addPageTemplates([
        PageTemplate(id="cover",   frames=[cover_frame],
                     onPage=_cover_page),
        PageTemplate(id="content", frames=[content_frame],
                     onPage=_footer),
    ])

    story = []

    # ── Página 1: Portada (vacía — _cover_page la pinta) ────────
    story.append(NextPageTemplate("content"))
    story.append(PageBreak())

    # ── Página 2: Resumen Ejecutivo ───────────────────────────────
    story += _section("Resumen Ejecutivo")
    story.append(Paragraph(
        f"<b>Distrito:</b> {distrito} &nbsp;&nbsp; "
        f"<b>Dirección:</b> {direccion} &nbsp;&nbsp; "
        f"<b>Fecha:</b> {today}", S_BODY))
    story.append(Spacer(1, 8))

    # KPI panel 4 columnas
    story.append(_kpi_table([
        ("MARGEN NETO POST-IR",  f"{_mg:.1f}%",  "Ref. óptimo ≥ 20%"),
        ("TIR ANUAL ESTIMADA",   f"{_tir:.1f}%", "Ref. óptimo ≥ 15%"),
        ("ROI",                  f"{r.get('roi_pct',0):.1f}%", "Ref. óptimo ≥ 20%"),
        ("UTILIDAD NETA",        _fmt(r.get("utilidad_neta",0)), "post impuestos"),
    ]))
    story.append(Spacer(1, 8))

    # Perfil inversión + clasificación terreno (2 columnas)
    _perf_bg = {GRN: GRN_L, AMB: AMB_L, RED: RED_L, NAV: colors.HexColor("#EEF2F7")}
    _p_bg = _perf_bg.get(_perfil_col, LGREY)
    _cell_w2 = (W - 2 * M) * 0.5

    def _info_cell(label, value, sub, val_color=NAV):
        """Nested 3-row table for label / large-value / sub — spacing controlled via rowHeights."""
        _iw = _cell_w2 - 32   # inner width minus left+right padding
        _p_lbl = Paragraph(label, _style(f"il{label[:4]}", fontSize=7,
                            fontName="Helvetica-Bold", textColor=GOLD,
                            alignment=TA_CENTER, leading=9))
        _p_val = Paragraph(value, _style(f"iv{label[:4]}", fontSize=16,
                            fontName="Helvetica-Bold", textColor=val_color,
                            alignment=TA_CENTER, leading=20))
        _p_sub = Paragraph(sub,   _style(f"is{label[:4]}", fontSize=7,
                            fontName="Helvetica", textColor=GREY,
                            alignment=TA_CENTER, leading=9))
        _inner = Table([[_p_lbl], [_p_val], [_p_sub]],
                       colWidths=[_iw], rowHeights=[14, 24, 14])
        _inner.setStyle(TableStyle([
            ("ALIGN",        (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",   (0, 0), (-1, -1), 0),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
            ("LEFTPADDING",  (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ]))
        return _inner

    perf_cell = _info_cell(
        "PERFIL DE INVERSIÓN",
        _perfil_txt,
        f"TIT terreno: {_tit:.1f}% · Ref. óptima: 15–25%",
        val_color=_perfil_col,
    )
    zona_cell = _info_cell(
        "PRECIO TERRENO INGRESADO",
        _fmt(_pc),
        f"{_zona_v} · Óptimo: {_fmt(_v20)}",
        val_color=_zona_c,
    )
    t2 = Table([[perf_cell, zona_cell]],
               colWidths=[_cell_w2] * 2, rowHeights=[44 * mm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), _p_bg),
        ("BACKGROUND", (1, 0), (1, 0), LGREY),
        ("GRID",       (0, 0), (-1, -1), 0.5, BORD),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 16),
        ("RIGHTPADDING", (0, 0), (-1, -1), 16),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 0),
    ]))
    story.append(t2)
    story.append(Spacer(1, 8))

    # Indicadores secundarios
    _sec_data = [
        ["Ingresos brutos", _fmt(r.get("ingresos_brutos", 0)),
         "Meses de obra", f"{r.get('meses_obra',0)} meses"],
        ["Costo total s/financ.", _fmt(r.get("costo_total_sin_financ", 0)),
         "Meses de ventas", f"{r.get('meses_venta',0)} meses"],
        ["Costo financiero", _fmt(r.get("costo_financiero", 0)),
         "Duración total", f"{r.get('meses_proyecto',0)} meses"],
        [f"IR ({r.get('ir_pct',29.5):.1f}%)", _fmt(r.get("costo_ir", 0)),
         "Break-even m²", f"${r.get('be_precio_m2',0):,}/m²"],
    ]
    cw = (W - 2 * M) / 4
    sec_t = Table([[Paragraph(cell, S_BODY if i % 2 == 0 else S_NUM)
                    for i, cell in enumerate(row)]
                   for row in _sec_data],
                  colWidths=[cw * 1.4, cw * 0.9, cw * 1.1, cw * 0.6])
    sec_t.setStyle(TableStyle([
        ("GRID",        (0, 0), (-1, -1), 0.3, BORD),
        ("BACKGROUND",  (0, 0), (-1, -1), colors.HexColor("#FDFAF6")),
        ("BACKGROUND",  (2, 0), (3, -1), LGREY),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
    ]))
    story.append(sec_t)

    # ── Página 3: Cabida Arquitectónica ──────────────────────────
    story.append(PageBreak())
    story += _section("Programa Arquitectónico")

    # Parámetros normativos resumidos
    _param_rows = []
    for k in ["pisos_max", "area_libre_min", "retiro_frontal", "retiro_lateral",
              "coeficiente_edificacion", "densidad_neta", "uso_suelo", "zonificacion"]:
        v = params.get(k)
        if v is not None and v != "" and v != 0:
            _label = k.replace("_", " ").title()
            _param_rows.append([Paragraph(_label, S_BODY), Paragraph(str(v), S_NUM)])
    if _param_rows:
        p_cw = (W - 2 * M) / 2
        p_tbl = Table(_param_rows, colWidths=[p_cw * 1.3, p_cw * 0.7])
        p_tbl.setStyle(TableStyle([
            ("GRID",        (0, 0), (-1, -1), 0.3, BORD),
            ("BACKGROUND",  (0, 0), (-1, -1), colors.HexColor("#FDFAF6")),
            ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",  (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING",(0, 0), (-1, -1), 8),
        ]))
        story.append(p_tbl)
        story.append(Spacer(1, 8))

    # Programa volumétrico
    story += _section("Volúmenes y Superficies")
    _vol_data = [
        ["M² construibles totales", f"{cabida.get('area_techada_total_m2',0):,.0f} m²",
         "Pisos",                    str(cabida.get("num_pisos", "—"))],
        ["M² vendibles",            f"{cabida.get('area_vendible_m2',0):,.0f} m²",
         "Sótanos",                  str(cabida.get("num_sotanos", 0))],
        ["Área libre",               f"{cabida.get('area_libre_m2',0):,.0f} m²",
         "Depósitos",                str(cabida.get("depositos_total", 0))],
        ["Estac. residentes",         str(cabida.get("estac_residentes", 0)),
         "Estac. visitas",            str(cabida.get("estac_visitas", 0))],
    ]
    cw2 = (W - 2 * M) / 4
    vol_t = Table([[Paragraph(cell, S_BODY if i % 2 == 0 else S_NUM)
                    for i, cell in enumerate(row)]
                   for row in _vol_data],
                  colWidths=[cw2 * 1.3, cw2 * 0.9, cw2 * 1.0, cw2 * 0.8])
    vol_t.setStyle(TableStyle([
        ("GRID",        (0, 0), (-1, -1), 0.3, BORD),
        ("BACKGROUND",  (0, 0), (-1, -1), colors.HexColor("#FDFAF6")),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
    ]))
    story.append(vol_t)
    story.append(Spacer(1, 8))

    # Mix tipológico
    unidades = cabida.get("unidades", [])
    _pvm = fin_inputs.get("precio_venta_m2", 0) or 0
    if unidades:
        _num_pisos = cabida.get("num_pisos", 1) or 1
        _total_u   = cabida.get("total_unidades", 1) or 1
        _dptos_piso = round(_total_u / _num_pisos, 1)

        story += _section("Mix de Tipologías y Precio de Venta")
        # Nota dptos/piso
        story.append(Paragraph(
            f"Total: <b>{_total_u} departamentos</b> en <b>{_num_pisos} pisos</b> "
            f"(~{_dptos_piso} dptos/piso · precio de venta: <b>${_pvm:,.0f}/m²</b>)",
            S_SMALL))
        story.append(Spacer(1, 5))

        _hdr_cols = ["Tipología", "Cant.", "m²/und", "m² total",
                     "Precio/und", "Subtotal", "% mix"]
        u_header = [Paragraph(h, _style("uh", fontSize=7.5, textColor=WHITE,
                                         fontName="Helvetica-Bold", alignment=TA_CENTER))
                    for h in _hdr_cols]
        u_data = [u_header]
        for u in unidades:
            pct  = round(u.get("cantidad", 0) / _total_u * 100, 1)
            _am2 = u.get("area_m2", 0)
            _cant = u.get("cantidad", 0)
            _p_und  = _am2 * _pvm
            _p_tot  = _cant * _p_und
            u_data.append([
                Paragraph(u.get("tipo", "—"), S_BODY),
                Paragraph(str(_cant), S_NUM),
                Paragraph(f"{_am2:.0f}", S_NUM),
                Paragraph(f"{u.get('area_total_m2', 0):,.0f}", S_NUM),
                Paragraph(f"${_p_und:,.0f}" if _pvm else "—", S_NUM),
                Paragraph(f"${_p_tot:,.0f}" if _pvm else "—", S_NUM),
                Paragraph(f"{pct}%", S_NUM),
            ])
        # Fila totales
        _ing_dpts = sum(u.get("cantidad",0) * u.get("area_m2",0) * _pvm for u in unidades)
        u_data.append([
            Paragraph("<b>TOTAL</b>", _style("utot", fontSize=9, fontName="Helvetica-Bold", textColor=NAV)),
            Paragraph(f"<b>{_total_u}</b>", _style("utn", fontSize=9, fontName="Helvetica-Bold", textColor=NAV, alignment=TA_RIGHT)),
            Paragraph("", S_NUM),
            Paragraph(f"<b>{cabida.get('area_vendible_m2',0):,.0f}</b>", _style("utav", fontSize=9, fontName="Helvetica-Bold", textColor=NAV, alignment=TA_RIGHT)),
            Paragraph("", S_NUM),
            Paragraph(f"<b>${_ing_dpts:,.0f}</b>" if _pvm else "<b>—</b>",
                      _style("utit", fontSize=9, fontName="Helvetica-Bold", textColor=GRN, alignment=TA_RIGHT)),
            Paragraph("<b>100%</b>", _style("utpct", fontSize=9, fontName="Helvetica-Bold", textColor=NAV, alignment=TA_RIGHT)),
        ])

        _uw = W - 2 * M
        u_tbl = Table(u_data, colWidths=[_uw*0.22, _uw*0.08, _uw*0.09, _uw*0.11,
                                          _uw*0.16, _uw*0.18, _uw*0.10])
        u_tbl.setStyle(TableStyle([
            ("BACKGROUND",     (0, 0), (-1, 0),  NAV),
            ("BACKGROUND",     (0, -1),(-1, -1), colors.HexColor("#E8EDF3")),
            ("LINEABOVE",      (0, -1),(-1, -1), 0.8, NAV),
            ("GRID",           (0, 0), (-1, -1), 0.3, BORD),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2),
             [colors.HexColor("#FDFAF6"), colors.HexColor("#F0EDE8")]),
            ("VALIGN",         (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING",     (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING",  (0, 0), (-1, -1), 5),
            ("LEFTPADDING",    (0, 0), (-1, -1), 6),
            ("RIGHTPADDING",   (0, 0), (-1, -1), 6),
        ]))
        story.append(u_tbl)

    # Observaciones
    obs = cabida.get("observaciones", [])
    if obs:
        story.append(Spacer(1, 8))
        story += _section("Observaciones Normativas")
        for o in obs:
            story.append(Paragraph(f"• {o}", S_SMALL))

    # ── Página 4: Análisis Financiero ────────────────────────────
    story.append(PageBreak())
    story += _section("Análisis Financiero")

    # Panel ingresos vs costos
    _ing_rows = [(k, v) for k, v in ing.items() if v != 0]
    _ING_total = r.get("ingresos_brutos", 1) or 1
    ing_header = [Paragraph(h, _style("ih", fontSize=8, textColor=WHITE,
                                       fontName="Helvetica-Bold"))
                  for h in ["INGRESOS", "Monto", "% del total"]]
    ing_data = [ing_header]
    for k, v in _ing_rows:
        ing_data.append([Paragraph(k, S_BODY),
                          Paragraph(_fmt(v), S_NUM),
                          Paragraph(f"{v/_ING_total*100:.1f}%", S_NUM)])
    i_cw = (W - 2 * M) / 3
    ing_tbl = Table(ing_data, colWidths=[i_cw * 1.6, i_cw * 0.8, i_cw * 0.6])
    ing_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), GRN),
        ("GRID",       (0, 0), (-1, -1), 0.3, BORD),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [GRN_L, colors.HexColor("#F5FAF7")]),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING",(0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
    ]))
    story.append(ing_tbl)
    story.append(Spacer(1, 10))

    story += _section("Estructura de Costos")
    story.append(_cost_table(det))
    story.append(Spacer(1, 10))

    # Resultado final
    story += _section("Resumen de Resultado")
    _res_rows = [
        ("Ingresos brutos",     _fmt(r.get("ingresos_brutos", 0)),      ""),
        ("Costo total s/financ.", _fmt(r.get("costo_total_sin_financ", 0)), ""),
        ("Utilidad bruta",      _fmt(r.get("utilidad_bruta", 0)),
         f"{r.get('margen_bruto_pct',0):.1f}% bruto"),
        (f"Impuesto a la Renta ({r.get('ir_pct',29.5):.1f}%)",
         _fmt(r.get("costo_ir", 0)), ""),
        ("UTILIDAD NETA",       _fmt(r.get("utilidad_neta", 0)),
         f"{_mg:.1f}% neto"),
        ("",  "",  ""),
        ("Gasto financiero banco", _fmt(r.get("costo_financiero", 0)),  ""),
        ("Margen s/financiamiento", "",
         f"{r.get('margen_sin_f_pct',0):.1f}%"),
    ]
    r_cw = (W - 2 * M) / 3
    res_data = []
    res_styles_ts = []
    for idx, (a, b, c) in enumerate(_res_rows):
        if not a:
            continue
        is_total = "UTILIDAD NETA" in a
        sty = _style(f"rs{idx}", fontSize=9,
                     fontName="Helvetica-Bold" if is_total else "Helvetica",
                     textColor=NAV)
        res_data.append([Paragraph(a, sty),
                          Paragraph(b, _style(f"rv{idx}", fontSize=9,
                                              fontName="Helvetica-Bold" if is_total else "Helvetica",
                                              textColor=NAV, alignment=TA_RIGHT)),
                          Paragraph(c, _style(f"rc{idx}", fontSize=8,
                                              fontName="Helvetica",
                                              textColor=GRN if is_total else GREY,
                                              alignment=TA_RIGHT))])
        if is_total:
            res_styles_ts += [
                ("BACKGROUND", (0, len(res_data) - 1), (-1, len(res_data) - 1), GRN_L),
                ("LINEABOVE",  (0, len(res_data) - 1), (-1, len(res_data) - 1), 1.0, GRN),
            ]

    res_tbl = Table(res_data, colWidths=[r_cw * 1.5, r_cw * 0.9, r_cw * 0.6])
    res_tbl.setStyle(TableStyle([
        ("GRID",        (0, 0), (-1, -1), 0.3, BORD),
        ("BACKGROUND",  (0, 0), (-1, -1), colors.HexColor("#FDFAF6")),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",(0, 0), (-1, -1), 8),
    ] + res_styles_ts))
    story.append(res_tbl)

    # ── Página: Due Diligence Legal ──────────────────────────────
    if legal:
        story.append(PageBreak())
        story += _section("Due Diligence Legal — Análisis Registral")

        _sem = (legal.get("semaforo") or "amarillo").lower()
        _sem_map = {
            "verde":    (GRN,  GRN_L,  "#1A4731", "● SIN ALERTAS CRÍTICAS"),
            "amarillo": (AMB,  AMB_L,  "#7A5500", "▲ OBSERVACIONES MENORES"),
            "rojo":     (RED,  RED_L,  "#7A1A1A", "✕ ALERTAS CRÍTICAS"),
        }
        _sem_col, _sem_bg, _sem_hex, _sem_label = _sem_map.get(
            _sem, (colors.HexColor("#1E2D3D"), LGREY, "#1E2D3D", "○ INDETERMINADO"))

        # Semáforo banner
        sem_data = [[
            Paragraph(
                f'<para alignment="center">'
                f'<font name="Helvetica-Bold" size="11" color="{_sem_hex}">'
                f'{_sem_label}'
                f'</font></para>',
                _style("sem_lbl", fontSize=11, fontName="Helvetica-Bold",
                       textColor=_sem_col, alignment=TA_CENTER)),
        ]]
        sem_tbl = Table(sem_data, colWidths=[W - 2 * M])
        sem_tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, -1), _sem_bg),
            ("BOX",           (0, 0), (-1, -1), 1.5, _sem_col),
            ("LEFTPADDING",   (0, 0), (-1, -1), 14),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 14),
            ("TOPPADDING",    (0, 0), (-1, -1), 14),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ]))
        story.append(sem_tbl)
        story.append(Spacer(1, 8))

        # Resumen legal
        _resumen = legal.get("resumen_legal") or ""
        if _resumen:
            story.append(Paragraph(_resumen,
                _style("leg_res", fontSize=10, textColor=NAV, leading=15)))
            story.append(Spacer(1, 10))

        # Datos registrales clave
        _reg_items = [
            ("Propietario registral",    legal.get("propietario") or legal.get("titular") or "—"),
            ("Área registral",           legal.get("area_registral") or "—"),
            ("Partida registral N°",     legal.get("partida") or legal.get("numero_partida") or "—"),
            ("Cargas / gravámenes",      legal.get("cargas") or "—"),
            ("Hipotecas",                legal.get("hipotecas") or "—"),
            ("Medidas cautelares",       legal.get("medidas_cautelares") or "—"),
            ("Consistencia de área",     legal.get("consistencia_area") or "—"),
        ]
        # Solo mostrar filas con datos reales
        _reg_rows_filtered = [(k, v) for k, v in _reg_items if v and v != "—"]
        if _reg_rows_filtered:
            _reg_header = [
                Paragraph("DATO REGISTRAL", _style("rh0", fontSize=8, fontName="Helvetica-Bold",
                                                    textColor=WHITE)),
                Paragraph("DETALLE",        _style("rh1", fontSize=8, fontName="Helvetica-Bold",
                                                    textColor=WHITE)),
            ]
            _reg_data = [_reg_header] + [
                [Paragraph(k, _style(f"rk{i}", fontSize=9, textColor=NAV)),
                 Paragraph(str(v), _style(f"rv{i}", fontSize=9, textColor=NAV))]
                for i, (k, v) in enumerate(_reg_rows_filtered)
            ]
            _reg_cw = W - 2 * M
            _reg_tbl = Table(_reg_data, colWidths=[_reg_cw * 0.38, _reg_cw * 0.62])
            _reg_tbl.setStyle(TableStyle([
                ("BACKGROUND",    (0, 0), (-1, 0), NAV),
                ("GRID",          (0, 0), (-1, -1), 0.3, BORD),
                ("ROWBACKGROUNDS",(0, 1), (-1, -1), [LGREY, WHITE]),
                ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING",    (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
            ]))
            story.append(_reg_tbl)
            story.append(Spacer(1, 10))

        # Alertas
        _alertas = legal.get("alertas") or []
        if _alertas:
            story += _section("Alertas y Observaciones")
            for _al in _alertas:
                _al_data = [[
                    Paragraph("⚠",   _style("al_ic", fontSize=10, textColor=AMB,
                                             alignment=TA_CENTER)),
                    Paragraph(str(_al), _style("al_tx", fontSize=9, textColor=NAV, leading=14)),
                ]]
                _al_tbl = Table(_al_data, colWidths=[10 * mm, W - 2 * M - 10 * mm])
                _al_tbl.setStyle(TableStyle([
                    ("BACKGROUND",    (0, 0), (-1, -1), AMB_L),
                    ("BOX",           (0, 0), (-1, -1), 0.5, AMB),
                    ("LEFTPADDING",   (0, 0), (-1, -1), 8),
                    ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
                    ("TOPPADDING",    (0, 0), (-1, -1), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("VALIGN",        (0, 0), (-1, -1), "TOP"),
                ]))
                story.append(_al_tbl)
                story.append(Spacer(1, 5))

        # Recomendación final
        _recom = legal.get("recomendacion") or legal.get("conclusion") or ""
        if _recom:
            story.append(Spacer(1, 4))
            story += _section("Recomendación")
            story.append(Paragraph(_recom,
                _style("leg_rec", fontSize=10, textColor=NAV, leading=15)))

        # Nota de alcance
        story.append(Spacer(1, 14))
        story.append(Paragraph(
            "Nota: El análisis legal se basa exclusivamente en los documentos adjuntados "
            "(Partida Registral SUNARP y/o PU/HR). No sustituye la revisión de un abogado "
            "especialista en derecho registral y no cubre aspectos tributarios, ambientales "
            "ni de zonificación.",
            _style("leg_nota", fontSize=8, textColor=GREY, leading=12)))

    # ── Build ────────────────────────────────────────────────────
    doc.build(story)
    return buf.getvalue()


# ═══════════════════════════════════════════════════════
# HELPERS UI
# ═══════════════════════════════════════════════════════

def fmt_usd(v):
    v = v or 0
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    return f"${v:,.0f}"

def card(label, value, color="#1E2D3D"):
    st.markdown(f"""
    <div class="metric-card">
        <div class="label">{label}</div>
        <div class="value" style="color:{color}">{value}</div>
    </div>""", unsafe_allow_html=True)

def row_item(label, value, highlight=False):
    bg    = "#F5F0E8" if highlight else "#FFFFFF"
    fg    = "#1E2D3D"
    val_c = "#B8904A" if highlight else "#1E2D3D"
    bdr   = "#C8A86A" if highlight else "#E8E4DC"
    lw    = "600" if highlight else "400"
    st.markdown(f"""
    <div style="display:flex;justify-content:space-between;align-items:center;
                padding:9px 14px;background:{bg};border-radius:3px;
                margin-bottom:3px;border:1px solid {bdr};
                {'border-left:3px solid #B8904A;' if highlight else ''}">
        <span style="color:{fg};font-size:12px;letter-spacing:0.3px;font-weight:{lw}">{label}</span>
        <span style="color:{val_c};font-weight:700;font-size:13px">{value}</span>
    </div>""", unsafe_allow_html=True)


def score_viabilidad(r: dict) -> tuple:
    """Devuelve (pts, score_10, etiqueta, color_txt, color_bg, recomendacion, items)."""
    margen = r.get("margen_pct", 0)
    tir    = r.get("tir_anual_pct", 0)
    roi    = r.get("roi_pct", 0)
    pts, items = 0, []

    if margen >= 25:   pts += 4; items.append(("Margen neto",   f"{margen:.0f}%", 4, 4))
    elif margen >= 20: pts += 3; items.append(("Margen neto",   f"{margen:.0f}%", 3, 4))
    elif margen >= 15: pts += 2; items.append(("Margen neto",   f"{margen:.0f}%", 2, 4))
    elif margen >= 10: pts += 1; items.append(("Margen neto",   f"{margen:.0f}%", 1, 4))
    else:                         items.append(("Margen neto",   f"{margen:.0f}%", 0, 4))

    if tir >= 20:   pts += 3; items.append(("TIR anual",   f"{tir:.0f}%",    3, 3))
    elif tir >= 15: pts += 2; items.append(("TIR anual",   f"{tir:.0f}%",    2, 3))
    elif tir >= 10: pts += 1; items.append(("TIR anual",   f"{tir:.0f}%",    1, 3))
    else:                      items.append(("TIR anual",   f"{tir:.0f}%",    0, 3))

    if roi >= 20:   pts += 2; items.append(("ROI",         f"{roi:.0f}%",    2, 2))
    elif roi >= 15: pts += 1; items.append(("ROI",         f"{roi:.0f}%",    1, 2))
    else:                      items.append(("ROI",         f"{roi:.0f}%",    0, 2))

    score_10 = round(pts / 9 * 10, 1)

    if pts >= 8:
        return (pts, score_10, "VIABILIDAD ALTA",  "#1A4731", "#E8F5EE",
                "El proyecto muestra sólidos retornos. Proceder con due diligence.", items)
    elif pts >= 5:
        return (pts, score_10, "VIABILIDAD MEDIA", "#7A4F1A", "#FFF8EE",
                "Proyecto viable con condiciones. Revisar precio del terreno y mezcla tipológica.", items)
    else:
        return (pts, score_10, "VIABILIDAD BAJA",  "#7A1A1A", "#FFF0F0",
                "Los retornos no compensan el riesgo. Renegociar terreno o ajustar programa.", items)


@st.cache_data(show_spinner=False)
def calcular_sensibilidad(cabida: dict, fin_base: dict, zona: str) -> pd.DataFrame:
    """Matriz de márgenes % para ±20% en precio y costo."""
    variaciones = [-20, -10, 0, 10, 20]
    filas = []
    for dpct in variaciones:
        fila = []
        for cpct in variaciones:
            p_adj = fin_base["precio_venta_m2"] * (1 + dpct / 100)
            c_adj = fin_base["costo_construccion"] * (1 + cpct / 100)
            fin_adj = {**fin_base, "precio_venta_m2": p_adj, "costo_construccion": c_adj}
            r_adj = calcular_financiero(cabida, fin_adj, zona)["resumen"]
            fila.append(f"{r_adj['margen_pct']:.0f}%")
        filas.append(fila)
    cols = [f"Costo {x:+d}%" for x in variaciones]
    idx  = [f"Precio {x:+d}%" for x in variaciones]
    return pd.DataFrame(filas, columns=cols, index=idx)


def _s_curve_weights(n: int) -> list:
    """Bell-shaped marginal weights (slow-fast-slow disbursement), sum = 1.0.
    Uses midpoints t=(i+0.5)/n so no endpoint is ever zero (avoids $0 first/last month).
    """
    if n <= 0:
        return []
    if n == 1:
        return [1.0]
    raw = [6.0 * ((i + 0.5) / n) * (1.0 - (i + 0.5) / n) for i in range(n)]
    s = sum(raw) or 1.0
    return [w / s for w in raw]


def generar_flujo(cabida: dict, result_financiero: dict, fin: dict, zona: str):
    """DCF mensual completo: S-curve construcción, IGV crédito fiscal, sin-banco vs con-banco.
    Returns: (df, flujo_list, tir_anual, mes_be, max_exp, escenarios)
      escenarios = {
        "sin_banco": {"tir": float, "max_exp": int, "mes_be": int, "acum": list, "flujo": list},
        "con_banco":  {"tir": float, "max_exp": int, "mes_be": int, "acum": list, "flujo": list,
                       "saldo_deuda": list, "interes_total": float, "igv_credito": float},
      }
    """
    m   = MERCADO[zona]
    r   = result_financiero["resumen"]
    raw = result_financiero["_raw"]

    meses_obra   = r["meses_obra"]
    meses_venta  = max(r["meses_venta"], 1)
    n_unidades   = max(cabida.get("total_unidades", 1) or 1, 1)
    vel          = m.get("velocidad_venta", 1.0) or 1.0
    inicio_obra  = 3
    fin_obra     = inicio_obra + meses_obra
    total_meses  = fin_obra + 6
    n_months     = total_meses + 1

    # ── S-curve construcción ──────────────────────────
    c_obra       = raw["c_obra_dptos"] + raw["c_obra_sotanos"] + raw["c_constructora"]
    s_weights    = _s_curve_weights(meses_obra)
    obra_mensual = [c_obra * w for w in s_weights]

    # ── IGV crédito fiscal ────────────────────────────
    # 18% IGV pagado en construcción = crédito fiscal recuperable al saldo de obra
    igv_credito  = c_obra * 0.18

    # ── Banco ─────────────────────────────────────────
    pct_banco        = 0.40
    tasa_mes_banco   = fin.get("tasa_financ", 7.0) / 100 / 12

    # Pre-computa saldo deuda (interés capitalizado — se repaga en bloque al fin de obra)
    saldo_banco      = 0.0
    saldo_deuda_list = [0.0] * n_months
    for j, costo_mes in enumerate(obra_mensual):
        i = inicio_obra + j
        if i >= n_months:
            break
        draw         = costo_mes * pct_banco
        interes_i    = saldo_banco * tasa_mes_banco
        saldo_banco += draw + interes_i          # capitalizar interés en saldo
        saldo_deuda_list[i] = saldo_banco
    # interes total = saldo final - principal total
    principal_total = c_obra * pct_banco
    interes_total   = max(0.0, saldo_banco - principal_total)

    # ── Constructor de flujo genérico ─────────────────
    def _build_flujo(con_banco: bool) -> list:
        fl = [0.0] * n_months

        # Terreno: mes 0
        fl[0] -= raw["c_terreno_total"]

        # Diseño (arq + esp + permisos): meses 0-2
        soft = raw["c_arq"] + raw["c_esp"] + raw["c_permisos"]
        for i in range(3):
            fl[i] -= soft / 3

        # Legales: spread uniforme
        c_leg = raw["c_legales"] / n_months
        for i in range(n_months):
            fl[i] -= c_leg

        # Construcción + supervisión técnica con S-curve
        c_sup = raw.get("c_supervision", 0.0)
        for j, costo_mes in enumerate(obra_mensual):
            i = inicio_obra + j
            if i >= n_months:
                break
            sup_mes = c_sup * s_weights[j]
            if con_banco:
                fl[i] -= costo_mes * (1.0 - pct_banco) + sup_mes  # equity paga 60% obra + 100% supervisión
            else:
                fl[i] -= costo_mes + sup_mes                        # equity paga 100%

        # Repago banco (principal + interés capitalizado) al fin de obra
        if con_banco:
            fl[min(fin_obra, total_meses)] -= saldo_banco

        # Costos de ventas + gerenciamiento
        c_vtas = (raw["c_ventas_fee"] + raw["c_publicidad"]
                  + raw["c_gerenciamiento"] + raw["c_gestion_com"])
        for i in range(min(meses_venta, n_months)):
            fl[i] -= c_vtas / meses_venta

        # Post venta
        fl[min(fin_obra + 1, total_meses)] -= raw["c_postventa"]

        # Ingresos: PIE 10% | 20 cuotas 30% | saldo 60% al fin de obra
        precio_u      = raw["ing_brutos"] / n_unidades
        unidades_acum = 0.0
        for mes in range(n_months):
            restantes = n_unidades - unidades_acum
            if restantes < 0.001:
                break
            u_mes          = min(vel, restantes)
            unidades_acum += u_mes
            fl[mes] += precio_u * 0.10 * u_mes
            cuota = precio_u * 0.30 / 20 * u_mes
            for k in range(1, 21):
                if mes + k < n_months:
                    fl[mes + k] += cuota
            fl[min(fin_obra, total_meses)] += precio_u * 0.60 * u_mes

        # IR
        fl[min(fin_obra + 2, total_meses)] -= raw["c_ir"]

        return fl

    flujo_sin = _build_flujo(con_banco=False)
    flujo_con = _build_flujo(con_banco=True)

    def _stats(fl):
        tir_m  = _irr_bisect(fl)
        tir_a  = round(((1 + tir_m) ** 12 - 1) * 100, 1) if tir_m is not None else None
        acum, acc = 0.0, []
        for f in fl:
            acum += f
            acc.append(acum)
        mes_be  = next((i for i, a in enumerate(acc) if a >= 0 and i > 0), None)
        max_exp = min(acc)
        return tir_a, mes_be, round(max_exp), acc

    tir_sin, mes_be_sin, max_exp_sin, acum_sin = _stats(flujo_sin)
    tir_con, mes_be_con, max_exp_con, acum_con = _stats(flujo_con)

    escenarios = {
        "sin_banco": {
            "tir": tir_sin, "max_exp": max_exp_sin, "mes_be": mes_be_sin,
            "acum": acum_sin, "flujo": flujo_sin,
        },
        "con_banco": {
            "tir": tir_con, "max_exp": max_exp_con, "mes_be": mes_be_con,
            "acum": acum_con, "flujo": flujo_con,
            "saldo_deuda": saldo_deuda_list,
            "interes_total": round(interes_total),
            "igv_credito": round(igv_credito),
            "obra_mensual": [round(x) for x in obra_mensual],
        },
    }

    # Backward-compatible base (sin banco)
    tir_anual = tir_sin
    mes_be    = mes_be_sin
    max_exp   = max_exp_sin

    df = pd.DataFrame({
        "Mes":               list(range(n_months)),
        "Flujo Sin Banco":   [round(f) for f in flujo_sin],
        "Flujo Con Banco":   [round(f) for f in flujo_con],
        "Acum. Sin Banco":   [round(f) for f in acum_sin],
        "Acum. Con Banco":   [round(f) for f in acum_con],
        "Saldo Deuda":       [round(f) for f in saldo_deuda_list],
    })
    return df, flujo_sin, tir_anual, mes_be, max_exp, escenarios


def generar_resumen_ejecutivo_ia(tipo: str, datos: dict) -> dict:
    client = get_client()

    if tipo == "industrial":
        _dscr_str = (f"{datos['dscr']:.2f}x" if datos.get('dscr') else 'sin financiamiento')
        _payback_str = (f"{datos['payback_anos']:.1f} años" if datos.get('payback_anos') else 'N/A')
        _irr_str = (f"{datos['irr_anual']:.1f}%" if datos.get('irr_anual') is not None else 'N/A')
        ctx = (
            f"Activo: {datos.get('tipo_nave')} · Zonificación {datos.get('zonificacion')} · Uso: {datos.get('uso')}\n"
            f"Área nave: {datos.get('area_nave',0):,.0f} m² · Área libre: {datos.get('area_libre',0):,.0f} m²\n"
            f"Costo total: ${datos.get('costo_total',0):,.0f} · Costo/m² nave: ${datos.get('costo_por_m2_nave',0):,.0f}\n"
            f"Yield bruto: {datos.get('yield_bruto',0):.1f}% · Yield neto: {datos.get('yield_neto',0):.1f}%\n"
            f"DSCR: {_dscr_str}\n"
            f"Payback: {_payback_str}\n"
            f"TIR equity 10a: {_irr_str}\n"
            f"Capital propio: ${datos.get('capital_propio',0):,.0f} · Financiado: {datos.get('pct_credito',0):.0f}%\n"
            f"Renta mercado: ${datos.get('renta_m2_mes',0):.2f}/m²/mes"
        )
        tipo_label = "industrial / logístico en Lima, Perú"
        ref = ("Referencia Lima 2025-2026: yield neto target 6–8%, TIR equity mínima 12%, "
               "DSCR ≥ 1.20x, renta logística $5.5–7.0/m²/mes. "
               "Costo construcción nave industrial (estructura metálica, SIN acabados residenciales): "
               "Logística Clase A 12-14m clara $270–300/m², estándar $220–260/m², básica $180–220/m², "
               "cross-docking $380–500/m², manufactura $350–450/m². "
               "Patios/maniobras: $60–90/m². "
               "Proyecto de referencia real: Parque Logístico Lima 14,315 m² nave, 13.6m clara, "
               "inversión $291/m² all-in, renta $6.5/m²/mes, payback 3.74 años, yield bruto 26.8%. "
               "IMPORTANTE: costos industriales son 3-4x más bajos que construcción residencial "
               "por ser estructura metálica sin particiones ni acabados interiores.")
    else:
        _payback_str = (f"{datos['payback_anos']:.1f} años" if datos.get('payback_anos') else 'N/A')
        _flujo_str = (f"${datos['flujo_mensual']:,.0f}" if datos.get('flujo_mensual') is not None else 'N/A')
        ctx = (
            f"Inmueble: {datos.get('uso')} · Precio: ${datos.get('precio',0):,.0f}\n"
            f"Cuota mensual: ${datos.get('cuota_mensual',0):,.0f} · Plazo: {datos.get('plazo_anos')} años\n"
            f"Ingreso mínimo recomendado: ${datos.get('ingreso_minimo',0):,.0f}/mes\n"
            f"Yield bruto: {datos.get('yield_bruto',0):.1f}% · Yield neto: {datos.get('yield_neto',0):.1f}%\n"
            f"Payback: {_payback_str}\n"
            f"Flujo mensual neto: {_flujo_str}\n"
            f"Total intereses crédito: ${datos.get('total_intereses',0):,.0f}\n"
            f"Apreciación est. 5 años: +${datos.get('ganancia_capital_5',0):,.0f}"
        )
        tipo_label = "residencial en Lima, Perú"
        ref = ("Referencia Lima 2025-2026: yield neto residencial 4–6%, payback típico 18–25 años, "
               "cuota recomendada máx. 30% del ingreso mensual, apreciación histórica ~4%/año.")

    _bench_ctx = f"\n\nBENCHMARKS INDUSTRIALES DE REFERENCIA:\n{BENCHMARKS_INDUSTRIAL}" if tipo_label.startswith("industrial") else ""

    prompt = f"""Eres Enrique Osterling, director de Osterling Advisory, con 20 años de experiencia en activos comerciales e industriales en Lima. Eres directo, preciso y orientado a la decisión.

Analiza este activo {tipo_label}:

{ctx}

{ref}{_bench_ctx}
Tasa libre de riesgo Perú: ~7.5% (bonos soberanos PEN).

Devuelve ÚNICAMENTE este JSON sin texto adicional:
{{
  "recomendacion": "comprar/evaluar_con_condiciones/no_recomendado",
  "titulo": "Frase de 6-9 palabras resumiendo la oportunidad de inversión",
  "resumen": "2-3 oraciones describiendo el activo, su posicionamiento y contexto de mercado.",
  "argumentos_favor": ["argumento concreto 1", "argumento concreto 2", "argumento concreto 3"],
  "riesgos": ["riesgo concreto 1", "riesgo concreto 2"],
  "conclusion": "1-2 oraciones de recomendación final. Directo y accionable."
}}"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    )
    if not response.content:
        raise ValueError("json_parse_error: API devolvió respuesta vacía")
    return parse_json_safe(response.content[0].text.strip())


def generar_informe_industrial_html(r: dict, factibilidad: dict | None, fecha: str) -> str:
    NAV = "#1E2D3D"; GLD = "#B8904A"; LGT = "#F5F2ED"; BRD = "#D8D4CC"
    sem_col = {"verde": "#1A4731", "amarillo": "#7A4F1A", "rojo": "#7A1A1A"}
    sem_bg  = {"verde": "#E8F5EE", "amarillo": "#FFF8EE", "rojo": "#FFF0F0"}

    def kpi(label, value, sub=""):
        sub_html = f'<div style="font-size:10px;color:#7A7268;margin-top:3px;">{sub}</div>' if sub else ""
        return (f'<div style="background:#FFFFFF;border:1px solid {BRD};border-top:3px solid {GLD};'
                f'border-radius:5px;padding:14px 16px;min-width:140px;flex:1;">'
                f'<div style="font-size:9px;color:#9A9080;letter-spacing:2px;text-transform:uppercase;font-weight:600;">{label}</div>'
                f'<div style="font-size:22px;font-weight:700;color:{NAV};margin-top:6px;">{value}</div>'
                f'{sub_html}</div>')

    kpis_html = (
        kpi("Costo Total", f"${r['costo_total']:,.0f}") +
        kpi("Costo / m² nave", f"${r['costo_por_m2_nave']:,.0f}") +
        (kpi("Yield Neto", f"{r['yield_neto']:.1f}%", "anual s/ costo total") if r.get('yield_neto') else "") +
        (kpi("Payback", f"{r['payback_anos']:.1f} años") if r.get('payback_anos') else "") +
        (kpi("TIR Equity 10a", f"{r['irr_anual']:.1f}%" if r.get('irr_anual') is not None else "—") if r['uso'] == "Inversión" else "")
    )

    _ct = r.get('costo_total') or 1
    costo_rows = "".join(
        f'<tr><td style="padding:8px 12px;color:{NAV};font-size:12px;">{lbl}</td>'
        f'<td style="padding:8px 12px;color:{NAV};font-size:12px;text-align:right;font-weight:600;">${val:,.0f}</td>'
        f'<td style="padding:8px 12px;color:#7A7268;font-size:11px;text-align:right;">{pct}</td></tr>'
        for lbl, val, pct in [
            ("Terreno", r.get('costo_terreno', 0), f"{r.get('costo_terreno',0)/_ct*100:.1f}%"),
            ("Alcabala (3%)", r.get('alcabala', 0), f"{r.get('alcabala',0)/_ct*100:.1f}%"),
            (f"Nave techada ({r.get('area_nave',0):,.0f} m² × ${r.get('costo_nave_m2',0):,.0f}/m²)", r.get('costo_nave_total', 0), f"{r.get('costo_nave_total',0)/_ct*100:.1f}%"),
            (f"Piso área libre ({r.get('area_libre',0):,.0f} m² × ${r.get('costo_piso_libre_m2',0):,.0f}/m²)", r.get('costo_pisos_libres', 0), f"{r.get('costo_pisos_libres',0)/_ct*100:.1f}%"),
            (f"Costos Indirectos ({r.get('pct_indirectos', 5):.0f}%)", r.get('soft_costs', 0), f"{r.get('soft_costs',0)/_ct*100:.1f}%"),
            ("<strong>TOTAL</strong>", r.get('costo_total', 0), "100%"),
        ]
    )

    flujo_rows = ""
    if r.get('flujo_anual') and len(r['flujo_anual']) > 1:
        for i, f in enumerate(r['flujo_anual']):
            yr = f"Año {i}" if i > 0 else "Inversión inicial"
            col = "#1A4731" if f >= 0 else "#7A1A1A"
            flujo_rows += (f'<tr><td style="padding:7px 12px;font-size:12px;color:{NAV};">{yr}</td>'
                          f'<td style="padding:7px 12px;font-size:12px;color:{col};text-align:right;font-weight:600;">${f:,.0f}</td></tr>')

    fac_html = ""
    if factibilidad:
        sg = factibilidad.get("semaforo_global", "amarillo").lower()
        fac_html = (
            f'<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;'
            f'margin:28px 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Factibilidad Técnica y Legal</h3>'
            f'<div style="background:{sem_bg.get(sg,"#F5F2ED")};border-left:4px solid {sem_col.get(sg,NAV)};'
            f'border-radius:5px;padding:14px 18px;margin-bottom:12px;">'
            f'<div style="font-size:12px;color:{sem_col.get(sg,NAV)};font-weight:700;">'
            f'{"SIN ALERTAS CRÍTICAS" if sg=="verde" else ("OBSERVACIONES" if sg=="amarillo" else "ALERTAS CRÍTICAS")}</div>'
            f'<div style="font-size:12px;color:{sem_col.get(sg,NAV)};margin-top:6px;">{factibilidad.get("resumen_tecnico","")}</div>'
            f'<div style="font-size:12px;color:{sem_col.get(sg,NAV)};margin-top:4px;">{factibilidad.get("resumen_legal","")}</div>'
            f'</div>'
        )

    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<title>Informe Industrial — Osterling Advisory</title>
<style>body{{font-family:'Segoe UI',Arial,sans-serif;background:#EDEAE4;margin:0;padding:32px;color:{NAV};}}
.page{{background:#FFFFFF;max-width:860px;margin:0 auto;padding:48px 56px;border-radius:6px;}}
table{{width:100%;border-collapse:collapse;}}thead th{{background:{NAV};color:#FFFFFF;padding:9px 12px;font-size:10px;letter-spacing:1px;text-transform:uppercase;}}
tbody tr:nth-child(even) td{{background:#F9F7F4;}}
</style></head><body><div class="page">
<div style="border-bottom:2px solid {GLD};padding-bottom:20px;margin-bottom:28px;display:flex;justify-content:space-between;align-items:flex-end;">
  <div>
    <div style="font-size:9px;color:{GLD};letter-spacing:4px;text-transform:uppercase;font-weight:600;">Osterling Advisory</div>
    <div style="font-size:22px;font-weight:700;color:{NAV};margin-top:6px;">Análisis Logístico / Industrial</div>
    <div style="font-size:12px;color:#7A7268;margin-top:4px;">{r['tipo_nave']} · {r['zonificacion']} · {r['uso']}</div>
  </div>
  <div style="text-align:right;font-size:11px;color:#9A9080;">{fecha}<br>Lima, Perú</div>
</div>

<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Indicadores Clave</h3>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:28px;">{kpis_html}</div>

<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Distribución del Área</h3>
<table style="margin-bottom:24px;"><thead><tr><th>Componente</th><th style="text-align:right;">Área (m²)</th><th style="text-align:right;">% del Terreno</th></tr></thead>
<tbody>
<tr><td style="padding:8px 12px;font-size:12px;">Área total terreno</td><td style="padding:8px 12px;font-size:12px;text-align:right;">{r['area_terreno']:,.0f} m²</td><td style="padding:8px 12px;font-size:12px;text-align:right;color:#7A7268;">100%</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Nave techada</td><td style="padding:8px 12px;font-size:12px;text-align:right;font-weight:600;">{r['area_nave']:,.0f} m²</td><td style="padding:8px 12px;font-size:12px;text-align:right;">{r['pct_techada']:.0f}%</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Patios y maniobras</td><td style="padding:8px 12px;font-size:12px;text-align:right;">{r['area_libre']:,.0f} m²</td><td style="padding:8px 12px;font-size:12px;text-align:right;">{100-r['pct_techada']:.0f}%</td></tr>
</tbody></table>

<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Estructura de Costos</h3>
<table style="margin-bottom:24px;"><thead><tr><th>Concepto</th><th style="text-align:right;">Monto USD</th><th style="text-align:right;">% del Total</th></tr></thead>
<tbody>{costo_rows}</tbody></table>

<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Financiamiento</h3>
<table style="margin-bottom:24px;"><thead><tr><th>Concepto</th><th style="text-align:right;">Valor</th></tr></thead>
<tbody>
<tr><td style="padding:8px 12px;font-size:12px;">Capital propio</td><td style="padding:8px 12px;font-size:12px;text-align:right;font-weight:600;">${r['capital_propio']:,.0f} ({100-r['pct_credito']:.0f}%)</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Monto financiado</td><td style="padding:8px 12px;font-size:12px;text-align:right;">${r['monto_credito']:,.0f} ({r['pct_credito']:.0f}%)</td></tr>
{"<tr><td style='padding:8px 12px;font-size:12px;'>Cuota mensual</td><td style='padding:8px 12px;font-size:12px;text-align:right;'>$"+f"{r['cuota_mensual']:,.0f}"+"</td></tr>" if r['cuota_mensual'] > 0 else ""}
{"<tr><td style='padding:8px 12px;font-size:12px;'>Plazo</td><td style='padding:8px 12px;font-size:12px;text-align:right;'>"+str(r['plazo_anos'])+" años</td></tr>" if r['cuota_mensual'] > 0 else ""}
{"<tr><td style='padding:8px 12px;font-size:12px;'>DSCR</td><td style='padding:8px 12px;font-size:12px;text-align:right;font-weight:600;'>"+f"{r['dscr']:.2f}x"+"</td></tr>" if r.get('dscr') else ""}
</tbody></table>

{"<h3 style='color:"+NAV+";font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;border-bottom:1px solid "+BRD+";padding-bottom:6px;'>Flujo de Caja Proyectado (10 años)</h3><table style='margin-bottom:24px;'><thead><tr><th>Período</th><th style='text-align:right;'>Flujo USD</th></tr></thead><tbody>"+flujo_rows+"</tbody></table>" if flujo_rows else ""}

{fac_html}

<div style="margin-top:48px;border-top:1px solid {BRD};padding-top:20px;">
<p style="font-size:11px;font-weight:700;color:{NAV};margin:0;">Enrique Osterling</p>
<p style="font-size:10px;color:#555;margin:3px 0;">Gerente General — Osterling Advisory · Inmobiliaria Corporativa</p>
<p style="font-size:10px;color:#555;margin:3px 0;">+51 950 891 995 · eosterling@grupoosterling.com · Lima, Perú</p>
<p style="font-size:9px;color:#AAA;margin-top:12px;">Análisis referencial basado en los parámetros ingresados. No constituye asesoría legal ni financiera formal.</p>
</div></div></body></html>"""


def generar_propuesta_html(
    tipo: str,
    propietario: str,
    params: dict,
    financ: dict | None,
    legal: dict | None,
    comps_sunarp: list,
    precio_oferta: float,
    moneda_oferta: str,
    condiciones: str,
    plazo_respuesta: int,
    fecha: str,
    representante: str = "Enrique Osterling",
    cargo: str = "Director General",
) -> str:
    p  = params or {}
    r  = (financ or {}).get("resumen", {})
    lg = legal or {}
    NAV  = "#1E2D3D"
    GOLD = "#B8904A"
    tc   = 3.75

    precio_pen = round(precio_oferta * tc, 0) if moneda_oferta == "USD" else precio_oferta
    precio_usd = precio_oferta if moneda_oferta == "USD" else round(precio_oferta / tc, 0)
    area       = p.get("area_terreno_m2") or p.get("area_m2") or 0
    pm2_usd    = round(precio_usd / area, 0) if area > 0 else 0
    ubicacion  = p.get("ubicacion") or p.get("direccion") or "—"
    distrito   = p.get("distrito") or ""
    zona_res   = p.get("zona_residencial") or p.get("zonificacion") or "—"
    partida    = lg.get("partida_numero") or "—"
    propietario_reg = (", ".join(lg.get("propietarios_partida") or [])) or propietario

    # Comparables SUNARP
    comp_rows = ""
    precios_cierre = []
    for rc in comps_sunarp:
        ut  = rc.get("ultima_transferencia") or {}
        p_v = ut.get("precio")
        mon = ut.get("moneda", "USD")
        pm2 = rc.get("precio_m2_estimado")
        if p_v and mon == "PEN":
            p_v = round(p_v / tc, 0)
            pm2 = round(pm2 / tc, 0) if pm2 else None
        if pm2:
            precios_cierre.append(pm2)
        _pv_str  = f"${p_v:,.0f}"  if p_v  else "—"
        _pm2_str = f"${pm2:,.0f}/m²" if pm2 else "—"
        comp_rows += (
            "<tr>"
            f'<td style="padding:6px 10px;border:1px solid #E0DDD8;font-size:11px;">{rc.get("descripcion_predio","—")}</td>'
            f'<td style="padding:6px 10px;border:1px solid #E0DDD8;font-size:11px;text-align:center;">{rc.get("area_m2","—")}</td>'
            f'<td style="padding:6px 10px;border:1px solid #E0DDD8;font-size:11px;text-align:center;">{_pv_str}</td>'
            f'<td style="padding:6px 10px;border:1px solid #E0DDD8;font-size:11px;text-align:center;">{_pm2_str}</td>'
            f'<td style="padding:6px 10px;border:1px solid #E0DDD8;font-size:11px;text-align:center;">{ut.get("fecha","—")}</td>'
            "</tr>"
        )
    med_cierre = round(sum(precios_cierre) / len(precios_cierre), 0) if precios_cierre else None
    comp_section = ""
    if comp_rows:
        comp_section = f"""
        <div style="margin:24px 0 0;">
          <div style="font-size:10px;font-weight:700;color:{NAV};letter-spacing:2px;text-transform:uppercase;
                      border-bottom:2px solid {GOLD};padding-bottom:4px;margin-bottom:12px;">
            III. SUSTENTO DE VALOR — COMPARABLES SUNARP
          </div>
          <p style="font-size:11px;color:#555;margin-bottom:10px;">
            Los siguientes precios de cierre, obtenidos de partidas registrales SUNARP, respaldan el valor propuesto:
          </p>
          <table style="width:100%;border-collapse:collapse;margin-bottom:10px;">
            <thead>
              <tr style="background:{NAV};">
                <th style="padding:7px 10px;color:#fff;font-size:10px;font-weight:600;text-align:left;">Predio comparable</th>
                <th style="padding:7px 10px;color:#fff;font-size:10px;font-weight:600;text-align:center;">Área m²</th>
                <th style="padding:7px 10px;color:#fff;font-size:10px;font-weight:600;text-align:center;">Precio cierre</th>
                <th style="padding:7px 10px;color:#fff;font-size:10px;font-weight:600;text-align:center;">USD/m²</th>
                <th style="padding:7px 10px;color:#fff;font-size:10px;font-weight:600;text-align:center;">Fecha</th>
              </tr>
            </thead>
            <tbody>{comp_rows}</tbody>
          </table>
          {"<p style='font-size:11px;font-weight:700;color:" + NAV + ";'>Precio de cierre promedio (SUNARP): $" + f"{med_cierre:,.0f}/m²</p>" if med_cierre else ""}
        </div>"""

    # Financial summary
    fin_section = ""
    if r:
        fin_section = f"""
        <div style="margin:24px 0 0;">
          <div style="font-size:10px;font-weight:700;color:{NAV};letter-spacing:2px;text-transform:uppercase;
                      border-bottom:2px solid {GOLD};padding-bottom:4px;margin-bottom:12px;">
            IV. VIABILIDAD DEL PROYECTO — RESUMEN
          </div>
          <p style="font-size:11px;color:#555;margin-bottom:10px;">
            El análisis de viabilidad del proyecto sobre el inmueble arroja los siguientes indicadores:
          </p>
          <table style="width:100%;border-collapse:collapse;">
            <tbody>
              <tr style="background:#F8F5F0;">
                <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">TIR del proyecto (anual)</td>
                <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:700;color:{GOLD};">{r.get('tir_anual_pct','—')}%</td>
                <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Margen neto</td>
                <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:700;color:{GOLD};">{r.get('margen_pct','—')}%</td>
              </tr>
              <tr>
                <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Ingresos proyectados</td>
                <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;">${r.get('ingresos_brutos',0):,.0f}</td>
                <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Duración estimada</td>
                <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;">{r.get('meses_proyecto','—')} meses</td>
              </tr>
            </tbody>
          </table>
        </div>"""

    tipo_label = "COMPRA" if tipo == "Compra" else "ARRENDAMIENTO"
    renta_note = ""
    if tipo == "Arrendamiento":
        renta_note = f"""
        <tr style="background:#F8F5F0;">
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Renta mensual ofertada</td>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;" colspan="3">
            USD {precio_usd:,.0f} + IGV &nbsp;|&nbsp; S/. {precio_pen:,.0f} + IGV &nbsp;|&nbsp;
            USD {pm2_usd:,.2f}/m²/mes
          </td>
        </tr>"""
    else:
        renta_note = f"""
        <tr style="background:#F8F5F0;">
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Precio ofertado</td>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;" colspan="3">
            <strong>USD {precio_usd:,.0f}</strong> &nbsp;|&nbsp; S/. {precio_pen:,.0f} (TC {tc}) &nbsp;|&nbsp;
            USD {pm2_usd:,.0f}/m²
          </td>
        </tr>"""

    condiciones_html = "".join(
        f'<li style="margin-bottom:5px;font-size:11px;color:#444;">{c.strip()}</li>'
        for c in (condiciones or "").split("\n") if c.strip()
    ) or '<li style="font-size:11px;color:#888;">—</li>'

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Propuesta de {tipo_label} — {ubicacion}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Inter',sans-serif; background:#F4F1EC; color:#1E2D3D; }}
  .page {{ max-width:780px; margin:40px auto; background:#fff; padding:52px 56px;
           box-shadow:0 4px 32px rgba(0,0,0,0.10); }}
  @media print {{ body{{background:#fff}} .page{{box-shadow:none;margin:0;padding:40px}} }}
</style>
</head>
<body>
<div class="page">

  <!-- Header -->
  <div style="display:flex;justify-content:space-between;align-items:flex-start;
              border-bottom:3px solid {NAV};padding-bottom:20px;margin-bottom:28px;">
    <div>
      <div style="font-size:9px;letter-spacing:4px;text-transform:uppercase;color:{GOLD};
                  font-weight:700;margin-bottom:6px;">Osterling Advisory</div>
      <div style="font-size:26px;font-weight:800;color:{NAV};letter-spacing:-0.5px;">FACTIS</div>
      <div style="font-size:9px;letter-spacing:2px;text-transform:uppercase;color:#888;margin-top:2px;">
        Herramienta Analítica Inmobiliaria
      </div>
    </div>
    <div style="text-align:right;">
      <div style="font-size:10px;color:#888;">Lima, Perú &nbsp;|&nbsp; {fecha}</div>
      <div style="font-size:10px;color:#888;margin-top:4px;">eosterling@grupoosterling.com</div>
      <div style="display:inline-block;margin-top:10px;background:{GOLD};color:#fff;
                  font-size:10px;font-weight:700;letter-spacing:2px;text-transform:uppercase;
                  padding:5px 14px;border-radius:2px;">
        PROPUESTA DE {tipo_label}
      </div>
    </div>
  </div>

  <!-- Destinatario -->
  <div style="margin-bottom:24px;">
    <div style="font-size:12px;font-weight:600;color:{NAV};">Señor(es)</div>
    <div style="font-size:13px;font-weight:700;color:{NAV};margin-top:2px;">{propietario or propietario_reg}</div>
    <div style="font-size:11px;color:#666;margin-top:2px;">Propietario(s) del inmueble</div>
    <div style="margin-top:12px;font-size:11px;color:#444;line-height:1.7;">
      Por medio de la presente, <strong>Osterling Advisory</strong> — en representación de su cliente —
      tiene el agrado de presentar su propuesta formal de <strong>{tipo.lower()}</strong> para el
      inmueble de su propiedad, con las condiciones que se detallan a continuación.
    </div>
  </div>

  <!-- I. Identificación -->
  <div style="margin:24px 0 0;">
    <div style="font-size:10px;font-weight:700;color:{NAV};letter-spacing:2px;text-transform:uppercase;
                border-bottom:2px solid {GOLD};padding-bottom:4px;margin-bottom:12px;">
      I. IDENTIFICACIÓN DEL INMUEBLE
    </div>
    <table style="width:100%;border-collapse:collapse;">
      <tbody>
        <tr style="background:#F8F5F0;">
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;
                     color:{NAV};width:35%;">Ubicación</td>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;">{ubicacion}{(', ' + distrito) if distrito else ''}</td>
        </tr>
        <tr>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Partida Registral</td>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;">{partida}</td>
        </tr>
        <tr style="background:#F8F5F0;">
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Área del terreno</td>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;">{area:,.1f} m²</td>
        </tr>
        <tr>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Zonificación</td>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;">{zona_res}</td>
        </tr>
        <tr style="background:#F8F5F0;">
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Propietario registral</td>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;">{propietario_reg}</td>
        </tr>
      </tbody>
    </table>
  </div>

  <!-- II. Propuesta económica -->
  <div style="margin:24px 0 0;">
    <div style="font-size:10px;font-weight:700;color:{NAV};letter-spacing:2px;text-transform:uppercase;
                border-bottom:2px solid {GOLD};padding-bottom:4px;margin-bottom:12px;">
      II. PROPUESTA ECONÓMICA Y CONDICIONES
    </div>
    <table style="width:100%;border-collapse:collapse;margin-bottom:14px;">
      <tbody>
        {renta_note}
        <tr{"" if tipo == "Arrendamiento" else ' style="background:#F8F5F0;"'}>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;font-weight:600;color:{NAV};">Plazo de respuesta</td>
          <td style="padding:8px 12px;border:1px solid #E0DDD8;font-size:11px;" colspan="3">{plazo_respuesta} días calendario desde la recepción de la presente</td>
        </tr>
      </tbody>
    </table>
    <div style="font-size:10px;font-weight:700;color:{NAV};margin-bottom:8px;text-transform:uppercase;
                letter-spacing:1px;">Condiciones de la operación</div>
    <ul style="padding-left:18px;margin:0;">{condiciones_html}</ul>
  </div>

  {comp_section}
  {fin_section}

  <!-- Cierre -->
  <div style="margin-top:40px;padding-top:20px;border-top:1px solid #E0DDD8;">
    <p style="font-size:11px;color:#444;line-height:1.7;margin-bottom:24px;">
      Quedamos a su disposición para cualquier consulta o coordinación adicional.
      La presente propuesta tiene carácter indicativo y no genera obligación legal hasta la
      suscripción de un documento de compraventa / arrendamiento definitivo.
    </p>
    <div style="display:flex;justify-content:space-between;align-items:flex-end;">
      <div>
        <div style="font-size:12px;font-weight:700;color:{NAV};">{representante}</div>
        <div style="font-size:10px;color:#666;">{cargo}</div>
        <div style="font-size:10px;color:{GOLD};margin-top:2px;">Osterling Advisory</div>
      </div>
      <div style="text-align:right;font-size:9px;color:#AAA;">
        Generado con FACTIS · Osterling Advisory<br>
        eosterling@grupoosterling.com · Lima, Perú
      </div>
    </div>
  </div>

</div>
</body>
</html>"""


def generar_informe_residencial_html(r: dict, legal: dict | None, fecha: str,
                                      distrito: str = "", m2: int = 0, antiguedad: int = 0, fotos: list = None) -> str:
    NAV = "#1E2D3D"; GLD = "#B8904A"; BRD = "#D8D4CC"
    sem_col = {"verde": "#1A4731", "amarillo": "#7A4F1A", "rojo": "#7A1A1A"}
    sem_bg  = {"verde": "#E8F5EE", "amarillo": "#FFF8EE", "rojo": "#FFF0F0"}

    def kpi(label, value, sub=""):
        sub_html = f'<div style="font-size:10px;color:#7A7268;margin-top:3px;">{sub}</div>' if sub else ""
        return (f'<div style="background:#FFFFFF;border:1px solid {BRD};border-top:3px solid {GLD};'
                f'border-radius:5px;padding:14px 16px;min-width:130px;flex:1;">'
                f'<div style="font-size:9px;color:#9A9080;letter-spacing:2px;text-transform:uppercase;font-weight:600;">{label}</div>'
                f'<div style="font-size:20px;font-weight:700;color:{NAV};margin-top:6px;">{value}</div>'
                f'{sub_html}</div>')

    kpis = (kpi("Precio", f"${r['precio']:,.0f}") +
            kpi("Pago inicial", f"${r['pie']:,.0f}", f"{r['pct_pie']:.0f}%") +
            kpi("Cuota Mensual", f"${r['cuota_mensual']:,.0f}" if r['cuota_mensual'] > 0 else "Al contado") +
            kpi("Ingreso Mínimo", f"${r['ingreso_minimo']:,.0f}" if r['ingreso_minimo'] > 0 else "—", "recomendado") +
            (kpi("Yield Neto", f"{r['yield_neto']:.1f}%") if r['uso'] == "Inversión" else "") +
            (kpi("Payback", f"{r['payback_anos']:.1f} años") if r.get('payback_anos') else ""))

    amort_rows = "".join(
        f'<tr><td style="padding:7px 12px;font-size:12px;text-align:center;">{row["año"]}</td>'
        f'<td style="padding:7px 12px;font-size:12px;text-align:right;color:#1A4731;font-weight:600;">${row["capital"]:,.0f}</td>'
        f'<td style="padding:7px 12px;font-size:12px;text-align:right;color:#7A4F1A;">${row["interes"]:,.0f}</td>'
        f'<td style="padding:7px 12px;font-size:12px;text-align:right;">${row["saldo"]:,.0f}</td></tr>'
        for row in (r.get('amort_tabla') or [])
    )

    legal_html = ""
    if legal:
        sg = legal.get("semaforo", "amarillo").lower()
        legal_html = (
            f'<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;'
            f'margin:28px 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Análisis Legal</h3>'
            f'<div style="background:{sem_bg.get(sg,"#F5F2ED")};border-left:4px solid {sem_col.get(sg,NAV)};'
            f'border-radius:5px;padding:14px 18px;margin-bottom:12px;">'
            f'<div style="font-size:12px;color:{sem_col.get(sg,NAV)};font-weight:700;">'
            f'{"SIN ALERTAS CRÍTICAS" if sg=="verde" else ("OBSERVACIONES MENORES" if sg=="amarillo" else "ALERTAS CRÍTICAS")}</div>'
            f'<div style="font-size:12px;color:{sem_col.get(sg,NAV)};margin-top:6px;">{legal.get("resumen_legal","")}</div>'
            f'</div>'
        )
        for al in (legal.get("alertas") or []):
            legal_html += f'<div style="background:#FFF8EE;border-left:3px solid {GLD};border-radius:4px;padding:10px 14px;margin-bottom:6px;font-size:12px;color:{NAV};">⚠ {al}</div>'

    prop_section = ""
    if r['uso'] == "Inversión":
        prop_section = f"""
<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:24px 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Análisis de Inversión</h3>
<table style="margin-bottom:20px;"><thead><tr><th>Indicador</th><th style="text-align:right;">Valor</th></tr></thead><tbody>
<tr><td style="padding:8px 12px;font-size:12px;">Alquiler mensual estimado</td><td style="padding:8px 12px;font-size:12px;text-align:right;">${r['alquiler_mes']:,.0f}</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Renta neta mensual</td><td style="padding:8px 12px;font-size:12px;text-align:right;font-weight:600;">${r['renta_neta_mes']:,.0f}</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Yield bruto anual</td><td style="padding:8px 12px;font-size:12px;text-align:right;">{r['yield_bruto']:.1f}%</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Yield neto anual</td><td style="padding:8px 12px;font-size:12px;text-align:right;font-weight:600;">{r['yield_neto']:.1f}%</td></tr>
{'<tr><td style="padding:8px 12px;font-size:12px;">Payback</td><td style="padding:8px 12px;font-size:12px;text-align:right;">'+f"{r['payback_anos']:.1f} años"+'</td></tr>' if r.get('payback_anos') else ''}
{'<tr><td style="padding:8px 12px;font-size:12px;">Flujo mensual neto</td><td style="padding:8px 12px;font-size:12px;text-align:right;font-weight:600;">$'+f"{r['flujo_mensual']:,.0f}"+'</td></tr>' if r.get('flujo_mensual') is not None else ''}
</tbody></table>
<table style="margin-bottom:20px;"><thead><tr><th>Apreciación estimada (4%/año)</th><th style="text-align:right;">Valor</th><th style="text-align:right;">Ganancia</th></tr></thead><tbody>
<tr><td style="padding:8px 12px;font-size:12px;">Valor a 5 años</td><td style="padding:8px 12px;font-size:12px;text-align:right;">${r['valor_5']:,.0f}</td><td style="padding:8px 12px;font-size:12px;text-align:right;color:#1A4731;">+${r['ganancia_capital_5']:,.0f}</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Valor a 10 años</td><td style="padding:8px 12px;font-size:12px;text-align:right;">${r['valor_10']:,.0f}</td><td style="padding:8px 12px;font-size:12px;text-align:right;color:#1A4731;font-weight:600;">+${r['ganancia_capital_10']:,.0f}</td></tr>
</tbody></table>"""

    _fotos_html = ""
    if fotos:
        import base64
        _fotos_html = '<div style="page-break-before:always;margin-top:40px;"><div class="section-title">Fotografías del Inmueble</div><div style="display:flex;flex-wrap:wrap;gap:12px;margin-top:16px;">'
        for _fb in fotos[:6]:
            try:
                _b64 = base64.b64encode(_fb).decode()
                _fotos_html += f'<img src="data:image/jpeg;base64,{_b64}" style="max-width:48%;max-height:300px;object-fit:cover;border-radius:6px;border:1px solid #E4E0D8;">'
            except Exception:
                pass
        _fotos_html += '</div></div>'

    _rpt_precio    = r.get("precio", 0)
    _rpt_ppm2      = r.get("precio_m2", 0)
    _rpt_yield     = r.get("yield_bruto", 0)
    _rpt_dorm      = r.get("dormitorios", "—")
    _rpt_precio_s  = f"{_rpt_precio:,}"
    _rpt_ppm2_s    = f"{_rpt_ppm2:,}"
    _rpt_yield_s   = f"{_rpt_yield:.1f}%" if _rpt_yield > 0 else "—"

    return f"""<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
<title>Informe Residencial — Osterling Advisory</title>
<style>body{{font-family:'Segoe UI',Arial,sans-serif;background:#EDEAE4;margin:0;padding:32px;color:{NAV};}}
.page{{background:#FFFFFF;max-width:860px;margin:0 auto;padding:48px 56px;border-radius:6px;}}
table{{width:100%;border-collapse:collapse;}}thead th{{background:{NAV};color:#FFFFFF;padding:9px 12px;font-size:10px;letter-spacing:1px;text-transform:uppercase;}}
tbody tr:nth-child(even) td{{background:#F9F7F4;}}
</style></head><body><div class="page">
<div style="background:linear-gradient(135deg,#1E2D3D 0%,#2A4060 100%);
            border-radius:12px;padding:36px 40px;margin-bottom:32px;color:#FFFFFF;">
    <div style="font-size:8px;letter-spacing:4px;text-transform:uppercase;
                color:rgba(255,255,255,0.5);margin-bottom:12px;">
        FACTIS · Informe de Análisis Residencial · {fecha}
    </div>
    <div style="font-size:32px;font-weight:800;line-height:1.2;margin-bottom:8px;">
        {distrito if distrito else r.get("zona", "—")} &nbsp;·&nbsp; {_rpt_dorm}
    </div>
    <div style="font-size:14px;color:rgba(255,255,255,0.7);margin-bottom:24px;">
        {str(m2) + " m²" if m2 else ""}{(" &nbsp;·&nbsp; " + str(antiguedad) + " años de antigüedad") if antiguedad else ""}
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px;">
        <div style="background:rgba(255,255,255,0.10);border-radius:8px;padding:16px;">
            <div style="font-size:9px;color:rgba(255,255,255,0.5);text-transform:uppercase;
                        letter-spacing:1px;margin-bottom:4px;">Precio de compra</div>
            <div style="font-size:20px;font-weight:700;">${_rpt_precio_s}</div>
        </div>
        <div style="background:rgba(255,255,255,0.10);border-radius:8px;padding:16px;">
            <div style="font-size:9px;color:rgba(255,255,255,0.5);text-transform:uppercase;
                        letter-spacing:1px;margin-bottom:4px;">Precio / m²</div>
            <div style="font-size:20px;font-weight:700;">${_rpt_ppm2_s}/m²</div>
        </div>
        <div style="background:rgba(255,255,255,0.10);border-radius:8px;padding:16px;">
            <div style="font-size:9px;color:rgba(255,255,255,0.5);text-transform:uppercase;
                        letter-spacing:1px;margin-bottom:4px;">Yield bruto</div>
            <div style="font-size:20px;font-weight:700;">{_rpt_yield_s}</div>
        </div>
    </div>
</div>
<div style="border-bottom:2px solid {GLD};padding-bottom:20px;margin-bottom:28px;display:flex;justify-content:space-between;align-items:flex-end;">
  <div>
    <div style="font-size:9px;color:{GLD};letter-spacing:4px;text-transform:uppercase;font-weight:600;">Osterling Advisory</div>
    <div style="font-size:22px;font-weight:700;color:{NAV};margin-top:6px;">Evaluación Inmueble Residencial</div>
    <div style="font-size:12px;color:#7A7268;margin-top:4px;">{r['uso']}{(" · "+distrito) if distrito else ""}{(" · "+str(m2)+" m²") if m2 else ""}{(" · "+str(antiguedad)+" años") if antiguedad else ""}</div>
  </div>
  <div style="text-align:right;font-size:11px;color:#9A9080;">{fecha}<br>Lima, Perú</div>
</div>

<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Indicadores Clave</h3>
<div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:28px;">{kpis}</div>

<h3 style="color:{NAV};font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;border-bottom:1px solid {BRD};padding-bottom:6px;">Estructura de Crédito Hipotecario</h3>
<table style="margin-bottom:24px;"><thead><tr><th>Concepto</th><th style="text-align:right;">Valor</th></tr></thead><tbody>
<tr><td style="padding:8px 12px;font-size:12px;">Precio de compra</td><td style="padding:8px 12px;font-size:12px;text-align:right;font-weight:600;">${r['precio']:,.0f}</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Pago inicial ({r['pct_pie']:.0f}%)</td><td style="padding:8px 12px;font-size:12px;text-align:right;">${r['pie']:,.0f}</td></tr>
<tr><td style="padding:8px 12px;font-size:12px;">Monto del crédito</td><td style="padding:8px 12px;font-size:12px;text-align:right;">${r['monto_credito']:,.0f}</td></tr>
{"<tr><td style='padding:8px 12px;font-size:12px;'>Tasa de interés</td><td style='padding:8px 12px;font-size:12px;text-align:right;'>"+f"{r['tasa_anual']:.2f}% TEA"+"</td></tr>" if r.get('cuota_mensual',0)>0 else ""}
{"<tr><td style='padding:8px 12px;font-size:12px;'>Plazo</td><td style='padding:8px 12px;font-size:12px;text-align:right;'>"+str(r['plazo_anos'])+" años ("+str(r['n_meses'])+" cuotas)"+"</td></tr>" if r.get('cuota_mensual',0)>0 else ""}
{"<tr><td style='padding:8px 12px;font-size:12px;'>Cuota mensual</td><td style='padding:8px 12px;font-size:12px;text-align:right;font-weight:600;'>$"+f"{r['cuota_mensual']:,.0f}"+"</td></tr>" if r.get('cuota_mensual',0)>0 else ""}
{"<tr><td style='padding:8px 12px;font-size:12px;'>Total pagado al banco</td><td style='padding:8px 12px;font-size:12px;text-align:right;'>$"+f"{r['total_pagado']:,.0f}"+" (intereses: $"+f"{r['total_intereses']:,.0f}"+")"+"</td></tr>" if r.get('cuota_mensual',0)>0 else ""}
{"<tr><td style='padding:8px 12px;font-size:12px;'>Ingreso mínimo recomendado</td><td style='padding:8px 12px;font-size:12px;text-align:right;font-weight:600;'>$"+f"{r['ingreso_minimo']:,.0f}"+"/mes</td></tr>" if r.get('ingreso_minimo',0)>0 else ""}
</tbody></table>

{prop_section}

{"<h3 style='color:"+NAV+";font-size:12px;letter-spacing:2px;text-transform:uppercase;margin:0 0 12px;border-bottom:1px solid "+BRD+";padding-bottom:6px;'>Tabla de Amortización (primeros 10 años)</h3><table><thead><tr><th style='text-align:center;'>Año</th><th style='text-align:right;'>Capital Pagado</th><th style='text-align:right;'>Intereses</th><th style='text-align:right;'>Saldo</th></tr></thead><tbody>"+amort_rows+"</tbody></table>" if amort_rows else ""}

{legal_html}

<div style="margin-top:48px;border-top:1px solid {BRD};padding-top:20px;">
<p style="font-size:11px;font-weight:700;color:{NAV};margin:0;">Enrique Osterling</p>
<p style="font-size:10px;color:#555;margin:3px 0;">Gerente General — Osterling Advisory · Inmobiliaria Corporativa</p>
<p style="font-size:10px;color:#555;margin:3px 0;">+51 950 891 995 · eosterling@grupoosterling.com · Lima, Perú</p>
<p style="font-size:9px;color:#AAA;margin-top:12px;">Análisis referencial. No constituye asesoría legal ni financiera formal.</p>
</div>
{_fotos_html}
</div></body></html>"""


def generar_informe_html(params, cabida, financ, legal, zona, financ_inputs, fecha):
    """Genera informe HTML descargable con estilo Osterling Advisory."""
    r   = financ["resumen"] if financ else {}
    fi  = financ_inputs or {}
    p   = params or {}
    c   = cabida or {}
    leg = legal  or {}

    # ── Flujo de caja ────────────────────────────────
    tir_real = mes_be = max_exp = None
    if cabida and financ:
        m_data = MERCADO.get(zona, {})
        fin_fl = {
            "costo_terreno":      fi.get("costo_terreno", 0),
            "costo_construccion": fi.get("costo_construccion", m_data.get("costo_construccion", 0)),
            "costo_sotano_m2":    fi.get("costo_sotano_m2", 450),
            "fee_constructora":   fi.get("fee_constructora", 10.0),
            "tasa_ir":            fi.get("tasa_ir", 29.5),
            "include_alcabala":   fi.get("include_alcabala", True),
            "include_dd":         fi.get("include_dd", True),
            "precio_venta_m2":    fi.get("precio_venta_m2", m_data.get("precio_2br", 0)),
            "precio_estac":       m_data.get("precio_estac", 0),
            "precio_deposito":    m_data.get("precio_deposito", 0),
            "tasa_financ":        fi.get("tasa_financ", 7.0),
        }
        result_fl = calcular_financiero(cabida, fin_fl, zona)
        try:
            _, _, tir_real, mes_be, max_exp, _ = generar_flujo(cabida, result_fl, fin_fl, zona)
        except Exception:
            pass

    pts, score_10, etiqueta, _, _, recomendacion, score_items = score_viabilidad(r) if r else (0, 0, "—", "", "", "—", [])

    NAV  = "#1E2D3D"
    GOLD = "#B8904A"
    ALT  = "#EEF1F6"
    BORD = "#C5D3E0"

    # ── Helpers ──────────────────────────────────────
    def th(txt):
        return '<th style="background:' + NAV + ';color:#fff;padding:7px 10px;text-align:left;font-size:11px;">' + txt + '</th>'

    def section(title):
        return (
            '<p style="margin:28px 0 4px 0;font-size:13px;font-weight:bold;color:' + NAV + ';">' + title + '</p>'
            '<div style="border-top:1.5px solid ' + GOLD + ';margin-bottom:14px;"></div>'
        )

    def kv_table(rows):
        out = '<table style="width:100%;border-collapse:collapse;margin-bottom:16px;">'
        for i, (k, v) in enumerate(rows):
            bg = ALT if i % 2 == 0 else "#fff"
            out += ('<tr>'
                    '<td style="background:' + bg + ';padding:5px 10px;font-size:11px;font-weight:bold;color:' + NAV + ';width:45%;border-bottom:1px solid ' + BORD + ';">' + str(k) + '</td>'
                    '<td style="background:' + bg + ';padding:5px 10px;font-size:11px;border-bottom:1px solid ' + BORD + ';">' + str(v) + '</td>'
                    '</tr>')
        return out + "</table>"

    def td_row(i, *cells):
        bg = ALT if i % 2 == 0 else "#fff"
        s = '<td style="background:' + bg + ';padding:6px 10px;font-size:11px;border-bottom:1px solid ' + BORD + ';">'
        return '<tr>' + ''.join(s + str(cell) + '</td>' for cell in cells) + '</tr>'

    # ── Pre-compute fragments (no backslash in f-expr) ─
    ubicacion   = p.get("ubicacion", "—")
    zonificacion = p.get("zonificacion", "—")
    area_t      = str(p.get("area_terreno_m2", "—")) + " m²"
    frente      = str(p.get("frente_ml", "—")) + " ml"
    fondo       = str(p.get("fondo_ml", "—")) + " ml"
    pisos_max   = str(p.get("pisos_max", "—")) + " pisos"
    area_libre  = str(p.get("area_libre_min_pct", "—")) + "%"
    retiro      = str(p.get("retiro_frontal_ml", "—")) + " ml"
    caduca      = p.get("fecha_caducidad", "—")

    at_total = c.get("area_techada_total_m2", 0)
    av_total = c.get("area_vendible_m2", 0)
    efic     = (str(round(av_total / at_total * 100, 1)) + "%" if at_total else "—")
    area_techada_str = f"{at_total:,.0f} m²"
    area_vend_str    = f"{av_total:,.0f} m²"

    beneficios = p.get("beneficios_normativos", [])
    benef_html = ""
    for b in beneficios:
        desc = b.get("descripcion", "")
        imp  = b.get("impacto_estimado", "")
        benef_html += '<p style="font-size:10px;color:' + GOLD + ';margin:2px 0;">&#9878; <strong>' + desc + '</strong> — ' + imp + '</p>'

    semaforo_color = {"verde": "#1A7A4A", "amarillo": "#B8862E", "rojo": "#8B1A1A"}.get(leg.get("semaforo", ""), NAV)
    semaforo_label = {"verde": "SIN ALERTAS", "amarillo": "ALERTAS MENORES", "rojo": "ALERTAS CRÍTICAS"}.get(leg.get("semaforo", ""), "—")

    alertas_html = ""
    for a in leg.get("alertas", []):
        alertas_html += '<p style="font-size:10px;color:#8B1A1A;margin:3px 0;">&#9888; ' + str(a) + '</p>'

    score_rows_html = ""
    for i, it in enumerate(score_items):
        score_rows_html += td_row(i, it[0], it[1], str(it[2]) + "/" + str(it[3]))

    tir_str = (str(tir_real) + "%") if tir_real is not None else "—"
    exp_str = fmt_usd(abs(max_exp)) if max_exp is not None else "—"
    be_str  = ("Mes " + str(mes_be)) if mes_be else "— (fuera del horizonte)"

    costo_total_financ = fmt_usd(r.get("costo_total_sin_financ", 0) + r.get("costo_financiero", 0))

    def _leg_list(val, empty_label="Ninguna registrada"):
        if not val or val == [] or val == "[]":
            return empty_label
        if isinstance(val, list):
            items = [str(v.get("descripcion", v) if isinstance(v, dict) else v) for v in val if v]
            return "; ".join(items) if items else empty_label
        return str(val) if val and val != "—" else empty_label

    def _leg_names(partida_list, puhr_list):
        parts = []
        if partida_list:
            parts.append("Partida: " + ", ".join(str(x) for x in partida_list if x))
        if puhr_list:
            parts.append("PU/HR: " + ", ".join(str(x) for x in puhr_list if x))
        return " | ".join(parts) if parts else "—"

    def _leg_addr(partida_val, puhr_val):
        parts = []
        if partida_val and partida_val != "—":
            parts.append("Partida: " + str(partida_val))
        if puhr_val and puhr_val != "—":
            parts.append("PU/HR: " + str(puhr_val))
        return " | ".join(parts) if parts else "—"

    def _leg_area(reg, muni):
        parts = []
        if reg:  parts.append(f"Partida: {reg:,.2f} m²")
        if muni: parts.append(f"PU/HR: {muni:,.2f} m²")
        return " | ".join(parts) if parts else "—"

    legal_table = kv_table([
        ("Propietario(s)",       _leg_names(leg.get("propietarios_partida"), leg.get("propietarios_puhr"))),
        ("Dirección",            _leg_addr(leg.get("direccion_partida"), leg.get("direccion_puhr"))),
        ("Área del inmueble",    _leg_area(leg.get("area_registral_m2"), leg.get("area_puhr_m2"))),
        ("Cargas vigentes",      _leg_list(leg.get("cargas_vigentes"))),
        ("Hipotecas vigentes",   _leg_list(leg.get("hipotecas_vigentes"))),
        ("Medidas cautelares",   _leg_list(leg.get("medidas_cautelares"))),
    ]) if leg else kv_table([("Estado", "Análisis legal no ejecutado")])

    resumen_legal = leg.get("resumen_legal", "")

    # ── HTML ─────────────────────────────────────────
    html = (
        '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">'
        '<title>FACTIS — Informe — ' + ubicacion + '</title>'
        '<style>'
        '* { box-sizing: border-box; margin: 0; padding: 0; }'
        'body { font-family: Arial, sans-serif; color: #2C2C2C; font-size: 11px; line-height: 1.6;'
        '       max-width: 800px; margin: 0 auto; padding: 40px 48px; background: #fff; }'
        '@media print {'
        '  body { padding: 0; }'
        '  @page { margin: 20mm 22mm; size: A4; }'
        '}'
        'table { border-collapse: collapse; width: 100%; }'
        '</style></head><body>'

        # Header
        '<table style="width:100%;margin-bottom:8px;"><tr>'
        '<td style="vertical-align:middle;">'
        '<span style="font-size:20px;font-weight:800;color:' + NAV + ';letter-spacing:-1px;">FACTIS</span>'
        '<span style="font-size:9px;color:' + GOLD + ';letter-spacing:3px;text-transform:uppercase;margin-left:10px;font-weight:600;">Herramienta Analítica Inmobiliaria</span>'
        '</td>'
        '<td style="text-align:right;vertical-align:middle;">'
        '<span style="font-size:9px;color:#555;font-weight:bold;">Osterling Advisory — Inmobiliaria Corporativa</span><br>'
        '<span style="font-size:9px;color:#555;">eosterling@grupoosterling.com | Lima, Perú | ' + fecha + '</span>'
        '</td></tr></table>'
        '<div style="border-top:1.5px solid ' + GOLD + ';margin-bottom:20px;"></div>'

        # Title
        '<p style="font-size:16px;font-weight:bold;color:' + NAV + ';text-align:center;margin-bottom:4px;letter-spacing:0.5px;">INFORME DE ANÁLISIS DE CABIDA E INVERSIÓN</p>'
        '<p style="font-size:12px;color:#555;text-align:center;margin-bottom:20px;">' + ubicacion + ' &nbsp;|&nbsp; Zona: ' + zona + ' &nbsp;|&nbsp; ' + fecha + '</p>'

        # I. Datos del Inmueble
        + section("I. Datos del Inmueble")
        + kv_table([
            ("Ubicación",          ubicacion),
            ("Zonificación",       zonificacion),
            ("Área del terreno",   area_t),
            ("Frente",             frente),
            ("Fondo",              fondo),
            ("Altura máxima",      pisos_max),
            ("Área libre mínima",  area_libre),
            ("Retiro frontal",     retiro),
            ("Certificado caduca", caduca),
        ])

        # II. Programa Arquitectónico
        + section("II. Programa Arquitectónico (Cabida)")
        + kv_table([
            ("Pisos sobre terreno",    str(c.get("num_pisos", "—"))),
            ("Sótanos",                str(c.get("num_sotanos", 0))),
            ("Área techada total",     area_techada_str),
            ("Área vendible",          area_vend_str),
            ("Eficiencia vendible",    efic),
            ("Total departamentos",    str(c.get("total_unidades", "—"))),
        ] + [
            (f"Dpto {u.get('tipo','—')}",
             f"{u.get('cantidad',0)} und · {u.get('area_m2',0):.0f} m²/und")
            for u in (c.get("unidades") or [])
        ] + [
            ("Estacionamientos",       str(c.get("estac_total", "—"))),
            ("Depósitos",              str(c.get("depositos_total", 0))),
        ])
        + benef_html

        # III. Análisis Financiero
        + section("III. Análisis Financiero")
        + '<table style="width:100%;border-collapse:collapse;margin-bottom:16px;"><tr>'
        + th("Indicador") + th("Sin financiamiento") + th("Con financiamiento")
        + '</tr>'
        + td_row(0, "Ingresos brutos",          fmt_usd(r.get("ingresos_brutos", 0)),           fmt_usd(r.get("ingresos_brutos", 0)))
        + td_row(1, "Costo total",               fmt_usd(r.get("costo_total_sin_financ", 0)),    costo_total_financ)
        + td_row(0, "Utilidad neta",             fmt_usd(r.get("utilidad_neta", 0)),             fmt_usd(r.get("utilidad_con_financ", 0)))
        + td_row(1, "Margen neto",               str(r.get("margen_pct", "—")) + "%",            str(r.get("margen_con_financ_pct", "—")) + "%")
        + td_row(0, "ROI / TIR estimada",        str(r.get("roi_pct", "—")) + "% / " + str(r.get("tir_anual_pct", "—")) + "%", "—")
        + td_row(1, "Duración proyecto",         str(r.get("meses_proyecto", "—")) + " meses",  "—")
        + td_row(0, "Precio máx. terreno (20%)", fmt_usd(r.get("max_terreno_20pct", 0)),         "—")
        + '</table>'

        # IV. Flujo de Caja
        + section("IV. Flujo de Caja")
        + kv_table([
            ("TIR anual real (bisección numérica)", tir_str),
            ("Exposición máxima de capital",        exp_str),
            ("Mes de breakeven",                    be_str),
        ])

        # V. Due Diligence Legal
        + section("V. Due Diligence Legal")
        + '<p style="font-size:12px;font-weight:bold;color:' + semaforo_color + ';margin-bottom:8px;">Estado: ' + semaforo_label + '</p>'
        + legal_table
        + alertas_html
        + '<p style="font-size:10px;color:#555;margin-top:8px;font-style:italic;">' + resumen_legal + '</p>'

        # VI. Viabilidad
        + section("VI. Evaluación de Viabilidad")
        + '<table style="width:100%;border-collapse:collapse;margin-bottom:16px;"><tr>'
        + th("Factor") + th("Valor") + th("Puntos")
        + '</tr>' + score_rows_html + '</table>'
        + '<p style="font-size:14px;font-weight:bold;color:' + NAV + ';margin-bottom:4px;">Score: ' + str(score_10) + '/10 — ' + etiqueta + '</p>'
        + '<p style="font-size:11px;color:#444;line-height:1.65;">' + recomendacion + '</p>'

        # Firma
        + '<div style="margin-top:48px;border-top:1px solid ' + BORD + ';padding-top:20px;">'
        + '<p style="font-size:11px;font-weight:bold;color:' + NAV + ';">Enrique Osterling</p>'
        + '<p style="font-size:10px;color:#555;">Gerente General</p>'
        + '<p style="font-size:10px;color:#555;">Osterling Advisory — Inmobiliaria Corporativa</p>'
        + '<p style="font-size:10px;color:#555;">+51 950 891 995 | eosterling@grupoosterling.com | Lima, Perú</p>'
        + '<p style="font-size:9px;color:#AAA;margin-top:16px;">'
        + 'Los resultados tienen carácter referencial y se basan en los parámetros ingresados. '
        + 'Se recomienda validar con asesores legales, financieros y técnicos antes de tomar decisiones de inversión. '
        + 'Generado con FACTIS — Osterling Advisory &copy; 2026.'
        + '</p></div>'
        + '</body></html>'
    )
    return html


# ═══════════════════════════════════════════════════════
# APP PRINCIPAL
# ═══════════════════════════════════════════════════════

_module_subtitles = {
    "Proyecto Inmobiliario":          "Herramienta Analítica Inmobiliaria",
    "Proyecto Logístico / Industrial": "Análisis de Activos Logísticos e Industriales",
    "Inmueble Residencial":            "Evaluación de Inmuebles Residenciales",
}
_active_module = st.session_state.get("tipo_operacion", "Proyecto Inmobiliario")
_subtitle = _module_subtitles.get(_active_module, "Herramienta Analítica Inmobiliaria")
_module_tags = {
    "Proyecto Inmobiliario":          "Cabida · Financiero · Legal · IA",
    "Proyecto Logístico / Industrial": "Costo · Yield · DSCR · Comparativa",
    "Inmueble Residencial":            "Crédito · Inversión · Amortización",
}
_tag = _module_tags.get(_active_module, "")

st.markdown(
    '<div class="main-header">'
    '<div style="display:flex;align-items:center;justify-content:space-between;">'
    '<div>'
    '<div style="font-size:9px;color:#B8904A;letter-spacing:4px;text-transform:uppercase;font-weight:600;margin-bottom:10px;">Osterling Advisory</div>'
    '<div style="display:flex;align-items:center;gap:18px;">'
    '<span style="font-size:22px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;">FACTIS</span>'
    '<span style="width:1px;height:18px;background:#B8904A;opacity:0.4;display:inline-block;flex-shrink:0;"></span>'
    f'<span style="font-size:10px;color:#8AA8C0;letter-spacing:2.5px;text-transform:uppercase;font-weight:500;">{_subtitle}</span>'
    '</div>'
    f'<div style="margin-top:10px;font-size:9px;color:#B8904A;letter-spacing:1.5px;opacity:0.8;">{_tag}</div>'
    '</div>'
    '<div style="text-align:right;">'
    '<div style="font-size:8px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;font-weight:600;opacity:0.7;">Lima, Perú</div>'
    f'<div style="font-size:9px;color:rgba(184,144,74,0.5);margin-top:6px;letter-spacing:1px;">{_active_module}</div>'
    '</div>'
    '</div></div>',
    unsafe_allow_html=True
)

# ── SIDEBAR ──────────────────────────────────────────

run = False
run_industrial = False
run_residencial = False
run_ind_docs = False
run_res_docs = False

with st.sidebar:
    # ── Sidebar brand header ──────────────────────────
    _user_display = st.session_state.get("_user_name", "")
    _user_role    = st.session_state.get("_user_role", "advisor")
    if _LOGO_B64:
        st.markdown(f"""
        <div style="padding:16px 16px 10px;text-align:center;
                    border-bottom:1px solid rgba(255,255,255,0.09);margin-bottom:6px;">
            <div style="background:#FFFFFF;border-radius:8px;padding:10px 16px;
                        display:inline-block;max-width:90%;">
                <img src="data:image/png;base64,{_LOGO_B64}"
                     style="height:36px;max-width:100%;object-fit:contain;display:block;">
            </div>
            <div style="font-size:7px;color:rgba(184,144,74,0.75);letter-spacing:3px;
                        text-transform:uppercase;font-weight:600;margin-top:9px;">
                Plataforma Analítica Inmobiliaria
            </div>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown("""
        <div style="padding:24px 20px 14px;border-bottom:1px solid rgba(255,255,255,0.09);
                    margin-bottom:6px;text-align:center;">
            <div style="font-size:22px;font-weight:800;color:#FFFFFF;letter-spacing:-0.5px;">
                FACTIS
            </div>
            <div style="font-size:7px;color:rgba(184,144,74,0.80);letter-spacing:4px;
                        text-transform:uppercase;font-weight:600;margin-top:6px;">
                Osterling Advisory
            </div>
        </div>""", unsafe_allow_html=True)

    # ── Usuario activo + logout ───────────────────────
    _role_label = "Admin" if _user_role == "admin" else "Asesor"
    st.markdown(
        f'<div style="display:flex;align-items:center;justify-content:space-between;'
        f'padding:8px 2px 4px;">'
        f'<div>'
        f'<div style="font-size:11px;font-weight:600;color:#C8D8E8;">{_user_display}</div>'
        f'<div style="font-size:9px;color:rgba(184,144,74,0.75);letter-spacing:1px;'
        f'text-transform:uppercase;font-weight:600;">{_role_label}</div>'
        f'</div></div>',
        unsafe_allow_html=True)
    if st.button("Cerrar sesión", key="_logout_btn", use_container_width=True):
        for k in ["_authenticated","_user_name","_user_role","_username"]:
            st.session_state.pop(k, None)
        st.rerun()

    st.markdown("### MÓDULO DE ANÁLISIS")
    tipo_op = st.radio(
        "tipo_op_radio",
        ["Proyecto Inmobiliario", "Proyecto Logístico / Industrial", "Inmueble Residencial", "Calculadora Inversa"],
        key="tipo_operacion",
        label_visibility="collapsed",
    )

    # ── Descripción contextual del módulo seleccionado ───
    _mod_ctx = {
        "Proyecto Inmobiliario": (
            "🏗",
            "Desarrollo residencial multifamiliar",
            "Cabida normativa · Financiero · RIN · PDF",
            "Úsalo cuando tienes un terreno y quieres proyectar pisos, unidades, costos y rentabilidad de un edificio de departamentos.",
        ),
        "Proyecto Logístico / Industrial": (
            "🏭",
            "Nave logística · Almacén · Industria",
            "Costo · Yield · DSCR · Comparativa",
            "Úsalo para evaluar la construcción o adquisición de una nave industrial, almacén logístico o planta de manufactura.",
        ),
        "Inmueble Residencial": (
            "🏠",
            "Valuación de inmueble existente",
            "Precio · Renta · Yield · Comparables",
            "Úsalo cuando tienes un departamento, casa o unidad residencial ya construida y quieres analizar su valor o rentabilidad.",
        ),
        "Calculadora Inversa": (
            "🎯",
            "Precio máximo de terreno",
            "Margen objetivo → Terreno máx.",
            "Ingresa el margen que necesitas y la app calcula el precio máximo que puedes pagar por el terreno. Ideal para negociaciones rápidas con propietarios.",
        ),
    }
    _mico, _mtit, _mtag, _mdesc = _mod_ctx[tipo_op]
    st.markdown(
        f'<div style="background:rgba(255,255,255,0.04);border-radius:9px;padding:11px 13px;'
        f'border:1px solid rgba(255,255,255,0.08);margin:6px 0 4px;">'
        f'<div style="font-size:12px;font-weight:700;color:#C8D8E8;margin-bottom:2px;">'
        f'{_mico} {_mtit}</div>'
        f'<div style="font-size:9px;color:rgba(184,144,74,0.80);letter-spacing:1px;'
        f'text-transform:uppercase;font-weight:600;margin-bottom:6px;">{_mtag}</div>'
        f'<div style="font-size:11px;color:rgba(184,200,216,0.70);line-height:1.5;">{_mdesc}</div>'
        f'</div>',
        unsafe_allow_html=True)
    st.markdown("---")

    # ── Helper compartido: render de paso de progreso ────
    def _sp(idx, lbl, sub, done, is_cur, is_last):
        if done:
            cbg, cco, ctxt, lco, sco, lnc = "#6BCEA0","#0A1628","✓","#6BCEA0","rgba(107,206,160,0.6)","rgba(107,206,160,0.35)"
        elif is_cur:
            cbg, cco, ctxt, lco, sco, lnc = "#B8904A","#FFF",str(idx+1),"#D4A853","rgba(184,200,216,0.75)","rgba(255,255,255,0.10)"
        else:
            cbg, cco, ctxt, lco, sco, lnc = "rgba(255,255,255,0.08)","rgba(184,200,216,0.35)",str(idx+1),"rgba(184,200,216,0.40)","rgba(184,200,216,0.28)","rgba(255,255,255,0.06)"
        ln = "" if is_last else f'<div style="width:1px;height:13px;background:{lnc};margin:2px auto;"></div>'
        return (f'<div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:2px;">'
                f'<div style="display:flex;flex-direction:column;align-items:center;flex-shrink:0;">'
                f'<div style="width:22px;height:22px;border-radius:50%;background:{cbg};'
                f'display:flex;align-items:center;justify-content:center;'
                f'font-size:10px;font-weight:700;color:{cco};">{ctxt}</div>{ln}</div>'
                f'<div style="padding-top:3px;">'
                f'<div style="font-size:11px;font-weight:600;color:{lco};line-height:1.2;">{lbl}</div>'
                f'<div style="font-size:10px;color:{sco};line-height:1.3;">{sub}</div>'
                f'</div></div>')

    # ── Indicador fuente de precios (solo admin, discreto) ───────────
    if _user_role == "admin":
        _sheet_live = bool((st.secrets.get("mercado", {}) or {}).get("sheet_url", ""))
        _live_data  = bool(_cargar_mercado_sheet()) if _sheet_live else False
        _src_txt = "● Precios vía Google Sheet" if _live_data else "● Precios locales Nov-2025"
        _src_col = "rgba(107,206,160,0.60)" if _live_data else "rgba(255,255,255,0.25)"
        st.markdown(
            f'<div style="font-size:9px;color:{_src_col};text-align:right;'
            f'margin-top:-4px;margin-bottom:8px;letter-spacing:0.5px;">{_src_txt}</div>',
            unsafe_allow_html=True)

    # ── MÓDULO 1: PROYECTO INMOBILIARIO ──────────────────
    if tipo_op == "Proyecto Inmobiliario":
        # ── Indicador de progreso guiado ─────────────────
        _step1_done = bool(st.session_state.get("nombre_proyecto", "").strip())
        _step2_done = int(st.session_state.get("cab_precio_compra", 0) or 0) > 0
        _step3_done = st.session_state.get("cabida") is not None
        _step4_done = _step3_done
        _steps_prog = [
            ("Terreno & Proyecto", "Nombre, ubicación, área", _step1_done),
            ("Datos Financieros",  "Precio compra y venta/m²", _step2_done),
            ("Análisis IA",        "Cabida, RIN, Factibilidad", _step3_done),
            ("Reporte PDF",        "Descarga informe ejecutivo", _step4_done),
        ]
        _current_step = next((i for i, (_, _, d) in enumerate(_steps_prog) if not d), 4)
        _prog_html = "".join([_sp(i,l,s,d,i==_current_step,i==3) for i,(l,s,d) in enumerate(_steps_prog)])
        st.markdown(
            f'<div style="background:rgba(255,255,255,0.04);border-radius:10px;padding:12px 14px 10px;'
            f'border:1px solid rgba(255,255,255,0.08);margin-bottom:10px;">'
            f'<div style="font-size:9px;font-weight:700;color:rgba(184,200,216,0.45);'
            f'letter-spacing:2px;text-transform:uppercase;margin-bottom:10px;">FLUJO DE TRABAJO</div>'
            f'{_prog_html}</div>',
            unsafe_allow_html=True)
        st.markdown("### DOCUMENTOS")
        pdf_cert    = st.file_uploader("Certificado de Parámetros ✱",       type=["pdf"], key="cert")
        pdf_plano   = st.file_uploader("Planos (perimetral / topográfico)",  type=["pdf"], key="plano",
                                       accept_multiple_files=True)
        pdf_partida = st.file_uploader("Partida Registral",                  type=["pdf"], key="partida")
        pdf_puhr    = st.file_uploader("PU / HR",                            type=["pdf"], key="puhr")
        pdf_norms   = st.file_uploader("Ordenanzas y normativa",             type=["pdf"], key="norms",
                                       accept_multiple_files=True)

        st.markdown("---")
        st.markdown("### PROYECTO")
        # ── Estado vacío guiado ────────────────────────────
        _no_nombre = not bool(st.session_state.get("nombre_proyecto", "").strip())
        _no_area   = float(st.session_state.get("cab_override_area", 0) or 0) == 0
        _no_precio = int(st.session_state.get("cab_precio_compra", 0) or 0) == 0
        if _no_nombre and _no_area and _no_precio:
            st.markdown(
                '<div style="background:rgba(184,144,74,0.08);border-radius:8px;padding:11px 13px;'
                'border:1px solid rgba(184,144,74,0.22);margin-bottom:10px;">'
                '<div style="font-size:10px;font-weight:700;color:#D4A853;letter-spacing:0.5px;margin-bottom:7px;">¿POR DÓNDE EMPEZAR?</div>'
                '<div style="font-size:11px;color:rgba(184,200,216,0.82);line-height:1.75;">'
                '① Ingresa el <b style="color:#C8D8E8;">nombre</b> del proyecto<br>'
                '② Selecciona el <b style="color:#C8D8E8;">distrito</b><br>'
                '③ Sube el <b style="color:#C8D8E8;">certificado de parámetros</b><br>'
                '④ Completa el <b style="color:#C8D8E8;">precio de compra</b><br>'
                '⑤ Presiona <b style="color:#D4A853;">Analizar →</b>'
                '</div></div>',
                unsafe_allow_html=True)
        nombre_proyecto = st.text_input(
            "Nombre del proyecto",
            placeholder="Ej: Torres Las Camelias — Miraflores",
            key="nombre_proyecto",
            help="Aparece en la portada del reporte PDF")
        _cab_zona_default = list(MERCADO.keys()).index(st.session_state.get("cab_zona_sel", "Miraflores")) if st.session_state.get("cab_zona_sel") in MERCADO else 20
        zona = st.selectbox("Ubicación", list(MERCADO.keys()), index=_cab_zona_default, key="cab_zona_sel_widget")

        st.markdown("---")
        st.markdown("### INFORMACIÓN DEL TERRENO")
        with st.expander("📄 Completar desde documento"):
            st.caption("Sube el certificado de parámetros, plano o cualquier documento del predio. La IA extrae automáticamente el área, frente, fondo, distrito y precios.")
            _cab_doc_up = st.file_uploader(
                "PDF, PPTX o DOCX",
                type=["pdf", "pptx", "ppt", "docx"],
                key="cab_import_doc",
            )
            if _cab_doc_up and st.button("EXTRAER DATOS", key="btn_cab_extract", use_container_width=True):
                _cab_bytes = _cab_doc_up.read()
                _cab_ext = _run_with_retry(
                    lambda _b=_cab_bytes, _n=_cab_doc_up.name: extraer_datos_desde_doc(_b, _n, "cabida"),
                    "Analizando documento…"
                )
                if _cab_ext.get("_error"):
                    st.error(_cab_ext["_error"])
                else:
                    if _cab_ext.get("nombre_proyecto"):
                        st.session_state["nombre_proyecto"] = _cab_ext["nombre_proyecto"]
                    if _cab_ext.get("area_terreno_m2"):
                        st.session_state["cab_override_area"] = float(_cab_ext["area_terreno_m2"])
                    if _cab_ext.get("frente_ml"):
                        st.session_state["cab_override_frente"] = float(_cab_ext["frente_ml"])
                    if _cab_ext.get("fondo_ml"):
                        st.session_state["cab_override_fondo"] = float(_cab_ext["fondo_ml"])
                    if _cab_ext.get("costo_terreno_usd"):
                        st.session_state["cab_precio_compra"] = int(_cab_ext["costo_terreno_usd"])
                    if _cab_ext.get("precio_venta_m2_usd"):
                        st.session_state["cab_precio_venta_m2"] = int(_cab_ext["precio_venta_m2_usd"])
                    if _cab_ext.get("costo_construccion_m2_usd"):
                        st.session_state["cab_costo_const_m2"] = int(_cab_ext["costo_construccion_m2_usd"])
                    _ext_dist = _cab_ext.get("distrito") or ""
                    for _k in MERCADO.keys():
                        if _ext_dist.lower() in _k.lower() or _k.lower() in _ext_dist.lower():
                            st.session_state["cab_zona_sel"] = _k
                            break
                    st.success("Datos extraídos. Revisa y ajusta antes de ejecutar.")
                    st.rerun()
        st.caption("Completa o corrige los datos del predio a analizar.")

        col_fr, col_fo = st.columns(2)
        override_frente = col_fr.number_input("Frente (ml)", min_value=0.0, max_value=500.0,
                                              value=float(st.session_state.get("cab_override_frente", 0.0)), step=0.5,
                                              help="Frente del lote en metros lineales", key="cab_frente_inp")
        override_fondo  = col_fo.number_input("Fondo (ml)",  min_value=0.0, max_value=500.0,
                                              value=float(st.session_state.get("cab_override_fondo", 0.0)), step=0.5,
                                              help="Fondo del lote en metros lineales", key="cab_fondo_inp")

        _area_calc = round(override_frente * override_fondo, 1) if override_frente > 0 and override_fondo > 0 else 0.0
        if _area_calc > 0:
            st.caption(f"Área calculada: **{_area_calc:,.1f} m²** (frente × fondo)")

        override_area = st.number_input("Área del terreno (m²)", min_value=0.0, max_value=50000.0,
                                        value=float(st.session_state.get("cab_override_area", _area_calc)), step=10.0,
                                        help="0 = usar el valor extraído del certificado. Se completa automáticamente si ingresas frente y fondo.", key="cab_area_inp")
        override_al   = st.number_input("Área libre mínima (%)", min_value=0.0, max_value=80.0,
                                        value=0.0, step=5.0,
                                        help="0 = usar el valor extraído del certificado")

        st.markdown("---")
        st.markdown("### COLINDANTES")
        st.caption("Alturas de edificaciones colindantes (verificar en campo). Activa la regla de colindancia del RIN para mayor altura.")
        _col_izq, _col_der = st.columns(2)
        colind_izq = _col_izq.number_input("Colindante izq. (pisos)", min_value=0, max_value=40,
                                            value=0, step=1,
                                            help="0 = sin edificación colindante izquierda")
        colind_der = _col_der.number_input("Colindante der. (pisos)", min_value=0, max_value=40,
                                            value=0, step=1,
                                            help="0 = sin edificación colindante derecha")
        if colind_izq > 0 or colind_der > 0:
            _col_max = max(colind_izq, colind_der)
            st.caption(f"Regla colindancia: edificio a analizar podrá alcanzar hasta el promedio "
                       f"con el colindante más alto ({_col_max} pisos). Claude calculará la altura permitida.")

        st.markdown("---")
        st.markdown("### DATOS FINANCIEROS")
        precio_compra   = st.number_input("Precio de compra del inmueble (USD)",
                                          min_value=0, max_value=50_000_000,
                                          value=int(st.session_state.get("cab_precio_compra", (st.session_state.get("financ_inputs") or {}).get("costo_terreno", 0) or 0)),
                                          step=10_000, format="%d", key="cab_precio_compra_inp")
        if st.session_state.get("financ_inputs") is not None:
            st.session_state.financ_inputs["costo_terreno"] = precio_compra
        precio_venta_m2 = st.number_input("Precio de venta / m² (USD)",
                                          min_value=0, max_value=15_000,
                                          value=int(st.session_state.get("cab_precio_venta_m2", MERCADO[zona]["precio_2br"])), step=100, key="cab_pventa_inp")
        costo_const_m2  = st.number_input("Costo construcción dptos / m² (USD)",
                                          min_value=300, max_value=2_000,
                                          value=int(st.session_state.get("cab_costo_const_m2", MERCADO[zona]["costo_construccion"])), step=25, key="cab_cconst_inp")
        with st.expander("Parámetros avanzados"):
            costo_sotano_m2  = st.number_input("Costo sótano / m² (USD)", 200, 1000, 450, 25,
                                                help="Costo por m² de sótano (excavación + estructura)")
            fee_constructora = st.number_input("Fee constructora (%)", 0.0, 20.0, 10.0, 0.5,
                                                help="Honorarios sobre costo directo de obra")
            tasa_ir          = st.number_input("Impuesto a la Renta (%)", 0.0, 40.0, 29.5, 0.5,
                                                help="IR corporativo Perú: 29.5%")
            include_alcabala = st.checkbox("Incluir Alcabala (3%)", value=True,
                                            help="Impuesto de alcabala sobre precio del terreno")
            include_dd       = st.checkbox("Incluir Due Diligence (~$11,500)", value=True,
                                            help="Suelo, topografía, títulos, notariales, registrales")

        st.markdown("---")
        st.markdown("### COMPETENCIA / PRECIOS")
        st.caption("Pega texto o sube capturas de portales (Urbania, Nexo, A Donde Vivir)")

        if "competencia" not in st.session_state:
            st.session_state.competencia = []

        # ── Extracción automática desde portal ──────────
        _comp_imgs = st.file_uploader(
            "Capturas del portal (PNG/JPG)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            key="comp_portal_imgs",
        )
        _comp_texto = st.text_area(
            "O pega el texto del portal",
            placeholder="Copia y pega el contenido de la página de Urbania, Nexo, etc.",
            height=100,
            key="comp_portal_texto",
        )
        if st.button("EXTRAER COMPARABLES", use_container_width=True, key="btn_extraer_comp",
                     type="primary", disabled=not ((_comp_imgs or _comp_texto.strip()) and
                                                    st.session_state.get("api_key_input"))):
            _api = st.session_state.get("api_key_input", "")
            _imagenes = []
            for _img_file in (_comp_imgs or []):
                _ext = _img_file.name.rsplit(".", 1)[-1].lower()
                _mt  = "image/png" if _ext == "png" else "image/jpeg"
                _imagenes.append((_img_file.read(), _mt))
            with st.spinner("Analizando portal..."):
                _extraidos = extraer_comparables_portal(_api, _comp_texto, _imagenes)
            if _extraidos:
                for _e in _extraidos:
                    st.session_state.competencia.append({
                        "proyecto":  str(_e.get("proyecto", "Sin nombre")),
                        "precio_m2": int(_e.get("precio_m2", 0)),
                        "pisos":     int(_e.get("pisos", 0)),
                        "tipologia": str(_e.get("tipologia", "—")),
                        "estado":    str(_e.get("estado", "En venta")),
                    })
                st.success(f"{len(_extraidos)} proyecto(s) extraído(s)")
                st.rerun()
            else:
                st.warning("No se detectaron proyectos. Intenta con más capturas o más texto.")

        # ── Ingreso manual (fallback) ────────────────────
        with st.expander("Agregar manualmente"):
            with st.form("form_competidor", clear_on_submit=True):
                nombre_c = st.text_input("Proyecto", placeholder="Ej: Torres Las Camelias 280")
                col_pc, col_fc = st.columns(2)
                precio_c = col_pc.number_input("USD/m²", 500, 15000, 3000, 50)
                pisos_c  = col_fc.number_input("Pisos", 1, 40, 8)
                col_tc, col_ec = st.columns(2)
                tipo_c   = col_tc.selectbox("Tipología", ["2-3 Dorm.", "1-2 Dorm.", "1-3 Dorm.",
                                                            "1 Dorm.", "2 Dorm.", "3 Dorm."])
                estado_c = col_ec.selectbox("Estado", ["Preventa", "En construcción", "En venta"])
                agregar  = st.form_submit_button("AGREGAR", use_container_width=True)
                if agregar and nombre_c.strip():
                    st.session_state.competencia.append({
                        "proyecto":  nombre_c.strip(),
                        "precio_m2": precio_c,
                        "pisos":     pisos_c,
                        "tipologia": tipo_c,
                        "estado":    estado_c,
                    })

        if st.session_state.competencia:
            for i, comp in enumerate(st.session_state.competencia):
                cc1, cc2 = st.columns([5, 1])
                cc1.caption(f"**{comp['proyecto']}** — ${comp['precio_m2']:,}/m²")
                if cc2.button("✕", key=f"del_c_{i}", help="Eliminar"):
                    st.session_state.competencia.pop(i)
                    st.rerun()
            if st.button("Limpiar lista", use_container_width=True):
                st.session_state.competencia = []
                st.rerun()

        st.markdown("---")
        st.markdown("### COMPARABLES SUNARP")
        st.caption("Sube partidas registrales de inmuebles comparables para extraer precios de cierre reales")

        _comp_files = []
        for _ci in range(1, 4):
            _cf = st.file_uploader(f"Partida comparable {_ci}", type="pdf",
                                   key=f"comp_sunarp_{_ci}")
            if _cf:
                _comp_files.append(_cf)

        if _comp_files and st.session_state.get("api_key_input"):
            _btn_comp = st.button("EXTRAER PRECIOS DE CIERRE", use_container_width=True,
                                  key="btn_comp_sunarp", type="secondary")
            if _btn_comp:
                _comp_bytes = [f.read() for f in _comp_files]
                st.session_state.comps_sunarp = _run_with_retry(
                    lambda _cb=list(_comp_bytes): extraer_precios_cierre(_cb),
                    "Leyendo partidas y extrayendo precios…"
                )
        elif _comp_files and not st.session_state.get("api_key_input"):
            st.caption("Ingresa la clave de acceso para analizar comparables.")

        if st.session_state.get("comps_sunarp"):
            st.caption(f"✓ {len(st.session_state.comps_sunarp)} comparable(s) extraídos")
            if st.button("Limpiar comparables", use_container_width=True,
                         key="btn_clear_comps"):
                st.session_state.comps_sunarp = []
                st.rerun()

        st.markdown("---")
        st.markdown("### NOTAS PARA EL ANÁLISIS")
        sugerencias = st.text_area(
            label="notas",
            placeholder="Ej: uso mixto en primer piso, acumulación de lotes, maximizar unidades de 2 dormitorios...",
            height=90,
            label_visibility="collapsed"
        )

        st.markdown("---")
        run = st.button("GENERAR ANÁLISIS", use_container_width=True, type="primary")

        # ── GUARDAR / CARGAR PROYECTO ─────────────────────
        st.markdown("---")
        st.markdown("### PROYECTOS")
        proyectos_saved = listar_proyectos()
        if proyectos_saved:
            nombres_saved = [p.name for p in proyectos_saved]
            sel_proy = st.selectbox("Cargar proyecto guardado", ["— seleccionar —"] + nombres_saved,
                                    label_visibility="collapsed")
            if sel_proy != "— seleccionar —":
                if st.button("CARGAR", use_container_width=True):
                    _pref = next((p for p in proyectos_saved if p.name == sel_proy), None)
                    datos = cargar_proyecto(_pref or sel_proy)
                    st.session_state.params        = datos.get("params") or None
                    st.session_state.cabida        = datos.get("cabida") or None
                    st.session_state.financ_inputs = datos.get("financ_inputs") or {}
                    st.session_state.zona          = datos.get("zona") or None
                    st.rerun()

        nombre_proy = st.text_input("Nombre del proyecto", placeholder="Ej: Torres Las Camelias",
                                    label_visibility="collapsed")
        if st.button("GUARDAR PROYECTO", use_container_width=True):
            if st.session_state.get("params"):
                fp = guardar_proyecto(nombre_proy or "sin_nombre", {
                    "params":        st.session_state.params,
                    "cabida":        st.session_state.cabida,
                    "financ_inputs": st.session_state.financ_inputs,
                    "financ":        st.session_state.financ,
                    "zona":          st.session_state.zona,
                })
                st.session_state["_last_inm_proy"] = fp
                st.session_state.pop("_share_url_inm", None)
                st.markdown('<div style="background:rgba(107,206,160,0.12);border-left:3px solid rgba(107,206,160,0.50);border-radius:6px;padding:8px 12px;color:rgba(107,206,160,0.90);font-size:12px;font-weight:600;margin-top:8px;">✓ ' + f"Guardado: {fp.name}" + '</div>', unsafe_allow_html=True)
            else:
                st.warning("Genera el análisis primero.")
        _lp_inm = st.session_state.get("_last_inm_proy")
        if _lp_inm and _lp_inm._id:
            if st.button("GENERAR LINK DE COMPARTIR", use_container_width=True, key="btn_share_inm"):
                _tok = str(uuid.uuid4())
                _sb2 = _get_supabase()
                if _sb2:
                    _sb2.table("proyectos").update({"share_token": _tok}).eq("id", _lp_inm._id).execute()
                    _base = (st.secrets.get("app", {}) or {}).get("base_url", "http://localhost:8501")
                    st.session_state["_share_url_inm"] = f"{_base}?share={_tok}"
            if st.session_state.get("_share_url_inm"):
                st.code(st.session_state["_share_url_inm"])
                st.caption("Comparte con tu cliente — no requiere contraseña")

        st.markdown("---")
        st.markdown("### FOTOS DEL INMUEBLE")
        st.caption("Las fotos se incluyen en el reporte PDF")
        _cab_fotos = st.file_uploader(
            "Sube fotos del inmueble / terreno",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="cab_fotos_upload",
        )
        if _cab_fotos:
            st.session_state["cab_fotos_bytes"] = [f.read() for f in _cab_fotos]
            st.session_state["cab_fotos_nombres"] = [f.name for f in _cab_fotos]
            cols_f = st.columns(min(len(_cab_fotos), 3))
            for _fi, _fup in enumerate(_cab_fotos[:3]):
                cols_f[_fi].image(_fup, use_container_width=True)

        st.markdown("---")
        st.markdown("### ANÁLISIS LEGAL")
        st.caption("Verifica titularidad, cargas, hipotecas y estado registral")

        _sb_has_partida = pdf_partida is not None
        _sb_has_puhr    = pdf_puhr is not None
        _sb_has_session_p = st.session_state.get("partida_bytes") is not None
        _sb_has_session_u = st.session_state.get("puhr_bytes") is not None
        _sb_can_run = _sb_has_partida or _sb_has_puhr or _sb_has_session_p or _sb_has_session_u

        if not _sb_can_run:
            st.markdown(
                '<div style="font-size:11px;color:rgba(255,255,255,0.45);'
                'background:rgba(255,255,255,0.06);border-radius:6px;'
                'padding:8px 12px;border-left:2px solid rgba(184,144,74,0.40);">Adjunta la '
                '<b style="color:rgba(255,255,255,0.65);">Partida Registral</b> y/o '
                '<b style="color:rgba(255,255,255,0.65);">PU/HR</b> en la sección '
                '<b style="color:rgba(184,144,74,0.80);">DOCUMENTOS</b> para habilitar este análisis.</div>',
                unsafe_allow_html=True)
        else:
            _sb_docs_list = []
            if _sb_has_partida or _sb_has_session_p: _sb_docs_list.append("Partida Registral")
            if _sb_has_puhr    or _sb_has_session_u: _sb_docs_list.append("PU / HR")
            st.markdown(
                f'<div style="font-size:11px;color:#7BCFA0;background:rgba(107,206,160,0.12);border-radius:6px;'
                f'padding:6px 10px;border-left:2px solid rgba(107,206,160,0.50);margin-bottom:6px;">'
                f'● {" · ".join(_sb_docs_list)}</div>',
                unsafe_allow_html=True)

            if st.button("ANALIZAR DOCUMENTOS LEGALES", use_container_width=True,
                         key="btn_legal_sidebar", type="secondary"):
                if pdf_partida is not None:
                    st.session_state.partida_bytes = pdf_partida.read()
                if pdf_puhr is not None:
                    st.session_state.puhr_bytes = pdf_puhr.read()
                _p_bytes = st.session_state.get("partida_bytes")
                _u_bytes = st.session_state.get("puhr_bytes")
                if _p_bytes or _u_bytes:
                    st.session_state.legal = _run_with_retry(
                        lambda _p=_p_bytes, _u=_u_bytes: analizar_legal(_p, _u),
                        "Analizando documentos registrales…",
                    )
                    st.rerun()

        if st.session_state.get("legal"):
            _sb_lg  = st.session_state.legal
            _sb_sem = _sb_lg.get("semaforo", "amarillo").lower()
            _sb_sem_map = {
                "verde":    ("rgba(107,206,160,0.90)", "rgba(107,206,160,0.12)", "rgba(107,206,160,0.40)", "✓ SIN ALERTAS CRÍTICAS"),
                "amarillo": ("rgba(232,200,122,0.90)", "rgba(184,144,74,0.12)",  "rgba(184,144,74,0.40)",  "⚠ OBSERVACIONES MENORES"),
                "rojo":     ("rgba(232,100,100,0.90)", "rgba(200,60,60,0.12)",   "rgba(200,80,80,0.40)",   "✕ ALERTAS CRÍTICAS"),
            }
            _sb_sc, _sb_sbg, _sb_bdr, _sb_sl = _sb_sem_map.get(_sb_sem, ("rgba(200,210,220,0.7)", "rgba(255,255,255,0.06)", "rgba(255,255,255,0.2)", "— INDETERMINADO"))
            st.markdown(
                f'<div style="background:{_sb_sbg};border-left:3px solid {_sb_bdr};border-radius:6px;'
                f'padding:8px 10px;margin-top:4px;font-size:11px;color:{_sb_sc};font-weight:700;">'
                f'{_sb_sl}</div>',
                unsafe_allow_html=True)
            st.caption("Ver detalles completos en la pestaña Legal →")

        st.markdown("---")
        st.markdown("### PROPUESTA")
        st.caption("Genera una propuesta formal de compra o arrendamiento")
        prop_tipo       = st.selectbox("Tipo de propuesta", ["Compra", "Arrendamiento"],
                                       key="prop_tipo")
        prop_propietario = st.text_input("Propietario(s)", placeholder="Nombre del vendedor/arrendador",
                                         key="prop_propietario")
        prop_precio      = st.number_input(
            "Precio ofertado (USD)" if prop_tipo == "Compra" else "Renta mensual ofertada (USD)",
            min_value=0, max_value=50_000_000, value=0, step=5_000, format="%d",
            key="prop_precio"
        )
        _fin_ss = st.session_state.get("financ")
        if _fin_ss:
            _r_ss = _fin_ss.get("resumen", {})
            _v20_ss = _r_ss.get("max_terreno_20pct", 0)
            _v15_ss = _r_ss.get("max_terreno_15pct", 0)
            if _v20_ss > 0:
                _prop_cur = st.session_state.get("prop_precio", 0) or 0
                _hint_color = "#1A4731" if _prop_cur <= _v20_ss else ("#7A5500" if _prop_cur <= _v15_ss else "#7A1A1A")
                _hint_label = "dentro del rango viable (mg ≥ 20%)" if _prop_cur <= _v20_ss else ("mg ≥ 15%" if _prop_cur <= _v15_ss else "supera máx. viable")
                st.caption(f"Máx. viable 20%: **${_v20_ss:,}** · 15%: **${_v15_ss:,}** — precio actual {_hint_label}")
        prop_plazo       = st.number_input("Plazo de respuesta (días)", 1, 90, 10, 1, key="prop_plazo")
        prop_condiciones = st.text_area(
            "Condiciones",
            placeholder="Ej:\nDue diligence de 30 días desde aceptación\nContrato de arras al 10%\nEscritura pública notarial",
            height=100, key="prop_condiciones"
        )


    # ── MÓDULO 2: LOGÍSTICO / INDUSTRIAL ─────────────────
    elif tipo_op == "Proyecto Logístico / Industrial":
        run = False
        run_residencial = False

        # ── Indicador de progreso guiado Industrial ───────
        _ind1_done = int(st.session_state.get("ind_costo_terreno", 0) or 0) > 0
        _ind2_done = float(st.session_state.get("ind_area_nave_m2", 0) or 0) > 0
        _ind3_done = st.session_state.get("ind_analizado") is True
        _ind4_done = _ind3_done
        _steps_ind = [
            ("Terreno & Nave",    "Zona, área, tipo de nave",    _ind1_done),
            ("Costos",            "Construcción, indirectos",     _ind2_done),
            ("Análisis",          "Yield, DSCR, Payback",         _ind3_done),
            ("Reporte",           "Resumen ejecutivo PDF",        _ind4_done),
        ]
        _cur_ind = next((i for i, (_, _, d) in enumerate(_steps_ind) if not d), 4)
        _ind_html = "".join([_sp(i,l,s,d,i==_cur_ind,i==3) for i,(l,s,d) in enumerate(_steps_ind)])
        st.markdown(
            f'<div style="background:rgba(255,255,255,0.04);border-radius:10px;padding:12px 14px 10px;'
            f'border:1px solid rgba(255,255,255,0.08);margin-bottom:10px;">'
            f'<div style="font-size:9px;font-weight:700;color:rgba(184,200,216,0.45);'
            f'letter-spacing:2px;text-transform:uppercase;margin-bottom:10px;">FLUJO DE TRABAJO</div>'
            f'{_ind_html}</div>',
            unsafe_allow_html=True)

        # ── Estado vacío guiado Industrial ────────────────
        _ind_empty = (not _ind1_done and not _ind2_done)
        if _ind_empty:
            st.markdown(
                '<div style="background:rgba(184,144,74,0.08);border-radius:8px;padding:11px 13px;'
                'border:1px solid rgba(184,144,74,0.22);margin-bottom:10px;">'
                '<div style="font-size:10px;font-weight:700;color:#D4A853;letter-spacing:0.5px;margin-bottom:7px;">¿CUÁNDO USAR ESTE MÓDULO?</div>'
                '<div style="font-size:11px;color:rgba(184,200,216,0.82);line-height:1.75;">'
                '✓ <b style="color:#C8D8E8;">Nave logística</b> o almacén a construir<br>'
                '✓ <b style="color:#C8D8E8;">Planta industrial</b> o manufactura<br>'
                '✓ <b style="color:#C8D8E8;">Cross-docking</b> o centro de distribución<br>'
                '✗ No para departamentos — usa <b style="color:#D4A853;">Proyecto Inmobiliario</b>'
                '</div>'
                '<div style="margin-top:9px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.08);'
                'font-size:10px;font-weight:700;color:#D4A853;letter-spacing:0.5px;margin-bottom:5px;">¿POR DÓNDE EMPEZAR?</div>'
                '<div style="font-size:11px;color:rgba(184,200,216,0.82);line-height:1.75;">'
                '① Selecciona la <b style="color:#C8D8E8;">zona industrial</b> de Lima<br>'
                '② Ingresa el <b style="color:#C8D8E8;">área de la nave</b> proyectada<br>'
                '③ Completa el <b style="color:#C8D8E8;">costo del terreno</b><br>'
                '④ Presiona <b style="color:#D4A853;">Ejecutar análisis →</b>'
                '</div></div>',
                unsafe_allow_html=True)

        # ── 1 · UBICACIÓN ──────────────────────────────────
        _step_header("1", "Ubicación")
        with st.expander("📄 Importar datos desde documento"):
            st.caption("Sube una ficha técnica, brochure o plano del terreno — la IA extrae área, ubicación y tipo de nave para pre-llenar los campos automáticamente.")
            _ind_doc_up = st.file_uploader(
                "PDF, PPTX o DOCX",
                type=["pdf", "pptx", "ppt", "docx"],
                key="ind_import_doc",
            )
            if _ind_doc_up and st.button("EXTRAER DATOS", key="btn_ind_extract", use_container_width=True):
                _ind_bytes = _ind_doc_up.read()
                _ind_ext = _run_with_retry(
                    lambda _b=_ind_bytes, _n=_ind_doc_up.name: extraer_datos_desde_doc(_b, _n, "industrial"),
                    "Analizando documento…"
                )
                if _ind_ext.get("_error"):
                    st.error(_ind_ext["_error"])
                else:
                    if _ind_ext.get("area_terreno_m2"):
                        st.session_state["ind_area_val"] = float(_ind_ext["area_terreno_m2"])
                        st.session_state["ind_area"] = float(_ind_ext["area_terreno_m2"])
                        st.session_state["ind_area_auto"] = False
                    if _ind_ext.get("frente_ml"):
                        st.session_state["ind_frente"] = float(_ind_ext["frente_ml"])
                    if _ind_ext.get("fondo_ml"):
                        st.session_state["ind_fondo"] = float(_ind_ext["fondo_ml"])
                    if _ind_ext.get("costo_terreno_usd"):
                        st.session_state["ind_costo_terreno"] = int(_ind_ext["costo_terreno_usd"])
                    if _ind_ext.get("tipo_nave"):
                        _tipo_opts = ["Almacén Logístico", "Nave Industrial", "Cross-docking", "Producción / Manufactura"]
                        _ext_tipo = _ind_ext["tipo_nave"]
                        for _t in _tipo_opts:
                            if any(w in _ext_tipo for w in _t.split()[:2]):
                                st.session_state["ind_tipo"] = _t
                                break
                    if _ind_ext.get("renta_usd_m2_mes"):
                        st.session_state["ind_renta"] = float(_ind_ext["renta_usd_m2_mes"])
                    if _ind_ext.get("zonificacion"):
                        _zon_opts = ["I1", "I2", "I3", "I4", "OU"]
                        if _ind_ext["zonificacion"] in _zon_opts:
                            st.session_state["ind_zona_ind"] = _ind_ext["zonificacion"]
                    st.success("Datos extraídos. Revisa y ajusta antes de ejecutar.")
                    st.rerun()

        ind_ubicacion = st.text_input("Dirección / Zona",
            placeholder="Ej: Av. Las Torres 1240, Lurín",
            key="ind_ubicacion",
            help="Dirección o zona industrial del proyecto")
        ind_zona_lima = st.selectbox("Zona industrial Lima",
            ["Lurín / Pachacámac", "Villa El Salvador", "Callao / Bellavista",
             "Huachipa / Ate", "Lurigancho / Chosica", "Puente Piedra", "Otro"],
            key="ind_zona_lima",
            help="Zona de mercado industrial para benchmarks de renta")

        # ── 2 · TERRENO ─────────────────────────────────────
        _step_header("2", "Terreno")
        ind_col1, ind_col2 = st.columns(2)
        ind_frente = ind_col1.number_input("Frente (ml)", 0.0, 1000.0, 0.0, 0.5, key="ind_frente")
        ind_fondo  = ind_col2.number_input("Fondo (ml)",  0.0, 1000.0, 0.0, 0.5, key="ind_fondo")
        _ind_area_calc = round(ind_frente * ind_fondo, 1) if ind_frente > 0 and ind_fondo > 0 else 0.0
        if _ind_area_calc > 0:
            st.caption(f"Área calculada: **{_ind_area_calc:,.0f} m²**")
            if st.session_state.get("ind_area_auto", True):
                st.session_state["ind_area_val"] = _ind_area_calc
        _ind_area_default = st.session_state.get("ind_area_val", 5000.0)
        ind_area = st.number_input("Área total del terreno (m²)", 0.0, 500_000.0,
                                   _ind_area_default, 50.0, key="ind_area")
        if abs(ind_area - _ind_area_calc) > 1 and _ind_area_calc > 0:
            st.session_state["ind_area_auto"] = False
        elif _ind_area_calc == 0:
            st.session_state["ind_area_auto"] = True

        ind_costo_terreno = st.number_input("Costo del terreno (USD)", 0, 100_000_000,
                                            1_000_000, 50_000, key="ind_costo_terreno")
        st.caption(f"= **${ind_costo_terreno:,.0f}** USD")

        # ── 3 · PROYECTO ────────────────────────────────────
        _step_header("3", "Proyecto")
        ind_pct_techada = st.number_input(
            "% Área techada (nave)",
            min_value=30.0, max_value=95.0, value=75.0, step=5.0, key="ind_pct_techada",
            help="Generalmente 75–80% del terreno. El remanente son patios y maniobras.")
        _ind_nave = ind_area * ind_pct_techada / 100
        _ind_libre = ind_area * (1 - ind_pct_techada / 100)
        st.caption(f"Nave: **{_ind_nave:,.0f} m²** · Patios/maniobras: **{_ind_libre:,.0f} m²**")

        ind_tipo = st.selectbox("Tipo de nave",
            ["Almacén Logístico", "Nave Industrial", "Cross-docking", "Producción / Manufactura"],
            key="ind_tipo")
        _COSTO_DEFAULTS = {
            "Almacén Logístico":        (280, "Estructura metálica portal frame, 12–14m clara, losa industrial. "
                                              "Ref. real: Parque Logístico 47 Lima (14,300 m², 13.6m, Clase A) = $270–300/m²"),
            "Nave Industrial":          (300, "Estructura metálica + elementos de concreto, uso mixto. "
                                              "Ref. Lima: $280–350/m² según especificación técnica"),
            "Cross-docking":            (420, "Mayor complejidad: múltiples docks, corredores internos, MEP intensivo. "
                                              "Ref. Lima: $380–500/m²"),
            "Producción / Manufactura": (380, "Losa reforzada (cargas pesadas), instalaciones especiales eléctricas/agua. "
                                              "Ref. Lima: $350–450/m²"),
        }
        _def_nave, _help_nave = _COSTO_DEFAULTS.get(
            st.session_state.get("ind_tipo", "Almacén Logístico"),
            (280, ""))
        st.caption("⚠ Industrial ≠ Residencial: estructura metálica sin acabados → **3-4x más barato por m²**")

        with st.expander("Costos de construcción"):
            ind_zona_ind = st.selectbox("Zonificación (referencia)",
                ["I1", "I2", "I3", "I4", "OU"], index=1, key="ind_zona_ind",
                help="Uso referencial. No afecta el cálculo de área.")
            ind_costo_nave = st.number_input(
                "Costo nave (USD/m²)",
                min_value=0, max_value=2000, value=_def_nave, step=25, key="ind_costo_nave",
                help=_help_nave)
            ind_costo_piso = st.number_input(
                "Costo patios / maniobras (USD/m²)",
                min_value=0, max_value=500, value=80, step=10, key="ind_costo_piso",
                help="Losa de concreto para circulación de montacargas/camiones. Ref. Lima: $60–90/m².")
            ind_pct_indirectos = st.number_input(
                "Costos indirectos (%)",
                min_value=0.0, max_value=30.0, value=5.0, step=0.5, key="ind_pct_indirectos",
                help="Permisos, licencias, supervisión, diseño, gestión. Ref: 5–8% sobre costo directo.")

        # ── 4 · FINANCIAMIENTO ──────────────────────────────
        _step_header("4", "Financiamiento")
        ind_pct_credito = st.number_input("Porcentaje financiado (%)", 0.0, 100.0, 60.0, 5.0,
                                          key="ind_pct_credito",
                                          help="Porcentaje del costo total financiado con crédito")
        ind_tasa = st.number_input("Tasa de interés anual (%)", 0.0, 30.0, 8.0, 0.25, key="ind_tasa")
        ind_plazo = st.number_input("Plazo del crédito (años)", 1, 30, 10, 1, key="ind_plazo")
        ind_alcabala = st.checkbox("Incluir Alcabala (3%)", value=True, key="ind_alcabala")

        # ── 5 · ANÁLISIS ─────────────────────────────────────
        _step_header("5", "Análisis de Uso")
        ind_uso = st.radio("Propósito del activo",
            ["Uso directo", "Inversión"], key="ind_uso",
            help="Uso directo: compra para operar. Inversión: compra para arrendar.")
        ind_renta = st.number_input(
            "Renta de mercado (USD/m²/mes)",
            0.0, 50.0, 6.5, 0.25, key="ind_renta",
            help="Ref. Lima: $5.5–7.0/m²/mes para almacenes logísticos")
        ind_tipo_contrato = st.radio(
            "Tipo de contrato", ["Anual", "Plurianual (3+ años)"],
            horizontal=True, key="ind_tipo_contrato")
        ind_ajuste_pct   = 0.0
        ind_inicio_ajuste = 2
        if ind_tipo_contrato == "Plurianual (3+ años)":
            _ica1, _ica2 = st.columns(2)
            ind_ajuste_pct    = _ica1.number_input(
                "Ajuste anual (%)", 0.0, 10.0, 3.0, 0.5, key="ind_ajuste_pct",
                help="Incremento de renta acordado. Ref. índice Lima: ~3% anual")
            ind_inicio_ajuste = _ica2.selectbox(
                "Año de inicio del ajuste", [2, 3], key="ind_inicio_ajuste",
                help="Contratos 3 años: ajuste en año 2 o 3 según lo pactado")

        # ── 6 · DOCUMENTOS ──────────────────────────────────
        _step_header("6", "Documentos")
        st.caption("Sube los documentos del proyecto para análisis de factibilidad")
        _ind_secrets_key = (st.secrets.get("anthropic", {}) or {}).get("api_key", "")
        if not _ind_secrets_key and not st.session_state.get("api_key_input"):
            with st.expander("⚙ Configuración API", expanded=True):
                _ind_api_k = st.text_input("Clave de acceso", type="password",
                                           placeholder="••••••••••••••••", key="ind_api_key_inp",
                                           value=st.session_state.get("api_key_input", ""))
                if _ind_api_k:
                    st.session_state["api_key_input"] = _sanitize_api_key(_ind_api_k)
        if _ind_secrets_key or st.session_state.get("api_key_input"):
            st.markdown(
                '<div style="font-size:10px;color:#1A4731;background:#E8F5EE;'
                'border-radius:4px;padding:5px 10px;margin-bottom:6px;'
                'border-left:2px solid #1A4731;">● Sistema activo</div>',
                unsafe_allow_html=True)
        ind_doc_partida = st.file_uploader("Partida Registral (SUNARP)", type="pdf", key="ind_doc_partida")
        ind_doc_params  = st.file_uploader("Certificado de Parámetros",  type="pdf", key="ind_doc_params")
        ind_doc_zon     = st.file_uploader("Cert. Zonificación y Vías",  type="pdf", key="ind_doc_zon")
        ind_doc_planos  = st.file_uploader("Planos del Inmueble",        type="pdf", key="ind_doc_planos")
        _ind_has_docs = any([ind_doc_partida, ind_doc_params, ind_doc_zon, ind_doc_planos])
        if _ind_has_docs:
            run_ind_docs = st.button("ANALIZAR DOCUMENTOS", use_container_width=True, key="btn_ind_docs")
        else:
            run_ind_docs = False
            st.caption("Adjunta al menos un documento para habilitar el análisis.")

        # ── 7 · FOTOS ───────────────────────────────────────
        _step_header("7", "Fotos del Inmueble")
        st.caption("Las fotos se incluyen en el reporte")
        _ind_fotos = st.file_uploader(
            "Sube fotos del terreno / nave",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="ind_fotos_upload",
        )
        if _ind_fotos:
            st.session_state["ind_fotos_bytes"] = [f.read() for f in _ind_fotos]
            st.session_state["ind_fotos_nombres"] = [f.name for f in _ind_fotos]
            cols_if = st.columns(min(len(_ind_fotos), 3))
            for _ifi, _ifup in enumerate(_ind_fotos[:3]):
                cols_if[_ifi].image(_ifup, use_container_width=True)

        # ── EJECUTAR ─────────────────────────────────────────
        st.markdown("---")
        run_industrial = st.button("EJECUTAR ANÁLISIS", use_container_width=True, type="primary")

        # ── PROYECTOS GUARDADOS ──────────────────────────────
        with st.expander("💾 Proyectos guardados"):
            _ind_saved = listar_proyectos()
            _ind_nombres = [p.name for p in _ind_saved]
            if _ind_nombres:
                _ind_sel = st.selectbox("Cargar proyecto", ["— seleccionar —"] + _ind_nombres,
                                        label_visibility="collapsed", key="ind_sel_proy")
                if _ind_sel != "— seleccionar —":
                    if st.button("CARGAR", use_container_width=True, key="btn_ind_cargar"):
                        _ind_pref = next((p for p in _ind_saved if p.name == _ind_sel), None)
                        _d = cargar_proyecto(_ind_pref or _ind_sel)
                        if _d.get("industrial_result"):
                            st.session_state.industrial_result = _d["industrial_result"]
                            st.rerun()
            _ind_nombre_proy = st.text_input("Nombre del proyecto", placeholder="Ej: Nave Lurín",
                                              label_visibility="collapsed", key="ind_nombre_proy")
            if st.button("GUARDAR PROYECTO", use_container_width=True, key="btn_ind_guardar"):
                if st.session_state.get("industrial_result"):
                    fp = guardar_proyecto(_ind_nombre_proy or "industrial_sin_nombre",
                                          {"industrial_result": st.session_state.industrial_result})
                    st.session_state["_last_ind_proy"] = fp
                    st.session_state.pop("_share_url_ind", None)
                    st.markdown(f'<div style="background:rgba(107,206,160,0.12);border-left:3px solid rgba(107,206,160,0.50);'
                                f'border-radius:6px;padding:8px 12px;color:rgba(107,206,160,0.90);font-size:12px;font-weight:600;margin-top:6px;">'
                                f'✓ {fp.name}</div>', unsafe_allow_html=True)
                else:
                    st.warning("Ejecuta el análisis primero.")
            _lp_ind = st.session_state.get("_last_ind_proy")
            if _lp_ind and _lp_ind._id:
                if st.button("GENERAR LINK DE COMPARTIR", use_container_width=True, key="btn_share_ind"):
                    _tok = str(uuid.uuid4())
                    _sb2 = _get_supabase()
                    if _sb2:
                        _sb2.table("proyectos").update({"share_token": _tok}).eq("id", _lp_ind._id).execute()
                        _base = (st.secrets.get("app", {}) or {}).get("base_url", "http://localhost:8501")
                        st.session_state["_share_url_ind"] = f"{_base}?share={_tok}"
                if st.session_state.get("_share_url_ind"):
                    st.code(st.session_state["_share_url_ind"])
                    st.caption("Comparte con tu cliente — no requiere contraseña")

    # ── MÓDULO 3: INMUEBLE RESIDENCIAL ────────────────────
    elif tipo_op == "Inmueble Residencial":
        run = False
        run_industrial = False

        # ── 1 · UBICACIÓN ──────────────────────────────────
        _step_header("1", "Ubicación")
        with st.expander("📄 Importar datos desde documento"):
            st.caption("Sube una ficha técnica, tasación o brochure del inmueble — la IA extrae automáticamente área, antigüedad, precio y ubicación para pre-llenar los campos.")
            _res_doc_up = st.file_uploader(
                "PDF, PPTX o DOCX",
                type=["pdf", "pptx", "ppt", "docx"],
                key="res_import_doc",
            )
            if _res_doc_up and st.button("EXTRAER DATOS", key="btn_res_extract", use_container_width=True):
                _res_bytes = _res_doc_up.read()
                _res_ext = _run_with_retry(
                    lambda _b=_res_bytes, _n=_res_doc_up.name: extraer_datos_desde_doc(_b, _n, "residencial"),
                    "Analizando documento…"
                )
                if _res_ext.get("_error"):
                    st.error(_res_ext["_error"])
                else:
                    if _res_ext.get("area_m2"):
                        st.session_state["res_m2_k"] = int(_res_ext["area_m2"])
                    if _res_ext.get("antiguedad_anios") is not None:
                        st.session_state["res_antig_k"] = int(_res_ext["antiguedad_anios"])
                    if _res_ext.get("precio_usd"):
                        st.session_state["res_precio_k"] = int(_res_ext["precio_usd"])
                    if _res_ext.get("alquiler_mes_usd"):
                        st.session_state["res_alq_k"] = int(_res_ext["alquiler_mes_usd"])
                    _ext_dorm = _res_ext.get("dormitorios") or ""
                    _dorm_opts_ext = ["1 Dormitorio", "2 Dormitorios", "3 Dormitorios", "Dúplex / Otro"]
                    for _d in _dorm_opts_ext:
                        if any(x in _ext_dorm for x in (_d[:2], _d.split()[0])):
                            st.session_state["res_dorm_k"] = _d
                            break
                    _ext_dist = _res_ext.get("distrito") or ""
                    for _k in MERCADO.keys():
                        if _ext_dist.lower() in _k.lower() or _k.lower() in _ext_dist.lower():
                            st.session_state["res_zona_sel"] = _k
                            break
                    st.success("Datos extraídos. Revisa y ajusta antes de ejecutar.")
                    st.rerun()

        res_zona = st.selectbox("Ubicación", list(MERCADO.keys()),
                                 index=20, key="res_zona_sel",
                                 help="Selecciona el distrito para comparar con datos de mercado Urbania 2025")
        _m_res = MERCADO[res_zona]

        # ── 2 · INMUEBLE ───────────────────────────────────
        _step_header("2", "Inmueble")
        res_col1, res_col2 = st.columns(2)
        res_m2 = res_col1.number_input("Área (m²)", 0, 2000, int(st.session_state.get("res_m2_k", 80)), 5, key="res_m2_k")
        res_antiguedad = res_col2.number_input("Antigüedad (años)", 0, 100, int(st.session_state.get("res_antig_k", 5)), 1, key="res_antig_k")
        _dorm_opts = ["1 Dormitorio", "2 Dormitorios", "3 Dormitorios", "Dúplex / Otro"]
        _dorm_default_idx = _dorm_opts.index(st.session_state["res_dorm_k"]) if st.session_state.get("res_dorm_k") in _dorm_opts else 1
        res_dormitorios = st.selectbox("Tipología", _dorm_opts, index=_dorm_default_idx, key="res_dorm_k")

        # ── 3 · PRECIO ─────────────────────────────────────
        _step_header("3", "Precio")
        _precio_ref = (_m_res["precio_1br"] if "1" in res_dormitorios else
                       _m_res["precio_2br"] if "2" in res_dormitorios else
                       _m_res["precio_3br"]) * res_m2
        _ref_m2_display = _m_res['precio_2br'] if '2' in res_dormitorios else (_m_res['precio_1br'] if '1' in res_dormitorios else _m_res['precio_3br'])
        st.caption(f"Valor mercado: **${_ref_m2_display:,}/m²** — Ref. total: ${_precio_ref:,.0f}")

        res_precio = st.number_input("Precio de compra (USD)", 0, 10_000_000,
                                      int(st.session_state.get("res_precio_k", max(int(_precio_ref / 10000) * 10000, 50000))), 5_000, format="%d", key="res_precio_k")

        _ppm2 = res_precio / res_m2 if res_m2 > 0 else 0
        _ref_m2 = _m_res["precio_2br"] if "2" in res_dormitorios else (_m_res["precio_1br"] if "1" in res_dormitorios else _m_res["precio_3br"])
        _diff_pct = ((_ppm2 - _ref_m2) / _ref_m2 * 100) if _ref_m2 > 0 else 0
        if abs(_diff_pct) <= 8:
            _pos_color, _pos_text = "#1A4731", f"En línea con mercado ({_diff_pct:+.1f}%)"
        elif _diff_pct > 8:
            _pos_color, _pos_text = "#7A1A1A", f"Sobre el mercado ({_diff_pct:+.1f}%) — negociar"
        else:
            _pos_color, _pos_text = "#1A4731", f"Por debajo del mercado ({_diff_pct:+.1f}%) — oportunidad"
        st.markdown(f'<div style="background:rgba(255,255,255,0.06);border-left:3px solid {_pos_color};border-radius:6px;'
                    f'padding:6px 12px;font-size:11px;color:{_pos_color};font-weight:600;margin-bottom:4px;">'
                    f'${_ppm2:,.0f}/m² — {_pos_text}</div>', unsafe_allow_html=True)

        # ── 4 · FINANCIAMIENTO ──────────────────────────────
        _step_header("4", "Financiamiento")
        res_pct_pie = st.number_input("Pago inicial / Down Payment (%)", 0.0, 100.0, 20.0, 1.0,
                                       help="Porcentaje que pagas de tu propio capital")
        res_tasa = st.number_input("Tasa de interés anual (%)", 0.0, 30.0, 8.5, 0.25,
                                    help="Tasa efectiva anual del crédito hipotecario")
        res_plazo = st.number_input("Plazo del crédito (años)", 1, 30, 20, 1)

        # ── 5 · PROPÓSITO ───────────────────────────────────
        _step_header("5", "Propósito")
        res_uso = st.radio("¿Para qué?",
            ["Vivienda propia", "Inversión para alquilar", "Evaluación para venta"],
            help="Define el análisis y los documentos que se generarán")

        if res_uso in ["Inversión para alquilar", "Evaluación para venta"]:
            _alq_sugerido = round(_m_res["alquiler_m2_mes"] * res_m2 / 50) * 50
            if res_uso == "Inversión para alquilar":
                st.caption(f"Mercado zona sugiere: **${_alq_sugerido:,}/mes** (${_m_res['alquiler_m2_mes']:.1f}/m²/mes)")
                res_alquiler = st.number_input("Renta mensual (USD)", 0, 20_000,
                                                int(st.session_state.get("res_alq_k", int(_alq_sugerido))), 50, key="res_alq_inp")
                res_tipo_contrato = st.radio(
                    "Tipo de contrato", ["Anual", "Plurianual (3+ años)"],
                    horizontal=True, key="res_tipo_contrato")
                res_ajuste_pct    = 0.0
                res_inicio_ajuste = 2
                if res_tipo_contrato == "Plurianual (3+ años)":
                    _rca1, _rca2 = st.columns(2)
                    res_ajuste_pct    = _rca1.number_input(
                        "Ajuste anual (%)", 0.0, 10.0, 3.0, 0.5, key="res_ajuste_pct",
                        help="Incremento de renta acordado. Ref. índice Lima: ~3% anual")
                    res_inicio_ajuste = _rca2.selectbox(
                        "Año de inicio del ajuste", [2, 3], key="res_inicio_ajuste",
                        help="Contratos 3 años: ajuste en año 2 o 3 según lo pactado")
            else:
                res_alquiler      = 0
                res_tipo_contrato = "Anual"
                res_ajuste_pct    = 0.0
                res_inicio_ajuste = 2
            res_gastos = st.number_input("Gastos mensuales (USD)", 0, 5_000,
                                          max(int(res_precio * 0.004 / 12), 50), 10,
                                          help="Mantenimiento, administración, arbitrios, seguro (~4% anual del valor)")
        else:
            res_alquiler      = 0
            res_gastos        = 0
            res_tipo_contrato = "Anual"
            res_ajuste_pct    = 0.0
            res_inicio_ajuste = 2

        # ── 6 · COMPARATIVA ─────────────────────────────────
        _step_header("6", "Comparativa de Inmuebles")
        st.caption("Agrega hasta 3 inmuebles alternativos para comparar")
        if "res_inmuebles_comp" not in st.session_state:
            st.session_state.res_inmuebles_comp = []

        with st.expander("Agregar inmueble a comparar"):
            _rc_nombre = st.text_input("Nombre / referencia", placeholder="Ej: Depto Av. Larco 320", key="rc_nombre_inp")
            _rc_col1, _rc_col2 = st.columns(2)
            _rc_precio = _rc_col1.number_input("Precio USD", 0, 10_000_000, 200_000, 5_000, format="%d", key="rc_precio_inp")
            _rc_m2 = _rc_col2.number_input("m²", 10, 2000, 80, 5, key="rc_m2")
            _rc_col3, _rc_col4 = st.columns(2)
            _rc_alq = _rc_col3.number_input("Alquiler/mes USD", 0, 20_000, 800, 50, key="rc_alq")
            _rc_dorm = _rc_col4.selectbox("Dorm.", ["1D", "2D", "3D"], key="rc_dorm")
            _rc_zona = st.selectbox("Distrito", list(MERCADO.keys()), key="rc_zona_sel")
            _rc_img = st.file_uploader("Foto del inmueble (opcional)", type=["jpg", "jpeg", "png", "webp"], key="rc_img_upload")
            if st.button("AGREGAR", use_container_width=True, key="btn_rc_agregar", type="primary"):
                if _rc_nombre.strip():
                    _rc_img_bytes = _rc_img.read() if _rc_img else None
                    st.session_state.res_inmuebles_comp.append({
                        "nombre": _rc_nombre.strip(),
                        "precio": _rc_precio, "m2": _rc_m2,
                        "alquiler": _rc_alq, "dormitorios": _rc_dorm,
                        "zona": _rc_zona,
                        "precio_m2": round(_rc_precio / _rc_m2) if _rc_m2 > 0 else 0,
                        "yield_bruto": round(_rc_alq * 12 / _rc_precio * 100, 1) if _rc_precio > 0 and _rc_alq > 0 else 0,
                        "imagen_bytes": _rc_img_bytes,
                        "imagen_nombre": _rc_img.name if _rc_img else None,
                    })
                    st.rerun()

        if st.session_state.res_inmuebles_comp:
            for _i, _ci in enumerate(st.session_state.res_inmuebles_comp):
                _cc1, _cc2 = st.columns([5, 1])
                _cc1.caption(f"**{_ci['nombre']}** — ${_ci['precio']:,} · ${_ci['precio_m2']:,}/m²")
                if _cc2.button("✕", key=f"del_ri_{_i}"):
                    st.session_state.res_inmuebles_comp.pop(_i)
                    st.rerun()
            if st.button("Limpiar comparativa", use_container_width=True, key="btn_clear_ri"):
                st.session_state.res_inmuebles_comp = []
                st.rerun()

        # ── 7 · DOCUMENTOS ──────────────────────────────────
        _step_header("7", "Documentos")
        st.caption("Sube los documentos del inmueble para análisis registral y técnico")
        _res_secrets_key = (st.secrets.get("anthropic", {}) or {}).get("api_key", "")
        if not _res_secrets_key and not st.session_state.get("api_key_input"):
            with st.expander("⚙ Configuración API", expanded=True):
                _res_api_k = st.text_input("Clave de acceso", type="password",
                                           placeholder="••••••••••••••••", key="res_api_key_inp",
                                           value=st.session_state.get("api_key_input", ""))
                if _res_api_k:
                    st.session_state["api_key_input"] = _sanitize_api_key(_res_api_k)
        if _res_secrets_key or st.session_state.get("api_key_input"):
            st.markdown(
                '<div style="font-size:10px;color:#1A4731;background:#E8F5EE;'
                'border-radius:4px;padding:5px 10px;margin-bottom:6px;'
                'border-left:2px solid #1A4731;">● Sistema activo</div>',
                unsafe_allow_html=True)
        res_doc_partida = st.file_uploader("Partida Registral (SUNARP)", type="pdf", key="res_doc_partida")
        res_doc_puhr    = st.file_uploader("PU / HR",                    type="pdf", key="res_doc_puhr")
        res_doc_params  = st.file_uploader("Certificado de Parámetros",  type="pdf", key="res_doc_params")
        res_doc_planos  = st.file_uploader("Planos del Inmueble",        type="pdf", key="res_doc_planos")
        _res_has_docs = any([res_doc_partida, res_doc_puhr, res_doc_params, res_doc_planos])
        if _res_has_docs:
            run_res_docs = st.button("ANALIZAR DOCUMENTOS", use_container_width=True, key="btn_res_docs")
        else:
            run_res_docs = False
            st.caption("Adjunta al menos un documento para habilitar el análisis.")

        # ── 8 · FOTOS ───────────────────────────────────────
        _step_header("8", "Fotos del Inmueble")
        st.caption("Las fotos se incluyen en el informe")
        _res_fotos = st.file_uploader(
            "Sube fotos del inmueble",
            type=["jpg", "jpeg", "png", "webp"],
            accept_multiple_files=True,
            key="res_fotos_upload",
        )
        if _res_fotos:
            st.session_state["res_fotos_bytes"] = [f.read() for f in _res_fotos]
            st.session_state["res_fotos_nombres"] = [f.name for f in _res_fotos]
            cols_rf = st.columns(min(len(_res_fotos), 3))
            for _rfi, _rfup in enumerate(_res_fotos[:3]):
                cols_rf[_rfi].image(_rfup, use_container_width=True)

        # ── EJECUTAR ─────────────────────────────────────────
        st.markdown("---")
        run_residencial = st.button("EJECUTAR ANÁLISIS", use_container_width=True, type="primary")

        # ── PROYECTOS GUARDADOS ──────────────────────────────
        with st.expander("💾 Proyectos guardados"):
            _res_saved = listar_proyectos()
            _res_nombres = [p.name for p in _res_saved]
            if _res_nombres:
                _res_sel = st.selectbox("Cargar proyecto", ["— seleccionar —"] + _res_nombres,
                                        label_visibility="collapsed", key="res_sel_proy")
                if _res_sel != "— seleccionar —":
                    if st.button("CARGAR", use_container_width=True, key="btn_res_cargar"):
                        _res_pref = next((p for p in _res_saved if p.name == _res_sel), None)
                        _d = cargar_proyecto(_res_pref or _res_sel)
                        if _d.get("residencial_result"):
                            st.session_state.residencial_result = _d["residencial_result"]
                            st.rerun()
            _res_nombre_proy = st.text_input("Nombre del proyecto", placeholder="Ej: Depto Miraflores",
                                              label_visibility="collapsed", key="res_nombre_proy")
            if st.button("GUARDAR PROYECTO", use_container_width=True, key="btn_res_guardar"):
                if st.session_state.get("residencial_result"):
                    fp = guardar_proyecto(_res_nombre_proy or "residencial_sin_nombre",
                                          {"residencial_result": st.session_state.residencial_result})
                    st.session_state["_last_res_proy"] = fp
                    st.session_state.pop("_share_url_res", None)
                    st.markdown(f'<div style="background:rgba(107,206,160,0.12);border-left:3px solid rgba(107,206,160,0.50);'
                                f'border-radius:6px;padding:8px 12px;color:rgba(107,206,160,0.90);font-size:12px;font-weight:600;margin-top:6px;">'
                                f'✓ {fp.name}</div>', unsafe_allow_html=True)
                else:
                    st.warning("Ejecuta el análisis primero.")
            _lp_res = st.session_state.get("_last_res_proy")
            if _lp_res and _lp_res._id:
                if st.button("GENERAR LINK DE COMPARTIR", use_container_width=True, key="btn_share_res"):
                    _tok = str(uuid.uuid4())
                    _sb2 = _get_supabase()
                    if _sb2:
                        _sb2.table("proyectos").update({"share_token": _tok}).eq("id", _lp_res._id).execute()
                        _base = (st.secrets.get("app", {}) or {}).get("base_url", "http://localhost:8501")
                        st.session_state["_share_url_res"] = f"{_base}?share={_tok}"
                if st.session_state.get("_share_url_res"):
                    st.code(st.session_state["_share_url_res"])
                    st.caption("Comparte con tu cliente — no requiere contraseña")

# ── SESSION STATE ────────────────────────────────────

for k in ("params", "cabida", "financ", "zona", "legal",
          "partida_bytes", "puhr_bytes", "industrial_result", "residencial_result",
          "industrial_factibilidad", "residencial_legal", "ind_resumen", "res_resumen"):
    if k not in st.session_state:
        st.session_state[k] = None
if "financ_inputs" not in st.session_state:
    st.session_state.financ_inputs = {}
if "competencia" not in st.session_state:
    st.session_state.competencia = []
if "ind_comparativa" not in st.session_state:
    st.session_state.ind_comparativa = []
if "res_comparativa" not in st.session_state:
    st.session_state.res_comparativa = []
if "comps_sunarp" not in st.session_state:
    st.session_state.comps_sunarp = []

tipo_op = st.session_state.get("tipo_operacion", "Proyecto Inmobiliario")

# ── EJECUCIÓN ────────────────────────────────────────

if tipo_op == "Proyecto Logístico / Industrial" and (run_industrial or st.session_state.get("ind_analizado")):
    _ind_inp = {
        "area_terreno":        ind_area,
        "costo_terreno":       ind_costo_terreno,
        "tipo_nave":           ind_tipo,
        "zonificacion":        ind_zona_ind,
        "pct_techada":         ind_pct_techada,
        "costo_nave_m2":       ind_costo_nave,
        "costo_piso_libre_m2": ind_costo_piso,
        "pct_indirectos":      ind_pct_indirectos,
        "include_alcabala":    ind_alcabala,
        "pct_credito":         ind_pct_credito,
        "tasa_anual":          ind_tasa,
        "plazo_anos":          ind_plazo,
        "renta_m2_mes":        ind_renta,
        "uso":                 ind_uso,
        "tipo_contrato":       ind_tipo_contrato,
        "ajuste_anual_pct":    ind_ajuste_pct,
        "inicio_ajuste_ano":   ind_inicio_ajuste,
    }
    st.session_state.industrial_result = calcular_industrial(_ind_inp)
    st.session_state.ind_analizado = True

if tipo_op == "Proyecto Logístico / Industrial" and run_ind_docs:
    _ip  = ind_doc_partida.read() if ind_doc_partida else None
    _ic  = ind_doc_params.read()  if ind_doc_params  else None
    _iz  = ind_doc_zon.read()     if ind_doc_zon      else None
    _ipl = ind_doc_planos.read()  if ind_doc_planos   else None
    _it  = st.session_state.get("ind_tipo", "Almacén Logístico")
    _iz2 = st.session_state.get("ind_zona_ind", "I2")
    _iu  = st.session_state.get("ind_uso", "Uso directo")
    st.session_state.industrial_factibilidad = _run_with_retry(
        lambda _ip=_ip, _ic=_ic, _iz=_iz, _it=_it, _iz2=_iz2, _iu=_iu, _ipl=_ipl: analizar_factibilidad_industrial(_ip, _ic, _iz, _it, _iz2, _iu, _ipl),
        "Analizando factibilidad técnica y documentos registrales…",
    )
    st.rerun()

if tipo_op == "Inmueble Residencial" and run_res_docs:
    _rp = res_doc_partida.read() if res_doc_partida else None
    _ru = res_doc_puhr.read()    if res_doc_puhr    else None
    _rc = res_doc_params.read() if res_doc_params else None
    _rl = res_doc_planos.read() if res_doc_planos  else None
    st.session_state.residencial_legal = _run_with_retry(
        lambda _p=_rp, _u=_ru, _c=_rc, _l=_rl: analizar_legal(_p, _u, _c, _l),
        "Analizando documentos legales…",
    )
    st.rerun()

elif tipo_op == "Inmueble Residencial" and (run_residencial or st.session_state.get("res_analizado")):
    _res_precio_m2_mercado = (MERCADO[res_zona]["precio_2br"] if "2" in res_dormitorios
                               else MERCADO[res_zona]["precio_1br"] if "1" in res_dormitorios
                               else MERCADO[res_zona]["precio_3br"])
    st.session_state.residencial_result = calcular_residencial({
        "precio":     res_precio,
        "pct_pie":    res_pct_pie,
        "tasa_anual": res_tasa,
        "plazo_anos": res_plazo,
        "uso":        res_uso,
        "alquiler_mes":      res_alquiler,
        "gastos_mes":        res_gastos,
        "tipo_contrato":     res_tipo_contrato,
        "ajuste_anual_pct":  res_ajuste_pct,
        "inicio_ajuste_ano": res_inicio_ajuste,
        "zona":       res_zona,
        "dormitorios": res_dormitorios,
        "m2":         res_m2,
        "antiguedad": res_antiguedad,
        "precio_m2":  res_precio / res_m2 if res_m2 > 0 else 0,
        "precio_m2_mercado": _res_precio_m2_mercado,
        "yield_mercado_pct": MERCADO[res_zona]["yield_mercado_pct"],
        "alquiler_mercado_m2": MERCADO[res_zona]["alquiler_m2_mes"],
        "variacion_anual_pct": MERCADO[res_zona]["variacion_anual_pct"],
    })
    st.session_state.res_analizado = True
    st.session_state["_res_zona_val"]      = res_zona
    st.session_state["_res_m2_val"]        = res_m2
    st.session_state["_res_antiguedad_val"] = res_antiguedad

elif run:
    if not pdf_cert:
        st.warning("⚠️ Adjunta el Certificado de Parámetros para continuar.")
        st.stop()

    # Recopilar todos los documentos adicionales
    extra_docs = []
    if pdf_plano:
        for f in (pdf_plano if isinstance(pdf_plano, list) else [pdf_plano]):
            extra_docs.append(f.read())
    if pdf_partida:
        _partida_bytes = pdf_partida.read()
        extra_docs.append(_partida_bytes)
        st.session_state.partida_bytes = _partida_bytes
    if pdf_puhr:
        _puhr_bytes = pdf_puhr.read()
        extra_docs.append(_puhr_bytes)
        st.session_state.puhr_bytes = _puhr_bytes
    if pdf_norms:
        for f in pdf_norms:
            extra_docs.append(f.read())

    _cert_bytes = pdf_cert.read()
    st.session_state.params = _run_with_retry(
        lambda _cb=_cert_bytes, _ed=list(extra_docs): extract_parameters(_cb, _ed),
        "Extrayendo información del documento…",
    )

    # Aplicar overrides manuales sobre los parámetros extraídos
    if override_area > 0:
        st.session_state.params["area_terreno_m2"] = override_area
    if override_al > 0:
        st.session_state.params["area_libre_min_pct"] = override_al

    config = {
        "sugerencias": sugerencias or "",
        "colindante_izq_pisos": colind_izq if colind_izq > 0 else None,
        "colindante_der_pisos": colind_der if colind_der > 0 else None,
    }

    _params_snap = st.session_state.params
    _config_snap = config
    st.session_state.cabida = _run_with_retry(
        lambda _ps=dict(_params_snap), _cs=dict(_config_snap): generate_cabida(_ps, _cs),
        "Analizando data y elaborando cabida…",
    )

    m = MERCADO[zona]
    st.session_state.financ_inputs = {
        "costo_terreno":      precio_compra,
        "costo_construccion": costo_const_m2,
        "costo_sotano_m2":    costo_sotano_m2,
        "fee_constructora":   fee_constructora,
        "tasa_ir":            tasa_ir,
        "include_alcabala":   include_alcabala,
        "include_dd":         include_dd,
        "precio_venta_m2":    precio_venta_m2,
        "precio_1br":         m["precio_1br"],
        "precio_2br":         m["precio_2br"],
        "precio_3br":         m["precio_3br"],
        "precio_estac":       m["precio_estac"],
        "precio_deposito":    m["precio_deposito"],
        "tasa_financ":        7.0,
    }
    st.session_state.zona = zona

# ── TABS ─────────────────────────────────────────────

if tipo_op == "Proyecto Inmobiliario":
    if st.session_state.params:
        p        = st.session_state.params
        c        = st.session_state.cabida
        zona_sel = st.session_state.zona or zona

        if st.session_state.get("_goto_tab") is not None:
            _ti = st.session_state.pop("_goto_tab")
            st.components.v1.html(f"""<script>
            setTimeout(function(){{
                var tabs=window.parent.document.querySelectorAll('[role="tab"]');
                if(tabs&&tabs.length>{_ti}){{tabs[{_ti}].click();}}
            }},400);
            </script>""", height=0)

        # ── Main header ──────────────────────────────────────────────
        _cab_ubicacion = p.get("ubicacion") or p.get("direccion") or zona_sel or "—"
        _cab_zona_txt  = p.get("zonificacion", "—")
        _cab_pisos     = p.get("pisos_max", "—")
        st.markdown(
            '<div class="main-header">'
            '<div style="display:flex;align-items:center;justify-content:space-between;">'
            '<div>'
            '<div style="font-size:9px;color:#B8904A;letter-spacing:4px;text-transform:uppercase;font-weight:600;margin-bottom:10px;">Osterling Advisory</div>'
            '<div style="display:flex;align-items:center;gap:18px;">'
            '<span style="font-size:22px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;">ANÁLISIS DE PROYECTO</span>'
            '<span style="width:1px;height:18px;background:#B8904A;opacity:0.4;display:inline-block;flex-shrink:0;"></span>'
            f'<span style="font-size:10px;color:#8AA8C0;letter-spacing:2.5px;text-transform:uppercase;font-weight:500;">'
            f'{_cab_zona_txt} · {_cab_pisos} pisos · {zona_sel}</span>'
            '</div></div>'
            '<div style="text-align:right;"><div style="font-size:8px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;font-weight:600;opacity:0.7;">Lima, Perú</div></div>'
            '</div></div>',
            unsafe_allow_html=True
        )

        # ── Project Hero Banner ───────────────────────────────────────
        import base64 as _b64c
        _cab_hero_fotos = st.session_state.get("cab_fotos_bytes") or []
        if _cab_hero_fotos:
            try:
                _b64_cab = _b64c.b64encode(_cab_hero_fotos[0]).decode()
                _cab_photo_css = f"url('data:image/jpeg;base64,{_b64_cab}') center/cover no-repeat"
            except Exception:
                _cab_photo_css = "linear-gradient(135deg,#1E2D3D 0%,#2A4060 100%)"
        else:
            _cab_photo_css = "linear-gradient(135deg,#1E2D3D 0%,#2A4060 100%)"

        _fr = st.session_state.financ["resumen"] if st.session_state.financ else None
        _cab_kpi1_label, _cab_kpi1_val = ("Terreno", f"{p.get('area_terreno_m2','—')} m²")
        _cab_kpi2_label, _cab_kpi2_val = ("Zonificación", _cab_zona_txt)
        _cab_kpi3_label, _cab_kpi3_val = ("Altura máx.", f"{_cab_pisos} pisos")
        _cab_kpi4_tuple = ("Margen neto", f"{_fr['margen_pct']:.1f}%") if _fr else ("Área libre mín.", f"{p.get('area_libre_min_pct','—')}%")
        _cab_kpi4_label, _cab_kpi4_val = _cab_kpi4_tuple
        _cab_fin_extra = (
            f'<div><div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">TIR Anual</div>'
            f'<div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_fr["tir_anual_pct"]:.1f}%</div></div>'
            if _fr else ""
        )
        _cab_nombre = st.session_state.get("nombre_proyecto") or _cab_ubicacion

        st.markdown(f"""
        <div style="position:relative;border-radius:16px;overflow:hidden;margin-bottom:20px;
                    box-shadow:0 6px 30px rgba(30,45,61,0.22);">
            <div style="background:{_cab_photo_css};height:220px;"></div>
            <div style="position:absolute;inset:0;background:linear-gradient(to bottom,
                        rgba(0,0,0,0.0) 0%,rgba(0,0,0,0.75) 100%);
                        display:flex;flex-direction:column;justify-content:flex-end;
                        padding:24px 28px;">
                <div style="font-size:9px;color:rgba(255,255,255,0.60);letter-spacing:3px;
                            text-transform:uppercase;margin-bottom:6px;">
                    Análisis de Proyecto Inmobiliario · FACTIS
                </div>
                <div style="font-size:28px;font-weight:800;color:#FFFFFF;line-height:1.15;
                            text-shadow:0 2px 8px rgba(0,0,0,0.5);">
                    {_cab_nombre}
                </div>
                <div style="display:flex;gap:20px;margin-top:12px;flex-wrap:wrap;">
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">{_cab_kpi1_label}</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_cab_kpi1_val}</div>
                    </div>
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">{_cab_kpi2_label}</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_cab_kpi2_val}</div>
                    </div>
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">{_cab_kpi3_label}</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_cab_kpi3_val}</div>
                    </div>
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">{_cab_kpi4_label}</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_cab_kpi4_val}</div>
                    </div>
                    {_cab_fin_extra}
                </div>
            </div>
        </div>""", unsafe_allow_html=True)

        tabs = st.tabs(["Parámetros", "Cabida", "Financiero", "Competencia", "Flujo de Caja", "Legal", "Resumen", "Propuesta"])

        # ── TAB 1: PARÁMETROS ────────────────────────────
        with tabs[0]:
            st.markdown('<div class="section-title">Datos Extraídos del Certificado</div>', unsafe_allow_html=True)

            c1, c2, c3 = st.columns(3)
            with c1:
                card("Zonificación",    p.get("zonificacion",    "—"))
                card("Área del terreno", f"{p.get('area_terreno_m2','—')} m²")
                card("Frente",          f"{p.get('frente_ml','—')} ml")
            with c2:
                card("Altura máxima",    f"{p.get('pisos_max','—')} pisos")
                card("Área libre mínima", f"{p.get('area_libre_min_pct','—')}%")
                card("Retiro frontal",   f"{p.get('retiro_frontal_ml','—')} ml")
            with c3:
                card("Retiro lateral",   f"{p.get('retiro_lateral_ml','—') or '—'} ml")
                card("Retiro posterior",  f"{p.get('retiro_posterior_ml','—') or '—'} ml")
                card("Caduca",           p.get("fecha_caducidad","—"), color="#8B3A2A")

            if p.get("pisos_por_via"):
                st.markdown('<div class="section-title">Alturas por Vía</div>', unsafe_allow_html=True)
                st.dataframe(pd.DataFrame(p["pisos_por_via"]), use_container_width=True, hide_index=True)

            if p.get("notas_altura"):
                st.markdown('<div class="section-title">Notas Normativas de Altura</div>', unsafe_allow_html=True)
                for nota in p["notas_altura"]:
                    st.markdown(f'<div class="alert-gold">📌 {nota}</div>', unsafe_allow_html=True)

            # ── BENEFICIOS NORMATIVOS ─────────────────────
            beneficios = p.get("beneficios_normativos", [])
            if beneficios:
                st.markdown('<div class="section-title">Beneficios Normativos Identificados</div>', unsafe_allow_html=True)

                tipo_icons = {
                    "mayor_altura":             "🔺",
                    "reduccion_aportes":        "📉",
                    "flexibilizacion_retiros":  "↔️",
                    "incentivo_densificacion":  "🏙️",
                    "otro":                     "⚖️",
                }
                for b in beneficios:
                    icon = tipo_icons.get(b.get("tipo", "otro"), "⚖️")
                    st.markdown(f"""
                    <div class="alert-legal">
                        <strong>{icon} {b.get('descripcion','')}</strong><br>
                        <span style="font-size:12px;color:#4A6080">
                            <em>Condición:</em> {b.get('condicion','—')} &nbsp;|&nbsp;
                            <em>Impacto:</em> {b.get('impacto_estimado','—')} &nbsp;|&nbsp;
                            <em>Base legal:</em> {b.get('base_legal','—')}
                        </span>
                    </div>""", unsafe_allow_html=True)
            else:
                st.markdown('<div class="section-title">Base Legal</div>', unsafe_allow_html=True)

            if p.get("ordenanzas_base"):
                for ord_ in p["ordenanzas_base"]:
                    st.markdown(f"• {ord_}")

        # ── TAB 2: CABIDA ────────────────────────────────
        with tabs[1]:
            if not c:
                st.markdown('<div class="alert-legal">Genera el análisis primero.</div>', unsafe_allow_html=True)
            else:
                st.markdown('<div class="section-title">Programa Arquitectónico</div>', unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("M² construibles",  f"{c.get('area_techada_total_m2',0):,.0f}")
                col2.metric("M² vendibles",      f"{c.get('area_vendible_m2',0):,.0f}")
                col3.metric("Departamentos",     str(c.get('total_unidades', 0)))
                col4.metric("Estacionamientos",  str(c.get('estac_total', 0)))

                st.markdown('<div class="section-title">Mix de Tipologías</div>', unsafe_allow_html=True)
                unidades = c.get("unidades", [])
                if unidades:
                    df_u = pd.DataFrame(unidades)
                    df_u.columns = ["Tipología", "Cantidad", "Área/unidad (m²)", "Área total (m²)"]
                    st.dataframe(df_u, use_container_width=True, hide_index=True)

                    fig = px.pie(df_u, values="Cantidad", names="Tipología",
                                 color_discrete_sequence=["#1E2D3D", "#B8904A", "#8A9BAD"], hole=0.5)
                    fig.update_traces(textfont_size=12, textfont_family="Inter, sans-serif",
                                      marker=dict(line=dict(color="#EDEAE4", width=3)))
                    fig.update_layout(
                        height=280, margin=dict(t=10, b=10, l=10, r=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(family="Inter, sans-serif", color="#1E2D3D"),
                        legend=dict(font=dict(size=12), bgcolor="rgba(0,0,0,0)"),
                    )
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

                col1, col2, col3 = st.columns(3)
                col1.metric("Estac. residentes", c.get("estac_residentes", 0))
                col2.metric("Estac. visitas",    c.get("estac_visitas",    0))
                col3.metric("Pisos",             c.get("num_pisos", "—"))

                # ── KPIs de eficiencia (benchmarks U. del Pacífico) ─
                _at_sobre  = c.get("area_techada_total_m2", 0)
                _at_sotano = c.get("num_sotanos", 0) * c.get("area_techada_piso_m2", 0)
                _at_total  = _at_sobre + _at_sotano
                _av        = c.get("area_vendible_m2", 0)
                _unidades  = c.get("total_unidades", 1) or 1
                _estac     = c.get("estac_total", 0)
                _av_at_sobre = round(_av / _at_sobre * 100, 1) if _at_sobre > 0 else 0
                _av_at_total = round(_av / _at_total * 100, 1) if _at_total > 0 else 0
                _autos_viv   = round(_estac / _unidades, 2) if _unidades > 0 else 0

                st.markdown('<div class="section-title">KPIs de Eficiencia</div>', unsafe_allow_html=True)
                _kc1, _kc2, _kc3, _kc4 = st.columns(4)
                _kc1.metric("AV/AT sobre rasante", f"{_av_at_sobre}%",
                            help="Área vendible / área techada sobre rasante. Ref.: 75-80%")
                _kc2.metric("AV/AT total (c/sótanos)", f"{_av_at_total}%",
                            help="Área vendible / área techada total. Ref. real Lima: 60-74%")
                _kc3.metric("Autos / vivienda", f"{_autos_viv}",
                            help="Ratio estacionamientos / departamentos. Ref. mercado Lima: ≈0.91")
                _kc4.metric("Depósitos / vivienda", f"{round(c.get('depositos_total',0)/_unidades,2)}",
                            help="Ratio depósitos sobre total de unidades residenciales")

                if c.get("ordenanzas_mayor_altura"):
                    st.markdown('<div class="section-title">Ordenanzas para Mayor Altura</div>', unsafe_allow_html=True)
                    for o in c["ordenanzas_mayor_altura"]:
                        st.markdown(f'<div class="alert-gold">⚖️ {o}</div>', unsafe_allow_html=True)
                if c.get("observaciones"):
                    st.markdown('<div class="section-title">Observaciones</div>', unsafe_allow_html=True)
                    for obs in c["observaciones"]:
                        st.markdown(f"• {obs}")
                if c.get("metodologia"):
                    with st.expander("Ver metodología de cálculo"):
                        st.write(c["metodologia"])

        # ── TAB 3: FINANCIERO ────────────────────────────
        with tabs[2]:
            if not c:
                st.markdown('<div class="alert-legal">Genera el análisis primero.</div>', unsafe_allow_html=True)
            else:
                fi     = st.session_state.financ_inputs or {}
                m_data = MERCADO[zona_sel]

                col_s1, col_s2 = st.columns([3, 1])
                with col_s1:
                    tasa = st.slider("Tasa financiamiento bancario (%)", 0.0, 15.0,
                                     float(fi.get("tasa_financ", 7.0)), step=0.5,
                                     help="Costo anual del crédito constructor")
                with col_s2:
                    st.metric("Velocidad de mercado", f"{m_data.get('velocidad_venta', 1.0):.2f} und/mes",
                              help="Absorción promedio del mercado en la zona")

                fin_run = {
                    "costo_terreno":      fi.get("costo_terreno", 0),
                    "costo_construccion": fi.get("costo_construccion", m_data["costo_construccion"]),
                    "costo_sotano_m2":    fi.get("costo_sotano_m2", 450),
                    "fee_constructora":   fi.get("fee_constructora", 10.0),
                    "tasa_ir":            fi.get("tasa_ir", 29.5),
                    "include_alcabala":   fi.get("include_alcabala", True),
                    "include_dd":         fi.get("include_dd", True),
                    "precio_venta_m2":    fi.get("precio_venta_m2", m_data["precio_2br"]),
                    "precio_estac":       m_data["precio_estac"],
                    "precio_deposito":    m_data["precio_deposito"],
                    "tasa_financ":        tasa,
                    "nombre_proyecto":    st.session_state.get("nombre_proyecto", ""),
                }
                result = calcular_financiero(c, fin_run, zona_sel)
                st.session_state.financ = result
                r = result["resumen"]

                # ── Métricas clave destacadas ─────────────
                _mg  = r["margen_pct"]
                _tir = r["tir_anual_pct"]
                _roi = r["roi_pct"]
                _mg_c  = "#1A4731" if _mg  >= 20 else ("#7A4F1A" if _mg  >= 12 else "#7A1A1A")
                _tir_c = "#1A4731" if _tir >= 15 else ("#7A4F1A" if _tir >= 10 else "#7A1A1A")
                _roi_c = "#1A4731" if _roi >= 20 else ("#7A4F1A" if _roi >= 12 else "#7A1A1A")
                st.markdown(f"""
                <div style="background:#E8F5EE;border:1px solid #6BAE90;border-left:4px solid #1A4731;
                            border-radius:8px;padding:16px 24px;margin-bottom:16px;">
                  <div style="font-size:9px;color:#1A4731;letter-spacing:3px;text-transform:uppercase;
                              font-weight:700;margin-bottom:12px;">Métricas Determinantes del Proyecto</div>
                  <div style="display:flex;gap:32px;flex-wrap:wrap;align-items:flex-end;">
                    <div>
                      <div style="font-size:10px;color:#4A5568;font-weight:600;text-transform:uppercase;
                                  letter-spacing:1px;margin-bottom:2px;">Margen Neto post-IR</div>
                      <div style="font-size:32px;font-weight:800;color:{_mg_c};letter-spacing:-1px;">{_mg:.1f}%</div>
                      <div style="font-size:10px;color:#7A9A80;">Ref. óptimo: ≥ 20%</div>
                    </div>
                    <div style="width:1px;background:#6BAE90;opacity:0.4;align-self:stretch;"></div>
                    <div>
                      <div style="font-size:10px;color:#4A5568;font-weight:600;text-transform:uppercase;
                                  letter-spacing:1px;margin-bottom:2px;">TIR Anual Estimada</div>
                      <div style="font-size:32px;font-weight:800;color:{_tir_c};letter-spacing:-1px;">{_tir:.1f}%</div>
                      <div style="font-size:10px;color:#7A9A80;">Ref. óptimo: ≥ 15%</div>
                    </div>
                    <div style="width:1px;background:#6BAE90;opacity:0.4;align-self:stretch;"></div>
                    <div>
                      <div style="font-size:10px;color:#4A5568;font-weight:600;text-transform:uppercase;
                                  letter-spacing:1px;margin-bottom:2px;">ROI</div>
                      <div style="font-size:32px;font-weight:800;color:{_roi_c};letter-spacing:-1px;">{_roi:.1f}%</div>
                      <div style="font-size:10px;color:#7A9A80;">Ref. óptimo: ≥ 20%</div>
                    </div>
                    <div style="width:1px;background:#6BAE90;opacity:0.4;align-self:stretch;"></div>
                    <div>
                      <div style="font-size:10px;color:#4A5568;font-weight:600;text-transform:uppercase;
                                  letter-spacing:1px;margin-bottom:2px;">Utilidad Neta</div>
                      <div style="font-size:28px;font-weight:800;color:#1A4731;letter-spacing:-0.5px;">{fmt_usd(r["utilidad_neta"])}</div>
                      <div style="font-size:10px;color:#7A9A80;">post-impuestos</div>
                    </div>
                  </div>
                </div>""", unsafe_allow_html=True)

                # ── KPIs secundarios ──────────────────────
                st.markdown('<div class="section-title">Detalle de Indicadores</div>', unsafe_allow_html=True)
                col1, col2, col3, col4, col5, col6 = st.columns(6)
                col1.metric("Ingresos brutos",   fmt_usd(r["ingresos_brutos"]))
                col2.metric("Utilidad bruta",    fmt_usd(r["utilidad_bruta"]),  delta=f"{r['margen_bruto_pct']}% bruto")
                col3.metric(f"IR ({r['ir_pct']}%)", fmt_usd(r["costo_ir"]),    help="Impuesto a la Renta 29.5%")
                col4.metric("Utilidad neta",     fmt_usd(r["utilidad_neta"]),  delta=f"{r['margen_pct']}% neto")
                col5.metric("ROI / TIR",         f"{r['roi_pct']}% / {r['tir_anual_pct']}%")
                col6.metric("Break-even m²",     f"${r['be_precio_m2']:,}",    help="Precio mínimo/m² para cubrir todos los costos")

                # ── Viabilidad del proyecto ──────────────────────────
                _tit = r["tit_pct"]
                if _mg >= 20 and _tir >= 15:
                    _perfil = ("VIABILIDAD ALTA", "#1A4731", "#E8F5EE", "#6BAE90",
                               "Margen y TIR dentro de parámetros óptimos — proyecto viable para desarrollo")
                elif _mg >= 12 and _tir >= 10:
                    _perfil = ("VIABILIDAD MEDIA", "#7A5500", "#FFF8E6", "#E8C55A",
                               "Parámetros aceptables — revisar estructura de costos y precio de venta")
                else:
                    _perfil = ("VIABILIDAD BAJA", "#7A1A1A", "#FDECEA", "#E87070",
                               "Margen o TIR por debajo de umbrales mínimos — proyecto requiere revisión")
                st.markdown(
                    f'<div style="background:{_perfil[2]};border:1px solid {_perfil[3]};border-left:4px solid {_perfil[1]};'
                    f'border-radius:6px;padding:12px 20px;margin:8px 0 16px;display:flex;align-items:center;gap:20px;">'
                    f'<div><div style="font-size:9px;color:{_perfil[1]};letter-spacing:2px;font-weight:700;text-transform:uppercase;">Perfil de Inversión</div>'
                    f'<div style="font-size:18px;font-weight:800;color:{_perfil[1]};letter-spacing:1px;margin-top:2px;">{_perfil[0]}</div></div>'
                    f'<div style="width:1px;background:{_perfil[3]};opacity:0.5;align-self:stretch;"></div>'
                    f'<div style="font-size:11px;color:{_perfil[1]};opacity:0.9;">{_perfil[4]}</div>'
                    f'<div style="margin-left:auto;text-align:right;">'
                    f'<div style="font-size:9px;color:{_perfil[1]};opacity:0.7;letter-spacing:1px;">TIT (Incidencia Terreno)</div>'
                    f'<div style="font-size:16px;font-weight:700;color:{_perfil[1]};">{_tit:.1f}% / ingresos</div>'
                    f'</div></div>',
                    unsafe_allow_html=True
                )

                # ── Escenario con banco ───────────────────
                st.markdown('<div class="section-title">Escenario con Financiamiento Bancario</div>', unsafe_allow_html=True)
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("Gasto financiero",     fmt_usd(r["costo_financiero"]))
                col2.metric("Costo total c/banco",  fmt_usd(r["costo_total_con_financ"]))
                col3.metric("Utilidad neta c/banco", fmt_usd(r["utilidad_con_financ"]), delta=f"{r['margen_con_financ_pct']}% neto")
                col4.metric("TIR anual est.",        f"{r['tir_anual_pct']}%")

                # ── Timeline ─────────────────────────────
                st.markdown('<div class="section-title">Timeline Estimado</div>', unsafe_allow_html=True)
                col1, col2, col3 = st.columns(3)
                col1.metric("Meses de obra",          f"{r['meses_obra']} meses")
                col2.metric("Meses de ventas",         f"{r['meses_venta']} meses",
                            help=f"A {m_data.get('velocidad_venta',1.0):.2f} und/mes (ASEI 2024)")
                col3.metric("Duración total proyecto", f"{r['meses_proyecto']} meses")

                # ── Detalle ingresos / costos + tipologías ─
                col1, col2 = st.columns(2)
                _pvm = fin_run.get("precio_venta_m2", m_data["precio_2br"])
                _pe  = m_data["precio_estac"]
                _pd  = m_data["precio_deposito"]
                with col1:
                    st.markdown('<div class="section-title">Ingresos</div>', unsafe_allow_html=True)
                    for k, v in result["detalle_ingresos"].items():
                        row_item(k, fmt_usd(v), highlight="TOTAL" in k)

                    # ── Desglose de tipologías ────────────
                    _unidades = c.get("unidades") or []
                    if _unidades:
                        NAV = "#1E2D3D"; BRD = "#D8D4CC"
                        _th = f'style="background:{NAV};color:#fff;padding:7px 10px;font-size:10px;font-weight:700;letter-spacing:0.5px;text-align:left;border:1px solid {BRD};"'
                        _tr = f'style="background:{NAV};color:#fff;padding:7px 10px;font-size:10px;font-weight:700;letter-spacing:0.5px;text-align:right;border:1px solid {BRD};"'
                        _td = f'style="padding:6px 10px;font-size:11px;color:{NAV};border:1px solid {BRD};"'
                        _tv = f'style="padding:6px 10px;font-size:11px;color:{NAV};text-align:right;border:1px solid {BRD};"'
                        _tf = f'style="padding:7px 10px;font-size:11px;font-weight:700;color:{NAV};border:1px solid {BRD};"'
                        _tfv = f'style="padding:7px 10px;font-size:11px;font-weight:700;color:{NAV};text-align:right;border:1px solid {BRD};"'
                        _tbl = (f'<div style="margin-top:14px;">'
                                f'<div style="font-size:9px;color:#B8904A;letter-spacing:2px;font-weight:700;'
                                f'text-transform:uppercase;padding:10px 0 6px;">Desglose por Tipología</div>'
                                f'<table style="border-collapse:collapse;width:100%;">'
                                f'<thead><tr>'
                                f'<th {_th}>Tipología</th>'
                                f'<th {_tr}>Unds.</th>'
                                f'<th {_tr}>Área m²</th>'
                                f'<th {_tr}>Precio/und</th>'
                                f'<th {_tr}>Subtotal</th>'
                                f'</tr></thead><tbody>')
                        for _u in _unidades:
                            _tipo = _u.get("tipo", "—")
                            _cant = _u.get("cantidad", 0)
                            _am2  = _u.get("area_m2", 0)
                            _pund = _am2 * _pvm
                            _sub  = _cant * _pund
                            _tbl += (f'<tr>'
                                     f'<td {_td}>{_tipo}</td>'
                                     f'<td {_tv}>{_cant}</td>'
                                     f'<td {_tv}>{_am2:.0f}</td>'
                                     f'<td {_tv}>${_pund:,.0f}</td>'
                                     f'<td {_tv}>${_sub:,.0f}</td>'
                                     f'</tr>')
                        _n_estac = c.get("estac_total", 0)
                        _n_dep   = c.get("depositos_total", 0)
                        if _n_estac:
                            _tbl += (f'<tr style="background:#F5F2ED !important;">'
                                     f'<td {_td}>Estacionamientos</td>'
                                     f'<td {_tv}>{_n_estac}</td>'
                                     f'<td {_tv}>—</td>'
                                     f'<td {_tv}>${_pe:,.0f}</td>'
                                     f'<td {_tv}>${_n_estac*_pe:,.0f}</td>'
                                     f'</tr>')
                        if _n_dep:
                            _tbl += (f'<tr style="background:#F5F2ED !important;">'
                                     f'<td {_td}>Depósitos</td>'
                                     f'<td {_tv}>{_n_dep}</td>'
                                     f'<td {_tv}>—</td>'
                                     f'<td {_tv}>${_pd:,.0f}</td>'
                                     f'<td {_tv}>${_n_dep*_pd:,.0f}</td>'
                                     f'</tr>')
                        _tbl += (f'<tr>'
                                 f'<td {_tf}>TOTAL</td>'
                                 f'<td {_tfv}>{sum(u.get("cantidad",0) for u in _unidades)}</td>'
                                 f'<td {_tfv}>—</td>'
                                 f'<td {_tfv}>—</td>'
                                 f'<td {_tfv}>${r["ingresos_brutos"]:,.0f}</td>'
                                 f'</tr>')
                        _tbl += '</tbody></table></div>'
                        st.markdown(_tbl, unsafe_allow_html=True)

                with col2:
                    st.markdown('<div class="section-title">Costos</div>', unsafe_allow_html=True)
                    for k, v in result["detalle_costos"].items():
                        if k.startswith("──"):
                            st.markdown(f'<div style="font-size:9px;color:#B8904A;letter-spacing:2px;font-weight:700;padding:10px 0 4px 14px;text-transform:uppercase;">{k.replace("──","").strip()}</div>', unsafe_allow_html=True)
                        else:
                            row_item(k, fmt_usd(v), highlight="TOTAL" in k or "SUBTOTAL" in k)

                # ── Valor estimado de compra del terreno ──
                st.markdown('<div class="section-title">Valor Estimado de Compra del Terreno</div>', unsafe_allow_html=True)
                _precio_actual = fi.get("costo_terreno", 0)
                _v20 = r.get("max_terreno_20pct", 0)
                _v15 = r.get("max_terreno_15pct", 0)
                _v12 = r.get("max_terreno_12pct", 0)
                # Determinar en qué zona está el precio actual
                if _precio_actual <= _v20:
                    _zona_actual = ("ZONA ÓPTIMA", "#1A4731", "#E8F5EE", "#6BAE90")
                elif _precio_actual <= _v15:
                    _zona_actual = ("ZONA ACEPTABLE", "#7A5500", "#FFF8E6", "#E8C55A")
                elif _precio_actual <= _v12:
                    _zona_actual = ("ZONA DE RIESGO", "#7A1A1A", "#FDECEA", "#E87070")
                else:
                    _zona_actual = ("PRECIO ELEVADO — INVIABLE", "#5A1A1A", "#FDE8E8", "#C84040")

                _ratio = r["ratio_terreno_pct"]
                st.markdown(
                    f'<div style="background:#FDFAF6;border:1px solid #D8D4CC;border-radius:8px;padding:20px 24px;margin-bottom:16px;">'
                    f'<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px;margin-bottom:16px;">'
                    f'<div style="background:#E8F5EE;border:1px solid #6BAE90;border-left:4px solid #1A4731;border-radius:6px;padding:14px 16px;">'
                    f'<div style="font-size:9px;color:#1A4731;letter-spacing:2px;font-weight:700;text-transform:uppercase;margin-bottom:6px;">Valor Óptimo</div>'
                    f'<div style="font-size:9px;color:#4A6A54;margin-bottom:8px;">Margen neto ≥ 20%</div>'
                    f'<div style="font-size:20px;font-weight:800;color:#1A4731;">{fmt_usd(_v20)}</div>'
                    f'<div style="font-size:10px;color:#4A6A54;margin-top:4px;">Compra recomendada</div>'
                    f'</div>'
                    f'<div style="background:#FFF8E6;border:1px solid #E8C55A;border-left:4px solid #7A5500;border-radius:6px;padding:14px 16px;">'
                    f'<div style="font-size:9px;color:#7A5500;letter-spacing:2px;font-weight:700;text-transform:uppercase;margin-bottom:6px;">Valor Aceptable</div>'
                    f'<div style="font-size:9px;color:#7A6030;margin-bottom:8px;">Margen neto 15–20%</div>'
                    f'<div style="font-size:20px;font-weight:800;color:#7A5500;">{fmt_usd(_v15)}</div>'
                    f'<div style="font-size:10px;color:#7A6030;margin-top:4px;">Negociar bajo este techo</div>'
                    f'</div>'
                    f'<div style="background:#FDECEA;border:1px solid #E87070;border-left:4px solid #7A1A1A;border-radius:6px;padding:14px 16px;">'
                    f'<div style="font-size:9px;color:#7A1A1A;letter-spacing:2px;font-weight:700;text-transform:uppercase;margin-bottom:6px;">Límite de Riesgo</div>'
                    f'<div style="font-size:9px;color:#8A3030;margin-bottom:8px;">Margen neto 12–15%</div>'
                    f'<div style="font-size:20px;font-weight:800;color:#7A1A1A;">{fmt_usd(_v12)}</div>'
                    f'<div style="font-size:10px;color:#8A3030;margin-top:4px;">Por encima → no viable</div>'
                    f'</div>'
                    f'</div>'
                    f'<div style="background:{_zona_actual[3]}22;border:1px solid {_zona_actual[3]};border-radius:6px;padding:10px 16px;display:flex;align-items:center;gap:16px;">'
                    f'<div style="font-size:11px;color:{_zona_actual[1]};font-weight:700;">Precio ingresado: {fmt_usd(_precio_actual)}</div>'
                    f'<div style="width:1px;background:{_zona_actual[3]};opacity:0.5;height:18px;"></div>'
                    f'<div style="font-size:11px;color:{_zona_actual[1]};font-weight:800;letter-spacing:1px;text-transform:uppercase;">{_zona_actual[0]}</div>'
                    f'<div style="margin-left:auto;font-size:10px;color:{_zona_actual[1]};">Ratio terreno/ingresos: {_ratio}%&nbsp;·&nbsp;Ref. óptima: 15–25%</div>'
                    f'</div>'
                    f'</div>',
                    unsafe_allow_html=True
                )

                # ── Matriz de sensibilidad ────────────────
                st.markdown('<div class="section-title">Matriz de Sensibilidad — Margen %</div>', unsafe_allow_html=True)
                st.caption("Impacto en margen neto ante variaciones de precio de venta (filas) y costo de construcción (columnas)")
                df_sens = calcular_sensibilidad(c, fin_run, zona_sel)

                # Renderizar como HTML con colores por umbral
                def _cell_color(val_str):
                    try:
                        v = float(val_str.strip("%"))
                        if v >= 20:   return "#E8F5EE", "#1A5C32"  # verde
                        elif v >= 12: return "#FFF8E6", "#7A5500"  # amarillo
                        else:         return "#FDECEA", "#7A1A1A"  # rojo
                    except Exception:
                        return "#FFFFFF", "#1E2D3D"

                NAV_S  = "#1E2D3D"
                BORD_S = "#D8D4CC"
                hdr_style = f'style="background:{NAV_S};color:#fff;padding:8px 14px;font-size:11px;font-weight:600;text-align:center;border:1px solid {BORD_S};"'
                lbl_style = f'style="background:#F0EDE8;color:{NAV_S};padding:8px 14px;font-size:11px;font-weight:700;border:1px solid {BORD_S};white-space:nowrap;"'

                sens_html = f'<table style="border-collapse:collapse;width:100%;margin-bottom:8px;"><thead><tr><th {hdr_style}></th>'
                for col in df_sens.columns:
                    sens_html += f'<th {hdr_style}>{col}</th>'
                sens_html += '</tr></thead><tbody>'
                for row_lbl, row in df_sens.iterrows():
                    sens_html += f'<tr><td {lbl_style}>{row_lbl}</td>'
                    for val in row:
                        bg, fg = _cell_color(str(val))
                        sens_html += (f'<td style="background:{bg} !important;color:{fg} !important;padding:8px 14px;'
                                      f'font-size:12px;font-weight:700;text-align:center;'
                                      f'border:1px solid {BORD_S};">{val}</td>')
                    sens_html += '</tr>'
                sens_html += '</tbody></table>'
                st.markdown(sens_html, unsafe_allow_html=True)
                st.caption("Verde = margen ≥ 20% · Amarillo = 12–20% · Rojo = < 12%")

                # ── Comparador de Escenarios ──────────────
                st.markdown("---")
                st.markdown('<div class="section-title">Comparador de Escenarios</div>', unsafe_allow_html=True)
                st.caption("Modifica precio de venta, costo de construcción o terreno para ver el impacto lado a lado")

                _ecc1, _ecc2, _ecc3 = st.columns(3)
                with _ecc1:
                    st.markdown(
                        '<div style="background:#1E2D3D;border-radius:8px;padding:10px 14px;margin-bottom:6px;">'
                        '<div style="font-size:11px;font-weight:700;color:#B8904A;letter-spacing:1.5px;text-transform:uppercase;">Escenario 1 — BASE</div>'
                        '<div style="font-size:10px;color:rgba(255,255,255,0.45);margin-top:2px;">Análisis actual</div>'
                        '</div>', unsafe_allow_html=True)
                    st.markdown(f'<div style="font-size:12px;color:#5A6A7A;margin-top:2px;">Precio: <b style="color:#1E2D3D;">${fin_run["precio_venta_m2"]:,}/m²</b></div>', unsafe_allow_html=True)
                    st.markdown(f'<div style="font-size:12px;color:#5A6A7A;">Construcción: <b style="color:#1E2D3D;">${fin_run["costo_construccion"]:,}/m²</b></div>', unsafe_allow_html=True)
                    st.markdown(f'<div style="font-size:12px;color:#5A6A7A;">Terreno: <b style="color:#1E2D3D;">${fin_run["costo_terreno"]:,.0f}</b></div>', unsafe_allow_html=True)

                with _ecc2:
                    _e2n = st.text_input("Nombre", value="Optimista", key="esc2_n", label_visibility="collapsed",
                                         placeholder="Escenario 2 — nombre")
                    st.caption(f"**{_e2n or 'Escenario 2'}**")
                    _e2p = st.number_input("Precio venta m²", 800, 8000,
                                           min(max(int(fin_run["precio_venta_m2"] * 1.10), 800), 8000), 50,
                                           key="esc2_p", help="Precio de venta por m² vendible")
                    _e2c = st.number_input("Costo construcción m²", 400, 3000,
                                           int(fin_run["costo_construccion"]), 50, key="esc2_c")
                    _e2t = st.number_input("Terreno ($)", 0, 50_000_000,
                                           int(fin_run["costo_terreno"]), 5000, format="%d", key="esc2_t")

                with _ecc3:
                    _e3n = st.text_input("Nombre", value="Conservador", key="esc3_n", label_visibility="collapsed",
                                         placeholder="Escenario 3 — nombre")
                    st.caption(f"**{_e3n or 'Escenario 3'}**")
                    _e3p = st.number_input("Precio venta m²", 800, 8000,
                                           min(max(int(fin_run["precio_venta_m2"] * 0.90), 800), 8000), 50,
                                           key="esc3_p")
                    _e3c = st.number_input("Costo construcción m²", 400, 3000,
                                           min(int(fin_run["costo_construccion"] * 1.05), 3000), 50, key="esc3_c")
                    _e3t = st.number_input("Terreno ($)", 0, 50_000_000,
                                           int(fin_run["costo_terreno"]), 5000, format="%d", key="esc3_t")

                # Calcular los 3 escenarios
                _esc_all = [
                    ("Base",             fin_run["precio_venta_m2"], fin_run["costo_construccion"], fin_run["costo_terreno"]),
                    (_e2n or "Optimista",    _e2p, _e2c, _e2t),
                    (_e3n or "Conservador",  _e3p, _e3c, _e3t),
                ]
                _esc_res = []
                for _en, _ep, _ecv, _et in _esc_all:
                    _fin_e = {**fin_run, "precio_venta_m2": _ep, "costo_construccion": _ecv, "costo_terreno": _et}
                    _r_e   = calcular_financiero(c, _fin_e, zona_sel)["resumen"]
                    _esc_res.append((_en, _ep, _ecv, _et, _r_e))

                # Tabla comparativa
                def _esc_bg(val, t1, t2):
                    if val >= t1: return "#E8F5EE", "#1A5C32"
                    if val >= t2: return "#FFF8E6", "#7A5500"
                    return "#FDECEA", "#7A1A1A"

                _BRD = "#D8D4CC"
                _NH  = "#1E2D3D"
                _tbl = (f'<table style="border-collapse:collapse;width:100%;margin-top:14px;">'
                        f'<thead><tr>'
                        f'<th style="background:{_NH};color:#fff;padding:8px 14px;font-size:11px;font-weight:600;text-align:left;border:1px solid {_BRD};min-width:170px;">Métrica</th>')
                for _en, *_ in _esc_res:
                    _is_base = _en == "Base"
                    _hbg = "#2A3D52" if _is_base else _NH
                    _tbl += f'<th style="background:{_hbg};color:#fff;padding:8px 14px;font-size:11px;font-weight:600;text-align:center;border:1px solid {_BRD};">{_en}</th>'
                _tbl += '</tr></thead><tbody>'

                _metricas = [
                    ("Precio venta m²",    lambda e: f"${e[1]:,}",                                    None,  None),
                    ("Costo construcción", lambda e: f"${e[2]:,}/m²",                                 None,  None),
                    ("Terreno",            lambda e: f"${e[3]:,.0f}",                                  None,  None),
                    (None, None, None, None),
                    ("Ingresos brutos",    lambda e: f"${e[4]['ingresos_brutos']:,.0f}",               None,  None),
                    ("Costo total",        lambda e: f"${e[4]['costo_total_con_financ']:,.0f}",        None,  None),
                    ("Utilidad neta",      lambda e: f"${e[4]['utilidad_neta']:,.0f}",                 None,  None),
                    ("Margen neto",        lambda e: f"{e[4]['margen_pct']:.1f}%",                    "margen_pct",    (20, 12)),
                    ("TIR anual",          lambda e: f"{e[4]['tir_anual_pct']:.1f}%",                 "tir_anual_pct", (15, 10)),
                    ("ROI",                lambda e: f"{e[4]['roi_pct']:.1f}%",                       "roi_pct",       (20, 12)),
                    ("Break-even m²",      lambda e: f"${e[4]['be_precio_m2']:,}",                    None,  None),
                    ("TIT (terreno/ingr.)",lambda e: f"{e[4]['tit_pct']:.1f}%",                       None,  None),
                ]
                _lbl_sty = f'style="background:#F0EDE8;color:{_NH};padding:7px 14px;font-size:11px;font-weight:700;border:1px solid {_BRD};"'
                _sep_sty = f'colspan="{len(_esc_res)+1}" style="background:#E8E4DC;height:1px;padding:0;border:1px solid {_BRD};"'
                for _row in _metricas:
                    _rl, _rfn, _rfield, _rthresh = _row
                    if _rl is None:
                        _tbl += f'<tr><td {_sep_sty}></td></tr>'
                        continue
                    _tbl += f'<tr><td {_lbl_sty}>{_rl}</td>'
                    for _e in _esc_res:
                        _vs = _rfn(_e)
                        if _rfield and _rthresh:
                            _raw = float(_e[4].get(_rfield, 0))
                            _bg, _fg = _esc_bg(_raw, _rthresh[0], _rthresh[1])
                        else:
                            _bg, _fg = "#FFFFFF", _NH
                        _tbl += (f'<td style="background:{_bg};color:{_fg};padding:7px 14px;'
                                 f'font-size:12px;font-weight:700;text-align:center;border:1px solid {_BRD};">{_vs}</td>')
                    _tbl += '</tr>'
                _tbl += '</tbody></table>'
                st.markdown(_tbl, unsafe_allow_html=True)
                st.caption("Margen/TIR/ROI: Verde = óptimo · Amarillo = aceptable · Rojo = revisar")

                # ── Botón de descarga PDF ─────────────────
                st.markdown("---")
                _pdf_col1, _pdf_col2 = st.columns([3, 1])
                with _pdf_col1:
                    st.markdown(
                        '<div style="font-size:11px;color:#7A7268;padding-top:8px;">'
                        'Genera el reporte ejecutivo completo con portada, cabida, '
                        'análisis financiero y estructura de costos.</div>',
                        unsafe_allow_html=True)
                with _pdf_col2:
                    if st.button("⬇ DESCARGAR REPORTE PDF",
                                 use_container_width=True, type="primary",
                                 key="btn_pdf"):
                        with st.spinner("Generando reporte…"):
                            try:
                                _pdf_bytes = generar_pdf_factis(
                                    result=st.session_state.financ,
                                    cabida=st.session_state.cabida,
                                    params=st.session_state.params,
                                    fin_inputs=fin_run,
                                    zona=zona_sel,
                                    legal=st.session_state.get("legal"),
                                )
                                _pdf_nombre = (
                                    f"Factis_{zona_sel.replace(' ','_')}_"
                                    f"{datetime.date.today().strftime('%Y%m%d')}.pdf"
                                )
                                st.download_button(
                                    label="📄 GUARDAR PDF",
                                    data=_pdf_bytes,
                                    file_name=_pdf_nombre,
                                    mime="application/pdf",
                                    use_container_width=True,
                                    key="btn_pdf_dl",
                                )
                            except Exception as _pdf_err:
                                st.error(f"Error al generar PDF: {_pdf_err}")

        # ── TAB 4: COMPETENCIA ───────────────────────────
        with tabs[3]:
            m_data    = MERCADO[zona_sel]
            comp_data = list(st.session_state.get("competencia", []))

            st.markdown('<div class="section-title">Datos del Proyecto vs. Mercado</div>', unsafe_allow_html=True)
            _fi_ref = st.session_state.financ_inputs or {}
            _pv_proj = _fi_ref.get("precio_venta_m2") if _fi_ref.get("precio_venta_m2", 0) > 0 else m_data.get("precio_2br", 0)
            _cc_proj = _fi_ref.get("costo_construccion") if _fi_ref.get("costo_construccion", 0) > 0 else m_data.get("costo_construccion", 0)
            col1, col2, col3 = st.columns(3)
            col1.metric("Precio ingresado / m²",   f"${_pv_proj:,}/m²",
                        delta=f"Ref. zona: ${m_data['precio_2br']:,}/m²" if abs(_pv_proj - m_data['precio_2br']) > 50 else "En línea con mercado")
            col2.metric("Velocidad de absorción",  f"{m_data.get('velocidad_venta',1.0):.2f} und/mes",
                        help="Absorción histórica del mercado en la zona seleccionada (ASEI 2024)")
            col3.metric("Costo construcción ingresado", f"${_cc_proj:,}/m²",
                        delta=f"Ref. zona: ${m_data['costo_construccion']:,}/m²" if abs(_cc_proj - m_data['costo_construccion']) > 25 else "En línea con mercado")

            if not comp_data:
                st.markdown("""
                <div class="alert-legal">
                    Agrega proyectos competidores desde el panel izquierdo (sección <strong>COMPETENCIA / PRECIOS</strong>).
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown('<div class="section-title">Proyectos del Cuadrante</div>', unsafe_allow_html=True)
                df_comp = pd.DataFrame(comp_data).rename(columns={
                    "proyecto": "Proyecto", "precio_m2": "USD/m²",
                    "tipologia": "Tipología", "pisos": "Pisos", "estado": "Estado"
                })
                st.dataframe(df_comp, use_container_width=True, hide_index=True)

                precio_prom = (st.session_state.financ_inputs or {}).get("precio_venta_m2", m_data["precio_2br"])
                nombres = [x["proyecto"] for x in comp_data] + ["Este proyecto"]
                precios = [x["precio_m2"] for x in comp_data] + [precio_prom]
                colores = ["#C8D4DE"] * len(comp_data) + ["#B8904A"]
                fig_bar = go.Figure(go.Bar(
                    x=nombres, y=precios, marker_color=colores,
                    marker_line=dict(width=0),
                    text=[f"${v:,.0f}" for v in precios], textposition="outside",
                    textfont=dict(size=11, family="Inter, sans-serif", color="#1E2D3D"),
                ))
                fig_bar.update_layout(
                    height=380, yaxis_title="USD/m²",
                    title=dict(text="Precio por m² — Competencia vs. este proyecto",
                               font=dict(size=12, color="#9A9080", family="Inter, sans-serif"),
                               x=0, xanchor="left"),
                    margin=dict(t=50, b=20, l=0, r=0),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#1E2D3D", family="Inter, sans-serif"),
                    xaxis=dict(tickfont=dict(size=10), showgrid=False, zeroline=False),
                    yaxis=dict(
                        tickformat="$,.0f", showgrid=True,
                        gridcolor="#E8E4DC", gridwidth=1, zeroline=False,
                    ),
                    bargap=0.35,
                )
                st.plotly_chart(fig_bar, use_container_width=True, config={"displayModeBar": False})

                if c and st.session_state.financ:
                    precio_be = st.session_state.financ["resumen"].get("be_precio_m2", 0)
                    prom_comp = sum(x["precio_m2"] for x in comp_data) / len(comp_data)
                    col1, col2, col3 = st.columns(3)
                    col1.metric("Precio este proyecto",    f"${precio_prom:,}/m²")
                    col2.metric("Promedio competencia",    f"${prom_comp:,.0f}/m²",
                                delta=f"${precio_prom - prom_comp:+,.0f} diferencial")
                    col3.metric("Break-even del proyecto", f"${precio_be:,}/m²",
                                help="Precio mínimo para cubrir todos los costos")

        # ── COMPARABLES DE MERCADO ────────────────────────
        with tabs[3]:
            _sunarp_comps = st.session_state.get("comps_sunarp", [])
            _urb_comps    = list(st.session_state.get("competencia", []))

            if _sunarp_comps or _urb_comps:
                st.markdown("---")
                st.markdown('<div class="section-title">Análisis de Comparables de Mercado</div>',
                            unsafe_allow_html=True)

                # ── Precios de cierre SUNARP ──────────────
                if _sunarp_comps:
                    st.markdown("**Precios de Cierre Verificados — SUNARP**")
                    st.caption("Fuente: partidas registrales · precio inscrito en acto de transferencia")

                    _rows_s = []
                    _precios_cierre_usd = []
                    for r in _sunarp_comps:
                        ut  = r.get("ultima_transferencia") or {}
                        p   = ut.get("precio")
                        mon = ut.get("moneda", "USD")
                        fec = ut.get("fecha", "—")
                        are = r.get("area_m2")
                        pm2 = r.get("precio_m2_estimado")
                        if p and are and not pm2:
                            pm2 = round(p / are, 0) if are > 0 else None
                        if p and mon == "PEN":
                            p_usd = round(p / 3.75, 0)
                            pm2_usd = round(pm2 / 3.75, 0) if pm2 else None
                        else:
                            p_usd   = p
                            pm2_usd = pm2
                        if pm2_usd:
                            _precios_cierre_usd.append(pm2_usd)
                        _rows_s.append({
                            "Predio": r.get("descripcion_predio", f"Comparable {r.get('_idx','')}"),
                            "Área (m²)": f"{are:,.0f}" if are else "—",
                            "Precio cierre": (f"${p_usd:,.0f}" if p_usd and mon != "PEN"
                                              else (f"S/.{p:,.0f}" if p else "—")),
                            "USD/m²": f"${pm2_usd:,.0f}" if pm2_usd else "—",
                            "Fecha": fec,
                            "Tipo acto": ut.get("tipo_acto", "—"),
                            "Obs.": r.get("observaciones", ""),
                        })
                    st.dataframe(pd.DataFrame(_rows_s), use_container_width=True, hide_index=True)

                    if _precios_cierre_usd:
                        _med_cierre = sum(_precios_cierre_usd) / len(_precios_cierre_usd)
                        st.info(f"Precio de cierre promedio (SUNARP): **${_med_cierre:,.0f}/m²**  "
                                f"· Rango: ${min(_precios_cierre_usd):,.0f} – ${max(_precios_cierre_usd):,.0f}/m²")

                # ── Precios de oferta (portales) ──────────
                if _urb_comps:
                    st.markdown("**Precios de Oferta — Portales Inmobiliarios**")
                    st.caption("Fuente: usuario · precios de publicación (expectativa de venta, no precio de cierre)")
                    _precios_oferta = [x["precio_m2"] for x in _urb_comps]
                    _med_oferta = sum(_precios_oferta) / len(_precios_oferta)
                    st.dataframe(
                        pd.DataFrame(_urb_comps).rename(columns={
                            "proyecto": "Proyecto/Referencia", "precio_m2": "USD/m² oferta",
                            "tipologia": "Tipología", "pisos": "Pisos", "estado": "Estado"
                        }),
                        use_container_width=True, hide_index=True
                    )
                    st.info(f"Precio de oferta promedio (portales): **${_med_oferta:,.0f}/m²**")

                # ── Brecha y recomendación ────────────────
                if _sunarp_comps and _urb_comps and _precios_cierre_usd and _precios_oferta:
                    _brecha_pct = ((_med_oferta - _med_cierre) / _med_oferta) * 100 if _med_oferta > 0 else 0
                    st.markdown("---")
                    st.markdown("**Análisis de Brecha**")
                    _bc1, _bc2, _bc3 = st.columns(3)
                    _bc1.metric("Precio oferta promedio",  f"${_med_oferta:,.0f}/m²",
                                help="Media de precios publicados en portales")
                    _bc2.metric("Precio cierre promedio",  f"${_med_cierre:,.0f}/m²",
                                help="Media de precios inscritos en SUNARP")
                    _bc3.metric("Brecha oferta vs. cierre", f"{_brecha_pct:.1f}%",
                                delta=f"El mercado cierra {_brecha_pct:.1f}% por debajo de la oferta",
                                delta_color="inverse")
                    st.success(
                        f"Valor de mercado recomendado para el análisis: **${_med_cierre:,.0f}/m²** "
                        f"(basado en precios de cierre SUNARP verificados)"
                    )
                    st.caption(
                        "Usar precio de oferta sin ajuste sobrevalúa el activo. "
                        "El precio de cierre SUNARP refleja el valor al que efectivamente se concretaron operaciones."
                    )

            else:
                st.markdown("""
                <div class="alert-legal">
                    Agrega comparables: sube partidas SUNARP desde el panel izquierdo (sección
                    <strong>COMPARABLES SUNARP</strong>) y/o proyectos en <strong>COMPETENCIA / PRECIOS</strong>.
                </div>""", unsafe_allow_html=True)

        # ── TAB 5: FLUJO DE CAJA ─────────────────────────
        with tabs[4]:
            if not c or not st.session_state.financ:
                st.markdown('<div class="alert-legal">Genera el análisis primero.</div>', unsafe_allow_html=True)
            else:
                fi        = st.session_state.financ_inputs or {}
                result_fl = st.session_state.financ
                fin_fl    = fi

                with st.spinner("Calculando DCF mensual…"):
                    df_fl, _, _, _, _, esc = generar_flujo(c, result_fl, fin_fl, zona_sel)

                sb  = esc["sin_banco"]
                cb  = esc["con_banco"]
                NAV_FL  = "#1E2D3D"
                BORD_FL = "#D8D4CC"
                ALT_FL  = "#F2EFE9"
                GRN     = "#1A5C32"
                RED     = "#C0392B"
                meses   = df_fl["Mes"].tolist()

                # ── Bloque comparativo escenarios ──────────
                st.markdown('<div class="section-title">Escenarios — Sin Banco vs Con Banco</div>',
                            unsafe_allow_html=True)

                _be_sin = f"Mes {sb['mes_be']}" if sb["mes_be"] else "—"
                _be_con = f"Mes {cb['mes_be']}" if cb["mes_be"] else "—"
                _tir_sin = f"{sb['tir']}%" if sb["tir"] is not None else "—"
                _tir_con = f"{cb['tir']}%" if cb["tir"] is not None else "—"
                _exp_sin = fmt_usd(abs(sb["max_exp"]))
                _exp_con = fmt_usd(abs(cb["max_exp"]))
                _delta_tir = (
                    f"+{cb['tir'] - sb['tir']:.1f}pp apalancamiento"
                    if (cb["tir"] is not None and sb["tir"] is not None and cb["tir"] > sb["tir"])
                    else ""
                )
                # Pre-build span to avoid nested f-string quote conflict (Python < 3.12)
                _delta_span = (
                    '<span style="font-size:10px;color:#B8904A;">(' + _delta_tir + ")</span>"
                    if _delta_tir else ""
                )

                _td  = f'padding:7px 14px;font-size:12px;border:1px solid {BORD_FL};'
                _interes_str  = fmt_usd(cb["interes_total"])
                _igv_str      = fmt_usd(cb["igv_credito"])
                _horizonte    = len(df_fl) - 1
                _cmp_html = (
                    '<table style="border-collapse:collapse;width:100%;margin-bottom:16px;"><thead><tr>'
                    + f'<th style="background:{NAV_FL};color:#fff;padding:8px 14px;font-size:11px;font-weight:600;text-align:left;border:1px solid {BORD_FL};">Métrica</th>'
                    + f'<th style="background:{NAV_FL};color:#fff;padding:8px 14px;font-size:11px;font-weight:600;text-align:right;border:1px solid {BORD_FL};">Sin Banco (100% Equity)</th>'
                    + f'<th style="background:{NAV_FL};color:#fff;padding:8px 14px;font-size:11px;font-weight:600;text-align:right;border:1px solid {BORD_FL};">Con Banco (Linea 40% obra)</th>'
                    + '</tr></thead><tbody>'
                    + f'<tr style="background:{ALT_FL};">'
                    + f'<td style="{_td}">TIR Equity anual</td>'
                    + f'<td style="{_td}font-weight:700;text-align:right;color:{GRN};">{_tir_sin}</td>'
                    + f'<td style="{_td}font-weight:700;text-align:right;color:{GRN};">{_tir_con} {_delta_span}</td>'
                    + '</tr>'
                    + '<tr>'
                    + f'<td style="{_td}">Maxima exposicion equity</td>'
                    + f'<td style="{_td}text-align:right;color:{RED};">{_exp_sin}</td>'
                    + f'<td style="{_td}text-align:right;color:{RED};">{_exp_con}</td>'
                    + '</tr>'
                    + f'<tr style="background:{ALT_FL};">'
                    + f'<td style="{_td}">Breakeven (flujo acum.)</td>'
                    + f'<td style="{_td}text-align:right;">{_be_sin}</td>'
                    + f'<td style="{_td}text-align:right;">{_be_con}</td>'
                    + '</tr>'
                    + '<tr>'
                    + f'<td style="{_td}">Gasto financiero banco</td>'
                    + f'<td style="{_td}text-align:right;">--</td>'
                    + f'<td style="{_td}text-align:right;">{_interes_str}</td>'
                    + '</tr>'
                    + f'<tr style="background:{ALT_FL};">'
                    + f'<td style="{_td}">IGV credito fiscal (recuperado)</td>'
                    + f'<td style="{_td}text-align:right;color:{GRN};">{_igv_str}</td>'
                    + f'<td style="{_td}text-align:right;color:{GRN};">{_igv_str}</td>'
                    + '</tr>'
                    + '<tr>'
                    + f'<td style="{_td}">Horizonte del modelo</td>'
                    + f'<td style="{_td}text-align:right;" colspan="2">{_horizonte} meses</td>'
                    + '</tr>'
                    + '</tbody></table>'
                )
                st.markdown(_cmp_html, unsafe_allow_html=True)

                # ── Gráfico: Curva S construcción ──────────
                st.markdown('<div class="section-title">Curva S — Desembolso Construcción</div>',
                            unsafe_allow_html=True)
                obra_m = cb["obra_mensual"]
                obra_cumsum = []
                _s = 0
                total_obra = sum(obra_m) or 1
                for v in obra_m:
                    _s += v
                    obra_cumsum.append(_s / total_obra * 100)
                obra_x = list(range(3, 3 + len(obra_m)))

                fig_s = go.Figure()
                fig_s.add_trace(go.Bar(
                    x=obra_x, y=[v / 1000 for v in obra_m],
                    name="Desembolso mensual ($K)",
                    marker_color="rgba(184,144,74,0.65)",
                    hovertemplate="Mes %{x}<br>Desembolso: $%{y:,.0f}K<extra></extra>",
                    yaxis="y",
                ))
                fig_s.add_trace(go.Scatter(
                    x=obra_x, y=obra_cumsum,
                    name="Avance acumulado (%)",
                    mode="lines+markers",
                    line=dict(color="#1E2D3D", width=2.5),
                    marker=dict(size=4),
                    hovertemplate="Mes %{x}<br>Avance: %{y:.1f}%<extra></extra>",
                    yaxis="y2",
                ))
                fig_s.update_layout(
                    height=300,
                    barmode="overlay",
                    yaxis=dict(title="Desembolso ($K)", tickformat="$,.0f",
                               showgrid=True, gridcolor="#E8E3DA",
                               tickfont=dict(color="#4A5568", size=10)),
                    yaxis2=dict(title="% Avance acumulado", overlaying="y", side="right",
                                range=[0, 105], ticksuffix="%",
                                tickfont=dict(color="#4A5568", size=10),
                                showgrid=False),
                    xaxis=dict(title="Mes de proyecto", tickfont=dict(color="#4A5568", size=10), showgrid=False),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                                font=dict(size=10, color="#4A5568")),
                    margin=dict(t=30, b=40, l=70, r=70),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#4A5568", size=11, family="Inter, sans-serif"),
                )
                st.plotly_chart(fig_s, use_container_width=True, config={"displayModeBar": False})

                # ── Gráfico: Flujo acumulado comparativo ───
                st.markdown('<div class="section-title">Flujo de Caja Acumulado — Comparativa</div>',
                            unsafe_allow_html=True)

                acum_sin = sb["acum"]
                acum_con = cb["acum"]

                fig_fl = go.Figure()
                fig_fl.add_trace(go.Scatter(
                    x=meses, y=acum_sin,
                    mode="lines", name="Sin banco",
                    line=dict(color="#1E2D3D", width=2.5),
                    hovertemplate="Mes %{x}<br>Sin banco: $%{y:,.0f}<extra></extra>",
                ))
                fig_fl.add_trace(go.Scatter(
                    x=meses, y=acum_con,
                    mode="lines", name="Con banco",
                    line=dict(color="#B8904A", width=2, dash="dash"),
                    hovertemplate="Mes %{x}<br>Con banco: $%{y:,.0f}<extra></extra>",
                ))
                fig_fl.add_hline(y=0, line_color="#AAAAAA", line_width=1.2)
                if sb["mes_be"]:
                    fig_fl.add_vline(x=sb["mes_be"], line_dash="dot", line_color="#1E2D3D",
                                     line_width=1.2,
                                     annotation_text=f" BE sin banco — mes {sb['mes_be']}",
                                     annotation_font=dict(size=10, color="#1E2D3D"),
                                     annotation_position="top left")
                if cb["mes_be"] and cb["mes_be"] != sb["mes_be"]:
                    fig_fl.add_vline(x=cb["mes_be"], line_dash="dot", line_color="#B8904A",
                                     line_width=1.2,
                                     annotation_text=f" BE con banco — mes {cb['mes_be']}",
                                     annotation_font=dict(size=10, color="#B8904A"),
                                     annotation_position="top right")
                fig_fl.update_layout(
                    height=360,
                    yaxis=dict(tickformat="$,.0f", zeroline=False,
                               showgrid=True, gridcolor="#E8E3DA",
                               title=dict(text="USD acumulado", font=dict(color="#4A5568", size=11)),
                               tickfont=dict(color="#4A5568", size=10)),
                    xaxis=dict(title=dict(text="Mes", font=dict(color="#4A5568", size=11)),
                               showgrid=False, tickfont=dict(color="#4A5568", size=10)),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0,
                                font=dict(size=11, color="#4A5568")),
                    margin=dict(t=30, b=40, l=80, r=20),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="#4A5568", size=11, family="Inter, sans-serif"),
                )
                st.plotly_chart(fig_fl, use_container_width=True, config={"displayModeBar": False})

                # ── Tabla mensual detallada ─────────────────
                st.markdown('<div class="section-title">Detalle Mensual</div>', unsafe_allow_html=True)
                _esc_sel = st.radio("Escenario:", ["Sin Banco", "Con Banco"],
                                    horizontal=True, label_visibility="collapsed")
                _flujo_col = "Flujo Sin Banco" if _esc_sel == "Sin Banco" else "Flujo Con Banco"
                _acum_col  = "Acum. Sin Banco"  if _esc_sel == "Sin Banco" else "Acum. Con Banco"

                tbl = ('<table style="border-collapse:collapse;width:100%;margin-bottom:12px;">'
                       '<thead><tr>'
                       + ''.join(
                           f'<th style="background:{NAV_FL};color:#fff;padding:8px 12px;font-size:11px;'
                           f'font-weight:600;text-align:{"right" if idx > 0 else "center"};border:1px solid {BORD_FL};">{h}</th>'
                           for idx, h in enumerate(["Mes", "Flujo Mensual", "Flujo Acumulado",
                                                    "Saldo Deuda" if _esc_sel == "Con Banco" else ""])
                           if h
                       )
                       + '</tr></thead><tbody>')
                for i, row in df_fl.iterrows():
                    bg = ALT_FL if i % 2 == 0 else "#FAFAF8"
                    fm = row[_flujo_col]
                    fa = row[_acum_col]
                    fc = RED if fm < 0 else GRN
                    ac = RED if fa < 0 else GRN
                    sd = row["Saldo Deuda"]
                    tbl += (f'<tr>'
                            f'<td style="background:{bg};padding:6px 12px;font-size:11px;text-align:center;border:1px solid {BORD_FL};color:{NAV_FL};font-weight:600;">{int(row["Mes"])}</td>'
                            f'<td style="background:{bg};padding:6px 12px;font-size:11px;text-align:right;border:1px solid {BORD_FL};color:{fc};font-weight:600;">${fm:,.0f}</td>'
                            f'<td style="background:{bg};padding:6px 12px;font-size:11px;text-align:right;border:1px solid {BORD_FL};color:{ac};font-weight:600;">${fa:,.0f}</td>'
                            + (f'<td style="background:{bg};padding:6px 12px;font-size:11px;text-align:right;border:1px solid {BORD_FL};color:{NAV_FL};">{"$"+f"{sd:,.0f}" if sd > 0 else "—"}</td>'
                               if _esc_sel == "Con Banco" else "")
                            + '</tr>')
                tbl += '</tbody></table>'
                st.markdown(tbl, unsafe_allow_html=True)

                csv = df_fl.to_csv(index=False).encode("utf-8")
                st.download_button("Descargar DCF completo (.csv)", csv, "dcf_mensual.csv", "text/csv",
                                   use_container_width=True)

        # ── TAB 6: LEGAL ─────────────────────────────────
        with tabs[5]:
            st.markdown('<div class="section-title">Due Diligence Legal — Partida Registral &amp; PU/HR</div>',
                        unsafe_allow_html=True)

            tiene_partida = st.session_state.partida_bytes is not None
            tiene_puhr    = st.session_state.puhr_bytes is not None

            if not tiene_partida and not tiene_puhr:
                st.markdown("""
                <div class="alert-legal">
                    Para el análisis legal adjunta la <strong>Partida Registral</strong> y/o el <strong>PU/HR</strong>
                    en el panel izquierdo y luego ejecuta <strong>GENERAR ANÁLISIS</strong>.
                </div>""", unsafe_allow_html=True)
            else:
                docs_disponibles = []
                if tiene_partida: docs_disponibles.append("Partida Registral")
                if tiene_puhr:    docs_disponibles.append("PU/HR")
                st.caption(f"Documentos disponibles: {' · '.join(docs_disponibles)}")

                if st.button("ANALIZAR DOCUMENTOS LEGALES", use_container_width=True, type="primary"):
                    _p_bytes = st.session_state.partida_bytes
                    _u_bytes = st.session_state.puhr_bytes
                    st.session_state.legal = _run_with_retry(
                        lambda _p=_p_bytes, _u=_u_bytes: analizar_legal(_p, _u),
                        "Analizando documentos registrales…",
                    )
                    st.session_state._goto_tab = 5
                    st.rerun()

                lg = st.session_state.legal
                if lg:
                    # ── Semáforo ─────────────────────────────
                    sem = lg.get("semaforo", "amarillo").lower()
                    sem_cfg = {
                        "verde":    ("#1A4731", "#E8F5EE", "SIN ALERTAS CRÍTICAS",   "El inmueble presenta un estado legal favorable para la adquisición."),
                        "amarillo": ("#7A4F1A", "#FFF8EE", "OBSERVACIONES MENORES",  "Existen observaciones que deben verificarse antes de proceder."),
                        "rojo":     ("#7A1A1A", "#FFF0F0", "ALERTAS CRÍTICAS",       "Se detectaron riesgos legales que requieren atención inmediata."),
                    }.get(sem, ("#1E2D3D", "#F5F2ED", "INDETERMINADO", ""))
                    sc, sbg, setiq, _ = sem_cfg

                    st.markdown(f"""
                    <div style="background:{sbg};border:1px solid {sc};border-left:4px solid {sc};
                                border-radius:8px;padding:20px 24px;margin-bottom:20px;
                                box-shadow:0 2px 10px rgba(0,0,0,0.06);">
                        <div style="font-size:9px;letter-spacing:3px;color:{sc};text-transform:uppercase;
                                    font-weight:700;opacity:0.7;margin-bottom:6px;">Estado Legal del Inmueble</div>
                        <div style="font-size:20px;font-weight:700;color:{sc};margin-bottom:10px;">{setiq}</div>
                        <div style="font-size:13px;color:{sc};opacity:0.85;line-height:1.6;">
                            {lg.get('resumen_legal','—')}
                        </div>
                    </div>""", unsafe_allow_html=True)

                    # ── Alertas ──────────────────────────────
                    alertas = lg.get("alertas", [])
                    if alertas:
                        st.markdown('<div class="section-title">Alertas</div>', unsafe_allow_html=True)
                        for al in alertas:
                            icon = "🔴" if sem == "rojo" else ("🟡" if sem == "amarillo" else "🟢")
                            st.markdown(f'<div class="alert-gold">{icon} {al}</div>', unsafe_allow_html=True)

                    # ── Verificación cruzada ─────────────────
                    st.markdown('<div class="section-title">Verificación Cruzada</div>', unsafe_allow_html=True)

                    def _check(ok):
                        if ok is True:  return "✓", "#1A4731"
                        if ok is False: return "✗", "#7A1A1A"
                        return "—", "#9A9080"

                    def _vcard(label, row1_lbl, row1_val, row2_lbl, row2_val, note, icon, col):
                        note_html = ('<div style="font-size:11px;color:#7A4F1A;margin-top:8px;font-style:italic;">' + note + '</div>') if note else ''
                        return (
                            '<div style="background:#FFFFFF;border:1px solid #E4E0D8;border-radius:6px;padding:16px 20px;margin-bottom:10px;box-shadow:0 1px 4px rgba(30,45,61,0.05);">'
                            '<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                            '<div style="flex:1;">'
                            '<div style="font-size:9px;color:#9A9080;letter-spacing:2px;text-transform:uppercase;font-weight:600;margin-bottom:8px;">' + label + '</div>'
                            '<div style="font-size:12px;color:#1E2D3D;margin-bottom:4px;"><strong>' + row1_lbl + ':</strong> ' + str(row1_val) + '</div>'
                            '<div style="font-size:12px;color:#1E2D3D;"><strong>' + row2_lbl + ':</strong> ' + str(row2_val) + '</div>'
                            + note_html
                            + '</div>'
                            '<div style="font-size:28px;color:' + col + ';font-weight:700;margin-left:16px;">' + icon + '</div>'
                            '</div></div>'
                        )

                    # Propietarios con DNI
                    prop_p_raw = lg.get("propietarios_partida") or []
                    prop_h_raw = lg.get("propietarios_puhr") or []

                    def _fmt_propietario(p, fuente):
                        if not p or not isinstance(p, dict):
                            return str(p) if p else "—"
                        nombre = p.get("nombre") or "—"
                        dni    = p.get("dni")
                        pct    = p.get("porcentaje")
                        cond   = p.get("condicion")
                        tipo   = p.get("tipo_doc", "DNI")
                        parts  = [nombre]
                        if pct:  parts.append(f"({pct})")
                        if cond: parts.append(f"[{cond}]")
                        result = " ".join(parts)
                        if dni:
                            result += f' &nbsp;<span style="background:#E8F5EE;color:#1A4731;font-size:10px;font-weight:700;padding:2px 6px;border-radius:3px;border:1px solid #1A4731;">{tipo}: {dni}</span>'
                        else:
                            result += ' &nbsp;<span style="background:#FFF8EE;color:#7A4F1A;font-size:10px;padding:2px 6px;border-radius:3px;border:1px solid #B8904A;">DNI no encontrado</span>'
                        return result

                    if prop_p_raw and isinstance(prop_p_raw[0], dict):
                        prop_p_str = "<br>".join(_fmt_propietario(p, "Partida") for p in prop_p_raw)
                    else:
                        prop_p_str = ", ".join(str(x) for x in prop_p_raw) if prop_p_raw else "—"

                    if prop_h_raw and isinstance(prop_h_raw[0], dict):
                        prop_h_str = "<br>".join(_fmt_propietario(p, "PU/HR") for p in prop_h_raw)
                    else:
                        prop_h_str = ", ".join(str(x) for x in prop_h_raw if x) if prop_h_raw else "—"

                    icon_p, col_p = _check(lg.get("propietarios_coinciden"))
                    note_p = lg.get("diferencias_propietarios", "") or ""
                    note_p_html = ('<div style="font-size:11px;color:#7A4F1A;margin-top:8px;font-style:italic;">' + note_p + '</div>') if note_p else ""
                    st.markdown(
                        '<div style="background:#FFFFFF;border:1px solid #E4E0D8;border-radius:6px;padding:16px 20px;margin-bottom:10px;box-shadow:0 1px 4px rgba(30,45,61,0.05);">'
                        '<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                        '<div style="flex:1;">'
                        '<div style="font-size:9px;color:#9A9080;letter-spacing:2px;text-transform:uppercase;font-weight:600;margin-bottom:8px;">Titularidad / Propietarios</div>'
                        '<div style="font-size:12px;color:#1E2D3D;margin-bottom:6px;"><strong>Partida:</strong><br>' + prop_p_str + '</div>'
                        '<div style="font-size:12px;color:#1E2D3D;"><strong>PU/HR:</strong><br>' + prop_h_str + '</div>'
                        + note_p_html +
                        '</div>'
                        '<div style="font-size:28px;color:' + col_p + ';font-weight:700;margin-left:16px;">' + icon_p + '</div>'
                        '</div></div>',
                        unsafe_allow_html=True
                    )

                    # Dirección
                    dir_p = lg.get("direccion_partida", "—") or "—"
                    dir_h = lg.get("direccion_puhr", "—") or "—"
                    icon_d, col_d = _check(lg.get("direcciones_coinciden"))
                    st.markdown(_vcard(
                        "Ubicación / Dirección",
                        "Partida", dir_p,
                        "PU/HR",   dir_h,
                        lg.get("diferencias_direccion", ""),
                        icon_d, col_d,
                    ), unsafe_allow_html=True)

                    # Área
                    area_r = lg.get("area_registral_m2")
                    area_h_v = lg.get("area_puhr_m2")
                    disc   = lg.get("discrepancia_area_m2")
                    icon_a, col_a = _check(lg.get("areas_coinciden"))
                    disc_note = ("Discrepancia: <strong>" + f"{disc:+.2f} m²</strong>") if disc else ""
                    st.markdown(_vcard(
                        "Área del Inmueble",
                        "Partida", f"{area_r:,.2f} m²" if area_r else "—",
                        "PU/HR",   f"{area_h_v:,.2f} m²" if area_h_v else "—",
                        disc_note,
                        icon_a, col_a,
                    ), unsafe_allow_html=True)

                    # ── Datos PU/HR municipales ───────────────
                    _autoavaluo   = lg.get("valor_autoavaluo")
                    _moneda_av    = lg.get("moneda_autoavaluo") or "PEN"
                    _anio_av      = lg.get("anio_autoavaluo")
                    _clasif_muni  = lg.get("clasificacion_municipal")
                    _cond_sat     = lg.get("condicion_propietario_sat")
                    _uso_predio   = lg.get("uso_predio")
                    if any([_autoavaluo, _clasif_muni, _cond_sat, _uso_predio]):
                        st.markdown('<div class="section-title">Datos Municipales — PU/HR</div>', unsafe_allow_html=True)
                        _mu_cols = st.columns(2)
                        if _autoavaluo:
                            _av_label = f"Autoavalúo {_anio_av}" if _anio_av else "Autoavalúo"
                            _av_val   = f"{_moneda_av} {_autoavaluo:,.0f}" if isinstance(_autoavaluo, (int, float)) else f"{_moneda_av} {_autoavaluo}"
                            _mu_cols[0].metric(_av_label, _av_val)
                        if _clasif_muni:
                            _mu_cols[1].metric("Clasificación Municipal", _clasif_muni)
                        if _cond_sat or _uso_predio:
                            _mu_cols2 = st.columns(2)
                            if _cond_sat:   _mu_cols2[0].metric("Condición (SAT)", _cond_sat)
                            if _uso_predio: _mu_cols2[1].metric("Uso del Predio", _uso_predio)

                    # ── Cargas e Hipotecas ────────────────────
                    hipotecas = lg.get("hipotecas_vigentes", []) or []
                    cargas    = lg.get("cargas_vigentes", []) or []
                    medidas   = lg.get("medidas_cautelares", []) or []
                    anotac    = lg.get("anotaciones_diversas", []) or []

                    if hipotecas or cargas or medidas:
                        st.markdown('<div class="section-title">Cargas, Gravámenes e Hipotecas</div>',
                                    unsafe_allow_html=True)

                        for h in hipotecas:
                            estado = h.get("estado", "vigente")
                            bg = "#FFF0F0" if estado == "vigente" else "#F7F5F1"
                            bl = "#7A1A1A" if estado == "vigente" else "#8A9BAD"
                            st.markdown(f"""
                            <div style="background:{bg};border-left:3px solid {bl};border-radius:0 6px 6px 0;
                                        padding:12px 16px;margin-bottom:8px;">
                                <div style="font-size:10px;color:{bl};letter-spacing:1.5px;text-transform:uppercase;
                                            font-weight:700;margin-bottom:4px;">Hipoteca — {estado.upper()}</div>
                                <div style="font-size:12px;color:#1E2D3D;">
                                    <strong>Acreedor:</strong> {h.get('acreedor','—')} &nbsp;·&nbsp;
                                    <strong>Monto:</strong> {h.get('monto','—')} &nbsp;·&nbsp;
                                    <strong>Inscripción:</strong> {h.get('fecha_inscripcion','—')}
                                    {f" &nbsp;·&nbsp; <strong>Asiento:</strong> {h.get('asiento','')}" if h.get('asiento') else ""}
                                </div>
                            </div>""", unsafe_allow_html=True)

                        for cg in cargas:
                            st.markdown(f"""
                            <div style="background:#FFF8EE;border-left:3px solid #B8904A;border-radius:0 6px 6px 0;
                                        padding:12px 16px;margin-bottom:8px;">
                                <div style="font-size:10px;color:#7A4F1A;letter-spacing:1.5px;text-transform:uppercase;
                                            font-weight:700;margin-bottom:4px;">Carga — {cg.get('tipo','').upper()}</div>
                                <div style="font-size:12px;color:#1E2D3D;">
                                    {cg.get('descripcion','—')}
                                    {f" &nbsp;·&nbsp; <strong>Acreedor:</strong> {cg.get('acreedor','')}" if cg.get('acreedor') else ""}
                                    {f" &nbsp;·&nbsp; <strong>Asiento:</strong> {cg.get('asiento','')}" if cg.get('asiento') else ""}
                                </div>
                            </div>""", unsafe_allow_html=True)

                        for mc in medidas:
                            st.markdown(f"""
                            <div style="background:#FFF0F0;border-left:3px solid #7A1A1A;border-radius:0 6px 6px 0;
                                        padding:12px 16px;margin-bottom:8px;">
                                <div style="font-size:10px;color:#7A1A1A;letter-spacing:1.5px;text-transform:uppercase;
                                            font-weight:700;margin-bottom:4px;">Medida Cautelar — {mc.get('tipo','').upper()}</div>
                                <div style="font-size:12px;color:#1E2D3D;">
                                    {mc.get('descripcion','—')}
                                    {f" &nbsp;·&nbsp; Exp. {mc.get('expediente','')}" if mc.get('expediente') else ""}
                                    {f" &nbsp;·&nbsp; {mc.get('fecha','')}" if mc.get('fecha') else ""}
                                </div>
                            </div>""", unsafe_allow_html=True)
                    else:
                        st.markdown('<div class="section-title">Cargas, Gravámenes e Hipotecas</div>',
                                    unsafe_allow_html=True)
                        st.markdown('<div class="alert-legal">Sin cargas, gravámenes ni hipotecas identificados en los documentos analizados.</div>',
                                    unsafe_allow_html=True)

                    # ── Datos registrales ─────────────────────
                    st.markdown('<div class="section-title">Identificación Registral</div>', unsafe_allow_html=True)
                    col1, col2 = st.columns(2)
                    col1.metric("N° Partida Registral", lg.get("partida_numero") or "—")
                    col2.metric("N° Predio / Contribuyente", lg.get("numero_predio") or "—")

                    if anotac:
                        st.markdown('<div class="section-title">Anotaciones Adicionales</div>', unsafe_allow_html=True)
                        for an in anotac:
                            st.markdown(f'<div class="alert-legal">• {an}</div>', unsafe_allow_html=True)

        # ── TAB 7: RESUMEN ───────────────────────────────
        with tabs[6]:
            # Score de viabilidad
            if c and st.session_state.financ:
                r = st.session_state.financ["resumen"]
                pts, score_10, etiqueta, color_txt, color_bg, recomendacion, score_items = score_viabilidad(r)

                # Score bar helper
                def _bar(v, mx):
                    filled = round(v / mx * 5)
                    return "●" * filled + "○" * (5 - filled)

                items_html = "".join(
                    '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid rgba(0,0,0,0.06);">'
                    + f'<span style="font-size:11px;color:{color_txt};font-weight:500;">{it[0]}</span>'
                    + f'<span style="font-size:11px;color:{color_txt};opacity:0.7;letter-spacing:1px;font-variant-numeric:tabular-nums;">{it[1]}</span>'
                    + f'<span style="font-size:10px;color:{color_txt};opacity:0.5;letter-spacing:2px;">{_bar(it[2], it[3])}</span>'
                    + '</div>'
                    for it in score_items
                )

                st.markdown(f"""
                <div class="score-card" style="background:{color_bg};border-color:{color_txt};
                            display:grid;grid-template-columns:1fr auto;gap:32px;text-align:left;">
                    <div>
                        <div style="font-size:9px;letter-spacing:3px;color:{color_txt};
                                    text-transform:uppercase;font-weight:700;opacity:0.6;margin-bottom:10px;">
                            Evaluación de la Oportunidad
                        </div>
                        <div style="font-size:22px;color:{color_txt};font-weight:700;
                                    letter-spacing:-0.3px;margin-bottom:10px;">
                            {etiqueta}
                        </div>
                        <div style="font-size:12px;color:{color_txt};opacity:0.75;
                                    line-height:1.7;margin-bottom:16px;">
                            {recomendacion}
                        </div>
                        {items_html}
                    </div>
                    <div style="display:flex;flex-direction:column;align-items:center;
                                justify-content:center;min-width:110px;">
                        <div style="font-size:56px;font-weight:700;color:{color_txt};
                                    letter-spacing:-2px;line-height:1;font-variant-numeric:tabular-nums;">
                            {score_10}
                        </div>
                        <div style="font-size:11px;color:{color_txt};opacity:0.5;
                                    letter-spacing:1px;margin-top:4px;">/ 10</div>
                        <div style="font-size:8px;color:{color_txt};opacity:0.4;
                                    letter-spacing:2px;text-transform:uppercase;margin-top:8px;">Score</div>
                    </div>
                </div>""", unsafe_allow_html=True)

            st.markdown('<div class="section-title">Resumen Ejecutivo</div>', unsafe_allow_html=True)

            col1, col2 = st.columns(2)
            with col1:
                st.markdown('<div class="section-title" style="font-size:8px">Datos del Inmueble</div>', unsafe_allow_html=True)
                data_inm = [
                    ("Ubicación",          p.get("ubicacion", "—")),
                    ("Zonificación",       p.get("zonificacion", "—")),
                    ("Área del terreno",   f"{p.get('area_terreno_m2','—')} m²"),
                    ("Frente",             f"{p.get('frente_ml','—')} ml"),
                    ("Altura máxima",      f"{p.get('pisos_max','—')} pisos"),
                    ("Área libre mínima",  f"{p.get('area_libre_min_pct','—')}%"),
                    ("Certificado caduca", p.get("fecha_caducidad","—")),
                ]
                for lbl, val in data_inm:
                    row_item(lbl, str(val))

            with col2:
                if c:
                    at_total = c.get("area_techada_total_m2", 0)
                    av_total = c.get("area_vendible_m2", 0)
                    at_piso  = c.get("area_techada_piso_m2", 0)
                    area_t   = p.get("area_terreno_m2", 1) or 1
                    cos = round(at_piso / area_t * 100, 1) if area_t else 0
                    cus = round(at_total / area_t, 2) if area_t else 0

                    st.markdown('<div class="section-title" style="font-size:8px">Programa Arquitectónico</div>', unsafe_allow_html=True)
                    data_cab = [
                        ("Pisos",              c.get("num_pisos", "—")),
                        ("Sótanos",            c.get("num_sotanos", 0)),
                        ("M² construibles",    f"{at_total:,.0f} m²"),
                        ("M² vendibles",       f"{av_total:,.0f} m²"),
                        ("Eficiencia vendible",f"{round(av_total/at_total*100,1) if at_total else 0}%"),
                        ("Departamentos",      c.get("total_unidades", "—")),
                        ("Estacionamientos",   c.get("estac_total", "—")),
                        ("COS (ocupación)",    f"{cos}%"),
                        ("CUS (uso del suelo)",f"{cus}"),
                    ]
                    for lbl, val in data_cab:
                        row_item(lbl, str(val))

            if c and st.session_state.financ:
                r = st.session_state.financ["resumen"]
                st.markdown('<div class="section-title">Resultados Financieros</div>', unsafe_allow_html=True)

                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("Ingresos brutos",  fmt_usd(r["ingresos_brutos"]))
                col2.metric("Costo total",      fmt_usd(r["costo_total_sin_financ"]))
                col3.metric("Utilidad neta",    fmt_usd(r["utilidad_neta"]))
                col4.metric("Margen",           f"{r['margen_pct']}%")
                col5.metric("ROI / TIR",        f"{r['roi_pct']}% / {r['tir_anual_pct']}%")

                st.markdown('<div class="section-title">Referencia del Terreno</div>', unsafe_allow_html=True)
                col1, col2, col3 = st.columns(3)
                col1.metric("Precio pagado",              fmt_usd(r.get("costo_total_sin_financ", 0)))
                col2.metric("Precio máx. para 20% mg.",   fmt_usd(r.get("max_terreno_20pct", 0)))
                col3.metric("Break-even precio/m²",       f"${r.get('be_precio_m2', 0):,}")

                st.markdown('<div class="section-title">Con Financiamiento Bancario</div>', unsafe_allow_html=True)
                col1, col2, col3 = st.columns(3)
                col1.metric("Costo financiero",   fmt_usd(r["costo_financiero"]))
                col2.metric("Utilidad neta",      fmt_usd(r["utilidad_con_financ"]), delta=f"{r['margen_con_financ_pct']}% margen")
                col3.metric("Duración proyecto",  f"{r['meses_proyecto']} meses")

            beneficios_all = p.get("beneficios_normativos", [])
            if beneficios_all:
                st.markdown('<div class="section-title">Beneficios Normativos Aplicables</div>', unsafe_allow_html=True)
                for b in beneficios_all:
                    st.markdown(f'<div class="alert-legal">⚖️ <strong>{b.get("descripcion","")}</strong> — {b.get("impacto_estimado","")}</div>', unsafe_allow_html=True)

            st.markdown("---")

            # ── Descarga del informe completo ─────────────
            if c and st.session_state.financ:
                from datetime import date as _date
                informe_html = generar_informe_html(
                    params        = p,
                    cabida        = c,
                    financ        = st.session_state.financ,
                    legal         = st.session_state.get("legal"),
                    zona          = zona_sel,
                    financ_inputs = st.session_state.get("financ_inputs"),
                    fecha         = _date.today().strftime("%d/%m/%Y"),
                )
                nombre_archivo = f"FACTIS_{p.get('ubicacion','Proyecto').replace(' ','_').replace(',','')[:40]}.html"
                st.download_button(
                    label             = "Descargar Informe Completo",
                    data              = informe_html.encode("utf-8"),
                    file_name         = nombre_archivo,
                    mime              = "text/html",
                    use_container_width = True,
                )
                st.caption("Abre el archivo en tu navegador y usa Ctrl+P / Cmd+P para imprimir a PDF.")

            st.caption("Osterling Advisory — Inmobiliaria Corporativa | eosterling@grupoosterling.com | Lima, Perú")

        # ── TAB 8: PROPUESTA ─────────────────────────────
        with tabs[7]:
            st.markdown('<div class="section-title">Propuesta de Compra / Arrendamiento</div>',
                        unsafe_allow_html=True)

            _prop_precio     = st.session_state.get("prop_precio", 0)
            _prop_tipo       = st.session_state.get("prop_tipo", "Compra")
            _prop_propietario = st.session_state.get("prop_propietario", "")
            _prop_plazo      = st.session_state.get("prop_plazo", 10)
            _prop_cond       = st.session_state.get("prop_condiciones", "")

            if not p:
                st.markdown('<div class="alert-legal">Genera el análisis primero para completar los datos del inmueble en la propuesta.</div>',
                            unsafe_allow_html=True)
            elif _prop_precio == 0:
                _financ_ss = st.session_state.get("financ")
                if _financ_ss:
                    _rr = _financ_ss.get("resumen", {})
                    _v20p = _rr.get("max_terreno_20pct", 0)
                    _v15p = _rr.get("max_terreno_15pct", 0)
                    _v12p = _rr.get("max_terreno_12pct", 0)
                    _ct   = (st.session_state.get("financ_inputs") or {}).get("costo_terreno", 0) or 0
                    st.markdown(
                        '<div class="alert-legal">'
                        '<b>Precio ofertado no ingresado.</b> El modelo financiero sugiere los siguientes precios '
                        'máximos de adquisición del terreno según margen objetivo:<br><br>'
                        + (f'<b>Precio ingresado en modelo:</b> ${_ct:,}<br><br>' if _ct > 0 else '')
                        + f'• <b>${_v20p:,}</b> → margen neto ≥ 20% &nbsp;<span style="color:#1A4731;font-weight:700;">●</span> óptimo<br>'
                        + f'• <b>${_v15p:,}</b> → margen neto ≥ 15% &nbsp;<span style="color:#7A5500;font-weight:700;">●</span> aceptable<br>'
                        + f'• <b>${_v12p:,}</b> → margen neto ≥ 12% &nbsp;<span style="color:#7A1A1A;font-weight:700;">●</span> mínimo<br><br>'
                        + 'Ingresa el precio ofertado en el panel izquierdo → sección <strong>PROPUESTA</strong>.'
                        '</div>',
                        unsafe_allow_html=True
                    )
                else:
                    st.markdown('<div class="alert-legal">Ingresa el precio ofertado en el panel izquierdo (sección <strong>PROPUESTA</strong>) para generar el documento.</div>',
                                unsafe_allow_html=True)
            else:
                from datetime import date as _date2
                _fecha_prop = _date2.today().strftime("%d de %B de %Y").replace(
                    "January","enero").replace("February","febrero").replace("March","marzo"
                    ).replace("April","abril").replace("May","mayo").replace("June","junio"
                    ).replace("July","julio").replace("August","agosto").replace("September","septiembre"
                    ).replace("October","octubre").replace("November","noviembre").replace("December","diciembre")

                _prop_html = generar_propuesta_html(
                    tipo           = _prop_tipo,
                    propietario    = _prop_propietario,
                    params         = p,
                    financ         = st.session_state.get("financ"),
                    legal          = st.session_state.get("legal"),
                    comps_sunarp   = st.session_state.get("comps_sunarp", []),
                    precio_oferta  = float(_prop_precio),
                    moneda_oferta  = "USD",
                    condiciones    = _prop_cond,
                    plazo_respuesta = int(_prop_plazo),
                    fecha          = _fecha_prop,
                )

                # Preview
                st.components.v1.html(_prop_html, height=820, scrolling=True)

                _nombre_prop = f"Propuesta_{_prop_tipo}_{(p.get('ubicacion') or 'Inmueble').replace(' ','_')[:35]}.html"
                st.download_button(
                    label               = f"Descargar Propuesta de {_prop_tipo}",
                    data                = _prop_html.encode("utf-8"),
                    file_name           = _nombre_prop,
                    mime                = "text/html",
                    use_container_width = True,
                )
                st.caption("Abre el archivo en tu navegador y usa Cmd+P para imprimir a PDF.")

    else:
        st.markdown(
            '<div style="border-radius:8px;min-height:460px;'
            'background:linear-gradient(160deg,#1A2737 0%,#1E2D3D 60%,#1A2737 100%);'
            'display:flex;align-items:center;justify-content:center;'
            'box-shadow:0 8px 32px rgba(30,45,61,0.18);padding:64px 48px;">'

            '<div style="display:grid;grid-template-columns:1fr 1px 1fr;gap:0;max-width:820px;width:100%;">'

            # Left: brand
            '<div style="padding-right:48px;display:flex;flex-direction:column;justify-content:center;">'
            '<div style="font-size:9px;color:#B8904A;letter-spacing:4px;text-transform:uppercase;'
            'font-weight:600;font-family:Inter,sans-serif;margin-bottom:20px;">Osterling Advisory</div>'
            '<div style="font-size:52px;font-weight:800;color:#FFFFFF;letter-spacing:-2px;line-height:1;'
            'font-family:Inter,sans-serif;margin-bottom:14px;">FACTIS</div>'
            '<div style="font-size:12px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;'
            'font-weight:500;font-family:Inter,sans-serif;">Herramienta Analítica Inmobiliaria</div>'
            '</div>'

            # Separator
            '<div style="background:rgba(184,144,74,0.3);"></div>'

            # Right: steps
            '<div style="padding-left:48px;display:flex;flex-direction:column;justify-content:center;gap:24px;">'
            '<div style="font-size:9px;color:#B8904A;letter-spacing:3px;text-transform:uppercase;'
            'font-weight:700;font-family:Inter,sans-serif;">Cómo comenzar</div>'

            '<div style="display:flex;align-items:flex-start;gap:16px;">'
            '<div style="min-width:24px;height:24px;border-radius:50%;background:rgba(184,144,74,0.2);'
            'border:1px solid #B8904A;display:flex;align-items:center;justify-content:center;'
            'font-size:11px;color:#B8904A;font-weight:700;">1</div>'
            '<div style="font-size:13px;color:#E8EDF2;line-height:1.65;font-family:Inter,sans-serif;">'
            'Adjunta el Certificado de Parámetros y documentos en el panel izquierdo'
            '</div></div>'

            '<div style="display:flex;align-items:flex-start;gap:16px;">'
            '<div style="min-width:24px;height:24px;border-radius:50%;background:rgba(184,144,74,0.2);'
            'border:1px solid #B8904A;display:flex;align-items:center;justify-content:center;'
            'font-size:11px;color:#B8904A;font-weight:700;">2</div>'
            '<div style="font-size:13px;color:#E8EDF2;line-height:1.65;font-family:Inter,sans-serif;">'
            'Configura la zona de mercado y los parámetros financieros del proyecto'
            '</div></div>'

            '<div style="display:flex;align-items:flex-start;gap:16px;">'
            '<div style="min-width:24px;height:24px;border-radius:50%;background:rgba(184,144,74,0.2);'
            'border:1px solid #B8904A;display:flex;align-items:center;justify-content:center;'
            'font-size:11px;color:#B8904A;font-weight:700;">3</div>'
            '<div style="font-size:13px;color:#E8EDF2;line-height:1.65;font-family:Inter,sans-serif;">'
            'Presiona GENERAR ANÁLISIS — cabida, financiero, legal y flujo de caja en segundos'
            '</div></div>'

            '</div>'  # end right
            '</div>'  # end grid
            '</div>',  # end hero
            unsafe_allow_html=True
        )

        # ── Capabilities bar ─────────────────────────────
        # icon: small gold monogram circle
        def _cap_icon(letter):
            return (
                '<div style="width:36px;height:36px;border-radius:50%;'
                'border:1.5px solid #B8904A;display:flex;align-items:center;'
                'justify-content:center;margin:0 auto 12px auto;">'
                f'<span style="font-size:13px;font-weight:700;color:#B8904A;'
                f'font-family:Inter,sans-serif;">{letter}</span>'
                '</div>'
            )
        def _cap(letter, title, desc):
            return (
                '<div style="display:flex;flex-direction:column;align-items:center;'
                'text-align:center;padding:28px 20px;">'
                + _cap_icon(letter)
                + f'<div style="font-size:12px;font-weight:700;color:#1E2D3D;letter-spacing:0.3px;'
                f'font-family:Inter,sans-serif;margin-bottom:6px;">{title}</div>'
                f'<div style="font-size:11px;color:#7A8A99;line-height:1.55;font-family:Inter,sans-serif;">{desc}</div>'
                '</div>'
            )
        cap_sep = '<div style="width:1px;background:#E0DAD0;margin:16px 0;align-self:stretch;"></div>'
        st.markdown(
            '<div style="background:#FAFAF8;border:1px solid #E8E3DA;border-radius:8px;'
            'margin-top:16px;display:grid;grid-template-columns:1fr 1px 1fr 1px 1fr 1px 1fr;'
            'align-items:stretch;">'
            + _cap("CA", "Cabida Arquitectónica", "Área techada, unidades, pisos y programa óptimo según normativa")
            + cap_sep
            + _cap("AF", "Análisis Financiero", "TIR, utilidad, margen y estructura de costos del proyecto")
            + cap_sep
            + _cap("FC", "Flujo de Caja", "Curva S mensual, breakeven y exposición máxima de capital")
            + cap_sep
            + _cap("DL", "Due Diligence Legal", "Partida registral, PU/HR, cargas, hipotecas y alertas registrales")
            + '</div>',
            unsafe_allow_html=True
        )

        # ── Footer disclaimer ────────────────────────────
        st.markdown(
            '<div style="margin-top:32px;padding:20px 32px;border-top:1px solid #E0DAD0;'
            'text-align:center;">'
            '<p style="font-size:11px;color:#8A8A8A;line-height:1.7;font-family:Inter,sans-serif;'
            'max-width:680px;margin:0 auto;">'
            'Osterling Advisory está comprometido con brindar información rigurosa y actualizada para la '
            'toma de decisiones inmobiliarias. Los resultados generados por FACTIS tienen carácter '
            'referencial y se basan en los parámetros ingresados por el usuario. Se recomienda validar '
            'los resultados con asesores legales, financieros y técnicos antes de tomar decisiones de inversión. '
            'Para consultas o soporte, escríbenos a '
            '<a href="mailto:eosterling@grupoosterling.com" style="color:#B8904A;text-decoration:none;">'
            'eosterling@grupoosterling.com</a>.'
            '</p>'
            '<p style="font-size:10px;color:#AAAAAA;margin-top:12px;font-family:Inter,sans-serif;">'
            '© 2026 Osterling Advisory — Lima, Perú. Todos los derechos reservados.'
            '</p>'
            '</div>',
            unsafe_allow_html=True
        )

# ═══════════════════════════════════════════════════════
# MÓDULO 2: PROYECTO LOGÍSTICO / INDUSTRIAL
# ═══════════════════════════════════════════════════════

elif tipo_op == "Proyecto Logístico / Industrial":
    r = st.session_state.get("industrial_result")

    if r:
        st.markdown(
            '<div class="main-header">'
            '<div style="display:flex;align-items:center;justify-content:space-between;">'
            '<div>'
            '<div style="font-size:9px;color:#B8904A;letter-spacing:4px;text-transform:uppercase;font-weight:600;margin-bottom:10px;">Osterling Advisory</div>'
            '<div style="display:flex;align-items:center;gap:18px;">'
            '<span style="font-size:22px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;">ANÁLISIS INDUSTRIAL</span>'
            '<span style="width:1px;height:18px;background:#B8904A;opacity:0.4;display:inline-block;flex-shrink:0;"></span>'
            '<span style="font-size:10px;color:#8AA8C0;letter-spacing:2.5px;text-transform:uppercase;font-weight:500;">'
            + r["tipo_nave"] + ' · ' + r["zonificacion"] + ' · ' + r["uso"] +
            '</span>'
            '</div></div>'
            '<div style="text-align:right;"><div style="font-size:8px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;font-weight:600;opacity:0.7;">Lima, Perú</div></div>'
            '</div></div>',
            unsafe_allow_html=True
        )

        # ── Controles de comparativa ─────────────────────
        _ic1, _ic2, _ic3 = st.columns([2, 1, 1])
        with _ic1:
            _ind_label = st.text_input("Nombre del escenario", placeholder="Ej: Nave Lurigancho — Opción A",
                                        label_visibility="collapsed", key="ind_cmp_label")
        with _ic2:
            if st.button("GUARDAR EN COMPARATIVA", use_container_width=True, key="btn_ind_cmp"):
                _lbl = _ind_label.strip() or f"Escenario {len(st.session_state.ind_comparativa)+1}"
                _entry = {"label": _lbl, "r": dict(r)}
                existing = [e["label"] for e in st.session_state.ind_comparativa]
                if _lbl in existing:
                    idx = existing.index(_lbl)
                    st.session_state.ind_comparativa[idx] = _entry
                elif len(st.session_state.ind_comparativa) < 3:
                    st.session_state.ind_comparativa.append(_entry)
                else:
                    st.session_state.ind_comparativa[2] = _entry
                st.toast(f"✓ '{_lbl}' guardado en comparativa")
        with _ic3:
            if st.session_state.ind_comparativa and st.button("LIMPIAR COMPARATIVA", use_container_width=True, key="btn_ind_cmp_clear"):
                st.session_state.ind_comparativa = []
                st.rerun()

        # ── Industrial Hero Banner ────────────────────────────────────
        import base64 as _b64i
        _ind_hero_fotos = st.session_state.get("ind_fotos_bytes") or []
        if _ind_hero_fotos:
            try:
                _b64_ind = _b64i.b64encode(_ind_hero_fotos[0]).decode()
                _ind_photo_css = f"url('data:image/jpeg;base64,{_b64_ind}') center/cover no-repeat"
            except Exception:
                _ind_photo_css = "linear-gradient(135deg,#1A2A1A 0%,#243824 100%)"
        else:
            _ind_photo_css = "linear-gradient(135deg,#1A2A1A 0%,#243824 100%)"

        _ind_ubicacion_label = st.session_state.get("ind_ubicacion") or (r.get("zonificacion", "") + " — Lima")
        _ind_yield_bruto = r.get("yield_bruto", 0)
        _ind_dscr        = r.get("dscr")
        _ind_payback     = r.get("payback_anos")
        _ind_kpi4 = (
            f'<div><div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">DSCR</div>'
            f'<div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_ind_dscr:.2f}x</div></div>'
            if _ind_dscr else (
            f'<div><div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">Payback</div>'
            f'<div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_ind_payback:.1f} años</div></div>'
            if _ind_payback else ""
            )
        )

        st.markdown(f"""
        <div style="position:relative;border-radius:16px;overflow:hidden;margin-bottom:20px;
                    box-shadow:0 6px 30px rgba(30,45,61,0.22);">
            <div style="background:{_ind_photo_css};height:220px;"></div>
            <div style="position:absolute;inset:0;background:linear-gradient(to bottom,
                        rgba(0,0,0,0.0) 0%,rgba(0,0,0,0.75) 100%);
                        display:flex;flex-direction:column;justify-content:flex-end;
                        padding:24px 28px;">
                <div style="font-size:9px;color:rgba(255,255,255,0.60);letter-spacing:3px;
                            text-transform:uppercase;margin-bottom:6px;">
                    Análisis Logístico / Industrial · FACTIS
                </div>
                <div style="font-size:28px;font-weight:800;color:#FFFFFF;line-height:1.15;
                            text-shadow:0 2px 8px rgba(0,0,0,0.5);">
                    {_ind_ubicacion_label}
                </div>
                <div style="display:flex;gap:20px;margin-top:12px;flex-wrap:wrap;">
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">Tipo de Nave</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">{r.get("tipo_nave","—")}</div>
                    </div>
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">Área Nave</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">{r.get("area_nave",0):,.0f} m²</div>
                    </div>
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">Costo Total</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">${r.get("costo_total",0):,.0f}</div>
                    </div>
                    {"" if _ind_yield_bruto == 0 else f'<div><div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">Yield Bruto</div><div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_ind_yield_bruto:.1f}%</div></div>'}
                    {_ind_kpi4}
                </div>
            </div>
        </div>""", unsafe_allow_html=True)

        ind_tabs = st.tabs(["Proyecto", "Financiero", "Flujo de Caja", "Comparativa", "Factibilidad", "Resumen IA"])

        # TAB 1: PROYECTO
        with ind_tabs[0]:
            st.markdown('<div class="section-title">Resumen del Proyecto</div>', unsafe_allow_html=True)
            ci1, ci2, ci3, ci4 = st.columns(4)
            ci1.metric("Área del Terreno", f"{r['area_terreno']:,.0f} m²")
            ci2.metric("Área Nave (techada)", f"{r['area_nave']:,.0f} m²", f"{r['pct_techada']:.0f}% techada · {r['area_libre']:,.0f} m² libre")
            ci3.metric("Costo Total Proyecto", f"${r['costo_total']:,.0f}")
            ci4.metric("Costo por m² (nave)", f"${r['costo_por_m2_nave']:,.0f}/m²")

            st.markdown('<div class="section-title">Estructura de Costos</div>', unsafe_allow_html=True)
            ci5, ci6 = st.columns(2)
            with ci5:
                ci5.metric("Terreno", f"${r['costo_terreno']:,.0f}")
                ci5.metric("Alcabala (3%)", f"${r['alcabala']:,.0f}")
                ci5.metric("Nave techada", f"${r['costo_nave_total']:,.0f}", f"${r['costo_nave_m2']:,.0f}/m² × {r['area_nave']:,.0f} m²")
                ci5.metric("Piso área libre", f"${r['costo_pisos_libres']:,.0f}", f"${r['costo_piso_libre_m2']:,.0f}/m² × {r['area_libre']:,.0f} m²")
                ci5.metric(f"Costos Indirectos ({r.get('pct_indirectos', 5):.0f}%)", f"${r['soft_costs']:,.0f}")
            with ci6:
                costo_items = [
                    ("Terreno", r['costo_terreno']),
                    ("Nave techada", r['costo_nave_total']),
                    ("Piso libre", r['costo_pisos_libres']),
                    (f"Costos Indirectos", r['soft_costs']),
                ]
                fig_costs = go.Figure(go.Bar(
                    x=[x[0] for x in costo_items],
                    y=[x[1] for x in costo_items],
                    marker_color=["#1E2D3D", "#B8904A", "#8A9BAD", "#C8A86A"],
                    text=[f"${x[1]:,.0f}" for x in costo_items],
                    textposition="outside",
                ))
                fig_costs.update_layout(
                    height=300, margin=dict(t=20, b=20, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(title=dict(text="USD", font=dict(color="#4A5568", size=11)), tickfont=dict(color="#4A5568", size=10), showgrid=True, gridcolor="#E8E4DC"),
                    xaxis=dict(tickfont=dict(color="#4A5568", size=10)),
                    font=dict(family="Inter", color="#4A5568"),
                    showlegend=False,
                )
                st.plotly_chart(fig_costs, use_container_width=True)

            st.markdown(
                '<div class="alert-gold">'
                f'<strong>Costos de construcción:</strong> Nave: ${r["costo_nave_m2"]:,.0f}/m² ({r["tipo_nave"]}) · '
                f'Piso área libre: ${r["costo_piso_libre_m2"]:,.0f}/m². '
                f'Costos indirectos ({r.get("pct_indirectos", 5):.0f}%): permisos, licencias municipales, supervisión y gestión de obra.'
                '</div>',
                unsafe_allow_html=True
            )

            # ── Validador precio de terreno (referencia orientativa) ──
            _pt_m2 = r['costo_terreno'] / r['area_terreno'] if r['area_terreno'] > 0 else 0
            _zona_ind_sel = st.session_state.get("ind_zona_lima", "")
            _es_ves_lurin = any(z in _zona_ind_sel for z in ["Villa El Salvador", "Lurín"])
            if _pt_m2 > 0:
                _uso_ind = r.get("uso", "Inversión")
                if _es_ves_lurin:
                    _max_t = 180 if _uso_ind == "Inversión" else 300
                    _ref_txt = ("build-to-rent · ref. Aldea Logística VES 2023-2024: $140–$172/m²"
                                if _uso_ind == "Inversión" else "uso propio · umbral orientativo")
                    if _pt_m2 <= _max_t:
                        _tc, _tb = "#E8F5EE", "#1A4731"
                        _tm = f"✓ Terreno a <b>${_pt_m2:,.0f}/m²</b> — dentro del rango para {_ref_txt} en VES/Lurín."
                    elif _pt_m2 <= _max_t * 1.25:
                        _tc, _tb = "#FFF8E6", "#7A5500"
                        _tm = (f"⚡ Terreno a <b>${_pt_m2:,.0f}/m²</b> — ligeramente sobre el umbral orientativo "
                               f"(${_max_t}/m²) para {_ref_txt}. Verificar márgenes.")
                    else:
                        _tc, _tb = "#FDECEA", "#7A1A1A"
                        _tm = (f"⚠ Terreno a <b>${_pt_m2:,.0f}/m²</b> — supera el umbral orientativo "
                               f"(${_max_t}/m²) para {_ref_txt}. Evaluar ajuste de precio o renta requerida.")
                else:
                    _tc, _tb = "#F0EDE8", "#4A5568"
                    _zona_rng = "$450–$700/m²" if any(z in _zona_ind_sel for z in ["Callao", "SJL", "Cercado", "Huachipa"]) else "variable según zona"
                    _tm = (f"Terreno a <b>${_pt_m2:,.0f}/m²</b>. "
                           f"En zonas céntricas ({_zona_rng}) la viabilidad depende principalmente "
                           f"de la capacidad de pago de la industria/inquilino.")
                st.markdown(
                    f'<div style="background:{_tc};border-left:3px solid {_tb};border-radius:6px;'
                    f'padding:10px 14px;margin-top:10px;font-size:12px;">'
                    f'{_tm}<br>'
                    f'<span style="font-size:10px;opacity:0.65;">Referencia orientativa — el profesional aplica su criterio según la operación específica.</span>'
                    f'</div>',
                    unsafe_allow_html=True)

        # TAB 2: FINANCIERO
        with ind_tabs[1]:
            # ── Compra vs. Arrendamiento ──────────────────────
            st.markdown('<div class="section-title">Compra vs. Arrendamiento</div>', unsafe_allow_html=True)
            st.caption("Referencia orientativa — el profesional aplica su criterio según la industria, perfil del inquilino y estructura del deal.")

            _an = r['area_nave']
            _cuota_ef = r.get('cuota_efectiva_mensual', 0)
            if _cuota_ef > 0 and r.get('cuota_mensual', 0) > 0:
                _costo_m2_mes = _cuota_ef / _an if _an > 0 else 0
                _metodo_lbl   = f"Cuota efectiva a {r['plazo_anos']} años (neta escudo fiscal)"
            else:
                _costo_m2_mes = r['costo_total'] / (10 * 12 * _an) if _an > 0 else 0
                _metodo_lbl   = "Amortización lineal 10 años (sin financiamiento)"
            _renta_be10 = r['costo_total'] / (10 * 12 * _an) if _an > 0 else 0

            _PRIME_LO, _PRIME_HI = 5.50, 7.50
            if _costo_m2_mes <= _PRIME_LO:
                _bvr_c, _bvr_b = "#E8F5EE", "#1A4731"
                _bvr_msg = (f"✓ Costo efectivo de compra (<b>${_costo_m2_mes:.2f}/m²/mes</b>) inferior al rango "
                            f"Prime Lima (${_PRIME_LO:.2f}–${_PRIME_HI:.2f}/m²/mes) — "
                            f"comprar es numéricamente más eficiente que arrendar.")
            elif _costo_m2_mes <= _PRIME_HI:
                _bvr_c, _bvr_b = "#FFF8E6", "#7A5500"
                _bvr_msg = (f"⚡ Costo efectivo (<b>${_costo_m2_mes:.2f}/m²/mes</b>) dentro del rango Prime "
                            f"(${_PRIME_LO:.2f}–${_PRIME_HI:.2f}/m²/mes) — "
                            f"compra y arriendo son alternativas equivalentes; evaluar según estrategia.")
            else:
                _bvr_c, _bvr_b = "#FDECEA", "#7A1A1A"
                _bvr_msg = (f"⚠ Costo efectivo (<b>${_costo_m2_mes:.2f}/m²/mes</b>) supera el rango Prime "
                            f"(${_PRIME_LO:.2f}–${_PRIME_HI:.2f}/m²/mes) — "
                            f"revisar precio de terreno, financiamiento o renta objetivo.")

            bvr1, bvr2, bvr3 = st.columns(3)
            bvr1.metric("Costo efectivo compra", f"${_costo_m2_mes:.2f}/m²/mes", _metodo_lbl)
            bvr2.metric("Renta Prime Lima",       "$5.50–$7.50/m²/mes", "Naves categoría A · VES, Lurín, Callao")
            bvr3.metric("Break-even renta 10 años", f"${_renta_be10:.2f}/m²/mes", "Renta mínima para recuperar inversión")

            st.markdown(
                f'<div style="background:{_bvr_c};border-left:3px solid {_bvr_b};border-radius:6px;'
                f'padding:10px 14px;margin-bottom:16px;font-size:12px;">{_bvr_msg}</div>',
                unsafe_allow_html=True)

            # ── Proyección indexada (solo contratos plurianuales) ──
            if r.get("tipo_contrato") == "Plurianual (3+ años)" and r.get("ajuste_anual_pct", 0) > 0:
                _aj  = r["ajuste_anual_pct"]
                _ini = r["inicio_ajuste_ano"]
                st.markdown(
                    f'<div style="background:#F0F4FF;border-left:3px solid #3B5BDB;border-radius:6px;'
                    f'padding:10px 14px;margin-bottom:8px;font-size:12px;">'
                    f'<strong>Contrato plurianual · ajuste +{_aj:.1f}% anual desde año {_ini}</strong><br>'
                    f'La renta crece con el contrato; el costo de compra (cuota) permanece fijo — '
                    f'el diferencial favorable <b>se amplía año a año</b>.'
                    f'</div>', unsafe_allow_html=True)
                _pi_cols = st.columns(4)
                _pi_cols[0].metric("Renta/m² año 1", f"${r['renta_m2_mes']:.2f}/mes")
                _pi_cols[1].metric(f"Renta/m² año 3", f"${r['renta_m2_ano3']:.2f}/mes",
                                   f"+{((r['renta_m2_ano3']/r['renta_m2_mes']-1)*100):.1f}%" if r['renta_m2_mes'] > 0 else "")
                _pi_cols[2].metric(f"Renta/m² año 5", f"${r['renta_m2_ano5']:.2f}/mes",
                                   f"+{((r['renta_m2_ano5']/r['renta_m2_mes']-1)*100):.1f}%" if r['renta_m2_mes'] > 0 else "")
                if r.get("payback_indexado") and r.get("payback_anos"):
                    _delta_pb = r["payback_anos"] - r["payback_indexado"]
                    _pi_cols[3].metric("Payback indexado", f"{r['payback_indexado']} años",
                                       f"{_delta_pb:.1f} años menos vs renta fija")
                _yield_data = {
                    "Año": ["Año 1 (base)", f"Año 3 (+{_aj:.1f}% × {max(3-_ini+1,0)})", f"Año 5 (+{_aj:.1f}% × {max(5-_ini+1,0)})"],
                    "Yield neto": [f"{r['yield_neto']:.1f}%", f"{r['yield_neto_ano3']:.1f}%", f"{r['yield_neto_ano5']:.1f}%"],
                }
                st.table(pd.DataFrame(_yield_data).set_index("Año"))

            st.markdown("---")
            st.markdown('<div class="section-title">Análisis Financiero</div>', unsafe_allow_html=True)
            cf1, cf2, cf3 = st.columns(3)
            cf1.metric("Capital Propio", f"${r['capital_propio']:,.0f}", f"{100 - r['pct_credito']:.0f}% del total")
            cf2.metric("Monto Financiado", f"${r['monto_credito']:,.0f}", f"{r['pct_credito']:.0f}% del total")
            cf3.metric("Cuota Mensual", f"${r['cuota_mensual']:,.0f}" if r['cuota_mensual'] > 0 else "Sin crédito", f"{r['plazo_anos']} años")

            if r['uso'] == "Inversión":
                st.markdown('<div class="section-title">Métricas de Retorno</div>', unsafe_allow_html=True)
                cr1, cr2, cr3, cr4 = st.columns(4)
                cr1.metric("Renta Mensual Total", f"${r['renta_total_mes']:,.0f}", f"${r['renta_m2_mes']:.2f}/m²/mes")
                cr2.metric("Yield Bruto Anual", f"{r['yield_bruto']:.1f}%")
                cr3.metric("Yield Neto Anual", f"{r['yield_neto']:.1f}%", "8% gastos op.")
                if r['payback_anos']:
                    cr4.metric("Payback", f"{r['payback_anos']:.1f} años")
                else:
                    cr4.metric("Payback", "N/A")

                if r['cuota_mensual'] > 0:
                    st.markdown('<div class="section-title">Flujo con Financiamiento</div>', unsafe_allow_html=True)
                    cd1, cd2, cd3 = st.columns(3)
                    flujo = r['flujo_mensual'] or 0
                    flujo_label = "Flujo mensual neto" if flujo >= 0 else "Déficit mensual"
                    cd1.metric(flujo_label, f"${abs(flujo):,.0f}/mes")
                    if r['dscr']:
                        cd2.metric("DSCR", f"{r['dscr']:.2f}x", "Cobertura deuda")
                    cd3.metric("Escudo fiscal nave", f"${r['ahorro_fiscal_mensual']:,.0f}/mes",
                               f"${r['ahorro_fiscal_anual']:,.0f}/año · IR 29.5%")

                    _dscr_val = r['dscr'] or 0
                    if _dscr_val >= 1.2:
                        _dscr_msg = (f"DSCR {_dscr_val:.2f}x — Cobertura adecuada. La renta cubre el servicio de deuda con margen.")
                        _dscr_cls = "alert-legal"
                    elif _dscr_val >= 1.0:
                        _dscr_msg = (f"DSCR {_dscr_val:.2f}x — Cobertura ajustada. La renta apenas cubre la deuda; "
                                     f"el retorno se evalúa por TIR equity, no solo por DSCR. "
                                     f"En proyectos de desarrollo con financiamiento &gt;60%, DSCR &lt; 1.20x es normal "
                                     f"al inicio; la vacancia en estabilización y la apreciación del activo compensan.")
                        _dscr_cls = "alert-gold"
                    else:
                        _dscr_msg = (f"DSCR {_dscr_val:.2f}x — La renta no cubre el servicio de deuda. "
                                     f"Esto es frecuente en proyectos de desarrollo nuevos donde el costo total de obra "
                                     f"es la base del financiamiento. El indicador determinante es la <strong>TIR equity</strong> "
                                     f"y la <strong>plusvalía del activo</strong> al horizonte de salida.")
                        _dscr_cls = "alert-gold"
                    st.markdown(f'<div class="{_dscr_cls}">{_dscr_msg}</div>', unsafe_allow_html=True)

            elif r['uso'] == "Uso directo":
                st.markdown('<div class="section-title">Análisis vs. Arrendamiento</div>', unsafe_allow_html=True)
                ca1, ca2, ca3 = st.columns(3)
                ca1.metric("Renta de Mercado (ref.)", f"${r['renta_total_mes']:,.0f}/mes", f"${r['renta_m2_mes']:.2f}/m²/mes")
                ca2.metric("Cuota Mensual", f"${r['cuota_mensual']:,.0f}/mes" if r['cuota_mensual'] > 0 else "Compra al contado")
                ahorro = r['alquiler_vs_compra'] or 0
                ca3.metric("Ahorro vs. Alquilar", f"${ahorro:,.0f}/mes", "Compra vs renta mensual")

                if r['cuota_mensual'] > 0 and r['renta_total_mes'] > 0:
                    anos_breakeven = r['capital_propio'] / (ahorro * 12) if ahorro > 0 else None
                    if anos_breakeven:
                        st.markdown(
                            '<div class="alert-gold">'
                            f'<strong>Punto de equilibrio estimado:</strong> El ahorro acumulado vs. arrendamiento '
                            f'recupera el capital propio invertido en aproximadamente <strong>{anos_breakeven:.1f} años</strong>.'
                            '</div>',
                            unsafe_allow_html=True
                        )

        # TAB 3: FLUJO DE CAJA
        with ind_tabs[2]:
            if r['uso'] == "Inversión" and r.get('flujo_anual'):
                st.markdown('<div class="section-title">Score de Viabilidad</div>', unsafe_allow_html=True)

                # Score compuesto
                _score_pts = 0
                _score_max = 4
                if r.get('yield_neto', 0) >= 7:    _score_pts += 1
                if r.get('dscr') and r['dscr'] >= 1.2: _score_pts += 1
                if r.get('payback_anos') and r['payback_anos'] <= 12: _score_pts += 1
                if r.get('irr_anual') and r['irr_anual'] >= 12: _score_pts += 1
                _score_pct = _score_pts / _score_max
                _score_color = "#1A4731" if _score_pct >= 0.75 else ("#7A4F1A" if _score_pct >= 0.5 else "#7A1A1A")
                _score_bg = "#E8F5EE" if _score_pct >= 0.75 else ("#FFF8EE" if _score_pct >= 0.5 else "#FFF0F0")
                _score_etiq = "INVERSIÓN VIABLE" if _score_pct >= 0.75 else ("INVERSIÓN CON RESERVAS" if _score_pct >= 0.5 else "REVISAR ESTRUCTURA")

                st.markdown(f"""
                <div style="background:{_score_bg};border:1px solid {_score_color};border-left:4px solid {_score_color};
                            border-radius:8px;padding:18px 24px;margin-bottom:20px;display:flex;align-items:center;gap:24px;">
                    <div style="font-size:48px;font-weight:800;color:{_score_color};min-width:64px;text-align:center;">{_score_pts}/{_score_max}</div>
                    <div>
                        <div style="font-size:9px;letter-spacing:3px;color:{_score_color};text-transform:uppercase;font-weight:700;opacity:0.7;">Score de Viabilidad Industrial</div>
                        <div style="font-size:18px;font-weight:700;color:{_score_color};margin-top:4px;">{_score_etiq}</div>
                        <div style="font-size:12px;color:{_score_color};opacity:0.8;margin-top:6px;line-height:1.5;">
                            {"✓" if r.get('yield_neto',0)>=7 else "✗"} Yield neto ≥ 7% &nbsp;·&nbsp;
                            {"✓" if r.get('dscr') and r['dscr']>=1.2 else "✗"} DSCR ≥ 1.20x &nbsp;·&nbsp;
                            {"✓" if r.get('payback_anos') and r['payback_anos']<=12 else "✗"} Payback ≤ 12 años &nbsp;·&nbsp;
                            {"✓" if r.get('irr_anual') and r['irr_anual']>=12 else "✗"} TIR equity ≥ 12%
                        </div>
                    </div>
                </div>""", unsafe_allow_html=True)

                st.markdown('<div class="section-title">Indicadores de Retorno</div>', unsafe_allow_html=True)
                cf1, cf2, cf3, cf4 = st.columns(4)
                cf1.metric("TIR Equity 10 años", f"{r['irr_anual']:.1f}%" if r.get('irr_anual') is not None else "—")
                cf2.metric("VAN 10 años (10%)", f"${r['van_10']:,.0f}" if r.get('van_10') is not None else "—")
                cf3.metric("Yield Neto", f"{r['yield_neto']:.1f}%")
                cf4.metric("Payback", f"{r['payback_anos']:.1f} a." if r.get('payback_anos') else "—")

                st.markdown('<div class="section-title">Flujo de Caja Proyectado (10 años)</div>', unsafe_allow_html=True)
                fa = r['flujo_anual']
                anos_fc = list(range(len(fa)))
                colores_fc = ["#7A1A1A" if v < 0 else "#1A4731" for v in fa]
                fig_fc = go.Figure(go.Bar(
                    x=[f"Año {i}" if i > 0 else "Inv. Inicial" for i in anos_fc],
                    y=fa,
                    marker_color=colores_fc,
                    text=[f"${v:,.0f}" for v in fa],
                    textposition="outside",
                ))
                fig_fc.update_layout(
                    height=300, margin=dict(t=30, b=20, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    yaxis=dict(tickfont=dict(color="#4A5568", size=10), showgrid=True, gridcolor="#E8E4DC", tickformat="$,.0f"),
                    xaxis=dict(tickfont=dict(color="#4A5568", size=10)),
                    font=dict(family="Inter", color="#4A5568"),
                    showlegend=False,
                )
                st.plotly_chart(fig_fc, use_container_width=True)

                # Tabla flujo
                _fc_th = "".join(
                    f'<th style="background:#1E2D3D;color:#FFFFFF;padding:9px 12px;font-size:10px;'
                    f'letter-spacing:1px;text-transform:uppercase;font-weight:700;border:1px solid #2A3D51;text-align:right;">{h}</th>'
                    for h in ["Período", "Renta Neta", "Cuota Deuda", "Flujo Libre", "Flujo Acumulado"]
                )
                _fc_rows = ""
                _acum = 0
                cuota_anual = r['cuota_mensual'] * 12
                for i, fv in enumerate(fa):
                    bg = "#FFFFFF" if i % 2 == 0 else "#F9F7F4"
                    yr_lbl = "Inversión Inicial" if i == 0 else f"Año {i}"
                    if i == 0:
                        _acum += fv
                        _fc_rows += (f'<tr><td style="background:{bg};color:#1E2D3D;padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;">{yr_lbl}</td>'
                                     f'<td style="background:{bg};color:#1E2D3D;padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">—</td>'
                                     f'<td style="background:{bg};color:#1E2D3D;padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">—</td>'
                                     f'<td style="background:{bg};color:#7A1A1A;padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;text-align:right;font-weight:700;">${fv:,.0f}</td>'
                                     f'<td style="background:{bg};color:#7A1A1A;padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">${_acum:,.0f}</td></tr>')
                    else:
                        yr_actual = i
                        _cuota_yr = cuota_anual if yr_actual <= r['plazo_anos'] else 0
                        _renta = r['renta_neta_anual']
                        _flujo_libre = _renta - _cuota_yr
                        _flujo_display = _flujo_libre if i < len(fa) - 1 else fv
                        _acum += _flujo_display
                        _col_libre = "#1A4731" if _flujo_display >= 0 else "#7A1A1A"
                        _col_acum  = "#1A4731" if _acum >= 0 else "#7A1A1A"
                        _yr_note = " + Venta" if i == len(fa) - 1 else ""
                        _fc_rows += (f'<tr><td style="background:{bg};color:#1E2D3D;padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;">{yr_lbl}{_yr_note}</td>'
                                     f'<td style="background:{bg};color:#1E2D3D;padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">${_renta:,.0f}</td>'
                                     f'<td style="background:{bg};color:#1E2D3D;padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">${_cuota_yr:,.0f}</td>'
                                     f'<td style="background:{bg};color:{_col_libre};padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;text-align:right;font-weight:600;">${_flujo_display:,.0f}</td>'
                                     f'<td style="background:{bg};color:{_col_acum};padding:8px 12px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">${_acum:,.0f}</td></tr>')

                st.markdown(
                    f'<div style="overflow-x:auto;margin-bottom:20px;">'
                    f'<table style="width:100%;border-collapse:collapse;">'
                    f'<thead><tr>{_fc_th}</tr></thead><tbody>{_fc_rows}</tbody></table></div>',
                    unsafe_allow_html=True
                )

                st.markdown('<div class="section-title">Descargar Informe</div>', unsafe_allow_html=True)
                _ind_html = generar_informe_industrial_html(
                    r, st.session_state.get("industrial_factibilidad"),
                    datetime.datetime.now().strftime("%d/%m/%Y"))
                st.download_button(
                    "DESCARGAR INFORME PDF",
                    data=_ind_html.encode("utf-8"),
                    file_name=f"informe_industrial_{datetime.datetime.now().strftime('%Y%m%d')}.html",
                    mime="text/html",
                    use_container_width=True,
                )
                st.caption("El archivo .html se abre en cualquier navegador y puede imprimirse como PDF.")

            else:
                st.markdown(
                    '<div class="alert-legal">El flujo de caja e IRR están disponibles en modo <strong>Inversión</strong> '
                    'con renta de mercado ingresada. Cambia el propósito del activo en el panel izquierdo.</div>',
                    unsafe_allow_html=True
                )
                # Siempre mostrar botón de descarga aunque no haya IRR
                st.markdown('<div class="section-title">Descargar Informe</div>', unsafe_allow_html=True)
                _ind_html = generar_informe_industrial_html(
                    r, st.session_state.get("industrial_factibilidad"),
                    datetime.datetime.now().strftime("%d/%m/%Y"))
                st.download_button(
                    "DESCARGAR INFORME PDF",
                    data=_ind_html.encode("utf-8"),
                    file_name=f"informe_industrial_{datetime.datetime.now().strftime('%Y%m%d')}.html",
                    mime="text/html",
                    use_container_width=True,
                )

        # TAB 4: COMPARATIVA
        with ind_tabs[3]:
            # Multi-project comparison
            cmp_list = st.session_state.ind_comparativa
            if cmp_list:
                st.markdown('<div class="section-title">Comparativa de Escenarios</div>', unsafe_allow_html=True)
                _cmp_metrics = ["costo_total", "costo_por_m2_nave", "yield_neto", "dscr", "payback_anos", "irr_anual", "capital_propio", "cuota_mensual"]
                _cmp_labels  = ["Costo Total", "Costo/m² Nave", "Yield Neto %", "DSCR", "Payback (años)", "TIR Equity %", "Capital Propio", "Cuota Mensual"]
                _cmp_fmt     = ["${:,.0f}", "${:,.0f}", "{:.1f}%", "{:.2f}x", "{:.1f} a.", "{:.1f}%", "${:,.0f}", "${:,.0f}"]

                _th = '<th style="background:#1E2D3D;color:#FFFFFF;padding:9px 14px;font-size:10px;letter-spacing:1px;text-transform:uppercase;">Indicador</th>'
                for e in cmp_list:
                    _th += f'<th style="background:#1E2D3D;color:#B8904A;padding:9px 14px;font-size:10px;letter-spacing:1px;text-transform:uppercase;text-align:right;">{e["label"]}</th>'

                _rows = ""
                for lbl, key, fmt in zip(_cmp_labels, _cmp_metrics, _cmp_fmt):
                    bg_row = "#FFFFFF" if _cmp_metrics.index(key) % 2 == 0 else "#F9F7F4"
                    _row = f'<td style="background:{bg_row};color:#4A5568;padding:8px 14px;font-size:11px;font-weight:600;border:1px solid #E0DAD0;">{lbl}</td>'
                    vals = [e["r"].get(key) for e in cmp_list]
                    # Determine best value (highest or lowest depending on metric)
                    _higher_is_better = key in ["yield_neto", "dscr", "irr_anual"]
                    _lower_is_better  = key in ["costo_total", "costo_por_m2_nave", "payback_anos", "cuota_mensual", "capital_propio"]
                    valid_vals = [v for v in vals if v is not None]
                    best = max(valid_vals) if _higher_is_better and valid_vals else (min(valid_vals) if _lower_is_better and valid_vals else None)
                    for v in vals:
                        try:
                            display = fmt.format(v) if v is not None else "—"
                        except Exception:
                            display = str(v) if v is not None else "—"
                        is_best = (v == best and best is not None)
                        _cell_color = "#1A4731" if is_best else "#1E2D3D"
                        _cell_weight = "700" if is_best else "400"
                        _row += f'<td style="background:{bg_row};color:{_cell_color};padding:8px 14px;font-size:12px;font-weight:{_cell_weight};border:1px solid #E0DAD0;text-align:right;">{display}</td>'
                    _rows += f"<tr>{_row}</tr>"

                st.markdown(
                    f'<div style="overflow-x:auto;margin-bottom:20px;">'
                    f'<table style="width:100%;border-collapse:collapse;">'
                    f'<thead><tr>{_th}</tr></thead><tbody>{_rows}</tbody></table></div>',
                    unsafe_allow_html=True
                )
                st.caption("Verde = mejor valor del escenario para ese indicador.")

                # Bar chart: yield neto comparison
                if len(cmp_list) > 1:
                    fig_cmp_multi = go.Figure(data=[
                        go.Bar(name=e["label"],
                               x=["Yield Neto %", "TIR Equity %", "DSCR x10"],
                               y=[e["r"].get("yield_neto", 0),
                                  e["r"].get("irr_anual") or 0,
                                  (e["r"].get("dscr") or 0) * 10],
                               text=[f"{e['r'].get('yield_neto',0):.1f}%",
                                     f"{e['r'].get('irr_anual') or 0:.1f}%",
                                     f"{(e['r'].get('dscr') or 0):.2f}x"],
                               textposition="outside")
                        for e in cmp_list
                    ])
                    fig_cmp_multi.update_layout(
                        barmode="group", height=300, margin=dict(t=20, b=20, l=10, r=10),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        yaxis=dict(tickfont=dict(color="#4A5568", size=10), showgrid=True, gridcolor="#E8E4DC"),
                        xaxis=dict(tickfont=dict(color="#4A5568", size=11)),
                        legend=dict(font=dict(color="#4A5568", size=11)),
                        font=dict(family="Inter", color="#4A5568"),
                        colorway=["#1E2D3D", "#B8904A", "#8A9BAD"],
                    )
                    st.plotly_chart(fig_cmp_multi, use_container_width=True)

            st.markdown('<div class="section-title">Comprar vs. Arrendar</div>', unsafe_allow_html=True)
            if r['renta_m2_mes'] > 0:
                APRECIACION = r.get('APRECIACION_IND', 0.03)
                plazo = max(r['plazo_anos'], 5)
                renta_anual = r['renta_total_mes'] * 12
                ahorro_fis_anual = r['ahorro_fiscal_anual']
                ahorro_fis_mens  = r['ahorro_fiscal_mensual']
                cuota_ef         = r['cuota_efectiva_mensual']

                # Costo acumulado arrendamiento (solo egreso puro)
                cum_alq = [renta_anual * y for y in range(1, plazo + 1)]

                # Costo acumulado compra bruto (capital propio + servicio deuda)
                cum_compra_bruta = []
                for y in range(1, plazo + 1):
                    if r['cuota_mensual'] > 0:
                        cum_compra_bruta.append(r['capital_propio'] + r['cuota_mensual'] * 12 * y)
                    else:
                        cum_compra_bruta.append(r['costo_total'])

                # Costo neto compra (– escudo fiscal 20 años) + valor del activo al año y
                cum_compra_neta  = []
                cum_valor_activo = []
                for y in range(1, plazo + 1):
                    escudo = ahorro_fis_anual * min(y, 20)      # hasta 20 años de depreciación
                    cum_compra_neta.append(cum_compra_bruta[y-1] - escudo)
                    cum_valor_activo.append(r['costo_total'] * (1 + APRECIACION) ** y)

                anos_range = list(range(1, plazo + 1))

                # ── Métricas clave ────────────────────────────────────────────────
                cv1, cv2, cv3, cv4 = st.columns(4)
                cv1.metric("Cuota mensual", f"${r['cuota_mensual']:,.0f}/mes" if r['cuota_mensual'] > 0 else "Al contado")
                cv2.metric("Cuota efectiva (post-impuestos)", f"${cuota_ef:,.0f}/mes",
                           f"−${ahorro_fis_mens:,.0f}/mes escudo fiscal")
                cv3.metric("Renta de mercado equiv.", f"${r['renta_total_mes']:,.0f}/mes")
                dif = r['renta_total_mes'] - cuota_ef
                cv4.metric("Ahorro vs. arrendar", f"${dif:,.0f}/mes" if dif >= 0 else f"−${abs(dif):,.0f}/mes",
                           "comprar es más barato" if dif >= 0 else "arrendar es más barato aún")

                # ── Panel escudo fiscal ───────────────────────────────────────────
                st.markdown(f"""
                <div style="background:#F7F5F1;border:1px solid #D8D4CC;border-left:4px solid #B8904A;
                            border-radius:6px;padding:14px 20px;margin:12px 0;">
                    <div style="font-size:9px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;
                                font-weight:700;margin-bottom:8px;">Beneficio Fiscal de la Propiedad</div>
                    <div style="display:flex;gap:32px;flex-wrap:wrap;">
                        <div><div style="font-size:10px;color:#7A7268;">Base depreciable (nave)</div>
                             <div style="font-size:14px;font-weight:700;color:#1E2D3D;">${r['costo_nave_total']:,.0f}</div></div>
                        <div><div style="font-size:10px;color:#7A7268;">Depreciación anual (5%/año · 20 años)</div>
                             <div style="font-size:14px;font-weight:700;color:#1E2D3D;">${r['depreciacion_anual']:,.0f}/año</div></div>
                        <div><div style="font-size:10px;color:#7A7268;">Ahorro IR anual (29.5%)</div>
                             <div style="font-size:14px;font-weight:700;color:#1A4731;">${ahorro_fis_anual:,.0f}/año</div></div>
                        <div><div style="font-size:10px;color:#7A7268;">Ahorro fiscal acumulado (20 años)</div>
                             <div style="font-size:14px;font-weight:700;color:#1A4731;">${ahorro_fis_anual * 20:,.0f}</div></div>
                    </div>
                    <div style="font-size:11px;color:#7A7268;margin-top:8px;line-height:1.5;">
                        El terreno no deprecia. Base: DS 122-94-EF · Tasa industrial 5% anual · IR corporativo 29.5%.
                        La compra del inmueble genera además <strong>plusvalía del activo</strong>,
                        <strong>capital societario respaldado</strong> y posibilidad de <strong>crédito fiscal</strong>.
                    </div>
                </div>""", unsafe_allow_html=True)

                # ── Gráfico comparativo ───────────────────────────────────────────
                fig_cmp = go.Figure()
                fig_cmp.add_trace(go.Scatter(
                    x=anos_range, y=cum_alq,
                    name="Arrendamiento acumulado",
                    line=dict(color="#B8904A", width=2.5), mode="lines",
                    hovertemplate="Año %{x}: $%{y:,.0f}<extra>Arrendamiento</extra>"))
                fig_cmp.add_trace(go.Scatter(
                    x=anos_range, y=cum_compra_bruta,
                    name="Compra (egreso bruto)",
                    line=dict(color="#8A9BAD", width=2, dash="dot"), mode="lines",
                    hovertemplate="Año %{x}: $%{y:,.0f}<extra>Compra bruta</extra>"))
                fig_cmp.add_trace(go.Scatter(
                    x=anos_range, y=cum_compra_neta,
                    name="Compra (neto escudo fiscal)",
                    line=dict(color="#1E2D3D", width=2.5), mode="lines",
                    hovertemplate="Año %{x}: $%{y:,.0f}<extra>Compra neta</extra>"))
                fig_cmp.add_trace(go.Scatter(
                    x=anos_range, y=cum_valor_activo,
                    name="Valor del activo (3% apreciación)",
                    line=dict(color="#1A4731", width=2, dash="dash"), mode="lines",
                    hovertemplate="Año %{x}: $%{y:,.0f}<extra>Valor activo</extra>"))
                fig_cmp.update_layout(
                    height=340, margin=dict(t=20, b=20, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(title=dict(text="Año", font=dict(color="#4A5568", size=11)),
                               tickfont=dict(color="#4A5568")),
                    yaxis=dict(title=dict(text="USD", font=dict(color="#4A5568", size=11)),
                               tickfont=dict(color="#4A5568"), tickformat="$,.0f"),
                    legend=dict(font=dict(color="#4A5568", size=11), bgcolor="rgba(255,255,255,0.8)"),
                    hovermode="x unified",
                )
                st.plotly_chart(fig_cmp, use_container_width=True)

                # ── Resumen patrimonial al final del plazo ────────────────────────
                val_final = cum_valor_activo[-1]
                egreso_neto = cum_compra_neta[-1]
                patrimonio_neto = val_final - egreso_neto
                st.markdown(f"""
                <div style="background:#1E2D3D;border-radius:6px;padding:14px 20px;margin-top:4px;">
                    <div style="font-size:9px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;
                                font-weight:700;margin-bottom:10px;">Posición Patrimonial al Año {plazo}</div>
                    <div style="display:flex;gap:32px;flex-wrap:wrap;">
                        <div><div style="font-size:10px;color:#8AA8C0;">Valor del activo</div>
                             <div style="font-size:16px;font-weight:700;color:#FFFFFF;">${val_final:,.0f}</div></div>
                        <div><div style="font-size:10px;color:#8AA8C0;">Egreso neto (compra − escudo fiscal)</div>
                             <div style="font-size:16px;font-weight:700;color:#FFFFFF;">${egreso_neto:,.0f}</div></div>
                        <div><div style="font-size:10px;color:#8AA8C0;">Arrendamiento pagado (sin activo)</div>
                             <div style="font-size:16px;font-weight:700;color:#B8904A;">${cum_alq[-1]:,.0f}</div></div>
                        <div><div style="font-size:10px;color:#8AA8C0;">Patrimonio neto generado</div>
                             <div style="font-size:16px;font-weight:700;color:#{'6BAE90' if patrimonio_neto > 0 else 'E07070'};">${patrimonio_neto:,.0f}</div></div>
                    </div>
                </div>""", unsafe_allow_html=True)
            else:
                st.markdown('<div class="alert-legal">Ingresa la renta de mercado equivalente en el panel izquierdo para activar la comparativa Comprar vs. Arrendar.</div>', unsafe_allow_html=True)

        # TAB 6: RESUMEN IA
        with ind_tabs[5]:
            rsm = st.session_state.get("ind_resumen")
            if not rsm:
                st.markdown(
                    '<div style="background:#F7F5F1;border:1px solid #D8D4CC;border-radius:8px;'
                    'padding:36px 32px;text-align:center;margin-top:8px;">'
                    '<div style="font-size:9px;color:#9A9080;letter-spacing:3px;text-transform:uppercase;'
                    'font-weight:600;margin-bottom:12px;">Análisis IA</div>'
                    '<div style="font-size:16px;font-weight:600;color:#1E2D3D;margin-bottom:8px;">'
                    'Resumen Ejecutivo</div>'
                    '<div style="width:36px;height:2px;background:#B8904A;margin:12px auto;"></div>'
                    '<div style="font-size:13px;color:#7A7268;line-height:1.7;max-width:480px;margin:0 auto 24px;">'
                    'Genera un análisis ejecutivo con recomendación de inversión, argumentos clave y riesgos, '
                    'redactado desde la perspectiva de Osterling Advisory.'
                    '</div>',
                    unsafe_allow_html=True
                )
                st.markdown("</div>", unsafe_allow_html=True)
            if st.button("GENERAR RESUMEN EJECUTIVO", use_container_width=True, type="primary", key="btn_ind_rsm"):
                _r_copy = dict(r)
                st.session_state.ind_resumen = _run_with_retry(
                    lambda _rc=_r_copy: generar_resumen_ejecutivo_ia("industrial", _rc),
                    "Generando resumen ejecutivo…"
                )
                st.rerun()
            if rsm:
                _rec = rsm.get("recomendacion", "evaluar_con_condiciones")
                _rec_cfg = {
                    "comprar":                ("#1A4731", "#E8F5EE", "RECOMENDADO — COMPRAR"),
                    "evaluar_con_condiciones":("#7A4F1A", "#FFF8EE", "EVALUAR CON CONDICIONES"),
                    "no_recomendado":         ("#7A1A1A", "#FFF0F0", "NO RECOMENDADO"),
                }.get(_rec, ("#1E2D3D", "#F5F2ED", "—"))
                _rc, _rbg, _retiq = _rec_cfg

                st.markdown(f"""
                <div style="background:{_rbg};border:1px solid {_rc};border-left:5px solid {_rc};
                            border-radius:8px;padding:22px 28px;margin-bottom:20px;">
                    <div style="font-size:9px;letter-spacing:3px;color:{_rc};text-transform:uppercase;
                                font-weight:700;opacity:0.7;margin-bottom:6px;">Recomendación</div>
                    <div style="font-size:20px;font-weight:700;color:{_rc};margin-bottom:8px;">{_retiq}</div>
                    <div style="font-size:15px;font-weight:600;color:{_rc};margin-bottom:12px;line-height:1.4;">
                        {rsm.get('titulo','')}</div>
                    <div style="font-size:13px;color:{_rc};opacity:0.9;line-height:1.7;">
                        {rsm.get('resumen','')}</div>
                </div>""", unsafe_allow_html=True)

                _ra1, _ra2 = st.columns(2)
                with _ra1:
                    st.markdown('<div class="section-title">A favor</div>', unsafe_allow_html=True)
                    for a in (rsm.get("argumentos_favor") or []):
                        st.markdown(f'<div class="alert-legal" style="margin-bottom:6px;">✓ {a}</div>', unsafe_allow_html=True)
                with _ra2:
                    st.markdown('<div class="section-title">Riesgos</div>', unsafe_allow_html=True)
                    for rk in (rsm.get("riesgos") or []):
                        st.markdown(f'<div class="alert-gold" style="margin-bottom:6px;">⚠ {rk}</div>', unsafe_allow_html=True)

                st.markdown(
                    f'<div style="background:#1E2D3D;border-radius:6px;padding:16px 22px;margin-top:16px;">'
                    f'<div style="font-size:9px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;font-weight:600;margin-bottom:6px;">Conclusión</div>'
                    f'<div style="font-size:13px;color:#FFFFFF;line-height:1.7;">{rsm.get("conclusion","")}</div>'
                    f'</div>', unsafe_allow_html=True)

                if st.button("REGENERAR", key="btn_ind_rsm_regen"):
                    st.session_state.ind_resumen = None
                    st.rerun()

        # TAB 5: FACTIBILIDAD
        with ind_tabs[4]:
            fac = st.session_state.get("industrial_factibilidad")
            if not fac:
                st.markdown(
                    '<div style="background:#F7F5F1;border:1px solid #D8D4CC;border-radius:8px;'
                    'padding:36px 32px;text-align:center;margin-top:8px;">'
                    '<div style="font-size:9px;color:#9A9080;letter-spacing:3px;text-transform:uppercase;'
                    'font-weight:600;margin-bottom:12px;">Análisis Opcional</div>'
                    '<div style="font-size:16px;font-weight:600;color:#1E2D3D;margin-bottom:8px;">'
                    'Factibilidad Técnica y Legal</div>'
                    '<div style="width:36px;height:2px;background:#B8904A;margin:12px auto;"></div>'
                    '<div style="font-size:13px;color:#7A7268;line-height:1.7;max-width:480px;margin:0 auto;">'
                    'Adjunta la <strong>Partida Registral</strong>, el <strong>Certificado de Parámetros</strong> '
                    'y/o el <strong>Certificado de Zonificación y Vías</strong> en el panel izquierdo, '
                    'luego presiona <strong>ANALIZAR DOCUMENTOS</strong> para obtener:'
                    '<br><br>✓ Compatibilidad de zonificación con la actividad<br>'
                    '✓ Restricciones técnicas de acceso y altura<br>'
                    '✓ Estado registral: cargas, hipotecas, medidas cautelares'
                    '</div></div>',
                    unsafe_allow_html=True
                )
            else:
                sem_g = fac.get("semaforo_global", "amarillo").lower()
                sem_t = fac.get("semaforo_tecnico", "amarillo").lower()
                sem_l = fac.get("semaforo_legal", "amarillo").lower()

                _SEM = {
                    "verde":    ("#1A4731", "#E8F5EE"),
                    "amarillo": ("#7A4F1A", "#FFF8EE"),
                    "rojo":     ("#7A1A1A", "#FFF0F0"),
                }
                _ETIQ = {
                    "verde": "SIN ALERTAS CRÍTICAS",
                    "amarillo": "OBSERVACIONES",
                    "rojo": "ALERTAS CRÍTICAS",
                }
                gc, gbg = _SEM.get(sem_g, ("#1E2D3D", "#F5F2ED"))

                # Semáforo global
                st.markdown(f"""
                <div style="background:{gbg};border:1px solid {gc};border-left:4px solid {gc};
                            border-radius:8px;padding:20px 24px;margin-bottom:20px;">
                    <div style="font-size:9px;letter-spacing:3px;color:{gc};text-transform:uppercase;
                                font-weight:700;opacity:0.7;margin-bottom:6px;">Evaluación Global</div>
                    <div style="font-size:20px;font-weight:700;color:{gc};margin-bottom:10px;">{_ETIQ.get(sem_g,'—')}</div>
                    <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:12px;">
                        <div style="font-size:11px;color:{_SEM.get(sem_t,('',''))[0]};background:{_SEM.get(sem_t,('','#F5F2ED'))[1]};
                                    padding:4px 12px;border-radius:4px;font-weight:600;">
                            ● Técnico: {sem_t.upper()}</div>
                        <div style="font-size:11px;color:{_SEM.get(sem_l,('',''))[0]};background:{_SEM.get(sem_l,('','#F5F2ED'))[1]};
                                    padding:4px 12px;border-radius:4px;font-weight:600;">
                            ● Legal: {sem_l.upper()}</div>
                    </div>
                    <div style="font-size:13px;color:{gc};opacity:0.85;line-height:1.6;margin-bottom:6px;">
                        {fac.get('resumen_tecnico','—')}</div>
                    <div style="font-size:13px;color:{gc};opacity:0.85;line-height:1.6;">
                        {fac.get('resumen_legal','—')}</div>
                </div>""", unsafe_allow_html=True)

                # ANÁLISIS TÉCNICO
                st.markdown('<div class="section-title">Factibilidad Técnica</div>', unsafe_allow_html=True)
                ft1, ft2 = st.columns(2)
                _zon_cert = fac.get("zonificacion_certificada") or "—"
                _compat = fac.get("compatible_actividad")
                _compat_icon = "✓" if _compat is True else ("✗" if _compat is False else "—")
                _compat_col = "#1A4731" if _compat is True else ("#7A1A1A" if _compat is False else "#9A9080")
                ft1.metric("Zonificación certificada", _zon_cert)
                ft2.metric("Compatible con actividad", _compat_icon)

                nota_compat = fac.get("nota_compatibilidad", "")
                if nota_compat:
                    st.markdown(f'<div class="alert-gold">{nota_compat}</div>', unsafe_allow_html=True)

                # Actividades
                act_perm  = fac.get("actividades_permitidas", []) or []
                act_cond  = fac.get("actividades_condicionadas", []) or []
                act_proh  = fac.get("actividades_prohibidas", []) or []
                if act_perm or act_cond or act_proh:
                    fa1, fa2, fa3 = st.columns(3)
                    with fa1:
                        st.markdown('<div style="font-size:9px;color:#1A4731;letter-spacing:2px;text-transform:uppercase;font-weight:700;margin-bottom:6px;">Permitidas</div>', unsafe_allow_html=True)
                        for a in act_perm:
                            st.markdown(f'<div style="font-size:12px;color:#1E2D3D;padding:3px 0;">✓ {a}</div>', unsafe_allow_html=True)
                    with fa2:
                        st.markdown('<div style="font-size:9px;color:#7A4F1A;letter-spacing:2px;text-transform:uppercase;font-weight:700;margin-bottom:6px;">Condicionadas</div>', unsafe_allow_html=True)
                        for a in act_cond:
                            st.markdown(f'<div style="font-size:12px;color:#1E2D3D;padding:3px 0;">⚠ {a}</div>', unsafe_allow_html=True)
                    with fa3:
                        st.markdown('<div style="font-size:9px;color:#7A1A1A;letter-spacing:2px;text-transform:uppercase;font-weight:700;margin-bottom:6px;">Prohibidas</div>', unsafe_allow_html=True)
                        for a in act_proh:
                            st.markdown(f'<div style="font-size:12px;color:#1E2D3D;padding:3px 0;">✗ {a}</div>', unsafe_allow_html=True)

                # Restricciones
                restr = fac.get("restricciones_especiales", []) or []
                alt_max = fac.get("restricciones_altura_m")
                acceso_pesado = fac.get("acceso_vehiculos_pesados")
                vias = fac.get("vias_frente", []) or []
                if alt_max or acceso_pesado is not None or restr or vias:
                    st.markdown('<div class="section-title">Restricciones y Accesos</div>', unsafe_allow_html=True)
                    fr1, fr2, fr3 = st.columns(3)
                    fr1.metric("Altura máxima", f"{alt_max} m" if alt_max else "No especificada")
                    _acc_icon = "✓ Permitido" if acceso_pesado is True else ("✗ Restringido" if acceso_pesado is False else "—")
                    fr2.metric("Vehículos pesados", _acc_icon)
                    fr3.metric("Vías de frente", str(len(vias)) if vias else "—")
                    if vias:
                        for v in vias:
                            _ancho = f" · {v.get('ancho_ml')} ml" if v.get('ancho_ml') else ""
                            st.markdown(f'<div class="alert-legal">'
                                        f'<strong>{v.get("nombre","—")}</strong> — {v.get("tipo","—")}{_ancho}</div>',
                                        unsafe_allow_html=True)
                    for rs in restr:
                        st.markdown(f'<div class="alert-gold">⚠ {rs}</div>', unsafe_allow_html=True)

                # ANÁLISIS LEGAL
                st.markdown('<div class="section-title">Estado Registral</div>', unsafe_allow_html=True)
                prop_l = fac.get("propietarios_partida", []) or []
                area_r = fac.get("area_registral_m2")
                partida_n = fac.get("partida_numero")
                dir_r = fac.get("direccion_partida")
                fl1, fl2, fl3 = st.columns(3)
                fl1.metric("N° Partida", partida_n or "—")
                fl2.metric("Área registral", f"{area_r:,.2f} m²" if area_r else "—")
                fl3.metric("Propietario(s)", str(len(prop_l)) if prop_l else "—")
                if prop_l:
                    st.markdown('<div class="alert-legal"><strong>Titular(es):</strong> ' +
                                ' · '.join(prop_l) + '</div>', unsafe_allow_html=True)
                if dir_r:
                    st.markdown(f'<div class="alert-legal"><strong>Dirección registral:</strong> {dir_r}</div>',
                                unsafe_allow_html=True)

                hipotecas = fac.get("hipotecas_vigentes", []) or []
                cargas    = fac.get("cargas_vigentes", []) or []
                medidas   = fac.get("medidas_cautelares", []) or []
                if hipotecas or cargas or medidas:
                    st.markdown('<div class="section-title">Cargas, Gravámenes e Hipotecas</div>', unsafe_allow_html=True)
                    for h in hipotecas:
                        st.markdown(
                            f'<div style="background:#FFF0F0;border:1px solid #E8B4B4;border-left:3px solid #C0392B;'
                            f'border-radius:6px;padding:12px 16px;margin-bottom:8px;color:#1E2D3D;font-size:13px;">'
                            f'<strong>Hipoteca</strong> — {h.get("acreedor","—")} · {h.get("monto","—")} '
                            f'<span style="font-size:11px;color:#7A1A1A;">({h.get("estado","—")})</span></div>',
                            unsafe_allow_html=True)
                    for c in cargas:
                        st.markdown(
                            f'<div style="background:#FFF8EE;border:1px solid #DFC07A;border-left:3px solid #B8904A;'
                            f'border-radius:6px;padding:12px 16px;margin-bottom:8px;color:#1E2D3D;font-size:13px;">'
                            f'<strong>{c.get("tipo","Carga")}</strong> — {c.get("descripcion","—")}</div>',
                            unsafe_allow_html=True)
                    for m in medidas:
                        st.markdown(
                            f'<div style="background:#FFF0F0;border:1px solid #E8B4B4;border-left:3px solid #C0392B;'
                            f'border-radius:6px;padding:12px 16px;margin-bottom:8px;color:#1E2D3D;font-size:13px;">'
                            f'<strong>Medida Cautelar</strong> — {m.get("tipo","—")}: {m.get("descripcion","—")}</div>',
                            unsafe_allow_html=True)
                elif sem_l == "verde":
                    st.markdown('<div class="alert-legal">✓ Sin cargas, hipotecas ni medidas cautelares detectadas.</div>',
                                unsafe_allow_html=True)

                alertas_t = fac.get("alertas_tecnicas", []) or []
                alertas_l = fac.get("alertas_legales", []) or []
                if alertas_t or alertas_l:
                    st.markdown('<div class="section-title">Alertas</div>', unsafe_allow_html=True)
                    for al in alertas_t:
                        st.markdown(f'<div class="alert-gold">⚠ [TÉCNICO] {al}</div>', unsafe_allow_html=True)
                    for al in alertas_l:
                        _al_style = "alert-gold" if sem_l == "amarillo" else "alert-legal"
                        icon = "🔴" if sem_l == "rojo" else "🟡"
                        st.markdown(f'<div class="{_al_style}">{icon} [LEGAL] {al}</div>', unsafe_allow_html=True)

    else:
        st.markdown(
            '<div style="border-radius:8px;min-height:420px;'
            'background:linear-gradient(160deg,#1A2737 0%,#1E2D3D 60%,#1A2737 100%);'
            'display:flex;align-items:center;justify-content:center;'
            'box-shadow:0 8px 32px rgba(30,45,61,0.18);padding:64px 48px;">'
            '<div style="max-width:600px;width:100%;text-align:center;">'
            '<div style="font-size:9px;color:#B8904A;letter-spacing:4px;text-transform:uppercase;font-weight:600;margin-bottom:16px;">Osterling Advisory</div>'
            '<div style="font-size:28px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;margin-bottom:8px;">Proyecto Logístico / Industrial</div>'
            '<div style="width:48px;height:2px;background:#B8904A;margin:16px auto;"></div>'
            '<div style="font-size:13px;color:#B0C0D0;line-height:1.7;margin-bottom:32px;">'
            'Evalúa la viabilidad de compra de un activo industrial o logístico. '
            'Ingresa los datos del terreno, tipo de nave y condiciones de financiamiento '
            'para obtener: costo total del proyecto, cuota mensual, yield, payback '
            'y comparativa compra vs. arrendamiento.'
            '</div>'
            '<div style="display:flex;gap:24px;justify-content:center;flex-wrap:wrap;">'
            '<div style="background:rgba(184,144,74,0.1);border:1px solid rgba(184,144,74,0.3);'
            'border-radius:6px;padding:14px 20px;min-width:120px;">'
            '<div style="font-size:20px;font-weight:700;color:#B8904A;">I1–I4</div>'
            '<div style="font-size:10px;color:#8AA8C0;letter-spacing:1.5px;text-transform:uppercase;margin-top:4px;">Zonificaciones</div>'
            '</div>'
            '<div style="background:rgba(184,144,74,0.1);border:1px solid rgba(184,144,74,0.3);'
            'border-radius:6px;padding:14px 20px;min-width:120px;">'
            '<div style="font-size:20px;font-weight:700;color:#B8904A;">4</div>'
            '<div style="font-size:10px;color:#8AA8C0;letter-spacing:1.5px;text-transform:uppercase;margin-top:4px;">Tipos de Nave</div>'
            '</div>'
            '<div style="background:rgba(184,144,74,0.1);border:1px solid rgba(184,144,74,0.3);'
            'border-radius:6px;padding:14px 20px;min-width:120px;">'
            '<div style="font-size:20px;font-weight:700;color:#B8904A;">Yield</div>'
            '<div style="font-size:10px;color:#8AA8C0;letter-spacing:1.5px;text-transform:uppercase;margin-top:4px;">+ DSCR + Payback</div>'
            '</div>'
            '</div>'
            '</div></div>',
            unsafe_allow_html=True
        )

# ═══════════════════════════════════════════════════════
# MÓDULO 3: INMUEBLE RESIDENCIAL
# ═══════════════════════════════════════════════════════

elif tipo_op == "Inmueble Residencial":
    r = st.session_state.get("residencial_result")

    if r:
        st.markdown(
            '<div class="main-header">'
            '<div style="display:flex;align-items:center;justify-content:space-between;">'
            '<div>'
            '<div style="font-size:9px;color:#B8904A;letter-spacing:4px;text-transform:uppercase;font-weight:600;margin-bottom:10px;">Osterling Advisory</div>'
            '<div style="display:flex;align-items:center;gap:18px;">'
            '<span style="font-size:22px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;">ANÁLISIS RESIDENCIAL</span>'
            '<span style="width:1px;height:18px;background:#B8904A;opacity:0.4;display:inline-block;flex-shrink:0;"></span>'
            '<span style="font-size:10px;color:#8AA8C0;letter-spacing:2.5px;text-transform:uppercase;font-weight:500;">'
            + r["uso"] + f" · {r['tasa_anual']:.1f}% TEA · {r['plazo_anos']} años" +
            '</span>'
            '</div></div>'
            '<div style="text-align:right;"><div style="font-size:8px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;font-weight:600;opacity:0.7;">Lima, Perú</div></div>'
            '</div></div>',
            unsafe_allow_html=True
        )

        _rc1, _rc2, _rc3 = st.columns([2, 1, 1])
        with _rc1:
            _res_cmp_label = st.text_input("Nombre del escenario", placeholder="Ej: Depto Miraflores 80m²",
                                            label_visibility="collapsed", key="res_cmp_label")
        with _rc2:
            if st.button("GUARDAR EN COMPARATIVA", use_container_width=True, key="btn_res_cmp"):
                _lbl = _res_cmp_label.strip() or f"Escenario {len(st.session_state.res_comparativa)+1}"
                _entry = {"label": _lbl, "r": dict(r)}
                existing = [e["label"] for e in st.session_state.res_comparativa]
                if _lbl in existing:
                    st.session_state.res_comparativa[existing.index(_lbl)] = _entry
                elif len(st.session_state.res_comparativa) < 3:
                    st.session_state.res_comparativa.append(_entry)
                else:
                    st.session_state.res_comparativa[2] = _entry
                st.toast(f"✓ '{_lbl}' guardado en comparativa")
        with _rc3:
            if st.session_state.res_comparativa and st.button("LIMPIAR COMPARATIVA", use_container_width=True, key="btn_res_cmp_clear"):
                st.session_state.res_comparativa = []
                st.rerun()

        # ── Property Hero Banner ─────────────────────────────
        import base64 as _b64h
        _hero_fotos = st.session_state.get("res_fotos_bytes") or []
        _hero_zona  = r.get("zona", "—")
        _hero_precio = r.get("precio", 0)
        _hero_m2    = r.get("m2", 0)
        _hero_dorm  = r.get("dormitorios", "—")
        _hero_ppm2  = r.get("precio_m2", 0)
        _hero_yield = r.get("yield_bruto", 0)

        if _hero_fotos:
            try:
                _b64_hero = _b64h.b64encode(_hero_fotos[0]).decode()
                _hero_photo_css = f"url('data:image/jpeg;base64,{_b64_hero}') center/cover no-repeat"
            except Exception:
                _hero_photo_css = "linear-gradient(135deg,#1E2D3D 0%,#2A4060 100%)"
        else:
            _hero_photo_css = "linear-gradient(135deg,#1E2D3D 0%,#2A4060 100%)"

        st.markdown(f"""
        <div style="position:relative;border-radius:16px;overflow:hidden;margin-bottom:20px;
                    box-shadow:0 6px 30px rgba(30,45,61,0.22);">
            <div style="background:{_hero_photo_css};height:220px;"></div>
            <div style="position:absolute;inset:0;background:linear-gradient(to bottom,
                        rgba(0,0,0,0.0) 0%,rgba(0,0,0,0.75) 100%);
                        display:flex;flex-direction:column;justify-content:flex-end;
                        padding:24px 28px;">
                <div style="font-size:9px;color:rgba(255,255,255,0.60);letter-spacing:3px;
                            text-transform:uppercase;margin-bottom:6px;">
                    Análisis de Inmueble Residencial · FACTIS
                </div>
                <div style="font-size:28px;font-weight:800;color:#FFFFFF;line-height:1.15;
                            text-shadow:0 2px 8px rgba(0,0,0,0.5);">
                    {_hero_zona} &nbsp;·&nbsp; {_hero_dorm}
                </div>
                <div style="display:flex;gap:20px;margin-top:12px;flex-wrap:wrap;">
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;
                                    letter-spacing:1px;">Precio</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">${_hero_precio:,}</div>
                    </div>
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;
                                    letter-spacing:1px;">Área</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_hero_m2} m²</div>
                    </div>
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;
                                    letter-spacing:1px;">USD/m²</div>
                        <div style="font-size:20px;font-weight:700;color:#FFFFFF;">${_hero_ppm2:,}</div>
                    </div>
                    {"" if _hero_yield == 0 else f'<div><div style="font-size:9px;color:rgba(255,255,255,0.55);text-transform:uppercase;letter-spacing:1px;">Yield bruto</div><div style="font-size:20px;font-weight:700;color:#FFFFFF;">{_hero_yield:.1f}%</div></div>'}
                </div>
            </div>
        </div>""", unsafe_allow_html=True)

        res_tab_labels = ["Mercado", "Crédito Hipotecario", "Inversión"] if r['uso'] in ["Inversión para alquilar", "Evaluación para venta"] else ["Mercado", "Crédito Hipotecario", "Escenarios"]
        res_tabs = st.tabs(res_tab_labels + ["Comparativa", "Amortización", "Legal", "Resumen IA", "Documentos"])

        # TAB 0: MERCADO
        with res_tabs[0]:
            # ── District Profile Hero ─────────────────────────────
            _zona_key    = r.get("zona", "")
            _m_data      = MERCADO.get(_zona_key, {})
            _p2br        = _m_data.get("precio_2br", 0)
            _p1br        = _m_data.get("precio_1br", 0)
            _p3br        = _m_data.get("precio_3br", 0)
            _yield_z     = _m_data.get("yield_mercado_pct", 0)
            _var_z       = _m_data.get("variacion_anual_pct", 0)
            _alq_z       = _m_data.get("alquiler_m2_mes", 0)

            # Tier classification
            if _p2br >= 2500:   _tier_name, _tier_col, _tier_bg = "PREMIUM",       "#FFFFFF", "#1E2D3D"
            elif _p2br >= 2000: _tier_name, _tier_col, _tier_bg = "ALTO",          "#FFFFFF", "#B8904A"
            elif _p2br >= 1500: _tier_name, _tier_col, _tier_bg = "RESIDENCIAL",   "#FFFFFF", "#4A7A6B"
            elif _p2br >= 1000: _tier_name, _tier_col, _tier_bg = "CONSOLIDADO",   "#FFFFFF", "#5A6A7A"
            else:               _tier_name, _tier_col, _tier_bg = "EMERGENTE",     "#FFFFFF", "#8A7A6A"

            # Investment grade
            if _yield_z >= 6 and _var_z >= 3:  _grade, _grade_col = "A",   "#1A4731"
            elif _yield_z >= 5.5 or _var_z >= 2: _grade, _grade_col = "B+", "#3A6A50"
            elif _yield_z >= 5 or _var_z >= 0:  _grade, _grade_col = "B",  "#7A5500"
            else:                                _grade, _grade_col = "C",  "#7A1A1A"

            _trend_icon  = "↑" if _var_z > 1 else ("→" if abs(_var_z) <= 1 else "↓")
            _trend_col   = "#1A4731" if _var_z > 1 else ("#7A5500" if abs(_var_z) <= 1 else "#7A1A1A")

            st.markdown(f"""
            <div style="background:linear-gradient(135deg,#1E2D3D 0%,#2A4060 100%);
                        border-radius:12px;padding:24px 28px;margin-bottom:20px;
                        box-shadow:0 4px 20px rgba(30,45,61,0.20);">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;flex-wrap:wrap;gap:12px;">
                    <div>
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);letter-spacing:3px;
                                    text-transform:uppercase;margin-bottom:6px;">Perfil de Distrito · Urbania 2025</div>
                        <div style="font-size:28px;font-weight:800;color:#FFFFFF;line-height:1.1;">{_zona_key}</div>
                        <div style="margin-top:8px;display:flex;gap:8px;flex-wrap:wrap;">
                            <span style="background:{_tier_bg};color:{_tier_col};font-size:9px;font-weight:700;
                                         padding:3px 10px;border-radius:12px;letter-spacing:1.5px;">{_tier_name}</span>
                            <span style="background:rgba(255,255,255,0.12);color:#FFFFFF;font-size:9px;font-weight:700;
                                         padding:3px 10px;border-radius:12px;letter-spacing:1px;">
                                         Alquiler ${_alq_z:.1f}/m²/mes</span>
                        </div>
                    </div>
                    <div style="text-align:center;background:rgba(255,255,255,0.10);border-radius:10px;
                                padding:14px 20px;min-width:80px;">
                        <div style="font-size:9px;color:rgba(255,255,255,0.55);letter-spacing:2px;
                                    text-transform:uppercase;margin-bottom:4px;">Inv. Grade</div>
                        <div style="font-size:36px;font-weight:900;color:#FFFFFF;line-height:1;">{_grade}</div>
                    </div>
                </div>
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px;">
                    <div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:12px 14px;">
                        <div style="font-size:9px;color:rgba(255,255,255,0.5);text-transform:uppercase;
                                    letter-spacing:1px;margin-bottom:4px;">Precio 1D</div>
                        <div style="font-size:15px;font-weight:700;color:#FFFFFF;">${_p1br:,}/m²</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:12px 14px;">
                        <div style="font-size:9px;color:rgba(255,255,255,0.5);text-transform:uppercase;
                                    letter-spacing:1px;margin-bottom:4px;">Precio 2D</div>
                        <div style="font-size:15px;font-weight:700;color:#FFFFFF;">${_p2br:,}/m²</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:12px 14px;">
                        <div style="font-size:9px;color:rgba(255,255,255,0.5);text-transform:uppercase;
                                    letter-spacing:1px;margin-bottom:4px;">Yield Zona</div>
                        <div style="font-size:15px;font-weight:700;color:#FFFFFF;">{_yield_z:.1f}%</div>
                    </div>
                    <div style="background:rgba(255,255,255,0.08);border-radius:8px;padding:12px 14px;">
                        <div style="font-size:9px;color:rgba(255,255,255,0.5);text-transform:uppercase;
                                    letter-spacing:1px;margin-bottom:4px;">Variación 12m</div>
                        <div style="font-size:15px;font-weight:700;color:#FFFFFF;">{_trend_icon} {_var_z:+.1f}%</div>
                    </div>
                </div>
            </div>""", unsafe_allow_html=True)

            # ── Price Gauge ───────────────────────────────────────
            _ppm2_r = r.get("precio_m2", 0)
            _ref_r  = r.get("precio_m2_mercado", 0)
            if _ref_r > 0 and _ppm2_r > 0:
                _gauge_min = int(_ref_r * 0.60)
                _gauge_max = int(_ref_r * 1.50)
                fig_gauge = go.Figure(go.Indicator(
                    mode="gauge+number+delta",
                    value=_ppm2_r,
                    number={"prefix": "$", "suffix": "/m²", "font": {"size": 26, "color": "#1E2D3D"}},
                    delta={"reference": _ref_r, "relative": True, "valueformat": "+.1%",
                           "font": {"size": 13},
                           "increasing": {"color": "#7A1A1A"},
                           "decreasing": {"color": "#1A4731"}},
                    title={"text": "Posición de Precio vs. Mediana de Zona", "font": {"size": 11, "color": "#9A9080"}},
                    gauge={
                        "axis": {"range": [_gauge_min, _gauge_max], "tickformat": "$,.0f",
                                 "tickfont": {"size": 9, "color": "#9A9080"},
                                 "nticks": 6},
                        "bar": {"color": "#B8904A", "thickness": 0.25},
                        "bgcolor": "#F7F5F1",
                        "borderwidth": 0,
                        "steps": [
                            {"range": [_gauge_min, int(_ref_r * 0.92)],    "color": "#E8F5EE"},
                            {"range": [int(_ref_r * 0.92), int(_ref_r * 1.08)], "color": "#FFF8EE"},
                            {"range": [int(_ref_r * 1.08), _gauge_max],   "color": "#FDECEA"},
                        ],
                        "threshold": {"line": {"color": "#1E2D3D", "width": 3},
                                      "thickness": 0.85, "value": _ref_r},
                    }
                ))
                fig_gauge.update_layout(
                    height=240, margin=dict(t=50, b=10, l=30, r=30),
                    paper_bgcolor="rgba(0,0,0,0)", font=dict(family="Inter"),
                )
                st.plotly_chart(fig_gauge, use_container_width=True, config={"displayModeBar": False})
                st.caption("Aguja naranja = precio pagado · Línea negra = mediana de zona (Urbania nov-2025) · Verde = oportunidad · Rojo = sobre mercado")

            # ── Posición de precio (KPIs) ────────────────────────
            _ppm2_r = r.get("precio_m2", 0)
            _ref_r   = r.get("precio_m2_mercado", 0)
            _diff_r  = ((_ppm2_r - _ref_r) / _ref_r * 100) if _ref_r > 0 else 0
            st.markdown('<div class="section-title">Posición de Precio en el Mercado</div>', unsafe_allow_html=True)

            if abs(_diff_r) <= 8:
                _sem_color, _sem_bg, _sem_label = "#1A4731", "#E8F5EE", "EN LÍNEA CON EL MERCADO"
            elif _diff_r > 8:
                _sem_color, _sem_bg, _sem_label = "#7A1A1A", "#FDECEA", "SOBRE EL MERCADO"
            else:
                _sem_color, _sem_bg, _sem_label = "#1A4731", "#E8F5EE", "POR DEBAJO — OPORTUNIDAD"

            pm1, pm2, pm3 = st.columns(3)
            pm1.metric("Precio pagado / m²", f"${_ppm2_r:,.0f}/m²")
            pm2.metric("Mediana zona (Urbania)", f"${_ref_r:,}/m²",
                       delta=f"{_diff_r:+.1f}% vs. mercado",
                       help="Fuente: Índice Urbania Lima, Noviembre 2025")
            pm3.metric("Precio justo estimado", f"${int(r.get('m2',0) * _ref_r):,}",
                       help="Área × mediana de zona")

            st.markdown(
                f'<div style="background:{_sem_bg};border:1px solid {_sem_color};border-left:4px solid {_sem_color};'
                f'border-radius:6px;padding:14px 20px;margin:12px 0;">'
                f'<div style="font-size:9px;color:{_sem_color};letter-spacing:2px;font-weight:700;text-transform:uppercase;">Posición de Mercado</div>'
                f'<div style="font-size:20px;font-weight:800;color:{_sem_color};margin:4px 0;">{_sem_label}</div>'
                f'<div style="font-size:12px;color:{_sem_color};opacity:0.85;">'
                f'El precio pagado (${_ppm2_r:,.0f}/m²) está {abs(_diff_r):.1f}% '
                f'{"sobre" if _diff_r > 0 else "bajo"} la mediana de {r.get("zona","la zona")} (${_ref_r:,}/m²). '
                f'{"Considera negociar." if _diff_r > 8 else ("Precio competitivo — buena entrada." if _diff_r < -8 else "Precio consistente con el mercado.")}'
                f'</div></div>',
                unsafe_allow_html=True
            )

            # ── Alquiler de mercado ─────────────────────────────
            st.markdown('<div class="section-title">Renta de Mercado — Zona</div>', unsafe_allow_html=True)
            _alq_ref_mes = r.get("alquiler_mercado_m2", 0) * r.get("m2", 0)
            _alq_actual = r.get("alquiler_mes", 0)

            am1, am2, am3 = st.columns(3)
            am1.metric("Alquiler mercado estimado", f"${_alq_ref_mes:,.0f}/mes",
                       help=f"${r.get('alquiler_mercado_m2',0):.1f} USD/m²/mes · Fuente: Urbania nov-25")
            am2.metric("Alquiler ingresado", f"${_alq_actual:,.0f}/mes" if _alq_actual > 0 else "No aplica")
            if _alq_actual > 0 and _alq_ref_mes > 0:
                _diff_alq = (_alq_actual - _alq_ref_mes) / _alq_ref_mes * 100
                am3.metric("Diferencial vs. mercado", f"{_diff_alq:+.1f}%",
                           help="Positivo = renta sobre mercado · Negativo = renta bajo mercado")

            # ── Yield benchmark ─────────────────────────────────
            st.markdown('<div class="section-title">Rentabilidad vs. Mercado</div>', unsafe_allow_html=True)
            _yield_mkt = r.get("yield_mercado_pct", 0)
            _yield_this = r.get("yield_bruto", 0)
            _yield_neto = r.get("yield_neto", 0)

            ym1, ym2, ym3, ym4 = st.columns(4)
            ym1.metric("Yield bruto este inmueble", f"{_yield_this:.1f}%")
            ym2.metric("Yield neto este inmueble", f"{_yield_neto:.1f}%")
            ym3.metric(f"Yield promedio zona", f"{_yield_mkt:.1f}%",
                       help="Fuente: Índice Urbania Lima, Noviembre 2025")
            if _yield_this > 0 and _yield_mkt > 0:
                _beat = _yield_this - _yield_mkt
                ym4.metric("Diferencial", f"{_beat:+.1f}pp",
                           delta="sobre mercado" if _beat >= 0 else "bajo mercado")

            # ── Tendencia del distrito ───────────────────────────
            st.markdown('<div class="section-title">Tendencia del Distrito — Últimos 12 Meses</div>', unsafe_allow_html=True)
            _var = r.get("variacion_anual_pct", 0)
            _var_color = "#1A4731" if _var >= 3 else ("#7A5500" if _var >= 0 else "#7A1A1A")
            _var_icon = "↑" if _var > 1 else ("→" if abs(_var) <= 1 else "↓")
            _var_label = "Distrito en alza" if _var >= 3 else ("Estable" if abs(_var) <= 1 else "Distrito en baja")

            td1, td2 = st.columns(2)
            td1.metric("Variación anual precio zona", f"{_var:+.1f}%",
                       help="Fuente: Índice Urbania Lima, Noviembre 2025")
            td2.metric("Inflación 12m (Perú)", "+1.4%",
                       help="Fuente: Banco Central de Perú · nov-25")

            _real_var = _var - 1.4
            st.markdown(
                f'<div style="background:#F5F2ED;border-left:3px solid {_var_color};border-radius:4px;'
                f'padding:10px 16px;margin:8px 0;">'
                f'<span style="font-size:22px;color:{_var_color};">{_var_icon}</span> '
                f'<strong style="color:{_var_color};">{_var_label}</strong> — '
                f'Variación real (descontando inflación): <strong style="color:{_var_color};">{_real_var:+.1f}%</strong>. '
                f'{"La zona genera plusvalía real para el comprador." if _real_var > 0 else "El inmueble pierde valor real contra inflación — negociar precio."}'
                f'</div>',
                unsafe_allow_html=True
            )

            # ── Valor a futuro con tasa real ─────────────────────
            st.markdown('<div class="section-title">Proyección de Valor</div>', unsafe_allow_html=True)
            _tasa_apr = r.get("tasa_apreciacion_pct", 4.0)
            pv1, pv2, pv3 = st.columns(3)
            pv1.metric("Valor actual", f"${r['precio']:,.0f}")
            pv2.metric("Valor estimado 5 años", f"${r['valor_5']:,.0f}",
                       f"+${r['ganancia_capital_5']:,.0f} ({_tasa_apr:.1f}%/año)")
            pv3.metric("Valor estimado 10 años", f"${r['valor_10']:,.0f}",
                       f"+${r['ganancia_capital_10']:,.0f}")
            st.caption(f"Tasa de apreciación usada: {_tasa_apr:.1f}% anual (variación anual de la zona). Fuente: Urbania nov-25.")

        # TAB 1: CRÉDITO HIPOTECARIO
        with res_tabs[1]:
            st.markdown('<div class="section-title">Estructura del Financiamiento</div>', unsafe_allow_html=True)
            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.metric("Precio de Compra", f"${r['precio']:,.0f}")
            rc2.metric("Pago inicial (Capital Propio)", f"${r['pie']:,.0f}", f"{r['pct_pie']:.0f}%")
            rc3.metric("Monto del Crédito", f"${r['monto_credito']:,.0f}", f"{100-r['pct_pie']:.0f}%")
            rc4.metric("Cuota Mensual", f"${r['cuota_mensual']:,.0f}" if r['cuota_mensual'] > 0 else "Contado")

            st.markdown('<div class="section-title">Resumen del Crédito</div>', unsafe_allow_html=True)
            rr1, rr2, rr3 = st.columns(3)
            rr1.metric("Total a Pagar", f"${r['total_pagado']:,.0f}", f"Plazo {r['plazo_anos']} años")
            rr2.metric("Total Intereses", f"${r['total_intereses']:,.0f}", f"{r['tasa_anual']:.2f}% TEA")
            rr3.metric("Ingreso Mínimo Sugerido", f"${r['ingreso_minimo']:,.0f}/mes", "Regla 30% ingresos")

            st.markdown(
                '<div class="alert-gold">'
                f'<strong>Ingreso mínimo recomendado:</strong> Los bancos generalmente exigen que la cuota hipotecaria '
                f'no supere el 30% del ingreso neto mensual. Con una cuota de <strong>${r["cuota_mensual"]:,.0f}</strong>, '
                f'se recomienda acreditar ingresos mínimos de <strong>${r["ingreso_minimo"]:,.0f}/mes</strong>.'
                '</div>',
                unsafe_allow_html=True
            )

            if r['monto_credito'] > 0:
                fig_pie_res = go.Figure(go.Pie(
                    labels=["Pago inicial (Capital Propio)", "Financiado por banco", "Intereses totales"],
                    values=[r['pie'], r['monto_credito'], r['total_intereses']],
                    marker_colors=["#1E2D3D", "#B8904A", "#C8A86A"],
                    textfont=dict(size=11, color="#FFFFFF"),
                    hole=0.40,
                ))
                fig_pie_res.update_layout(
                    height=300, margin=dict(t=10, b=10, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    legend=dict(font=dict(color="#4A5568", size=11)),
                    font=dict(family="Inter"),
                )
                st.plotly_chart(fig_pie_res, use_container_width=True)

        # TAB 2: INVERSIÓN o ESCENARIOS
        with res_tabs[2]:
            if r['uso'] == "Inversión":
                st.markdown('<div class="section-title">Análisis de Rentabilidad</div>', unsafe_allow_html=True)
                ri1, ri2, ri3, ri4 = st.columns(4)
                ri1.metric("Alquiler Mensual", f"${r['alquiler_mes']:,.0f}")
                ri2.metric("Yield Bruto Anual", f"{r['yield_bruto']:.1f}%")
                ri3.metric("Yield Neto Anual", f"{r['yield_neto']:.1f}%", f"-${r['gastos_mes']:,.0f}/mes gastos")
                if r['payback_anos']:
                    ri4.metric("Payback", f"{r['payback_anos']:.1f} años")
                else:
                    ri4.metric("Payback", "N/A")

                # ── Proyección indexada (solo contratos plurianuales) ──
                if r.get("tipo_contrato") == "Plurianual (3+ años)" and r.get("ajuste_anual_pct", 0) > 0:
                    _raj  = r["ajuste_anual_pct"]
                    _rini = r["inicio_ajuste_ano"]
                    st.markdown(
                        f'<div style="background:#F0F4FF;border-left:3px solid #3B5BDB;border-radius:6px;'
                        f'padding:10px 14px;margin:12px 0 6px;font-size:12px;">'
                        f'<strong>Contrato plurianual · ajuste +{_raj:.1f}% anual desde año {_rini}</strong><br>'
                        f'La renta crece mientras la cuota hipotecaria permanece fija — '
                        f'el flujo mejora año a año.'
                        f'</div>', unsafe_allow_html=True)
                    _rpi1, _rpi2, _rpi3, _rpi4 = st.columns(4)
                    _rpi1.metric("Alquiler año 1", f"${r['alquiler_mes']:,.0f}/mes")
                    _rpi2.metric("Alquiler año 3", f"${r['alquiler_ano3']:,.0f}/mes",
                                 f"+{((r['alquiler_ano3']/r['alquiler_mes']-1)*100):.1f}%" if r['alquiler_mes'] > 0 else "")
                    _rpi3.metric("Alquiler año 5", f"${r['alquiler_ano5']:,.0f}/mes",
                                 f"+{((r['alquiler_ano5']/r['alquiler_mes']-1)*100):.1f}%" if r['alquiler_mes'] > 0 else "")
                    if r.get("payback_indexado") and r.get("payback_anos"):
                        _rdpb = r["payback_anos"] - r["payback_indexado"]
                        _rpi4.metric("Payback indexado", f"{r['payback_indexado']} años",
                                     f"{_rdpb:.1f} años menos vs renta fija")
                    _rydata = {
                        "Año": ["Año 1 (base)", f"Año 3 (+{_raj:.1f}% × {max(3-_rini+1,0)})", f"Año 5 (+{_raj:.1f}% × {max(5-_rini+1,0)})"],
                        "Alquiler/mes": [f"${r['alquiler_mes']:,.0f}", f"${r['alquiler_ano3']:,.0f}", f"${r['alquiler_ano5']:,.0f}"],
                        "Yield neto": [f"{r['yield_neto']:.1f}%", f"{r['yield_neto_ano3']:.1f}%", f"{r['yield_neto_ano5']:.1f}%"],
                    }
                    st.table(pd.DataFrame(_rydata).set_index("Año"))

                if r['cuota_mensual'] > 0:
                    st.markdown('<div class="section-title">Flujo Mensual Neto</div>', unsafe_allow_html=True)
                    rf1, rf2, rf3 = st.columns(3)
                    flujo = r['flujo_mensual'] or 0
                    rf1.metric("Renta Neta", f"${r['renta_neta_mes']:,.0f}/mes")
                    rf2.metric("Cuota Mensual", f"${r['cuota_mensual']:,.0f}/mes")
                    rf3.metric("Flujo Mensual", f"${flujo:,.0f}" if flujo >= 0 else f"-${abs(flujo):,.0f}",
                               "Positivo" if flujo >= 0 else "Déficit — evaluar pie")

                    st.markdown(
                        '<div class="alert-gold">'
                        f'<strong>Alquiler para autofinanciar:</strong> Necesitas una renta mínima de '
                        f'<strong>${r["alquiler_equilibrio"]:,.0f}/mes</strong> para cubrir la cuota más los gastos operativos.'
                        '</div>',
                        unsafe_allow_html=True
                    )

                st.markdown('<div class="section-title">Apreciación del Capital (Lima +4% anual est.)</div>', unsafe_allow_html=True)
                rap1, rap2 = st.columns(2)
                rap1.metric("Valor Estimado a 5 años", f"${r['valor_5']:,.0f}", f"+${r['ganancia_capital_5']:,.0f}")
                rap2.metric("Valor Estimado a 10 años", f"${r['valor_10']:,.0f}", f"+${r['ganancia_capital_10']:,.0f}")

            else:
                st.markdown('<div class="section-title">Escenarios de Financiamiento</div>', unsafe_allow_html=True)
                precio_base = r['precio']
                escenarios = [
                    ("Conservador", 10, 9.5, 25),
                    ("Estándar", 20, 8.5, 20),
                    ("Agresivo (comprador)", 30, 7.5, 15),
                ]
                esc_data = []
                for name, pct, tasa, plazo in escenarios:
                    c_res = calcular_residencial({"precio": precio_base, "pct_pie": pct, "tasa_anual": tasa, "plazo_anos": plazo, "uso": "Vivienda propia", "alquiler_mes": 0, "gastos_mes": 0})
                    esc_data.append({"Escenario": name, "Pago inicial %": f"{pct}%", "TEA %": f"{tasa}%", "Plazo": f"{plazo}a", "Cuota": f"${c_res['cuota_mensual']:,.0f}", "Ingreso Mín.": f"${c_res['ingreso_minimo']:,.0f}", "Total Pagado": f"${c_res['total_pagado']:,.0f}"})
                _esc_cols = ["Pago inicial %", "TEA %", "Plazo", "Cuota", "Ingreso Mín.", "Total Pagado"]
                _th = "".join(f'<th style="background:#1E2D3D;color:#FFFFFF;padding:10px 14px;font-size:10px;letter-spacing:1px;text-transform:uppercase;font-weight:700;border:1px solid #2A3D51;white-space:nowrap;">{c}</th>' for c in ["Escenario"] + _esc_cols)
                _trows = "".join(
                    '<tr>' + f'<td style="background:#F5F2ED;color:#1E2D3D;padding:9px 14px;font-size:12px;border:1px solid #E0DAD0;font-weight:600;">{d["Escenario"]}</td>' +
                    "".join(f'<td style="background:#FFFFFF;color:#1E2D3D;padding:9px 14px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">{d[c]}</td>' for c in _esc_cols) +
                    '</tr>'
                    for d in esc_data
                )
                st.markdown(f'<div style="overflow-x:auto;"><table style="width:100%;border-collapse:collapse;">'
                            f'<thead><tr>{_th}</tr></thead><tbody>{_trows}</tbody></table></div>',
                            unsafe_allow_html=True)

                st.markdown('<div class="section-title">Apreciación del Capital (Lima +4% anual est.)</div>', unsafe_allow_html=True)
                rav1, rav2 = st.columns(2)
                rav1.metric("Valor Estimado a 5 años", f"${r['valor_5']:,.0f}", f"+${r['ganancia_capital_5']:,.0f}")
                rav2.metric("Valor Estimado a 10 años", f"${r['valor_10']:,.0f}", f"+${r['ganancia_capital_10']:,.0f}")

            # Multi-project comparison (residential)
            if st.session_state.res_comparativa and len(st.session_state.res_comparativa) > 1:
                st.markdown('<div class="section-title">Comparativa de Escenarios</div>', unsafe_allow_html=True)
                _res_cmp_metrics = ["precio", "cuota_mensual", "yield_neto", "payback_anos", "flujo_mensual", "ingreso_minimo"]
                _res_cmp_labels  = ["Precio", "Cuota Mensual", "Yield Neto %", "Payback (años)", "Flujo Mensual", "Ingreso Mínimo"]
                _res_cmp_fmts    = ["${:,.0f}", "${:,.0f}", "{:.1f}%", "{:.1f} a.", "${:,.0f}", "${:,.0f}"]

                _rth = '<th style="background:#1E2D3D;color:#FFFFFF;padding:9px 14px;font-size:10px;letter-spacing:1px;text-transform:uppercase;">Indicador</th>'
                for e in st.session_state.res_comparativa:
                    _rth += f'<th style="background:#1E2D3D;color:#B8904A;padding:9px 14px;font-size:10px;text-align:right;">{e["label"]}</th>'
                _rrows = ""
                for lbl, key, fmt in zip(_res_cmp_labels, _res_cmp_metrics, _res_cmp_fmts):
                    bg_row = "#FFFFFF" if _res_cmp_metrics.index(key) % 2 == 0 else "#F9F7F4"
                    _rrow = f'<td style="background:{bg_row};color:#4A5568;padding:8px 14px;font-size:11px;font-weight:600;border:1px solid #E0DAD0;">{lbl}</td>'
                    vals = [e["r"].get(key) for e in st.session_state.res_comparativa]
                    _hib = key in ["yield_neto", "flujo_mensual"]
                    _lib = key in ["precio", "cuota_mensual", "payback_anos", "ingreso_minimo"]
                    valid = [v for v in vals if v is not None]
                    best = max(valid) if _hib and valid else (min(valid) if _lib and valid else None)
                    for v in vals:
                        try: disp = fmt.format(v) if v is not None else "—"
                        except: disp = "—"
                        is_b = (v == best and best is not None)
                        _rrow += f'<td style="background:{bg_row};color:{"#1A4731" if is_b else "#1E2D3D"};padding:8px 14px;font-size:12px;font-weight:{"700" if is_b else "400"};border:1px solid #E0DAD0;text-align:right;">{disp}</td>'
                    _rrows += f"<tr>{_rrow}</tr>"
                st.markdown(f'<div style="overflow-x:auto;margin-bottom:16px;"><table style="width:100%;border-collapse:collapse;"><thead><tr>{_rth}</tr></thead><tbody>{_rrows}</tbody></table></div>', unsafe_allow_html=True)
                st.caption("Verde = mejor valor para ese indicador.")

        # TAB 3: COMPARATIVA DE INMUEBLES
        with res_tabs[3]:
            st.markdown('<div class="section-title">Comparativa de Inmuebles</div>', unsafe_allow_html=True)

            _comps = st.session_state.get("res_inmuebles_comp", [])

            if not _comps:
                st.markdown('<div class="alert-legal">Agrega inmuebles en el panel izquierdo (sección <strong>COMPARATIVA DE INMUEBLES</strong>) para comparar alternativas de mercado.</div>', unsafe_allow_html=True)
            else:
                import base64 as _b64

                # ── District tier helper ──────────────────────────
                def _tier_badge(zona_key: str) -> str:
                    _pm2 = MERCADO.get(zona_key, {}).get("precio_2br", 0)
                    if _pm2 >= 2500: return ('<span style="background:#1E2D3D;color:#F5F2ED;font-size:9px;font-weight:700;'
                                              'padding:2px 8px;border-radius:10px;letter-spacing:1px;">PREMIUM</span>')
                    if _pm2 >= 2000: return ('<span style="background:#B8904A;color:#FFFFFF;font-size:9px;font-weight:700;'
                                              'padding:2px 8px;border-radius:10px;letter-spacing:1px;">PREMIUM +</span>')
                    if _pm2 >= 1500: return ('<span style="background:#4A7A6B;color:#FFFFFF;font-size:9px;font-weight:700;'
                                              'padding:2px 8px;border-radius:10px;letter-spacing:1px;">RESIDENCIAL</span>')
                    if _pm2 >= 1000: return ('<span style="background:#5A6A7A;color:#FFFFFF;font-size:9px;font-weight:700;'
                                              'padding:2px 8px;border-radius:10px;letter-spacing:1px;">CONSOLIDADO</span>')
                    return ('<span style="background:#8A7A6A;color:#FFFFFF;font-size:9px;font-weight:700;'
                             'padding:2px 8px;border-radius:10px;letter-spacing:1px;">EMERGENTE</span>')

                # ── All properties including current ──────────────
                _all = [{"nombre": "Este inmueble", "is_main": True,
                         "precio": r["precio"], "m2": r.get("m2", 0),
                         "precio_m2": r.get("precio_m2", 0),
                         "alquiler": r.get("alquiler_mes", 0),
                         "yield_bruto": r.get("yield_bruto", 0),
                         "zona": r.get("zona", "—"),
                         "dormitorios": r.get("dormitorios", "—"),
                         "imagen_bytes": (st.session_state.get("res_fotos_bytes") or [None])[0],
                        }] + [dict(c, is_main=False) for c in _comps]

                _best_pm2   = min((c["precio_m2"] for c in _all if c["precio_m2"] > 0), default=0)
                _best_yield = max((c["yield_bruto"] for c in _all), default=0)
                _best_precio = min(c["precio"] for c in _all)

                # ── Property Cards Grid ────────────────────────────
                _GRAD_PALETTES = [
                    "linear-gradient(135deg,#1E2D3D 0%,#2A4060 100%)",
                    "linear-gradient(135deg,#2D3A2E 0%,#3D5C40 100%)",
                    "linear-gradient(135deg,#3A2A1E 0%,#5C4030 100%)",
                    "linear-gradient(135deg,#2A2A3A 0%,#3D3D5C 100%)",
                ]
                _cards_html = '<div style="display:grid;grid-template-columns:repeat(2,1fr);gap:16px;margin-top:8px;">'
                for _ci_idx, _ci in enumerate(_all):
                    _is_main = _ci.get("is_main", False)
                    _img_b = _ci.get("imagen_bytes")
                    if _img_b:
                        try:
                            _img_src = f"data:image/jpeg;base64,{_b64.b64encode(_img_b).decode()}"
                            _photo_css = f"background:url('{_img_src}') center/cover no-repeat;"
                        except Exception:
                            _img_src = None
                            _photo_css = _GRAD_PALETTES[_ci_idx % len(_GRAD_PALETTES)]
                    else:
                        _photo_css = _GRAD_PALETTES[_ci_idx % len(_GRAD_PALETTES)]

                    _border = "2px solid #B8904A" if _is_main else "1px solid #E4E0D8"
                    _label_badge = ('<div style="position:absolute;top:10px;left:10px;background:#B8904A;color:#FFFFFF;'
                                    'font-size:9px;font-weight:700;padding:3px 8px;border-radius:3px;letter-spacing:1px;">▶ ANALIZADO</div>') if _is_main else ""

                    _best_badges = ""
                    if _ci["precio_m2"] == _best_pm2 and _ci["precio_m2"] > 0:
                        _best_badges += '<span style="background:#1A4731;color:#FFFFFF;font-size:8px;font-weight:700;padding:2px 6px;border-radius:2px;margin-right:4px;">✓ MEJOR USD/m²</span>'
                    if _ci["yield_bruto"] == _best_yield and _ci["yield_bruto"] > 0:
                        _best_badges += '<span style="background:#1A4731;color:#FFFFFF;font-size:8px;font-weight:700;padding:2px 6px;border-radius:2px;">✓ MEJOR YIELD</span>'

                    _zona_disp = _ci.get("zona", "—")
                    _tier_html = _tier_badge(_zona_disp) if _zona_disp in MERCADO else ""
                    _dorm_disp = _ci.get("dormitorios", "—")
                    _precio_str = f"${_ci['precio']:,}"
                    _pm2_str    = f"${_ci['precio_m2']:,}/m²" if _ci["precio_m2"] > 0 else "—"
                    _alq_str    = f"${_ci['alquiler']:,}/mes" if _ci.get("alquiler", 0) > 0 else "—"
                    _yield_str  = f"{_ci['yield_bruto']:.1f}%" if _ci.get("yield_bruto", 0) > 0 else "—"
                    _m2_str     = f"{_ci['m2']:,} m²" if _ci.get("m2", 0) > 0 else "—"

                    _cards_html += f'''
                    <div style="border:{_border};border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(30,45,61,0.10);background:#FFFFFF;">
                        <div style="position:relative;height:160px;{_photo_css}">
                            {_label_badge}
                            <div style="position:absolute;bottom:0;left:0;right:0;height:70px;
                                        background:linear-gradient(transparent,rgba(0,0,0,0.65));
                                        padding:10px 14px 12px;display:flex;flex-direction:column;justify-content:flex-end;">
                                <div style="color:#FFFFFF;font-size:18px;font-weight:800;line-height:1.2;">{_precio_str}</div>
                                <div style="color:rgba(255,255,255,0.85);font-size:10px;margin-top:2px;">{_pm2_str} &nbsp;·&nbsp; {_m2_str}</div>
                            </div>
                        </div>
                        <div style="padding:14px 16px;">
                            <div style="font-size:13px;font-weight:700;color:#1E2D3D;margin-bottom:4px;">{_ci["nombre"]}</div>
                            <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
                                <span style="font-size:11px;color:#6A7A8A;">{_zona_disp}</span>
                                {_tier_html}
                            </div>
                            <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:8px;">
                                <div style="background:#F7F5F1;border-radius:6px;padding:8px 10px;">
                                    <div style="font-size:9px;color:#9A9080;text-transform:uppercase;letter-spacing:1px;margin-bottom:2px;">Tipología</div>
                                    <div style="font-size:12px;font-weight:600;color:#1E2D3D;">{_dorm_disp}</div>
                                </div>
                                <div style="background:#F7F5F1;border-radius:6px;padding:8px 10px;">
                                    <div style="font-size:9px;color:#9A9080;text-transform:uppercase;letter-spacing:1px;margin-bottom:2px;">Alquiler est.</div>
                                    <div style="font-size:12px;font-weight:600;color:#1E2D3D;">{_alq_str}</div>
                                </div>
                                <div style="background:#F7F5F1;border-radius:6px;padding:8px 10px;">
                                    <div style="font-size:9px;color:#9A9080;text-transform:uppercase;letter-spacing:1px;margin-bottom:2px;">Yield bruto</div>
                                    <div style="font-size:12px;font-weight:600;color:{"#1A4731" if _ci.get("yield_bruto",0)>0 else "#9A9080"};">{_yield_str}</div>
                                </div>
                                <div style="background:#F7F5F1;border-radius:6px;padding:8px 10px;">
                                    <div style="font-size:9px;color:#9A9080;text-transform:uppercase;letter-spacing:1px;margin-bottom:2px;">USD/m²</div>
                                    <div style="font-size:12px;font-weight:600;color:#1E2D3D;">{_pm2_str}</div>
                                </div>
                            </div>
                            {f'<div style="margin-top:4px;">{_best_badges}</div>' if _best_badges else ""}
                        </div>
                    </div>'''

                _cards_html += '</div>'
                st.markdown(_cards_html, unsafe_allow_html=True)

                # ── Comparison chart ───────────────────────────────
                if any(c["precio_m2"] > 0 for c in _all):
                    _nombres = [("★ " + c["nombre"]) if c.get("is_main") else c["nombre"] for c in _all]
                    _pm2s = [c["precio_m2"] for c in _all]
                    _colors = ["#B8904A" if c.get("is_main") else ("#4A7A6B" if c["precio_m2"] == _best_pm2 else "#C8D4DE") for c in _all]
                    fig_comp = go.Figure(go.Bar(
                        x=_nombres, y=_pm2s, marker_color=_colors, marker_line_width=0,
                        text=[f"${v:,}/m²" for v in _pm2s], textposition="outside",
                        textfont=dict(size=10, color="#1E2D3D"),
                    ))
                    fig_comp.update_layout(
                        height=300, yaxis_title="USD/m²",
                        title=dict(text="Precio por m² — Comparativa de mercado", font=dict(size=11, color="#9A9080"), x=0),
                        margin=dict(t=40, b=10, l=0, r=0),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        font=dict(color="#1E2D3D", family="Inter"),
                        xaxis=dict(showgrid=False),
                        yaxis=dict(tickformat="$,.0f", gridcolor="#EEEBE3"),
                        bargap=0.4,
                    )
                    st.plotly_chart(fig_comp, use_container_width=True, config={"displayModeBar": False})
                st.caption("Verde = mejor valor para ese indicador. Naranja = inmueble analizado.")

        # TAB 4: AMORTIZACIÓN
        with res_tabs[4]:
            st.markdown('<div class="section-title">Tabla de Amortización (primeros 10 años)</div>', unsafe_allow_html=True)
            if r['amort_tabla']:
                _amort_th = "".join(
                    f'<th style="background:#1E2D3D;color:#FFFFFF;padding:10px 14px;font-size:10px;'
                    f'letter-spacing:1px;text-transform:uppercase;font-weight:700;border:1px solid #2A3D51;text-align:right;">{h}</th>'
                    for h in ["Año", "Capital Pagado", "Intereses Pagados", "Saldo Restante"]
                )
                _amort_rows = ""
                for i, row in enumerate(r['amort_tabla']):
                    bg = "#FFFFFF" if i % 2 == 0 else "#F9F7F4"
                    _amort_rows += (
                        f'<tr>'
                        f'<td style="background:{bg};color:#1E2D3D;padding:9px 14px;font-size:12px;border:1px solid #E0DAD0;font-weight:700;text-align:center;">{row["año"]}</td>'
                        f'<td style="background:{bg};color:#1A4731;padding:9px 14px;font-size:12px;border:1px solid #E0DAD0;text-align:right;font-weight:600;">${row["capital"]:,.0f}</td>'
                        f'<td style="background:{bg};color:#7A4F1A;padding:9px 14px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">${row["interes"]:,.0f}</td>'
                        f'<td style="background:{bg};color:#1E2D3D;padding:9px 14px;font-size:12px;border:1px solid #E0DAD0;text-align:right;">${row["saldo"]:,.0f}</td>'
                        f'</tr>'
                    )
                st.markdown(
                    f'<div style="overflow-x:auto;margin-bottom:20px;">'
                    f'<table style="width:100%;border-collapse:collapse;">'
                    f'<thead><tr>{_amort_th}</tr></thead>'
                    f'<tbody>{_amort_rows}</tbody>'
                    f'</table></div>',
                    unsafe_allow_html=True
                )

                anos_a = [row['año'] for row in r['amort_tabla']]
                fig_amort = go.Figure()
                fig_amort.add_trace(go.Bar(name="Capital", x=anos_a, y=[row['capital'] for row in r['amort_tabla']], marker_color="#1E2D3D"))
                fig_amort.add_trace(go.Bar(name="Intereses", x=anos_a, y=[row['interes'] for row in r['amort_tabla']], marker_color="#B8904A"))
                fig_amort.update_layout(
                    barmode="stack", height=280, margin=dict(t=20, b=20, l=10, r=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(title=dict(text="Año", font=dict(color="#4A5568", size=11)), tickfont=dict(color="#4A5568")),
                    yaxis=dict(title=dict(text="USD", font=dict(color="#4A5568", size=11)), tickfont=dict(color="#4A5568"), tickformat="$,.0f"),
                    legend=dict(font=dict(color="#4A5568", size=11)),
                    font=dict(family="Inter"),
                )
                st.plotly_chart(fig_amort, use_container_width=True)
            else:
                st.markdown('<div class="alert-legal">Sin crédito — compra al contado.</div>', unsafe_allow_html=True)

        # TAB 5: LEGAL + DESCARGA
        with res_tabs[5]:
            st.markdown('<div class="section-title">Descargar Informe</div>', unsafe_allow_html=True)
            _res_html = generar_informe_residencial_html(
                r, st.session_state.get("residencial_legal"),
                datetime.datetime.now().strftime("%d/%m/%Y"),
                distrito=st.session_state.get("_res_zona_val", r.get("zona", "")),
                m2=st.session_state.get("_res_m2_val", 0),
                antiguedad=st.session_state.get("_res_antiguedad_val", 0),
                fotos=st.session_state.get("res_fotos_bytes", []),
            )
            st.download_button(
                "DESCARGAR INFORME PDF",
                data=_res_html.encode("utf-8"),
                file_name=f"informe_residencial_{datetime.datetime.now().strftime('%Y%m%d')}.html",
                mime="text/html",
                use_container_width=True,
            )
            st.caption("El archivo .html se abre en cualquier navegador y puede imprimirse como PDF.")
            st.markdown("---")
            lg = st.session_state.get("residencial_legal")
            if not lg:
                st.markdown(
                    '<div style="background:#F7F5F1;border:1px solid #D8D4CC;border-radius:8px;'
                    'padding:36px 32px;text-align:center;margin-top:8px;">'
                    '<div style="font-size:9px;color:#9A9080;letter-spacing:3px;text-transform:uppercase;'
                    'font-weight:600;margin-bottom:12px;">Análisis Opcional</div>'
                    '<div style="font-size:16px;font-weight:600;color:#1E2D3D;margin-bottom:8px;">'
                    'Análisis Legal Registral</div>'
                    '<div style="width:36px;height:2px;background:#B8904A;margin:12px auto;"></div>'
                    '<div style="font-size:13px;color:#7A7268;line-height:1.7;max-width:480px;margin:0 auto;">'
                    'Adjunta la <strong>Partida Registral (SUNARP)</strong> y/o el <strong>PU/HR</strong> '
                    'en el panel izquierdo, luego presiona <strong>ANALIZAR DOCUMENTOS</strong> para verificar:'
                    '<br><br>✓ Titularidad y propietarios registrales<br>'
                    '✓ Cargas, hipotecas y medidas cautelares<br>'
                    '✓ Consistencia de áreas y direcciones entre documentos'
                    '</div></div>',
                    unsafe_allow_html=True
                )
            else:
                sem = lg.get("semaforo", "amarillo").lower()
                sem_cfg = {
                    "verde":    ("#1A4731", "#E8F5EE", "SIN ALERTAS CRÍTICAS"),
                    "amarillo": ("#7A4F1A", "#FFF8EE", "OBSERVACIONES MENORES"),
                    "rojo":     ("#7A1A1A", "#FFF0F0", "ALERTAS CRÍTICAS"),
                }.get(sem, ("#1E2D3D", "#F5F2ED", "INDETERMINADO"))
                sc, sbg, setiq = sem_cfg

                st.markdown(f"""
                <div style="background:{sbg};border:1px solid {sc};border-left:4px solid {sc};
                            border-radius:8px;padding:20px 24px;margin-bottom:20px;">
                    <div style="font-size:9px;letter-spacing:3px;color:{sc};text-transform:uppercase;
                                font-weight:700;opacity:0.7;margin-bottom:6px;">Estado Legal del Inmueble</div>
                    <div style="font-size:20px;font-weight:700;color:{sc};margin-bottom:10px;">{setiq}</div>
                    <div style="font-size:13px;color:{sc};opacity:0.85;line-height:1.6;">
                        {lg.get('resumen_legal','—')}</div>
                </div>""", unsafe_allow_html=True)

                alertas = lg.get("alertas", []) or []
                if alertas:
                    st.markdown('<div class="section-title">Alertas</div>', unsafe_allow_html=True)
                    for al in alertas:
                        icon = "🔴" if sem == "rojo" else ("🟡" if sem == "amarillo" else "🟢")
                        st.markdown(f'<div class="alert-gold">{icon} {al}</div>', unsafe_allow_html=True)

                st.markdown('<div class="section-title">Verificación Cruzada</div>', unsafe_allow_html=True)

                def _check(ok):
                    if ok is True:  return "✓", "#1A4731"
                    if ok is False: return "✗", "#7A1A1A"
                    return "—", "#9A9080"

                def _vcard_r(label, row1_lbl, row1_val, row2_lbl, row2_val, note, icon, col):
                    note_html = ('<div style="font-size:11px;color:#7A4F1A;margin-top:8px;font-style:italic;">' + note + '</div>') if note else ''
                    return (
                        '<div style="background:#FFFFFF;border:1px solid #E4E0D8;border-radius:6px;padding:16px 20px;margin-bottom:10px;">'
                        '<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                        '<div style="flex:1;">'
                        '<div style="font-size:9px;color:#9A9080;letter-spacing:2px;text-transform:uppercase;font-weight:600;margin-bottom:8px;">' + label + '</div>'
                        '<div style="font-size:12px;color:#1E2D3D;margin-bottom:4px;"><strong>' + row1_lbl + ':</strong> ' + str(row1_val) + '</div>'
                        '<div style="font-size:12px;color:#1E2D3D;"><strong>' + row2_lbl + ':</strong> ' + str(row2_val) + '</div>'
                        + note_html
                        + '</div>'
                        '<div style="font-size:28px;color:' + col + ';font-weight:700;margin-left:16px;">' + icon + '</div>'
                        '</div></div>'
                    )

                def _fmt_prop_r(p):
                    if not p or not isinstance(p, dict):
                        return str(p) if p else "—"
                    nombre = p.get("nombre") or "—"
                    dni    = p.get("dni")
                    pct    = p.get("porcentaje")
                    cond   = p.get("condicion")
                    tipo   = p.get("tipo_doc", "DNI")
                    parts  = [nombre]
                    if pct:  parts.append(f"({pct})")
                    if cond: parts.append(f"[{cond}]")
                    result = " ".join(parts)
                    if dni:
                        result += f' <span style="background:#E8F5EE;color:#1A4731;font-size:10px;font-weight:700;padding:2px 6px;border-radius:3px;border:1px solid #1A4731;">{tipo}: {dni}</span>'
                    else:
                        result += ' <span style="background:#FFF8EE;color:#7A4F1A;font-size:10px;padding:2px 6px;border-radius:3px;border:1px solid #B8904A;">DNI no encontrado</span>'
                    return result

                prop_p_raw = lg.get("propietarios_partida") or []
                prop_h_raw = lg.get("propietarios_puhr") or []

                if prop_p_raw and isinstance(prop_p_raw[0], dict):
                    prop_p_str = "<br>".join(_fmt_prop_r(p) for p in prop_p_raw)
                else:
                    prop_p_str = ", ".join(str(x) for x in prop_p_raw) if prop_p_raw else "—"

                if prop_h_raw and isinstance(prop_h_raw[0], dict):
                    prop_h_str = "<br>".join(_fmt_prop_r(p) for p in prop_h_raw)
                else:
                    prop_h_str = ", ".join(str(x) for x in prop_h_raw if x) if prop_h_raw else "—"

                icon_p, col_p = _check(lg.get("propietarios_coinciden"))
                note_p = lg.get("diferencias_propietarios", "") or ""
                note_p_html = ('<div style="font-size:11px;color:#7A4F1A;margin-top:8px;font-style:italic;">' + note_p + '</div>') if note_p else ""
                st.markdown(
                    '<div style="background:#FFFFFF;border:1px solid #E4E0D8;border-radius:6px;padding:16px 20px;margin-bottom:10px;">'
                    '<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                    '<div style="flex:1;">'
                    '<div style="font-size:9px;color:#9A9080;letter-spacing:2px;text-transform:uppercase;font-weight:600;margin-bottom:8px;">Titularidad / Propietarios</div>'
                    '<div style="font-size:12px;color:#1E2D3D;margin-bottom:6px;"><strong>Partida:</strong><br>' + prop_p_str + '</div>'
                    '<div style="font-size:12px;color:#1E2D3D;"><strong>PU/HR:</strong><br>' + prop_h_str + '</div>'
                    + note_p_html +
                    '</div>'
                    '<div style="font-size:28px;color:' + col_p + ';font-weight:700;margin-left:16px;">' + icon_p + '</div>'
                    '</div></div>',
                    unsafe_allow_html=True
                )

                dir_p = lg.get("direccion_partida", "—") or "—"
                dir_h = lg.get("direccion_puhr", "—") or "—"
                icon_d, col_d = _check(lg.get("direcciones_coinciden"))
                st.markdown(_vcard_r(
                    "Ubicación / Dirección",
                    "Partida", dir_p, "PU/HR", dir_h,
                    lg.get("diferencias_direccion", ""),
                    icon_d, col_d,
                ), unsafe_allow_html=True)

                area_r = lg.get("area_registral_m2")
                area_h_v = lg.get("area_puhr_m2")
                disc = lg.get("discrepancia_area_m2")
                icon_a, col_a = _check(lg.get("areas_coinciden"))
                disc_note = ("Discrepancia: <strong>" + f"{disc:+.2f} m²</strong>") if disc else ""
                st.markdown(_vcard_r(
                    "Área del Inmueble",
                    "Partida", f"{area_r:,.2f} m²" if area_r else "—",
                    "PU/HR",   f"{area_h_v:,.2f} m²" if area_h_v else "—",
                    disc_note, icon_a, col_a,
                ), unsafe_allow_html=True)

                _autoavaluo_r  = lg.get("valor_autoavaluo")
                _moneda_av_r   = lg.get("moneda_autoavaluo") or "PEN"
                _anio_av_r     = lg.get("anio_autoavaluo")
                _clasif_muni_r = lg.get("clasificacion_municipal")
                _cond_sat_r    = lg.get("condicion_propietario_sat")
                _uso_predio_r  = lg.get("uso_predio")
                if any([_autoavaluo_r, _clasif_muni_r, _cond_sat_r, _uso_predio_r]):
                    st.markdown('<div class="section-title">Datos Municipales — PU/HR</div>', unsafe_allow_html=True)
                    _mu_r_cols = st.columns(2)
                    if _autoavaluo_r:
                        _av_label_r = f"Autoavalúo {_anio_av_r}" if _anio_av_r else "Autoavalúo"
                        _av_val_r   = f"{_moneda_av_r} {_autoavaluo_r:,.0f}" if isinstance(_autoavaluo_r, (int, float)) else f"{_moneda_av_r} {_autoavaluo_r}"
                        _mu_r_cols[0].metric(_av_label_r, _av_val_r)
                    if _clasif_muni_r:
                        _mu_r_cols[1].metric("Clasificación Municipal", _clasif_muni_r)
                    if _cond_sat_r or _uso_predio_r:
                        _mu_r_cols2 = st.columns(2)
                        if _cond_sat_r:   _mu_r_cols2[0].metric("Condición (SAT)", _cond_sat_r)
                        if _uso_predio_r: _mu_r_cols2[1].metric("Uso del Predio", _uso_predio_r)

                hipotecas = lg.get("hipotecas_vigentes", []) or []
                cargas    = lg.get("cargas_vigentes", []) or []
                medidas   = lg.get("medidas_cautelares", []) or []
                if hipotecas or cargas or medidas:
                    st.markdown('<div class="section-title">Cargas, Gravámenes e Hipotecas</div>', unsafe_allow_html=True)
                    for h in hipotecas:
                        st.markdown(
                            f'<div style="background:#FFF0F0;border:1px solid #E8B4B4;border-left:3px solid #C0392B;'
                            f'border-radius:6px;padding:12px 16px;margin-bottom:8px;color:#1E2D3D;font-size:13px;">'
                            f'<strong>Hipoteca</strong> — {h.get("acreedor","—")} · {h.get("monto","—")} '
                            f'<span style="font-size:11px;color:#7A1A1A;">({h.get("estado","—")})</span></div>',
                            unsafe_allow_html=True)
                    for c in cargas:
                        st.markdown(
                            f'<div style="background:#FFF8EE;border:1px solid #DFC07A;border-left:3px solid #B8904A;'
                            f'border-radius:6px;padding:12px 16px;margin-bottom:8px;color:#1E2D3D;font-size:13px;">'
                            f'<strong>{c.get("tipo","Carga")}</strong> — {c.get("descripcion","—")}</div>',
                            unsafe_allow_html=True)
                    for m in medidas:
                        st.markdown(
                            f'<div style="background:#FFF0F0;border:1px solid #E8B4B4;border-left:3px solid #C0392B;'
                            f'border-radius:6px;padding:12px 16px;margin-bottom:8px;color:#1E2D3D;font-size:13px;">'
                            f'<strong>Medida Cautelar</strong> — {m.get("tipo","—")}: {m.get("descripcion","—")}</div>',
                            unsafe_allow_html=True)
                elif sem == "verde":
                    st.markdown('<div class="alert-legal">✓ Sin cargas, hipotecas ni medidas cautelares detectadas.</div>',
                                unsafe_allow_html=True)

        # TAB 6: RESUMEN IA (residencial)
        with res_tabs[6]:
            rsm_r = st.session_state.get("res_resumen")
            if not rsm_r:
                st.markdown(
                    '<div style="background:#F7F5F1;border:1px solid #D8D4CC;border-radius:8px;'
                    'padding:36px 32px;text-align:center;margin-top:8px;">'
                    '<div style="font-size:16px;font-weight:600;color:#1E2D3D;margin-bottom:8px;">Resumen Ejecutivo</div>'
                    '<div style="width:36px;height:2px;background:#B8904A;margin:12px auto;"></div>'
                    '<div style="font-size:13px;color:#7A7268;line-height:1.7;max-width:480px;margin:0 auto 24px;">'
                    'Análisis ejecutivo con recomendación, argumentos clave y riesgos para este inmueble residencial.'
                    '</div></div>', unsafe_allow_html=True)
            if st.button("GENERAR RESUMEN EJECUTIVO", use_container_width=True, type="primary", key="btn_res_rsm"):
                _r_copy = dict(r)
                st.session_state.res_resumen = _run_with_retry(
                    lambda _rc=_r_copy: generar_resumen_ejecutivo_ia("residencial", _rc),
                    "Generando resumen ejecutivo…"
                )
                st.rerun()
            if rsm_r:
                _rec = rsm_r.get("recomendacion", "evaluar_con_condiciones")
                _rec_cfg = {
                    "comprar":                ("#1A4731", "#E8F5EE", "RECOMENDADO — COMPRAR"),
                    "evaluar_con_condiciones":("#7A4F1A", "#FFF8EE", "EVALUAR CON CONDICIONES"),
                    "no_recomendado":         ("#7A1A1A", "#FFF0F0", "NO RECOMENDADO"),
                }.get(_rec, ("#1E2D3D", "#F5F2ED", "—"))
                _rc2, _rbg2, _retiq2 = _rec_cfg

                st.markdown(f"""
                <div style="background:{_rbg2};border:1px solid {_rc2};border-left:5px solid {_rc2};
                            border-radius:8px;padding:22px 28px;margin-bottom:20px;">
                    <div style="font-size:9px;letter-spacing:3px;color:{_rc2};text-transform:uppercase;
                                font-weight:700;opacity:0.7;margin-bottom:6px;">Recomendación</div>
                    <div style="font-size:20px;font-weight:700;color:{_rc2};margin-bottom:8px;">{_retiq2}</div>
                    <div style="font-size:15px;font-weight:600;color:{_rc2};margin-bottom:12px;">{rsm_r.get('titulo','')}</div>
                    <div style="font-size:13px;color:{_rc2};opacity:0.9;line-height:1.7;">{rsm_r.get('resumen','')}</div>
                </div>""", unsafe_allow_html=True)

                _rra1, _rra2 = st.columns(2)
                with _rra1:
                    st.markdown('<div class="section-title">A favor</div>', unsafe_allow_html=True)
                    for a in (rsm_r.get("argumentos_favor") or []):
                        st.markdown(f'<div class="alert-legal" style="margin-bottom:6px;">✓ {a}</div>', unsafe_allow_html=True)
                with _rra2:
                    st.markdown('<div class="section-title">Riesgos</div>', unsafe_allow_html=True)
                    for rk in (rsm_r.get("riesgos") or []):
                        st.markdown(f'<div class="alert-gold" style="margin-bottom:6px;">⚠ {rk}</div>', unsafe_allow_html=True)

                st.markdown(
                    f'<div style="background:#1E2D3D;border-radius:6px;padding:16px 22px;margin-top:16px;">'
                    f'<div style="font-size:9px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;font-weight:600;margin-bottom:6px;">Conclusión</div>'
                    f'<div style="font-size:13px;color:#FFFFFF;line-height:1.7;">{rsm_r.get("conclusion","")}</div>'
                    f'</div>', unsafe_allow_html=True)

                if st.button("REGENERAR", key="btn_res_rsm_regen"):
                    st.session_state.res_resumen = None
                    st.rerun()

        # TAB 7: DOCUMENTOS
        with res_tabs[7]:
            st.markdown('<div class="section-title">Documentos Profesionales</div>', unsafe_allow_html=True)

            _doc_tipo = st.radio("Tipo de documento",
                                  ["Informe de Valoración", "Propuesta de Alquiler", "Propuesta de Compra", "Contraoferta"],
                                  horizontal=True)

            _dc1, _dc2 = st.columns(2)
            _doc_agente = _dc1.text_input("Nombre del agente", placeholder="Tu nombre completo")
            _doc_cliente = _dc2.text_input("Nombre del cliente / propietario", placeholder="A quién va dirigido")
            _doc_obs = st.text_area("Observaciones adicionales", placeholder="Condiciones especiales, notas del cliente, etc.", height=80)

            if st.button("GENERAR DOCUMENTO", use_container_width=True, type="primary"):
                # Generate document HTML
                _fecha_doc = datetime.datetime.now().strftime("%d/%m/%Y")
                _zona_doc = r.get("zona", "Lima")
                _precio_doc = r["precio"]
                _m2_doc = r.get("m2", 0)
                _ppm2_doc = r.get("precio_m2", 0)
                _ref_m2_doc = r.get("precio_m2_mercado", 0)
                _diff_doc = ((_ppm2_doc - _ref_m2_doc) / _ref_m2_doc * 100) if _ref_m2_doc > 0 else 0
                _alq_doc = r.get("alquiler_mes", 0)
                _alq_mkt_doc = r.get("alquiler_mercado_m2", 0) * _m2_doc
                _yield_doc = r.get("yield_bruto", 0)
                _yield_mkt_doc = r.get("yield_mercado_pct", 0)
                _var_doc = r.get("variacion_anual_pct", 0)
                _cuota_doc = r.get("cuota_mensual", 0)
                _pie_doc = r.get("pie", 0)
                _ingreso_min_doc = r.get("ingreso_minimo", 0)

                _NAV = "#1E2D3D"
                _GOLD = "#B8904A"

                _posicion = ("por debajo del mercado — precio competitivo" if _diff_doc < -5
                             else ("en línea con el mercado" if abs(_diff_doc) <= 8
                                   else f"{_diff_doc:.1f}% sobre la mediana de zona"))

                _doc_html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8">
<style>
  body{{font-family:'Segoe UI',Arial,sans-serif;background:#EDEAE4;margin:0;padding:32px;color:{_NAV};}}
  .page{{background:#FFFFFF;max-width:820px;margin:0 auto;padding:48px 52px;border-radius:8px;box-shadow:0 4px 24px rgba(0,0,0,0.08);}}
  .header{{background:linear-gradient(135deg,#1E2D3D,#243850);padding:28px 32px;border-radius:6px;margin-bottom:32px;}}
  .header-title{{font-size:24px;font-weight:800;color:#FFFFFF;letter-spacing:-0.5px;}}
  .header-sub{{font-size:11px;color:{_GOLD};letter-spacing:3px;text-transform:uppercase;font-weight:600;margin-bottom:10px;}}
  .header-meta{{font-size:11px;color:#8AA8C0;margin-top:8px;}}
  .section-title{{font-size:9px;color:#9A9080;letter-spacing:2.5px;text-transform:uppercase;font-weight:700;border-bottom:1px solid #D8D4CC;padding-bottom:6px;margin:28px 0 14px;}}
  .metric-row{{display:flex;gap:20px;flex-wrap:wrap;margin-bottom:20px;}}
  .metric-box{{flex:1;min-width:140px;background:#F9F7F4;border:1px solid #E4E0D8;border-top:3px solid {_GOLD};border-radius:6px;padding:14px 16px;}}
  .metric-label{{font-size:9px;color:#9A9080;letter-spacing:1.5px;text-transform:uppercase;font-weight:600;margin-bottom:4px;}}
  .metric-value{{font-size:20px;font-weight:700;color:{_NAV};letter-spacing:-0.5px;}}
  .alert{{border-left:4px solid {_GOLD};background:#FFFBF3;border-radius:4px;padding:12px 16px;margin:12px 0;font-size:12px;color:#5C3D10;line-height:1.6;}}
  .market-box{{background:#F0F4F8;border:1px solid #C8D4DE;border-radius:6px;padding:16px 20px;margin:12px 0;}}
  table{{width:100%;border-collapse:collapse;margin:12px 0;}}
  th{{background:{_NAV};color:#FFFFFF;padding:9px 14px;font-size:10px;text-transform:uppercase;letter-spacing:1px;text-align:left;}}
  td{{padding:9px 14px;font-size:12px;border-bottom:1px solid #E8E4DC;color:{_NAV};}}
  tr:nth-child(even) td{{background:#F9F7F4;}}
  .footer{{margin-top:40px;padding-top:16px;border-top:1px solid #D8D4CC;font-size:10px;color:#9A9080;text-align:center;line-height:1.6;}}
  .gold{{color:{_GOLD};font-weight:700;}}
  .verde{{color:#1A4731;font-weight:700;}}
  .rojo{{color:#7A1A1A;font-weight:700;}}
  @media print{{body{{background:white;padding:0;}} .page{{box-shadow:none;}}}}
</style>
</head>
<body>
<div class="page">

<div class="header">
  <div class="header-sub">Osterling Advisory · FACTIS</div>
  <div class="header-title">{_doc_tipo}</div>
  <div class="header-meta">
    {'Preparado por: ' + _doc_agente + ' · ' if _doc_agente else ''}Zona: {_zona_doc} · Fecha: {_fecha_doc}
    {' · Para: ' + _doc_cliente if _doc_cliente else ''}
  </div>
</div>

<div class="section-title">I. Resumen del Inmueble</div>
<div class="metric-row">
  <div class="metric-box"><div class="metric-label">Precio</div><div class="metric-value">${_precio_doc:,}</div></div>
  <div class="metric-box"><div class="metric-label">Área</div><div class="metric-value">{_m2_doc} m²</div></div>
  <div class="metric-box"><div class="metric-label">USD / m²</div><div class="metric-value">${_ppm2_doc:,.0f}</div></div>
  <div class="metric-box"><div class="metric-label">Zona</div><div class="metric-value" style="font-size:14px;">{_zona_doc}</div></div>
</div>

<div class="section-title">II. Posición de Mercado</div>
<div class="market-box">
  <table>
    <tr><th>Indicador</th><th>Este Inmueble</th><th>Mercado Zona (Urbania nov-25)</th><th>Diferencial</th></tr>
    <tr>
      <td>Precio / m²</td>
      <td><strong>${_ppm2_doc:,.0f}/m²</strong></td>
      <td>${_ref_m2_doc:,}/m²</td>
      <td class="{'verde' if _diff_doc <= 0 else 'rojo'}">{_diff_doc:+.1f}%</td>
    </tr>
    {"" if not _alq_doc else f'<tr><td>Alquiler mensual</td><td><strong>${_alq_doc:,}/mes</strong></td><td>${_alq_mkt_doc:,.0f}/mes</td><td class="' + ("verde" if _alq_doc >= _alq_mkt_doc else "rojo") + f'">{((_alq_doc-_alq_mkt_doc)/_alq_mkt_doc*100) if _alq_mkt_doc > 0 else 0:+.1f}% vs. mercado</td></tr>'}
    {"" if not _yield_doc else f'<tr><td>Yield bruto anual</td><td><strong>{_yield_doc:.1f}%</strong></td><td>{_yield_mkt_doc:.1f}%</td><td class="' + ("verde" if _yield_doc >= _yield_mkt_doc else "rojo") + f'">{(_yield_doc-_yield_mkt_doc):+.1f}pp</td></tr>'}
    <tr>
      <td>Tendencia anual zona</td>
      <td colspan="2">{_var_doc:+.1f}% en 12 meses (Urbania Lima Index)</td>
      <td class="{'verde' if _var_doc >= 0 else 'rojo'}">{'↑ En alza' if _var_doc >= 2 else ('→ Estable' if abs(_var_doc) < 2 else '↓ En baja')}</td>
    </tr>
  </table>
</div>

<div class="alert">
  <strong>Posición de precio:</strong> El inmueble se encuentra <strong>{_posicion}</strong>.
  {"La variación anual de la zona (" + str(_var_doc) + "%) indica " + ("potencial de plusvalía." if _var_doc > 2 else ("mercado estable." if abs(_var_doc) <= 2 else "presión a la baja — oportunidad de negociación."))}
</div>

{'<div class="section-title">III. Análisis Financiero del Comprador</div><div class="metric-row"><div class="metric-box"><div class="metric-label">Pago inicial (' + str(int(r["pct_pie"])) + '%)</div><div class="metric-value">$' + f"{_pie_doc:,.0f}" + '</div></div><div class="metric-box"><div class="metric-label">Cuota mensual</div><div class="metric-value">$' + f"{_cuota_doc:,.0f}" + '</div></div><div class="metric-box"><div class="metric-label">Ingreso mínimo</div><div class="metric-value">$' + f"{_ingreso_min_doc:,.0f}" + '/mes</div></div></div>' if _cuota_doc > 0 else ""}

{'<div class="section-title">IV. Rentabilidad de la Inversión</div><div class="metric-row"><div class="metric-box"><div class="metric-label">Yield Bruto</div><div class="metric-value">' + f"{_yield_doc:.1f}%" + '</div></div><div class="metric-box"><div class="metric-label">Yield Neto</div><div class="metric-value">' + f"{r.get('yield_neto',0):.1f}%" + '</div></div><div class="metric-box"><div class="metric-label">Payback</div><div class="metric-value">' + (f"{r.get('payback_anos',0):.1f} años" if r.get('payback_anos') else "N/A") + '</div></div><div class="metric-box"><div class="metric-label">Yield mercado zona</div><div class="metric-value">' + f"{_yield_mkt_doc:.1f}%" + '</div></div></div>' if _yield_doc > 0 else ""}

<div class="section-title">V. Proyección de Valor (tasa zona: {r.get("tasa_apreciacion_pct", 4.0):.1f}%/año)</div>
<div class="metric-row">
  <div class="metric-box"><div class="metric-label">Valor a 5 años</div><div class="metric-value">${r['valor_5']:,.0f}</div></div>
  <div class="metric-box"><div class="metric-label">Ganancia capital 5a</div><div class="metric-value">+${r['ganancia_capital_5']:,.0f}</div></div>
  <div class="metric-box"><div class="metric-label">Valor a 10 años</div><div class="metric-value">${r['valor_10']:,.0f}</div></div>
</div>

{('<div class="section-title">VI. Observaciones</div><div class="alert">' + _doc_obs + '</div>') if _doc_obs else ""}

<div class="footer">
  Documento generado por FACTIS · Osterling Advisory<br>
  Los valores de mercado corresponden al Índice Urbania Lima — Noviembre 2025 · Tipo de cambio SUNAT: 3.42 S./USD<br>
  Este documento tiene carácter referencial y no reemplaza la asesoría profesional especializada.<br>
  {_fecha_doc}
</div>

</div>
</body>
</html>"""

                st.session_state["_res_doc_html"] = _doc_html
                st.success("Documento generado.")

            if st.session_state.get("_res_doc_html"):
                _doc_filename = f"{_doc_tipo.replace(' ','_')}_{datetime.datetime.now().strftime('%Y%m%d')}.html"
                st.download_button(
                    f"DESCARGAR {_doc_tipo.upper()}",
                    data=st.session_state["_res_doc_html"].encode("utf-8"),
                    file_name=_doc_filename,
                    mime="text/html",
                    use_container_width=True,
                )
                st.caption("Abre en tu navegador y usa Cmd+P para imprimir a PDF o compartir.")

                # Preview
                st.markdown("---")
                st.markdown('<div class="section-title">Vista Previa</div>', unsafe_allow_html=True)
                st.components.v1.html(st.session_state["_res_doc_html"], height=700, scrolling=True)

    else:
        st.markdown(
            '<div style="border-radius:8px;min-height:420px;'
            'background:linear-gradient(160deg,#1A2737 0%,#1E2D3D 60%,#1A2737 100%);'
            'display:flex;align-items:center;justify-content:center;'
            'box-shadow:0 8px 32px rgba(30,45,61,0.18);padding:64px 48px;">'
            '<div style="max-width:600px;width:100%;text-align:center;">'
            '<div style="font-size:9px;color:#B8904A;letter-spacing:4px;text-transform:uppercase;font-weight:600;margin-bottom:16px;">Osterling Advisory</div>'
            '<div style="font-size:28px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;margin-bottom:8px;">Análisis Residencial</div>'
            '<div style="width:48px;height:2px;background:#B8904A;margin:16px auto;"></div>'
            '<div style="font-size:13px;color:#B0C0D0;line-height:1.7;margin-bottom:32px;">'
            'Evalúa la compra de un inmueble residencial ya sea para uso propio o como inversión. '
            'Obtén la cuota mensual exacta, el ingreso mínimo recomendado para calificar al crédito, '
            'rentabilidad por alquiler, payback y proyección de apreciación de capital.'
            '</div>'
            '<div style="display:flex;gap:24px;justify-content:center;flex-wrap:wrap;">'
            '<div style="background:rgba(184,144,74,0.1);border:1px solid rgba(184,144,74,0.3);'
            'border-radius:6px;padding:14px 20px;min-width:120px;">'
            '<div style="font-size:18px;font-weight:700;color:#B8904A;">Cuota</div>'
            '<div style="font-size:10px;color:#8AA8C0;letter-spacing:1.5px;text-transform:uppercase;margin-top:4px;">Hipotecaria Exacta</div>'
            '</div>'
            '<div style="background:rgba(184,144,74,0.1);border:1px solid rgba(184,144,74,0.3);'
            'border-radius:6px;padding:14px 20px;min-width:120px;">'
            '<div style="font-size:18px;font-weight:700;color:#B8904A;">Yield</div>'
            '<div style="font-size:10px;color:#8AA8C0;letter-spacing:1.5px;text-transform:uppercase;margin-top:4px;">Bruto y Neto</div>'
            '</div>'
            '<div style="background:rgba(184,144,74,0.1);border:1px solid rgba(184,144,74,0.3);'
            'border-radius:6px;padding:14px 20px;min-width:120px;">'
            '<div style="font-size:18px;font-weight:700;color:#B8904A;">+4%</div>'
            '<div style="font-size:10px;color:#8AA8C0;letter-spacing:1.5px;text-transform:uppercase;margin-top:4px;">Apreciación Lima</div>'
            '</div>'
            '</div>'
            '</div></div>',
            unsafe_allow_html=True
        )

# ═══════════════════════════════════════════════════════
# MÓDULO 4: CALCULADORA INVERSA DE TERRENO
# ═══════════════════════════════════════════════════════
elif tipo_op == "Calculadora Inversa":
    st.markdown(
        '<div style="font-size:9px;color:#B8904A;letter-spacing:4px;text-transform:uppercase;'
        'font-weight:600;margin-bottom:4px;">Osterling Advisory</div>'
        '<div style="font-size:26px;font-weight:700;color:#FFFFFF;letter-spacing:-0.5px;">'
        '🎯 Calculadora Inversa de Terreno</div>'
        '<div style="font-size:13px;color:#B0C0D0;margin-top:6px;margin-bottom:24px;">'
        'Ingresa el margen objetivo y los datos del proyecto — la app calcula el precio máximo '
        'que puedes pagar por el terreno para alcanzar ese margen.</div>',
        unsafe_allow_html=True)

    _ci_col1, _ci_col2 = st.columns([1, 1], gap="large")

    with _ci_col1:
        st.markdown("#### Datos del proyecto")
        _ci_zona = st.selectbox("Distrito", sorted(MERCADO.keys()), key="ci_zona")
        _m_ci = MERCADO.get(_ci_zona, {})
        _ci_area_t = st.number_input("Área del terreno (m²)", 100, 5000, 400, 10, key="ci_area_t")
        _ci_pisos  = st.number_input("Número de pisos", 1, 30, 8, 1, key="ci_pisos")

        _ci_cus_default = min(_ci_pisos * 0.85, 9.0)
        _ci_area_techada = st.number_input(
            "Área techada total (m²)",
            100, 20000,
            int(_ci_area_t * _ci_cus_default),
            50, key="ci_area_techada",
            help="Área techada total construida. Referencia: área terreno × CUS")
        _ci_area_v = st.number_input(
            "Área vendible (m²)",
            50, 15000,
            int(_ci_area_techada * 0.73),
            50, key="ci_area_v",
            help="Aprox. 70-75% del área techada")

        _ci_estac = st.number_input("Estacionamientos", 0, 200, max(int(_ci_area_v / 75), 0), 1, key="ci_estac")
        _ci_dep   = st.number_input("Depósitos", 0, 200, max(int(_ci_area_v / 150), 0), 1, key="ci_dep")

        st.markdown("#### Costos y precios")
        _ci_precio_m2 = st.number_input(
            "Precio de venta ($/m² vendible)",
            500, 5000,
            int(_m_ci.get("precio_2br", 1800)),
            50, key="ci_precio_m2")
        _ci_costo_c = st.number_input("Costo construcción ($/m² techado)", 500, 2000, 920, 10, key="ci_costo_c")
        _ci_tasa_f  = st.number_input("Tasa financiamiento (%)", 0.0, 15.0, 7.0, 0.5, key="ci_tasa_f")

        st.markdown("#### Margen objetivo")
        _ci_margen = st.slider(
            "Margen neto objetivo (%)", 5, 30, 15, 1, key="ci_margen",
            help="Margen neto = utilidad neta / ingresos brutos")

    _ci_inp = {
        "zona": _ci_zona,
        "area_terreno": _ci_area_t,
        "area_vendible": _ci_area_v,
        "area_techada": _ci_area_techada,
        "num_pisos": _ci_pisos,
        "n_estac": _ci_estac,
        "n_depositos": _ci_dep,
        "precio_m2": _ci_precio_m2,
        "costo_construccion": _ci_costo_c,
        "tasa_financ": _ci_tasa_f,
        "tasa_ir": 29.5,
        "margen_objetivo": _ci_margen,
    }
    _ci_r = calcular_terreno_maximo(_ci_inp)

    with _ci_col2:
        st.markdown("#### Resultado")
        _ci_T    = _ci_r["resultados"].get(_ci_margen / 100, 0)
        _ci_tc   = _ci_r["tipo_cambio"]
        _ci_T_s  = round(_ci_T * _ci_tc)
        _ci_T_m2 = round(_ci_T / _ci_area_t) if _ci_area_t > 0 else 0
        _ci_T_m2_s = round(_ci_T_m2 * _ci_tc)
        _ci_ing  = _ci_r["ing_brutos"]

        # Semáforo según precio/m² de terreno vs. benchmarks de Lima
        if _ci_T_m2 <= 0:
            _ci_sem = "🔴"
            _ci_sem_txt = "Inviable con estos parámetros"
            _ci_sem_col = "#FF4444"
        elif _ci_T_m2 >= 800:
            _ci_sem = "🟢"
            _ci_sem_txt = "Holgura amplia — zona premium viable"
            _ci_sem_col = "#4CAF50"
        elif _ci_T_m2 >= 400:
            _ci_sem = "🟡"
            _ci_sem_txt = "Viable — negocia dentro de este rango"
            _ci_sem_col = "#FFC107"
        elif _ci_T_m2 >= 150:
            _ci_sem = "🟡"
            _ci_sem_txt = "Viable — zona media/periferia"
            _ci_sem_col = "#FFC107"
        else:
            _ci_sem = "🔴"
            _ci_sem_txt = "Precio máximo muy bajo — revisar supuestos"
            _ci_sem_col = "#FF4444"

        st.markdown(
            f'<div style="background:linear-gradient(135deg,#1A2737,#1E2D3D);border-radius:12px;'
            f'padding:24px;border:1px solid rgba(184,144,74,0.3);margin-bottom:16px;">'
            f'<div style="font-size:11px;color:#B8904A;letter-spacing:2px;text-transform:uppercase;'
            f'font-weight:600;margin-bottom:8px;">Precio máximo de terreno — margen {_ci_margen}%</div>'
            f'<div style="font-size:38px;font-weight:800;color:#FFFFFF;letter-spacing:-1px;">'
            f'${_ci_T:,.0f}</div>'
            f'<div style="font-size:15px;color:#B0C0D0;margin-top:4px;">S/ {_ci_T_s:,.0f}</div>'
            f'<div style="width:40px;height:2px;background:#B8904A;margin:14px 0;"></div>'
            f'<div style="display:flex;gap:32px;">'
            f'<div><div style="font-size:22px;font-weight:700;color:#D4A853;">${_ci_T_m2:,}/m²</div>'
            f'<div style="font-size:10px;color:#8AA8C0;letter-spacing:1px;text-transform:uppercase;">por m² de terreno</div></div>'
            f'<div><div style="font-size:22px;font-weight:700;color:#D4A853;">S/ {_ci_T_m2_s:,}/m²</div>'
            f'<div style="font-size:10px;color:#8AA8C0;letter-spacing:1px;text-transform:uppercase;">en soles</div></div>'
            f'</div>'
            f'<div style="margin-top:16px;padding:10px 14px;background:rgba(255,255,255,0.04);'
            f'border-radius:8px;border-left:3px solid {_ci_sem_col};">'
            f'<div style="font-size:13px;color:{_ci_sem_col};font-weight:600;">{_ci_sem} {_ci_sem_txt}</div>'
            f'</div></div>',
            unsafe_allow_html=True)

        _ci_mc1, _ci_mc2 = st.columns(2)
        _ci_mc1.metric("Ingresos brutos", f"${_ci_ing:,.0f}")
        _ci_mc2.metric("Costo construcción", f"${_ci_r['c_construccion']:,.0f}")

        st.markdown("#### Tabla de sensibilidad")
        st.caption("Precio máximo de terreno según margen objetivo")
        _ci_rows = []
        for mg_k, mg_label in [(0.10,"10%"),(0.12,"12%"),(0.15,"15%"),(0.18,"18%"),(0.20,"20%")]:
            T_v = _ci_r["resultados"].get(mg_k, 0)
            T_m2_v = round(T_v / _ci_area_t) if _ci_area_t > 0 else 0
            marker = " ◀" if abs(mg_k - _ci_margen/100) < 0.001 else ""
            _ci_rows.append({
                "Margen": mg_label + marker,
                "Terreno máx. ($)": f"${T_v:,.0f}",
                "$/m² terreno": f"${T_m2_v:,}",
                f"S/ m² (TC {_ci_tc})": f"S/ {round(T_m2_v * _ci_tc):,}",
            })
        st.dataframe(
            pd.DataFrame(_ci_rows),
            hide_index=True,
            use_container_width=True)

        st.markdown("#### Desglose de costos fijos")
        st.caption("Costos independientes del terreno (base de cálculo)")
        _ci_desglose = {
            "Construcción (inc. fee constructora)": _ci_r["c_construccion"],
            "Gerenciamiento (6% ing.)": round(_ci_ing * 0.06),
            "Comercialización (6% ing.)": round(_ci_ing * 0.065),
            "Diseño (arq. + esp.)": round(_ci_area_techada * (10.5 + 4.4)),
            "Costo financiero (est.)": _ci_r["c_financiero"],
            "Due diligence + otros fijos": 11500,
        }
        for _lbl, _val in _ci_desglose.items():
            pct = _val / _ci_ing * 100 if _ci_ing > 0 else 0
            st.markdown(
                f'<div style="display:flex;justify-content:space-between;padding:4px 0;'
                f'border-bottom:1px solid rgba(255,255,255,0.05);font-size:12px;">'
                f'<span style="color:#B0C0D0;">{_lbl}</span>'
                f'<span style="color:#FFFFFF;font-weight:600;">${_val:,.0f} '
                f'<span style="color:#8AA8C0;font-weight:400;">({pct:.1f}%)</span></span></div>',
                unsafe_allow_html=True)
