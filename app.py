import streamlit as st
import ollama
import requests
from bs4 import BeautifulSoup
from PIL import Image
import re
import sys
import io
import datetime

# ==========================================
# 1. CONFIGURATION
# ==========================================
st.set_page_config(page_title="FaithLoop: Polished Edition", layout="wide")
FAST_MODEL = "llama3.2"       # Fast Brain (Text)
VISION_MODEL = "llava-phi3"   # Eye (Images) - MUST be installed

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
# 3. CONTEXT MANAGER (Memory)
# ==========================================
def get_context(messages):
    """
    Combines the last 2 turns of conversation so the AI knows who 'he' or 'it' is.
    """
    if not messages: return ""
    history = messages[-4:] 
    context_str = "\n".join([f"{m['role'].upper()}: {m['content']}" for m in history])
    return context_str

# ==========================================
# 4. STEALTH SEARCH TOOL (Anti-Block)
# ==========================================
def search_web(query):
    url = "https://html.duckduckgo.com/html/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://www.google.com/"
    }
    try:
        resp = requests.post(url, data={'q': query}, headers=headers, timeout=10)
        if resp.status_code != 200: return f"Error: Status {resp.status_code}"
        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        for result in soup.find_all('div', class_='result__body', limit=3):
            title = result.find('a', class_='result__a')
            snippet = result.find('a', class_='result__snippet')
            if title and snippet:
                results.append(f"SOURCE: {title.get_text(strip=True)}\nFACT: {snippet.get_text(strip=True)}")
        if not results: return "No text results found."
        return "\n\n".join(results)
    except Exception as e: return f"Connection Error: {e}"

# ==========================================
# 5. THE BRAIN (Logic + Beautifier)
# ==========================================
def run_agent_workflow(user_query, image_input, chat_history):
    logs = []
    
    # Get Conversation Context
    context_str = get_context(chat_history)
    
    # --- A. VISION CHECK ---
    if image_input:
        logs.append("Vision: Analyzing image...")
        img_byte_arr = io.BytesIO()
        image_input.save(img_byte_arr, format=image_input.format)
        img_bytes = img_byte_arr.getvalue()
        
        vision_response = ollama.chat(
            model=VISION_MODEL,  
            messages=[{'role': 'user', 'content': f"Look at this image. {user_query}", 'images': [img_bytes]}]
        )
        return vision_response['message']['content'], logs

    # --- B. TEXT ROUTER ---
    logs.append("Router: Classifying...")
    router_prompt = f"""
    Chat History:
    {context_str}
    
    Current Question: "{user_query}"
    
    Task: Classify the Current Question.
    Options: SEARCH, MATLAB, LOGIC.
    - SEARCH: Facts, "Who is", "Age of", News.
    - MATLAB: Math, Calculus, Matrix.
    - LOGIC: Riddles, Python code, Future dates, "How old will he be".
    Output 1 word.
    """
    intent = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': router_prompt}])['message']['content'].strip().upper()
    
    if "MATLAB" in intent: intent = "MATLAB"
    elif "LOGIC" in intent: intent = "LOGIC"
    else: intent = "SEARCH"
    
    logs.append(f"   Intent: {intent}")

    # --- C. EXECUTION ---
    final_response = ""
    
    if intent == "MATLAB":
        if not matlab_tool: final_response = "Error: MATLAB not connected."
        else:
            code_prompt = f"History: {context_str}\nTask: Write MATLAB code for: {user_query}. Use disp(). Enclose in ```matlab```"
            resp = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': code_prompt}])
            match = re.search(r"```matlab(.*?)```", resp['message']['content'], re.DOTALL)
            if match:
                final_response = f"**MATLAB:**\n```\n{matlab_tool.run(match.group(1).strip())}\n```"
            else: final_response = "Error: Invalid MATLAB code."

    elif intent == "LOGIC":
        # 1. Generate Python Code
        prompt = f"""
        History: {context_str}
        Task: Write Python script to solve: '{user_query}'.
        CRITICAL: You MUST end with 'print(answer)'.
        Enclose in ```python```
        """
        resp = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': prompt}])
        match = re.search(r"```python(.*?)```", resp['message']['content'], re.DOTALL)
        
        if match:
            old_stdout = sys.stdout
            redirected_output = sys.stdout = io.StringIO()
            try:
                # 2. Execute Code
                exec(match.group(1).strip(), {}, {})
                sys.stdout = old_stdout
                raw_result = redirected_output.getvalue().strip()
                logs.append(f"   Raw Logic Result: {raw_result}")

                # 3. BEAUTIFIER (New!)
                # Turns "82" into "He will be 82 years old."
                beautify_prompt = f"""
                Question: {user_query}
                Calculated Answer: {raw_result}
                Task: Write a natural sentence response. Do not explain the math.
                """
                final_response = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': beautify_prompt}])['message']['content']
                
            except Exception as e:
                sys.stdout = old_stdout
                final_response = f"Simulation Failed: {e}"
        else: final_response = "Could not generate logic code."

    else: # SEARCH
        # Rewrite query to resolve "He"
        rewrite_prompt = f"""
        History: {context_str}
        Current: {user_query}
        Task: Rewrite 'Current' to be a full standalone search query (replace 'he'/'it' with names).
        Output ONLY the query.
        """
        search_query = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': rewrite_prompt}])['message']['content'].strip()
        logs.append(f"   Rewritten Query: {search_query}")
        
        logs.append("Researcher: Scraping Web...")
        evidence_text = search_web(search_query)
        
        if "Error" in evidence_text:
            final_response = f"I cannot answer. {evidence_text}"
        else:
            writer_prompt = f"DATA: {evidence_text}\nQUESTION: {user_query}\nAnswer concisely using DATA."
            final_response = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': writer_prompt}])['message']['content']

    return final_response, logs

# ==========================================
# 6. UI
# ==========================================
st.title("FaithLoop AI (Pro Edition)")

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display History
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])
        if "logs" in msg:
            with st.expander("System Logs"):
                for log in msg["logs"]:
                    st.text(log)

# Inputs
up = st.file_uploader("Image", type=["png","jpg", "jpeg"])
img = Image.open(up) if up else None
if img: st.image(img)

if p := st.chat_input("Ask..."):
    # Save User Msg
    st.session_state.messages.append({"role": "user", "content": p})
    with st.chat_message("user"): st.write(p)

    # Run AI with History
    res, logs = run_agent_workflow(p, img, st.session_state.messages)

    # Save Assistant Msg
    st.session_state.messages.append({"role": "assistant", "content": res, "logs": logs})
    with st.chat_message("assistant"):
        st.write(res)
        with st.expander("System Logs"):
            for log in logs:
                st.text(log)