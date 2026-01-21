import streamlit as st
import ollama
import requests
from bs4 import BeautifulSoup
from PIL import Image
import io
import re
import sys

# ==========================================
# 1. CONFIGURATION
# ==========================================
st.set_page_config(page_title="FaithLoop: Speed Control", layout="wide")
FAST_MODEL = "llama3.2"       # Text/Logic
VISION_MODEL = "llava-phi3"   # Vision

# ==========================================
# 2. INITIALIZE MATLAB
# ==========================================
@st.cache_resource
def get_matlab_engine():
    try:
        from agent_tool import MATLABTool
        return MATLABTool()
    except ImportError: return None

matlab_tool = get_matlab_engine()

# ==========================================
# 3. CONTEXT MANAGER
# ==========================================
def get_context(messages):
    if not messages: return ""
    history = messages[-4:] 
    return "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history])

# ==========================================
# 4. STEALTH SEARCH TOOL
# ==========================================
def search_web(query):
    url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Referer": "https://www.google.com/"
    }
    try:
        resp = requests.post(url, data={'q': query}, headers=headers, timeout=10)
        if resp.status_code != 200: return "Search Blocked."
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for result in soup.find_all('div', class_='result__body', limit=3):
            t = result.find('a', class_='result__a')
            s = result.find('a', class_='result__snippet')
            if t and s: results.append(f"SOURCE: {t.get_text(strip=True)}\nFACT: {s.get_text(strip=True)}")
        return "\n\n".join(results) if results else "No results."
    except Exception as e: return f"Error: {e}"

# ==========================================
# 5. THE BRAIN (With "Deep Check" Toggle)
# ==========================================
def run_agent_workflow(user_query, image_input, chat_history, status_box, deep_check_mode):
    logs = []
    
    def update_status(message, state="running"):
        logs.append(message)
        if status_box:
            status_box.update(label=message, state=state)
            status_box.write(f"⚙️ {message}")
    
    text_context = get_context(chat_history)
    visual_context = ""
    img_bytes = None

    # --- PHASE 1: INITIAL VISION ---
    if image_input:
        update_status("Phase 1: Vision Model Reading...")
        img_byte_arr = io.BytesIO()
        image_input.save(img_byte_arr, format=image_input.format)
        img_bytes = img_byte_arr.getvalue()
        
        vision_resp = ollama.chat(
            model=VISION_MODEL,  
            messages=[{'role': 'user', 'content': f"Describe the image relevant to: {user_query}", 'images': [img_bytes]}]
        )
        visual_context = vision_resp['message']['content']
        logs.append(f"   Vision saw: {visual_context[:100]}...")

    # --- PHASE 2: ROUTER ---
    combined_input = f"Chat History: {text_context}\nUser Question: {user_query}\nVisual Evidence: {visual_context}"
    update_status("Phase 2: Router deciding tool...")
    
    router_prompt = f"""
    Context: {combined_input}
    Task: Choose tool. Options: SEARCH, MATLAB, LOGIC, CHAT.
    RULES:
    - If math/equations -> MATLAB.
    - If riddle/logic -> LOGIC.
    - If fact/history -> SEARCH.
    - Else -> CHAT.
    Output 1 word.
    """
    intent = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': router_prompt}])['message']['content'].strip().upper()
    logs.append(f"   Intent: {intent}")

    initial_response = ""

    # --- PHASE 3: EXECUTION ---
    if intent == "MATLAB":
        update_status("Phase 3: Running MATLAB...")
        if not matlab_tool: initial_response = "Error: MATLAB not connected."
        else:
            code_prompt = f"Data: {combined_input}\nTask: Write MATLAB code using disp(). Enclose in ```matlab```"
            resp = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': code_prompt}])
            match = re.search(r"```matlab(.*?)```", resp['message']['content'], re.DOTALL)
            if match:
                initial_response = f"**MATLAB Solution:**\n{matlab_tool.run(match.group(1).strip())}"
            else: initial_response = "Error: Invalid MATLAB code."

    elif intent == "LOGIC":
        update_status("Phase 3: Logic Engine...")
        prompt = f"Data: {combined_input}\nTask: Python script. End with 'print(answer)'. Enclose in ```python```"
        resp = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': prompt}])
        match = re.search(r"```python(.*?)```", resp['message']['content'], re.DOTALL)
        if match:
            old_stdout = sys.stdout
            redirected_output = sys.stdout = io.StringIO()
            try:
                exec(match.group(1).strip(), {}, {})
                sys.stdout = old_stdout
                initial_response = redirected_output.getvalue().strip()
            except Exception as e:
                sys.stdout = old_stdout
                initial_response = f"Logic Error: {e}"
        else: initial_response = "Could not generate logic."

    elif intent == "SEARCH":
        update_status("Phase 3: Web Search...")
        rewrite_prompt = f"Context: {combined_input}\nTask: Search query."
        search_query = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': rewrite_prompt}])['message']['content'].strip()
        evidence = search_web(search_query)
        initial_response = f"Based on search: {evidence}"

    else: # CHAT
        initial_response = visual_context

    # --- PHASE 4: VOLCANO LOOP (ONLY IF CHECKED) ---
    final_response = initial_response
    
    if deep_check_mode and image_input and intent in ["LOGIC", "CHAT"]: 
        update_status("Phase 4: Deep Check (VOLCANO Protocol)...")
        
        # Critique
        critique_prompt = f"""
        Role: Strict Critic.
        User Question: {user_query}
        Model Answer: {initial_response}
        Task: Does the answer match the image EXACTLY? If not, explain why.
        Output: "PASS" if correct. If wrong, explain error.
        """
        critique_resp = ollama.chat(
            model=VISION_MODEL, 
            messages=[{'role': 'user', 'content': critique_prompt, 'images': [img_bytes]}]
        )
        critique_text = critique_resp['message']['content']
        logs.append(f"   Critique: {critique_text}")

        # Revise
        if "PASS" not in critique_text.upper():
            update_status("Phase 5: Final Revision...")
            revision_prompt = f"Fix this answer: {initial_response}\nCritique: {critique_text}\nWrite final correct answer."
            revision_resp = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': revision_prompt}])
            final_response = revision_resp['message']['content']
            logs.append("   Answer Revised.")
    
    elif not deep_check_mode:
        logs.append("   Deep Check Skipped (Turbo Mode).")

    update_status("Process Complete.", state="complete")
    return final_response, logs

# ==========================================
# 6. UI
# ==========================================
st.title("FaithLoop AI")

# Sidebar for controls
with st.sidebar:
    st.header("Settings")
    deep_check = st.checkbox("Enable Deep Check (Slower)", value=False, help="Checks image twice to prevent hallucinations.")

if "messages" not in st.session_state: st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "logs" in msg:
            with st.expander("Process Logs"):
                for log in msg["logs"]: st.write(log)

up = st.file_uploader("Image", type=["png","jpg","jpeg"])
img = Image.open(up) if up else None
if img: st.image(img)

if p := st.chat_input("Ask..."):
    st.session_state.messages.append({"role": "user", "content": p})
    with st.chat_message("user"): st.write(p)

    with st.chat_message("assistant"):
        with st.status("Thinking...", expanded=True) as status_box:
            # Pass the checkbox value to the agent
            res, logs = run_agent_workflow(p, img, st.session_state.messages, status_box, deep_check)
        st.write(res)

    st.session_state.messages.append({"role": "assistant", "content": res, "logs": logs})