"""
SOLUM — Teaser Institucional PDF
Diseño basado en: Reporte Financiero Fresnos (jun 2026)
Paleta: blanco puro + carbón #1E2D3D + grises — SIN gold, SIN navy brillante
"""
import asyncio, pathlib
from playwright.async_api import async_playwright

DIR  = pathlib.Path(__file__).parent
OUT  = DIR / "SOLUM_TEASER_2026.pdf"

# ── Logo SVG — barras en carbón sobre fondo transparente ────────────
SVG_RAW = (DIR / "solum_logo_transparent.svg").read_text(encoding="utf-8")
SVG_RAW = (SVG_RAW
    .replace('<?xml version="1.0" encoding="UTF-8"?>', "")
    .replace('<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">', "")
    .strip())
# Versión carbón (páginas claras)
SVG_DARK  = SVG_RAW.replace('.fil1 {fill:#FEFEFE}', '.fil1 {fill:#1E2D3D}')
# Versión blanca (franja inferior oscura)
SVG_WHITE = SVG_RAW  # ya tiene #FEFEFE

def sized(svg, w, h):
    return (svg
        .replace('width="61.726mm"',  f'width="{w}"')
        .replace('height="61.726mm"', f'height="{h}"'))

def page_header(section_label: str) -> str:
    return f"""
    <div class="ph">
      <div class="ph-left">
        {sized(SVG_DARK, "28px", "28px")}
        <span class="ph-name">SOLUM</span>
      </div>
      <div class="ph-right">
        <span>Investment &amp; Client Teaser</span>
        <span>{section_label}</span>
      </div>
    </div>
    <div class="ph-rule"></div>"""

def page_footer(n: int) -> str:
    return f"""
    <div class="pf-rule"></div>
    <div class="pf">
      <span>INFORMACIÓN CONFIDENCIAL · SOLUM Herramienta Analítica Inmobiliaria</span>
      <span>Pág. {n}</span>
    </div>"""

def build_html() -> str:
    toc_items = [
        ("I","El Problema"), ("II","La Solución — Qué es SOLUM"),
        ("III","Cómo Funciona"), ("IV","Capacidades"),
        ("V","La Fortaleza — Ventaja Competitiva"), ("VI","La Oportunidad de Mercado"),
        ("VII","Modelo de Negocio"), ("VIII","Comparativa con Herramientas Similares"),
        ("IX","Estrategias de los Líderes"), ("X","Valoración y Potencial"),
        ("XI","El Pitch — 60 Segundos"), ("XII","Próximos Pasos"),
    ]
    toc_rows = "".join(
        f'<div class="toc-row"><span class="toc-n">{n}</span>'
        f'<span class="toc-t">{t}</span></div>'
        for n, t in toc_items)

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>SOLUM — Investment & Client Teaser 2026</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box;}}
:root{{
  --ch:  #1E2D3D;
  --bd:  #4A5568;
  --mt:  #718096;
  --ln:  #E2E8F0;
  --bg:  #F7F9FC;
  --wh:  #FFFFFF;
}}
body{{
  font-family:'Inter',sans-serif;background:#E8ECF2;color:var(--bd);
  font-size:13px;-webkit-print-color-adjust:exact;print-color-adjust:exact;
}}
.page{{
  width:794px;min-height:1123px;background:var(--wh);
  margin:0 auto 28px;display:flex;flex-direction:column;
}}

/* header / footer */
.ph{{display:flex;align-items:center;justify-content:space-between;padding:20px 40px 10px;}}
.ph-left{{display:flex;align-items:center;gap:10px;}}
.ph-name{{font-size:13px;font-weight:800;color:var(--ch);letter-spacing:2px;}}
.ph-right{{display:flex;flex-direction:column;align-items:flex-end;gap:2px;font-size:10px;color:var(--mt);}}
.ph-rule{{height:1px;background:var(--ln);margin:0 40px;}}
.pb{{flex:1;padding:26px 40px 18px;display:flex;flex-direction:column;}}
.pf-rule{{height:1px;background:var(--ln);margin:0 40px;}}
.pf{{display:flex;justify-content:space-between;align-items:center;padding:7px 40px;
  font-size:9px;color:var(--mt);letter-spacing:.5px;text-transform:uppercase;}}

/* tipografía */
.sec-lbl{{font-size:9px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:var(--mt);margin-bottom:6px;}}
.sec-title{{font-size:20px;font-weight:800;color:var(--ch);line-height:1.15;margin-bottom:10px;}}
.sec-rule{{height:1px;background:var(--ln);margin-bottom:20px;}}
.sub{{font-size:10px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--ch);
  border-bottom:1px solid var(--ln);padding-bottom:4px;margin:16px 0 8px;}}
.bt{{font-size:12px;line-height:1.75;color:var(--bd);margin-bottom:10px;}}
.bt b{{color:var(--ch);}}

/* bullets */
ul.bl{{list-style:none;margin:0 0 12px;}}
ul.bl li{{font-size:12px;line-height:1.65;color:var(--bd);
  padding:4px 0 4px 16px;position:relative;border-bottom:1px solid var(--ln);}}
