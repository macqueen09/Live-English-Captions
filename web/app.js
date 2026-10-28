const $ = id => document.getElementById(id);
let lastId = 0,
  liveRows = [],
  historyRows = [],
  historyBefore = null,
  currentTab = 'live';
let followLatest = true;
let liveRevision = -1;
let followChinese = true;
let selected = {
    term: '',
    zh: '',
    context: ''
  },
  lookupGeneration = 0,
  wordRows = [],
  cards = [],
  cardIndex = 0,
  historyGeneration = 0;
async function api(path, body) {
  const r = await fetch('/api/' + path, body === undefined ? {} : {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(body)
  });
  const d = await r.json();
  if (!r.ok) throw Error(d.detail || '请求失败');
  return d
}

function node(cls, text) {
  const e = document.createElement('div');
  e.className = cls;
  e.textContent = text;
  return e
}

function caption(r) {
  const e = document.createElement('article');
  e.dataset.id = r.id;
  e.dataset.source = r.source;
  e.captionRows = [r];
  const head = node('time', r.time),
    person = document.createElement('button'),
    edit = document.createElement('button');
  person.className = 'speaker-name';
  person.dataset.source = r.source;
  person.textContent = r.speaker;
  person.onclick = () => r.source.startsWith('remote:') ? renameSpeaker(r) : null;
  person.title = r.source.startsWith('remote:') ? '点击为本次会话的这位人物命名' : '音频来源';
  head.title = `${r.date} ${r.time}${r.session ? ' · 会话 ' + r.session : ''}`;
  head.append(person);
  edit.className = 'speaker-edit';
  edit.textContent = '改人物';
  edit.onclick = () => correctSpeaker(r, e);
  head.append(edit);
  const english = node('en', r.en);
  english.textContent = '';
  const spoken = document.createElement('span');
  spoken.className = 'spoken';
  spoken.textContent = r.en;
  english.append(spoken, head);
  const chinese = node('zh', '');
  const translation = document.createElement('span');
  translation.dataset.translationId = r.id;
  translation.textContent = r.zh || '中文稍后补充…';
  if (r.translation_group && r.translation_group !== r.id) translation.textContent = '（译文见同段首句）';
  chinese.append(translation);
  e.append(english, chinese);
  return e
}

function freshText(text) {
  const span = document.createElement('span');
  span.textContent = text;
  span.className = 'caption-new';
  setTimeout(() => span.classList.remove('caption-new'), 4500);
  return span;
}

function appendCaption(container, row) {
  const live = container === $('rows');
  const last = container.lastElementChild;
  const previous = last?.captionRows?.at(-1);
  const seconds = previous ? (Date.parse(row.timestamp) - Date.parse(previous.timestamp)) / 1000 : Infinity;
  const english = last?.querySelector('.spoken');
  const currentText = last?.captionRows?.map(r => r.en).join(' ') || '';
  if (previous && previous.source === row.source && previous.speaker === row.speaker &&
    seconds >= 0 && seconds <= 12 && currentText.length + row.en.length < 380) {
    // Append text nodes so an existing selection is never replaced.
    english.append(live ? freshText(' ' + row.en) : document.createTextNode(' ' + row.en));
    const translation = document.createElement('span');
    translation.dataset.translationId = row.id;
    translation.append(live && row.zh ? freshText(' ' + row.zh) : document.createTextNode(' ' + (row.zh || '中文稍后补充…')));
    last.querySelector('.zh').append(translation);
    last.captionRows.push(row);
    return;
  }
  const item = caption(row);
  if (live) {
    item.querySelector('.spoken').replaceChildren(freshText(row.en));
    if (row.zh) item.querySelector('[data-translation-id]').replaceChildren(freshText(row.zh));
  }
  container.append(item);
}

function updateTranslation(row) {
  const span = $('rows').querySelector(`[data-translation-id="${row.id}"]`);
  if (span && row.zh !== span.dataset.zh) {
    const first = span.parentElement.firstElementChild === span;
    const text = row.translation_group && row.translation_group !== row.id ? '（译文见同段首句）' : row.zh;
    span.replaceChildren(freshText((first ? '' : ' ') + text));
    span.dataset.zh = row.zh;
  }
  for (const item of liveRows) if (item.id === row.id) Object.assign(item, row);
  for (const article of $('rows').children)
    for (const item of article.captionRows || []) if (item.id === row.id) Object.assign(item, row);
}

