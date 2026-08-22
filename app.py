"""
Streamlit Web UI for The Grounded Answer.
Provides an interactive front-end to query the Calder County HSP policy manual.
"""

import streamlit as st
import time

from main import _load_components, _ask_question

# Must be the first Streamlit command
st.set_page_config(
    page_title="The Grounded Answer",
    page_icon="⚖️",
    layout="centered",
)

st.title("⚖️ The Grounded Answer")
st.subheader("Calder County HSP Policy Assistant")

st.markdown("""
This assistant answers questions using **only** the official Calder County Household Support Program policy manual. 
It cites exact clauses, highlights manual contradictions, and refuses to answer if the manual lacks sufficient information.
""")

# Load models and index
@st.cache_resource(show_spinner="Loading policy manual index and AI models...")
def load_system():
    # Will sys.exit if index not found or similar
    try:
        return _load_components()
    except SystemExit:
        st.error("Error: FAISS index not found. Please run `python main.py ingest` first.")
        st.stop()

# Initialize models
retriever, generator = load_system()

if not generator:
    st.warning("GEMINI_API_KEY is not set. The assistant will retrieve clauses but cannot synthesize a plain-language answer.")

# Chat history initialization
if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        # Render citations/context if available
        if "citations" in message and message["citations"]:
            with st.expander("View Cited Clauses"):
                for c in message["citations"]:
                    st.markdown(f"**§{c['clause_id']} — {c.get('section', '')}** (lines {c.get('lines', '?')})")
                    if "text_preview" in c:
                        st.info(f"\"{c['text_preview']}\"")
        if "conflicting_clauses" in message and message["conflicting_clauses"]:
            with st.expander("View Conflicting Clauses"):
                for conflict in message["conflicting_clauses"]:
                    st.markdown(f"**§{conflict['clause_a']}**")
                    st.info(f"\"{conflict['text_a']}\"")
                    st.markdown(f"**§{conflict['clause_b']}**")
                    st.info(f"\"{conflict['text_b']}\"")

# Input for new question
if prompt := st.chat_input("Ask a policy question..."):
    # Add user message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Process answer
    with st.chat_message("assistant"):
        with st.spinner("Analyzing policy manual..."):
            result = _ask_question(prompt, verbose=False)
            
            state = result.get("state", "unknown")
            answer = result.get("answer", "Unknown error occurred.")
            citations = result.get("citations", [])
            conflicting_clauses = result.get("conflicting_clauses", [])

            # Format the output based on state
            if state == "answer":
                st.success("✅ **Answered** based on policy.")
                st.markdown(answer)
                
                if citations:
                    with st.expander("View Cited Clauses"):
                        for c in citations:
                            st.markdown(f"**§{c['clause_id']} — {c.get('section', '')}** (lines {c.get('lines', '?')})")
                            if "text_preview" in c:
                                st.info(f"\"{c['text_preview']}\"")

                if result.get("warnings"):
                    for w in result["warnings"]:
                        st.warning(f"⚠ {w}")
                        
            elif state == "conflict":
                st.warning("⚠ **Manual Conflict Detected**")
                st.markdown(answer)
                
                if conflicting_clauses:
                    with st.expander("View Conflicting Clauses"):
                        for conflict in conflicting_clauses:
                            st.markdown(f"**§{conflict['clause_a']}**")
                            st.info(f"\"{conflict['text_a']}\"")
                            st.markdown(f"**§{conflict['clause_b']}**")
                            st.info(f"\"{conflict['text_b']}\"")
                            
            elif state == "refuse":
                st.error("🚫 **Unable to Answer**")
                st.markdown(answer)
            else:
                st.markdown(answer)
            
            timing_info = []
            if "retrieval_time" in result:
                timing_info.append(f"Retrieval: {result['retrieval_time']:.2f}s")
            if "generation_time" in result:
                timing_info.append(f"Generation: {result['generation_time']:.2f}s")
            if timing_info:
                st.caption(" | ".join(timing_info))

    # Save assistant response to state
    st.session_state.messages.append({
        "role": "assistant",
        "content": answer,
        "citations": citations,
        "conflicting_clauses": conflicting_clauses
    })
