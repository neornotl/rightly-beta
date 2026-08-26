from pathlib import Path
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "web" / "index.html"


def test_auto_language_handles_diacritic_free_vietnamese_transcript():
    source = HTML.read_text(encoding="utf-8")
    start = source.index("function detectLang(text){")
    end = source.index("function pickVoice(lang){", start)
    fn = source[start:end]
    script = fn + "\nconsole.log(JSON.stringify([detectLang('quy dinh khi vuot den do'), detectLang('câu hỏi có dấu'), detectLang('What do I need to do?'), detectLang('May I ask a question?'), detectLang('what is the legal process'), detectLang('hello')]));"
    result = subprocess.run(["node", "-e", script], cwd=ROOT, text=True, capture_output=True, check=True)
    assert json.loads(result.stdout) == ["vi", "vi", "en", "en", "en", "vi"]


def test_voice_has_single_generation_and_abort_guards():
    source = HTML.read_text(encoding="utf-8")
    for token in ("let speakSeq = 0;", "ttsAbort.abort()", "synth.cancel()", "seq !== speakSeq", "currentAudio.pause()", "earlyVoicePromise.then"):
        assert token in source
