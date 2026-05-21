// 로그인 체크
(function(){
  try {
    const a = JSON.parse(localStorage.getItem('readme_auth') || '{}');
    if(!a.token){ window.location.replace('/'); return; }
    window._auth = a;
    const sub = document.getElementById('logoSub');
    if(sub) sub.textContent = (a.name || '나') + '의 일기';
  } catch(e){ window.location.replace('/'); }
})();

function authHeaders(json = true) {
  const h = {'Authorization': 'Bearer ' + (window._auth?.token || '')};
  if(json) h['Content-Type'] = 'application/json';
  return h;
}

const API = 'http://localhost:8000';
const PAGES = ['home','write','library','stats'];
let cur = 'write';
let diariesCache = null;
let selId = null;

const EMOJI={
  '기쁨':'😊','행복감':'😄','환희':'✨','설렘':'💓','감사함':'🙏',
  '슬픔':'😢','우울함':'😔','외로움':'🌙','허무함':'🍂','그리움':'💭',
  '불안함':'😰','걱정':'😟','두려움':'😨','긴장감':'😬',
  '분노':'😡','짜증남':'😤','원망':'💢','억울함':'😠',
  '무기력함':'😪','지침':'😵','싱숭생숭함':'🌀','혼란스러움':'💫',
  '평온함':'😌','무감각함':'😶'
};
const CHIP_CLS={
  '기쁨':'pos','행복감':'pos','환희':'pos','설렘':'pos','감사함':'pos','평온함':'pos',
  '슬픔':'neg','우울함':'neg','외로움':'neg','허무함':'neg','그리움':'neg',
  '분노':'ang','짜증남':'ang','원망':'ang','억울함':'ang',
  '불안함':'neu','걱정':'neu','두려움':'neu','긴장감':'neu',
  '무기력함':'neu','지침':'neu','싱숭생숭함':'neu','혼란스러움':'neu','무감각함':'neu'
};

const _uname = (window._auth && window._auth.name) || '너';
const SPEECHES={
  home:`반가워! 오늘의 서재를\n살펴볼까? 📚`,
  write:`솔직하게 털어놔, ${_uname}.\n내가 다 들을게 🐾`,
  library:'과거의 기록들이\n여기 잠들어 있어 🌙',
  stats:'네 감정의 흐름을\n함께 볼까? 📊'
};
const MARU_STAGES={
  1:{cls:'maru-s1',name:'아기 마루',speeches:['안녕! 나는 아기 마루야 🥚\n일기를 쓰면 같이 자랄게!','아직 잘 모르지만...\n네 이야기가 궁금해 🌱','솔직하게 털어놔.\n내가 다 들을게 🐾']},
  2:{cls:'maru-s2',name:'소년 마루',speeches:['나 이제 날개가 생겼어! 🦉\n네 감정 패턴이 보이기 시작해.','같이 많이 쌓았구나!\n오늘은 어떤 하루였어?','점점 네가 어떤 사람인지\n알 것 같아 🌿']},
  3:{cls:'maru-s3',name:'현자 마루',speeches:['우린 이제 오랜 친구야. 🌙\n네 마음을 잘 알고 있어.','많이 성장했어, 나도 너도. ✨\n오늘도 여기 있을게.','힘들 땐 언제든 털어놔. 🦉\n과거의 네가 답을 알고 있어.']}
};
let prevStage=1;

function getMaruImgUrl(){
  const s=document.getElementById('maruSprite');
  if(!s) return '/img/web/%EB%A7%88%EB%A3%A81.png';
  if(s.classList.contains('maru-s3')) return '/img/web/%EB%A7%88%EB%A3%A83.png';
  if(s.classList.contains('maru-s2')) return '/img/web/%EB%A7%88%EB%A3%A82.png';
  return '/img/web/%EB%A7%88%EB%A3%A81.png';
}