function updateEnglish(spoken, text) {
  const before = spoken.textContent;
  if (before === text) return;
  if (text.startsWith(before)) { spoken.append(freshText(text.slice(before.length))); return; }
  let common = 0;
  while (common < Math.min(before.length, text.length) && before[common] === text[common]) common++;
  const selection = window.getSelection();
  if (selection?.toString() && spoken.contains(selection.anchorNode)) return;
  // Keep prefix nodes intact; only the editable suffix is deleted/replaced.
  const walker = document.createTreeWalker(spoken, NodeFilter.SHOW_TEXT);
  let offset = common, start = walker.nextNode();
  while (start && offset > start.length) { offset -= start.length; start = walker.nextNode(); }
  if (start) {
    const range = document.createRange();
    range.setStart(start, offset);
    range.setEnd(spoken, spoken.childNodes.length);
    range.deleteContents();
  } else spoken.replaceChildren();
  spoken.append(freshText(text.slice(common)));
}

function renderParagraphs(paragraphs) {
  const container = $('rows');
  const firstKey = Number(paragraphs[0]?.key || Infinity);
  let shown = paragraphs;
  if (followLatest && !selectionActive()) shown = paragraphs.slice(-12);
  else {
    const first = Number(container.firstElementChild?.dataset.paragraphKey || firstKey);
    shown = paragraphs.filter(p => Number(p.key) >= first);
  }
  const keys = new Set(shown.map(p => p.key));
  for (const article of [...container.children])
    if (!keys.has(article.dataset.paragraphKey) && (followLatest || Number(article.dataset.paragraphKey) >= firstKey)) article.remove();
  for (const [index, p] of shown.entries()) {
    let article = [...container.children].find(el => el.dataset.paragraphKey === p.key);
    const row = p.rows[0] || {id:0, en:p.en, zh:'', source:p.source || p.capture_source, speaker:p.speaker, time:p.time, date:p.date};
    if (!article) {
      article = caption({...row, en:p.en});
      article.dataset.paragraphKey = p.key;
      article.querySelector('.spoken').replaceChildren(freshText(p.en));
      const following = new Set(shown.slice(index+1).map(item => item.key));
      const next = [...container.children].find(el => following.has(el.dataset.paragraphKey));
      container.insertBefore(article, next || null);
    } else updateEnglish(article.querySelector('.spoken'), p.en);
    article.dataset.id = p.rows[0]?.id || 0;
    article.captionRows = p.rows;
    const person = article.querySelector('.speaker-name');
    person.textContent = p.speaker;
    person.dataset.source = p.source || p.capture_source;
    person.onclick = () => row.source.startsWith('remote:') ? renameSpeaker(row) : null;
    const edit = article.querySelector('.speaker-edit');
    edit.disabled = !p.rows.length;
    edit.onclick = () => correctSpeaker(row, article);
  }
  $('partial-rows').replaceChildren();
}

function renderChinese() {
  const container = $('translation-scroll');
  const rows = liveRows.filter(r => !r.translation_group || r.translation_group === r.id).slice(-16);
  const ids = new Set(rows.map(r => String(r.id)));
  for (const item of [...container.children]) if (!ids.has(item.dataset.id)) item.remove();
  for (const row of rows) {
    let item = [...container.children].find(el => el.dataset.id === String(row.id));
    if (!item) {
      item = document.createElement('article');
      item.dataset.id = row.id;
      const meaning = node('zh', '');
      const text = document.createElement('span');
      text.className = 'translation-text';
      meaning.append(text, node('time', `${row.time} · ${row.speaker}`));
      item.append(meaning);
      const next = [...container.children].find(el => Number(el.dataset.id) > row.id);
      container.insertBefore(item, next || null);
    }
    const meaning = item.querySelector('.translation-text');
    if (item.dataset.zh !== row.zh) {
      meaning.replaceChildren(row.zh ? freshText(row.zh) : document.createTextNode('中文稍后补充…'));
      item.dataset.zh = row.zh;
    }
  }
  if (followChinese) container.scrollTop = container.scrollHeight;
}

