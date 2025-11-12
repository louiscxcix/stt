import base64
import json
import os
import re
from pathlib import Path

import requests
import streamlit as st


# --- Function to encode an image file to Base64 ---
def img_to_base64(image_path):
    """Converts a local image file into a Base64 string."""
    try:
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    except FileNotFoundError:
        st.warning(
            f"Icon file not found: {image_path}. Running the app without an icon."
        )
        return None


# --- API Call Function ---
def get_refocus_plan_from_gemini(api_key, situation):
    """Calls the Gemini API to generate a refocusing plan."""
    prompt = f"""
        You are a professional sports psychologist who coaches athletes on their mentality.

        A 'Refocusing Plan' is a concrete action plan to help an athlete break the cycle of negative thoughts and refocus on the present when faced with an unexpected situation.

        Now, analyze the situation entered by the user and create a 'Refocusing Plan'. The output must consist of three parts: [Situation Summary], [Outcome Goal], and [Process Goal].

        1.  **[Situation Summary]**: Clearly summarize the user's input 'situation' in one sentence, in the format "In [the situation], I feel [the emotion]".
        2.  **[Outcome Goal]**: Based on the summarized situation, present a cognitive shift the athlete should adopt—i.e., a 'goal for thinking'—in a rational sentence.
        3.  **[Process Goal]**: Present a concrete and clear 'goal for action' that the athlete can immediately execute.

        - Important: Emphasize the most crucial keywords or phrases in the Outcome Goal and Process Goal by wrapping them in Markdown bold format (`**keyword**`).
        - Add a brief explanation after each goal.

        You must adhere to the response format shown in the example below:
        [Situation Summary]
        {{AI-generated situation summary}}
        [Outcome Goal]
        {{Generated outcome goal}}
        [Outcome Goal Explanation]
        {{Generated outcome goal explanation}}
        [Process Goal]
        {{Generated process goal}}
        [Process Goal Explanation]
        {{Generated process goal explanation}}

        ---
        User Input Situation: "{situation}"
    """
    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-preview-05-20:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    data = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        response = requests.post(
            api_url, headers=headers, data=json.dumps(data), timeout=120
        )
        response.raise_for_status()
        result = response.json()
        if "candidates" in result and result["candidates"]:
            part = result["candidates"][0].get("content", {}).get("parts", [{}])[0]
            return part.get("text", "Error: Could not find text in the response.")
        else:
            return f"Error: API response is empty or in an unexpected format.\nResponse content: {result}"
    except requests.exceptions.RequestException as e:
        return f"An error occurred during the API request: {e}"
    except Exception as e:
        return f"An unknown error occurred: {e}"


