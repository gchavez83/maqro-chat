# Post LinkedIn — MCP Tunnel + Power BI Fabric
*Borrador finalizado: 2026-06-01 · Tono: personal · Autor: Guillermo Chavez*

---

## Texto del post

Hice una pregunta en lenguaje natural y obtuve esto.

Sin abrir Power BI. Sin escribir DAX. Sin dashboards precargados.

Escribí: *"Compara las ventas mensuales de 2026 vs 2025 con variación porcentual"* — y en menos de dos minutos tenía la tabla, el análisis y la gráfica que ven en las imágenes. Con datos reales, consultados en vivo.

---

**La arquitectura**

Lo que hay detrás es una cadena de tecnologías open standard que conecta Claude con un modelo semántico de Microsoft Fabric:

Pregunta en lenguaje natural → Claude Sonnet → MCP Tunnel (cloudflared) → Servidor MCP local → Power BI Fabric API → DAX ejecutado en tiempo real → Respuesta con datos, tablas y análisis

Tres piezas clave lo hacen posible:

**MCP (Model Context Protocol):** estándar abierto de Anthropic que convierte cualquier fuente de datos en un tool que el modelo puede invocar. El modelo semántico de Power BI se vuelve consultable como si fuera una función.

**Anthropic Tunnel:** expone el servidor MCP local con una URL HTTPS pública mediante cloudflared. Sin abrir puertos de entrada. Sin API Gateway. Sin infraestructura adicional. Un token revocable desde la consola en segundos.

**Streamlit Community Cloud:** el frontend deployado desde GitHub en minutos, con streaming de respuestas en tiempo real. Cero infraestructura propia.

---

**¿Y la seguridad de los datos?**

Es la primera pregunta en cualquier conversación enterprise sobre LLMs. Y es completamente legítima. Esta arquitectura fue diseñada con eso en mente desde el principio:

El modelo semántico de Power BI actúa como escudo: el LLM ejecuta DAX contra una capa de abstracción que el equipo de datos ya controló y aprobó. No hay acceso a tablas raw ni a otros workspaces.

El servidor MCP corre en infraestructura propia, autenticado con un Service Principal de solo lectura. Las credenciales nunca salen del entorno local.

El tunnel usa cloudflared con conexión saliente únicamente. TLS end-to-end. Sin puertos abiertos al exterior.

Lo que viaja por la API de Anthropic son resultados de queries agregadas — no la estructura del modelo, no credenciales, no datos no consultados explícitamente. Y por política explícita de Anthropic: los datos enviados via API no se usan para entrenar modelos. Con acuerdo enterprise se activa Zero Data Retention.

Cada consulta queda registrada en un log de auditoría local. Sin dependencia de registros externos.

¿Riesgo cero? No existe en ningún sistema conectado a internet. Pero el nivel de control es comparable — y en algunos aspectos superior — al de una integración tradicional con una API REST corporativa.

---

**El resultado práctico**

Cualquier persona del equipo puede consultar el modelo semántico en lenguaje natural, sin saber que existe Power BI detrás. Llevamos años hablando de democratizar el acceso a los datos. Esta arquitectura lo hace literal — con los controles de seguridad que una organización real necesita.

¿Alguien más está explorando MCP para conectar LLMs con fuentes de datos empresariales? Me interesa mucho saber cómo están resolviendo el tema de seguridad en sus implementaciones.

---

#MCP #ModelContextProtocol #Anthropic #Claude #PowerBI #MicrosoftFabric #BusinessIntelligence #DataAnalytics #LLM #Streamlit #DataSecurity #AIEngineering #BI

---

## Instrucciones de publicación

### Carrusel de imágenes (en este orden)
1. **Slide 1** — Tabla mensual 2026 vs 2025 con indicadores verde/rojo: gancho visual inmediato
2. **Slide 2** — Análisis clave con resumen comparativo: muestra interpretación, no solo datos
3. **Slide 3** — Gráfica de barras comparativa: cierre visual que refuerza la potencia del output

### Antes de publicar
- Verificar que ninguna imagen muestre nombre del cliente o datos que lo identifiquen
- Las capturas actuales se ven limpias en ese sentido

### Primer comentario sugerido
Agregar el link al repo público para quien quiera ver el código:
https://github.com/gchavez83/maqro-chat