function updatePreviews(partials) {
  const container = $('partial-rows');
  const active = new Set(partials.map(p => p.source));
  for (const child of [...container.children]) if (!active.has(child.dataset.source)) child.remove();
  for (const preview of partials) {
    let article = [...container.children].find(el => el.dataset.source === preview.source);
    if (!article) {
      article = document.createElement('article');
      article.dataset.source = preview.source;
      article.className = 'partial-caption';
      const en = node('en', '');
      const spoken = document.createElement('span');
      spoken.className = 'spoken';
      en.append(spoken, node('time', preview.speaker + ' · 实时预览'));
      article.append(en);
      container.append(article);
    }
    const spoken = article.querySelector('.spoken');
    const before = spoken.textContent;
    if (before === preview.en) continue;
    if (window.getSelection()?.anchorNode && spoken.contains(window.getSelection().anchorNode) && selectionActive()) continue;
    if (preview.en.startsWith(before)) spoken.append(freshText(preview.en.slice(before.length)));
    else {
      let common = 0;
      while (common < before.length && before[common] === preview.en[common]) common++;
      spoken.replaceChildren(document.createTextNode(preview.en.slice(0, common)), freshText(preview.en.slice(common)));
    }
  }
}
async function devices() {
  try {
    const d = await api('devices');
    $('device').replaceChildren();
    $('microphone').replaceChildren();
    const off = document.createElement('option');
    off.value = '';
    off.textContent = '不记录麦克风';
    $('microphone').append(off);
    for (const m of d.microphones) {
      const o = document.createElement('option');
      o.value = m.id;
      o.textContent = '麦克风：' + m.name;
      o.selected = m.id === d.default_microphone;
      $('microphone').append(o)
    }
    for (const x of d.devices) {
      const o = document.createElement('option');
      o.value = x.id;
      o.textContent = x.name;
      o.selected = x.id === d.default;
      $('device').append(o)
    }
    if (!d.devices.length) throw Error('未找到播放设备，请连接耳机后刷新。')
  } catch (e) {
    $('error').textContent = e.message
  }
}
$('refresh').onclick = devices;
$('start').onclick = async () => {
  try {
    if (!$('device').value) throw Error('请先选择耳机');
    $('start').disabled = true;
    await api('start', {
      device: Number($('device').value),
      microphone: $('microphone').value === '' ? null : Number($('microphone').value)
    })
  } catch (e) {
    $('error').textContent = e.message;
    $('start').disabled = false
  }
};
$('stop').onclick = async () => {
  try {
    await api('stop', {})
  } catch (e) {
    $('error').textContent = e.message
  }
};
$('compact').onclick = async () => {
  try {
    try { await api('overlay', {}); }
    catch (error) {
      const response = await fetch('http://127.0.0.1:8767/open', {method:'POST', headers:{'Content-Type':'application/json'}, body:'{}'});
      if (!response.ok) throw Error('无法启动悬浮窗，请双击桌面快捷方式后重试。');
    }
    $('compact').textContent = '打开悬浮字幕';
  } catch (error) { $('error').textContent = error.message; }
};
$('live-scroll').addEventListener('scroll', () => {
  const sc = $('live-scroll');
  followLatest = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 8;
  $('follow-state').textContent = followLatest ? '跟随最新字幕' : '正在回看 · 滚到底部恢复跟随';
}, {
  passive: true
});
$('follow-state').onclick = () => {
  followLatest = true;
  followChinese = true;
  $('live-scroll').scrollTop = $('live-scroll').scrollHeight;
  $('follow-state').textContent = '跟随最新字幕';
};
$('translation-scroll').addEventListener('scroll', () => {
  const sc = $('translation-scroll');
  followChinese = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 8;
}, {passive:true});

function selectionActive() {
  return Boolean(window.getSelection()?.toString().trim())
}

