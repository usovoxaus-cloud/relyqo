const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs'),vm=require('node:vm'),acorn=require('acorn');
const {parseHTML}=require('linkedom');
const read=name=>fs.readFileSync('app/static/'+name,'utf8');
const dictionary=JSON.parse(read('i18n-uz.json'));
const settle=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};

async function setup({html='<!doctype html><html><head><title>Профиль</title></head><body></body></html>',query='?lang=uz',saved=null,cookie='',blocked=false,failed=false}={}) {
  const {document,window}=parseHTML(html), storage=new Map(saved?[['relyqo_language',saved]]:[]),requests=[],navigations=[];
  Object.defineProperty(document,'cookie',{configurable:true,writable:true,value:cookie});
  Object.defineProperty(window.HTMLSelectElement.prototype,'value',{configurable:true,get(){return [...this.options].find(o=>o.hasAttribute('selected'))?.value||this.options[0]?.value||''},set(v){for(const o of this.options)o.removeAttribute('selected');[...this.options].find(o=>o.value===v)?.setAttribute('selected','');}});
  const location={search:query,href:'https://relyqo.test/me'+query+'#account',protocol:'https:',assign:url=>navigations.push(url),replace:url=>navigations.push(url)};
  const localStorage={getItem:key=>{if(blocked)throw Error('unavailable');return storage.get(key)||null;},setItem:(key,value)=>{if(blocked)throw Error('unavailable');storage.set(key,value);}};
  const context={document,window,location,localStorage,navigator:{language:'ru-RU'},URL,URLSearchParams,AbortController,setTimeout,clearTimeout,MutationObserver:window.MutationObserver,
    fetch:async(url,options)=>{requests.push({url,options});if(url==='/v1/auth/language')return new Promise(()=>{});return{ok:!failed,json:async()=>dictionary};}};
  vm.runInNewContext(read('i18n.js'),context);
  await window.relyqoLanguageReady;await settle();
  return{document,window,storage,requests,navigations,context};
}

test('a language URL persists across navigation, reload and switching back to Russian',async()=>{
  const first=await setup({saved:'ru'});
  assert.equal(first.document.documentElement.lang,'uz');assert.equal(first.storage.get('relyqo_language'),'uz');
  assert.match(first.document.cookie,/relyqo_language=uz/);assert.match(first.document.cookie,/Max-Age=31536000/);
  const second=await setup({query:'',saved:first.storage.get('relyqo_language')});
  assert.equal(second.document.documentElement.lang,'uz');
  const select=second.document.querySelector('.languageBar select');select.value='ru';select.dispatchEvent(new second.window.Event('change'));
  assert.equal(second.storage.get('relyqo_language'),'ru');assert.equal(second.navigations[0],'/me?lang=ru#account');
  assert.equal(second.requests.at(-1).options.keepalive,true);
  const third=await setup({query:'',saved:'ru'});assert.equal(third.document.title,'Профиль');
  assert.equal(third.requests.length,0);
});

test('cookie preserves the language when browser storage is blocked; invalid language does not override it',async()=>{
  const x=await setup({query:'?lang=invalid',cookie:'relyqo_language=uz',blocked:true});
  assert.equal(x.document.documentElement.lang,'uz');assert.equal(x.document.title,'Profil');
});

test('translation covers dynamic text, accessible hints and titles without altering authored content or values',async()=>{
  const x=await setup({html:'<!doctype html><html><head><title>Профиль</title></head><body><h1> Профиль </h1><p data-user-content>Название Кафе</p><textarea data-user-content placeholder="Название организации">Название Кафе</textarea><input value="Название Кафе"><div id="later"></div></body></html>'});
  assert.equal(x.document.querySelector('h1').textContent,' Profil ');
  assert.equal(x.document.querySelector('[data-user-content]').textContent,'Название Кафе');
  assert.equal(x.document.querySelector('textarea').value,'Название Кафе');
  assert.equal(x.document.querySelector('textarea').getAttribute('placeholder'),dictionary['Название организации']);
  assert.equal(x.document.querySelector('input').value,'Название Кафе');
  x.document.getElementById('later').innerHTML='<button title="Повторить">Не удалось загрузить организации</button>';
  x.document.title='Сотрудник — RELYQO';await settle();
  assert.equal(x.document.title,'Xodim — RELYQO');assert.equal(x.document.querySelector('#later button').textContent,dictionary['Не удалось загрузить организации']);
  x.document.querySelector('#later button').setAttribute('aria-label','Открыть приложение');await settle();
  assert.equal(x.document.querySelector('#later button').getAttribute('aria-label'),dictionary['Открыть приложение']);
  assert.equal(x.document.querySelector('.languageBar option').textContent,'Русский');
});

