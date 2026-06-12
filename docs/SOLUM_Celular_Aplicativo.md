# SOLUM — Aplicativo Móvil
## Análisis y Hoja de Ruta

*Documento de referencia — creado 12 junio 2026*

---

## Contexto

El usuario identificó la app **Pazos.AI** como referencia de arquitectura móvil deseable para SOLUM.
Pazos.AI es un CRM inmobiliario mobile-first construido probablemente con **React Native / Expo**,
con backend Supabase y auth via magic link (código por email).

---

## Pantallas de referencia observadas (Pazos.AI)

| Pantalla | Patrón clave |
|---|---|
| Login | Full-screen background image · logo centrado · magic link auth · card oscuro superpuesto |
| Home / Dashboard | Header con título · cards con borde izquierdo coloreado · bottom nav bar fija |
| Leads | Section headers en small caps · list items: icono + título + descripción + chevron |
| Detalle propiedad | Back arrow en header · **horizontal scrollable tabs** · grid 2 columnas para datos · cards por sección |
| Ajustes | Avatar + email · grouped settings list · logout button rojo |

**Elemento destacado:** Las pestañas horizontales deslizables con el dedo en la vista de detalle —
permite navegar entre secciones sin ocupar espacio vertical.

---

## Análisis Técnico

### Stack identificado en Pazos.AI
- **Frontend:** React Native / Expo
- **Auth:** Magic link por email (mismo patrón que SOLUM)
- **Backend:** Probablemente Supabase (mismo que SOLUM)
- **Paleta:** Dark navy #0D2137 + acento naranja — análogo a SOLUM (dark navy + teal)
- **Origen:** Construida con IA (confirmado por patrón de colores y perfil del equipo)

---

## Cuadro Comparativo: Opciones para SOLUM Móvil

| Aspecto | Streamlit CSS responsive | React Native / Expo (como Pazos) |
|---|---|---|
| Bottom nav bar | Sí, con CSS inyectado | Nativo y fluido |
| Cards scrollables | Sí | Nativo |
| Horizontal tabs deslizables | Parcial (HTML custom) | Nativo |
| Formularios complejos | Difícil — widgets Streamlit no son touch-native | Nativo |
| Gráficos Plotly | Problemático en móvil | Igual de problemático |
| Sensación de app real | ~60% | 100% |
| Esfuerzo estimado | 1–2 semanas | 3–4 semanas |
| Requiere nuevo repositorio | No | Sí |
| Reutiliza backend Supabase | Sí | Sí |
| Reutiliza lógica de negocio | Sí (misma app) | No — solo consume datos |

---

## Recomendación Acordada

**Arquitectura híbrida — No reemplazar Streamlit, construir un companion móvil en Expo.**

```
SOLUM Desktop (Streamlit)
        ↕
    Supabase
        ↕
SOLUM Mobile (Expo / React Native)
```

### Qué haría el companion móvil

- Login con magic link (Resend ya está configurado)
- Ver historial de análisis guardados (tabla analisis_historial ya existe en Supabase)
- Consultas rápidas: precio de mercado por distrito, RIN, benchmarks
- Recibir alertas de normativas
- Ver resumen ejecutivo de análisis guardados en Portfolio
- **NO hace análisis profundo** — cabida, financiero, PDF siguen en desktop

### Qué sigue en desktop (Streamlit)

- Ingreso de parámetros (formularios extensos)
- Generación de cabida arquitectónica con IA
- Modelos financieros completos
- Reportes PDF / Excel
- Massing 3D / Gantt / Sensibilidad

---

## Stack propuesto para el companion móvil

| Componente | Tecnología |
|---|---|
| Framework | Expo (React Native) |
| Navegación | Expo Router (file-based, bottom tabs nativo) |
| UI | NativeWind (Tailwind para React Native) o Tamagui |
| Backend | Supabase JS client (mismo proyecto) |
| Auth | Supabase magic link + Resend (ya configurado) |
| Estado | Zustand o React Query |
| Notificaciones push | Expo Notifications + Supabase Edge Functions |

---

## Prerequisitos antes de arrancar

- [ ] Definir las 4–5 pantallas exactas del MVP móvil
- [ ] Confirmar si el companion es solo para Kike o también para clientes/equipo
- [ ] Decidir si se publica en App Store / Play Store o solo se usa via Expo Go (link directo)
- [ ] Crear nuevo repositorio: `SOLUM-Mobile` o `FACTIS-Mobile`

---

## Nota sobre Claude Code

Claude Code puede construir la app Expo sin plugins adicionales.
React Native + Expo es código JavaScript/TypeScript estándar.
El backend Supabase ya existe y está documentado.
Tiempo estimado de desarrollo: **3–4 sesiones de trabajo**.

---

*Retomar esta tarea abriendo este documento como contexto de inicio de sesión.*