function updateMaru(stats){
  const maru=stats.maru||{stage:1,stage_name:'아기 마루',next_at:5,progress:0};
  const {stage,stage_name,next_at,progress}=maru;
  const total=stats.total||0;
  const si=MARU_STAGES[stage]||MARU_STAGES[1];
  const sprite=document.getElementById('maruSprite');
  sprite.className='maru-sprite '+si.cls;
  document.getElementById('maruStageName').textContent=stage_name;
  document.getElementById('maruLv').textContent=next_at?`일기 ${total}개 · 다음 단계까지 ${next_at-total}개`:`일기 ${total}개 · 최고 단계 달성! 🎉`;
  document.getElementById('maruProg').style.width=Math.round(progress*100)+'%';
  document.getElementById('bnLevel').textContent=`Lv.${total}`;
  const wrStage=document.getElementById('wrStageLabel');
  if(wrStage) wrStage.textContent=stage_name;
  const speech=si.speeches[total%si.speeches.length];
  if(cur==='write'||cur==='home') document.getElementById('maruSpeech').textContent=speech;
  if(prevStage!==stage&&prevStage!==0){showLevelUp(stage_name);sprite.classList.add('maru-bounce');setTimeout(()=>sprite.classList.remove('maru-bounce'),1100);}
  prevStage=stage;
}
function showLevelUp(n){
  let t=document.getElementById('levelupToast');
  if(!t){t=document.createElement('div');t.id='levelupToast';t.className='levelup-toast';document.body.appendChild(t);}
  t.textContent=`🎉 마루가 성장했어요! → ${n}`;t.classList.add('show');setTimeout(()=>t.classList.remove('show'),3500);
}
function fetchAndUpdateMaru(){fetch(`${API}/stats`,{headers:authHeaders(false)}).then(r=>r.json()).then(updateMaru).catch(()=>{});}
fetchAndUpdateMaru();

function chip(e,sm=false){const c=CHIP_CLS[e]||'neu',em=EMOJI[e]||'•';return `<span class="chip chip-${c}${sm?' chip-sm':''}">${em} ${e}</span>`;}
function polIcon(p){return{positive:'☀️',negative:'🌧️',mixed:'🌤️'}[p]||'•';}
function fmt(dt){if(!dt)return '';const d=new Date(dt);if(isNaN(d))return dt;return `${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getDate()).padStart(2,'0')}`;}
function todayStr(){const d=new Date(),days=['일','월','화','수','목','금','토'];return `${d.getFullYear()}년 ${d.getMonth()+1}월 ${d.getDate()}일 (${days[d.getDay()]})`;}

function go(page){
  if(cur===page&&page!=='write')return;
  cur=page;
  PAGES.forEach(p=>{
    document.getElementById('nav-'+p).classList.toggle('active',p===page);
    document.getElementById('bn-'+p).classList.toggle('active',p===page);
  });
  document.getElementById('maruSpeech').textContent=SPEECHES[page]||'';
  PAGES.forEach(p=>{
    const L=document.getElementById(p+'-L'),R=document.getElementById(p+'-R');
    if(L)L.classList.toggle('visible',p===page);
    if(R)R.classList.toggle('visible',p===page);
  });
  document.getElementById('bookTab').classList.toggle('visible',page==='write');
  if(page==='home')    loadHome();
  if(page==='library') loadLibrary();
  if(page==='stats')   loadStats();
}

/* ══ 감정 선택기 ══ */
function initEmoSelector(){
  const el=document.getElementById('emoSelector');
  if(!el||el.dataset.init)return;
  el.dataset.init='1';
  el.innerHTML=Object.keys(EMOJI).map(e=>
    `<span class="emo-sel-chip" onclick="addEmotionTag('${e}')">${EMOJI[e]} ${e}</span>`
  ).join('');
}
function addEmotionTag(name){
  const ta=document.getElementById('diaryInput');
  const tag=' '+name;
  const pos=ta.selectionStart;
  const v=ta.value;
  ta.value=v.slice(0,pos)+tag+v.slice(pos);
  ta.selectionStart=ta.selectionEnd=pos+tag.length;
  ta.focus();
  document.getElementById('charCount').textContent=`${ta.value.length} / 2000`;
}
initEmoSelector();

