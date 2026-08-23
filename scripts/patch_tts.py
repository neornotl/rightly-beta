var fs = require('fs');
var path = 'api/index.py';
var s = fs.readFileSync(path, 'utf8');

var oldStr = "        elif self.path.startswith(\"/api/chat\"):\n            self._send(200, \"application/json\", json.dumps({\"reply\": reply, \"sources\": [], \"lang\": reply_lang}, ensure_ascii=False))\n        else:\n            self._send(404, \"application/json\", '{\"detail\":\"Not found\"}')";

var newStr = "        elif self.path.startswith(\"/api/chat\"):\n            self._send(200, \"application/json\", json.dumps({\"reply\": reply, \"sources\": [], \"lang\": reply_lang}, ensure_ascii=False))\n        elif self.path.startswith(\"/api/tts\"):\n            self._tts(payload)\n        else:\n            self._send(404, \"application/json\", '{\"detail\":\"Not found\"}')\n\n    def _tts(self, payload):\n        text = str(payload.get(\"text\", \"\")).strip()[:500]\n        if not text:\n            self._send(400, \"application/json\", '{\"detail\":\"Empty text\"}')\n            return\n        lang = str(payload.get(\"lang\", \"vi\")).lower()\n        tl = \"vi\" if lang.startswith(\"vi\") else \"en\"\n        from urllib.parse import quote\n        url = \"https://translate.google.com/translate_tts?ie=UTF-8&q=\" + quote(text) + \"&tl=\" + tl + \"&client=tw-ob\"\n        req = Request(url, headers={\n            \"User-Agent\": \"Mozilla/5.0\",\n            \"Referer\": \"https://translate.google.com/\",\n        })\n        try:\n            with urlopen(req, timeout=20) as resp:\n                data = resp.read()\n        except Exception as exc:\n            self._send(502, \"application/json\", json.dumps({\"detail\": \"TTS unavailable: \" + str(exc)}))\n            return\n        self.send_response(200)\n        self.send_header(\"Content-Type\", \"audio/mpeg\")\n        self.send_header(\"Content-Length\", str(len(data)))\n        self.send_header(\"Cache-Control\", \"public, max-age=86400\")\n        self.end_headers()\n        self.wfile.write(data)";

var idx = s.indexOf(oldStr);
if (idx === -1) { console.error('Anchor not found'); process.exit(1); }
s = s.substring(0, idx) + newStr + s.substring(idx + oldStr.length);
fs.writeFileSync(path, s);
console.log('OK, size:', s.length);
