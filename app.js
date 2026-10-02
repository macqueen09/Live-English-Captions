const $ = id => document.getElementById(id);
let lastId = 0,
  liveRows = [],
  historyRows = [],
  historyBefore = null,
  currentTab = 'live';
let followLatest = true;
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
  e.append(english, node('zh', r.zh));
  return e
}

function appendCaption(container, row) {
  const last = container.lastElementChild;
  const previous = last?.captionRows?.at(-1);
  const seconds = previous ? (Date.parse(row.timestamp) - Date.parse(previous.timestamp)) / 1000 : Infinity;
  const english = last?.querySelector('.spoken');
  const currentText = last?.captionRows?.map(r => r.en).join(' ') || '';
  if (previous && previous.source === row.source && previous.speaker === row.speaker &&
    seconds >= 0 && seconds <= 12 && currentText.length + row.en.length < 380) {
    // Append text nodes so an existing selection is never replaced.
    english.append(document.createTextNode(' ' + row.en));
    last.querySelector('.zh').append(document.createTextNode(' ' + row.zh));
    last.captionRows.push(row);
    return;
  }
  container.append(caption(row));
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
$('compact').onclick = () => {
  const enabled = document.body.classList.toggle('compact');
  $('compact').textContent = enabled ? '退出字幕模式' : '字幕模式';
  $('compact').setAttribute('aria-pressed', String(enabled));
  if (followLatest) $('live-scroll').scrollTop = $('live-scroll').scrollHeight;
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
  $('live-scroll').scrollTop = $('live-scroll').scrollHeight;
  $('follow-state').textContent = '跟随最新字幕';
};

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
  try {
    const s = await api(`state?after=${lastId}`);
    $('status').textContent = s.status;
    $('error').textContent = s.error;
    $('level').value = s.level;
    $('start').disabled = s.running;
    $('stop').disabled = !s.running;
    $('device').disabled = s.running;
    $('microphone').disabled = s.running;
    $('refresh').disabled = s.running;
    if (s.rows.length) {
      const sc = $('live-scroll'),
        follow = followLatest && !selectionActive() && currentTab === 'live';
      for (const r of s.rows) {
        if (r.id <= lastId) continue;
        appendCaption($('rows'), r);
        liveRows.push(r);
        lastId = r.id
      }
      $('empty').hidden = true;
      trimLive();
      if (follow) sc.scrollTop = sc.scrollHeight
    } else trimLive()
  } catch (e) {
    $('status').textContent = '服务连接失败';
    $('error').textContent = '后台服务未连接，请双击 start.cmd 恢复服务。';
    $('refresh').disabled = false;
    $('device').disabled = false;
    $('microphone').disabled = false;
    $('start').disabled = true;
    $('stop').disabled = true
  } finally {
    setTimeout(poll, 2000)
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
