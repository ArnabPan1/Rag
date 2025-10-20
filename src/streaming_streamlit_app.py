import streamlit as st
import requests
import json

st.set_page_config(page_title="Earnings Call RAG Chatbot", page_icon="💬", layout="wide")

API_URL = "http://127.0.0.1:8000/chat/"  # your FastAPI endpoint


# -----------------------------
# Helper Functions
# -----------------------------

def stream_api_response(user_id: str, user_query: str):
    """
    Connect to FastAPI SSE endpoint and stream messages (metadata, tokens, done)
    """
    with requests.post(
        API_URL,
        params={"user_id": user_id, "user_query": user_query},
        stream=True,
    ) as response:
        if response.status_code != 200:
            yield f"[Error] {response.status_code}: {response.text}"
            return

        buffer = ""
        for line in response.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data:"):
                data_str = line.replace("data:", "").strip()
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                yield event


def logout():
    """Logout the current user."""
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    st.rerun()


# -----------------------------
# Authentication Section
# -----------------------------

if "user_id" not in st.session_state:
    st.title("🔐 Login to Chatbot")
    user_id_input = st.text_input("Enter your User ID", "")
    if st.button("Login"):
        if user_id_input.strip():
            st.session_state["user_id"] = user_id_input.strip()
            st.session_state["chat_history"] = []
            st.success(f"Logged in as {user_id_input}")
            st.rerun()
        else:
            st.error("Please enter a valid User ID.")
    st.stop()


# -----------------------------
# Main Chat Section
# -----------------------------

st.sidebar.title("⚙️ Settings")
st.sidebar.write(f"**Logged in as:** `{st.session_state.user_id}`")
st.sidebar.button("Logout", on_click=logout)

st.title("💬 Earnings Call RAG Chatbot")

# Chat display container
chat_container = st.container()

# Input area at bottom
user_query = st.chat_input("Ask something about earnings call...")

# Display existing history
with chat_container:
    for msg in st.session_state.get("chat_history", []):
        if msg["role"] == "user":
            st.chat_message("user").write(msg["content"])
        else:
            st.chat_message("assistant").write(msg["content"])


if user_query:
    user_id = st.session_state["user_id"]
    st.session_state["chat_history"].append({"role": "user", "content": user_query})
    st.chat_message("user").write(user_query)

    # Create placeholder for streaming assistant response
    with st.chat_message("assistant"):
        response_box = st.empty()
        final_text = ""
        sources = []

        # Stream directly (no threading)
        for event in stream_api_response(user_id, user_query):
            if isinstance(event, dict):
                etype = event.get("type")
                if etype == "metadata":
                    sources = event.get("metadata", [])
                elif etype == "token":
                    token = event.get("token", "")
                    final_text += token
                    response_box.markdown(final_text + "▌")
                elif etype == "done":
                    final_text = event.get("answer", final_text)
                    response_box.markdown(final_text)
            else:
                final_text += str(event)
                response_box.markdown(final_text + "▌")
        
        # Show sources after streaming completes
        if sources:
            st.markdown("**Sources:**")
            for idx, s in enumerate(sources, 1):
                with st.expander(f"Source {idx}"):
                    st.json(s)

    # Save assistant response to session
    st.session_state["chat_history"].append(
        {"role": "assistant", "content": final_text}
    )
