var fs = require('fs');
var s = fs.readFileSync('web/index.html', 'utf8');
var Q = String.fromCharCode(34);
var idx = s.indexOf('id=' + Q + 'langSwitch' + Q);
console.log(JSON.stringify(s.substring(idx - 30, idx + 700)));
