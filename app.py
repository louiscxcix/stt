import streamlit as st
import google.generativeai as genai
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder

# --- Page Setup and Title ---
st.set_page_config(page_title="AI Class Summarizer", page_icon="🎙️")
st.title("💡 AI Voice-to-Summary for Classes")
st.write("""
This app creates intelligent study notes from your voice. It now includes an **AI-powered recovery step** to handle unclear audio.
""")

# --- Configure Gemini API Key (using Streamlit Secrets) ---
try:
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-pro')
except (KeyError, AttributeError):
    st.error("Error: Gemini API key is not configured.")
    st.info("To deploy this app, you must add your API key to the 'Secrets' section in Streamlit's settings.")
    st.stop()

# --- Initialize Session State ---
if 'corrected_text' not in st.session_state:
    st.session_state.corrected_text = None
if 'summary_text' not in st.session_state:
    st.session_state.summary_text = None
if 'raw_stt_text' not in st.session_state:
    st.session_state.raw_stt_text = None

# --- AI Recovery Function for Unclear Audio ---
def attempt_audio_recovery_with_gemini(recognizer, audio_data):
    """
    When standard STT fails, this function gets low-confidence alternatives
    and asks Gemini to reason about the most likely transcript.
    """
    st.info("Standard recognition failed. Attempting AI-powered recovery...")
    with st.spinner("AI is analyzing the unclear audio..."):
        try:
            # Get a dictionary of all possible, low-confidence transcriptions
            all_possible_transcripts = recognizer.recognize_google(audio_data, show_all=True)

            # Check if the result is valid and has alternatives
            if not isinstance(all_possible_transcripts, dict) or not all_possible_transcripts.get('alternative'):
                return None, "AI recovery failed: No possible transcriptions found in the audio."

            # Create a detailed prompt for Gemini
            recovery_prompt = f"""
            You are an expert audio analyst. A speech-to-text model failed to confidently transcribe a piece of audio.
            Below is the raw data containing a list of potential, low-confidence transcriptions.

            Your task is to analyze these alternatives and determine the most probable, coherent sentence or phrase that the user was trying to say.
            Consider the context of a class lecture. If the alternatives are complete gibberish, state that the audio is irrecoverable.

            Low-confidence data:
            ---
            {all_possible_transcripts}
            ---

            Most likely intended speech:
            """
            
            recovery_response = model.generate_content(recovery_prompt)
            recovered_text = recovery_response.text.strip()
            
            # Use the recovered text as both the "raw" and "corrected" for the next step
            return recovered_text, None
        
        except Exception as e:
            return None, f"An error occurred during AI recovery: {e}"


# --- Main App Workflow ---

# Step 1: Voice Recording
st.subheader("Step 1: Record Your Lecture Audio")
audio_bytes = mic_recorder(
    start_prompt="🔴 Start Recording",
    stop_prompt="⏹️ Stop Recording",
    just_once=True,
    key='my_mic_recorder'
)

if audio_bytes:
    # Step 2: Transcription and Correction Button
    st.subheader("Step 2: Get a Clean Transcript")
    if st.button("Transcribe and Correct Audio", use_container_width=True):
        # Reset state for a new run
        st.session_state.summary_text = None
        st.session_state.corrected_text = None
        st.session_state.raw_stt_text = None
        
        r = sr.Recognizer()
        audio_data = sr.AudioData(audio_bytes['bytes'], audio_bytes['sample_rate'], 2)

        try:
            # Primary transcription attempt
            with st.spinner('Converting speech to text...'):
                stt_text = r.recognize_google(audio_data, language='en-US')
                st.session_state.raw_stt_text = stt_text
            
            # Correction of the successful transcription
            with st.spinner('Gemini is correcting the transcript...'):
                correction_prompt = f"Please correct any errors in this lecture transcript: \"{stt_text}\""
                correction_response = model.generate_content(correction_prompt)
                st.session_state.corrected_text = correction_response.text.strip()

        except sr.UnknownValueError:
            # This is where the new recovery logic kicks in
            recovered_text, error_message = attempt_audio_recovery_with_gemini(r, audio_data)
            if recovered_text:
                st.success("AI Recovery was successful!")
                st.session_state.raw_stt_text = f"[Recovered from unclear audio]: {recovered_text}"
                st.session_state.corrected_text = recovered_text # The recovered text is already "corrected"
            else:
                st.error(f"Could not understand the audio. {error_message}")

        except sr.RequestError as e:
            st.error(f"Could not request results from Google's service; {e}")
        except Exception as e:
            st.error(f"An unknown error occurred: {e}")

# Display Transcripts and Summarization Button if transcription was successful
if st.session_state.corrected_text:
    st.divider()
    st.markdown("### Review Your Transcripts")
    
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("##### 🗣️ Original Recognition")
        st.text_area("STT", st.session_state.raw_stt_text, height=250, key="stt_display")
    with col2:
        st.markdown("##### 📝 Gemini-Corrected Transcript")
        st.text_area("Gemini Correction", st.session_state.corrected_text, height=250, key="correction_display")

    st.divider()
    
    # Step 3: Summarization Button
    st.subheader("Step 3: Generate Your Study Notes")
    if st.button("Generate Smart Summary", use_container_width=True):
        with st.spinner('Gemini is creating your intelligent study notes...'):
            try:
                summary_prompt = f"""
                You are an AI learning assistant tasked with creating personal study notes from a lecture transcript.
                Your main goal is to answer the question: "What are the key concepts I learned from this lecture?"

                Follow these critical instructions:
                1.  **Filter Content:** Your priority is to extract the core concepts taught by the main speaker (e.g., the professor). You MUST minimize or ignore parts of the transcript that are student presentations, student questions, or general class discussions. Focus only on the main lecture material.
                2.  **Explain Concepts:** For each key concept identified, provide a clear and concise explanation suitable for a study guide.
                3.  **Handle Examples:** When the lecturer uses an example, do not describe it in detail. Instead, briefly mention its purpose, such as, "An example about [topic] was used to illustrate this point."
                4.  **Format:** Structure the final output as personal study notes. Use headings and bullet points for maximum clarity.

                Analyze the following transcript and generate the study notes.

                Transcript:
                ---
                {st.session_state.corrected_text}
                ---

                My Study Notes:
                """
                summary_response = model.generate_content(summary_prompt)
                st.session_state.summary_text = summary_response.text.strip()
            
            except Exception as e:
                st.error(f"An error occurred during summarization: {e}")

# Display Final Summary if it exists
if st.session_state.summary_text:
    st.divider()
    st.markdown("### ✨ Your Intelligent Class Summary")
    st.markdown(st.session_state.summary_text)
