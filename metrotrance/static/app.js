const $ = (id) => document.getElementById(id);
let currentJob = null;
let pollTimer = null;
let audioAssets = {music:[], atmosphere:[], event:[]};
let lastAutomaticStressText = '';
let lastHealth = null;
let voiceLabState = {jobId:null, readyIds:[], listened:new Set()};

function escapeHtml(value){return String(value).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));}


function openDialog(dialog){
  if(!dialog.open) dialog.showModal();
}

function closeDialog(dialog){
  if(dialog && dialog.open) dialog.close('cancel');
}

function bindDialogControls(dialog){
  if(!dialog) return;
  dialog.querySelectorAll('[data-dialog-close]').forEach(button=>{
    button.addEventListener('click',event=>{
      event.preventDefault();
      event.stopPropagation();
      closeDialog(dialog);
    });
  });
  dialog.addEventListener('click',event=>{
    if(event.target===dialog) closeDialog(dialog);
  });
}

bindDialogControls($('settingsDialog'));
bindDialogControls($('soundLibraryDialog'));

function stressPreviewHtml(value){
  const text=String(value||'').normalize('NFD');
  const pattern=/([АЕЁИОУЫЭЮЯаеёиоуыэюя])\u0301/g;
  let html='';let cursor=0;let match;
  while((match=pattern.exec(text))!==null){
    html+=escapeHtml(text.slice(cursor,match.index));
    html+=`<span class="stress-vowel">${escapeHtml(match[1]+'\u0301')}</span>`;
    cursor=pattern.lastIndex;
  }
  html+=escapeHtml(text.slice(cursor));
  return html;
}

async function api(path, options={}){
  const response = await fetch(path, options);
  if(!response.ok){let detail='Ошибка';try{detail=(await response.json()).detail||detail}catch{}throw new Error(detail)}
  return response.json();
}

async function refreshHealth(){
  const data = await api('/api/health');
  lastHealth=data;
  const ttsOk = data.tts.some(x=>x.ok);
  const voiceWarnings=data.voice?.assessment?.warnings||[];
  const voiceDetail = (data.voice.detail || (data.voice.ok ? 'Голос готов' : 'Нужна настройка голоса'))
    + (voiceWarnings.length?` · Важно: ${voiceWarnings[0]}`:'');
  const items = [
    ['Сценарист', data.script.ok, data.script.detail],
    ['Озвучка', ttsOk, data.tts.map(x=>x.detail).join(' · ')],
    ['Ударения', data.pronunciation?.ok, data.pronunciation?.detail || 'Словарь произношения'],
    ['Ваш голос', data.voice.ok, voiceDetail],
    ['Допуск готовой записи', data.voice_quality?.approved, data.voice_quality?.detail || 'Нужен тест голоса']
  ];
  $('healthCards').innerHTML = items.map(([title,ok,detail])=>`<div class="status ${ok?'ok':'bad'}"><strong>${ok?'●':'○'} ${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div>`).join('');
  return data;
}

function updateMode(){
  const mode = $('contentMode').value;
  const ownText = mode === 'provided_text';
  $('aiPanel').classList.toggle('hidden', ownText);
  $('textPanel').classList.toggle('hidden', !ownText);
  $('contentModeHint').textContent = mode === 'ai_fast'
    ? 'Один проход локальной модели. На старом процессоре это всё равно может занять минуты; облачный ИИ обычно пишет за секунды.'
    : mode === 'ai_quality'
      ? 'План и отдельная редактура. Качественнее, но локально примерно вдвое дольше.'
      : 'ИИ не запускается: программа сразу переходит к озвучке вашего текста.';
  updateTextEstimate();
}

function refreshDurationHint(){
  const minutes = Number($('duration').value);
  $('durationHint').textContent = minutes === 1
    ? 'Тест конвейера. Голос не замедляется обработкой; длительность создают текст и паузы.'
    : 'Студийный профиль оставляет примерно треть времени на осмысленные паузы и работающий фон.';
  updateTextEstimate();
}

function wordRange(target){
  return target === 1 ? [70,90] : [target*45,target*55];
}

