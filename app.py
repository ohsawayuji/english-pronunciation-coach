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

    # enable_miscue=True が重要（言い間違い・飛ばし・挿入を検知）
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
        
        # 変数初期化
        total_words_for_score = 0
        green_count = 0
        weak_words = []      # 練習用リスト
        
        # 表示用データ
        feedback_html_parts = []     # 詳細レポート（色付き）用
        heard_words_list = []        # 「聞こえた音」再現用

        # --- 判定ループ ---
        for word in words:
            error_type = word.error_type
            
            # --- A. 「聞こえた音」リストの作成 ---
            # Omission（読み飛ばし）以外は、口から発せられた音なのでリストに入れる
            if error_type != speechsdk.PronunciationAssessmentErrorType.Omission:
                heard_words_list.append(word.word)

            # --- B. 採点と色分け ---
            
            # 1. 挿入誤り（Insertion）: 余計な単語
            if error_type == speechsdk.PronunciationAssessmentErrorType.Insertion:
                # 採点の分母には含めないが、表示は紫にする
                feedback_html_parts.append(
                    f"<span style='color:purple; font-style:italic; font-size:18px;'>({word.word})</span>"
                )
                # 挿入された語も練習候補に入れたければここに追加（今回は除外）
            
            # 2. 読み飛ばし（Omission）: 言わなかった単語
            elif error_type == speechsdk.PronunciationAssessmentErrorType.Omission:
                total_words_for_score += 1
                weak_words.append(word.word)
                feedback_html_parts.append(
                    f"<span style='color:#b0b0b0; text-decoration:line-through; font-size:24px; margin-right:5px;'>{word.word}</span>"
                )

            # 3. その他の通常判定（None, Mispronunciation）
            else:
                total_words_for_score += 1
                
                # スコアによる色分け
                if word.accuracy_score >= 85:
                    color = "green"
                    green_count += 1
                elif word.accuracy_score >= 75:
                    color = "#FFC107" # 黄色
                    weak_words.append(word.word)
                else:
                    color = "red"
                    weak_words.append(word.word)
                
                feedback_html_parts.append(
                    f"<span style='color:{color}; font-size:24px; font-weight:bold; margin-right:5px;' title='{word.accuracy_score:.0f}点'>{word.word}</span>"
                )

        # --- 集計 ---
        recognized_sentence = " ".join(heard_words_list) # リストを文字列に変換
        
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

        acc = score_result.accuracy_score if score_result.accuracy_score else 0
        flu = score_result.fluency_score if score_result.fluency_score else 0
        com = score_result.completeness_score if score_result.completeness_score else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Accuracy (正確さ)", f"{acc:.0f}")
        c2.metric("Fluency (流暢さ)", f"{flu:.0f}")
        c3.metric("Completeness (完全性)", f"{com:.0f}")

        st.divider()

        # --- 📝 詳細レポート ---
        st.subheader("📝 詳細レポート")
        
        # 👂 実際に聞こえた文章
        st.markdown("##### 👂 AIが聞き取った内容")
        if not recognized_sentence:
             st.info("（音声が検出されませんでした）")
        else:
             # ここに「soccer soccer」や「soccer game」などがそのまま表示されます
             st.info(f"「 {recognized_sentence} 」")

        # 📊 添削結果
        st.markdown("##### 📊 添削結果")
        feedback_html = "<div style='line-height: 2.0;'>" + " ".join(feedback_html_parts) + "</div>"
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

