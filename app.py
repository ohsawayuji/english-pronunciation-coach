import streamlit as st
import azure.cognitiveservices.speech as speechsdk
import os
import time
import uuid
import json

# --- ページ設定とメニュー非表示CSS ---
st.set_page_config(page_title="AI英語発音コーチ", page_icon="🗣️")

hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            
            /* 添削結果を見やすくするためのCSS */
            .correction-box {
                font-family: sans-serif;
                line-height: 2.2;
                font-size: 22px;
                background-color: #f9f9f9;
                padding: 20px;
                border-radius: 10px;
                border: 1px solid #ddd;
            }
            .word-green { color: #28a745; font-weight: bold; margin-right: 6px; }
            .word-yellow { color: #d39e00; font-weight: bold; margin-right: 6px; }
            .word-red { color: #dc3545; font-weight: bold; margin-right: 6px; }
            .word-omission { color: #b0b0b0; text-decoration: line-through; margin-right: 6px; }
            .word-insertion { color: #6f42c1; font-style: italic; font-weight: bold; margin-left: 2px; margin-right: 8px; }
            </style>
            """
st.markdown(hide_streamlit_style, unsafe_allow_html=True)

# --- 設定 ---
try:
    SPEECH_KEY = st.secrets["SPEECH_KEY"]
    SPEECH_REGION = st.secrets["SPEECH_REGION"]
except:
    st.error("設定エラー: APIキーが設定されていません。")

# --- セッション管理 ---
if 'user_id' not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())

def get_filename(base_name):
    return f"{base_name}_{st.session_state.user_id}.wav"

def get_speech_synthesizer():
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = "en-US-JennyNeural" 
    return speech_config

def assess_pronunciation(audio_file_path, reference_text):
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_recognition_language = "en-US" 
    
    # 1. 採点用（正解文と比較）
    audio_config_score = speechsdk.audio.AudioConfig(filename=audio_file_path)
    pronunciation_config = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference_text,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme
    )
    pronunciation_config.enable_miscue = True 

    recognizer_score = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config_score)
    pronunciation_config.apply_to(recognizer_score)
    
    result_score = recognizer_score.recognize_once_async().get()

    # 2. 聞き取り用（正解文無視）
    audio_config_raw = speechsdk.audio.AudioConfig(filename=audio_file_path)
    recognizer_raw = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config_raw)
    result_raw = recognizer_raw.recognize_once_async().get()

    json_result_str = result_score.json
    raw_transcription = result_raw.text if result_raw.reason == speechsdk.ResultReason.RecognizedSpeech else ""

    return json_result_str, raw_transcription, result_score

def generate_tts(text, filename):
    speech_config = get_speech_synthesizer()
    audio_config = speechsdk.audio.AudioConfig(filename=filename)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synthesizer.speak_text_async(text).get()
    return result

# --- 画面（UI）の構築 ---
st.title("🗣️ AI英語発音コーチ")
st.info("この画面での操作は、他の人には影響しません。安心して練習してください。")

# 1. 課題文の入力
if 'target_text' not in st.session_state:
    st.session_state.target_text = "I like playing soccer with my friends."

target_text = st.text_area("読む英文を入力:", st.session_state.target_text, key="input_text")

# --- ステップ1：お手本再生 ---
st.markdown("##### ステップ1：お手本を確認する")
if st.button("🔊 お手本を聞く (Play Model Audio)"):
    with st.spinner("音声を生成中..."):
        tts_file = get_filename("model_reference")
        generate_tts(target_text, tts_file)
        st.audio(tts_file, format="audio/wav")

st.divider()

# --- ステップ2：録音 ---
st.markdown("##### ステップ2：録音して採点")
audio_value = st.audio_input("録音ボタンを押して全文を読む")

if audio_value:
    input_filename = get_filename("temp_input")
    
    with open(input_filename, "wb") as f:
        f.write(audio_value.getbuffer())

    with st.spinner("AIが分析中..."):
        json_str, raw_text_heard, result_obj = assess_pronunciation(input_filename, target_text)

    if result_obj.reason == speechsdk.ResultReason.RecognizedSpeech:
        data = json.loads(json_str)
        
        # NBestのチェック
        if 'NBest' in data and len(data['NBest']) > 0:
            nbest = data['NBest'][0]
            words_data = nbest.get('Words', [])
            
            # 全体スコア取得
            pron_scores = nbest.get('PronunciationAssessment', {})
            acc = pron_scores.get('AccuracyScore', 0)
            flu = pron_scores.get('FluencyScore', 0)
            com = pron_scores.get('CompletenessScore', 0)

            total_words_for_score = 0
            green_count = 0
            weak_words = []
            feedback_html_parts = []

            # --- JSONデータから単語ループ解析 ---
            for word_info in words_data:
                word_text = word_info.get('Word', '')
                
                # ★修正ポイント：PronunciationAssessmentオブジェクトの中から値を取得する
                pron_acc = word_info.get('PronunciationAssessment', {})
                
                # ErrorTypeを取得 (デフォルトはNone)
                error_type = pron_acc.get('ErrorType', 'None')
                
                # AccuracyScoreを取得 (デフォルトは0)
                accuracy = pron_acc.get('AccuracyScore', 0)

                # --- ケース1: 余計な単語 (Insertion) ---
                if error_type == "Insertion":
                    feedback_html_parts.append(
                        f"<span class='word-insertion'>({word_text})</span>"
                    )
                
                # --- ケース2: 読み飛ばし (Omission) ---
                elif error_type == "Omission":
                    total_words_for_score += 1
                    weak_words.append(word_text)
                    feedback_html_parts.append(
                        f"<span class='word-omission'>{word_text}</span>"
                    )

                # --- ケース3: 通常 or 発音ミス (None, Mispronunciation) ---
                else:
                    total_words_for_score += 1
                    
                    if accuracy >= 85:
                        css_class = "word-green"
                        green_count += 1
                    elif accuracy >= 75:
                        css_class = "word-yellow"
                        weak_words.append(word_text)
                    else:
                        css_class = "word-red"
                        weak_words.append(word_text)
                    
                    feedback_html_parts.append(
                        f"<span class='{css_class}' title='{accuracy}点'>{word_text}</span>"
                    )

            # --- 集計 ---
            if total_words_for_score > 0:
                green_ratio = (green_count / total_words_for_score) * 100
            else:
                green_ratio = 0

            # --- 結果表示 ---
            if green_ratio >= 85:
                st.balloons()
                st.success(f"🎉 Excellent! 合格です！ (緑率: {green_ratio:.1f}%)")
            elif green_ratio >= 75:
                st.warning(f"⚠️ Good! 仮合格です。あと少し！ (緑率: {green_ratio:.1f}%)")
            else:
                st.error(f"❌ Try Again. 緑を増やしましょう。 (緑率: {green_ratio:.1f}%)")

            c1, c2, c3 = st.