/* ══ 홈 ══ */
function loadHome(){
  document.getElementById('home-date').textContent=todayStr();
  Promise.all([fetch(`${API}/diaries`,{headers:authHeaders(false)}).then(r=>r.json()),fetch(`${API}/stats`,{headers:authHeaders(false)}).then(r=>r.json())])
  .then(([diaries,stats])=>{
    diariesCache=diaries;
    const top=Object.entries(stats.emotion_freq||{})[0];
    document.getElementById('hs-total').textContent=stats.total||0;
    document.getElementById('hs-emo').textContent=top?EMOJI[top[0]]||'😶':'—';
    document.getElementById('hs-emo-lbl').textContent=top?top[0]:'기록 없음';
    const entries=document.getElementById('home-entries');
    if(!diaries.length){entries.innerHTML='<div class="no-data">아직 기록이 없어요.<br>첫 일기를 써볼까요? ✏️</div>';return;}
    entries.innerHTML=diaries.slice(0,4).map(d=>`
      <div class="home-entry" onclick="openDiary(${d.id})">
        <div class="home-entry-date">${fmt(d.created_at)} ${polIcon(d.emotion_polarity)}</div>
        <div class="home-entry-text">${d.summary||d.text||''}</div>
      </div>`).join('');
  }).catch(()=>{document.getElementById('home-entries').innerHTML='<div class="no-data">데이터를 불러올 수 없어요.</div>';});
}
function openDiary(id){selId=id;go('library');}

/* ══ 일기 쓰기 ══ */
document.getElementById('diaryInput').addEventListener('input',function(){
  document.getElementById('charCount').textContent=`${this.value.length} / 2000`;
});

async function doAnalyze(){
  const text=(document.getElementById('diaryInput').value||'').trim();
  if(!text){alert('일기를 먼저 작성해주세요!');return;}
  const btn=document.getElementById('analyzeBtn');
  btn.disabled=true;btn.innerHTML='<span class="spin">⟳</span> 분석 중…';
  document.getElementById('feedbackArea').innerHTML='<div class="ph"><span class="pi spin">⟳</span><p>마루가 일기를 읽고 있어요…<br><small style="opacity:.65">첫 실행 시 30초~1분 소요</small></p></div>';
  try{
    const res=await fetch(`${API}/analyze`,{method:'POST',headers:authHeaders(),body:JSON.stringify({text})});
    if(!res.ok)throw new Error(`서버 오류 ${res.status}`);
    renderFeedback(await res.json());diariesCache=null;fetchAndUpdateMaru();
  }catch(e){
    document.getElementById('feedbackArea').innerHTML=`<div class="ph"><span class="pi">⚠️</span><p style="color:#a05030">${e.message}</p></div>`;
  }finally{btn.disabled=false;btn.textContent='분석하기';}
}

