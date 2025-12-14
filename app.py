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
    # これが重要：言い間違い検知をオンにする
    pronunciation_config.enable_miscue = True 

    recognizer_score = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config_score)
    pronunciation_config.apply_to(recognizer_score)
    
    # 実行
    result_score = recognizer_score.recognize_once_async().get()

    # 2. 聞き取り用（正解文無視）
    audio_config_raw = speechsdk.audio.AudioConfig(filename=audio_file_path)
    recognizer_raw = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config_raw)
    result_raw = recognizer_raw.recognize_once_async().get()

    # JSONデータを文字列として取得（これが最も確実です）
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
        # JSON文字列を受け取る
        json_str, raw_text_heard, result_obj = assess_pronunciation(input_filename, target_text)

    # JSONをパースして解析
    if result_obj.reason == speechsdk.ResultReason.RecognizedSpeech:
        data = json.loads(json_str)
        # NBestの最初の候補を使う
        words_data = data['NBest'][0]['Words']
        
        # 全体スコア取得
        pron_scores = data['NBest'][0]['PronunciationAssessment']
        acc = pron_scores.get('AccuracyScore', 0)
        flu = pron_scores.get('FluencyScore', 0)
        com = pron_scores.get('CompletenessScore', 0)

        total_words_for_score = 0
        green_count = 0
        weak_words = []
        feedback_html_parts = []

        # --- JSONデータから単語ループ解析 ---
        for word_info in words_data:
            word_text = word_info['Word']
            error_type = word_info.get('ErrorType', 'None') # Insertion, Omission, None, Mispronunciation
            accuracy = word_info.get('AccuracyScore', 0)

            # --- ケース1: 余計な単語 (Insertion) ---
            if error_type == "Insertion":
                # 紫色のカッコ書き
                feedback_html_parts.append(
                    f"<span class='word-insertion'>({word_text})</span>"
                )
            
            # --- ケース2: 読み飛ばし (Omission) ---
            elif error_type == "Omission":
                total_words_for_score += 1
                weak_words.append(word_text)
                # グレーの取り消し線
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

        c1, c2, c3 = st.columns(3)
        c1.metric("Accuracy (正確さ)", f"{acc:.0f}")
        c2.metric("Fluency (流暢さ)", f"{flu:.0f}")
        c3.metric("Completeness (完全性)", f"{com:.0f}")

        st.divider()

        # --- 📝 詳細レポート ---
        st.subheader("📝 詳細レポート")
        
        # 👂 実際に聞こえた文章
        st.markdown("##### 👂 AIが聞き取った内容 (Raw Text)")
        if not raw_text_heard:
             st.info("（音声が検出されませんでした）")
        else:
             st.info(f"「 {raw_text_heard} 」")
             st.caption("※ ここには、あなたの発音がそのまま文字になって表示されます。")

        # 📊 添削結果
        st.markdown("##### 📊 添削結果 (Correction)")
        
        feedback_html = f"<div class='correction-box'>{''.join(feedback_html_parts)}</div>"
        st.markdown(feedback_html, unsafe_allow_html=True)
        
        st.markdown("""
        <small>
        <b>凡例:</b><br>
        🟢 緑 = OK (Excellent)<br>
        🔴 赤 = 発音NG (Try again)<br>
        🔘 <span style='color:#b0b0b0; text-decoration:line-through;'>取り消し線</span> = 読み飛ばした単語 (Omission)<br>
        🟣 <span style='color:#6f42c1; font-style: italic; font-weight: bold;'>(カッコ)</span> = 余計な単語 (Insertion)<br>
        ※ <b>単語の言い間違い</b>は、「<span style='color:#b0b0b0; text-decoration:line-through;'>元の単語</span> <span style='color:#6f42c1; font-style: italic; font-weight: bold;'>(言った単語)</span>」のように並んで表示されます。<br>
        （例: I like <span style='color:#b0b0b0; text-decoration:line-through;'>playing</span> <span style='color:#6f42c1; font-style: italic; font-weight: bold;'>(praying)</span> soccer.）
        </small>
        """, unsafe_allow_html=True)

        st.divider()

        # --- 🔥 弱点特訓コーナー ---
        if len(weak_words) > 0:
            st.subheader("🔥 弱点特訓コーナー")
            st.write("不合格だった単語（赤・黄）や、読み飛ばした単語（グレー）を練習しましょう。")

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
                    
                    # 練習時は結果オブジェクトだけあればOK
                    _, _, p_result = assess_pronunciation(practice_file, selected_word)
                    
                    if p_result.reason == speechsdk.ResultReason.RecognizedSpeech:
                        # 簡易評価（練習モードはJSONパースまでしなくてOK）
                        p_assess = speechsdk.PronunciationAssessmentResult(p_result)
                        single_score = p_assess.accuracy_score
                        
                        if single_score >= 85:
                            st.success(f"🎉 {single_score:.0f}点 (Excellent!)")
                        elif single_score >= 75:
                            st.warning(f"🟡 {single_score:.0f}点 (Good)")
                        else:
                            st.error(f"🔴 {single_score:.0f}点 (Try again)")
        else:
            st.success("弱点単語はありません！")

    else:
        st.error("音声を認識できませんでした。マイクの調子を確認してください。")
