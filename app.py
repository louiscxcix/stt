import streamlit as st
import google.generativeai as genai
import speech_recognition as sr
from streamlit_mic_recorder import mic_recorder

# --- 페이지 설정 및 제목 ---
st.set_page_config(page_title="음성 비서 App", page_icon="🎙️")
st.title("💡 AI 음성 인식 및 교정 앱")
st.write("""
이 앱은 당신의 말을 텍스트로 변환하고, Gemini AI를 이용해 문맥에 맞게 다듬어 줍니다.
'녹음 시작' 버튼을 누르고 말씀하신 후, '녹음 중지' 버튼을 눌러주세요.
""")

# --- Gemini API 키 설정 (Streamlit Secrets 사용) ---
try:
    # st.secrets에 저장된 API 키를 불러옵니다.
    genai.configure(api_key=st.secrets["GEMINI_API_KEY"])
    model = genai.GenerativeModel('gemini-pro')
except (KeyError, AttributeError):
    st.error("오류: Gemini API 키가 설정되지 않았습니다.")
    st.info("앱을 배포할 때 Streamlit 설정의 'Secrets' 부분에 API 키를 추가해야 합니다.")
    st.stop() # API 키가 없으면 앱 실행 중지

# --- 음성 녹음 및 처리 ---
st.subheader("음성 입력")

# 마이크 녹음 세션 시작
audio_bytes = mic_recorder(
    start_prompt="🔴 녹음 시작",
    stop_prompt="⏹️ 녹음 중지",
    just_once=True,
    key='my_mic_recorder'
)

if audio_bytes:
    st.success("음성 녹음 완료!")
    
    r = sr.Recognizer()
    audio_data = sr.AudioData(audio_bytes['bytes'], audio_bytes['sample_rate'], 2)

    st.divider()

    # --- STT 및 Gemini 처리 ---
    try:
        with st.spinner('음성을 텍스트로 변환하는 중...'):
            stt_text = r.recognize_google(audio_data, language='ko-KR')

        with st.spinner('Gemini가 문장을 다듬는 중...'):
            prompt = f"""
            다음은 음성 인식을 통해 생성된 텍스트입니다.
            오타가 있거나 문맥이 어색할 수 있습니다.
            자연스러운 한국어 문장으로 수정하고 다듬어 주세요.

            원본 텍스트: "{stt_text}"
            수정된 텍스트:
            """
            response = model.generate_content(prompt)
            corrected_text = response.text.strip()
        
        # --- 결과 출력 ---
        st.subheader("처리 결과")
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("##### 🗣️ 음성 인식 원본")
            st.text_area("STT", stt_text, height=150)

        with col2:
            st.markdown("##### ✨ Gemini 수정본")
            st.text_area("Gemini", corrected_text, height=150)

    except sr.UnknownValueError:
        st.error("음성을 인식할 수 없습니다. 더 명확하게 말씀해주세요.")
    except sr.RequestError as e:
        st.error(f"Google 음성 인식 서비스에 접근할 수 없습니다: {e}")
    except Exception as e:
        st.error(f"오류가 발생했습니다: {e}")