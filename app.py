import base64
import json
import os
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import anthropic
import requests
import streamlit as st

# ── Power BI / Fabric (para leer el último refresh real del dataset) ──────────
TZ_MX        = ZoneInfo("America/Mexico_City")
WORKSPACE_ID = "4e1a441d-2e10-4d08-95af-9e9cb7ab41cb"
DATASET_ID   = "1ce6d1c3-0021-44a2-a9f4-100122d1446a"

# ── page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Maqro Ventas SF · IA Enterprise",
    page_icon="assets/logo.png",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── brand tokens (IA Enterprise — Manual de Identidad, Sistema Synapse) ───────
INK     = "#0A1628"
AZURE   = "#2A6FDB"
AMBER   = "#F39A1E"
IVORY   = "#F7F4EE"
NAVY    = "#244269"
SLATE   = "#38414F"

MODEL = "claude-sonnet-4-6"

SUGGESTIONS = [
    "¿Cuáles son los 10 clientes con mayor Total de Ventas?",
    "Ventas mensuales 2025 vs 2024 — variación porcentual mes a mes",
    "¿Qué productos tienen mayor % de Utilidad? Ordena de mayor a menor",
    "Desempeño por vendedor: Total de Ventas, Cantidad Vendida y % Utilidad",
    "Ventas por categoría de producto: Farmacéutico, OTC y Genérico",
    "¿Cómo va el mes actual vs el mismo mes del año anterior?",
]

# ── helpers ───────────────────────────────────────────────────────────────────
LOGO_PATH   = Path(__file__).parent / "assets" / "logo.png"
AVATAR_PATH = Path(__file__).parent / "assets" / "avatar.png"
PROMPT_PATH = Path(__file__).parent / "maqro-system-prompt.txt"
LOG_PATH    = Path(__file__).parent / "logs" / "queries.jsonl"