function updateTextEstimate(){
  if($('contentMode').value !== 'provided_text') return;
  const text = $('sourceText').value.trim();
  const words = (text.match(/[A-Za-zА-Яа-яЁё0-9'-]+/g) || []).length;
  const target = Number($('duration').value);
  const [lower,upper] = wordRange(target);
  const roughMinutes = words ? (words / 50) : 0;
  $('textEstimate').textContent = words
    ? `Сейчас: ${words} слов. По студийному эталону это около ${roughMinutes.toFixed(1)} мин вместе с паузами. Для ${target} мин ориентир: ${lower}–${upper} слов.`
    : `Для ${target} минут по студийному эталону обычно нужно примерно ${lower}–${upper} слов.`;
}

$('contentMode').addEventListener('change', updateMode);
$('duration').addEventListener('change', refreshDurationHint);
$('sourceText').addEventListener('input',()=>{
  updateTextEstimate();
  if(!$('stressPreviewWrap').classList.contains('hidden')){
    $('stressPreviewWrap').classList.add('hidden');
    $('stressPreviewStatus').classList.add('hidden');
    lastAutomaticStressText='';
  }
});
$('musicLevel').addEventListener('input',()=>{$('musicLevelValue').textContent=$('musicLevel').value});
$('atmosphereLevel').addEventListener('input',()=>{$('atmosphereLevelValue').textContent=$('atmosphereLevel').value});
$('expressiveness').addEventListener('input',()=>{$('expressivenessValue').textContent=$('expressiveness').value});

function assetOption(asset){return `<option value="${escapeHtml(asset.id)}">${escapeHtml(asset.title)} · ${Math.round(asset.duration_seconds)} с · ${escapeHtml(asset.category)}</option>`}
function renderAssetSelectors(){
  const music=$('musicAsset'), atmosphere=$('atmosphereAsset');
  music.innerHTML=audioAssets.music.length?audioAssets.music.map(assetOption).join(''):'<option value="">Нет загруженной лицензированной музыки</option>';
  atmosphere.innerHTML=audioAssets.atmosphere.length?audioAssets.atmosphere.map(assetOption).join(''):'<option value="">Нет загруженных атмосферных дорожек</option>';
}
async function loadAudioAssets(){
  const result=await api('/api/audio-assets');
  audioAssets={music:result.assets.filter(x=>x.kind==='music'),atmosphere:result.assets.filter(x=>x.kind==='atmosphere'),event:result.assets.filter(x=>x.kind==='event')};
  renderAssetSelectors();renderAssetList();
}
function updateSoundMode(){
  const musicMode=$('musicMode').value, atmosphereMode=$('atmosphereMode').value;
  $('musicAsset').classList.toggle('hidden',musicMode!=='library');
  $('technicalMusicStyle').classList.toggle('hidden',musicMode!=='technical_draft');
  $('atmosphereAsset').classList.toggle('hidden',atmosphereMode!=='library');
  $('technicalAtmosphereStyle').classList.toggle('hidden',atmosphereMode!=='technical_draft');
}
$('musicMode').addEventListener('change',updateSoundMode);
$('atmosphereMode').addEventListener('change',updateSoundMode);
updateMode();refreshDurationHint();updateSoundMode();
loadAudioAssets().catch(()=>{});

$('importTextButton').addEventListener('click',async()=>{
  const file=$('sourceFile').files[0];
  if(!file){$('sourceFile').click();return}
  const form=new FormData();form.append('file',file);
  $('importTextButton').disabled=true;$('importTextButton').textContent='Читаю файл…';
  try{
    const result=await api('/api/text/import',{method:'POST',body:form});
    $('sourceText').value=result.text;updateTextEstimate();
    $('importTextButton').textContent=`Загружено: ${result.word_count} слов`;
  }catch(error){$('importTextButton').textContent=error.message}
  finally{setTimeout(()=>{$('importTextButton').disabled=false;$('importTextButton').textContent='Загрузить TXT/DOCX'},1800)}
});


function dictionaryToText(entries){
  return Object.entries(entries||{}).sort((a,b)=>a[0].localeCompare(b[0],'ru')).map(([word,accented])=>`${word}=${accented}`).join('\n');
}

function textToDictionary(value){
  const entries={};
  for(const [index,raw] of value.split(/\r?\n/).entries()){
    const line=raw.trim();if(!line||line.startsWith('#'))continue;
    const pos=line.indexOf('=');if(pos<1)throw new Error(`Строка ${index+1}: нужен формат слово=сло́во`);
    entries[line.slice(0,pos).trim()]=line.slice(pos+1).trim();
  }
  return entries;
}


function stripWordStress(value){
  return String(value||'').normalize('NFD').replace(/\u0301/g,'').normalize('NFC');
}

function hasStress(value){
  return String(value||'').normalize('NFD').includes('\u0301');
}

function russianWords(value){
  return String(value||'').normalize('NFC').match(/[А-Яа-яЁё\u0301-]+/gu)||[];
}

function wordBoundsAt(text, position){
  const allowed=/[А-Яа-яЁё\u0301-]/u;
  let start=Math.max(0,Math.min(position,text.length));
  let end=start;
  while(start>0&&allowed.test(text[start-1]))start-=1;
  while(end<text.length&&allowed.test(text[end]))end+=1;
  return [start,end];
}

function editCurrentWordStress(removeOnly=false){
  const editor=$('stressPreviewEditor');
  const text=editor.value;
  const caret=editor.selectionStart;
  const [start,end]=wordBoundsAt(text,caret);
  if(start===end){
    $('stressEditMessage').textContent='Поставьте курсор внутри нужного слова.';
    editor.focus();
    return;
  }
  const rawWord=text.slice(start,end);
  const beforeCaret=rawWord.slice(0,Math.max(0,caret-start));
  const removedBefore=(beforeCaret.match(/\u0301/g)||[]).length;
  const plainWord=rawWord.replace(/\u0301/g,'');
  const plainCaret=Math.max(0,Math.min(plainWord.length,caret-start-removedBefore));
  if(removeOnly){
    editor.setRangeText(plainWord,start,end,'end');
    $('stressEditMessage').textContent=`Ударение в слове «${plainWord}» убрано.`;
    editor.focus();
    return;
  }
  const vowels='аеёиоуыэюяАЕЁИОУЫЭЮЯ';
  let vowelIndex=-1;
  if(plainCaret>0&&vowels.includes(plainWord[plainCaret-1]))vowelIndex=plainCaret-1;
  else if(plainCaret<plainWord.length&&vowels.includes(plainWord[plainCaret]))vowelIndex=plainCaret;
  else{
    for(let distance=1;distance<=plainWord.length;distance+=1){
      const left=plainCaret-distance;
      const right=plainCaret+distance-1;
      if(left>=0&&vowels.includes(plainWord[left])){vowelIndex=left;break}
      if(right<plainWord.length&&vowels.includes(plainWord[right])){vowelIndex=right;break}
    }
  }
  if(vowelIndex<0){
    $('stressEditMessage').textContent='В выбранном слове не найдена гласная.';
    editor.focus();
    return;
  }
  const vowel=plainWord[vowelIndex];
  const corrected=(vowel==='ё'||vowel==='Ё')
    ? plainWord
    : `${plainWord.slice(0,vowelIndex+1)}\u0301${plainWord.slice(vowelIndex+1)}`.normalize('NFC');
  editor.setRangeText(corrected,start,end,'end');
  editor.setSelectionRange(start+vowelIndex+2,start+vowelIndex+2);
  $('stressEditMessage').textContent=`Поставлено вручную: ${corrected}`;
  editor.focus();
}

function collectDictionaryCorrections(automaticText,editedText){
  const automaticWords=russianWords(automaticText);
  const editedWords=russianWords(editedText);
  if(automaticWords.length!==editedWords.length){
    throw new Error('Для сохранения в словарь меняйте только ударения, не добавляя и не удаляя слова. Сам исправленный текст применить можно.');
  }
  const entries={};
  for(let index=0;index<editedWords.length;index+=1){
    const automatic=automaticWords[index].normalize('NFC');
    const edited=editedWords[index].normalize('NFC');
    const plainAutomatic=stripWordStress(automatic).toLocaleLowerCase('ru-RU');
    const plainEdited=stripWordStress(edited).toLocaleLowerCase('ru-RU');
    if(plainAutomatic!==plainEdited){
      throw new Error(`Изменено само слово «${automatic}». В словарь можно сохранять только исправление ударения.`);
    }
    if(automatic!==edited&&hasStress(edited)){
      entries[plainEdited]=edited.toLocaleLowerCase('ru-RU');
    }
  }
  return entries;
}

function applyEditedStressText(){
  const edited=$('stressPreviewEditor').value.trim();
  if(!edited)return false;
  $('sourceText').value=edited;
  updateTextEstimate();
  $('stressEditMessage').textContent='Исправленный текст применён. Ручные ударения защищены и будут переданы в озвучку.';
  return true;
}

async function loadPronunciation(){
  try{
    const data=await api('/api/pronunciation');
    $('pronunciationDictionary').value=dictionaryToText(data.dictionary);
    $('pronunciationMessage').textContent=data.detail;
  }catch(error){$('pronunciationMessage').textContent=error.message}
}

$('settingsButton').addEventListener('click',async()=>{$('settingsDialog').showModal();await loadPronunciation()});
$('savePronunciation').addEventListener('click',async()=>{
  $('savePronunciation').disabled=true;
  try{
    const entries=textToDictionary($('pronunciationDictionary').value);
    const result=await api('/api/pronunciation/dictionary',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({entries})});
    $('pronunciationMessage').textContent=`Сохранено исправлений: ${result.count}`;
    await refreshHealth();
  }catch(error){$('pronunciationMessage').innerHTML=`<span class="error">${escapeHtml(error.message)}</span>`}
  finally{$('savePronunciation').disabled=false}
});

$('previewStressButton').addEventListener('click',async()=>{
  const text=$('sourceText').value.trim();
  if(!text){$('sourceText').focus();return}
  const status=$('stressPreviewStatus');
  $('previewStressButton').disabled=true;
  $('previewStressButton').textContent='Расставляю ударения…';
  status.className='stress-preview-status';
  status.textContent='Проверяю русский текст и контекст омографов…';
  status.classList.remove('hidden');
  try{
    const result=await api('/api/pronunciation/preview',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text})});
    lastAutomaticStressText=result.tts_text;
    $('stressPreviewEditor').value=result.tts_text;
    $('stressEditMessage').textContent='Текст можно исправлять вручную.';
    $('stressPreviewWrap').classList.remove('hidden');
    const engine=result.engine==='silero_stress'?'Silero Stress':'только словарь произношения';
    const parts=[`Добавлено ударений: ${result.accents_added}`,`восстановлено «ё»: ${result.yo_added}`,`исправлений словаря: ${result.dictionary_hits}`,`движок: ${engine}`];
    status.textContent=parts.join(' · ')+(result.warning?` · ${result.warning}`:'');
    const incomplete=result.engine!=='silero_stress'||Boolean(result.warning)||result.accents_added===0;
    status.className=`stress-preview-status${incomplete?' warning':''}`;
    $('previewStressButton').textContent='Проверить снова';
  }catch(error){
    $('stressPreviewWrap').classList.add('hidden');
    status.className='stress-preview-status error';
    status.textContent=`Проверка не выполнена: ${error.message}`;
    $('previewStressButton').textContent='Повторить проверку';
  }finally{
    $('previewStressButton').disabled=false;
  }
});