/* ══ 분석 결과 렌더링 (카드 UI) ══ */
function renderFeedback(data){
  const {analysis, maru_memo, past_connection, ai_connected, ai_error} = data;

  const emotions     = analysis.emotions || [];
  const distortions  = analysis.cognitive_distortions || [];
  const distortion   = distortions[0] || '';
  const interpretation = data.interpretation || analysis.summary || '';
  const question     = data.question || analysis.followup_question || '';
  const highlight    = data.highlight || '';
  const sim          = past_connection?.similarity_score || 0;

  // 마루 사이드바 말풍선 업데이트
  if(maru_memo){
    document.getElementById('maruSpeech').textContent = maru_memo;
  }

  let cards = '';
  let idx = 0;

  // ── 카드 1: 감정 ──────────────────────────────────────────
  if(emotions.length){
    idx++;
    const chipsH = emotions.map(e=>chip(e)).join('');
    cards += `<div class="card emotion-card" style="animation-delay:${idx*0.1}s">
      <div class="card-label">💙 오늘의 감정</div>
      <div class="chips">${chipsH}</div>
    </div>`;
  }

  // ── 카드 2: 인지 왜곡 ────────────────────────────────────
  if(distortion){
    idx++;
    const highlightH = highlight
      ? `<div class="card-highlight">"${highlight}"</div>`
      : '';
    cards += `<div class="card distortion-card" style="animation-delay:${idx*0.1}s">
      <div class="card-label">🧠 생각 패턴</div>
      <div class="card-content"><span class="cbt-badge">⚡ ${distortion}</span></div>
      ${highlightH}
    </div>`;
  }

  // ── 카드 3: 해석 (A/B/C 대신 자연어) ────────────────────
  if(interpretation){
    idx++;
    cards += `<div class="card interpretation-card" style="animation-delay:${idx*0.1}s">
      <div class="card-label">📖 오늘 하루 읽기</div>
      <div class="card-content">${interpretation}</div>
    </div>`;
  }

  // ── 카드 4: 질문 (가장 강조) ─────────────────────────────
  if(question){
    idx++;
    cards += `<div class="card question-card" style="animation-delay:${idx*0.1}s">
      <div class="card-label">💬 마루의 질문</div>
      <div class="card-question">${question}</div>
    </div>`;
  }

  // ── 카드 5: 과거의 나 (RAG, 조건부) ─────────────────────
  if(sim >= 0.70 && past_connection?.past_summary){
    idx++;
    cards += `<div class="card rag-card" style="animation-delay:${idx*0.1}s">
      <div class="card-label">📚 과거의 나</div>
      <div class="card-content">"${past_connection.past_summary}"</div>
      <div class="card-sub">비슷한 상황을 ${Math.round(sim*100)}% 닮았어 — 그때도 결국 괜찮았잖아</div>
    </div>`;
  }

  // ── 마루 채팅 말풍선 ──────────────────────────────────────
  const maruImgUrl = getMaruImgUrl();
  const maruChatH = maru_memo ? `
    <div class="maru-chat">
      <div class="maru-avatar" style="background-image:url('${maruImgUrl}')"></div>
      <div class="maru-bubble">${maru_memo}</div>
    </div>` : '';

  const aiErrH = (ai_connected === false)
    ? `<div class="ai-error-note">⚠️ AI 미연결 — ${ai_error || 'Ollama가 실행 중인지 확인해주세요 (http://localhost:11434)'}</div>`
    : '';

  document.getElementById('feedbackArea').innerHTML = `
    <div class="scroll fi">
      <div class="cards-container">${cards || '<div style="font-size:11px;color:rgba(92,61,40,.5);padding:4px 0">분석 결과가 없어요.</div>'}</div>
      ${maruChatH}
      <div class="wellness-note" style="margin-top:8px">Read:Me는 의료적 진단·치료가 아닌 웰니스 기록 도구예요.</div>
      ${aiErrH}
    </div>`;
}

/* ══ 서재 ══ */
async function loadLibrary(){
  if(!diariesCache){
    try{diariesCache=await fetch(`${API}/diaries`,{headers:authHeaders(false)}).then(r=>r.json());}
    catch{document.getElementById('lib-list').innerHTML='<div class="no-data">데이터를 불러올 수 없어요.</div>';return;}
  }
  renderLibList(diariesCache);
  if(selId){const d=diariesCache.find(x=>x.id===selId);if(d)selectDiary(d);selId=null;}
}
function renderLibList(diaries){
  const el=document.getElementById('lib-list');
  if(!diaries.length){el.innerHTML='<div class="no-data">아직 일기가 없어요.<br>첫 일기를 써볼까요? ✏️</div>';return;}
  el.innerHTML=diaries.map(d=>{
    const emos=(d.emotions||[]).slice(0,2).map(e=>chip(e,true)).join('');
    return `<div class="lib-item" id="li-${d.id}" onclick="selectDiaryById(${d.id})">
      <div class="lib-row">
        <span class="lib-date">${fmt(d.created_at)}</span>
        <div style="display:flex;align-items:center;gap:3px">
          <span>${polIcon(d.emotion_polarity)}</span>
          <button class="del-btn" onclick="openDelModal(event,${d.id})" title="삭제">🗑️</button>
        </div>
      </div>
      <div class="lib-summary">${d.summary||d.text?.slice(0,40)||'(내용 없음)'}</div>
      <div class="chips">${emos}</div>
    </div>`;
  }).join('');
}