def _log_query(query: str, reply: str | None, error: str | None, duration_ms: int) -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    record = {
        "ts":          datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status":      "error" if error else "ok",
        "duration_ms": duration_ms,
        "query":       query,
        "reply":       reply[:2000] if reply else None,
        "error":       error,
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


@st.cache_data
def _avatar_data_url() -> str:
    path = AVATAR_PATH if AVATAR_PATH.exists() else LOGO_PATH
    if path.exists():
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        return f"data:image/png;base64,{b64}"
    return "assistant"


@st.cache_data
def _load_system_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return "Eres un asistente experto en el modelo semántico Maqro Ventas SF de Power BI."


_MESES_ES = [
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def _current_date_block() -> str:
    """
    Fecha actual real, inyectada en cada llamada. Sin esto, Claude no sabe
    qué día es y termina infiriendo el "mes actual" a partir del último dato
    disponible (p. ej. junio), lo cual es incorrecto.
    """
    now = datetime.now(TZ_MX)
    mes = _MESES_ES[now.month - 1]
    return (
        "\n\n# FECHA ACTUAL DEL SISTEMA (AUTORIDAD ÚNICA PARA EL TIEMPO)\n"
        f"Hoy es {now:%Y-%m-%d}, {mes} de {now.year}.\n"
        f'Cuando el usuario diga "este mes", "mes actual", "hoy", "este año" '
        f"o similar, el punto de referencia es SIEMPRE esta fecha: "
        f"mes actual = {mes} {now.year}, año actual = {now.year}.\n"
        "NUNCA deduzcas la fecha actual a partir del último refresh del modelo "
        "ni del último mes con datos. El modelo puede contener datos hasta un "
        "mes anterior y aun así el mes actual es el indicado aquí. Si el mes "
        "actual no tiene datos todavía, dilo explícitamente en vez de asumir "
        "que el último mes con datos es el mes actual."
    )


def _secret(name: str, default: str = "") -> str:
    try:
        return st.secrets[name]
    except (KeyError, FileNotFoundError):
        return os.environ.get(name, default)


@st.cache_data(ttl=900, show_spinner=False)
def _last_refresh() -> str | None:
    """
    Último refresh real del dataset vía Power BI REST (cacheado 15 min).
    Devuelve 'YYYY-MM-DD HH:MM' en hora de México, o None si no se pudo obtener
    (p. ej. faltan credenciales del Service Principal en los Secrets).
    """
    tenant = _secret("AZURE_TENANT_ID")
    cid    = _secret("AZURE_CLIENT_ID")
    secret = _secret("AZURE_CLIENT_SECRET")
    if not (tenant and cid and secret):
        return None
    try:
        tok = requests.post(
            f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
            data={
                "client_id":     cid,
                "client_secret": secret,
                "scope":         "https://analysis.windows.net/powerbi/api/.default",
                "grant_type":    "client_credentials",
            },
            timeout=10,
        ).json().get("access_token")
        if not tok:
            return None
        data = requests.get(
            f"https://api.powerbi.com/v1.0/myorg/groups/{WORKSPACE_ID}"
            f"/datasets/{DATASET_ID}/refreshes?$top=10",
            headers={"Authorization": f"Bearer {tok}"},
            timeout=10,
        ).json()
        # Toma el refresh COMPLETADO más reciente (ignora fallidos/en curso).
        done = [r for r in data.get("value", []) if r.get("status") == "Completed"]
        if not done:
            return None
        ts = done[0].get("endTime") or done[0].get("startTime")
        if not ts:
            return None
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(TZ_MX)
        return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return None


def _get_client() -> anthropic.Anthropic:
    try:
        api_key = st.secrets["ANTHROPIC_API_KEY"]
    except (KeyError, FileNotFoundError):
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        st.error("Configura ANTHROPIC_API_KEY en los Secrets de Streamlit.")
        st.stop()
    return anthropic.Anthropic(api_key=api_key)


def _get_mcp_url() -> str:
    try:
        return st.secrets["MCP_SERVER_URL"]
    except (KeyError, FileNotFoundError):
        pass
    return os.environ.get(
        "MCP_SERVER_URL",
        "https://maqro-reader.dqw1vzxn.tunnel.anthropic.com/mcp",
    )


def _stream_reply(history: list[dict], system: str, mcp_url: str):
    """Yields text chunks from claude-sonnet via remote MCP tunnel."""
    client = _get_client()
    with client.beta.messages.create(
        model=MODEL,
        max_tokens=8096,
        system=system,
        messages=history,
        betas=["mcp-client-2025-04-04"],
        mcp_servers=[{"type": "url", "url": mcp_url, "name": "maqro-reader"}],
        stream=True,
    ) as stream:
        for event in stream:
            if event.type == "content_block_delta" and event.delta.type == "text_delta":
                yield event.delta.text


# ── custom CSS ────────────────────────────────────────────────────────────────
st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Geist:wght@300;400;500;600;700&display=swap');

/* Base */
.stApp {{
    background-color: {IVORY};
    font-family: 'Geist', sans-serif;
}}

/* ── Sidebar ── */
section[data-testid="stSidebar"] > div:first-child {{
    background-color: {INK};
    border-right: none;
}}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] .stMarkdown {{
    color: rgba(247,244,238,0.80) !important;
}}
section[data-testid="stSidebar"] hr {{
    border-color: rgba(247,244,238,0.12) !important;
    margin: 14px 0 !important;
}}
section[data-testid="stSidebar"] .stButton > button {{
    background: transparent !important;
    border: 1px solid rgba(42,111,219,0.45) !important;
    color: {IVORY} !important;
    border-radius: 8px !important;
    width: 100% !important;
    font-family: 'Geist', sans-serif !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    padding: 8px 14px !important;
    transition: all 0.15s ease !important;
}}
section[data-testid="stSidebar"] .stButton > button:hover {{
    background: {AZURE} !important;
    border-color: {AZURE} !important;
    color: white !important;
}}

/* ── Suggestion chips (main area buttons) ── */
section[data-testid="stMain"] .stButton > button {{
    text-align: left !important;
    white-space: normal !important;
    height: auto !important;
    min-height: 60px !important;
    border: 1.5px solid rgba(42,111,219,0.28) !important;
    border-radius: 10px !important;
    background: white !important;
    color: {INK} !important;
    padding: 14px 16px !important;
    font-family: 'Geist', sans-serif !important;
    font-size: 14px !important;
    font-weight: 500 !important;
    line-height: 1.45 !important;
    box-shadow: 0 1px 3px rgba(10,22,40,0.06) !important;
    transition: all 0.15s ease !important;
}}
section[data-testid="stMain"] .stButton > button:hover {{
    background: {AZURE} !important;
    border-color: {AZURE} !important;
    color: white !important;
    box-shadow: 0 3px 10px rgba(42,111,219,0.25) !important;
}}

/* ── Chat messages ── */
[data-testid="stChatMessage"] {{
    background: white !important;
    border: 1px solid rgba(10,22,40,0.07) !important;
    border-radius: 12px !important;
    margin-bottom: 6px !important;
}}

/* ── Chat input ── */
[data-testid="stChatInputContainer"] {{
    background: white !important;
    border-top: 1px solid rgba(10,22,40,0.08) !important;
}}
[data-testid="stChatInputContainer"] textarea {{
    font-family: 'Geist', sans-serif !important;
    color: {INK} !important;
}}

/* ── Typography helpers ── */
.hero-title {{
    font-family: 'Instrument Serif', serif;
    font-size: clamp(28px, 4vw, 44px);
    color: {INK};
    line-height: 1.1;
    margin: 0 0 12px;
}}
.hero-sub {{
    font-family: 'Geist', sans-serif;
    font-size: 17px;
    color: {SLATE};
    margin: 0 0 34px;
    font-weight: 400;
    line-height: 1.55;
}}
.azure {{ color: {AZURE}; }}
.amber {{ color: {AMBER}; }}
.eyebrow {{
    font-family: 'Geist', sans-serif;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.13em;
    text-transform: uppercase;
    color: {SLATE};
    margin: 0 0 14px;
}}
.sidebar-label {{
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    opacity: 0.45;
    margin: 0 0 5px;
    color: {IVORY};
}}
.sidebar-value {{
    font-size: 13px;
    margin: 0 0 2px;
    color: {IVORY};
}}
.sidebar-sub {{
    font-size: 12px;
    opacity: 0.55;
    margin: 0 0 16px;
    color: {IVORY};
}}
</style>
""", unsafe_allow_html=True)

# ── session state ─────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_q" not in st.session_state:
    st.session_state.pending_q = None

# ── preload resources ─────────────────────────────────────────────────────────
AVATAR_DATA_URL = _avatar_data_url()
SYSTEM_PROMPT   = _load_system_prompt()
MCP_URL         = _get_mcp_url()

# ── sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), use_container_width=True)
    st.markdown("---")

    if st.button("Nueva conversación", key="new_chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.pending_q = None
        st.rerun()

    st.markdown("---")
    _refresh = _last_refresh() or "no disponible"
    st.markdown(f"""
<p class="sidebar-label">Modelo de datos</p>
<p class="sidebar-value">Maqro Ventas SF</p>
<p class="sidebar-sub">Fabric Trial &middot; Power BI</p>
<p class="sidebar-label">Motor IA</p>
<p class="sidebar-value">claude-sonnet-4-6</p>
<p class="sidebar-sub">Streaming &middot; MCP</p>
<p class="sidebar-label">Datos al</p>
<p class="sidebar-value">{_refresh}</p>
<p class="sidebar-sub">Último refresh del modelo</p>
""", unsafe_allow_html=True)

# ── main: logo header ─────────────────────────────────────────────────────────
if LOGO_PATH.exists():
    st.image(str(LOGO_PATH), width=190)

st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

# ── hero (only when conversation is empty) ────────────────────────────────────
if not st.session_state.messages:
    st.markdown("""
<div class="hero-title">
Inteligencia operativa<br>para <span class="azure">Maqro Ventas</span>
</div>
<p class="hero-sub">
Consulta ventas, analiza tendencias y obtén insights del modelo<br>
Salesforce — en lenguaje natural, conectado en tiempo real.
</p>""", unsafe_allow_html=True)

    st.markdown('<p class="eyebrow">Preguntas frecuentes</p>', unsafe_allow_html=True)

    col_a, col_b = st.columns(2, gap="small")
    for i, q in enumerate(SUGGESTIONS):
        target = col_a if i % 2 == 0 else col_b
        with target:
            if st.button(q, key=f"q_{i}", use_container_width=True):
                st.session_state.pending_q = q
                st.rerun()

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

# ── chat history ──────────────────────────────────────────────────────────────
for msg in st.session_state.messages:
    avatar = AVATAR_DATA_URL if msg["role"] == "assistant" else None
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

# ── resolve user input (chat box or suggestion click) ────────────────────────
if st.session_state.pending_q:
    user_input: str | None = st.session_state.pending_q
    st.session_state.pending_q = None
else:
    user_input = st.chat_input("Escribe tu pregunta sobre Maqro Ventas SF…")

# ── handle message ────────────────────────────────────────────────────────────
if user_input:
    st.session_state.messages.append({"role": "user", "content": user_input})

    with st.chat_message("user"):
        st.markdown(user_input)

    _status = st.empty()
    _status.markdown(
        f"<p style='font-size:13px;color:{SLATE};padding:2px 6px;margin:0'>"
        "Consultando Maqro Ventas SF…</p>",
        unsafe_allow_html=True,
    )

    reply: str | None = None
    error: str | None = None
    t0 = time.monotonic()

    with st.chat_message("assistant", avatar=AVATAR_DATA_URL):
        try:
            reply = st.write_stream(
                _stream_reply(
                    st.session_state.messages,
                    SYSTEM_PROMPT + _current_date_block(),
                    MCP_URL,
                )
            )
        except Exception as exc:
            error = str(exc)
            st.error(f"Error al consultar el modelo: {exc}")

    duration_ms = int((time.monotonic() - t0) * 1000)
    _log_query(user_input, reply, error, duration_ms)
    _status.empty()

    if reply:
        st.session_state.messages.append({"role": "assistant", "content": reply})

    st.rerun()
