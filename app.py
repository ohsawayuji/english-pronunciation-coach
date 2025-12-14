import streamlit as st
import azure.cognitiveservices.speech as speechsdk
import os
import uuid
import json
import pandas as pd
import string

# --- ページ設定 ---
st.set_page_config(page_title="AI英語発音コーチ", page_icon="🗣️")

# --- CSS定義 ---
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
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
    
    .word-green { color: #28a745; font-weight: bold; margin-right: 5px; }
    .word-yellow { color: #d39e00; font-weight: bold; margin-right: 5px; }
    .word-red { color: #dc3545; font-weight: bold; margin-right: 5px; text-decoration: underline; text-decoration-style: dotted; }
    .word-omission { color: #adb5bd; text-decoration: line-through; margin-right: 5px; }
    
    /* 挿入（紫） - AI判定 */
    .word-insertion { color: #6f42c1; font-weight: bold; font-style: italic; margin-left: 2px; margin-right: 8px; }
    
    /* ゴースト単語（タイムスタンプで検出した無視された単語） */
    .word-ghost { 
        color: #fff; 
        background-color: #6f42c1; 
        padding: 2px 6px; 
        border-radius: 4px; 
        font-size: 0.8em;
        margin-left: 2px;
        margin-right: 8px;
        vertical-align: middle;
        font-style: italic;
    }
</style>
""", unsafe_allow_html=True)

# --- 設定 ---
try:
    SPEECH_KEY = st.secrets["SPEECH_KEY"]
    SPEECH_REGION = st.secrets["SPEECH_REGION"]
except:
    st.error("設定エラー: APIキーが設定されていません。")

if 'user_id' not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())

def get_filename(base_name):
    return f"{base_name}_{st.session_state.user_id}.wav"

def get_speech_synthesizer():
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_synthesis_voice_name = "en-US-JennyNeural" 
    return speech_config

def normalize_word(w):
    return w.lower().translate(str.maketrans('', '', string.punctuation))

def assess_pronunciation(audio_file_path, reference_text):
    speech_config = speechsdk.SpeechConfig(subscription=SPEECH_KEY, region=SPEECH_REGION)
    speech_config.speech_recognition_language = "en-US" 
    # 詳細なタイムスタンプを取得するためにDetailedフォーマットを指定
    speech_config.output_format = speechsdk.OutputFormat.Detailed
    
    # 1. 採点用 (Pronunciation Assessment)
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

    # 2. 聞き取り用 (Standard Recognition with Detailed Output)
    audio_config_raw = speechsdk.audio.AudioConfig(filename=audio_file_path)
    recognizer_raw = speechsdk.SpeechRecognizer(speech_config=speech_config, audio_config=audio_config_raw)
    result_raw = recognizer_raw.recognize_once_async().get()

    # 結果のテキスト抽出
    if result_raw.reason == speechsdk.ResultReason.RecognizedSpeech:
        raw_text_heard = result_raw.text
    else:
        raw_text_heard = ""

    return result_score.json, result_raw.json, result_score, raw_text_heard

def generate_tts(text, filename):
    speech_config = get_speech_synthesizer()
    audio_config = speechsdk.audio.AudioConfig(filename=filename)
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synthesizer.speak_text_async(text).get()
    return result

# --- UI ---
st.title("🗣️ AI英語発音コーチ")
st.info("タイムスタンプ解析により、余計な言葉を「発言した場所」に正確に表示します。")

if 'target_text' not in st.session_state:
    st.session_state.target_text = "I like playing soccer with my friends."

target_text = st.text_area("読む英文を入力:", st.session_state.target_text, key="input_text")

st.markdown("##### ステップ1：お手本を確認する")
if st.button("🔊 お手本を聞く"):
    with st.spinner("音声を生成中..."):
        tts_file = get_filename("model_reference")
        generate_tts(target_text, tts_file)
        st.audio(tts_file, format="audio/wav")

st.divider()

st.markdown("##### ステップ2：録音して採点")
audio_value = st.audio_input("録音ボタンを押して全文を読む")

if audio_value:
    input_filename = get_filename("temp_input")
    with open(input_filename, "wb") as f:
        f.write(audio_value.getbuffer())

    with st.spinner("AIが分析中..."):
        # 戻り値を変更: score_json, raw_json, result_obj, raw_text
        json_str_score, json_str_raw, result_obj, raw_text_heard = assess_pronunciation(input_filename, target_text)

    if result_obj.reason == speechsdk.ResultReason.RecognizedSpeech:
        data_score = json.loads(json_str_score)
        data_raw = json.loads(json_str_raw)
        
        # Pronunciation Assessmentの結果取得
        if 'NBest' in data_score and len(data_score['NBest']) > 0:
            nbest_score = data_score['NBest'][0]
            words_score = nbest_score.get('Words', [])
            
            pron_scores = nbest_score.get('PronunciationAssessment', {})
            acc = pron_scores.get('AccuracyScore', 0)
            flu = pron_scores.get('FluencyScore', 0)
            com = pron_scores.get('CompletenessScore', 0)
        else:
            words_score = []
            acc, flu, com = 0, 0, 0

        # Raw Recognitionの結果取得 (Detailedフォーマット)
        words_raw = []
        if 'NBest' in data_raw and len(data_raw['NBest']) > 0:
            # Detailed formatのNBest[0]にはWordsリストがあることが多い
            words_raw = data_raw['NBest'][0].get('Words', [])
        
        # --- 統合表示ロジック (Timeline Merge) ---
        
        # 全ての表示要素をこのリストに入れて、最後にOffsetでソートする
        # 要素: {'text': str, 'html': str, 'offset': int, 'type': str, 'debug_info': dict}
        display_items = []
        
        total_words_for_score = 0
        green_count = 0
        weak_words = []
        
        # 1. 採点結果（Assessment）の単語をリストに追加
        for w in words_score:
            word_text = w.get('Word') or w.get('DisplayWord') or "???"
            offset = w.get('Offset', 0)
            duration = w.get('Duration', 0)
            
            pron_acc = w.get('PronunciationAssessment', {})
            raw_error = pron_acc.get('ErrorType') or w.get('ErrorType') or 'None'
            score = pron_acc.get('AccuracyScore', 0)
            
            # 判定ロジック
            final_error = "Normal"
            html = ""
            
            if raw_error.lower() == "insertion":
                final_error = "Insertion"
                html = f"<span class='word-insertion'>({word_text})</span>"
            elif raw_error == "Omission":
                total_words_for_score += 1
                weak_words.append(word_text)
                final_error = "Omission"
                html = f"<span class='word-omission'>{word_text}</span>"
            elif raw_error == "Mispronunciation" and score <= 40:
                total_words_for_score += 1
                weak_words.append(word_text)
                final_error = "Low Score -> Omission"
                html = f"<span class='word-omission'>{word_text}</span>"
            else:
                # Normal or Scored
                total_words_for_score += 1
                if score >= 85:
                    css = "word-green"
                    final_error = "Excellent"
                    green_count += 1
                elif score >= 75:
                    css = "word-yellow"
                    final_error = "Good"
                    weak_words.append(word_text)
                else:
                    css = "word-red"
                    final_error = "Bad"
                    weak_words.append(word_text)
                html = f"<span class='{css}' title='{score}点'>{word_text}</span>"

            display_items.append({
                'text': word_text,
                'html': html,
                'offset': offset,
                'duration': duration,
                'source': 'assessment',
                'debug_raw': raw_error,
                'debug_final': final_error,
                'score': score
            })

        # 2. Raw認識（聞き取り）にあるが、採点結果の時間帯と被らない単語を「Ghost」として追加
        # (Assessmentの単語と時間的に重なっているRaw単語は「同一」とみなして無視する)
        
        for r_w in words_raw:
            r_text = r_w.get('Word') or r_w.get('DisplayWord')
            r_offset = r_w.get('Offset', 0)
            r_duration = r_w.get('Duration', 0)
            r_end = r_offset + r_duration
            
            # 重なりチェック
            is_overlapped = False
            for item in display_items:
                if item['source'] == 'assessment':
                    # 判定側単語の開始・終了
                    a_start = item['offset']
                    a_end = item['offset'] + item['duration']
                    
                    # 簡易的な衝突判定: 時間が大幅に重なっていれば同一単語とみなす
                    # (厳密には交差判定だが、ここでは中心点が相手の区間にあるかで判定)
                    r_center = r_offset + (r_duration / 2)
                    if a_start <= r_center <= a_end:
                        is_overlapped = True
                        break
            
            if not is_overlapped:
                # 重なっていない＝AIが無視した挿入語 (Ghost)
                # ただし、句読点などは除外したいが、DisplayWordには含まれることがある
                if normalize_word(r_text): 
                    display_items.append({
                        'text': r_text,
                        'html': f"<span class='word-ghost'>Ghost: {r_text}</span>",
                        'offset': r_offset, # 正しい時間の位置に配置
                        'duration': r_duration,
                        'source': 'raw_ghost',
                        'debug_raw': 'Not in JSON',
                        'debug_final': 'Ghost Insertion',
                        'score': '-'
                    })

        # 3. オフセット順にソートしてHTML生成
        display_items.sort(key=lambda x: x['offset'])
        
        final_html_parts = [item['html'] for item in display_items]
        
        # --- 結果表示計算 ---
        if total_words_for_score > 0:
            green_ratio = (green_count / total_words_for_score) * 100
        else:
            green_ratio = 0

        if green_ratio >= 85:
            st.balloons()
            st.success(f"🎉 Excellent! (緑率: {green_ratio:.1f}%)")
        elif green_ratio >= 75:
            st.warning(f"⚠️ Good! (緑率: {green_ratio:.1f}%)")
        else:
            st.error(f"❌ Try Again. (緑率: {green_ratio:.1f}%)")

        c1, c2, c3 = st.columns(3)
        c1.metric("Accuracy", f"{acc:.0f}")
        c2.metric("Fluency", f"{flu:.0f}")
        c3.metric("Completeness", f"{com:.0f}")

        st.divider()

        st.subheader("📝 詳細レポート")
        st.markdown("##### 👂 聞き取り内容")
        st.info(f"「 {raw_text_heard} 」")

        st.markdown("##### 📊 添削結果 (タイムライン同期)")
        final_html = "".join(final_html_parts)
        st.markdown(f"<div class='correction-box'>{final_html}</div>", unsafe_allow_html=True)
        st.caption("凡例: 🟢OK 🔴NG 🔘取り消し線(読み飛ばし) 🟣(Ghost: AIが無視した単語を時間位置に復元)")

        st.markdown("---")
        st.subheader("🧐 判定ロジック診断テーブル")
        
        # 診断用データ作成
        debug_data = []
        for item in display_items:
            debug_data.append({
                "順序(Offset)": item['offset'],
                "単語": item['text'],
                "ソース": item['source'],
                "判定": item['debug_final'],
                "Score": item['score']
            })
        st.dataframe(pd.DataFrame(debug_data))

        st.divider()

        # --- 弱点特訓 ---
        if len(weak_words) > 0:
            st.subheader("🔥 弱点特訓コーナー")
            unique_weak_words = [w for w in list(dict.fromkeys(weak_words)) if w != "???"]
            if unique_weak_words:
                selected_word = st.selectbox("練習する単語:", unique_weak_words)
                ca, cb = st.columns(2)
                with ca:
                    if st.button(f"Play: {selected_word}"):
                        tts_s = get_filename("single_word_tts")
                        generate_tts(selected_word, tts_s)
                        st.audio(tts_s)
                with cb:
                    pa = st.audio_input(f"Record: {selected_word}", key="p_rec")
                    if pa:
                        pf = get_filename("practice")
                        with open(pf, "wb") as f: f.write(pa.getbuffer())
                        # 練習モードでは簡易呼び出し
                        _, _, pr, _ = assess_pronunciation(pf, selected_word) 
                        if pr.reason == speechsdk.ResultReason.RecognizedSpeech:
                            s = speechsdk.PronunciationAssessmentResult(pr).accuracy_score
                            if s >= 85: st.success(f"🎉 {s:.0f}点")
                            elif s >= 75: st.warning(f"🟡 {s:.0f}点")
                            else: st.error(f"🔴 {s:.0f}点")
        else:
            st.error("解析失敗")
            
        with st.expander("🛠️ 開発用データ確認 (Raw JSON)"):
            st.write("Score JSON:")
            st.json(data_score)
            st.write("Raw Recognition JSON:")
            st.json(data_raw)

    elif result_obj.reason == speechsdk.ResultReason.NoMatch:
        st.error("音声を認識できませんでした。")
    elif result_obj.reason == speechsdk.ResultReason.Canceled:
        st.error("処理中断。APIキーを確認してください。")
