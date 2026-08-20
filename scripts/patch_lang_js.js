var fs = require('fs');
var path = 'web/index.html';
var s = fs.readFileSync(path, 'utf8');

var anchor = "    modeChat.addEventListener('click', exitCall);\n    modeCall.addEventListener('click', enterCall);";
var idx = s.indexOf(anchor);
if (idx === -1) {
  console.error('Anchor not found');
  process.exit(1);
}

var injection = anchor + '\n\n' +
  "    let currentLang = 'auto';\n" +
  "    document.querySelectorAll('#langSwitch .lang-btn').forEach(b => {\n" +
  "      b.addEventListener('click', () => {\n" +
  "        currentLang = b.dataset.lang;\n" +
  "        document.querySelectorAll('#langSwitch .lang-btn').forEach(x => x.classList.toggle('active', x === b));\n" +
  "        try { localStorage.setItem('rightly.lang', currentLang); } catch(e){}\n" +
  "        setStatus(currentLang === 'en' ? 'English' : currentLang === 'vi' ? 'Tiếng Việt' : 'Tự động');\n" +
  "      });\n" +
  "    });\n" +
  "    try { const saved = localStorage.getItem('rightly.lang'); if (saved && ['auto','vi','en'].includes(saved)) { currentLang = saved; document.querySelectorAll('#langSwitch .lang-btn').forEach(x => x.classList.toggle('active', x.dataset.lang === saved)); } } catch(e){}";

var newContent = s.substring(0, idx) + injection + s.substring(idx + anchor.length);
fs.writeFileSync(path, newContent);
console.log('OK, new size:', newContent.length);