let delTargetId=null;
function openDelModal(e,id){
  e.stopPropagation();delTargetId=id;
  const d=diariesCache?.find(x=>x.id===id);
  document.getElementById('delModalPreview').textContent=d?(d.summary||d.text?.slice(0,60)||'내용 없음'):'';
  document.getElementById('delModal').classList.add('open');
}
function closeDelModal(){document.getElementById('delModal').classList.remove('open');delTargetId=null;}
async function confirmDelete(){
  if(!delTargetId)return;
  try{
    const res=await fetch(`${API}/diaries/${delTargetId}`,{method:'DELETE',headers:authHeaders(false)});
    if(!res.ok)throw new Error('삭제 실패');
    diariesCache=diariesCache?.filter(x=>x.id!==delTargetId)||null;
    document.getElementById('lib-detail').innerHTML='<div class="ph"><span class="pi">🗂️</span><p>왼쪽에서 일기를 선택하세요.</p></div>';
    if(diariesCache)renderLibList(diariesCache);
    fetchAndUpdateMaru();
  }catch(err){alert('삭제 중 오류: '+err.message);}
  finally{closeDelModal();}
}
function selectDiaryById(id){const d=diariesCache?.find(x=>x.id===id);if(!d)return;selectDiary(d);}

function selectDiary(d){
  document.querySelectorAll('.lib-item').forEach(el=>el.classList.remove('sel'));
  document.getElementById('li-'+d.id)?.classList.add('sel');

  const emos=(d.emotions||[]).map(e=>chip(e)).join('');
  const polLbl={positive:'긍정적 ☀️',negative:'부정적 🌧️',mixed:'복합적 🌤️'}[d.emotion_polarity]||'-';
  const distortions=d.cognitive_distortions||[];
  const interpretation=d.interpretation||d.summary||'';
  const question=d.question||d.followup_question||d.reframe_question||'';
  const highlight=d.highlight||'';

  const interpretH = interpretation
    ? `<div class="card interpretation-card fi" style="margin-bottom:6px">
        <div class="card-label">📖 오늘 하루 읽기</div>
        <div class="card-content">${interpretation}</div>
       </div>`
    : '';

  const distH = distortions.length
    ? `<div class="card distortion-card fi" style="margin-bottom:6px">
        <div class="card-label">🧠 생각 패턴</div>
        <div class="card-content">${distortions.map(dt=>`<span class="cbt-badge">⚡ ${dt}</span>`).join('')}</div>
        ${highlight?`<div class="card-highlight">"${highlight}"</div>`:''}
       </div>`
    : '';

  const questionH = question
    ? `<div class="card question-card fi" style="margin-bottom:6px">
        <div class="card-label">💬 마루의 질문</div>
        <div class="card-question">${question}</div>
       </div>`
    : '';

  document.getElementById('lib-detail').innerHTML=`
    <div class="scroll fi">
      <div style="font-size:9.5px;color:rgba(92,61,40,.42);margin-bottom:6px">${fmt(d.created_at)} · ${polLbl}</div>
      <div class="sec-lbl">원문</div>
      <div class="lib-text">${d.text||''}</div>
      <hr class="divider">
      <div class="sec-lbl">분석</div>
      <div style="margin-bottom:6px"><div class="chips">${emos||'<span style="font-size:10px;opacity:.4">감정 없음</span>'}</div></div>
      ${interpretH}
      ${distH}
      ${questionH}
    </div>`;
}