# --- UI Styling and Component Functions ---
def apply_ui_styles():
    """Defines the CSS styles that will be applied to the entire app."""
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;700&display=swap');
            
            :root {
                --primary-color: #2BA7D1;
                --black-color: #0D1628;
                --secondary-color: #86929A;
                --gray-color: #898D99;
                --divider-color: #F1F1F1;
                --icon-bg-color: rgba(12, 124, 162, 0.04);
            }

            .stApp {
                background-color: #f0f2f5;
            }
            
            /* Completely remove Streamlit header and default padding */
            div.block-container {
                padding: 2rem 1rem 1.5rem 1rem !important;
            }
            
            header[data-testid="stHeader"] {
                display: none !important;
            }

            body, .stTextArea, .stButton>button {
                font-family: 'Noto Sans', sans-serif;
            }

            .icon-container {
                width: 68px;
                height: 68px;
                background-color: var(--icon-bg-color);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin-bottom: 12px;
            }
            .icon-container img {
                width: 52px;
                height: 52px;
            }

            .title {
                font-size: 24px;
                font-weight: 700;
                color: var(--black-color);
                line-height: 36px;
                margin-bottom: 8px;
            }
            .subtitle {
                font-size: 16px;
                color: var(--secondary-color);
                line-height: 24px;
                margin-bottom: 14px;
            }
            
            /* Text input area style */
            .stTextArea textarea {
                background-color: #f9fafb;
                border: 1px solid #D1D5DB;
                border-radius: 12px;
            }

            .section {
                padding-bottom: 20px;
                margin-bottom: 20px;
            }

            .section-header {
                font-size: 12px;
                font-weight: 400;
                color: var(--gray-color);
                margin-bottom: 4px;
            }
            .section-title {
                font-size: 18px;
                font-weight: 700;
                color: var(--black-color);
                line-height: 28px;
                margin-bottom: 12px;
            }
            
            .goal-text {
                font-size: 18px;
                font-weight: 700;
                color: var(--black-color);
                line-height: 28px;
            }
            .goal-text span {
                color: var(--primary-color);
            }
            
            .explanation-text {
                font-size: 13px;
                color: var(--secondary-color);
                line-height: 20px;
                margin-top: 12px;
            }
            
            .stButton>button {
                background: linear-gradient(135deg, rgba(98, 120.20, 246, 0.20) 0%, rgba(29, 48, 78, 0) 100%), var(--primary-color) !important;
                color: white !important;
                font-size: 14px;
                font-weight: 400;
                border-radius: 12px;
                padding: 14px 36px;
                border: none;
                box-shadow: 0px 5px 10px rgba(26, 26, 26, 0.10);
                transition: all 0.3s ease;
            }

            .stButton>button:hover {
                background: linear-gradient(135deg, rgba(98, 120.20, 246, 0.30) 0%, rgba(29, 48, 78, 0) 100%), #1A8BB0 !important;
                box-shadow: 0px 6px 14px rgba(26, 26, 26, 0.15);
                transform: translateY(-2px);
            }
            
            /* Mobile responsive styles */
            @media (max-width: 600px) {
                 div.block-container {
                    padding: 1rem 1.2rem 1.5rem 1.2rem !important;
                }
            }
        </style>
    """,
        unsafe_allow_html=True,
    )


def display_and_save_card(plan):
    """Displays the generated plan as a card and adds an image save button."""

    # Convert **text** from the AI response to a <span> tag
    highlighted_outcome = re.sub(
        r"\*\*(.*?)\*\*", r"<span>\1</span>", plan["outcome_goal"]
    )
    highlighted_process = re.sub(
        r"\*\*(.*?)\*\*", r"<span>\1</span>", plan["process_goal"]
    )

    # Include styles directly within the HTML component to resolve iframe issues
    card_html = f"""
    <style>
        /* Copy only the necessary styles for this component */
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans:wght@400;500;700&display=swap');
        :root {{
            --primary-color: #2BA7D1;
            --black-color: #0D1628;
            --secondary-color: #86929A;
            --gray-color: #898D99;
            --divider-color: #F1F1F1;
        }}
        body {{
            font-family: 'Noto Sans', sans-serif;
            margin: 0;
            background-color: #f0f2f5;
        }}
        .card-container {{
            background-color: white;
            padding: 2rem;
            border-radius: 32px;
        }}
        .section {{
            border-bottom: 1px solid var(--divider-color);
            padding-bottom: 20px;
            margin-bottom: 20px;
        }}
        .last-section {{
            border-bottom: none;
            margin-bottom: 0;
            padding-bottom: 0;
        }}
        .section-header {{
            font-size: 14px;
            font-weight: 700;
            color: var(--gray-color);
            margin-bottom: 4px;
        }}
        .section-title {{
            font-size: 18px;
            font-weight: 700;
            color: var(--black-color);
            line-height: 28px;
            margin-bottom: 12px;
        }}
        .goal-text {{
            font-size: 18px;
            font-weight: 700;
            color: var(--black-color);
            line-height: 28px;
        }}
        .goal-text span {{
            color: var(--primary-color);
        }}
        .explanation-text {{
            font-size: 13px;
            color: var(--secondary-color);
            line-height: 20px;
            margin-top: 12px;
        }}
        #save-btn {{
            width: 100%;
            padding: 14px;
            margin-top: 1rem;
            font-size: 14px;
            font-weight: 400;
            color: white;
            background-color: #2BA7D1;
            border: none;
            border-radius: 12px;
            cursor: pointer;
            text-align: center;
            box-shadow: 0px 5px 10px rgba(26, 26, 26, 0.10);
        }}
    </style>

    <div id="refocus-plan-card" class="card-container">
        <div class="section">
            <p class="section-header">When</p>
            <p class="section-title">In what situation<br>do you need to refocus?</p>
            <p class="explanation-text">{plan["when_summary"]}</p>
        </div>

        <div class="section">
            <p class="section-header">Outcome Goal</p>
            <p class="goal-text">"{highlighted_outcome}"</p>
            <p class="explanation-text">{plan["outcome_explanation"]}</p>
        </div>

        <div class="section last-section">
            <p class="section-header">Process Goal</p>
            <p class="goal-text">"{highlighted_process}"</p>
            <p class="explanation-text">{plan["process_explanation"]}</p>
        </div>
    </div>
    
    <button id="save-btn">Save Card as Image</button>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js"></script>
    <script>
    document.getElementById("save-btn").onclick = function() {{
        const cardElement = document.getElementById("refocus-plan-card");
        const saveButton = this;
        
        saveButton.innerHTML = "Saving...";
        saveButton.disabled = true;

        html2canvas(cardElement, {{
            useCORS: true,
            scale: 2,
            backgroundColor: 'white'
        }}).then(canvas => {{
            const image = canvas.toDataURL("image/png");
            const link = document.createElement("a");
            link.href = image;
            link.download = "refocus-plan-card.png";
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            saveButton.innerHTML = "Save Card as Image";
            saveButton.disabled = false;
        }});
    }}
    </script>
    """
    st.components.v1.html(card_html, height=850, scrolling=True)


# --- Main Application Logic ---
def main():
    st.set_page_config(page_title="Refocusing Card Generator", layout="centered")
    apply_ui_styles()

    if "generated_plan" not in st.session_state:
        st.session_state.generated_plan = None

    icon_path = Path(__file__).parent / "icon.png"
    icon_base64 = img_to_base64(icon_path)

    if icon_base64:
        st.markdown(
            f"""
            <div class="icon-container">
                <img src="data:image/png;base64,{icon_base64}" alt="icon">
            </div>
        """,
            unsafe_allow_html=True,
        )
    st.markdown('<p class="title">Refocusing Card</p>', unsafe_allow_html=True)
    st.markdown(
        '<p class="subtitle">Your personal refocusing card is a training tool<br>you can use to regain lost concentration.</p>',
        unsafe_allow_html=True,
    )

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
             st.error("'GEMINI_API_KEY' is not set in your environment or Streamlit Secrets.")
             st.stop()
    except Exception:
        st.error("'GEMINI_API_KEY' is not set in your environment or Streamlit Secrets.")
        st.stop()

    with st.container():
        st.markdown('<div class="section">', unsafe_allow_html=True)
        st.markdown('<p class="section-header">When</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="section-title">In what situation<br>do you need to refocus?</p>',
            unsafe_allow_html=True,
        )
        situation = st.text_area(
            "situation_input",
            height=120,
            placeholder="In a tense, one-point game, I get anxious about 'what if I mess up' and can't concentrate properly...",
            label_visibility="collapsed",
        )
        st.markdown("</div>", unsafe_allow_html=True)

    if st.button("Create My Refocusing Plan", use_container_width=True):
        if not situation.strip():
            st.warning("Please enter a situation where refocusing is needed.")
            st.session_state.generated_plan = None
        else:
            with st.spinner("The AI is creating a personalized refocusing card for you..."):
                result_text = get_refocus_plan_from_gemini(api_key, situation)
                try:
                    if result_text.startswith("Error:") or result_text.startswith(
                        "An error occurred"
                    ):
                        raise ValueError(result_text)

                    # NOTE: These split keys must match the ones in the prompt
                    when_summary = (
                        result_text.split("[Situation Summary]")[1]
                        .split("[Outcome Goal]")[0]
                        .strip()
                    )
                    outcome_goal = (
                        result_text.split("[Outcome Goal]")[1]
                        .split("[Outcome Goal Explanation]")[0]
                        .strip()
                    )
                    outcome_explanation = (
                        result_text.split("[Outcome Goal Explanation]")[1]
                        .split("[Process Goal]")[0]
                        .strip()
                    )
                    process_goal = (
                        result_text.split("[Process Goal]")[1]
                        .split("[Process Goal Explanation]")[0]
                        .strip()
                    )
                    process_explanation = result_text.split("[Process Goal Explanation]")[
                        1
                    ].strip()

                    st.session_state.generated_plan = {
                        "when_summary": when_summary,
                        "outcome_goal": outcome_goal,
                        "outcome_explanation": outcome_explanation,
                        "process_goal": process_goal,
                        "process_explanation": process_explanation,
                    }
                except (IndexError, ValueError) as e:
                    st.error(f"An error occurred while processing the results: {e}")
                    st.session_state.generated_plan = None

    if st.session_state.generated_plan:
        display_and_save_card(st.session_state.generated_plan)


if __name__ == "__main__":
    main()
