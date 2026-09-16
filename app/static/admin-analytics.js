(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const count = value => value == null ? '—' : Number(value).toLocaleString('ru-RU');
  const pct = value => value == null ? 'Нет данных' : count(value) + '%';
  let report = null, directory = [], version = 0, firstLoad = true, appliedParams = '';
  function element(tag, text, className) { const e = document.createElement(tag); if(text != null) e.textContent = text; if(className) e.className = className; return e; }
  function option(value, label) { const e = element('option', label); e.value = value; return e; }
  function lock() { $('content').hidden = true; $('locked').hidden = false; $('pageStatus').textContent = ''; }
  async function api(url, options = {}) {
    const res = await fetch(url, {cache:'no-store', ...options});
    const data = await res.json().catch(() => ({}));
    if (!res.ok) { if(res.status === 401 || res.status === 403) lock(); throw new Error(typeof data.detail === 'string' ? data.detail : 'Не удалось загрузить данные'); }
    return data;
  }
  function params() { const p = new URLSearchParams(); for (const id of ['start','end','source','category','entity']) if($(id).value) p.set(id,$(id).value); return p.toString(); }
  function setPeriod(days) { const end = new Date(); const start = new Date(end); start.setUTCDate(start.getUTCDate() - Number(days) + 1); $('start').value = start.toISOString().slice(0,10); $('end').value = end.toISOString().slice(0,10); }
  function entityOptions() {
    const current = $('entity').value; $('entity').replaceChildren(option('', 'Все организации'));
    for(const row of directory) if(!$('category').value || row.category === $('category').value) $('entity').append(option(row.key,row.name));
    if([...$('entity').options].some(o => o.value === current)) $('entity').value = current;
  }
  async function categories() {
    const data = await api('/v1/public/service-categories');
    const current = $('category').value; $('category').replaceChildren(option('', 'Все сферы'));
    $('categoryGroup').replaceChildren(); $('categoryList').replaceChildren();
    for(const [code,label] of Object.entries(data.groups)) $('categoryGroup').append(option(code,label));
    $('categoryGroup').value = 'OTHER';
    for(const item of data.items) { $('category').append(option(item.code,item.label)); $('categoryList').append(element('span',item.label,'tag' + (item.custom?' custom':''))); }
    if(current) $('category').value=current;
  }
  function barRow(name, value, max, label) {
    const row=element('div',null,'barRow'), p=element('p'); p.append(element('span',name),element('b',label));
    const bar=document.createElement('progress'); bar.max=max||1; bar.value=value||0; bar.setAttribute('aria-label',name+': '+label); row.append(p,bar); return row;
  }
  function svg(tag,attrs) { const e=document.createElementNS('http://www.w3.org/2000/svg',tag); for(const [k,v] of Object.entries(attrs)) e.setAttribute(k,String(v)); return e; }
  function trend(data) {
    $('trend').replaceChildren(); $('trendRows').replaceChildren();
    const max=Math.max(1,...data.flatMap(d=>[d.included,d.verified_visits||0]));
    for(const [field,color] of [['included','#8ae7c4'],['verified_visits','#b5a1ff']]) {
      if(field==='verified_visits'&&report.filters.source!=='verified') continue;
      const points=data.map((d,i)=>`${20+i*680/Math.max(1,data.length-1)},${155-130*(d[field]||0)/max}`).join(' ');
      $('trend').append(svg('polyline',{points,fill:'none',stroke:color,'stroke-width':3}));
    }
    const title=svg('title',{}); title.textContent=`Динамика за ${data.length} дней. Максимум: ${max}. Точные значения в таблице ниже.`; $('trend').prepend(title);
    for(const row of data) { const tr=element('tr'); for(const value of [row.date,count(row.included),count(row.verified_visits),pct(row.satisfied_percent)]) tr.append(element('td',value)); $('trendRows').append(tr); }
  }
  function render(data) {
    report=data; const s=data.summary;
    $('visits').textContent=count(s.verified_visits); $('respondents').textContent=count(s.respondents); $('ratings').textContent=count(s.included); $('satisfaction').textContent=pct(s.satisfied_percent);
    $('coverage').textContent=`Без аккаунта: ${s.anonymous}. На проверке или исключено: ${s.excluded}.`;
    $('periodLabel').textContent=`${data.period.start} — ${data.period.end} · UTC`;
    $('visitsLegend').hidden=data.filters.source!=='verified';
    $('satisfactionBar').replaceChildren(); $('satisfactionRows').replaceChildren(); let x=0;
    for(const [field,label,color] of [['satisfied','Довольны · 8–10','#8ae7c4'],['neutral','Нейтрально · 5–7','#ffd37a'],['dissatisfied','Недовольны · 1–4','#ff9eaa']]) {
      const width=s.included?400*s[field]/s.included:0;
      $('satisfactionBar').append(svg('rect',{x,y:0,width,height:32,fill:color})); x+=width;
      const p=element('p'); p.append(element('span',label),element('b',count(s[field]))); $('satisfactionRows').append(p);
    }
    $('sampleNote').textContent=!s.included?'За этот период пока нет учтённых оценок.':s.included<20?'Оценок пока мало: выводы предварительные.':'Доли описывают оценки в выбранной выборке.';
    trend(data.trend);
    $('sectors').replaceChildren(); const sectors=[...data.categories].sort((a,b)=>b.included-a.included);
    for(const row of sectors) $('sectors').append(barRow(row.label,row.included,Math.max(1,...sectors.map(x=>x.included)),count(row.included)));
    if(!sectors.length) $('sectors').append(element('p','За этот период данных пока нет.','muted'));
    $('dimensions').replaceChildren();
    for(const [key,label] of Object.entries({overall:'Общее впечатление',quality:'Качество услуги / продукта',service:'Обслуживание',cleanliness:'Чистота',value:'Цена и ценность'})) $('dimensions').append(barRow(label,s.dimensions[key],10,s.dimensions[key]==null?'Нет данных':count(s.dimensions[key])+' / 10'));
    $('organizations').replaceChildren(); $('organizationCount').textContent=`Организаций: ${data.organizations.length}`;
    for(const row of data.organizations) { const tr=element('tr'), name=element('td'), button=element('button',row.name); button.type='button'; button.addEventListener('click',()=>{$('entity').value=row.key;load();}); name.append(button,element('small',row.category_label)); tr.append(name); for(const value of [count(row.verified_visits),count(row.respondents),count(row.included),`${count(row.satisfied)} · ${pct(row.satisfied_percent)}`,count(row.neutral),count(row.dissatisfied)]) tr.append(element('td',value)); $('organizations').append(tr); }
    if(!data.organizations.length) { const tr=element('tr'), td=element('td','В этой категории пока нет организаций.'); td.colSpan=7;tr.append(td);$('organizations').append(tr); }
    $('methodology').replaceChildren(...['basis','respondents','visits','sources'].map(key=>element('p',data.methodology[key],'note')));
    $('analyze').disabled=!data.ai.configured||!s.included;
    $('aiText').textContent=''; $('aiStatus').textContent=!data.ai.configured?'ИИ-анализ пока не подключён. Статистика работает.':!s.included?'Для ИИ-анализа нужны оценки.':'ИИ объяснит показатели для выбранных фильтров.';
  }
  async function analyze() {
    const current=version; $('analyze').disabled=true; $('aiStatus').textContent='ИИ анализирует сводные показатели…';
    try { const data=await api('/v1/admin/analytics/insights?'+appliedParams,{method:'POST'}); if(current!==version) return; $('aiText').textContent=data.analysis; $('aiStatus').textContent=`${data.cached?'Сохранённый анализ':'Анализ готов'} · ${new Date(data.generated_at).toLocaleString('ru-RU')}`; }
    catch(error) { if(current===version) $('aiStatus').textContent=error.message; }
    finally { if(current===version) $('analyze').disabled=!report?.ai.configured||!report?.summary.included; }
  }
  async function load() {
    const current=++version; $('apply').disabled=true; $('error').textContent=''; $('pageStatus').textContent='Обновляем статистику…'; $('aiText').textContent=''; $('analyze').disabled=true;
    try { const query=params(); const data=await api('/v1/admin/analytics?'+query); if(current!==version) return; appliedParams=query; if(!directory.length||(!$('category').value&&!$('entity').value)) {directory=data.organizations;entityOptions();} render(data); $('content').hidden=false; $('locked').hidden=true; $('pageStatus').textContent='Данные обновлены · доступны только администратору'; if(firstLoad) {firstLoad=false;if(data.ai.configured&&data.summary.included) void analyze();} }
    catch(error) { if(current===version) {$('pageStatus').textContent='';$('error').textContent=error.message;if(!$('locked').hidden) $('pageStatus').textContent=error.message;else $('content').hidden=false;} }
    finally {if(current===version) $('apply').disabled=false;}
  }
  $('filters').addEventListener('submit',event=>{event.preventDefault();load();});
  $('period').addEventListener('change',()=>{if($('period').value!=='custom')setPeriod($('period').value);});
  for(const id of ['start','end']) $(id).addEventListener('change',()=>{$('period').value='custom';});
  $('category').addEventListener('change',()=>{$('entity').value='';entityOptions();});
  $('analyze').addEventListener('click',analyze);
  $('categoryForm').addEventListener('submit',async event=>{event.preventDefault();$('saveCategory').disabled=true;$('categoryStatus').textContent='';try{const data=await api('/v1/admin/service-categories',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:$('categoryName').value.trim(),group:$('categoryGroup').value})});await categories();$('categoryName').value='';$('categoryStatus').textContent=`Категория «${data.label}» добавлена и доступна на сайте.`;}catch(error){$('categoryStatus').textContent=error.message;}finally{$('saveCategory').disabled=false;}});
  setPeriod(30);
  (async()=>{try{await categories();await load();}catch(error){$('pageStatus').textContent=error.message;}})();
})();