function trimLive() {
  if (selectionActive() || !followLatest) return;
  while ($('rows').children.length > 12) $('rows').firstElementChild.remove();
  const firstId = Number($('rows').firstElementChild?.dataset.id || 0);
  liveRows = liveRows.filter(r => r.id >= firstId)
}
async function poll() {
  let delay = 50;
  try {
    let s;
    try { s = await api(`live?after=${lastId}&revision=${liveRevision}`); }
    catch (error) { s = await api(`state?after=${lastId}&revision=${liveRevision}`); delay = 1000; }
    liveRevision = s.revision ?? -1;
    if (s.hardware) {
      const mode = `ASR ${s.hardware.asr} / 中文 ${s.hardware.translation}`;
      document.querySelector('h1').textContent = 'Live English Captions · ' + mode;
      document.title = 'Live English Captions · ' + mode;
      $('status').title = Object.entries(s.hardware.fallback || {}).map(([k,v]) => `${k}: ${v}`).join('\n');
    }
    $('status').textContent = s.status;
    $('error').textContent = s.error;
    $('level').value = s.level;
    $('start').disabled = s.running;
    $('stop').disabled = !s.running;
    $('device').disabled = s.running;
    $('microphone').disabled = s.running;
    $('refresh').disabled = s.running;
    if (s.rows.length || s.updates?.length || s.partials !== undefined) {
      const sc = $('live-scroll'),
        atBottom = sc.scrollHeight - sc.scrollTop - sc.clientHeight <= 8;
      if (followLatest && !atBottom && !selectionActive()) followLatest = false;
      const follow = followLatest && !selectionActive() && currentTab === 'live';
      for (const r of s.rows) {
        if (r.id <= lastId) continue;
        if (!s.paragraphs) appendCaption($('rows'), r);
        liveRows.push(r);
        lastId = r.id
      }
      for (const r of s.updates || []) updateTranslation(r);
      if (s.paragraphs) renderParagraphs(s.paragraphs);
      else updatePreviews(s.partials || []);
      $('empty').hidden = liveRows.length > 0 || (s.partials || []).length > 0;
      trimLive();
      renderChinese();
      if (follow) sc.scrollTop = sc.scrollHeight
    } else trimLive()
  } catch (e) {
    delay = 1000;
    $('status').textContent = '服务连接失败';
    $('error').textContent = '后台服务未连接，请双击 start.cmd 恢复服务。';
    $('refresh').disabled = false;
    $('device').disabled = false;
    $('microphone').disabled = false;
    $('start').disabled = true;
    $('stop').disabled = true
  } finally {
    setTimeout(poll, delay)
  }
}
for (const b of document.querySelectorAll('nav button')) b.onclick = async () => {
  currentTab = b.dataset.tab;
  for (const p of document.querySelectorAll('.panel')) p.hidden = p.id !== currentTab;
  for (const x of document.querySelectorAll('nav button')) x.classList.toggle('active', x === b);
  if (currentTab === 'history') await loadDates();
  if (currentTab === 'vocabulary') await loadWords()
};
async function loadDates() {
  try {
    const previous = $('dates').value,
      dates = await api('history/dates');
    $('dates').replaceChildren();
    for (const x of dates) {
      const o = document.createElement('option');
      o.value = x.date;
      o.textContent = `${x.date} · ${x.count} 段`;
      $('dates').append(o)
    }
    if (dates.some(x => x.date === previous)) $('dates').value = previous;
    if (dates.length) await loadHistory(false);
    else {
      $('history-message').textContent = '还没有保存的聊天记录。';
      $('history-rows').replaceChildren();
      $('older').hidden = true
    }
  } catch (e) {
    $('history-message').textContent = e.message
  }
}
async function loadHistory(older) {
  const g = ++historyGeneration;
  try {
    const date = $('dates').value,
      d = await api(`history/${date}${older&&historyBefore?'?before='+historyBefore:''}`);
    if (g !== historyGeneration) return;
    if (!older) {
      $('history-rows').replaceChildren();
      historyRows = []
    }
    const f = document.createDocumentFragment();
    d.rows.forEach(r => appendCaption(f, r));
    $('history-rows').prepend(f);
    historyRows = [...d.rows, ...historyRows];
    historyBefore = d.before;
    $('older').hidden = !d.more;
    $('history-message').textContent = `已显示 ${historyRows.length} 段${d.more?'，可加载更早记录':''}`
  } catch (e) {
    $('history-message').textContent = e.message
  }
}
$('history-refresh').onclick = loadDates;
$('dates').onchange = () => loadHistory(false);
$('older').onclick = () => loadHistory(true);