$('insertStressMark').addEventListener('click',()=>editCurrentWordStress(false));
$('removeWordStress').addEventListener('click',()=>editCurrentWordStress(true));
$('resetStressEdits').addEventListener('click',()=>{
  $('stressPreviewEditor').value=lastAutomaticStressText;
  $('stressEditMessage').textContent='Автоматический вариант восстановлен.';
  $('stressPreviewEditor').focus();
});
$('applyStressEdits').addEventListener('click',()=>applyEditedStressText());
$('saveStressCorrections').addEventListener('click',async()=>{
  const message=$('stressEditMessage');
  $('saveStressCorrections').disabled=true;
  try{
    const corrections=collectDictionaryCorrections(lastAutomaticStressText,$('stressPreviewEditor').value);
    const count=Object.keys(corrections).length;
    if(!count){throw new Error('Нет изменённых ударений для сохранения в словарь.')}
    const current=await api('/api/pronunciation');
    const entries={...(current.dictionary||{}),...corrections};
    const result=await api('/api/pronunciation/dictionary',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({entries})});
    applyEditedStressText();
    lastAutomaticStressText=$('stressPreviewEditor').value;
    message.className='stress-edit-message';
    message.textContent=`Сохранено новых исправлений: ${count}. Всего в личном словаре: ${result.count}.`;
  }catch(error){
    message.className='stress-edit-message error';
    message.textContent=error.message;
  }finally{$('saveStressCorrections').disabled=false}
});
$('stressPreviewEditor').addEventListener('input',()=>{
  $('stressEditMessage').className='stress-edit-message';
  $('stressEditMessage').textContent='Есть ручные изменения. Нажмите «Использовать исправленный текст».';
});


