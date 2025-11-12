import streamlit as st
import google.generativeai as genai
import speech_recognition as sr
from streamlit_webrtc import webrtc_streamer, WebRtcMode, AudioProcessorBase
import av
import threading
import queue
import time 

# --- STUN/TURN Server Configuration ---
# This is the critical addition to solve connection issues.
WEBRTC_CONFIGURATION = {
    "iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]
}
# --- End STUN/TURN Config ---


# --- Page Setup and Title ---
st.set_page_config(page_title="AI Class Summarizer", page_icon="🎙️")
st.title("💡 AI Voice-to-Summary for Classes")
st.write("""
This app creates intelligent study notes from your voice, featuring **live transcription** as you speak.
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
if 'full_transcript' not in st.session_state:
    st.session_state.full_transcript = ""
if 'corrected_text' not in st.session_state:
    st.session_state.corrected_text = None
if 'summary_text' not in st.session_state:
    st.session_state.summary_text = None
if 'is_recording' not in st.session_state:
    st.session_state.is_recording = False

# --- Real-Time Transcription Logic ---

# Thread-safe queue to hold audio frames
audio_frames_queue = queue.Queue()
# Thread-safe string to hold the final transcript
final_transcript_container = {"text": ""}

# Function to run the speech recognition in a separate thread
def speech_recognition_thread(recognizer):
    global final_transcript_container
    
    # Clear the global container at the start of a new thread
    final_transcript_container["text"] = "" 
    
    while True:
        try:
            # Get audio data from the queue
            audio_data = audio_frames_queue.get(block=True)
            
            # If a special "stop" signal is received, break the loop
            if audio_data is None:
                break
            
            # Recognize speech using Google Web Speech API
            text = recognizer.recognize_google(audio_data, language='en-US')
            final_transcript_container["text"] += text + " "
            
        except sr.UnknownValueError:
            pass
        except sr.RequestError:
            pass
        except Exception:
            pass
        finally:
            audio_frames_queue.task_done()

# Audio processor class for streamlit-webrtc
class AudioProcessor(AudioProcessorBase):
    def __init__(self):
        self._recognizer = sr.Recognizer()
        self._recognition_thread = threading.Thread(target=speech_recognition_thread, args=(self._recognizer,))
        self._recognition_thread.daemon = True
        self._recognition_thread.start()
        st.session_state.is_recording = True

    def recv(self, frame: av.AudioFrame) -> av.AudioFrame:
        raw_samples = frame.to_ndarray()
        
        audio_data = sr.AudioData(
            raw_samples.tobytes(),
            frame.sample_rate,
            frame.layout.channels * 2
        )
        
        audio_frames_queue.put(audio_data)
        
        return frame

    def on_ended(self):
        st.session_state.is_recording = False
        time.sleep(0.5) 
        audio_frames_queue.put(None)
        self._recognition_thread.join()
        st.session_state.full_transcript = final_transcript_container["text"].strip()
        if not st.session_state.full_transcript:
             st.session_state.full_transcript = "[No recognizable speech detected or transcription error occurred.]"


# --- Main App Workflow ---

# Step 1: Live Voice Recording and Transcription
st.subheader("Step 1: Record and Transcribe Live")
st.write("Click 'START' to begin streaming your voice. The live transcript will appear below.")

# Reset session state for new recording when the component is about to start
if not st.session_state.is_recording and not st.session_state.full_transcript:
    st.session_state.full_transcript = ""
    st.session_state.corrected_text = None
    st.session_state.summary_text = None

webrtc_ctx = webrtc_streamer(
    key="live-transcription",
    mode=WebRtcMode.SENDONLY,
    audio_processor_factory=AudioProcessor,
    media_stream_constraints={"video": False, "audio": True},
    # PASS THE CONFIG HERE
    rtc_configuration=WEBRTC_CONFIGURATION, 
)

st.markdown("##### Live Transcript")
transcript_placeholder = st.empty()

# Update the placeholder with the live transcript while playing
if webrtc_ctx.state.playing:
    transcript_placeholder.text_area("Your live transcript...", value=final_transcript_container["text"], height=200)

# Display the next steps only after the streaming has stopped and we have a transcript.
if not webrtc_ctx.state.playing and st.session_state.full_transcript:
    st.divider()
    st.subheader("Step 2: Choose an Action")
    st.text_area("Final Transcript:", st.session_state.full_transcript, height=150)
    
    # Only show action buttons if the transcript is not the error message
    if not st.session_state.full_transcript.startswith("[No recognizable speech detected"):
        col1, col2 = st.columns(2)

        with col1:
            if st.button("📝 Correct Transcript", use_container_width=True):
                st.session_state.summary_text = None
                with st.spinner('Gemini is correcting the transcript...'):
                    try:
                        correction_prompt = f"Please correct any grammar or spelling errors in this lecture transcript: \"{st.session_state.full_transcript}\""
                        correction_response = model.generate_content(correction_prompt)
                        st.session_state.corrected_text = correction_response.text.strip()
                    except Exception as e:
                        st.error(f"An error occurred during correction: {e}")

        with col2:
            if st.button("✨ Generate Smart Summary", use_container_width=True):
                st.session_state.corrected_text = None
                with st.spinner('Gemini is creating your intelligent study notes...'):
                    try:
                        summary_prompt = f"""
                        You are an AI learning assistant tasked with creating personal study notes from a lecture transcript.
                        Your main goal is to answer the question: "What are the key concepts I learned from this lecture?"
                        Analyze the following transcript and generate the study notes.

                        Transcript:
                        ---
                        {st.session_state.full_transcript}
                        ---

                        My Study Notes:
                        """
                        summary_response = model.generate_content(summary_prompt)
                        st.session_state.summary_text = summary_response.text.strip()
                    except Exception as e:
                        st.error(f"An error occurred during summarization: {e}")

# Display the corrected transcript if it exists
if st.session_state.corrected_text:
    st.divider()
    st.markdown("### Corrected Transcript")
    st.text_area("Gemini-Corrected Text", st.session_state.corrected_text, height=250, key="correction_display")

# Display the final summary if it exists
if st.session_state.summary_text:
    st.divider()
    st.markdown("### Your Intelligent Class Summary")
    st.markdown(st.session_state.summary_text)