/* ══ 통계 ══ */
function loadStats(){
  Promise.all([
    fetch(`${API}/stats`,{headers:authHeaders(false)}).then(r=>r.json()),
    fetch(`${API}/recovery-stats`,{headers:authHeaders(false)}).then(r=>r.json()).catch(()=>({groups:[]}))
  ]).then(([stats,recovery])=>{
    const lEl=document.getElementById('stats-left-content'),rEl=document.getElementById('stats-right-content');
    if(!stats.total){
      lEl.innerHTML='<div class="no-data" style="padding-top:16px">아직 기록이 없어요.<br>일기를 써보세요! ✏️</div>';
      rEl.innerHTML='<div class="no-data">데이터 없음</div>';return;
    }

    const pol=stats.polarity_dist||{},pTotal=Object.values(pol).reduce((a,b)=>a+b,0)||1;
    function polBar(key,cls,lbl){const c=pol[key]||0,pct=Math.round(c/pTotal*100);return `<div class="pol-row"><span class="pol-lbl">${lbl}</span><div class="pol-bar"><div class="${cls}" style="width:${pct}%"></div></div><span class="pol-cnt">${c}</span></div>`;}
    const freq=Object.entries(stats.emotion_freq||{});
    const mx=Math.max(...freq.map(([,v])=>v),1);
    lEl.innerHTML=`<div class="fi">
      <div class="stat-big"><div class="stat-big-num">${stats.total}</div><div class="stat-big-lbl">총 기록한 일기</div></div>
      <hr class="divider">
      <div class="sec-lbl">감정 극성 분포</div>
      ${polBar('positive','pf-pos','긍정 ☀️')}${polBar('negative','pf-neg','부정 🌧️')}${polBar('mixed','pf-mix','복합 🌤️')}
      <hr class="divider">
      <div class="sec-lbl">감정 빈도 TOP 5</div>
      ${freq.slice(0,5).map(([e,c],i)=>`
        <div class="top-row">
          <span style="font-size:9px;color:rgba(92,61,40,.42);min-width:13px">${i+1}</span>
          <span class="top-em">${EMOJI[e]||'•'}</span>
          <span class="top-nm">${e}</span>
          <div class="top-bar"><div class="top-fill" style="width:${Math.round(c/mx*100)}%"></div></div>
          <span class="top-cnt">${c}</span>
        </div>`).join('')}
    </div>`;

    const groups=recovery.groups||[];
    let recH='';
    if(groups.length){
      recH=groups.map(g=>`
        <div class="rec-item">
          <div class="rec-emotion">${EMOJI[g.emotion]||'•'} ${g.emotion}</div>
          <div class="rec-meta">기록 ${g.total}건 · 회복 ${g.resolved}건</div>
          <div class="rec-meta" style="margin-top:2px">처음 회복까지 ${g.first_recovery_count}번 → 최근 ${g.latest_recovery_count}번</div>
          <span class="rec-badge ${g.improving?'rec-badge-up':'rec-badge-flat'}">${g.improving?'📈 회복이 빨라지고 있어':'📊 비슷한 패턴'}</span>
        </div>`).join('');
    } else {
      recH='<div class="no-data">같은 감정이 3번 이상 기록되면<br>회복 패턴을 보여드려요.<br><span style="font-size:9.5px;opacity:.7">일기를 계속 써봐요 🌱</span></div>';
    }
    rEl.innerHTML=`<div class="fi">
      <div style="font-size:10px;color:rgba(92,61,40,.55);line-height:1.6;margin-bottom:8px">
        같은 감정을 반복할 때 회복 속도가 빨라지면<br>"감정 근육이 성장하고 있어" 📈
      </div>
      ${recH}
    </div>`;
  }).catch(()=>{document.getElementById('stats-left-content').innerHTML='<div class="no-data">데이터 없음</div>';});
}