function download(name, text) {
  const u = URL.createObjectURL(new Blob(['\ufeff' + text], {
      type: 'text/plain;charset=utf-8'
    })),
    a = document.createElement('a');
  a.href = u;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(u), 1000)
}
$('history-export').onclick = async () => {
  const date = $('dates').value;
  if (!date) return;
  try {
    let rows = [],
      before = null,
      more;
    do {
      const d = await api(`history/${date}${before?'?before='+before:''}`);
      rows = [...d.rows, ...rows];
      before = d.before;
      more = d.more
    } while (more);
    download(`${date}-双语字幕.txt`, rows.map(r => `[${r.time}] ${r.speaker}${r.session?"（会话 "+r.session+"）":""}\n${r.en}\n${r.zh}`).join('\n\n'))
  } catch (e) {
    $('history-message').textContent = e.message
  }
};

function openLookup(term, context = '') {
  lookupGeneration++;
  selected = {
    term,
    zh: '',
    context
  };
  $('lookup').hidden = false;
  $('lookup-open').hidden = true;
  $('lookup-term').value = term;
  $('lookup-result').textContent = '';
  $('lookup-context').textContent = context ? '原句：' + context : '';
  $('lookup-message').textContent = '';
  $('lookup-save').disabled = true
}

function lookupSelection() {
  const s = window.getSelection(),
    term = s?.toString().trim(),
    a = s?.anchorNode?.parentElement?.closest('.spoken'),
    f = s?.focusNode?.parentElement?.closest('.spoken');
  if (term && term.length <= 120 && a && a === f) openLookup(term, a.textContent)
}
document.addEventListener('mouseup', e => {
  if (e.target.closest('.spoken')) lookupSelection()
});
document.addEventListener('keyup', e => {
  if (e.shiftKey) lookupSelection()
});
$('lookup-open').onclick = () => openLookup('');
$('lookup-close').onclick = () => {
  lookupGeneration++;
  $('lookup').hidden = true;
  $('lookup-open').hidden = false
};
$('lookup-term').oninput = () => {
  lookupGeneration++;
  selected.zh = '';
  $('lookup-save').disabled = true;
  $('lookup-result').textContent = ''
};
$('lookup-translate').onclick = async () => {
  const g = ++lookupGeneration;
  selected.term = $('lookup-term').value.trim();
  selected.zh = '';
  $('lookup-save').disabled = true;
  $('lookup-result').textContent = '正在本机翻译…';
  $('lookup-message').textContent = '';
  try {
    const d = await api('translate-word', {
      term: selected.term
    });
    if (g !== lookupGeneration) return;
    selected.term = d.term;
    selected.zh = d.zh;
    $('lookup-result').textContent = d.zh;
    $('lookup-save').disabled = false
  } catch (e) {
    if (g === lookupGeneration) $('lookup-result').textContent = e.message
  }
};
$('lookup-save').onclick = async () => {
  const g = lookupGeneration,
    entry = {
      ...selected
    };
  $('lookup-save').disabled = true;
  try {
    await api('words', entry);
    if (g === lookupGeneration) $('lookup-message').textContent = '已保存到个人单词本。';
    if (currentTab === 'vocabulary') await loadWords()
  } catch (e) {
    if (g === lookupGeneration) {
      $('lookup-message').textContent = e.message;
      $('lookup-save').disabled = false
    }
  }
};
async function loadWords() {
  try {
    wordRows = await api('words');
    renderWords()
  } catch (e) {
    $('word-count').textContent = e.message
  }
}

