"""Self-contained Parking Helper assistant chatbot page (OpenAI)."""
import html
import json
import os
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from openai import OpenAI

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
except ImportError:
    pass

DATA_DIR = _PROJECT_ROOT / "data"
REPORTING_DIR = DATA_DIR / "reporting"
CHATBOT_MODEL = "gpt-4o-mini"


def _latest_row_occupancy(path: Path) -> dict | None:
    try:
        df = pd.read_csv(path)
    except Exception:
        return None
    if df.empty or "Timestamp" not in df.columns:
        return None
    last = df.iloc[-1]
    lot_id = str(last.get("ParkingLotID", path.stem.replace("_history", "")))
    spot_cols = [c for c in df.columns if c.startswith("SP")]
    if not spot_cols:
        return None
    total = len(spot_cols)
    occupied = sum(1 for c in spot_cols if str(last[c]).lower() == "occupied")
    available = total - occupied
    return {
        "lot": lot_id,
        "total_spots": total,
        "occupied_spots": occupied,
        "available_spots": available,
        "timestamp": str(last.get("Timestamp", "")),
    }


def build_occupancy_context() -> str:
    if not REPORTING_DIR.exists():
        return "No reporting directory found. No historical occupancy data."
    files = sorted(REPORTING_DIR.glob("*_history.csv"))
    if not files:
        return "No *_history.csv files yet. Occupancy snapshot unavailable."
    lines = []
    for f in files:
        info = _latest_row_occupancy(f)
        if not info:
            continue
        lines.append(
            f"- Lot {info['lot']}: total spots={info['total_spots']}, "
            f"occupied={info['occupied_spots']}, available={info['available_spots']} "
            f"(timestamp {info['timestamp']})"
        )
    if not lines:
        return "History files exist but no valid rows were read."
    return "\n".join(lines)


def _last_assistant_text(messages: list) -> str:
    for m in reversed(messages):
        if m.get("role") == "assistant":
            return m.get("content") or ""
    return ""


def render_read_aloud(last_reply: str) -> None:
    """Read assistant reply using the browser Web Speech API (no server TTS install)."""
    if not last_reply.strip():
        return
    js_text = json.dumps(last_reply)
    components.html(
        f"""
        <div style="font-family: 'Segoe UI', system-ui, sans-serif;">
          <button id="ph_tts_play" type="button" style="
            background: linear-gradient(135deg, #FF3B3B, #CC2F2F);
            color: white; border: none; border-radius: 10px; padding: 8px 18px;
            font-weight: 600; cursor: pointer; font-size: 13px;
          ">🔊 Read last reply aloud</button>
          <button id="ph_tts_stop" type="button" style="
            background: #1A1D27; color: #F0F0F5; border: 1px solid #2A2D3A;
            border-radius: 10px; padding: 8px 14px; margin-left: 8px;
            font-weight: 600; cursor: pointer; font-size: 13px;
          ">⏹ Stop</button>
        </div>
        <script>
        const txt = {js_text};
        const play = document.getElementById('ph_tts_play');
        const stop = document.getElementById('ph_tts_stop');
        if (play) play.onclick = function() {{
          try {{
            window.speechSynthesis.cancel();
            const u = new SpeechSynthesisUtterance(txt);
            u.lang = 'en-US';
            u.rate = 1.0;
            window.speechSynthesis.speak(u);
          }} catch (e) {{}}
        }};
        if (stop) stop.onclick = function() {{ window.speechSynthesis.cancel(); }};
        </script>
        """,
        height=52,
    )
    st.caption("Voice: uses your browser (Chrome / Edge / Safari). Click Read to hear the last assistant message.")


