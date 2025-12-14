import streamlit as st
import azure.cognitiveservices.speech as speechsdk
import os
import time
import uuid
import json

# --- ページ設定 ---
st.set_page_config(page_title="AI英語発音コーチ", page_icon="🗣️")

# --- CSS定義（スタイルを確実に適用） ---
st.markdown("""
<style>
    /* メニューなどを隠す */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* 添削結果ボックスのスタイル */
    .correction-box {
        font-family: "Helvetica Neue", Arial, sans-serif;
        line-height: 2.5;
        font-size: 22px;
        background-color: #f8f9fa;
        padding: 20px;
        border-radius: 12px;
        border: 2px solid #e9ecef;
        margin-bottom: 20px;
    }
    
    /* 単語ごとのスタイル */
    .word-green { 
        color: #28a745; 
        font-weight: bold; 
        margin-right: 8px; 
    }
    .word-yellow { 
        color: #d39e00; 
        font-weight: bold; 
        margin-right: 8px; 
    }
    .word-red { 
        color: #dc3545; 
        font-weight: bold; 
        margin-right: 8px; 
        text-decoration: underline;
        text-decoration-style: dotted;
    }
    .word-omission { 
        color: #adb5bd; 
        text-decoration: line-through; 
        margin-right: 8px; 
    }
    .word-insertion { 
        color: #6f42c1; 
        font-style: italic; 
        font-weight: bold; 
        margin-left: 4px; 
        margin-right: 10px; 
    }
</style>
""", unsafe_allow_html=True)

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

    # 結果処理
    if result_obj.reason == speechsdk.ResultReason.RecognizedSpeech:
        data = json.loads(json_str)
        
        # NBestのチェック
        if 'NBest' in data and len(data['NBest']) > 0:
            nbest = data['NBest'][0]
            words_data = nbest.get('Words', [])
            
            # --- スコア取得 ---
            pron_scores = nbest.get('PronunciationAssessment', {})
            acc = pron_scores.get('AccuracyScore', 0)
            flu = pron_scores.get('FluencyScore', 0)
            com = pron_scores.get('CompletenessScore', 0)

            total_words_for_score = 0
            green_count = 0
            weak_words = []
            feedback_html_parts = []

            # --- 単語ループ解析 ---
            if not words_data:
                st.warning("音声は検出されましたが、単語ごとの分解に失敗しました。もう少しゆっくり話してみてください。")
            else:
                for word_info in words_data:
                    # テキスト取得（WordがなければDisplayWord、それもなければ???）
                    word_text = word_info.get('Word') or word_info.get('DisplayWord') or "???"
                    
                    pron_acc = word_info.get('PronunciationAssessment', {})
                    error_type = pron_acc.get('ErrorType', 'None')
                    accuracy = pron_acc.get('AccuracyScore', 0)

                    # 1. 余計な単語 (Insertion)
                    if error_type == "Insertion":
                        feedback_html_parts.append(
                            f"<span class='word-insertion'>({word_text})</span>"
                        )
                    
                    # 2. 読み飛ばし (Omission)
                    elif error_type == "Omission":
                        total_words_for_score += 1
                        weak_words.append(word_text)
                        feedback_html_parts.append(
                            f"<span class='word-omission'>{word_text}</span>"
                        )

                    # 3. 通常判定
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

                # --- 合否判定と表示 ---
                if total_words_for_score > 0:
                    green_ratio = (green_count / total_words_for_score) * 100
                else:
                    green_ratio = 0

                if green_ratio >= 85:
                    st.balloons()
                    st.success(f"🎉 Excellent! 合格です！ (緑率: {green_ratio:.1f}%)")
                elif green_ratio >= 75:
                    st.warning(f"⚠️ Good! 仮合格です。あと少し！ (緑率: {green_ratio:.1f}%)")
                else:
                    st.error(f"❌ Try Again. 緑を増やしましょう。 (緑率: {green_ratio:.1f}%)")

                # メトリクス表示
                c1, c2, c3 = st.columns(3)
                c1.metric("Accuracy (正確さ)", f"{acc:.0f}")
                c2.metric("Fluency (流暢さ)", f"{flu:.0f}")
                c3.metric("Completeness (完全性)", f"{com:.0f}")

                st.divider()

                # --- 📝 詳細レポート ---
                st.subheader("📝 詳細レポート")
                
                # 聞き取り内容
                st.markdown("##### 👂 AIが聞き取った内容 (Raw Text)")
                if not raw_text_heard:
                    st.info("（音声が検出されませんでした）")
                else:
                    st.info(f"「 {raw_text_heard} 」")

                # 添削結果（ここが表示されない問題を修正）
                st.markdown("##### 📊 添削結果 (Correction)")
                
                # HTML生成
                final_html = "".join(feedback_html_parts)
                if not final_html:
                    st.warning("添削データの生成に失敗しました（データが空です）。")
                else:
                    st.markdown(f"<div class='correction-box'>{final_html}</div>", unsafe_allow_html=True)
                
                st.caption("凡例: 🟢OK  🔴NG  🔘取り消し線(読み飛ばし)  🟣カッコ(余計な単語)")

                st.divider()

                # --- 🔥 弱点特訓 ---
                if len(weak_words) > 0:
                    st.subheader("🔥 弱点特訓コーナー")
                    unique_weak_words = list(dict.fromkeys(weak_words))
                    # ???などの無効な単語を除外
                    unique_weak_words = [w for w in unique_weak_words if w != "???"]
                    
                    if unique_weak_words:
                        selected_word = st.selectbox("練習する単語を選択:", unique_weak_words)
                        col_a, col_b = st.columns(2)
                        with col_a:
                            if st.button(f"Play: {selected_word}"):
                                tts_single = get_filename("single_word_tts")
                                generate_tts(selected_word, tts_single)
                                st.audio(tts_single)
                        with col_b:
                            practice_audio = st.audio_input(f"Record: {selected_word}", key="practice_rec")
                            if practice_audio:
                                practice_file = get_filename("practice")
                                with open(practice_file, "wb") as f:
                                    f.write(practice_audio.getbuffer())
                                _, _, p_result = assess_pronunciation(practice_file, selected_word)
                                if p_result.reason == speechsdk.ResultReason.RecognizedSpeech:
                                    p_assess = speechsdk.PronunciationAssessmentResult(p_result)
                                    s_score = p_assess.accuracy_score
                                    if s_score >= 85: st.success(f"🎉 {s_score:.0f}点")
                                    elif s_score >= 75: st.warning(f"🟡 {s_score:.0f}点")
                                    else: st.error(f"🔴 {s_score:.0f}点")
                    else:
                        st.info("練習可能な単語が見つかりませんでした。")
                else:
                    st.success("弱点単語はありません！")

        else:
            st.error("データの解析に失敗しました (NBest empty)。")
            
        # --- 開発用：データ確認窓（万が一表示されない場合用） ---
        with st.expander("🛠️ 開発用データ確認（表示されない場合はここを確認）"):
            st.json(json.loads(json_str))

    elif result_obj.reason == speechsdk.ResultReason.NoMatch:
        st.error("音声を認識できませんでした。マイクに近づいて、もう一度はっきり話してみてください。")
    elif result_obj.reason == speechsdk.ResultReason.Canceled:
        st.error("処理が中断されました。APIキーの設定を確認してください。")