ul.bl li::before{{content:"—";position:absolute;left:0;color:var(--ch);font-weight:600;}}
ul.bl li b{{color:var(--ch);}}

/* tablas */
table{{width:100%;border-collapse:collapse;font-size:11.5px;margin-bottom:16px;}}
thead th{{background:var(--ch);color:var(--wh);font-weight:600;padding:8px 12px;
  text-align:left;font-size:10px;letter-spacing:.5px;text-transform:uppercase;}}
thead th.c{{text-align:center;}}
tbody tr:nth-child(even){{background:var(--bg);}}
tbody tr:nth-child(odd){{background:var(--wh);}}
tbody td{{padding:7px 12px;color:var(--bd);border-bottom:1px solid var(--ln);vertical-align:middle;}}
tbody td b{{color:var(--ch);}}
tbody td.c{{text-align:center;}}
tbody td.ok{{color:#276749;font-weight:600;}}
tbody td.no{{color:#C53030;font-weight:600;}}
tr.total td{{background:var(--ch)!important;color:var(--wh)!important;font-weight:700;}}

/* KPIs */
.kpi-grid{{display:grid;gap:1px;background:var(--ln);border:1px solid var(--ln);border-radius:4px;overflow:hidden;margin-bottom:18px;}}
.kpi4{{grid-template-columns:repeat(4,1fr);}}
.kpi3{{grid-template-columns:repeat(3,1fr);}}
.kpi-cell{{background:var(--wh);padding:16px 12px;text-align:center;}}
.kpi-num{{font-size:24px;font-weight:800;color:var(--ch);line-height:1;margin-bottom:4px;}}
.kpi-lbl{{font-size:9px;font-weight:600;color:var(--mt);letter-spacing:1px;text-transform:uppercase;line-height:1.4;}}

/* highlight / pitch */
.hbox{{background:var(--bg);border-left:3px solid var(--ch);padding:14px 18px;margin:12px 0;border-radius:0 4px 4px 0;}}
.hbox p{{font-size:12px;color:var(--ch);line-height:1.7;font-style:italic;}}
.pitch-box{{border:1px solid var(--ln);border-top:3px solid var(--ch);padding:22px 28px;margin:8px 0;background:var(--wh);border-radius:0 0 4px 4px;}}
.pitch-box p{{font-size:13px;color:var(--bd);line-height:1.85;font-style:italic;}}

/* step cards */
.step-card{{display:flex;align-items:stretch;border:1px solid var(--ln);border-radius:4px;overflow:hidden;margin-bottom:4px;}}
.step-n{{background:var(--ch);color:var(--wh);font-size:18px;font-weight:900;min-width:48px;display:flex;align-items:center;justify-content:center;flex-shrink:0;}}
.step-body{{padding:12px 16px;background:var(--bg);flex:1;}}
.step-title{{font-size:11px;font-weight:700;color:var(--ch);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px;}}
.step-desc{{font-size:11px;color:var(--bd);line-height:1.6;}}

/* strength cards */
.str-card{{display:flex;align-items:stretch;border:1px solid var(--ln);border-radius:4px;overflow:hidden;margin-bottom:6px;}}
.str-n{{background:var(--ch);color:var(--wh);font-size:20px;font-weight:900;min-width:44px;display:flex;align-items:center;justify-content:center;flex-shrink:0;}}
.str-body{{padding:12px 16px;flex:1;border-left:2px solid var(--ch);}}
.str-title{{font-size:11.5px;font-weight:700;color:var(--ch);margin-bottom:3px;}}
.str-text{{font-size:11px;color:var(--bd);line-height:1.65;}}

/* val box */
.val-box{{background:var(--ch);padding:20px 28px;text-align:center;margin:14px 0;border-radius:4px;}}
.val-lbl{{font-size:9px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:#A0AEC0;margin-bottom:8px;}}
.val-num{{font-size:26px;font-weight:900;color:var(--wh);}}

/* toc */
.toc-row{{display:flex;align-items:baseline;gap:12px;padding:8px 0;border-bottom:1px solid var(--ln);}}
.toc-n{{font-size:9px;font-weight:700;color:var(--mt);min-width:30px;letter-spacing:1px;}}
.toc-t{{font-size:12px;color:var(--ch);font-weight:500;}}

/* two col */
.two-col{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:12px;}}
.col-hdr{{font-size:10px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--ch);border-bottom:1px solid var(--ch);padding-bottom:4px;margin-bottom:8px;}}

/* cierre */
.cierre{{background:var(--ch);padding:22px 32px;border-radius:4px;display:flex;align-items:center;justify-content:space-between;margin-top:22px;}}
.cierre-brand{{font-size:15px;font-weight:800;letter-spacing:2px;color:var(--wh);}}
.cierre-sub{{font-size:10px;color:rgba(255,255,255,.55);margin-top:2px;}}
.cierre-email{{font-size:11px;color:rgba(255,255,255,.8);margin-top:4px;}}
.disc{{font-size:9px;color:var(--mt);line-height:1.6;text-align:center;margin-top:12px;padding:0 16px;}}

/* ── PORTADA ────────────────────────────────────────────── */
.cover{{width:794px;min-height:1123px;background:var(--wh);margin:0 auto 28px;display:flex;flex-direction:column;}}
.cover-strip{{background:var(--ch);height:6px;flex-shrink:0;}}
.cover-head{{padding:38px 52px 0;display:flex;align-items:flex-start;justify-content:space-between;}}
.cover-logo-row{{display:flex;align-items:flex-start;gap:14px;}}
.cv-brand{{display:flex;flex-direction:column;}}
.cv-name{{font-size:22px;font-weight:900;color:var(--ch);letter-spacing:3px;}}
.cv-sub{{font-size:9px;font-weight:500;color:var(--mt);letter-spacing:2.5px;text-transform:uppercase;margin-top:3px;}}
.cv-tag{{font-size:9px;font-weight:600;color:var(--mt);letter-spacing:2px;text-transform:uppercase;border:1px solid var(--ln);padding:4px 12px;border-radius:2px;margin-top:6px;}}
.cv-rule{{height:1px;background:var(--ln);margin:30px 52px 0;}}
.cv-main{{flex:1;padding:44px 52px 0;}}
.cv-eye{{font-size:9px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:var(--mt);margin-bottom:14px;}}
.cv-bold{{font-size:48px;font-weight:900;color:var(--ch);line-height:1;letter-spacing:-1px;}}
.cv-light{{font-size:48px;font-weight:300;color:var(--mt);line-height:1;letter-spacing:-1px;margin-bottom:36px;}}
.cv-lead{{max-width:460px;font-size:13px;color:var(--bd);line-height:1.75;margin-bottom:48px;}}
.cv-kpi{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--ln);border:1px solid var(--ln);border-radius:4px;overflow:hidden;margin-bottom:48px;}}
.ck{{background:var(--bg);padding:16px 12px;text-align:center;}}
.ck-num{{font-size:24px;font-weight:800;color:var(--ch);line-height:1;margin-bottom:4px;}}
.ck-lbl{{font-size:9px;font-weight:600;color:var(--mt);letter-spacing:1px;text-transform:uppercase;line-height:1.4;}}
.cv-quote{{font-size:13px;font-style:italic;font-weight:300;color:var(--mt);}}
.cv-bottom{{background:var(--ch);padding:22px 52px;margin-top:auto;display:flex;align-items:center;justify-content:space-between;}}
.cb-left{{color:rgba(255,255,255,.9);line-height:1.9;}}
.cb-brand{{font-size:14px;font-weight:800;letter-spacing:2px;}}
.cb-sub{{font-size:10px;color:rgba(255,255,255,.55);}}
.cb-contact{{font-size:10px;color:rgba(255,255,255,.75);}}
.cb-right{{font-size:10px;color:rgba(255,255,255,.45);text-align:right;line-height:1.9;}}

@media print{{body{{background:white;}}.page,.cover{{margin:0;}}}}
</style>
</head>
<body>

<!-- PORTADA -->
<div class="cover">
  <div class="cover-strip"></div>
  <div class="cover-head">
    <div class="cover-logo-row">
      {sized(SVG_DARK, "72px", "72px")}
      <div class="cv-brand">
        <div class="cv-name">SOLUM</div>
        <div class="cv-sub">Osterling Advisory</div>
      </div>
    </div>
    <div class="cv-tag">Confidencial · Junio 2026</div>
  </div>
  <div class="cv-rule"></div>
  <div class="cv-main">
    <div class="cv-eye">Investment &amp; Client Teaser</div>
    <div class="cv-bold">La decisión correcta.</div>
    <div class="cv-light">En 90 segundos.</div>
    <div class="cv-lead">SOLUM es la primera plataforma de análisis inmobiliario de alta precisión construida para el mercado de Lima. Normativa urbanística real, modelos financieros calibrados y análisis legal automatizado — en una sola sesión, con reportes listos para el cliente.</div>
    <div class="cv-kpi">
      <div class="ck"><div class="ck-num">90 seg</div><div class="ck-lbl">Análisis completo</div></div>
      <div class="ck"><div class="ck-num">27</div><div class="ck-lbl">Distritos Lima</div></div>
      <div class="ck"><div class="ck-num">80+</div><div class="ck-lbl">Reglas de negocio</div></div>
      <div class="ck"><div class="ck-num">3</div><div class="ck-lbl">Verticales de mercado</div></div>
    </div>
    <div class="cv-quote">"Hace en 90 segundos lo que un equipo de análisis tarda 3 semanas."</div>
  </div>
  <div class="cv-bottom">
    <div class="cb-left">
      <div class="cb-brand">SOLUM</div>
      <div class="cb-sub">Grupo Osterling Advisory · Lima, Perú</div>
      <div class="cb-contact">eosterling@grupoosterling.com</div>
    </div>
    <div class="cb-right"><div>Junio 2026</div><div>Documento confidencial</div></div>
  </div>
</div>

<!-- ÍNDICE -->
<div class="page">
  {page_header("Índice")}
  <div class="pb">
    <div class="sec-lbl">Contenido</div>
    <div class="sec-title">Índice</div>
    <div class="sec-rule"></div>
    {toc_rows}
  </div>
  {page_footer(1)}
</div>

<!-- I — PROBLEMA -->
<div class="page">
  {page_header("I · El Problema")}
  <div class="pb">
    <div class="sec-lbl">Sección I</div><div class="sec-title">El Problema</div><div class="sec-rule"></div>
    <p class="bt">El mercado inmobiliario de Lima opera con <b>información de segunda categoría</b>. Un promotor, asesor o family office que identifica un terreno enfrenta un proceso manual, lento y costoso antes de poder tomar cualquier decisión de inversión.</p>
    <table>
      <thead><tr><th>Etapa</th><th>Proceso</th><th class="c">Tiempo</th><th class="c">Costo</th></tr></thead>
      <tbody>
        <tr><td><b>1 · Normativa</b></td><td>Solicitar CPUE e interpretar la Ordenanza aplicable</td><td class="c">15–30 días</td><td class="c">—</td></tr>
        <tr><td><b>2 · Cabida</b></td><td>Arquitecto estima el potencial edificable del predio</td><td class="c">3–5 días</td><td class="c">S/.800–3,000</td></tr>
        <tr><td><b>3 · Finanzas</b></td><td>Modelo financiero en Excel: DCF, TIR, VAN, flujo mensual</td><td class="c">1–2 días</td><td class="c">En el fee</td></tr>
        <tr><td><b>4 · Legal</b></td><td>Revisión Partida SUNARP: titulares, hipotecas, cargas</td><td class="c">3–5 días</td><td class="c">$200–500</td></tr>
        <tr class="total"><td colspan="2"><b>TOTAL</b></td><td class="c"><b>3–6 semanas</b></td><td class="c"><b>$500–4,000</b></td></tr>
      </tbody>
    </table>
    <div class="hbox"><p>"Y el terreno ya lo compró otro."</p></div>
    <div class="sub">El dolor tiene nombre y apellido</div>
    <ul class="bl">
      <li><b>El promotor mediano</b> pierde oportunidades por lentitud analítica. En Lima un terreno prime se mueve en días, no semanas.</li>
      <li><b>El asesor independiente</b> no puede escalar porque cada análisis consume 2–3 días de trabajo manual.</li>
      <li><b>El family office o fondo</b> toma decisiones de capital con información incompleta o con semanas de retraso.</li>
      <li><b>El banco o structurer</b> no tiene visibilidad rápida sobre la viabilidad real del proyecto que va a financiar.</li>
    </ul>
  </div>
  {page_footer(2)}
</div>

<!-- II — SOLUCIÓN -->
<div class="page">
  {page_header("II · La Solución")}
  <div class="pb">
    <div class="sec-lbl">Sección II</div><div class="sec-title">La Solución — Qué es SOLUM</div><div class="sec-rule"></div>
    <div class="kpi-grid kpi4">
      <div class="kpi-cell"><div class="kpi-num">90 seg</div><div class="kpi-lbl">Análisis completo</div></div>
      <div class="kpi-cell"><div class="kpi-num">27</div><div class="kpi-lbl">Distritos Lima</div></div>
      <div class="kpi-cell"><div class="kpi-num">80+</div><div class="kpi-lbl">Reglas de negocio</div></div>
      <div class="kpi-cell"><div class="kpi-num">3</div><div class="kpi-lbl">Verticales de mercado</div></div>
    </div>
    <p class="bt">SOLUM es la primera plataforma de análisis inmobiliario de alta precisión construida para el mercado de Lima. Integra normativa urbanística real, modelos financieros calibrados y análisis legal automatizado — en una interfaz unificada, con reportes listos para presentar al cliente.</p>
    <p class="bt"><b>No es un chatbot.</b> Es un sistema analítico que combina cuatro pilares:</p>
    <table>
      <thead><tr><th>Pilar</th><th>Descripción</th></tr></thead>
      <tbody>
        <tr><td><b>Normativa municipal real</b></td><td>27 distritos de Lima con Ordenanzas específicas, interpretadas y validadas por zona</td></tr>
        <tr><td><b>Motor financiero calibrado</b></td><td>Benchmarks Lima 2025–2026: costos, rentas y velocidades de venta por mercado</td></tr>
        <tr><td><b>IA de última generación</b></td><td>Claude (Anthropic) — el modelo más avanzado disponible hoy</td></tr>
        <tr><td><b>Flujo de trabajo integrado</b></td><td>Terreno → Normativa → Cabida → Finanzas → Reporte en una sola sesión</td></tr>
      </tbody>
    </table>
    <div class="hbox"><p>"SOLUM hace en 90 segundos lo que un equipo de análisis tarda 3 semanas. El usuario no necesita saber IA — necesita saber inmobiliario."</p></div>
  </div>
  {page_footer(3)}
</div>

<!-- III — CÓMO FUNCIONA -->
<div class="page">
  {page_header("III · Cómo Funciona")}
  <div class="pb">
    <div class="sec-lbl">Sección III</div><div class="sec-title">Cómo Funciona</div><div class="sec-rule"></div>
    <div class="step-card"><div class="step-n">01</div><div class="step-body"><div class="step-title">Ingreso del Predio</div><div class="step-desc">El usuario carga el Certificado de Parámetros Urbanísticos (CPUE) y la Partida SUNARP. SOLUM extrae automáticamente: área, zonificación, retiros, altura máxima, CUS, COS, área libre y estacionamiento exigido.</div></div></div>
    <div class="step-card"><div class="step-n">02</div><div class="step-body"><div class="step-title">Normativa Específica por Distrito</div><div class="step-desc">Aplica la ordenanza correcta por predio. San Isidro: altura por ámbito A/B/C/D (Ord. 523-MSI). Magdalena: tope 4 pisos fijos. Lurín: lote mínimo 5,000 m², retiros dinámicos. Cada distrito tiene su lógica propia.</div></div></div>
    <div class="step-card"><div class="step-n">03</div><div class="step-body"><div class="step-title">Cabida Arquitectónica</div><div class="step-desc">Calcula pisos, área construible por nivel, área libre, estacionamientos, número máximo de unidades por tipología y mix óptimo (1D/2D/3D) para maximizar rentabilidad dentro de los límites normativos.</div></div></div>
    <div class="step-card"><div class="step-n">04</div><div class="step-body"><div class="step-title">Análisis Financiero Completo</div><div class="step-desc">DCF mensual: preventa, construcción, ventas, cierre. TIR, VAN, margen neto. Precio máximo de terreno. Sensibilidad precio×costo en matriz 7×7. Escenarios Conservador/Base/Optimista. 80+ alertas de riesgo.</div></div></div>
    <div class="step-card"><div class="step-n">05</div><div class="step-body"><div class="step-title">Reporte Ejecutivo</div><div class="step-desc">Excel descargable con DCF estructurado. PDF institucional listo para bancos y socios. Informe HTML para envío digital. Propuesta comercial con análisis completo del predio.</div></div></div>
  </div>
  {page_footer(4)}
</div>

<!-- IV — CAPACIDADES -->
<div class="page">
  {page_header("IV · Capacidades")}
  <div class="pb">
    <div class="sec-lbl">Sección IV</div><div class="sec-title">Capacidades</div><div class="sec-rule"></div>
    <div class="two-col">
      <div>
        <div class="col-hdr">Residencial</div>
        <ul class="bl">
          <li>Multifamiliar en 27 distritos de Lima Metropolitana</li>
          <li>Mix 1D/2D/3D con áreas mínimas por distrito</li>
          <li>Precio/m² por rango de área, no por n.° de dormitorios</li>
          <li>Integración Mi Vivienda y Bono Buen Pagador</li>
          <li>Velocidad de ventas calibrada por zona y segmento</li>
        </ul>
        <div class="col-hdr" style="margin-top:14px;">Industrial</div>
        <ul class="bl">
          <li>Naves y almacenes: Lurín, Ate, VES, SJL, Callao</li>
          <li>Parámetros I1/I2/I3/IE con restricciones por zona</li>
          <li>Índice de Usos ATN-I: 6,349 actividades clasificadas</li>
          <li>Benchmarks renta prime Lima: $5.50–8.50/m²/mes</li>
          <li>Costo nave estándar $350/m² · Estructura total ~$480/m²</li>
        </ul>
      </div>
      <div>
        <div class="col-hdr">Oficinas</div>
        <ul class="bl">
          <li>Clusters prime: San Isidro, San Borja, Miraflores, Surco</li>
          <li>Precio compra y alquiler por antigüedad del edificio</li>
          <li>Referentes: Grupo Breca, Grupo Centenario</li>
          <li>Análisis de vacancia y absorción por submercado</li>
        </ul>
        <div class="col-hdr" style="margin-top:14px;">Inteligencia Jurídica</div>
        <ul class="bl">
          <li>Lectura automática Partidas SUNARP — papel y electrónico</li>
          <li>Titular vigente: asiento más reciente prevalece</li>
          <li>Hipotecas activas vs. canceladas — validación rubros D/E</li>
          <li>Red flags: litigios, gravámenes, embargos, cautelares</li>
          <li>Verificación Alcabala y exoneraciones primera venta</li>
        </ul>
      </div>
    </div>
  </div>
  {page_footer(5)}
</div>

<!-- V — FORTALEZA -->
<div class="page">
  {page_header("V · Ventaja Competitiva")}
  <div class="pb">
    <div class="sec-lbl">Sección V</div><div class="sec-title">La Fortaleza — Ventaja Competitiva</div><div class="sec-rule"></div>
    <div class="str-card"><div class="str-n">1</div><div class="str-body"><div class="str-title">Know-how que no se replica con $20/mes</div><div class="str-text">La ventaja de SOLUM no es el modelo de IA — Claude está disponible para cualquier desarrollador. La ventaja es el <b>conocimiento embebido</b>: 27 Ordenanzas distritales interpretadas, parámetros por zonificación/sector/ámbito/lote, benchmarks validados por transacciones reales y 80+ reglas de negocio del mercado limeño. Construido en 2+ años.</div></div></div>
    <div class="str-card"><div class="str-n">2</div><div class="str-body"><div class="str-title">Flujo integrado — no un chat, un sistema</div><div class="str-text">Un analista con Claude o ChatGPT necesita hacer las preguntas correctas, interpretar respuestas, armar el Excel y construir el reporte por su cuenta. <b>SOLUM entrega todo en una secuencia estructurada.</b> El usuario no necesita saber IA — necesita saber inmobiliario.</div></div></div>
    <div class="str-card"><div class="str-n">3</div><div class="str-body"><div class="str-title">Velocidad de decisión como ventaja real</div><div class="str-text">Los terrenos prime en San Isidro, Miraflores o los corredores logísticos de Lurín se mueven en días. SOLUM reduce el tiempo de análisis <b>de 3 semanas a 90 segundos</b> sin sacrificar precisión normativa.</div></div></div>
    <div class="str-card"><div class="str-n">4</div><div class="str-body"><div class="str-title">Confiabilidad calibrada — no alucina normativa</div><div class="str-text">SOLUM hace el <b>90% del trabajo de pre-factibilidad</b> con datos reales y validados. Los reportes incluyen la advertencia de verificación en CPUE oficial — construyendo credibilidad con clientes institucionales.</div></div></div>
  </div>
  {page_footer(6)}
</div>

<!-- VI + VII — OPORTUNIDAD + NEGOCIO -->
<div class="page">
  {page_header("VI–VII · Oportunidad & Negocio")}
  <div class="pb">
    <div class="sec-lbl">Sección VI</div><div class="sec-title">La Oportunidad de Mercado</div><div class="sec-rule"></div>
    <div class="kpi-grid kpi4">
      <div class="kpi-cell"><div class="kpi-num">+120K</div><div class="kpi-lbl">Transacciones Lima/año</div></div>
      <div class="kpi-cell"><div class="kpi-num">+800</div><div class="kpi-lbl">Proyectos activos</div></div>
      <div class="kpi-cell"><div class="kpi-num">+15K</div><div class="kpi-lbl">Asesores certificados</div></div>
      <div class="kpi-cell"><div class="kpi-num">+1,200</div><div class="kpi-lbl">Promotores activos</div></div>
    </div>
    <ul class="bl" style="margin-bottom:14px;">
      <li><b>SAM inmediato:</b> 5,000–8,000 profesionales con necesidad real de análisis rápido y confiable</li>
      <li><b>Sin competidor directo en Perú</b> — el primer jugador establece el estándar del mercado</li>
      <li><b>ARR potencial:</b> $9M–$14.4M con penetración del mercado addressable a $150/mes promedio</li>
    </ul>
    <div class="sec-lbl" style="margin-top:16px;">Sección VII</div><div class="sec-title">Modelo de Negocio</div><div class="sec-rule"></div>
    <table>
      <thead><tr><th>Plan</th><th>Perfil objetivo</th><th class="c">Precio/mes</th><th>Capacidad</th></tr></thead>
      <tbody>
        <tr><td><b>SOLUM Advisor</b></td><td>Asesores independientes, agentes</td><td class="c">$79–99</td><td>20 análisis/mes, reportes incluidos</td></tr>
        <tr><td><b>SOLUM Pro</b></td><td>Promotores, desarrolladores medianos</td><td class="c">$199–249</td><td>Ilimitado + DCF + Excel/PDF</td></tr>
        <tr><td><b>SOLUM Institutional</b></td><td>Fondos, bancos, family offices</td><td class="c">$500–800</td><td>Multi-usuario + soporte dedicado</td></tr>
      </tbody>
    </table>
    <table>
      <thead><tr><th>KPI</th><th class="c">Conservador</th><th class="c">Base</th></tr></thead>
      <tbody>
        <tr><td>Usuarios activos</td><td class="c">150</td><td class="c">400</td></tr>
        <tr><td>MRR</td><td class="c">$18,000</td><td class="c">$60,000</td></tr>
        <tr><td>ARR</td><td class="c">$216,000</td><td class="c">$720,000</td></tr>
        <tr><td>LTV / CAC</td><td class="c">4x</td><td class="c">8x</td></tr>
      </tbody>
    </table>
  </div>
  {page_footer(7)}
</div>

<!-- VIII — COMPARATIVA -->
<div class="page">
  {page_header("VIII · Comparativa")}
  <div class="pb">
    <div class="sec-lbl">Sección VIII</div><div class="sec-title">Comparativa con Herramientas Similares</div><div class="sec-rule"></div>
    <table style="margin-bottom:16px;">
      <thead><tr><th>Herramienta</th><th>País</th><th class="c">Precio/mes</th><th>Limitación vs. SOLUM</th></tr></thead>
      <tbody>
        <tr><td><b>CoStar Group</b></td><td>EE.UU.</td><td class="c">$400–1,500</td><td>Sin normativa ni cabida arquitectónica</td></tr>
        <tr><td><b>Reonomy</b></td><td>EE.UU.</td><td class="c">$500–2,000</td><td>Sin DCF ni reporte ejecutivo</td></tr>
        <tr><td><b>Argus Enterprise</b></td><td>Global</td><td class="c">$250–1,250</td><td>Sin normativa Lima · 6 meses de training</td></tr>
        <tr><td><b>Properati / Urbania</b></td><td>LatAm/Perú</td><td class="c">Gratuito</td><td>Sin análisis financiero ni normativo</td></tr>
        <tr><td><b>Claude Pro / ChatGPT</b></td><td>Global</td><td class="c">$20</td><td>Sin normativa Lima · sin DCF · sin Excel</td></tr>
      </tbody>
    </table>
    <div class="sub">SOLUM vs. Claude Pro $20/mes</div>
    <table>
      <thead><tr><th>Criterio</th><th class="c">Claude Pro $20/mes</th><th class="c">SOLUM $199/mes</th></tr></thead>
      <tbody>
        <tr><td>Normativa Ord. 523-MSI San Isidro</td><td class="c no">✗ Alucina</td><td class="c ok">✓ Integrada por ámbito</td></tr>
        <tr><td>DCF mensual con preventa automática</td><td class="c no">✗ No genera</td><td class="c ok">✓ Automático</td></tr>
        <tr><td>Excel descargable con fórmulas</td><td class="c no">✗ No</td><td class="c ok">✓ Estructurado</td></tr>
        <tr><td>Análisis Partida SUNARP asientos C/D/E</td><td class="c no">✗ Sin conocimiento</td><td class="c ok">✓ Completo</td></tr>
        <tr><td>Benchmarks Lima validados 2025–2026</td><td class="c no">✗ Dato genérico</td><td class="c ok">✓ Por mercado y zona</td></tr>
        <tr><td>Reporte PDF institucional</td><td class="c no">✗ No</td><td class="c ok">✓ Branded</td></tr>
        <tr><td>Tiempo de análisis completo</td><td class="c">2–3 horas manuales</td><td class="c"><b>90 segundos</b></td></tr>
      </tbody>
    </table>
  </div>
  {page_footer(8)}
</div>

<!-- IX — ESTRATEGIAS -->
<div class="page">
  {page_header("IX · Estrategias de los Líderes")}
  <div class="pb">
    <div class="sec-lbl">Sección IX</div><div class="sec-title">Estrategias de los Líderes — Qué Aprende SOLUM</div><div class="sec-rule"></div>
    <table>
      <thead><tr><th>Empresa</th><th>Estrategia</th><th>Aplicación SOLUM</th></tr></thead>
      <tbody>
        <tr><td><b>Procore / Argus</b></td><td>Verticalización profunda en un flujo antes de expandirse</td><td>Dominar Lima residencial + industrial primero, luego expansión regional</td></tr>
        <tr><td><b>CoStar</b></td><td>Data propietaria como barrera — 30 años de transacciones</td><td>Normativa interpretada + benchmarks validados = data propietaria de SOLUM</td></tr>
        <tr><td><b>Zillow</b></td><td>Freemium para crear hábito; el revenue viene del profesional</td><td>Cabida básica gratuita para crear hábito; el promotor que quiere el DCF paga</td></tr>
        <tr><td><b>Argus / Yardi</b></td><td>Integración con workflow institucional — permanencia total</td><td>Objetivo: que los bancos de Lima pidan el "Reporte SOLUM" en el expediente de crédito</td></tr>
        <tr><td><b>Reonomy</b></td><td>Capa analítica IA sobre data específica — adquirida CoStar $188M</td><td>Confirma el modelo: IA especializada vs. IA genérica</td></tr>
      </tbody>
    </table>
  </div>
  {page_footer(9)}
</div>

<!-- X — VALORACIÓN -->
<div class="page">
  {page_header("X · Valoración y Potencial")}
  <div class="pb">
    <div class="sec-lbl">Sección X</div><div class="sec-title">Valoración y Potencial</div><div class="sec-rule"></div>
    <div class="sub">Activos tangibles</div>
    <table style="margin-bottom:16px;">
      <thead><tr><th>Activo</th><th>Descripción</th><th class="c">Valor estimado</th></tr></thead>
      <tbody>
        <tr><td><b>Plataforma tecnológica</b></td><td>6+ meses de desarrollo, arquitectura escalable</td><td class="c">$80K–$150K</td></tr>
        <tr><td><b>Normativa estructurada</b></td><td>27 distritos, 2+ años de validación y calibración</td><td class="c">$100K–$200K</td></tr>
        <tr><td><b>Modelos financieros</b></td><td>DCF, sensibilidades, benchmarks Lima 2025–2026</td><td class="c">$50K–$80K</td></tr>
        <tr><td><b>Sistema de alertas</b></td><td>80+ reglas de negocio del mercado limeño</td><td class="c">$30K–$50K</td></tr>
        <tr class="total"><td colspan="2"><b>Total activos tangibles</b></td><td class="c"><b>$260K–$480K</b></td></tr>
      </tbody>
    </table>
    <div class="sub">Valoración por múltiplo ARR</div>
    <table style="margin-bottom:14px;">
      <thead><tr><th>Escenario</th><th class="c">ARR Año 1</th><th class="c">Múltiplo</th><th class="c">Valoración</th></tr></thead>
      <tbody>
        <tr><td>Conservador</td><td class="c">$216,000</td><td class="c">5x</td><td class="c">$1,080,000</td></tr>
        <tr><td>Base</td><td class="c">$720,000</td><td class="c">6x</td><td class="c">$4,320,000</td></tr>
        <tr><td>Optimista</td><td class="c">$1,800,000</td><td class="c">8x</td><td class="c"><b>$14,400,000</b></td></tr>
      </tbody>
    </table>
    <div class="val-box">
      <div class="val-lbl">Valoración pre-money defendible — Ronda Seed</div>
      <div class="val-num">$1,000,000 — $2,500,000</div>
    </div>
    <ul class="bl">
      <li>No hay deuda de conocimiento — el know-how ya está construido y validado</li>
      <li>El producto funciona hoy — no es un deck, es un sistema operativo</li>
      <li>Sin competidor directo en Perú — el primer jugador establece el estándar</li>
    </ul>
  </div>
  {page_footer(10)}
</div>

<!-- XI + XII — PITCH + PASOS -->
<div class="page">
  {page_header("XI–XII · Pitch & Próximos Pasos")}
  <div class="pb">
    <div class="sec-lbl">Sección XI</div><div class="sec-title">El Pitch — 60 Segundos</div><div class="sec-rule"></div>
    <div class="pitch-box">
      <p>"El mercado inmobiliario de Lima mueve $12,000 millones al año. Los promotores, asesores y fondos que participan en ese mercado toman decisiones de inversión con análisis que toman semanas y cuestan miles de dólares.<br><br>
      SOLUM comprime ese proceso a 90 segundos.<br><br>
      No es inteligencia artificial genérica. Es la primera plataforma analítica construida para Lima — con normativa urbanística real de 27 distritos, modelos financieros calibrados con benchmarks del mercado y análisis legal automatizado de partidas SUNARP.<br><br>
      Un promotor que paga $200 al mes en SOLUM reemplaza al analista junior que le cuesta S/.4,000 mensuales y tarda 3 días en entregar un análisis. ROI en el primer terreno."</p>
    </div>
    <div class="sec-lbl" style="margin-top:20px;">Sección XII</div><div class="sec-title">Próximos Pasos</div><div class="sec-rule"></div>
    <table style="margin-bottom:20px;">
      <thead><tr><th>Hito</th><th class="c">Plazo</th><th>Objetivo</th></tr></thead>
      <tbody>
        <tr><td><b>Soft launch — red privada beta</b></td><td class="c">Q3 2026</td><td>30–50 usuarios, feedback y primeras métricas</td></tr>
        <tr><td><b>Lanzamiento público</b></td><td class="c">Q4 2026</td><td>150 usuarios activos, primeros ingresos recurrentes</td></tr>
        <tr><td><b>Lima completa + Arequipa</b></td><td class="c">Q1 2027</td><td>400 usuarios, $60K MRR</td></tr>
        <tr><td><b>Ronda seed institucional</b></td><td class="c">Q2 2027</td><td>$400K–$800K para escala operativa</td></tr>
        <tr><td><b>Expansión regional</b></td><td class="c">2027–2028</td><td>Colombia / Chile — replicar modelo en nuevos mercados</td></tr>
      </tbody>
    </table>
    <div class="cierre">
      <div>
        <div class="cierre-brand">SOLUM</div>
        <div class="cierre-sub">Plataforma Analítica Inmobiliaria · Grupo Osterling Advisory</div>
        <div class="cierre-email">eosterling@grupoosterling.com · grupoosterling.com</div>
      </div>
      {sized(SVG_WHITE, "52px", "52px")}
    </div>
    <div class="disc">Documento confidencial preparado para uso exclusivo del destinatario. Prohibida su reproducción sin autorización escrita de Grupo Osterling Advisory. Las proyecciones son estimaciones basadas en información disponible a junio 2026 y no constituyen garantía de resultados. Lima, Perú · 2026</div>
  </div>
  {page_footer(11)}
</div>

</body>
</html>"""

async def build():
    html = build_html()
    html_path = DIR / "_teaser_tmp.html"
    html_path.write_text(html, encoding="utf-8")
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.goto(f"file://{html_path}", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        await page.pdf(
            path=str(OUT),
            format="A4",
            print_background=True,
            margin={"top":"0mm","bottom":"0mm","left":"0mm","right":"0mm"},
        )
        await browser.close()
    html_path.unlink()
    print(f"✓  {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")

if __name__ == "__main__":
    asyncio.run(build())