function licenseLabel(value){return ({owned_exclusive:'собственная',commissioned_with_rights:'заказ с правами',licensed_commercial:'коммерческая лицензия',public_domain_cc0:'CC0 / public domain',pixabay_content_license:'Pixabay Content License'})[value]||value}
function renderAssetList(){
  const items=[...audioAssets.music,...audioAssets.atmosphere,...audioAssets.event];
  $('soundAssetList').innerHTML=items.length?items.map(asset=>{const kind=asset.kind==='music'?'Музыка':asset.kind==='atmosphere'?'Атмосфера':'Событие';const safety=asset.safe_for_trance&&asset.content_reviewed?'· допущено в авторежим':'· только вручную';return `<div class="asset-row"><div><strong>${escapeHtml(asset.title)}</strong><span>${kind} · ${escapeHtml(asset.category)} · ${escapeHtml(licenseLabel(asset.license_basis))} · ${Math.round(asset.duration_seconds)} с ${safety}</span></div><button class="ghost delete-asset" type="button" data-id="${escapeHtml(asset.id)}">Удалить</button></div>`}).join(''):'<p class="field-note">Библиотека пока пуста. Автоматический режиссёр не скачивает чужие звуки из интернета.</p>';
  document.querySelectorAll('.delete-asset').forEach(button=>button.addEventListener('click',async()=>{
    if(!confirm('Удалить дорожку из локальной библиотеки?'))return;
    try{await api(`/api/audio-assets/${button.dataset.id}`,{method:'DELETE'});await loadAudioAssets()}catch(error){$('soundAssetMessage').textContent=error.message}
  }));
}
$('soundLibraryButton').addEventListener('click',async()=>{openDialog($('soundLibraryDialog'));await loadAudioAssets()});

