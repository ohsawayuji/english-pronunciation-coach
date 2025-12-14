import streamlit as st
import azure.cognitiveservices.speech as speechsdk
import os
import time
import uuid

# --- ページ設定とメニュー非表示CSS ---
st.set_page_config(page_title="AI英語発音コーチ", page_icon="🗣️")

hide_streamlit_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
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
    audio_config = speechsdk.audio.AudioConfig(filename=audio_file_path)

    pronunciation_config = speechsdk.PronunciationAssessmentConfig(
        reference_text=reference_text,
        grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
        granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme
    )
    pronunciation_config.enable_miscue = True

    recognizer = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config)
    pronunciation_config.apply_to(recognizer)

    result = recognizer.recognize_once_async().get()
    
    if result.reason == speechsdk.ResultReason.RecognizedSpeech:
        pronunciation_result = speechsdk.PronunciationAssessmentResult(result)
        return pronunciation_result, result
    else:
        return None, None

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
        score_result, raw_result = assess_pronunciation(input_filename, target_text)

    if score_result:
        words = speechsdk.PronunciationAssessmentResult(raw_result).words
        total_words = 0
        green_count = 0
        weak_words = []
        word_details = []
        
        # ★追加：実際に認識された単語リストを作成するための変数
        recognized_words_list = []

        for word in words:
            error_type_str = str(word.error_type)
            
            # --- 1. 実際に認識された文章を作るロジック ---
            # 「読み飛ばし(Omission)」以外は、発声された言葉なのでリストに追加
            if "Omission" not in error_type_str:
                recognized_words_list.append(word.word)
            
            # --- 2. 採点ロジック ---
            if word.error_type != "Insertion":
                total_words += 1
                
                if "Omission" in error_type_str:
                    color = "gray"
                    weak_words.append(word.word)
                    display_score = "-"
                elif word.accuracy_score >= 85:
                    color = "green"
                    green_count += 1
                    display_score = f"{word.accuracy_score:.0f}"
                elif word.accuracy_score >= 75:
                    color = "#FFC107"
                    weak_words.append(word.word)
                    display_score = f"{word.accuracy_score:.0f}"
                else:
                    color = "red"
                    weak_words.append(word.word)
                    display_score = f"{word.accuracy_score:.0f}"
                
                word_details.append({
                    "word": word.word,
                    "score": display_score,
                    "color": color,
                    "error": error_type_str
                })
        
        # 認識された文章を結合
        recognized_sentence = " ".join(recognized_words_list)

        if total_words > 0:
            green_ratio = (green_count / total_words) * 100
        else:
            green_ratio = 0

        # --- 結果表示エリア ---
        
        # 合否メッセージ
        if green_ratio >= 85:
            st.balloons()
            st.success(f"🎉 Excellent! 合格です！ (緑率: {green_ratio:.1f}%)")
        elif green_ratio >= 75:
            st.warning(f"⚠️ Good! 仮合格です。あと少し！ (緑率: {green_ratio:.1f}%)")
        else:
            st.error(f"❌ Try Again. 緑を増やしましょう。 (緑率: {green_ratio:.1f}%)")

        # 3つの指標
        acc = score_result.accuracy_score if score_result.accuracy_score else 0
        flu = score_result.fluency_score if score_result.fluency_score else 0
        com = score_result.completeness_score if score_result.completeness_score else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Accuracy (正確さ)", f"{acc:.0f}")
        c2.metric("Fluency (流暢さ)", f"{flu:.0f}")
        c3.metric("Completeness (完全性)", f"{com:.0f}")

        st.divider()

        # --- ★ここが新機能：AIが聞き取った内容の表示 ---
        st.subheader("📝 詳細レポート")
        
        st.markdown("##### 👂 AIが聞き取った内容")
        if recognized_sentence.strip() == "":
            st.info("（何も聞き取れませんでした）")
        else:
            st.info(f"「 {recognized_sentence} 」")
            st.caption("※ 読み飛ばした単語はここに含まれず、余計に読んだ単語はここに含まれます。")

        st.markdown("##### 📊 採点と添削")
        feedback_html = "<div style='line-height: 2.0;'>"
        for item in word_details:
            if "Omission" in item["error"]:
                feedback_html += f"<span style='color:#b0b0b0; text-decoration:line-through; font-size:24px; margin-right:8px;'>{item['word']}</span> "
            else:
                feedback_html += f"<span style='color:{item['color']}; font-size:24px; font-weight:bold; margin-right:8px;' title='{item['score']}点'>{item['word']}</span> "
        
        for word in words:
            if word.error_type == "Insertion":
                 feedback_html += f"<span style='color:purple; font-style:italic; font-size:18px;'>({word.word}?)</span> "
        
        feedback_html += "</div>"

        st.markdown(feedback_html, unsafe_allow_html=True)
        st.caption("凡例: 🟢完璧  🟡惜しい  🔴発音NG  🔘読み飛ばし  (🟣余計な単語)")

        st.divider()

        # --- 🔥 弱点特訓コーナー ---
        if len(weak_words) > 0:
            st.subheader("🔥 弱点特訓コーナー")
            st.write("赤・黄・グレー（読み飛ばし）の単語を練習しましょう。")

            unique_weak_words = list(dict.fromkeys(weak_words))
            selected_word = st.selectbox("練習する単語を選択:", unique_weak_words)

            col_a, col_b = st.columns(2)
            
            with col_a:
                st.markdown("##### 👂 ① お手本")
                if st.button(f"Play: {selected_word}"):
                    tts_single = get_filename("single_word_tts")
                    generate_tts(selected_word, tts_single)
                    st.audio(tts_single)
            
            with col_b:
                st.markdown("##### 🎤 ② 録音")
                practice_audio = st.audio_input(f"Record: {selected_word}", key="practice_rec")
                
                if practice_audio:
                    practice_file = get_filename("practice")
                    with open(practice_file, "wb") as f:
                        f.write(practice_audio.getbuffer())
                    
                    p_score, p_raw = assess_pronunciation(practice_file, selected_word)
                    
                    if p_score:
                        single_score = p_score.accuracy_score
                        if single_score >= 85:
                            st.success(f"🎉 {single_score:.0f}点 (Excellent!)")
                        elif single_score >= 75:
                            st.warning(f"🟡 {single_score:.0f}点 (Good)")
                        else:
                            st.error(f"🔴 {single_score:.0f}点 (Try again)")
        else:
            st.success("弱点単語はありません！")

    else:
        st.error("音声を認識できませんでした。")

