var fs = require('fs');
var path = 'webhook_server.py';
var s = fs.readFileSync(path, 'utf8');

var oldStr = "class ChatRequest(BaseModel):\r\n    session_id: str = Field(min_length=1, max_length=100)\r\n    text: str = Field(min_length=1, max_length=1000)";
var newStr = "class ChatRequest(BaseModel):\r\n    session_id: str = Field(min_length=1, max_length=100)\r\n    text: str = Field(min_length=1, max_length=1000)\r\n    lang: str | None = None";

var idx = s.indexOf(oldStr);
if (idx === -1) { console.error('ChatRequest not found'); process.exit(1); }
s = s.substring(0, idx) + newStr + s.substring(idx + oldStr.length);
fs.writeFileSync(path, s);
console.log('OK');
