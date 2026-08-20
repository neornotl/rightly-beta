var fs = require('fs');
var path = 'api/index.py';
var s = fs.readFileSync(path, 'utf8');

// Use LF line endings
var oldStr =
'        text = str(payload.get("text", "")).strip()[:300]\n' +
'        reply = self._fallback(text)\n' +
'        if API_KEY and text:\n' +
'            try:\n' +
'                reply = self._ask_api(text)\n' +
'            except Exception:\n' +
'                reply = self._fallback(text) + " (API tạm thời không khả dụng.)"\n' +
'        if self.path.startswith("/api/chat/stream"):\n' +
'            events = [\n' +
'                {"type": "progress", "percent": 100, "detail": "Chế độ demo public"},\n' +
'                {"type": "answer", "reply": reply, "sources": [], "decision": "guide", "summary": "", "appropriate": True},\n' +
'            ]\n' +
'            body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\\n\\n" for e in events)\n' +
'            self._send(200, "text/event-stream", body)\n' +
'        elif self.path.startswith("/api/chat"):\n' +
'            self._send(200, "application/json", json.dumps({"reply": reply, "sources": []}, ensure_ascii=False))\n' +
'        else:\n' +
'            self._send(404, "application/json", \'{"detail":"Not found"}\')';

var newStr =
'        text = str(payload.get("text", "")).strip()[:300]\n' +
'        lang = str(payload.get("lang", "auto")).lower()\n' +
'        if lang not in ("vi", "en", "auto"):\n' +
'            lang = "auto"\n' +
'        reply = self._fallback(text, lang)\n' +
'        if API_KEY and text:\n' +
'            try:\n' +
'                reply = self._ask_api(text, lang)\n' +
'            except Exception:\n' +
'                reply = self._fallback(text, lang) + (" (API temporarily unavailable.)" if lang == "en" else " (API tạm thời không khả dụng.)")\n' +
'        reply_lang = lang if lang in ("vi", "en") else self._detect_lang(reply)\n' +
'        if self.path.startswith("/api/chat/stream"):\n' +
'            events = [\n' +
'                {"type": "progress", "percent": 100, "detail": "Public demo"},\n' +
'                {"type": "answer", "reply": reply, "sources": [], "decision": "guide", "summary": "", "appropriate": True, "lang": reply_lang},\n' +
'            ]\n' +
'            body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\\n\\n" for e in events)\n' +
'            self._send(200, "text/event-stream", body)\n' +
'        elif self.path.startswith("/api/chat"):\n' +
'            self._send(200, "application/json", json.dumps({"reply": reply, "sources": [], "lang": reply_lang}, ensure_ascii=False))\n' +
'        else:\n' +
'            self._send(404, "application/json", \'{"detail":"Not found"}\')';

var idx = s.indexOf(oldStr);
if (idx === -1) {
  console.error('Anchor not found');
  // Show what's there
  var idx2 = s.indexOf('payload.get');
  console.log(JSON.stringify(s.substring(idx2 - 5, idx2 + 500)));
  process.exit(1);
}
s = s.substring(0, idx) + newStr + s.substring(idx + oldStr.length);

// Update _fallback
var fbOld =
'    @staticmethod\n' +
'    def _fallback(text):\n' +
'        return (\n' +
'            "Bản web public đang ở chế độ demo an toàn. Để tra cứu đầy đủ bằng "\n' +
'            "Whisper và LLM local, hãy chạy start.bat trên máy của bạn. "\n' +
'            "Câu hỏi đã được ghi nhận: " + text\n' +
'        )';

var fbNew =
'    @staticmethod\n' +
'    def _fallback(text, lang):\n' +
'        if lang == "en":\n' +
'            return (\n' +
'                "The public demo runs in safe mode. For full Whisper + LLM local "\n' +
'                "search, run start.bat on your machine. Question received: " + text\n' +
'            )\n' +
'        return (\n' +
'            "Bản web public đang ở chế độ demo an toàn. Để tra cứu đầy đủ bằng "\n' +
'            "Whisper và LLM local, hãy chạy start.bat trên máy của bạn. "\n' +
'            "Câu hỏi đã được ghi nhận: " + text\n' +
'        )\n' +
'\n' +
'    @staticmethod\n' +
'    def _detect_lang(text):\n' +
'        if not text:\n' +
'            return "vi"\n' +
'        import re\n' +
'        if re.search(r"[ăâđêôơưáàảãạằẳẵặắấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", text):\n' +
'            return "vi"\n' +
'        letters = sum(1 for c in text if c.isascii() and c.isalpha())\n' +
'        return "en" if letters >= 4 else "vi"';

var idx2 = s.indexOf(fbOld);
if (idx2 === -1) { console.error('_fallback not found'); process.exit(1); }
s = s.substring(0, idx2) + fbNew + s.substring(idx2 + fbOld.length);

// Update _ask_api
var askOld =
'    @staticmethod\n' +
'    def _ask_api(text):\n' +
'        request = Request(\n' +
'            API_BASE_URL.rstrip("/") + "/chat/completions",\n' +
'            data=json.dumps({\n' +
'                "model": MODEL,\n' +
'                "messages": [\n' +
'                    {"role": "system", "content": "Bạn là trợ lý Rightly. Trả lời bằng tiếng Việt, ngắn gọn và hữu ích."},\n' +
'                    {"role": "user", "content": text},\n' +
'                ],\n' +
'                "temperature": 0.2,\n' +
'            }).encode("utf-8"),\n' +
'            headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"},\n' +
'            method="POST",\n' +
'        )\n' +
'        with urlopen(request, timeout=25) as response:\n' +
'            data = json.loads(response.read().decode("utf-8"))\n' +
'        content = data["choices"][0]["message"]["content"]\n' +
'        if not isinstance(content, str) or not content.strip():\n' +
'            raise ValueError("Provider returned empty content")\n' +
'        return content.strip()';

var askNew =
'    @staticmethod\n' +
'    def _ask_api(text, lang):\n' +
'        if lang == "en":\n' +
'            system_prompt = "You are Rightly, a concise and helpful Vietnamese legal/administrative assistant. Reply in English when the user writes in English."\n' +
'        else:\n' +
'            system_prompt = "Bạn là trợ lý Rightly. Trả lời bằng tiếng Việt, ngắn gọn và hữu ích."\n' +
'        request = Request(\n' +
'            API_BASE_URL.rstrip("/") + "/chat/completions",\n' +
'            data=json.dumps({\n' +
'                "model": MODEL,\n' +
'                "messages": [\n' +
'                    {"role": "system", "content": system_prompt},\n' +
'                    {"role": "user", "content": text},\n' +
'                ],\n' +
'                "temperature": 0.2,\n' +
'            }).encode("utf-8"),\n' +
'            headers={"Authorization": "Bearer " + API_KEY, "Content-Type": "application/json"},\n' +
'            method="POST",\n' +
'        )\n' +
'        with urlopen(request, timeout=25) as response:\n' +
'            data = json.loads(response.read().decode("utf-8"))\n' +
'        content = data["choices"][0]["message"]["content"]\n' +
'        if not isinstance(content, str) or not content.strip():\n' +
'            raise ValueError("Provider returned empty content")\n' +
'        return content.strip()';

var idx3 = s.indexOf(askOld);
if (idx3 === -1) { console.error('_ask_api not found'); process.exit(1); }
s = s.substring(0, idx3) + askNew + s.substring(idx3 + askOld.length);

fs.writeFileSync(path, s);
console.log('OK, size:', s.length);
