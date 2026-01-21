import streamlit as st
import ollama
import requests
from bs4 import BeautifulSoup
from PIL import Image
import re
import sys
import io

# 1. CONFIGURATION
st.set_page_config(page_title="FaithLoop: Vision & Search", layout="wide")
FAST_MODEL = "llama3.2" 

# 2. INITIALIZE MATLAB (Cached)
@st.cache_resource
def get_matlab_engine():
    try:
        from agent_tool import MATLABTool
        return MATLABTool()
    except ImportError: return None

matlab_tool = get_matlab_engine()

# 3. STEALTH SEARCH TOOL (The one that works!)
def search_web(query):
    """
    Manually mimics a Firefox browser to bypass search blocks.
    """
    url = "https://html.duckduckgo.com/html/"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Referer": "https://www.google.com/"
    }
    
    try:
        resp = requests.post(url, data={'q': query}, headers=headers, timeout=10)
        
        if resp.status_code != 200:
            return f"Error: Search blocked (Status {resp.status_code})"

        soup = BeautifulSoup(resp.text, 'html.parser')
        results = []
        
        for result in soup.find_all('div', class_='result__body', limit=3):
            title = result.find('a', class_='result__a')
            snippet = result.find('a', class_='result__snippet')
            if title and snippet:
                results.append(f"SOURCE: {title.get_text(strip=True)}\nFACT: {snippet.get_text(strip=True)}")

        if not results:
            return "Search successful, but no relevant text found."

        return "\n\n".join(results)

    except Exception as e:
        return f"Connection Error: {e}"

# 4. THE BRAIN (Now with Vision!)
def run_agent_workflow(user_query, image_input):
    logs = []
    
    # === A. VISION CHECK (Restored!) ===
    if image_input:
        logs.append("Vision: Analyzing image...")
        
        # Convert image for Ollama
        img_byte_arr = io.BytesIO()
        image_input.save(img_byte_arr, format=image_input.format)
        img_bytes = img_byte_arr.getvalue()
        
        # Send image to the model
        # Note: If you have a specific vision model (like llava), change FAST_MODEL below
        vision_response = ollama.chat(
            model="llava-phi3",
            messages=[{'role': 'user', 'content': f"Look at this image. {user_query}", 'images': [img_bytes]}]
        )
        return vision_response['message']['content'], logs

    # === B. TEXT ROUTER ===
    logs.append("Router: Classifying...")
    router_prompt = f"""
    Classify Query: "{user_query}"
    Options: SEARCH, MATLAB, LOGIC.
    - SEARCH: "Who is", "President", "History", "Facts", "Current events".
    - MATLAB: Math, Calculus, Matrix.
    - LOGIC: Riddles, Reasoning.
    Output 1 word.
    """
    intent = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': router_prompt}])['message']['content'].strip().upper()
    
    if "MATLAB" in intent: intent = "MATLAB"
    elif "LOGIC" in intent: intent = "LOGIC"
    else: intent = "SEARCH"
    
    logs.append(f"   Intent: {intent}")

    # === C. EXECUTION ===
    final_response = ""
    
    if intent == "MATLAB":
        if not matlab_tool: final_response = "Error: MATLAB not connected."
        else:
            code_prompt = f"Write MATLAB code for: {user_query}. Use disp(). Enclose in ```matlab```"
            resp = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': code_prompt}])
            match = re.search(r"```matlab(.*?)```", resp['message']['content'], re.DOTALL)
            if match:
                final_response = f"**MATLAB:**\n```\n{matlab_tool.run(match.group(1).strip())}\n```"
            else: final_response = "Error: Invalid MATLAB code."

    elif intent == "LOGIC":
        # Restored the Logic Execution!
        prompt = f"Write Python script to solve: '{user_query}'. Print answer. Enclose in ```python```"
        resp = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': prompt}])
        match = re.search(r"```python(.*?)```", resp['message']['content'], re.DOTALL)
        if match:
            old_stdout = sys.stdout
            redirected_output = sys.stdout = io.StringIO()
            try:
                exec(match.group(1).strip(), {}, {})
                sys.stdout = old_stdout
                final_response = f"**Logic Output:**\n{redirected_output.getvalue()}"
            except Exception as e:
                sys.stdout = old_stdout
                final_response = f"Simulation Failed: {e}"
        else: final_response = "Could not generate logic code."

    else: # SEARCH (Using the working tool)
        logs.append("Researcher: Scraping Web (Stealth Mode)...")
        evidence_text = search_web(user_query)
        logs.append(f"   Data Length: {len(evidence_text)} chars")
        
        if "Error" in evidence_text:
            final_response = f"I cannot answer. {evidence_text}"
        else:
            writer_prompt = f"""
            REAL-TIME WEB DATA:
            {evidence_text}
            
            QUESTION: {user_query}
            
            RULES:
            1. Answer using ONLY the Web Data above.
            2. State the name clearly.
            """
            final_response = ollama.chat(model=FAST_MODEL, messages=[{'role': 'user', 'content': writer_prompt}])['message']['content']

    return final_response, logs

# 5. UI
st.title("FaithLoop AI (Complete)")
up = st.file_uploader("Image", type=["png","jpg", "jpeg"])
img = Image.open(up) if up else None
if img: st.image(img)

if p := st.chat_input("Ask..."):
    with st.chat_message("user"): st.write(p)
    res, logs = run_agent_workflow(p, img)
    with st.chat_message("assistant"):
        st.write(res)
        with st.expander("System Logs"):
            for log in logs:
                st.text(log)