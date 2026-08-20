const fs=require('fs');
const path='web/index.html';
let s=fs.readFileSync(path,'utf8');
const oldLines = [
  '      <div class="spacer</div>',
  '      <nav class="modes" id="modeSwitch">',
  '        <button class="mode active" id="modeChat" type="button">💬 Chat</button>',
  '        <button class="mode" id="modeCall" type="button">📞 Cuộc gọi</button>',
  '     </nav>',
  '      <div class="status" id="status">sẵn sàng</div>'
];
const newLines = [
  '      <div class="spacer</div>',
  '      <div class="lang-switch" id="langSwitch" role="group" aria-label="Ngôn ngữ">',
  '        <span class="flag" aria-hidden="true">🌐</span>',
  '        <button class="lang-btn active" data-lang="auto" type="button" title="Tự động theo ngôn ngữ câu hỏi">Auto</button>',
  '        <button class="lang-btn" data-lang="vi" type="button" title="Tiếng Việt">VI</button>',
  '        <button class="lang-btn" data-lang="en" type="button" title="English">EN</button>',
  '     </div>',
  '      <nav class="modes" id="modeSwitch">',
  '        <button class="mode active" id="modeChat" type="button">💬 Chat</button>',
  '        <button class="mode" id="modeCall" type="button">📞 Cuộc gọi</button>',
  '     </nav>',
  '      <div class="status" id="status">sẵn sàng</div>'
];
const oldStr = oldLines.join('\n');
const newStr = newLines.join('\n');
if(!s.includes(oldStr)){console.error('NOT FOUND');process.exit(1);}
s=s.replace(oldStr,newStr);
fs.writeFileSync(path,s);
console.log('OK');