$('assetKind').addEventListener('change',()=>{
  const kind=$('assetKind').value;
  $('assetRecommendedDb').value=kind==='music'?-30:kind==='atmosphere'?-34:-41;
});
$('soundAssetForm').addEventListener('submit',async(event)=>{
  if(event.submitter?.classList.contains('close')){event.preventDefault();closeDialog($('soundLibraryDialog'));return}
  event.preventDefault();
  const file=$('assetFile').files[0];
  if(!file){$('soundAssetMessage').textContent='Выберите аудиофайл';return}
  if(!$('assetRightsConfirmed').checked){$('soundAssetMessage').textContent='Нужно подтвердить право использования';return}
  const form=new FormData();
  form.append('file',file);form.append('title',$('assetTitle').value.trim());form.append('category',$('assetCategory').value);form.append('license_basis',$('assetLicense').value);form.append('source_note',$('assetSourceNote').value.trim());form.append('rights_confirmed','true');form.append('tags',$('assetTags').value.trim());form.append('safe_for_trance',$('assetSafeForTrance').checked?'true':'false');form.append('content_reviewed',$('assetContentReviewed').checked?'true':'false');form.append('recommended_volume_db',$('assetRecommendedDb').value);form.append('license_evidence',$('assetEvidence').value.trim());
  $('saveSoundAsset').disabled=true;$('soundAssetMessage').textContent='Проверяю и нормализую дорожку…';
  try{const result=await api(`/api/audio-assets/${$('assetKind').value}`,{method:'POST',body:form});$('soundAssetMessage').textContent=`Добавлено: ${result.asset.title}`;$('assetFile').value='';$('assetTitle').value='';$('assetTags').value='';$('assetEvidence').value='';$('assetSafeForTrance').checked=false;$('assetContentReviewed').checked=false;await loadAudioAssets();}
  catch(error){$('soundAssetMessage').innerHTML=`<span class="error">${escapeHtml(error.message)}</span>`}
  finally{$('saveSoundAsset').disabled=false}
});

function syncStudioStyleFamilyVisibility(){
  const field=$('studioStyleFamilyField');
  if(!field)return;
  field.classList.toggle('hidden',$('performanceProfile').value!=='studio_melodic');
}
$('performanceProfile').addEventListener('change',syncStudioStyleFamilyVisibility);
syncStudioStyleFamilyVisibility();

$('voiceForm').addEventListener('submit',async(event)=>{
  if(event.submitter?.classList.contains('close')){event.preventDefault();closeDialog($('settingsDialog'));return}
  event.preventDefault();
  const file=$('voiceFile').files[0];
  const transcript=$('transcript').value.trim();
  if(!file){$('voiceMessage').textContent='Выберите аудиофайл';return}
  if(transcript.length<40){$('voiceMessage').textContent='Нужна дословная расшифровка выбранного фрагмента';$('transcript').focus();return}
  const form=new FormData();form.append('audio',file);form.append('transcript',transcript);
  $('saveVoice').disabled=true;$('voiceMessage').textContent='Проверяю и подготавливаю образец…';
  try{
    const result=await api('/api/voice',{method:'POST',body:form});
    $('voiceMessage').textContent=`Голос сохранён: ${result.duration_seconds} с, моно 24 кГц`;
    await refreshHealth();setTimeout(()=>$('settingsDialog').close(),900)
  }
  catch(error){$('voiceMessage').innerHTML=`<span class="error">${escapeHtml(error.message)}</span>`}
  finally{$('saveVoice').disabled=false}
});

function collectPayload(workflowMode='production'){
  const mode=$('contentMode').value;
  return {
    goal:$('goal').value.trim(),
    duration_minutes:workflowMode==='voice_test'?1:Number($('duration').value),
    address_form:$('address').value,
    style:$('style').value,
    ending_state:$('ending').value.trim(),
    extra_notes:$('notes').value.trim(),
    tts_provider:$('ttsProvider').value,
    content_mode:mode,
    source_text:$('sourceText').value.trim(),
    workflow_mode:workflowMode,
    duration_mode:$('durationMode').value,
    pacing_profile:$('pacingProfile').value,
    performance_profile:$('performanceProfile').value,
    studio_style_family:$('studioStyleFamily').value,
    expressiveness:Number($('expressiveness').value),
    music_mode:workflowMode==='voice_test'?'none':$('musicMode').value,
    music_asset_id:workflowMode==='production'&&$('musicMode').value==='library'?$('musicAsset').value:null,
    atmosphere_mode:workflowMode==='voice_test'?'none':$('atmosphereMode').value,
    atmosphere_asset_id:workflowMode==='production'&&$('atmosphereMode').value==='library'?$('atmosphereAsset').value:null,
    music_level:Number($('musicLevel').value),
    atmosphere_level:Number($('atmosphereLevel').value),
    audio_mix_profile:$('audioMixProfile').value,
    sound_design_mode:workflowMode==='voice_test'?'none':$('soundDesignMode').value,
    music_style:$('technicalMusicStyle').value,
    nature_sound:$('technicalAtmosphereStyle').value
  };
}