function renderWords() {
  const q = $('word-search').value.toLowerCase(),
    visible = wordRows.filter(w => (w.term + ' ' + w.zh).toLowerCase().includes(q));
  $('word-count').textContent = `共 ${wordRows.length} 个单词 / 短语 · 已掌握 ${wordRows.filter(w=>w.mastered).length} 个`;
  $('word-list').replaceChildren();
  for (const w of visible) {
    const e = document.createElement('article'),
      head = document.createElement('div'),
      term = document.createElement('strong'),
      progress = document.createElement('span');
    head.className = 'word-head';
    term.textContent = w.term;
    progress.textContent = `${w.mastered?'已掌握':'待学习'} · 复习 ${w.reviewed} 次`;
    head.append(term, progress);
    e.append(head, node('word-meaning', w.zh));
    if (w.context) e.append(node('context', w.context));
    $('word-list').append(e)
  }
  if (!visible.length) $('word-list').append(node('empty', q ? '没有匹配的单词' : '从字幕中选词、翻译并保存，即可开始积累。'))
}
$('word-search').oninput = renderWords;
$('words-refresh').onclick = loadWords;
$('words-export').onclick = async () => {
  await loadWords();
  download('个人单词本.txt', wordRows.map(w => `${w.term}\n${w.zh}\n${w.context}\n${w.mastered?'已掌握':'待学习'} · 复习 ${w.reviewed} 次`).join('\n\n'))
};
$('study-start').onclick = async () => {
  await loadWords();
  cards = wordRows.filter(w => !w.mastered);
  if (!cards.length) cards = [...wordRows];
  cardIndex = 0;
  $('study').hidden = false;
  showCard()
};

function showCard() {
  const c = cards[cardIndex];
  $('study-actions').hidden = true;
  $('study-answer').hidden = true;
  $('reveal').hidden = !c;
  if (!c) {
    $('study-count').textContent = '';
    $('study-term').textContent = cards.length ? '本轮复习完成' : '先保存几个单词吧';
    $('study-context').textContent = '';
    return
  }
  $('study-count').textContent = `${cardIndex+1} / ${cards.length}`;
  $('study-term').textContent = c.term;
  $('study-context').textContent = c.context;
  $('study-answer').textContent = c.zh
}
$('reveal').onclick = () => {
  $('study-answer').hidden = false;
  $('study-actions').hidden = false;
  $('reveal').hidden = true
};
async function review(mastered) {
  const c = cards[cardIndex];
  if (!c) return;
  $('remember').disabled = true;
  $('again').disabled = true;
  try {
    await api(`words/${c.id}/review`, {
      mastered
    });
    cardIndex++;
    showCard();
    await loadWords()
  } catch (e) {
    $('study-count').textContent = e.message
  } finally {
    $('remember').disabled = false;
    $('again').disabled = false
  }
}
$('remember').onclick = () => review(true);
$('again').onclick = () => review(false);
devices();
poll();

async function correctSpeaker(row, element) {
  const originals = element.captionRows || [row];
  const name = prompt(originals.length > 1 ? '输入这一块字幕的说话人姓名（修改其中所有句子）：' : '输入这句话的说话人姓名（只修改此句）：', row.speaker);
  if (name === null || !name.trim()) return;
  try {
    const replacements = document.createDocumentFragment();
    for (const original of originals) {
      const updated = await api(`transcripts/${original.id}/speaker`, {
        name
      });
      // Keep individually corrected source identities intact.
      replacements.append(caption(updated));
      for (const list of [liveRows, historyRows]) {
        const index = list.findIndex(x => x.id === original.id);
        if (index >= 0) list[index] = updated;
      }
    }
    element.replaceWith(replacements);
  } catch (error) {
    alert(error.message)
  }
}
$('export-all').onclick = () => {
  const a = document.createElement('a');
  a.href = '/api/export';
  a.download = '全部双语对话.txt';
  a.click()
};

async function renameSpeaker(row) {
  const name = prompt('为此人命名（修改本次会话同一声纹的所有句子）：', row.speaker);
  if (name === null || !name.trim()) return;
  try {
    const result = await api('speakers/name', {
      source: row.source,
      name
    });
    for (const button of document.querySelectorAll('.speaker-name'))
      if (button.dataset.source === row.source) button.textContent = result.name;
    for (const list of [liveRows, historyRows])
      for (const r of list)
        if (r.source === row.source) r.speaker = result.name;
    row.speaker = result.name
  } catch (error) {
    alert(error.message)
  }
}