def page_chatbot() -> None:
    st.markdown(
        '<div style="font-size:28px;font-weight:700;color:#F0F0F5;letter-spacing:-0.5px;">Parking Assistant</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:14px;color:#8B8FA3;margin-bottom:16px;">'
        "Ask about lot availability, busy times, and tips — Cambrian College Parking Helper.</div>",
        unsafe_allow_html=True,
    )

    if "chatbot_messages" not in st.session_state:
        st.session_state.chatbot_messages = []

    occupancy_ctx = build_occupancy_context()
    system_prompt = (
        "You are a helpful parking assistant for the Parking Helper capstone project at Cambrian College. "
        "You answer questions about parking lot availability, typical busy times, and practical navigation "
        "tips for drivers. Be concise, accurate, and friendly. If you lack data, say so clearly.\n\n"
        "Current snapshot from the latest row in each lot's *_history.csv in reporting (use as ground truth for counts):\n"
        f"{occupancy_ctx}"
    )

    messages = st.session_state.chatbot_messages
    parts = []
    for m in messages:
        safe = html.escape(m["content"])
        if m["role"] == "user":
            parts.append(
                '<div style="text-align:right;margin:10px 0;">'
                '<span style="background:#FF3B3B22;color:#FF3B3B;border:1px solid #FF3B3B44;'
                'padding:10px 14px;border-radius:12px;display:inline-block;max-width:85%;text-align:left;">'
                f"{safe}</span></div>"
            )
        else:
            parts.append(
                '<div style="text-align:left;margin:10px 0;">'
                '<div style="background:#1A1D27;border:1px solid #2A2D3A;color:#F0F0F5;'
                'padding:12px 14px;border-radius:12px;max-width:88%;display:inline-block;">'
                f"{safe}</div></div>"
            )
    inner = (
        "".join(parts)
        if parts
        else '<div style="color:#8B8FA3;font-size:14px;">No messages yet. Say hello below.</div>'
    )
    scroll_html = (
        '<div style="background:#11131A;border:1px solid #2A2D3A;border-radius:14px;padding:16px;'
        'max-height:420px;overflow-y:auto;margin-bottom:16px;">'
        f"{inner}</div>"
    )
    st.markdown(scroll_html, unsafe_allow_html=True)

    last_reply = _last_assistant_text(messages)
    if last_reply.strip():
        render_read_aloud(last_reply)

    with st.form("chatbot_form", clear_on_submit=True):
        c1, c2 = st.columns([5, 1])
        with c1:
            user_text = st.text_input(
                "Message",
                label_visibility="collapsed",
                placeholder="Ask about parking lots, busy hours, or directions…",
            )
        with c2:
            send = st.form_submit_button("Send", use_container_width=True)

    api_key = os.environ.get("OPENAI_API_KEY")

    if send and user_text.strip():
        if not api_key:
            st.session_state.chatbot_messages.append(
                {"role": "user", "content": user_text.strip()}
            )
            st.session_state.chatbot_messages.append(
                {
                    "role": "assistant",
                    "content": "I cannot reply until OPENAI_API_KEY is set in your environment.",
                }
            )
            st.rerun()
        else:
            st.session_state.chatbot_messages.append(
                {"role": "user", "content": user_text.strip()}
            )
            try:
                client = OpenAI(api_key=api_key)
                api_messages = [{"role": "system", "content": system_prompt}]
                for m in st.session_state.chatbot_messages:
                    api_messages.append({"role": m["role"], "content": m["content"]})
                resp = client.chat.completions.create(
                    model=CHATBOT_MODEL,
                    max_tokens=500,
                    messages=api_messages,
                )
                text = (resp.choices[0].message.content or "").strip()
                st.session_state.chatbot_messages.append(
                    {"role": "assistant", "content": text or "(No response text.)"}
                )
            except Exception as e:
                st.session_state.chatbot_messages.append(
                    {
                        "role": "assistant",
                        "content": f"Sorry, something went wrong: {e!s}",
                    }
                )
            st.rerun()

    if not api_key:
        st.caption("Set OPENAI_API_KEY in your environment to enable assistant replies.")