async function beginJob(payload){
  $('createButton').disabled=true;
  $('voiceTestButton').disabled=true;
  $('resultCard').classList.add('hidden');
  $('progressCard').classList.remove('hidden');
  try{
    const job=await api('/api/jobs',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(payload)
    });
    currentJob=job.id;
    renderJob(job);
    pollTimer=setInterval(pollJob,1800);
  }catch(error){
    $('jobMessage').innerHTML=`<span class="error">${escapeHtml(error.message)}</span>`;
    $('createButton').disabled=false;
    $('voiceTestButton').disabled=false;
  }
}

$('voiceTestButton').addEventListener('click',async()=>{
  const health=await refreshHealth();
  if(!health.voice.ok){
    openDialog($('settingsDialog'));
    $('voiceMessage').textContent='Сохраните чистый образец и его точную расшифровку';
    return;
  }
  const payload=collectPayload('voice_test');
  $('jobMessage').textContent='Создаю несколько слепых коротких кандидатов. Студийные записи с музыкой не используются как голосовые prompts.';
  await beginJob(payload);
});

$('createButton').addEventListener('click',async()=>{
  const health=await refreshHealth();
  if(!health.voice.ok){
    openDialog($('settingsDialog'));
    $('voiceMessage').textContent='Сохраните образец и его точную расшифровку';
    return;
  }
  const mode=$('contentMode').value;
  if(mode==='provided_text'&&!$('stressPreviewWrap').classList.contains('hidden')){
    const edited=$('stressPreviewEditor').value.trim();
    if(edited&&edited!==$('sourceText').value.trim()){
      $('sourceText').value=edited;
      updateTextEstimate();
      $('stressEditMessage').textContent='Ручные исправления автоматически применены перед созданием.';
    }
  }
  if(mode!=='provided_text' && !health.script.ok){
    $('jobMessage').innerHTML='<span class="error">Локальный сценарист не готов. Выберите «Мой готовый текст — без ИИ» или установите модель.</span>';
    $('progressCard').classList.remove('hidden');
    return;
  }
  const payload=collectPayload('production');
  if(!health.voice_quality?.approved){
    $('progressCard').classList.remove('hidden');
    $('jobMessage').innerHTML='<span class="error">Создание транса заблокировано. Сначала нажмите «Слепой тест голоса — 30–45 секунд», прослушайте кандидатов и выберите один.</span>';
    $('voiceTestButton').focus();
    return;
  }
  if(mode==='provided_text' && payload.source_text.length<20){$('sourceText').focus();return}
  if(payload.music_mode==='library'&&!payload.music_asset_id){openDialog($('soundLibraryDialog'));$('soundAssetMessage').textContent='Сначала добавьте или выберите музыкальную дорожку';return}
  if(payload.atmosphere_mode==='library'&&!payload.atmosphere_asset_id){openDialog($('soundLibraryDialog'));$('soundAssetMessage').textContent='Сначала добавьте или выберите атмосферную дорожку';return}
  if(mode!=='provided_text' && payload.goal.length<3){$('goal').focus();return}
  await beginJob(payload);
});

function candidateMetricsHtml(metrics={}){
  const technical=metrics.structural_ok?'<span class="ok">Техническая целостность пройдена</span>':'<span class="bad">Техническая целостность не пройдена</span>';
  const duration=Number(metrics.duration_seconds||0).toFixed(1);
  const peak=Number(metrics.peak_dbfs||0).toFixed(1);
  const silence=Math.round(Number(metrics.silence_fraction||0)*100);
  const wpm=Number(metrics.overall_words_per_minute||0).toFixed(0);
  const warnings=(metrics.warnings||[]).map(item=>`<span class="warning">${escapeHtml(item)}</span>`).join('');
  const failures=(metrics.failures||[]).map(item=>`<span class="bad">${escapeHtml(item)}</span>`).join('');
  return `<div class="voice-metrics">${technical}<span>Длительность: ${duration} с</span><span>Расчётный общий темп: ${wpm} слов/мин</span><span>Пик: ${peak} dBFS</span><span>Полная тишина: ${silence}%</span>${warnings}${failures}<span>Живость и сходство автоматически не объявляются — слушаете вы.</span></div>`;
}

function ratingSelect(name,label){
  return `<label>${escapeHtml(label)}<select data-rating="${name}"><option value="">—</option><option value="1">1 — плохо</option><option value="2">2</option><option value="3">3</option><option value="4">4 — годится</option><option value="5">5 — отлично</option></select></label>`;
}