test('validation messages follow the selected language and clear when a field is edited',async()=>{
  const x=await setup({html:'<!doctype html><html><head></head><body><form><input required type="email"></form></body></html>'});
  const input=x.document.querySelector('input');let message='';const validity={valueMissing:true,customError:false};
  Object.defineProperties(input,{validity:{value:validity},validationMessage:{get:()=>message}});
  input.setCustomValidity=text=>{message=text;validity.customError=Boolean(text);};
  input.dispatchEvent(new x.window.Event('invalid',{bubbles:true}));assert.equal(message,'Ushbu maydonni to‘ldiring.');
  input.dispatchEvent(new x.window.Event('input',{bubbles:true}));assert.equal(message,'');
  validity.valueMissing=false;validity.typeMismatch=true;input.dispatchEvent(new x.window.Event('invalid',{bubbles:true}));assert.equal(message,'To‘g‘ri email manzilini kiriting.');
  input.dispatchEvent(new x.window.Event('change',{bubbles:true}));input.setCustomValidity('Custom business rule');
  input.dispatchEvent(new x.window.Event('invalid',{bubbles:true}));assert.equal(message,'Custom business rule');
});

test('a missing dictionary retries once and reloads a consistent Russian page',async()=>{
  const x=await setup({failed:true});assert.equal(x.requests.length,2);assert.equal(x.navigations[0],'/me?lang=ru#account');assert.equal(x.storage.get('relyqo_language'),'ru');
});

const protectedContent='script,style,code,[data-user-content],[translate="no"],.languageBar,#placeName,#placeAddress,#organizationTitle,#organizationLead,#username,#name,#description,#assistantAnswer,#aiText,#analysis,#photoAnalysis';
function untranslated(document) {
  const missing=[];
  function visit(node) {
    if(node.nodeType===3&&node.parentElement&&!node.parentElement.closest(protectedContent)&&/[А-Яа-яЁё]/.test(node.nodeValue))missing.push(node.nodeValue.trim());
    if(node.nodeType===1&&!node.closest(protectedContent))for(const attr of ['placeholder','aria-label','title','alt'])if(/[А-Яа-яЁё]/.test(node.getAttribute(attr)||''))missing.push(node.getAttribute(attr));
    for(const child of node.childNodes||[])visit(child);
  }
  visit(document.documentElement);return [...new Set(missing)];
}
for(const file of fs.readdirSync('app/static').filter(file=>file.endsWith('.html')))test(file+' has complete Uzbek static copy and initializes language before page scripts',async()=>{
  const html=read(file),x=await setup({html});
  const first=x.document.querySelector('script');assert.match(first.getAttribute('src'),/^\/static\/i18n.js\?v=/);assert(!first.hasAttribute('defer'));
  assert.deepEqual(untranslated(x.document),[],file);
});

test('all runtime JavaScript interface fragments have Uzbek translations',async()=>{
  const x=await setup(),missing=new Map();
  function check(value,file) {
    if(typeof value!=='string'||!/[А-Яа-яЁё]/.test(value)||value.length<2)return;
    // CSS, regular-expression strings and search/transliteration keys are implementation data.
    if(value.includes('[А-Я')||value==='Til / Язык'||value==='Русский'||value.includes('replace(/'))return;
    const pieces=value.includes('<')?value.replace(/<[^>]*>/g,'|').split('|'):[value];
    for(let piece of pieces){piece=piece.trim();if(!piece||!/[А-Яа-яЁё]/.test(piece))continue;if(/[А-Яа-яЁё]/.test(x.window.relyqoT(piece)))missing.set(piece,file);}
  }
  function walk(node,file) {
    if(!node||typeof node!=='object')return;
    if(node.type==='Literal')check(node.value,file);
    if(node.type==='TemplateElement')check(node.value.cooked,file);
    for(const [key,value]of Object.entries(node))if(key!=='value'){
      if(Array.isArray(value))value.forEach(child=>walk(child,file));else if(value&&typeof value==='object')walk(value,file);
    }
  }
  for(const file of fs.readdirSync('app/static').filter(file=>/\.(js|html)$/.test(file))){
    if(file==='i18n.js')continue;
    const source=file.endsWith('.js')?read(file):[...parseHTML(read(file)).document.querySelectorAll('script:not([src])')].map(s=>s.textContent).join('\n');
    walk(acorn.parse(source,{ecmaVersion:'latest'}),file);
  }
  assert.deepEqual([...missing],[]);
});

test('bilingual editor previews translate labels while preserving both authored versions',async()=>{
  const x=await setup({html:read('admin-editor.html')});
  const state={content:{ru:{title:'Название Кафе',hint:'Русское описание'},uz:{title:'O‘zbekcha nom',hint:'O‘zbekcha izoh'}},categories:[],groups:{OTHER:'Другие услуги'},version:1,ai_configured:false};
  x.context.fetch=async()=>({ok:true,json:async()=>state});vm.runInNewContext(read('admin-editor.js'),x.context);await settle();
  assert.equal(x.document.getElementById('previewTitleRu').textContent,'Название Кафе');
  assert.equal(x.document.getElementById('homeChanges').textContent,dictionary['Опубликованная версия']);
  x.document.getElementById('titleRu').value='Новое название';x.document.getElementById('homeForm').dispatchEvent(new x.window.Event('input'));await settle();
  const changes=x.document.getElementById('homeChanges').textContent;assert.match(changes,/Oldin: Название Кафе/);assert.match(changes,/Keyin: Новое название/);
});
