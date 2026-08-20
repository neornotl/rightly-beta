var fs = require('fs');
var path = 'webhook_server.py';
var s = fs.readFileSync(path, 'utf8');

var oldStr = "            result = get_pipeline().process_text(\r\n                body.session_id, body.text.strip(), progress_callback=on_progress\r\n            )\r\n            answer = result.answer\r\n            events.put({\r\n                \"type\": \"answer\",\r\n                \"reply\": answer.answer_text if answer else result.decision.user_message,\r\n                \"sources\": list(answer.source_ids) if answer else [],\r\n                \"decision\": result.decision.zone.value,\r\n                \"summary\": answer.summary if answer else \"\",\r\n                \"appropriate\": answer.appropriate if answer else None,\r\n            })";
var newStr = "            result = get_pipeline().process_text(\r\n                body.session_id, body.text.strip(), progress_callback=on_progress\r\n            )\r\n            answer = result.answer\r\n            reply_text = answer.answer_text if answer else result.decision.user_message\r\n            events.put({\r\n                \"type\": \"answer\",\r\n                \"reply\": reply_text,\r\n                \"sources\": list(answer.source_ids) if answer else [],\r\n                \"decision\": result.decision.zone.value,\r\n                \"summary\": answer.summary if answer else \"\",\r\n                \"appropriate\": answer.appropriate if answer else None,\r\n                \"lang\": _detect_lang(reply_text, body.lang),\r\n            })";

var idx = s.indexOf(oldStr);
if (idx === -1) { console.error('Anchor not found'); process.exit(1); }
s = s.substring(0, idx) + newStr + s.substring(idx + oldStr.length);

// Also add _detect_lang helper near top of file
var helper = "\r\n\r\ndef _detect_lang(text: str, hint: str | None) -> str:\r\n    \"\"\"Pick the reply language. Hint from client wins; else detect.\"\"\"\r\n    if hint and hint.lower() in (\"vi\", \"en\"):\r\n        return hint.lower()\r\n    if not text:\r\n        return \"vi\"\r\n    try:\r\n        import re\r\n        if re.search(r\"[\u0103\u00e2\u0111\u00ea\u00f4\u01a1\u01b0\u0103\u00c2\u0110\u00ca\u00d4\u01a0\u01af\u00e1\u00e0\u1ea3\u00e3\u1ea1\u1eb1\u1ea7\u1ead\u1eb3\u1ebf\u1eb5\u1ebd\u1ec1\u00e9\u00e8\u1ebb\u1eb9\u1eb7\u1ec7\u1ec3\u1ec5\u00ed\u00ec\u1ec9\u1ecb\u1ea9\u1ecd\u00f3\u00f2\u1ecf\u00f5\u1ecd\u1ed1\u1ed9\u1edb\u1edf\u1ee3\u1edd\u1ee1\u1ee9\u00fa\u00f9\u1ee7\u1ee5\u1ef1\u1eef\u1eed\u1ef3\u1ef9\u00fd\u1ef3\u1ef7\u1ef5\u1efd]\", text):\r\n            return \"vi\"\r\n        letters = sum(1 for c in text if c.isascii() and c.isalpha())\r\n        return \"en\" if letters >= 4 else \"vi\"\r\n    except Exception:\r\n        return \"vi\"";

var insertAfter = "import logging";
var idx2 = s.indexOf(insertAfter);
if (idx2 !== -1) {
  s = s.substring(0, idx2 + insertAfter.length) + helper + s.substring(idx2 + insertAfter.length);
}

fs.writeFileSync(path, s);
console.log('OK, size:', s.length);