function allReadyCandidatesListened(){
  return voiceLabState.readyIds.every(id=>voiceLabState.listened.has(id));
}

function refreshVoiceLabButtons(){
  const allListened=allReadyCandidatesListened();
  document.querySelectorAll('.approve-voice').forEach(button=>{button.disabled=!allListened||button.dataset.structural!=='true'});
  const reject=$('rejectAllVoice');
  if(reject) reject.disabled=!allListened;
  const status=$('voiceListenStatus');
  if(status){
    status.textContent=allListened
      ? 'Все готовые варианты прослушаны. Теперь можно оценить лучший или честно отклонить все.'
      : `Прослушано: ${voiceLabState.listened.size} из ${voiceLabState.readyIds.length}.`;
  }
}

function collectCandidateRatings(card){
  const values={};
  card.querySelectorAll('[data-rating]').forEach(select=>{values[select.dataset.rating]=Number(select.value||0)});
  return values;
}

function renderVoiceCandidates(job){
  const candidates=job.metadata?.voice_candidates||[];
  const ready=candidates.filter(candidate=>candidate.status==='ready');
  voiceLabState={jobId:job.id,readyIds:ready.map(item=>item.id),listened:new Set()};
  $('resultTitle').textContent='Лаборатория живого голоса';
  $('productionResult').classList.add('hidden');
  $('voiceLabResults').classList.remove('hidden');
  const cards=candidates.map(candidate=>{
    const label=candidate.blind_label||'Вариант';
    if(candidate.status!=='ready'){
      return `<article class="voice-candidate failed"><h3>${escapeHtml(label)}</h3><p>${escapeHtml(candidate.error||'Кандидат не создан')}</p></article>`;
    }
    const rawSrc=`/api/jobs/${job.id}/candidate/${encodeURIComponent(candidate.id)}/raw`;
    const masteredSrc=`/api/jobs/${job.id}/candidate/${encodeURIComponent(candidate.id)}/mp3`;
    return `<article class="voice-candidate" data-candidate="${escapeHtml(candidate.id)}">
      <h3>${escapeHtml(label)}</h3>
      <p>Слепой вариант: название движка откроется только после решения.</p>
      <strong class="audio-label">Честный WAV без мастеринга</strong>
      <audio class="candidate-audio raw-audio" controls preload="metadata" src="${rawSrc}" data-candidate="${escapeHtml(candidate.id)}"></audio>
      <details><summary>Сравнить обработанную версию</summary><audio controls preload="none" src="${masteredSrc}"></audio></details>
      <span class="listen-badge" data-listen-badge="${escapeHtml(candidate.id)}">Не прослушан</span>
      ${candidateMetricsHtml(candidate.metrics)}
      <div class="voice-ratings">
        ${ratingSelect('identity','Похожесть на меня')}
        ${ratingSelect('naturalness','Живость')}
        ${ratingSelect('articulation','Артикуляция')}
        ${ratingSelect('continuity','Целостность фраз')}
      </div>
      <button class="primary approve-voice" type="button" data-job="${escapeHtml(job.id)}" data-candidate="${escapeHtml(candidate.id)}" data-structural="${candidate.metrics?.structural_ok?'true':'false'}" disabled>Этот вариант действительно годится</button>
    </article>`;
  }).join('');
  $('voiceLabResults').innerHTML=`
    <p class="voice-lab-intro">Сначала освежите слух настоящим образцом, затем прослушайте каждый вариант минимум на две трети. Оценивайте не красоту, а свою личность, живость переходов и отсутствие цифровой маски.</p>
    <div class="voice-reference-anchor"><strong>Ваш настоящий образец</strong><audio controls preload="metadata" src="/api/voice/reference"></audio></div>
    <p id="voiceListenStatus" class="voice-listen-status"></p>
    <div class="voice-candidates">${cards}</div>
    <div class="voice-reject-box"><label for="voiceLabNotes">Что именно звучит плохо</label><textarea id="voiceLabNotes" rows="3" placeholder="Например: чужая артикуляция, цифровая маска, меняется личность, неживые окончания..."></textarea><button id="rejectAllVoice" class="ghost" type="button" disabled>Ни один вариант не годится</button></div>
    <p class="voice-approval-note">Допуск возможен только при оценках 4–5 по всем четырём критериям. Выбор «наименее плохого» длинную генерацию не откроет.</p>`;

  $('voiceLabResults').querySelectorAll('.raw-audio').forEach(audio=>{
    audio.addEventListener('timeupdate',()=>{
      if(!Number.isFinite(audio.duration)||audio.duration<=0)return;
      const enough=audio.currentTime>=Math.min(audio.duration*0.67,Math.max(12,audio.duration-2));
      if(!enough)return;
      const id=audio.dataset.candidate;
      voiceLabState.listened.add(id);
      const badge=document.querySelector(`[data-listen-badge="${CSS.escape(id)}"]`);
      if(badge){badge.textContent='Прослушан';badge.classList.add('ok')}
      refreshVoiceLabButtons();
    });
    audio.addEventListener('ended',()=>{
      const id=audio.dataset.candidate;
      voiceLabState.listened.add(id);
      const badge=document.querySelector(`[data-listen-badge="${CSS.escape(id)}"]`);
      if(badge){badge.textContent='Прослушан';badge.classList.add('ok')}
      refreshVoiceLabButtons();
    });
  });

  $('voiceLabResults').querySelectorAll('.approve-voice').forEach(button=>{
    button.addEventListener('click',async()=>{
      const card=button.closest('.voice-candidate');
      const ratings=collectCandidateRatings(card);
      if(Object.values(ratings).some(value=>value<4)){
        $('jobMessage').innerHTML='<span class="error">Для допуска нужны оценки 4 или 5 по всем четырём критериям. Плохой результат не выбирайте — отклоните все.</span>';
        return;
      }
      button.disabled=true;
      try{
        const result=await api('/api/voice/quality/approve',{
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify({
            job_id:button.dataset.job,
            candidate_id:button.dataset.candidate,
            ratings,
            listened_candidate_ids:[...voiceLabState.listened],
            confirm_all_listened:true,
            notes:$('voiceLabNotes')?.value||''
          })
        });
        $('voiceLabResults').querySelectorAll('.voice-candidate').forEach(item=>item.classList.remove('voice-approved'));
        card.classList.add('voice-approved');
        button.textContent=`Одобрен: ${result.approval.candidate_title}`;
        $('jobMessage').textContent='Допуск сохранён и привязан к голосу, тексту образца, версиям моделей и конкретному аудиофайлу кандидата.';
        await refreshHealth();
      }catch(error){
        $('jobMessage').innerHTML=`<span class="error">${escapeHtml(error.message)}</span>`;
        refreshVoiceLabButtons();
      }
    });
  });

  $('rejectAllVoice').addEventListener('click',async()=>{
    try{
      await api('/api/voice/quality/reject',{
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body:JSON.stringify({job_id:job.id,listened_candidate_ids:[...voiceLabState.listened],confirm_all_listened:true,notes:$('voiceLabNotes').value})
      });
      $('jobMessage').innerHTML='<span class="warning">Все варианты отклонены. Длинная генерация остаётся заблокированной; отзыв сохранён для следующего голосового ядра.</span>';
      await refreshHealth();
    }catch(error){$('jobMessage').innerHTML=`<span class="error">${escapeHtml(error.message)}</span>`}
  });
  refreshVoiceLabButtons();
}

