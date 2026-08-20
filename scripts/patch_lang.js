var fs = require('fs');
var path = 'web/index.html';
var s = fs.readFileSync(path, 'utf8');

var Q = String.fromCharCode(34);
var LT = String.fromCharCode(60);
var GT = String.fromCharCode(62);

var oldStr =
  '      ' + LT + 'div class=' + Q + 'spacer' + Q + GT + LT + '/div' + GT + '\n' +
  '      ' + LT + 'nav class=' + Q + 'modes' + Q + ' id=' + Q + 'modeSwitch' + Q + GT + '\n' +
  '        ' + LT + 'button class=' + Q + 'mode active' + Q + ' id=' + Q + 'modeChat' + Q + ' type=' + Q + 'button' + Q + GT + '💬 Chat' + LT + '/button' + GT + '\n' +
  '        ' + LT + 'button class=' + Q + 'mode' + Q + ' id=' + Q + 'modeCall' + Q + ' type=' + Q + 'button' + Q + GT + '📞 Cuộc gọi' + LT + '/button' + GT + '\n' +
  '      ' + LT + '/nav' + GT + '\n' +
  '      ' + LT + 'div class=' + Q + 'status' + Q + ' id=' + Q + 'status' + Q + GT + 'sẵn sàng' + LT + '/div' + GT;

var idx = s.indexOf(oldStr);
if (idx === -1) {
  console.error('Old string not found');
  process.exit(1);
}

var newStr =
  '      ' + LT + 'div class=' + Q + 'spacer' + Q + GT + LT + '/div' + GT + '\n' +
  '      ' + LT + 'div class=' + Q + 'lang-switch' + Q + ' id=' + Q + 'langSwitch' + Q + ' role=' + Q + 'group' + Q + ' aria-label=' + Q + 'Ngôn ngữ' + Q + GT + '\n' +
  '        ' + LT + 'span class=' + Q + 'flag' + Q + ' aria-hidden=' + Q + 'true' + Q + GT + '🌐' + LT + '/span' + GT + '\n' +
  '        ' + LT + 'button class=' + Q + 'lang-btn active' + Q + ' data-lang=' + Q + 'auto' + Q + ' type=' + Q + 'button' + Q + ' title=' + Q + 'Tự động theo ngôn ngữ câu hỏi' + Q + GT + 'Auto' + LT + '/button' + GT + '\n' +
  '        ' + LT + 'button class=' + Q + 'lang-btn' + Q + ' data-lang=' + Q + 'vi' + Q + ' type=' + Q + 'button' + Q + ' title=' + Q + 'Tiếng Việt' + Q + GT + 'VI' + LT + '/button' + GT + '\n' +
  '        ' + LT + 'button class=' + Q + 'lang-btn' + Q + ' data-lang=' + Q + 'en' + Q + ' type=' + Q + 'button' + Q + ' title=' + Q + 'English' + Q + GT + 'EN' + LT + '/button' + GT + '\n' +
  '      ' + LT + '/div' + GT + '\n' +
  '      ' + LT + 'nav class=' + Q + 'modes' + Q + ' id=' + Q + 'modeSwitch' + Q + GT + '\n' +
  '        ' + LT + 'button class=' + Q + 'mode active' + Q + ' id=' + Q + 'modeChat' + Q + ' type=' + Q + 'button' + Q + GT + '💬 Chat' + LT + '/button' + GT + '\n' +
  '        ' + LT + 'button class=' + Q + 'mode' + Q + ' id=' + Q + 'modeCall' + Q + ' type=' + Q + 'button' + Q + GT + '📞 Cuộc gọi' + LT + '/button' + GT + '\n' +
  '      ' + LT + '/nav' + GT + '\n' +
  '      ' + LT + 'div class=' + Q + 'status' + Q + ' id=' + Q + 'status' + Q + GT + 'sẵn sàng' + LT + '/div' + GT;

var newContent = s.substring(0, idx) + newStr + s.substring(idx + oldStr.length);
fs.writeFileSync(path, newContent);
console.log('OK, new size:', newContent.length);
