var fs = require('fs');
var path = 'web/index.html';
var s = fs.readFileSync(path, 'utf8');

var anchor = "    async function streamAnswer(text, target, onAnswer){\n      const container = target || messages;\n      const disableMic = target ? callMic : mic;\n      disableMic.disabled=true; if(!target){ input.disabled=true; send.disabled=true; send.textContent='...'; }\n      setStatus('đang xử lý');\n      const box=progressBox(container);\n      try {\n        const r=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,text})});";

var newCode = "    async function streamAnswer(text, target, onAnswer){\n      const container = target || messages;\n      const disableMic = target ? callMic : mic;\n      disableMic.disabled=true; if(!target){ input.disabled=true; send.disabled=true; send.textContent='...'; }\n      setStatus('đang xử lý');\n      const reqLang = currentLang === 'auto' ? detectLang(text) : currentLang;\n      const box=progressBox(container);\n      try {\n        const r=await fetch('/api/chat/stream',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,text,lang:reqLang})});";

var idx = s.indexOf(anchor);
if (idx === -1) {
  console.error('streamAnswer anchor not found');
  process.exit(1);
}

var newContent = s.substring(0, idx) + newCode + s.substring(idx + anchor.length);
fs.writeFileSync(path, newContent);
console.log('OK, size:', newContent.length);
