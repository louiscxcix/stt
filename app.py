import streamlit as st
import google.generativeai as genai
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder

# --- Page Setup and Title ---
st.set_page_config(page_title="AI Class Summarizer", page_icon="🎙️")
st.title("💡 AI Voice-to-Summary for Classes")
st.write("""
This app is designed to summarize lectures or classes from your speech.
1.  **Transcribes** your voice into raw text.
2.  **Corrects** the text for clarity.
3.  **Intelligently summarizes** the content, focusing on key concepts over examples.
""")

# --- Configure Gemini API Key (using Streamlit Secrets) ---
try:
    # Load the API key from st.secrets
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-pro')
except (KeyError, AttributeError):
    st.error("Error: Gemini API key is not configured.")
    st.info("To deploy this app, you must add your API key to the 'Secrets' section in Streamlit's settings.")
    st.stop() # Stop the app if the API key is missing

# --- Voice Recording and Processing ---
st.subheader("1. Voice Input")
st.write("Press 'Start Recording', deliver your class content, and then press 'Stop Recording'.")


# Start the microphone recording session
audio_bytes = mic_recorder(
    start_prompt="🔴 Start Recording",
    stop_prompt="⏹️ Stop Recording",
    just_once=True,
    key='my_mic_recorder'
)

if audio_bytes:
    st.success("Audio recording complete! Processing now...")
    
    # Initialize the speech recognizer
    r = sr.Recognizer()
    # Convert the recorded bytes to an AudioData object
    audio_data = sr.AudioData(audio_bytes['bytes'], audio_bytes['sample_rate'], 2)

    st.divider()
    st.subheader("2. Processing Results")

    # --- STT, Correction, and Summarization ---
    try:
        # Step 1: Transcribe the audio to text
        with st.spinner('Converting speech to text...'):
            stt_text = r.recognize_google(audio_data, language='en-US')

        # Step 2: Refine and correct the text using Gemini
        with st.spinner('Gemini is correcting the text...'):
            correction_prompt = f"""
            The following text was generated via speech recognition from a lecture.
            Please correct any transcription errors and clean up the formatting to make it a readable transcript.
            Ensure the original meaning is perfectly preserved.

            Original Transcript: "{stt_text}"
            Corrected Transcript:
            """
            correction_response = model.generate_content(correction_prompt)
            corrected_text = correction_response.text.strip()
        
        # Step 3: Summarize the corrected text with specific instructions
        with st.spinner('Gemini is creating an intelligent summary...'):
            # This is the updated, more detailed prompt
            summary_prompt = f"""
            You are an expert academic assistant. Your task is to summarize the following transcript from a class.
            
            Follow these instructions carefully:
            1.  **Identify Core Concepts vs. Examples:** Distinguish between fundamental concepts and illustrative examples or stories.
            2.  **Prioritize Information:**
                *   When summarizing core concepts, provide a clear and detailed explanation. Emphasize why this information is important.
                *   When you encounter an example, summarize it very briefly. For instance, state "An example of [concept] was given to illustrate..." and do not describe the full example.
            3.  **Structure the Output:** Organize the final summary with clear headings and bullet points for readability. Start with the main topic and then list the key takeaways.

            Please process the following transcript and generate a structured summary based on these rules.

            Transcript to Summarize:
            ---
            {corrected_text}
            ---

            Structured Summary:
            """
            summary_response = model.generate_content(summary_prompt)
            summary_text = summary_response.text.strip()

        # --- Display All Results ---
        st.markdown("##### ✨ Intelligent Class Summary")
        st.markdown(summary_text) # Display summary with markdown for better formatting
        
        st.markdown("---")

        with st.expander("Show Full Transcripts"):
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("##### 🗣️ Original Recognition")
                st.text_area("STT", stt_text, height=250, key="stt")

            with col2:
                st.markdown("##### 📝 Gemini-Corrected Transcript")
                st.text_area("Gemini Correction", corrected_text, height=250, key="correction")


    except sr.UnknownValueError:
        st.error("Could not understand the audio. Please speak more clearly.")
    except sr.RequestError as e:
        st.error(f"Could not request results from Google Speech Recognition service; {e}")
    except Exception as e:
        st.error(f"An error occurred during processing: {e}")