function renderJob(job){
  $('stage').textContent=job.stage;
  $('progressText').textContent=`${job.progress}%`;
  $('progressBar').style.width=`${job.progress}%`;
  $('jobMessage').textContent=job.error||'';
  if(job.status==='completed'){
    clearInterval(pollTimer);
    $('createButton').disabled=false;
    $('voiceTestButton').disabled=false;
    $('resultCard').classList.remove('hidden');
    if(job.metadata?.workflow_mode==='voice_test'){
      renderVoiceCandidates(job);
    }else{
      $('resultTitle').textContent='Готовая запись';
      $('voiceLabResults').classList.add('hidden');
      $('productionResult').classList.remove('hidden');
      const base=`/api/jobs/${job.id}/download`;
      $('player').src=`${base}/mp3`;
      $('downloadMp3').href=`${base}/mp3`;
      $('downloadWav').href=`${base}/wav`;
      $('downloadOpus').href=`${base}/opus`;
      $('downloadScript').href=`${base}/script`;
      $('downloadTtsScript').href=`${base}/tts-script`;
      $('downloadPassport').href=`${base}/passport`;
      $('downloadSoundPlan').href=`${base}/sound-plan`;
      $('downloadPerformancePlan').href=`${base}/performance-plan`;
      $('downloadAudioSafety').href=`${base}/audio-safety`;
    }
    $('warnings').innerHTML=(job.warnings||[]).map(x=>`<p class="warning">${escapeHtml(x)}</p>`).join('');
  }
  if(job.status==='failed'||job.status==='cancelled'){
    clearInterval(pollTimer);
    $('createButton').disabled=false;
    $('voiceTestButton').disabled=false;
    $('jobMessage').innerHTML=`<span class="error">${escapeHtml(job.error||job.stage)}</span>`;
  }
}

async function pollJob(){if(!currentJob)return;try{renderJob(await api(`/api/jobs/${currentJob}`))}catch(error){$('jobMessage').textContent=error.message}}
refreshHealth().catch(error=>$('healthCards').innerHTML=`<p class="error">${escapeHtml(error.message)}</p>`);
