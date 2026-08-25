var http = require('http');
var https = require('https');

function ttsTest(text, lang) {
  return new Promise((resolve, reject) => {
    var body = JSON.stringify({ text: text, lang: lang });
    var req = https.request({
      hostname: 'intel-demo-topaz.vercel.app',
      path: '/api/tts',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }, (res) => {
      var data = [];
      res.on('data', chunk => data.push(chunk));
      res.on('end', () => {
        var buf = Buffer.concat(data);
        console.log(lang, ':', res.statusCode, res.headers['content-type'], 'bytes=' + buf.length);
        if (buf.length > 0 && buf.length < 500) {
          console.log('  body:', buf.toString('utf8'));
        }
        resolve();
      });
    });
    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

(async () => {
  await ttsTest('Xin chào, bạn khỏe không?', 'vi');
  await ttsTest('Hello world', 'en');
  await ttsTest('Mức phạt vượt đèn đỏ với xe máy là bao nhiêu?', 'vi');
})();
